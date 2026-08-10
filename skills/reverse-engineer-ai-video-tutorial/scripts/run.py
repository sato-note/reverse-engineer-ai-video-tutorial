from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

EXPECTED_RUNTIME_VERSION = "0.0.1"

def _ensure_runtime() -> None:
    bundled = Path(__file__).resolve().parent / "_runtime"
    if (bundled / "tutorial_re").is_dir():
        sys.path.insert(0, str(bundled))
        import tutorial_re

        if tutorial_re.__version__ != EXPECTED_RUNTIME_VERSION:
            raise SystemExit(
                f"incompatible bundled tutorial-re {tutorial_re.__version__}; expected {EXPECTED_RUNTIME_VERSION}"
            )
        return
    try:
        import tutorial_re

        if tutorial_re.__version__ != EXPECTED_RUNTIME_VERSION:
            raise SystemExit(
                f"incompatible tutorial-re {tutorial_re.__version__}; install tutorial-re=={EXPECTED_RUNTIME_VERSION}"
            )
        return
    except ImportError:
        pass
    for start in (Path.cwd(), Path(__file__).resolve()):
        for root in (start, *start.parents):
            src = root / "src"
            if (src / "tutorial_re").is_dir():
                sys.path.insert(0, str(src))
                import tutorial_re

                if tutorial_re.__version__ != EXPECTED_RUNTIME_VERSION:
                    raise SystemExit(
                        f"incompatible tutorial-re {tutorial_re.__version__}; install tutorial-re=={EXPECTED_RUNTIME_VERSION}"
                    )
                return
    raise SystemExit(
        f"tutorial_re runtime not found. Install tutorial-re=={EXPECTED_RUNTIME_VERSION}, then run: tutorial-re doctor --json"
    )


def _runtime_args(args: list[str]) -> tuple[str, list[str]]:
    legacy_system = os.environ.get("TUTORIAL_RE_ALLOW_SYSTEM") == "1"
    mode = os.environ.get("TUTORIAL_RE_RUNTIME", "system" if legacy_system else "auto")
    cleaned: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--runtime":
            if index + 1 >= len(args) or args[index + 1] not in {"auto", "managed", "system"}:
                raise SystemExit("--runtime requires auto, managed, or system")
            mode = args[index + 1]
            index += 2
            continue
        if value.startswith("--runtime="):
            mode = value.split("=", 1)[1]
            if mode not in {"auto", "managed", "system"}:
                raise SystemExit("--runtime requires auto, managed, or system")
            index += 1
            continue
        cleaned.append(value)
        index += 1
    if mode not in {"auto", "managed", "system"}:
        raise SystemExit("TUTORIAL_RE_RUNTIME requires auto, managed, or system")
    return mode, cleaned


def _maybe_reexec_managed() -> int | None:
    from tutorial_re.tools import managed_python_path, managed_runtime_report

    skip_reexec = os.environ.get("TUTORIAL_RE_NO_REEXEC") == "1"
    mode = os.environ.get("TUTORIAL_RE_RUNTIME", "auto")
    configured = os.environ.get("TUTORIAL_RE_PYTHON")
    if mode == "system" and not configured:
        return None
    try:
        managed = Path(configured).expanduser() if configured else managed_python_path()
    except (OSError, ValueError) as exc:
        if configured:
            raise SystemExit(f"invalid managed runtime configuration: {exc}") from exc
        managed = Path("__invalid-managed-interpreter__")
    try:
        report = managed_runtime_report(interpreter=managed if configured else None)
    except (OSError, ValueError) as exc:
        if configured:
            raise SystemExit(f"invalid managed runtime configuration: {exc}") from exc
        report = {"ready": False}
    if configured and not managed.is_file():
        raise SystemExit(
            f"TUTORIAL_RE_PYTHON interpreter is missing: {managed}"
        )
    if skip_reexec:
        return None
    if not managed.is_file() or managed.resolve() == Path(sys.executable).resolve():
        return None
    if mode == "managed" and not report.get("ready"):
        raise SystemExit(
            "managed runtime is not ready; run scripts/bootstrap_runtime.py --plan, then --repair"
        )
    if mode == "system" and configured:
        report = {"ready": False}
    if mode == "auto" and configured and not report.get("ready"):
        # An explicitly configured interpreter may be a compatible host runtime;
        # it is still re-execed so probes and subprocesses use the same Python.
        pass
    if mode == "auto" and not configured and not report.get("ready"):
        return None
    env = os.environ.copy()
    env["TUTORIAL_RE_NO_REEXEC"] = "1"
    completed = subprocess.run(
        [str(managed), str(Path(__file__).resolve()), *sys.argv[1:]],
        env=env,
        check=False,
    )
    return completed.returncode


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run.py <doctor|ingest|review|prepare-scene|validate|artifact|crop|qa-clip> [args]")
    runtime_mode, cleaned_args = _runtime_args(sys.argv[1:])
    os.environ["TUTORIAL_RE_RUNTIME"] = runtime_mode
    sys.argv[:] = [sys.argv[0], *cleaned_args]
    if len(sys.argv) < 2:
        raise SystemExit("usage: run.py <doctor|ingest|review|prepare-scene|validate|artifact|crop|qa-clip> [args]")
    _ensure_runtime()
    managed_result = _maybe_reexec_managed()
    if managed_result is not None:
        return managed_result
    command = sys.argv[1]
    if command == "doctor":
        from tutorial_re.doctor import main as doctor_main

        return doctor_main(sys.argv[2:])
    if command in {"--help", "-h", "help"}:
        print("usage: run.py <doctor|ingest|review|prepare-scene|validate|artifact|crop|qa-clip> [args]")
        return 0
    from tutorial_re.tools import managed_runtime_report, system_runtime_health

    try:
        managed_report = managed_runtime_report()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"invalid managed runtime configuration: {exc}") from exc
    active_raw = managed_report.get("interpreter")
    active = Path(str(active_raw)).resolve() if active_raw else None
    current = Path(sys.executable).resolve()
    if active is None or current != active:
        profile = _profile_for_command(command, sys.argv[2:])
        if runtime_mode == "managed":
            raise SystemExit(
                "managed runtime was requested but is not active; run scripts/bootstrap_runtime.py --repair"
            )
        system_health = system_runtime_health(current, profile)
        if not system_health.get("ready"):
            raise SystemExit(f"system runtime is not compatible with {profile}: {system_health.get('error')}")
        label = "system runtime override" if os.environ.get("TUTORIAL_RE_ALLOW_SYSTEM") == "1" else ("configured" if os.environ.get("TUTORIAL_RE_PYTHON") else "system")
        print(f"{label} runtime: interpreter={current} profile={profile} health=ready_with_warnings", file=sys.stderr)
        os.environ["TUTORIAL_RE_RUNTIME_SOURCE"] = "configured_compatible" if os.environ.get("TUTORIAL_RE_PYTHON") else "system_compatible"
    elif not managed_report.get("ready"):
        raise SystemExit(
            "managed runtime is not ready; run scripts/bootstrap_runtime.py --plan, then --repair"
        )
    if active is not None and current == active and managed_report.get("ready"):
        os.environ["TUTORIAL_RE_RUNTIME_SOURCE"] = "managed_exact"
    if command == "crop":
        sys.argv.pop(1)
        from tutorial_re.crops import main as command_main
    elif command == "qa-clip":
        sys.argv.pop(1)
        from tutorial_re.qa_clip import main as command_main
    else:
        from tutorial_re.cli import main as command_main
    return command_main()


def _profile_for_command(command: str, args: list[str]) -> str:
    if command == "ingest":
        has_video_url = any(value == "--video-url" or value.startswith("--video-url=") for value in args)
        return "youtube-guide" if has_video_url else "local-guide"
    if command in {"extract-detail", "qa-clip"}:
        return "local-guide"
    if command in {"start-recreate", "validate-scene-delivery"}:
        return "recreate"
    if command in {"prepare-hyperframes", "render-hyperframes"}:
        return "hyperframes"
    return "base"


if __name__ == "__main__":
    raise SystemExit(main())
