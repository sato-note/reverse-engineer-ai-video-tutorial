"""Render an approved native HyperFrames project and write tamper-evident proof."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "_runtime"))

from prepare_hyperframes import (  # noqa: E402
    CHECK_RECEIPT,
    READINESS,
    _sha256,
    _write_json,
)
from tutorial_re.tools import probe_tool  # noqa: E402


APPROVAL = ".tutorial-re-hyperframes-approval.json"
RENDER_RECEIPT = ".tutorial-re-hyperframes-render-receipt.json"
RENDER_TIMEOUT_SECONDS = 600


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render approved native HyperFrames output.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", default="out.mp4")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"HyperFrames project missing: {project}")
    output = (project / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output).expanduser().resolve()
    _validate_containment(project, output)
    if not args.approved:
        report = {"framework": "HyperFrames", "status": "approval_required", "next_action": "run again with explicit preview approval and --approved"}
        _print(report, args.json)
        return 2

    readiness_path = project / READINESS
    check_path = project / CHECK_RECEIPT
    if not readiness_path.is_file() or not check_path.is_file():
        raise SystemExit("HyperFrames readiness/check receipt missing; run prepare_hyperframes.py first")
    readiness = _read_json(readiness_path)
    check = _read_json(check_path)
    if readiness.get("status") != "ready" or check.get("status") != "pass":
        raise SystemExit("HyperFrames check is not ready; repair project and rerun check")
    cli = probe_tool("hyperframes")
    ffprobe = probe_tool("ffprobe")
    if not cli.available or not ffprobe.available:
        raise SystemExit("direct HyperFrames CLI and FFprobe required; install after approval")

    approval = {
        "schema_version": 1,
        "framework": "HyperFrames",
        "status": "approved",
        "reviewer": args.reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "project_marker_sha256": _sha256(project / "hyperframes.json"),
        "check_receipt_sha256": _sha256(check_path),
    }
    _write_json(project / APPROVAL, approval)
    render_log = project / "hyperframes-render.log"
    command = [*cli.command, "render", "--quality", "high", "--output", str(output)]
    try:
        completed = subprocess.run(
            command,
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        render_log.write_text(
            "$ " + " ".join(command) + f"\n\nTIMEOUT after {RENDER_TIMEOUT_SECONDS}s\n{exc}",
            encoding="utf-8",
        )
        report = {"framework": "HyperFrames", "status": "broken", "error": "native render timed out", "render_log": str(render_log)}
        _print(report, args.json)
        return 2
    render_log.write_text("$ " + " ".join(command) + "\n\n" + (completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode or not output.is_file() or output.stat().st_size == 0:
        report = {"framework": "HyperFrames", "status": "broken", "error": "native render failed or output empty", "render_log": str(render_log)}
        _print(report, args.json)
        return 2

    probe_command = [*ffprobe.command, "-v", "error", "-show_format", "-of", "json", str(output)]
    probe = subprocess.run(probe_command, cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if probe.returncode:
        raise RuntimeError("FFprobe rejected native HyperFrames output")
    render_receipt = {
        "schema_version": 1,
        "framework": "HyperFrames",
        "status": "pass",
        "run_id": os.environ.get("HYPERFRAMES_RUN_ID") or uuid.uuid4().hex,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "output": {"path": str(output.relative_to(project)).replace("\\", "/"), "sha256": _sha256(output), "bytes": output.stat().st_size},
        "ffprobe": json.loads(probe.stdout or "{}"),
        "render_log": {"path": "hyperframes-render.log", "sha256": _sha256(render_log)},
        "approval": {"path": APPROVAL, "sha256": _sha256(project / APPROVAL)},
        "project_marker_sha256": _sha256(project / "hyperframes.json"),
        "check_receipt_sha256": _sha256(check_path),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(project / RENDER_RECEIPT, render_receipt)
    report = {"framework": "HyperFrames", "status": "ready", "render_receipt": RENDER_RECEIPT, "output_sha256": render_receipt["output"]["sha256"]}
    _print(report, args.json)
    return 0


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _validate_containment(root: Path, target: Path) -> None:
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"output escapes HyperFrames project: {target}") from exc


def _print(report: dict[str, object], as_json: bool) -> None:
    print(json.dumps(report, indent=2) if as_json else f"framework: HyperFrames\nstatus: {report['status']}\nnext_action: {report.get('next_action')}")


if __name__ == "__main__":
    raise SystemExit(main())
