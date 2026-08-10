"""Exact local-framework adapter plans; external runtimes remain authoritative."""

from __future__ import annotations

import re
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .tools import probe_tool, runtime_data_root


def normalize_framework(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    if key in {"remotion", "remotion-studio"}:
        return "remotion"
    if key in {"hyperframes", "hyperframes-cli", "hyperframes-by-heygen"}:
        return "hyperframes"
    return key


def build_adapter_plan(source_id: str, route: dict[str, Any]) -> dict[str, Any]:
    framework = normalize_framework(route.get("tool"))
    project_root = (Path("videos") / source_id / (framework or "framework")).as_posix()
    if framework == "remotion":
        toolchain_state = _remotion_toolchain_state()
        return {
            "adapter": "remotion",
            "framework": "Remotion",
            "state": toolchain_state,
            "project_root": project_root,
            "setup_command": "python <skill-root>/scripts/prepare_remotion.py --repo-root <workspace> --source-id <source-id> --setup-shared",
            "preview_command": "npm run studio",
            "check_command": "npm run compositions",
            "render_command": "npm run render:smoke",
            "native_provenance": "Remotion render log + MP4 hash",
            "delivery_fields": {
                "shared_framework_project_root": project_root,
                "studio_command": "npm run studio",
                "studio_launcher": "npm run studio",
                "single_project_for_source": True,
                "editable_studio_required": True,
                "rendered_checkpoint_comparison_required": True,
            },
        }
    if framework == "hyperframes":
        resolution = probe_tool("hyperframes")
        state = "ready" if resolution.available else "setup_required"
        return {
            "adapter": "hyperframes",
            "framework": "HyperFrames",
            "state": state,
            "project_root": project_root,
            "cli": resolution.as_dict(),
            "setup_command": "python <skill-root>/scripts/prepare_hyperframes.py --repo-root <workspace> --source-id <source-id> --setup-approved",
            "resume_command": "<recorded HyperFrames CLI> check",
            "preview_command": "<recorded HyperFrames CLI> preview",
            "check_command": "<recorded HyperFrames CLI> check",
            "render_command": "<recorded HyperFrames CLI> render --quality high --output out.mp4",
            "approval_gate": "preview approval required before render",
            "native_provenance": "HyperFrames check/preview/render logs + MP4 hash",
            "delivery_fields": {
                "shared_framework_project_root": project_root,
                "framework_adapter": "hyperframes",
                "project_marker": f"{project_root}/hyperframes.json",
                "readiness_record": f"{project_root}/.tutorial-re-hyperframes-readiness.json",
                "source_files": [f"{project_root}/index.html"],
                "check_log": f"{project_root}/hyperframes-check.log",
                "render_log": f"{project_root}/hyperframes-render.log",
                "check_receipt": f"{project_root}/.tutorial-re-hyperframes-check-receipt.json",
                "render_receipt": f"{project_root}/.tutorial-re-hyperframes-render-receipt.json",
                "approval_record": f"{project_root}/.tutorial-re-hyperframes-approval.json",
                "check_command": "<recorded HyperFrames CLI> check",
                "preview_command": "<recorded HyperFrames CLI> preview",
                "render_command": "<recorded HyperFrames CLI> render --quality high --output out.mp4",
                "single_project_for_source": True,
                "rendered_checkpoint_comparison_required": True,
            },
        }
    return {
        "adapter": framework or "unknown",
        "framework": str(route.get("tool") or "unknown"),
        "state": "adapter_unavailable",
        "project_root": project_root,
        "next_action": f"adapter unavailable for exact local framework {route.get('tool')!r}; preserve source route or add reviewed adapter",
        "delivery_fields": {},
    }


def _remotion_toolchain_state() -> str:
    version = "4.0.489"
    root = runtime_data_root() / "remotion" / version
    receipt = root / ".remotion-toolchain-receipt.json"
    package = root / "package.json"
    lockfile = root / "package-lock.json"
    binary = root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
    if not root.exists():
        return "setup_required"
    if not all(path.is_file() for path in (receipt, package, lockfile, binary)):
        return "broken"
    try:
        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
        package_data = json.loads(package.read_text(encoding="utf-8"))
        package_hash = _sha256(package)
        lock_hash = _sha256(lockfile)
    except (OSError, ValueError):
        return "broken"
    return "ready" if (
        receipt_data.get("state") == "ready"
        and receipt_data.get("remotion_version") == version
        and receipt_data.get("package_sha256") == package_hash
        and receipt_data.get("lock_sha256") == lock_hash
        and package_data.get("dependencies", {}).get("remotion") == version
    ) else "broken"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
