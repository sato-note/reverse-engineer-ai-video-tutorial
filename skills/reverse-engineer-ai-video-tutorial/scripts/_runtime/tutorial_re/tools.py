"""Cross-platform external-tool and managed-runtime resolution."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


TOOL_ENV = {
    "ffmpeg": "TUTORIAL_RE_FFMPEG",
    "ffprobe": "TUTORIAL_RE_FFPROBE",
    "yt-dlp": "TUTORIAL_RE_YTDLP",
    "git": "TUTORIAL_RE_GIT",
    "node": "TUTORIAL_RE_NODE",
    "npm": "TUTORIAL_RE_NPM",
    "hyperframes": "TUTORIAL_RE_HYPERFRAMES",
}


@dataclass(frozen=True)
class ToolResolution:
    name: str
    command: tuple[str, ...] | None
    path: str | None
    source: str
    version: str | None = None
    verified: bool | None = None
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.command is not None and self.verified is not False

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "command": list(self.command) if self.command else None,
            "path": self.path,
            "source": self.source,
            "version": self.version,
            "verified": self.verified,
            "error": self.error,
        }


def runtime_data_root() -> Path:
    configured = os.environ.get("TUTORIAL_RE_DATA_ROOT")
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise ValueError("TUTORIAL_RE_DATA_ROOT must be an absolute path")
        resolved = candidate.resolve()
        home = Path.home().resolve()
        if resolved == Path(resolved.anchor) or resolved == home:
            raise ValueError("TUTORIAL_RE_DATA_ROOT cannot be a filesystem root or home directory")
        return resolved
    system = platform.system()
    if system == "Windows":
        return (Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "reverse-engineer-ai-video-tutorial").resolve()
    if system == "Darwin":
        return (Path.home() / "Library" / "Application Support" / "reverse-engineer-ai-video-tutorial").resolve()
    configured = os.environ.get("XDG_DATA_HOME")
    if configured and Path(configured).expanduser().is_absolute():
        base = Path(configured).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return (base / "reverse-engineer-ai-video-tutorial").resolve()


def managed_runtime_root() -> Path:
    return runtime_data_root() / "runtime"


def managed_python_path() -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    metadata = read_runtime_metadata()
    if metadata:
        configured = metadata.get("interpreter")
        if isinstance(configured, str) and Path(configured).is_absolute():
            return Path(configured).expanduser()
    return managed_runtime_root() / "venv" / bin_dir / executable


def runtime_metadata_path() -> Path:
    return managed_runtime_root() / "runtime.json"


def read_runtime_metadata() -> dict[str, object] | None:
    path = runtime_metadata_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _candidate_paths() -> list[Path]:
    values: list[Path] = []
    configured = os.environ.get("TUTORIAL_RE_TOOL_BIN")
    if configured:
        values.append(Path(configured).expanduser())
    prefix = Path(sys.prefix)
    values.extend((prefix / "bin", prefix / "Scripts"))
    return values


def resolve_tool(
    name: str,
    *,
    python_module: str | None = None,
    allow_network: bool = False,
) -> ToolResolution:
    env_name = TOOL_ENV.get(name)
    if env_name and os.environ.get(env_name):
        configured = os.environ[env_name]
        path = Path(configured).expanduser()
        resolved = shutil.which(configured) or (str(path) if path.is_file() else None)
        if resolved and Path(resolved).is_file():
            return ToolResolution(name, (resolved,), resolved, f"env:{env_name}")

    for directory in _candidate_paths():
        candidate = directory / (f"{name}.exe" if os.name == "nt" else name)
        if candidate.is_file():
            return ToolResolution(name, (str(candidate),), str(candidate), "managed-bin")

    resolved = shutil.which(name)
    if resolved and Path(resolved).is_file():
        return ToolResolution(name, (resolved,), resolved, "path")
    # A standalone downloader is portable across Python environments. Prefer it
    # over the module route, then fall back to the module for minimal hosts.
    if python_module and importlib.util.find_spec(python_module) is not None:
        return ToolResolution(name, (sys.executable, "-m", python_module), sys.executable, "python-module")
    if name == "hyperframes" and allow_network:
        npx = shutil.which("npx")
        if npx and Path(npx).is_file():
            return ToolResolution(name, (npx, "hyperframes"), npx, "npx")
    return ToolResolution(name, None, None, "missing")


def probe_tool(
    name: str,
    *,
    python_module: str | None = None,
    allow_network: bool = False,
) -> ToolResolution:
    result = resolve_tool(name, python_module=python_module, allow_network=allow_network)
    if not result.available:
        return ToolResolution(name, None, None, result.source, verified=False, error="not found")
    try:
        version_flag = "-version" if name in {"ffmpeg", "ffprobe"} else "--version"
        completed = subprocess.run(
            [*result.command, version_flag],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        raw = (completed.stdout or "") + (completed.stderr or "")
        output = raw.splitlines()
        version = output[0].strip() if output else None
        if completed.returncode != 0:
            return ToolResolution(name, result.command, result.path, result.source, version, False, f"exit {completed.returncode}")
        if not version or not re.search(r"\d+\.\d+", raw):
            return ToolResolution(name, result.command, result.path, result.source, version, False, "unrecognized version output")
        return ToolResolution(name, result.command, result.path, result.source, version, True)
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolResolution(name, result.command, result.path, result.source, None, False, f"{type(exc).__name__}: {exc}")


def require_tool(
    name: str,
    *,
    python_module: str | None = None,
    allow_network: bool = False,
) -> list[str]:
    result = probe_tool(name, python_module=python_module, allow_network=allow_network)
    if result.command is None:
        raise RuntimeError(f"required tool missing: {name}; run doctor for remediation")
    if not result.available:
        raise RuntimeError(f"required tool unusable: {name}: {result.error or 'probe failed'}")
    return list(result.command)


def detected_package_managers() -> dict[str, str | None]:
    candidates = {
        "winget": "Windows",
        "brew": "macOS",
        "apt": "Linux Debian/Ubuntu",
        "dnf": "Linux Fedora/RHEL",
        "pacman": "Linux Arch",
        "zypper": "Linux openSUSE",
    }
    return {name: shutil.which(name) for name in candidates}


def linux_distribution() -> dict[str, str]:
    if platform.system() != "Linux":
        return {}
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        result[key.lower()] = value.strip().strip('"')
    return {key: result[key] for key in ("id", "id_like", "version_id", "name") if key in result}


def supported_python() -> bool:
    return (3, 11) <= sys.version_info[:2] < (3, 15)


def python_runtime_health(interpreter: Path) -> dict[str, object]:
    """Report support for the selected interpreter, not the launcher process."""
    if not interpreter.is_file():
        return {"available": False, "supported": False, "version": None, "error": "interpreter missing"}
    code = (
        "import json,sys; "
        "version=sys.version.split()[0]; "
        "supported=(3,11)<=sys.version_info[:2]<(3,15); "
        "print(json.dumps({'available':True,'supported':supported,'version':version}))"
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "supported": False,
            "version": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    available = completed.returncode == 0 and payload.get("available") is True
    supported = available and payload.get("supported") is True
    return {
        "available": available,
        "supported": supported,
        "version": payload.get("version"),
        "error": None if available else ((completed.stderr or "").strip() or f"interpreter probe exited {completed.returncode}"),
    }


def command_text(command: Sequence[str] | None) -> str | None:
    return " ".join(command) if command else None


def managed_runtime_report(
    lock_path: Path | None = None,
    *,
    interpreter: Path | None = None,
) -> dict[str, object]:
    """Report receipt integrity plus a live check of the selected interpreter."""
    lock = lock_path or Path(__file__).resolve().parents[3] / "requirements.lock"
    metadata = read_runtime_metadata()
    selected = (interpreter or managed_python_path()).expanduser()
    lock_hash = _sha256(lock) if lock.is_file() else None
    expected = locked_packages(lock)
    runtime_path = (
        Path(str(metadata.get("runtime_path"))).expanduser()
        if metadata and isinstance(metadata.get("runtime_path"), str) and metadata.get("runtime_path")
        else None
    )
    metadata_interpreter = (
        Path(str(metadata.get("interpreter"))).expanduser()
        if metadata and isinstance(metadata.get("interpreter"), str) and metadata.get("interpreter")
        else None
    )
    metadata_path_match = bool(
        metadata
        and metadata.get("schema_version") == 3
        and metadata_interpreter is not None
        and metadata_interpreter.is_absolute()
        and metadata_interpreter.resolve() == selected.resolve()
        and runtime_path is not None
        and runtime_path.is_absolute()
        and runtime_path.resolve() == selected.parent.parent.resolve()
        and runtime_path.parent.resolve() == (managed_runtime_root() / "versions").resolve()
    )
    metadata_match = bool(
        metadata
        and metadata.get("lock_sha256") == lock_hash
        and metadata_path_match
        and metadata.get("python_supported") is True
        and metadata.get("modules_ok") is True
        and metadata.get("packages") == expected
    )
    live = live_runtime_check(selected, lock)
    ready = bool(metadata_match and live["ready"])
    return {
        "available": selected.is_file(),
        "ready": ready,
        "root": str(managed_runtime_root()),
        "interpreter": str(selected),
        "runtime_path": str(runtime_path) if runtime_path else None,
        "metadata": str(runtime_metadata_path()),
        "lock_sha256": lock_hash,
        "metadata_match": bool(metadata_match),
        "live": live,
        "error": live.get("error") if not live["ready"] else (None if metadata_match else "runtime receipt does not match active interpreter"),
        "receipt": metadata,
    }


def live_runtime_check(interpreter: Path, lock_path: Path | None = None) -> dict[str, object]:
    """Run bounded imports/version checks in the exact interpreter."""
    lock = lock_path or Path(__file__).resolve().parents[3] / "requirements.lock"
    expected = locked_packages(lock)
    if not interpreter.is_file():
        return {"ready": False, "supported_python": False, "modules_ok": False, "packages": {}, "error": "interpreter missing"}
    code = (
        "import importlib,importlib.metadata,json,sys; "
        "expected=json.loads(sys.argv[1]); modules=json.loads(sys.argv[2]); "
        "supported=(3,11)<=sys.version_info[:2]<(3,15); "
        "[importlib.import_module(name) for name in modules]; "
        "packages={name.lower().replace('_','-'):importlib.metadata.version(name) for name in expected}; "
        "print(json.dumps({'supported_python':supported,'modules_ok':True,'packages':packages,'python':sys.version.split()[0]})); "
        "sys.exit(0 if supported and packages==expected else 2)"
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", code, json.dumps(expected), json.dumps(["PIL", "youtube_transcript_api", "yt_dlp"])],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ready": False, "supported_python": False, "modules_ok": False, "packages": {}, "error": f"{type(exc).__name__}: {exc}"}
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    except (ValueError, json.JSONDecodeError):
        payload = {}
    packages = payload.get("packages") if isinstance(payload.get("packages"), dict) else {}
    supported = payload.get("supported_python") is True
    modules_ok = payload.get("modules_ok") is True
    ready = completed.returncode == 0 and supported and modules_ok and packages == expected
    error = None if ready else ((completed.stderr or "").strip() or f"runtime health check exited {completed.returncode}")
    return {
        "ready": ready,
        "supported_python": supported,
        "modules_ok": modules_ok,
        "packages": packages,
        "python": payload.get("python"),
        "error": error,
    }


def system_runtime_health(interpreter: Path, profile: str = "base") -> dict[str, object]:
    """Check only capabilities used by one workflow; never require the full lock."""
    requirements = {
        "base": ("Pillow",),
        "local-guide": ("Pillow", "ffmpeg", "ffprobe"),
        "youtube-guide": ("Pillow", "youtube-transcript-api", "ffmpeg", "ffprobe", "yt-dlp"),
        "recreate": ("Pillow", "ffmpeg", "ffprobe"),
        "remotion": ("Pillow", "ffmpeg", "ffprobe", "node", "npm"),
        "hyperframes": ("Pillow", "hyperframes", "node", "ffmpeg", "ffprobe"),
    }.get(profile)
    if requirements is None:
        return {"ready": False, "compatible": False, "profile": profile, "error": f"unknown profile: {profile}"}
    python = python_runtime_health(interpreter)
    dependencies = {
        "Pillow": compatible_dependency_health(interpreter, "PIL", "Pillow"),
        "youtube-transcript-api": compatible_dependency_health(interpreter, "youtube_transcript_api", "youtube-transcript-api"),
    }
    tools = {
        name: probe_tool(name, python_module="yt_dlp" if name == "yt-dlp" else None).as_dict()
        for name in ("ffmpeg", "ffprobe", "yt-dlp", "node", "npm", "hyperframes")
    }
    values = {
        "Pillow": dependencies["Pillow"]["ready"],
        "youtube-transcript-api": dependencies["youtube-transcript-api"]["ready"],
        **{name: tools[name]["available"] for name in tools},
    }
    missing = [name for name in requirements if not values.get(name, False)]
    if not python["supported"]:
        missing.insert(0, "python")
    return {
        "ready": not missing,
        "compatible": not missing,
        "profile": profile,
        "interpreter": str(interpreter.resolve()),
        "verified": "feature_probe",
        "supported_python": python["supported"],
        "python": python,
        "dependencies": dependencies,
        "tools": tools,
        "missing": missing,
        "error": None if not missing else f"missing compatible capability: {', '.join(missing)}",
    }


def dependency_health(interpreter: Path, module: str, distribution: str, expected: str | None) -> dict[str, object]:
    """Check one dependency by importing it in the exact selected interpreter."""
    if not interpreter.is_file():
        return {
            "available": False,
            "import_ok": False,
            "version_ok": False,
            "ready": False,
            "version": None,
            "expected_version": expected,
            "module": module,
            "distribution": distribution,
            "error": "interpreter missing",
        }
    code = "\n".join(
        (
            "import importlib, importlib.metadata, importlib.util, json, sys",
            "module = sys.argv[1]",
            "distribution = sys.argv[2]",
            "expected = sys.argv[3] or None",
            "result = {'available': False, 'import_ok': False, 'version_ok': False, 'ready': False, 'version': None, 'expected_version': expected, 'module': module, 'distribution': distribution, 'error': None}",
            "try:",
            "    result['available'] = importlib.util.find_spec(module) is not None",
            "except Exception as exc:",
            "    result['error'] = f'{type(exc).__name__}: {exc}'",
            "try:",
            "    importlib.import_module(module)",
            "    result['import_ok'] = True",
            "except Exception as exc:",
            "    result['error'] = f'{type(exc).__name__}: {exc}'",
            "try:",
            "    result['version'] = importlib.metadata.version(distribution)",
            "except importlib.metadata.PackageNotFoundError:",
            "    pass",
            "result['version_ok'] = bool(result['version'] and expected and result['version'] == expected)",
            "result['ready'] = bool(result['available'] and result['import_ok'] and result['version_ok'])",
            "print(json.dumps(result))",
            "sys.exit(0 if result['ready'] else 2)",
        )
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", code, module, distribution, expected or ""],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "import_ok": False,
            "version_ok": False,
            "ready": False,
            "version": None,
            "expected_version": expected,
            "module": module,
            "distribution": distribution,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("available", False)
    payload.setdefault("import_ok", False)
    payload.setdefault("version_ok", False)
    payload.setdefault("ready", False)
    payload.setdefault("version", None)
    payload.setdefault("expected_version", expected)
    payload.setdefault("module", module)
    payload.setdefault("distribution", distribution)
    if not payload["ready"] and not payload.get("error"):
        payload["error"] = (completed.stderr or "").strip() or f"dependency health exited {completed.returncode}"
    return payload


def compatible_dependency_health(
    interpreter: Path,
    module: str,
    distribution: str,
) -> dict[str, object]:
    """Probe an API contract without comparing the host to the managed lock."""
    if not interpreter.is_file():
        return {
            "available": False,
            "import_ok": False,
            "compatible": False,
            "ready": False,
            "verified": "feature_probe",
            "version": None,
            "expected_version": None,
            "module": module,
            "distribution": distribution,
            "error": "interpreter missing",
        }
    code = "\n".join(
        (
            "import importlib, importlib.metadata, importlib.util, io, json, sys",
            "module = sys.argv[1]; distribution = sys.argv[2]",
            "result = {'available': False, 'import_ok': False, 'compatible': False, 'ready': False, 'verified': 'feature_probe', 'version': None, 'expected_version': None, 'module': module, 'distribution': distribution, 'error': None}",
            "try:",
            "    result['available'] = importlib.util.find_spec(module) is not None",
            "    imported = importlib.import_module(module)",
            "    result['import_ok'] = True",
            "    result['version'] = importlib.metadata.version(distribution)",
            "    if module == 'PIL':",
            "        from PIL import Image",
            "        image = Image.new('RGB', (2, 2), (1, 2, 3)); stream = io.BytesIO(); image.save(stream, format='PNG'); stream.seek(0); Image.open(stream).load()",
            "    elif module == 'youtube_transcript_api':",
            "        api = getattr(imported, 'YouTubeTranscriptApi', None); instance = api() if api else None",
            "        if not ((api and callable(getattr(instance, 'fetch', None))) or (api and callable(getattr(api, 'get_transcript', None)))): raise RuntimeError('required transcript fetch API missing')",
            "    result['compatible'] = True; result['ready'] = True",
            "except Exception as exc:",
            "    result['error'] = f'{type(exc).__name__}: {exc}'",
            "print(json.dumps(result)); sys.exit(0 if result['ready'] else 2)",
        )
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", code, module, distribution],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "import_ok": False,
            "compatible": False,
            "ready": False,
            "verified": "feature_probe",
            "version": None,
            "expected_version": None,
            "module": module,
            "distribution": distribution,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("available", False)
    payload.setdefault("import_ok", False)
    payload.setdefault("compatible", False)
    payload.setdefault("ready", False)
    payload.setdefault("verified", "feature_probe")
    payload.setdefault("version", None)
    payload.setdefault("expected_version", None)
    payload.setdefault("module", module)
    payload.setdefault("distribution", distribution)
    if not payload["ready"] and not payload.get("error"):
        payload["error"] = (completed.stderr or "").strip() or f"feature probe exited {completed.returncode}"
    return payload


def locked_packages(path: Path) -> dict[str, str]:
    packages: dict[str, str] = {}
    if not path.is_file():
        return packages
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "==" not in value:
            continue
        name, version = value.split("==", 1)
        packages[name.lower().replace("_", "-")] = version
    return packages


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
