"""Create and verify a per-user managed Python runtime.

Virtual environments are created once at permanent versioned paths.  The
small active receipt is the only atomically switched runtime pointer.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import venv
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from file_lock import HeldFileLock, acquire as acquire_file_lock


SKILL_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = SKILL_ROOT / "requirements.lock"
RUNTIME_SCHEMA = 3
LOCK_STALE_SECONDS = 6 * 60 * 60
sys.path.insert(0, str(SKILL_ROOT / "scripts" / "_runtime"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare tutorial-re managed Python runtime")
    parser.add_argument("--check", action="store_true", help="verify existing runtime without mutation")
    parser.add_argument("--plan", action="store_true", help="show planned changes without mutation")
    parser.add_argument("--offline", action="store_true", help="never contact package indexes")
    parser.add_argument("--repair", action="store_true", help="build and activate a fresh runtime")
    parser.add_argument("--rollback", action="store_true", help="activate the receipt-linked previous runtime")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        state = inspect_runtime()
        if args.check:
            _print(state, args.json)
            return 0 if state["ready"] else 2
        if args.plan:
            state["plan"] = _plan(state, offline=args.offline, repair=args.repair)
            _print(state, args.json)
            return 0 if state["supported_python"] else 2
        if args.rollback:
            result = rollback_runtime(state)
            _print(result, args.json)
            return 0 if result["ready"] else 2
        if state["ready"] and not args.repair:
            _print(state, args.json)
            return 0
        if state["runtime_exists"] and not args.repair:
            state["error"] = "managed runtime stale; rerun with --repair"
            _print(state, args.json)
            return 2
        if args.offline:
            state["error"] = "offline mode cannot build missing or stale runtime"
            _print(state, args.json)
            return 2
        if not state["supported_python"]:
            state["error"] = "Python 3.11 through 3.14 required for managed runtime"
            _print(state, args.json)
            return 2
        result = build_runtime(state, offline=args.offline)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        state = locals().get("state") or {"schema_version": RUNTIME_SCHEMA, "ready": False}
        state["ready"] = False
        state["error"] = f"{type(exc).__name__}: {exc}"
        _print(state, args.json)
        return 1
    _print(result, args.json)
    return 0 if result["ready"] else 2


def inspect_runtime() -> dict[str, Any]:
    from tutorial_re.tools import locked_packages, managed_python_path, managed_runtime_report, managed_runtime_root, runtime_metadata_path, supported_python

    if not LOCK_PATH.is_file():
        raise RuntimeError(f"requirements lock missing: {LOCK_PATH}")
    report = managed_runtime_report(LOCK_PATH)
    interpreter = managed_python_path()
    metadata = report.get("receipt") if isinstance(report.get("receipt"), dict) else None
    runtime_path = Path(str(report["runtime_path"])) if report.get("runtime_path") else None
    live = report.get("live") if isinstance(report.get("live"), dict) else {}
    packages = live.get("packages") if isinstance(live.get("packages"), dict) else {}
    expected = locked_packages(LOCK_PATH)
    return {
        "schema_version": RUNTIME_SCHEMA,
        "ready": bool(report["ready"]),
        "supported_python": supported_python(),
        "current_python": sys.version.split()[0],
        "current_interpreter": str(Path(sys.executable).resolve()),
        "runtime_root": str(managed_runtime_root()),
        "versions_root": str(managed_runtime_root() / "versions"),
        "runtime_path": str(runtime_path) if runtime_path else None,
        "venv": str(runtime_path) if runtime_path else str(interpreter.parent.parent),
        "runtime_exists": bool(runtime_path.is_dir() if runtime_path else interpreter.parent.parent.is_dir()),
        "interpreter": str(interpreter),
        "metadata": str(runtime_metadata_path()),
        "lock": str(LOCK_PATH),
        "lock_sha256": report.get("lock_sha256"),
        "metadata_match": bool(report.get("metadata_match")),
        "live": live,
        "modules_ok": bool(live.get("modules_ok")),
        "packages": packages,
        "packages_ok": packages == expected,
        "required_modules": ["PIL", "youtube_transcript_api", "yt_dlp"],
        "receipt": metadata,
        "error": report.get("error"),
    }


def build_runtime(state: dict[str, Any], *, offline: bool = False) -> dict[str, Any]:
    from tutorial_re.tools import live_runtime_check, locked_packages, managed_runtime_root, runtime_metadata_path

    runtime_root = managed_runtime_root()
    versions_root = runtime_root / "versions"
    runtime_root.mkdir(parents=True, exist_ok=True)
    versions_root.mkdir(parents=True, exist_ok=True)
    _restrict_directory(runtime_root)
    _restrict_directory(versions_root)
    lock = _acquire_runtime_lock(runtime_root)
    active_path = runtime_metadata_path()
    previous_bytes = active_path.read_bytes() if active_path.is_file() else None
    previous = _read_json_bytes(previous_bytes)
    runtime_path = versions_root / f"{state['lock_sha256'][:16]}-{uuid.uuid4().hex}"
    interpreter = runtime_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(str(runtime_path))
        pip_command = [
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--requirement",
            str(LOCK_PATH),
        ]
        if offline:
            pip_command[3:3] = ["--no-index"]
        subprocess.run(pip_command, check=True)
        live = live_runtime_check(interpreter, LOCK_PATH)
        if not live["ready"]:
            raise RuntimeError(f"new managed runtime failed live check: {live.get('error')}")
        packages = live.get("packages") if isinstance(live.get("packages"), dict) else {}
        if packages != locked_packages(LOCK_PATH):
            raise RuntimeError("managed runtime package versions do not match requirements.lock")
        receipt = {
            "schema_version": RUNTIME_SCHEMA,
            "lock_sha256": state["lock_sha256"],
            "runtime_path": str(runtime_path.resolve()),
            "interpreter": str(interpreter.resolve()),
            "python": live.get("python"),
            "python_supported": True,
            "modules_ok": True,
            "packages": packages,
            "created_at": _now(),
        }
        _write_json_atomic(runtime_path / "runtime.json", receipt)
        active = dict(receipt)
        active.update(
            {
                "active": True,
                "activated_at": _now(),
                "previous_runtime_path": previous.get("runtime_path") if previous else None,
                "previous_interpreter": previous.get("interpreter") if previous else None,
            }
        )
        _write_json_atomic(active_path, active)
        result = inspect_runtime()
        if not result["ready"]:
            raise RuntimeError(f"active managed runtime failed post-switch check: {result.get('error')}")
        _prune_versions(versions_root, {runtime_path.resolve(), Path(str(active.get("previous_runtime_path") or "")).resolve()}, keep=3)
        result.update({"installed": True, "runtime_path": str(runtime_path), "previous_runtime": active.get("previous_runtime_path")})
        return result
    except Exception:
        _restore_active_pointer(active_path, previous_bytes)
        if runtime_path.exists():
            shutil.rmtree(runtime_path)
        raise
    finally:
        _release_runtime_lock(lock)


def rollback_runtime(state: dict[str, Any]) -> dict[str, Any]:
    from tutorial_re.tools import live_runtime_check, managed_runtime_root, runtime_metadata_path

    runtime_root = managed_runtime_root()
    active_path = runtime_metadata_path()
    lock = _acquire_runtime_lock(runtime_root)
    previous_bytes = active_path.read_bytes() if active_path.is_file() else None
    try:
        current = _read_json_bytes(previous_bytes)
        previous_path = Path(str(current.get("previous_runtime_path") or "")) if current else Path()
        versions_root = (runtime_root / "versions").resolve()
        if not current or not previous_path.is_absolute() or previous_path.resolve().parent != versions_root or not previous_path.is_dir():
            raise RuntimeError("no valid receipt-linked previous runtime")
        previous_receipt = _read_json(previous_path / "runtime.json")
        previous_interpreter = Path(str(previous_receipt.get("interpreter") or "")) if previous_receipt else Path()
        live = live_runtime_check(previous_interpreter)
        if not previous_receipt or not live["ready"] or previous_receipt.get("lock_sha256") != state.get("lock_sha256"):
            raise RuntimeError("receipt-linked previous runtime is not healthy for the current lock")
        active = dict(previous_receipt)
        active.update(
            {
                "active": True,
                "activated_at": _now(),
                "previous_runtime_path": current.get("runtime_path"),
                "previous_interpreter": current.get("interpreter"),
            }
        )
        _write_json_atomic(active_path, active)
        result = inspect_runtime()
        if not result["ready"]:
            raise RuntimeError("runtime rollback failed post-switch check")
        result.update({"rolled_back": True, "runtime_path": str(previous_path)})
        return result
    except Exception:
        _restore_active_pointer(active_path, previous_bytes)
        raise
    finally:
        _release_runtime_lock(lock)


def _plan(state: dict[str, Any], *, offline: bool, repair: bool) -> list[str]:
    if state["ready"] and not repair:
        return ["reuse matching managed runtime"]
    actions = []
    if state["runtime_exists"]:
        actions.extend(["create venv at a new permanent versioned path", "atomically switch active runtime receipt", "retain receipt-linked previous runtime"])
    else:
        actions.append("create managed virtual environment at a permanent versioned path")
    actions.append("install requirements.lock" + (" without package indexes" if offline else ""))
    actions.extend(["run exact-interpreter import/package health check", "restore previous active receipt if post-switch validation fails"])
    return actions


def _acquire_runtime_lock(runtime_root: Path) -> HeldFileLock:
    return acquire_file_lock(runtime_root / "repair.lock", "managed runtime repair")


def _release_runtime_lock(lock: HeldFileLock) -> None:
    lock.release()


def _prune_versions(versions_root: Path, protected: set[Path], *, keep: int) -> None:
    candidates = sorted((path for path in versions_root.iterdir() if path.is_dir() and not path.is_symlink()), key=lambda path: path.stat().st_mtime, reverse=True)
    retained = 0
    for path in candidates:
        if path.resolve() in protected or retained < keep:
            retained += 1
            continue
        shutil.rmtree(path)


def _restrict_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)


def _restore_active_pointer(path: Path, previous_bytes: bytes | None) -> None:
    if previous_bytes is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    else:
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
        temp.write_bytes(previous_bytes)
        os.replace(temp, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_json_bytes(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"ready: {payload.get('ready')}")
    print(f"runtime: {payload.get('interpreter')}")
    if payload.get("error"):
        print(f"error: {payload['error']}")
    if payload.get("plan"):
        print("plan:")
        for action in payload["plan"]:
            print(f"- {action}")


if __name__ == "__main__":
    raise SystemExit(main())
