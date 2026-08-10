"""Initialize and check one native HyperFrames project without owning its runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "_runtime"))

from tutorial_re.tools import ToolResolution, probe_tool  # noqa: E402
from file_lock import acquire as acquire_file_lock  # noqa: E402


READINESS = ".tutorial-re-hyperframes-readiness.json"
CHECK_RECEIPT = ".tutorial-re-hyperframes-check-receipt.json"
LOCK_ATTEMPTS = 240
PUBLISH_ATTEMPTS = 60
PUBLISH_DELAY = 0.25


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a native HyperFrames project.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--destination", default="")
    parser.add_argument("--setup-approved", action="store_true", help="allow approved npx-based CLI setup/discovery")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.expanduser().resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"workspace root missing: {repo_root}")
    _validate_source_id(args.source_id)
    raw = Path(args.destination).expanduser() if args.destination else Path("videos") / args.source_id / "hyperframes"
    raw_target = raw if raw.is_absolute() else repo_root / raw
    _reject_symlink_components(repo_root, raw_target)
    if raw_target.exists() and raw_target.is_symlink():
        raise SystemExit(f"HyperFrames destination symlink not allowed: {raw_target}")
    target = raw_target.resolve()
    _validate_containment(repo_root, target)
    if target.exists() and target.is_symlink():
        raise SystemExit(f"HyperFrames destination symlink not allowed: {target}")

    cli = probe_tool("hyperframes", allow_network=args.setup_approved)
    if cli.available and cli.source == "npx" and cli.version:
        match = re.search(r"(\d+\.\d+\.\d+)", cli.version)
        if match:
            cli = ToolResolution(
                cli.name,
                (cli.command[0], f"hyperframes@{match.group(1)}"),
                cli.path,
                cli.source,
                match.group(1),
                cli.verified,
                cli.error,
            )
    if not cli.available:
        report = {
            "framework": "HyperFrames",
            "status": "setup_required",
            "approval_required": True,
            "next_action": "install or enable the official HyperFrames CLI after approval; rerun with --setup-approved",
            "cli": cli.as_dict(),
        }
        _print(report, args.json)
        return 2

    lock = acquire_file_lock(
        target.parent / f".{target.name}.lock",
        f"HyperFrames setup for {target}",
        attempts=LOCK_ATTEMPTS,
        delay=0.1,
    )
    try:
        marker = target / "hyperframes.json"
        entries = list(target.iterdir()) if target.is_dir() else []
        if entries and not marker.is_file():
            raise SystemExit(
                f"HyperFrames destination is nonempty and not an owned project: {target}; "
                "choose a new directory or resume a directory containing hyperframes.json"
            )
        if marker.is_file():
            report = _check_existing_project(target, repo_root, cli)
            _print(report, args.json)
            return 0 if report["status"] == "ready" else 2

        stage = target.parent / f".{target.name}.stage-{uuid.uuid4().hex}"
        target.parent.mkdir(parents=True, exist_ok=True)
        init_log = target.parent / f".{target.name}.init-{uuid.uuid4().hex}.log"
        try:
            _run(
                [*cli.command, "init", stage.name, "--non-interactive", "--example=blank"],
                target.parent,
                init_log,
                timeout_seconds=180,
            )
            if not stage.is_dir():
                raise RuntimeError(f"HyperFrames init did not create staging project: {stage}")
            os.replace(init_log, stage / "hyperframes-init.log")
            _verify_project(stage)
            report = _check_project(stage, repo_root, cli, target_relative=target.relative_to(repo_root))
            if report["status"] != "ready":
                raise RuntimeError(str(report.get("error") or "HyperFrames check failed"))
            if target.exists():
                target.rmdir()
            _publish_stage(stage, target)
            report["project_root"] = str(target.relative_to(repo_root)).replace("\\", "/")
            _rewrite_project_paths(target, report)
            _print(report, args.json)
            return 0
        except BaseException:
            if init_log.exists() and not init_log.is_symlink():
                init_log.unlink(missing_ok=True)
            if stage.exists() and not stage.is_symlink():
                shutil.rmtree(stage, ignore_errors=True)
            raise
    finally:
        lock.release()


def _run(command: list[str], cwd: Path, log_path: Path, *, timeout_seconds: int) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text("$ " + " ".join(command) + f"\n\nTIMEOUT after {timeout_seconds}s\n{exc}", encoding="utf-8")
        raise RuntimeError(f"HyperFrames command timed out after {timeout_seconds}s; see {log_path}") from exc
    log_path.write_text("$ " + " ".join(command) + "\n\n" + (completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"HyperFrames command failed ({completed.returncode}); see {log_path}")


def _publish_stage(stage: Path, target: Path) -> None:
    last_error: OSError | None = None
    for attempt in range(PUBLISH_ATTEMPTS):
        try:
            os.replace(stage, target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(PUBLISH_DELAY)
    raise RuntimeError(
        f"HyperFrames staging directory remained locked after {PUBLISH_ATTEMPTS * PUBLISH_DELAY:.1f}s; "
        "retry after native CLI processes exit"
    ) from last_error


def _check_existing_project(target: Path, repo_root: Path, cli) -> dict[str, object]:
    try:
        _verify_project(target)
    except RuntimeError as exc:
        return {"framework": "HyperFrames", "status": "broken", "error": str(exc), "next_action": "repair native project and rerun"}
    return _check_project(target, repo_root, cli, target_relative=target.relative_to(repo_root))


def _check_project(project: Path, repo_root: Path, cli, *, target_relative: Path) -> dict[str, object]:
    check_log = project / "hyperframes-check.log"
    try:
        _run([*cli.command, "check"], project, check_log, timeout_seconds=180)
        status = "ready"
        error = None
    except RuntimeError as exc:
        status = "broken"
        error = str(exc)
    check_receipt = None
    if status == "ready":
        check_receipt = _write_check_receipt(project, repo_root, target_relative, cli, check_log)
    readiness = {
        "schema_version": 1,
        "framework": "HyperFrames",
        "status": status,
        "readiness_scope": "framework_project_check",
        "cli": cli.as_dict(),
        "project_root": str(target_relative).replace("\\", "/"),
        "project_marker": "hyperframes.json",
        "check_command": _command_text([*cli.command, "check"]),
        "preview_command": _command_text([*cli.command, "preview"]),
        "render_command": _command_text([*cli.command, "render", "--quality", "high", "--output", "out.mp4"]),
        "preview_approval": "required before render",
        "check_receipt": CHECK_RECEIPT if check_receipt else None,
        "native_provenance": ["hyperframes-check.log", CHECK_RECEIPT] if check_receipt else [],
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(project / READINESS, readiness)
    return {**readiness, "error": error, "next_action": None if status == "ready" else "repair the native HyperFrames project and rerun check"}


def _rewrite_project_paths(project: Path, report: dict[str, object]) -> None:
    _write_json(project / READINESS, {**json.loads((project / READINESS).read_text(encoding="utf-8")), "project_root": report["project_root"]})


def _verify_project(project: Path) -> None:
    marker = project / "hyperframes.json"
    if not marker.is_file():
        raise RuntimeError(f"HyperFrames native project marker missing: {marker}")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"HyperFrames native project marker invalid: {marker}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"HyperFrames native project marker must be an object: {marker}")
    if not (project / "index.html").is_file():
        raise RuntimeError(f"HyperFrames index.html missing: {project}")


def _write_check_receipt(project: Path, repo_root: Path, target_relative: Path, cli, log_path: Path) -> dict[str, object]:
    marker = project / "hyperframes.json"
    source_files = [path for path in sorted(project.rglob("*")) if path.is_file() and path.name not in {READINESS, CHECK_RECEIPT, "hyperframes-check.log"}]
    receipt = {
        "schema_version": 1,
        "framework": "HyperFrames",
        "status": "pass",
        "run_id": os.environ.get("HYPERFRAMES_RUN_ID") or uuid.uuid4().hex,
        "cli": cli.as_dict(),
        "project_root": str(target_relative).replace("\\", "/"),
        "project_marker": {"path": "hyperframes.json", "sha256": _sha256(marker)},
        "source_files": [{"path": str(path.relative_to(project)).replace("\\", "/"), "sha256": _sha256(path)} for path in source_files],
        "command": _command_text([*cli.command, "check"]),
        "exit_code": 0,
        "log": {"path": "hyperframes-check.log", "sha256": _sha256(log_path)},
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(project / CHECK_RECEIPT, receipt)
    return receipt


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print(report: dict[str, object], as_json: bool) -> None:
    print(json.dumps(report, indent=2) if as_json else f"framework: HyperFrames\nstatus: {report['status']}\nnext_action: {report.get('next_action')}")


def _validate_source_id(source_id: str) -> None:
    if not source_id or source_id in {".", ".."} or any(char in '<>:"/\\|?*' for char in source_id):
        raise SystemExit("source-id must be one safe workspace path component")


def _validate_containment(root: Path, target: Path) -> None:
    if target == root:
        raise SystemExit("destination must be below workspace root")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"destination escapes workspace: {target}") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.exists() and current.is_symlink():
            raise SystemExit(f"workspace symlink escape: {current}")


def _reject_symlink_components(root: Path, target: Path) -> None:
    root = root.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"destination escapes workspace: {target}") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.exists() and current.is_symlink():
            raise SystemExit(f"workspace symlink not allowed: {current}")


if __name__ == "__main__":
    raise SystemExit(main())
