"""Stdlib-safe capability doctor."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__
from .contracts import INTERNAL_STAGES, PUBLIC_ACTIONS
from .tools import (
    detected_package_managers,
    compatible_dependency_health,
    dependency_health,
    managed_python_path,
    managed_runtime_report,
    linux_distribution,
    probe_tool,
    python_runtime_health,
    read_runtime_metadata,
    runtime_data_root,
    locked_packages,
)


PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "base": {"required": ("python", "Pillow", "write")},
    "local-guide": {"required": ("python", "Pillow", "write", "ffmpeg", "ffprobe")},
    "youtube-guide": {"required": ("python", "Pillow", "youtube-transcript-api", "write", "ffmpeg", "ffprobe", "yt-dlp")},
    "recreate": {"required": ("python", "Pillow", "write", "ffmpeg", "ffprobe")},
    "remotion": {"required": ("python", "Pillow", "write", "ffmpeg", "ffprobe", "node", "npm", "remotion-toolchain")},
    "hyperframes": {"required": ("python", "Pillow", "write", "hyperframes", "hyperframes-node", "hyperframes-ffmpeg", "hyperframes-ffprobe")},
}

PROFILE_TOOLS = {
    "base": (),
    "local-guide": ("ffmpeg", "ffprobe"),
    "youtube-guide": ("ffmpeg", "ffprobe", "yt-dlp"),
    "recreate": ("ffmpeg", "ffprobe"),
    "remotion": ("ffmpeg", "ffprobe", "node", "npm"),
    "hyperframes": ("hyperframes", "node", "ffmpeg", "ffprobe"),
}


def doctor_report(
    profile: str = "base",
    *,
    workspace_root: Path | None = None,
    cache_root: Path | None = None,
    install_root: Path | None = None,
    runtime: str | None = None,
    all_profiles: bool = False,
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError(f"unknown doctor profile: {profile}")

    selected_runtime = runtime or os.environ.get("TUTORIAL_RE_RUNTIME") or "auto"
    if selected_runtime not in {"auto", "managed", "system"}:
        raise ValueError(f"unknown runtime mode: {selected_runtime}")
    current = Path(sys.executable).resolve()
    try:
        runtime_report = managed_runtime_report(Path(__file__).resolve().parents[3] / "requirements.lock")
    except (OSError, ValueError) as exc:
        runtime_report = {"available": False, "ready": False, "interpreter": "", "error": f"{type(exc).__name__}: {exc}"}
    managed_path = Path(str(runtime_report.get("interpreter") or "__invalid-managed-interpreter__")).resolve()
    configured_raw = os.environ.get("TUTORIAL_RE_PYTHON")
    configured_path = Path(configured_raw).expanduser().resolve() if configured_raw else None
    managed_selected = selected_runtime == "managed" or (
        selected_runtime == "auto" and not configured_path and bool(runtime_report.get("ready"))
    )
    if selected_runtime == "managed" and not runtime_report.get("ready"):
        managed_selected = True
    selected_interpreter = (
        configured_path if configured_path and configured_path.is_file()
        else managed_path if managed_selected and managed_path.is_file()
        else current
    )
    exact = selected_interpreter.resolve() == managed_path.resolve() and bool(runtime_report.get("ready"))
    python_health = python_runtime_health(selected_interpreter)
    dependencies = {
        "Pillow": _dependency_report("PIL", "Pillow", exact=exact, interpreter=selected_interpreter),
        "youtube-transcript-api": _dependency_report("youtube_transcript_api", "youtube-transcript-api", exact=exact, interpreter=selected_interpreter),
        "yt-dlp": _dependency_report("yt_dlp", "yt-dlp", exact=exact, interpreter=selected_interpreter),
    }
    tool_names = ("ffmpeg", "ffprobe", "yt-dlp", "git", "node", "npm", "hyperframes")
    selected_tools = set(tool_names if all_profiles else PROFILE_TOOLS[profile])
    tools = {
        name: (
            probe_tool(name, python_module="yt_dlp" if name == "yt-dlp" else None).as_dict()
            if name in selected_tools
            else _not_checked_tool(name)
        )
        for name in tool_names
    }
    remotion_toolchain = (
        _remotion_toolchain_report(workspace_root)
        if profile == "remotion" or all_profiles
        else _not_checked_framework("remotion")
    )
    hyperframes = (
        _hyperframes_report(tools["hyperframes"], tools["node"], tools["ffmpeg"], tools["ffprobe"])
        if profile == "hyperframes" or all_profiles
        else _not_checked_hyperframes()
    )
    probes = {
        "workspace": _path_probe(workspace_root),
        "cache": _path_probe(cache_root),
        "install": _path_probe(install_root),
        "temp": _temp_probe(),
    }
    configured_interpreter = configured_path is not None and selected_interpreter == configured_path
    selected_environment = "managed_exact" if selected_runtime == "managed" or exact else (
        "configured_compatible" if configured_interpreter else "system_compatible"
    )
    environment_ready = bool(python_health["supported"]) and (
        selected_environment != "managed_exact" or bool(runtime_report.get("ready"))
    )
    context = _path_context(probes)
    values: dict[str, Any] = {
        "python_version": python_health.get("version"),
        "python_executable": str(selected_interpreter.resolve()),
        "python_supported": bool(python_health["supported"]),
        "python": bool(python_health["supported"]),
        "Pillow": dependencies["Pillow"]["ready"],
        "youtube-transcript-api": dependencies["youtube-transcript-api"]["ready"],
        "write": all(item["ready"] for item in probes.values()),
        "ffmpeg": tools["ffmpeg"]["available"],
        "ffprobe": tools["ffprobe"]["available"],
        "yt-dlp": tools["yt-dlp"]["available"],
        "youtube_transcript_api": dependencies["youtube-transcript-api"]["ready"],
        "node": tools["node"]["available"],
        "npm": tools["npm"]["available"],
        "hyperframes": hyperframes["ready"],
        "hyperframes-node": hyperframes["requirements"]["node"]["ready"],
        "hyperframes-ffmpeg": hyperframes["requirements"]["ffmpeg"]["ready"],
        "hyperframes-ffprobe": hyperframes["requirements"]["ffprobe"]["ready"],
        "remotion-toolchain": remotion_toolchain["ready"],
    }
    values["write"] = context["state"] == "ready"
    profiles = {}
    for name, config in PROFILES.items():
        if name != profile and not all_profiles:
            profiles[name] = {
                "ready": False,
                "state": "not_checked",
                "required": list(config["required"]),
                "missing": [],
                "warnings": [],
                "next_action": f"run doctor --profile {name}",
                "path_plan": {"mutating": False, "state": "not_checked"},
            }
            continue
        missing = [
            item for item in config["required"]
            if item != "write" and not values.get(item, False)
        ]
        warnings: list[str] = []
        if not exact and environment_ready:
            warnings.append("system runtime passed compatibility probes; it is not managed-lock exact")
        if not environment_ready:
            missing.append("python-runtime")
        state = _profile_state(missing, context, probes, environment_ready)
        if state in {"ready", "ready_with_warnings"} and warnings:
            state = "ready_with_warnings"
        profiles[name] = {
            "ready": state in {"ready", "ready_with_warnings"},
            "state": state,
            "required": list(config["required"]),
            "missing": missing,
            "warnings": warnings,
            "next_action": _next_action(state, missing, context),
            "path_plan": context["path_plan"],
        }

    fixes = _fixes(profile, values, tools, dependencies, context)
    runtime_metadata = read_runtime_metadata()
    selected = profiles[profile]
    optional = {
        name: item for name, item in profiles.items() if name != profile
    }
    return {
        "schema_version": 3,
        "package": "tutorial-re",
        "runtime_version": __version__,
        "profile": profile,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": values["python_version"],
            "distribution": linux_distribution(),
        },
        "python": {
            "version": values["python_version"],
            "executable": values["python_executable"],
            "supported": values["python_supported"],
            "probe": python_health,
            "managed": str(managed_path) if managed_path.is_file() else None,
        },
        "dependencies": dependencies,
        "tools": tools,
        "frameworks": {
            "remotion": remotion_toolchain,
            "hyperframes": hyperframes,
        },
        "package_managers": detected_package_managers(),
        "probes": probes,
        "runtime": runtime_metadata,
        "environment": {
            "selected": selected_environment,
            "requested": selected_runtime,
            "ready": environment_ready,
            "system": {"interpreter": values["python_executable"], "supported": values["python_supported"]},
            "managed": runtime_report,
        },
        "capabilities": {
            "local-guide": profiles["local-guide"]["ready"],
            "youtube-guide": profiles["youtube-guide"]["ready"],
            "recreate": profiles["recreate"]["ready"],
            "remotion": profiles["remotion"]["ready"],
            "hyperframes": profiles["hyperframes"]["ready"],
            "transcript_fetch": dependencies["youtube-transcript-api"]["ready"],
            "transcript_import": ["json", "vtt", "srt"],
            "local_transcription": False,
        },
        "public_actions": list(PUBLIC_ACTIONS),
        "internal_stages": list(INTERNAL_STAGES),
        "profiles": profiles,
        "ready": selected["ready"],
        "state": selected["state"],
        "next_action": selected["next_action"],
        "fixes": fixes,
        "optional_capabilities": optional,
        "all_profiles": all_profiles,
    }


def _dependency_report(
    module: str,
    distribution: str,
    *,
    exact: bool,
    interpreter: Path,
) -> dict[str, Any]:
    lock = Path(__file__).resolve().parents[3] / "requirements.lock"
    expected = locked_packages(lock).get(distribution.lower().replace("_", "-"))
    if exact:
        result = dict(dependency_health(interpreter, module, distribution, expected))
        result["verified"] = "managed_lock"
        return result
    return dict(compatible_dependency_health(interpreter, module, distribution))


def _path_context(probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    selected = (probes["workspace"], probes["cache"])
    omitted = [name for name, item in zip(("workspace", "cache"), selected) if item.get("state") == "not_checked"]
    unsafe = [name for name, item in zip(("workspace", "cache"), selected) if item.get("state") in {"symlink", "symlink_escape", "not_directory", "unwritable"}]
    missing = [name for name, item in zip(("workspace", "cache"), selected) if item.get("state") == "missing"]
    workspace_path = probes["workspace"].get("path")
    cache_path = probes["cache"].get("path")
    if workspace_path and cache_path:
        try:
            Path(str(cache_path)).relative_to(Path(str(workspace_path)))
        except ValueError:
            unsafe.append("cache_outside_workspace")
    if unsafe:
        state = "blocked"
    elif missing:
        state = "setup_required"
    elif omitted:
        state = "needs_context"
    else:
        state = "ready"
    return {
        "state": state,
        "omitted": omitted,
        "missing": missing,
        "unsafe": unsafe,
        "path_plan": {
            "workspace": probes["workspace"],
            "cache": probes["cache"],
            "mutating": False,
            "next_action": (
                "choose a cache root inside the workspace and repair unsafe paths"
                if unsafe
                else "provide absolute --workspace-root and --cache-root"
                if omitted
                else "create missing owned directories in the workspace"
                if missing
                else None
            ),
        },
    }


def _profile_state(
    missing: list[str],
    context: dict[str, Any],
    probes: dict[str, dict[str, Any]],
    environment_ready: bool,
) -> str:
    if not environment_ready or context["unsafe"]:
        return "blocked"
    if missing or context["missing"]:
        return "setup_required"
    if context["omitted"]:
        return "needs_context"
    return "ready"


def _next_action(state: str, missing: list[str], context: dict[str, Any]) -> str | None:
    if state == "needs_context":
        return "provide absolute --workspace-root and --cache-root for a write-path check"
    if state == "setup_required":
        if context["missing"]:
            return "create missing owned directories in the workspace"
        return f"prepare selected capability: {', '.join(missing or context['missing'])}"
    if state == "blocked":
        if context["unsafe"]:
            return str(context["path_plan"]["next_action"])
        return "repair incompatible runtime or unsafe path, then rerun doctor"
    return None


def _not_checked_tool(name: str) -> dict[str, Any]:
    return {
        "available": False,
        "command": None,
        "path": None,
        "source": "not_checked",
        "version": None,
        "verified": None,
        "error": None,
        "state": "not_checked",
        "name": name,
    }


def _not_checked_framework(name: str) -> dict[str, Any]:
    return {
        "state": "not_checked",
        "ready": False,
        "source": "not_checked",
        "version": None,
        "next_action": f"run doctor --profile {name}",
        "error": None,
    }


def _not_checked_hyperframes() -> dict[str, Any]:
    result = _not_checked_framework("hyperframes")
    result.update({
        "requirements": {
            name: {"ready": False, "state": "not_checked"}
            for name in ("node", "ffmpeg", "ffprobe")
        },
        "health": {"ready": False, "state": "not_checked"},
        "approval_required": False,
    })
    return result


def _remotion_toolchain_report(workspace_root: Path | None = None) -> dict[str, Any]:
    native = _native_remotion_report(workspace_root)
    if native is not None:
        return native
    version = "4.0.489"
    root = runtime_data_root() / "remotion" / version
    receipt = root / ".remotion-toolchain-receipt.json"
    package = root / "package.json"
    lockfile = root / "package-lock.json"
    binary = root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
    if not root.exists():
        state = "setup_required"
        error = "shared Remotion toolchain has not been installed"
    elif not receipt.is_file() or not package.is_file() or not lockfile.is_file() or not binary.is_file():
        state = "broken"
        error = "shared Remotion receipt, package, lockfile, or CLI binary is missing"
    else:
        try:
            receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
            package_data = json.loads(package.read_text(encoding="utf-8"))
            package_hash = _sha256(package)
            lock_hash = _sha256(lockfile)
            node = probe_tool("node")
            binary_probe = subprocess.run(
                [str(binary), "--help"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            ) if node.available else None
            import_probe = subprocess.run(
                [*node.command, "-e", "require('remotion'); require('@remotion/cli');"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            ) if node.available and node.command else None
            ready = (
                receipt_data.get("state") == "ready"
                and receipt_data.get("remotion_version") == version
                and receipt_data.get("package_sha256") == package_hash
                and receipt_data.get("lock_sha256") == lock_hash
                and package_data.get("dependencies", {}).get("remotion") == version
                and node.available
                and binary_probe is not None
                and binary_probe.returncode == 0
                and import_probe is not None
                and import_probe.returncode == 0
            )
            state = "ready" if ready else "broken"
            error = None if ready else "shared Remotion receipt, package, CLI, or import probe is not healthy"
        except (OSError, ValueError, subprocess.SubprocessError):
            state = "broken"
            error = "shared Remotion metadata is invalid"
    return {
        "state": state,
        "ready": state == "ready",
        "source": "managed_shared_fallback",
        "policy": "tested fallback; not a universal host requirement",
        "root": str(root),
        "receipt": str(receipt),
        "version": version,
        "next_action": None if state == "ready" else "run prepare_remotion.py --setup-shared after approval",
        "error": error,
    }


def _native_remotion_report(workspace_root: Path | None) -> dict[str, Any] | None:
    if workspace_root is None:
        return None
    root = workspace_root.expanduser().resolve()
    package_path = root / "package.json"
    modules = root / "node_modules"
    binary = modules / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
    if not package_path.is_file():
        return None
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "state": "broken",
            "ready": False,
            "source": "project_native",
            "policy": "project-local toolchain",
            "root": str(root),
            "version": None,
            "error": "project package.json is invalid",
            "next_action": "repair the project package manifest before using Remotion",
        }
    dependencies = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(package.get(key), dict):
            dependencies.update(package[key])
    version = dependencies.get("remotion") or dependencies.get("@remotion/cli")
    if not version:
        return None
    node = probe_tool("node")
    import_probe = subprocess.run(
        [*node.command, "-e", "require('remotion'); require('@remotion/cli');"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    ) if node.available and node.command and modules.is_dir() else None
    cli_probe = subprocess.run(
        [str(binary), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    ) if binary.is_file() else None
    ready = bool(import_probe and import_probe.returncode == 0 and cli_probe and cli_probe.returncode == 0)
    return {
        "state": "ready" if ready else "broken",
        "ready": ready,
        "source": "project_native",
        "policy": "project-local toolchain",
        "root": str(root),
        "version": str(version),
        "receipt": None,
        "error": None if ready else "project-native Remotion import/CLI probe failed",
        "next_action": None if ready else "run the project package manager and native Remotion checks after approval",
    }


def _hyperframes_report(
    tool: dict[str, Any],
    node: dict[str, Any],
    ffmpeg: dict[str, Any],
    ffprobe: dict[str, Any],
) -> dict[str, Any]:
    requirements = {
        "node": _engine_requirement(node, 22),
        "ffmpeg": {"ready": bool(ffmpeg.get("available")), "version": ffmpeg.get("version")},
        "ffprobe": {"ready": bool(ffprobe.get("available")), "version": ffprobe.get("version")},
    }
    if not tool.get("command"):
        state = "approval_required"
        installation_state = "not_installed"
        next_action = "setup approval required; install or enable official HyperFrames CLI"
        health = {"ready": False, "state": "not_checked", "error": "CLI not installed"}
    elif not tool.get("available"):
        state = "broken"
        installation_state = "installed"
        next_action = "repair official HyperFrames CLI after approval"
        health = {"ready": False, "state": "broken", "error": tool.get("error")}
    elif not all(item["ready"] for item in requirements.values()):
        state = "broken"
        installation_state = "installed"
        next_action = "install Node.js 22+ and FFmpeg/FFprobe, then rerun doctor"
        health = {"ready": False, "state": "blocked_by_host_requirements", "error": "Node/FFmpeg requirements missing"}
    else:
        health = _hyperframes_cli_health(tool["command"])
        state = "ready" if health["ready"] else "broken"
        installation_state = "installed"
        next_action = None if state == "ready" else "repair native HyperFrames CLI/project health after approval"
    return {
        "state": state,
        "installation_state": installation_state,
        "ready": state == "ready",
        "cli": tool,
        "requirements": requirements,
        "health": health,
        "approval_required": state == "approval_required",
        "next_action": next_action,
    }


def _engine_requirement(tool: dict[str, Any], minimum_major: int) -> dict[str, Any]:
    version = str(tool.get("version") or "")
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    current = tuple(int(match.group(index) or 0) for index in (1, 2, 3)) if match else None
    ready = bool(tool.get("available") and current and current >= (minimum_major, 0, 0))
    return {"ready": ready, "minimum": f">={minimum_major}.0.0", "version": version or None}


def _hyperframes_cli_health(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [*command, "doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        payload = json.loads(completed.stdout or "{}")
        checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
        core = {str(item.get("name")): item.get("ok") is True for item in checks if isinstance(item, dict) and item.get("name")}
        core_ready = all(core.get(name) is True for name in ("Node.js", "FFmpeg", "FFprobe")) if core else False
        # HyperFrames doctor marks optional integrations and update availability as
        # failures; readiness here is limited to the native engine prerequisites.
        ready = completed.returncode == 0 and (payload.get("ok", True) is not False or core_ready)
        return {"ready": ready, "state": "ready" if ready else "broken", "exit_code": completed.returncode, "report": payload}
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        return {"ready": False, "state": "broken", "error": f"{type(exc).__name__}: {exc}"}


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_probe(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "state": "not_checked", "ready": False, "created": False}
    raw = path.expanduser()
    target = raw.resolve()
    if raw.is_symlink():
        state = "symlink_escape" if target != raw.absolute() else "symlink"
        return {"path": str(target), "state": state, "exists": True, "ready": False, "created": False}
    if not raw.exists():
        return {"path": str(target), "state": "missing", "exists": False, "ready": False, "created": False, "error": "directory missing"}
    if not raw.is_dir():
        return {"path": str(target), "state": "not_directory", "exists": True, "ready": False, "created": False}
    writable = os.access(raw, os.W_OK)
    if os.name != "nt":
        writable = writable and bool(raw.stat().st_mode & 0o222)
    return {"path": str(target), "state": "ready" if writable else "unwritable", "exists": True, "ready": writable, "created": False}


def _temp_probe() -> dict[str, Any]:
    try:
        directory = Path(tempfile.gettempdir()).resolve()
        ready = directory.is_dir() and os.access(directory, os.W_OK)
        return {"path": str(directory), "state": "ready" if ready else "unwritable", "exists": directory.is_dir(), "ready": ready, "created": False}
    except OSError as exc:
        return {"path": None, "ready": False, "created": False, "error": f"{type(exc).__name__}: {exc}"}


def _fixes(
    profile: str,
    values: dict[str, Any],
    tools: dict[str, Any],
    dependencies: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    fixes: list[dict[str, Any]] = []
    required = set(PROFILES[profile]["required"])
    if "python" in required and not values["python_supported"]:
        fixes.append({"code": "PYTHON_UNSUPPORTED", "message": "Use Python 3.11 through 3.14."})
    if "Pillow" in required and not values["Pillow"]:
        state = "missing" if not dependencies["Pillow"]["available"] else "broken"
        fixes.append({"code": f"PYTHON_DEPENDENCY_{state.upper()}", "package": "Pillow", "message": "Prepare Pillow for the selected profile; managed bootstrap is an optional exact fallback."})
    for name in ("ffmpeg", "ffprobe"):
        if name in required and not values[name]:
            fixes.append({"code": "SYSTEM_TOOL_MISSING", "tool": name, "message": f"Install {name} through approved OS package manager."})
    if "yt-dlp" in required and not values["yt-dlp"]:
        fixes.append({"code": "YOUTUBE_TOOL_MISSING", "tool": "yt-dlp", "message": "Provide a healthy standalone yt-dlp executable or Python yt_dlp module."})
    if "youtube-transcript-api" in required and not dependencies["youtube-transcript-api"]["ready"]:
        state = "missing" if not dependencies["youtube-transcript-api"]["available"] else "broken"
        fixes.append({"code": f"TRANSCRIPT_API_{state.upper()}", "package": "youtube-transcript-api", "message": "Prepare a compatible transcript API only for youtube-guide."})
    for name in ("node", "npm", "remotion-toolchain"):
        if name in required and not values[name]:
            fixes.append({"code": "REMOTION_SETUP_REQUIRED", "tool": name, "message": "Reuse or prepare a compatible project-local Remotion toolchain after approval."})
    if "hyperframes-node" in required and not values["hyperframes-node"]:
        fixes.append({"code": "HYPERFRAMES_NODE_REQUIRED", "tool": "node", "message": "HyperFrames requires Node.js 22+; install or enable it after approval."})
    if ("hyperframes-ffmpeg" in required and not values["hyperframes-ffmpeg"]) or ("hyperframes-ffprobe" in required and not values["hyperframes-ffprobe"]):
        fixes.append({"code": "HYPERFRAMES_FFMPEG_REQUIRED", "tool": "ffmpeg/ffprobe", "message": "HyperFrames requires FFmpeg and FFprobe; install after approval."})
    if "hyperframes" in required and not values["hyperframes"]:
        fixes.append({"code": "HYPERFRAMES_SETUP_REQUIRED", "tool": "hyperframes", "message": "Install or enable official HyperFrames CLI after approval; use direct CLI doctor, never plain npx discovery."})
    if context["state"] in {"setup_required", "blocked"}:
        fixes.append({"code": "PATH_CONTEXT", "message": context["path_plan"]["next_action"] or "repair supplied workspace/cache paths"})
    return fixes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check tutorial-re runtime capabilities")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="base")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--runtime", choices=("auto", "managed", "system"), default=None)
    parser.add_argument("--all-profiles", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)
    report = doctor_report(
        args.profile,
        workspace_root=args.workspace_root,
        cache_root=args.cache_root,
        install_root=args.install_root,
        runtime=args.runtime,
        all_profiles=args.all_profiles,
    )
    print(json.dumps(report, indent=2) if args.json else _text(report))
    return 0 if report["state"] in {"ready", "ready_with_warnings", "needs_context"} or args.allow_missing else 2


def _text(report: dict[str, Any]) -> str:
    lines = [f"profile: {report['profile']}", f"state: {report['state']}", f"runtime: {report['environment']['selected']}"]
    for name in ("remotion", "hyperframes"):
        framework = report.get("frameworks", {}).get(name, {})
        if framework:
            lines.append(f"{name}: {framework.get('state')}")
            if framework.get("next_action"):
                lines.append(f"next_action: {framework['next_action']}")
    for name, item in report["profiles"].items():
        lines.append(f"{name}: {item['state']}" + (f" missing={','.join(item['missing'])}" if item["missing"] else ""))
    return "\n".join(lines)
