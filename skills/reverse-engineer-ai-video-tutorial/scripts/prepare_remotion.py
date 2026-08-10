"""Prepare a lean Remotion project backed by one shared toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "_runtime"))

from file_lock import acquire as acquire_file_lock  # noqa: E402
from remotion_scaffold import REMOTION_VERSION, SCAFFOLD_FILES, SHARED_PACKAGE  # noqa: E402
from tutorial_re.tools import probe_tool, require_tool, runtime_data_root  # noqa: E402


TOOLCHAIN_RECEIPT = ".remotion-toolchain-receipt.json"
PROJECT_RECEIPT = ".tutorial-re-remotion-project.json"
PACKAGE_INPUT = SCRIPT_DIR / "remotion_toolchain_package.json"
LOCK_INPUT = SCRIPT_DIR / "remotion_toolchain_package-lock.json"
REVIEWED_PACKAGE_SHA256 = "407ea7989c40c671b7ca2c1d9efa4911019d8201e00cd2393c7be3e0f1e0ddbf"
REVIEWED_LOCK_SHA256 = "eddf7fb592ffae415d00f81391cf9843d7cefa3b6b7fc56bae814d0c7284a53e"
LOCK_ATTEMPTS = 240


def _run(command: list[str], *, cwd: Path, log_name: str, env: dict[str, str] | None = None) -> None:
    log_path = cwd / log_name
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n\n" + (completed.stdout or "") + (completed.stderr or ""),
        encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}); see {log_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare one lean Remotion project with a shared toolchain.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--destination", default="")
    parser.add_argument("--toolchain-root", type=Path)
    parser.add_argument(
        "--setup-shared",
        action="store_true",
        help="explicitly install the shared Remotion toolchain with npm",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.expanduser().resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"workspace root missing: {repo_root}")
    _validate_source_id(args.source_id)
    destination = args.destination or str(Path("videos") / args.source_id / "remotion")
    destination_path = Path(destination).expanduser()
    raw_target = destination_path if destination_path.is_absolute() else repo_root / destination_path
    _reject_symlink_components(repo_root, raw_target)
    if raw_target.exists() and raw_target.is_symlink():
        raise SystemExit(f"destination symlink not allowed: {raw_target}")
    target = raw_target.resolve()
    _validate_containment(repo_root, target)

    toolchain_root = (args.toolchain_root.expanduser() if args.toolchain_root else runtime_data_root() / "remotion" / REMOTION_VERSION).resolve()
    _validate_toolchain_root(toolchain_root)
    package = _ensure_shared_toolchain(toolchain_root, setup=args.setup_shared)
    _scaffold_project(target, toolchain_root, package)
    _ensure_node_modules_link(target, toolchain_root / "node_modules")

    package_path = target / "package.json"
    project_package = json.loads(package_path.read_text(encoding="utf-8"))
    if project_package.get("dependencies", {}).get("remotion") != package.get("dependencies", {}).get("remotion"):
        raise RuntimeError("project Remotion version does not match the shared toolchain")
    _check_engine("node", project_package.get("engines", {}).get("node", ">=18.17.0"))
    _check_engine("npm", project_package.get("engines", {}).get("npm", ">=9.0.0"))
    npm = require_tool("npm")
    _run([*npm, "run", "typecheck"], cwd=target, log_name="framework-typecheck.log")
    _run([*npm, "run", "compositions"], cwd=target, log_name="framework-check.log")

    smoke_parent = target / ".prepare-smoke"
    if smoke_parent.exists() and smoke_parent.is_symlink():
        raise RuntimeError(f"smoke directory symlink not allowed: {smoke_parent}")
    smoke_parent.mkdir(parents=True, exist_ok=True)
    smoke_dir = smoke_parent / uuid.uuid4().hex
    smoke_dir.mkdir()
    _validate_containment(target, smoke_dir)
    smoke_output = smoke_dir / "framework-smoke.mp4"
    try:
        smoke_env = os.environ.copy()
        smoke_env["REMOTION_ALLOW_UNVERIFIED_SMOKE"] = "1"
        remotion = target / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
        if not remotion.is_file():
            raise RuntimeError("shared Remotion binary missing; rerun with --setup-shared")
        _run(
            [str(remotion), "render", "src/index.ts", "FrameworkSmoke", str(smoke_output)],
            cwd=target,
            env=smoke_env,
            log_name="framework-render-check.log",
        )
        if not smoke_output.is_file():
            raise RuntimeError(f"Remotion smoke render missing: {smoke_output}")
    finally:
        if smoke_dir.exists() and not smoke_dir.is_symlink():
            shutil.rmtree(smoke_dir)
        try:
            smoke_parent.rmdir()
        except OSError:
            pass

    writer = SCRIPT_DIR / "write_framework_readiness.py"
    subprocess.run(
        [
            sys.executable,
            str(writer),
            "--package",
            "package.json",
            "--output",
            "framework-readiness.json",
            "--project-root",
            target.relative_to(repo_root).as_posix(),
            "--toolchain-root",
            str(toolchain_root),
            "--receipt",
            str(toolchain_root / TOOLCHAIN_RECEIPT),
        ],
        cwd=target,
        check=True,
    )
    _mark_project_ready(target)
    print(f"framework-ready: {_console_text(target)}")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _toolchain_receipt(root: Path) -> dict[str, object]:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    lockfile = root / "package-lock.json"
    _reviewed_package_and_lock()
    return {
        "schema_version": 1,
        "framework": "Remotion",
        "state": "ready",
        "remotion_version": REMOTION_VERSION,
        "package_sha256": _sha256(root / "package.json"),
        "lock_sha256": _sha256(lockfile),
        "package_input_sha256": _sha256(PACKAGE_INPUT),
        "lock_input_sha256": _sha256(LOCK_INPUT),
        "package": package.get("dependencies", {}),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def _inspect_toolchain(root: Path, *, require_receipt: bool) -> dict[str, object]:
    package_path = root / "package.json"
    lockfile = root / "package-lock.json"
    modules = root / "node_modules"
    receipt_path = root / TOOLCHAIN_RECEIPT
    if not root.is_dir() or root.is_symlink():
        return {"ready": False, "state": "setup_required", "package": {}, "error": "toolchain root missing"}
    if not package_path.is_file() or not lockfile.is_file() or not modules.is_dir():
        return {"ready": False, "state": "broken", "package": {}, "error": "package, lockfile, or node_modules missing"}
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ready": False, "state": "broken", "package": {}, "error": f"invalid package.json: {exc}"}
    if package.get("dependencies", {}).get("remotion") != REMOTION_VERSION:
        return {"ready": False, "state": "broken", "package": package, "error": "Remotion version mismatch"}
    try:
        reviewed_package, _ = _reviewed_package_and_lock()
    except (OSError, ValueError, RuntimeError) as exc:
        return {"ready": False, "state": "broken", "package": package, "error": str(exc)}
    if package != reviewed_package:
        return {"ready": False, "state": "broken", "package": package, "error": "toolchain package differs from reviewed package input"}
    binary = modules / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
    if not binary.is_file():
        return {"ready": False, "state": "broken", "package": package, "error": "Remotion CLI binary missing"}
    if require_receipt:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ready": False, "state": "broken", "package": package, "error": "toolchain receipt missing or invalid"}
        if (
            receipt.get("state") != "ready"
            or receipt.get("remotion_version") != REMOTION_VERSION
            or receipt.get("package_sha256") != _sha256(package_path)
            or receipt.get("lock_sha256") != _sha256(lockfile)
            or receipt.get("package_input_sha256") != _sha256(PACKAGE_INPUT)
            or receipt.get("lock_input_sha256") != _sha256(LOCK_INPUT)
        ):
            return {"ready": False, "state": "broken", "package": package, "error": "toolchain receipt does not match files"}
    return {"ready": True, "state": "ready", "package": package, "error": None}


def _recover_verified_generation(root: Path) -> None:
    if root.exists():
        return
    candidates = sorted(root.parent.glob(f".{root.name}.previous-*"), key=lambda item: item.stat().st_mtime, reverse=True)
    for candidate in candidates:
        inspected = _inspect_toolchain(candidate, require_receipt=True)
        if inspected["ready"]:
            os.replace(candidate, root)
            return


def _mark_project_ready(target: Path) -> None:
    marker = target / PROJECT_RECEIPT
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["state"] = "ready"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(marker, payload)


def _ensure_shared_toolchain(root: Path, *, setup: bool) -> dict[str, object]:
    if root.exists() and root.is_symlink():
        raise SystemExit(f"shared toolchain symlink not allowed: {root}")
    lock = acquire_file_lock(
        root.parent / f".{root.name}.lock",
        f"Remotion toolchain setup for {root}",
        attempts=LOCK_ATTEMPTS,
        delay=0.1,
    )
    try:
        _recover_verified_generation(root)
        current = _inspect_toolchain(root, require_receipt=True)
        if current["ready"]:
            return current["package"]
        if not setup:
            raise RuntimeError(
                f"shared Remotion toolchain is {current['state']} at {root}; "
                "request setup approval, then rerun with --setup-shared"
            )

        stage = root.parent / f".{root.name}.stage-{uuid.uuid4().hex}"
        backup: Path | None = None
        published_root = False
        try:
            stage.mkdir(parents=True, exist_ok=False)
            package_path = stage / "package.json"
            reviewed_package, _ = _reviewed_package_and_lock()
            package_path.write_text(json.dumps(reviewed_package, indent=2) + "\n", encoding="utf-8")
            shutil.copy2(LOCK_INPUT, stage / "package-lock.json")
            _check_engine("node", str(reviewed_package["engines"]["node"]))
            _check_engine("npm", str(reviewed_package["engines"]["npm"]))
            npm = require_tool("npm")
            _run([*npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=stage, log_name="toolchain-install.log")
            _run(
                [*require_tool("node"), "-e", "require('remotion'); require('@remotion/cli');"],
                cwd=stage,
                log_name="toolchain-import-probe.log",
            )
            remotion_bin = stage / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
            if not remotion_bin.is_file():
                raise RuntimeError(f"staged Remotion binary missing: {remotion_bin}")
            _run([str(remotion_bin), "--help"], cwd=stage, log_name="toolchain-cli-probe.log")
            _run(
                [
                    *require_tool("node"),
                    "-e",
                    f"const p=require('@remotion/cli/package.json'); if (p.version !== '{REMOTION_VERSION}') process.exit(2); console.log(p.version);",
                ],
                cwd=stage,
                log_name="toolchain-version-probe.log",
            )
            receipt = _toolchain_receipt(stage)
            _write_json(stage / TOOLCHAIN_RECEIPT, receipt)
            staged = _inspect_toolchain(stage, require_receipt=True)
            if not staged["ready"]:
                raise RuntimeError(f"staged Remotion toolchain failed verification: {staged['error']}")

            if root.exists():
                backup = root.parent / f".{root.name}.previous-{uuid.uuid4().hex}"
                os.replace(root, backup)
            os.replace(stage, root)
            published_root = True
            published = _inspect_toolchain(root, require_receipt=True)
            if not published["ready"]:
                raise RuntimeError(f"published Remotion toolchain failed verification: {published['error']}")
            return published["package"]
        except BaseException:
            if stage.exists() and not stage.is_symlink():
                shutil.rmtree(stage, ignore_errors=True)
            if published_root and root.exists() and not root.is_symlink():
                failed = root.parent / f".{root.name}.failed-{uuid.uuid4().hex}"
                os.replace(root, failed)
            if backup is not None and backup.exists():
                if not root.exists():
                    os.replace(backup, root)
                restored = _inspect_toolchain(root, require_receipt=True)
                if not restored["ready"]:
                    raise RuntimeError(f"prior Remotion toolchain failed restoration: {restored['error']}")
            raise
    finally:
        lock.release()


def _scaffold_project(target: Path, toolchain_root: Path, package: dict[str, object]) -> None:
    if target.exists() and not target.is_dir():
        raise SystemExit(f"destination is not a directory: {target}")
    marker = target / PROJECT_RECEIPT
    existing_entries = list(target.iterdir()) if target.is_dir() else []
    if existing_entries and not marker.is_file():
        raise RuntimeError(
            f"destination is nonempty and not an owned Remotion project: {target}; "
            "choose a new directory or add the ownership marker after review"
        )
    target.mkdir(parents=True, exist_ok=True)
    if marker.is_file():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"invalid Remotion project ownership marker: {marker}") from exc
        if previous.get("framework") != "Remotion" or previous.get("remotion_version") != REMOTION_VERSION:
            raise RuntimeError(f"Remotion project ownership marker does not match this toolchain: {marker}")
        if Path(str(previous.get("toolchain_root") or "")).resolve() != toolchain_root.resolve():
            raise RuntimeError(f"Remotion project is bound to another shared toolchain: {marker}")
    package_lock = target / "package-lock.json"
    if package_lock.exists() and not package_lock.is_symlink():
        raise RuntimeError(
            f"project-local package-lock.json is not supported by the shared toolchain: {package_lock}; "
            "use a fresh project directory or remove the old generated project"
        )
    for relative, content in SCAFFOLD_FILES.items():
        path = target / relative
        if path.exists() and path.is_symlink():
            raise RuntimeError(f"scaffold path symlink not allowed: {path}")
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _write_json(
        marker,
        {
            "schema_version": 1,
            "framework": "Remotion",
            "state": "provisioning",
            "remotion_version": REMOTION_VERSION,
            "toolchain_root": str(toolchain_root),
            "toolchain_receipt": str(toolchain_root / TOOLCHAIN_RECEIPT),
            "project_package_sha256": _sha256(target / "package.json"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _reviewed_package_and_lock() -> tuple[dict[str, object], dict[str, object]]:
    if _sha256(PACKAGE_INPUT) != REVIEWED_PACKAGE_SHA256 or _sha256(LOCK_INPUT) != REVIEWED_LOCK_SHA256:
        raise RuntimeError("reviewed Remotion package/lock input hash does not match the code-bound review")
    try:
        package = json.loads(PACKAGE_INPUT.read_text(encoding="utf-8"))
        lock = json.loads(LOCK_INPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"reviewed Remotion package/lock input missing or invalid: {exc}") from exc
    if package != SHARED_PACKAGE:
        raise RuntimeError("reviewed Remotion package input differs from the code manifest")
    root = lock.get("packages", {}).get("") if isinstance(lock.get("packages"), dict) else None
    if not isinstance(root, dict):
        raise RuntimeError("reviewed Remotion lock input has no root package")
    for field in ("name", "version", "dependencies", "devDependencies"):
        if root.get(field) != package.get(field):
            raise RuntimeError(f"reviewed Remotion lock root differs from package input: {field}")
    return package, lock


def _ensure_node_modules_link(project: Path, shared_node_modules: Path) -> None:
    link = project / "node_modules"
    shared_node_modules = shared_node_modules.resolve()
    if not shared_node_modules.is_dir():
        raise RuntimeError(f"shared node_modules missing: {shared_node_modules}")
    if link.exists() or link.is_symlink():
        if Path(os.path.realpath(link)).resolve() != shared_node_modules:
            raise RuntimeError(f"project node_modules is not linked to the shared toolchain: {link}")
        return
    try:
        os.symlink(shared_node_modules, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        command = f'cmd /d /c mklink /J "{link}" "{shared_node_modules}"'
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError(f"could not create shared node_modules junction: {completed.stderr or completed.stdout}")


def _validate_source_id(source_id: str) -> None:
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if (
        not source_id
        or source_id in {".", ".."}
        or any(ord(char) < 32 for char in source_id)
        or any(char in '<>:"/\\|?*' for char in source_id)
        or source_id.endswith((".", " "))
        or source_id.casefold().split(".", 1)[0] in reserved
    ):
        raise SystemExit("source-id must be one safe workspace path component")


def _validate_toolchain_root(root: Path) -> None:
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise SystemExit(f"unsafe shared toolchain root: {root}")
    _reject_symlink_components(Path(root.anchor), root)


def _validate_containment(root: Path, target: Path) -> None:
    root = root.resolve()
    target = target.resolve()
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


def _check_engine(name: str, requirement: str) -> None:
    probe = probe_tool(name)
    if not probe.available:
        raise RuntimeError(f"{name} unavailable: {probe.error or 'probe failed'}")
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", probe.version or "")
    required = re.search(r">=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", requirement or "")
    current_tuple = tuple(int(match.group(index) or 0) for index in (1, 2, 3)) if match else None
    required_tuple = tuple(int(required.group(index) or 0) for index in (1, 2, 3)) if required else None
    if not current_tuple or not required_tuple or current_tuple < required_tuple:
        raise RuntimeError(f"{name} {probe.version or '<unknown>'} fails engines.{name}: {requirement}")


def _console_text(value: object) -> str:
    text = str(value)
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
