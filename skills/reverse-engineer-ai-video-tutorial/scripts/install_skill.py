"""Safe cross-platform skill installer; stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.dont_write_bytecode = True

try:
    from file_lock import HeldFileLock, acquire as acquire_file_lock
except ImportError:  # loaded from a test harness rather than the scripts directory
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from file_lock import HeldFileLock, acquire as acquire_file_lock


PAYLOAD_FILES = ("SKILL.md", "VERSION", "LICENSE", "requirements.in", "requirements.lock")
PAYLOAD_DIRS = ("agents", "assets", "references", "scripts")
CANONICAL_SUBPATH = Path("skills") / "reverse-engineer-ai-video-tutorial"
RECEIPT_NAME = ".install-receipt.json"
INSTALLER_VERSION = "1.1.0"
LOCK_STALE_SECONDS = 6 * 60 * 60
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
HOST_NAMES = ("codex", "cursor", "shared")
EXCLUDED_PARTS = {
    ".git",
    ".hermes.md",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "out",
    ".remotion",
    "cache",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install reverse-engineer-ai-video-tutorial safely")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--skills-root", type=Path)
    parser.add_argument("--host", choices=HOST_NAMES, help="select user-level host target: codex, cursor, or shared")
    parser.add_argument("--user", action="store_true", help="legacy alias for --host shared")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--verify", action="store_true", help="verify installed receipt and payload hashes")
    parser.add_argument("--github", action="store_true", help="require immutable GitHub provenance in receipt")
    args = parser.parse_args(argv)

    try:
        source = _resolve_source(args.source)
        name = _skill_name(source)
        host, skills_root_raw, target_raw = _resolve_install_paths(args, name)
        _validate_target(target_raw, skills_root_raw, name)
        skills_root = skills_root_raw.resolve()
        target = target_raw.resolve()

        if args.verify:
            result = verify_install(target, name)
        elif args.rollback:
            result = rollback(target, skills_root, dry_run=args.dry_run)
        else:
            payload = validate_source(source, name)
            provenance = _source_receipt(source)
            if args.github:
                _validate_github_source(source, payload, provenance)
            result = install(
                source,
                target,
                skills_root,
                payload,
                force=args.force,
                dry_run=args.dry_run,
                provenance=provenance,
                host=host,
            )
        result.update(_install_context(host, skills_root, target, args, action=result.get("action")))
        _print(result, args.json)
        return 0
    except SystemExit as exc:
        message = str(exc) or "install failed"
        if "already in progress" in message:
            error_code = "INSTALL_LOCK_BUSY"
        elif "target exists" in message:
            error_code = "TARGET_EXISTS"
        else:
            error_code = "INSTALL_FAILED"
        payload = {"ok": False, "error_code": error_code, "error": message}
        if args.json:
            print(json.dumps(payload, indent=2))
            print(f"{error_code}: {message}", file=sys.stderr)
        else:
            print(f"{error_code}: {message}", file=sys.stderr)
        return 2


def _default_skills_root() -> Path:
    configured = os.environ.get("AGENTS_SKILLS_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".agents" / "skills"


def _host_skills_root(host: str) -> Path:
    roots = {
        "codex": Path.home() / ".codex" / "skills",
        "cursor": Path.home() / ".cursor" / "skills",
        "shared": Path.home() / ".agents" / "skills",
    }
    try:
        return roots[host]
    except KeyError as exc:
        raise SystemExit(f"unsupported install host: {host}") from exc


def _resolve_install_paths(args: argparse.Namespace, name: str) -> tuple[str | None, Path, Path]:
    host = args.host
    if args.user:
        if host and host != "shared":
            raise SystemExit("--user conflicts with --host; use --host shared")
        host = "shared"

    if (
        host is None
        and args.skills_root is None
        and args.target is None
        and not os.environ.get("AGENTS_SKILLS_ROOT")
    ):
        host = "shared"

    selected_root = _host_skills_root(host) if host else None
    explicit_root = args.skills_root.expanduser().absolute() if args.skills_root else None
    if selected_root is not None and explicit_root is not None:
        if explicit_root.resolve() != selected_root.resolve():
            raise SystemExit(f"--skills-root conflicts with --host {host}: expected {selected_root}")
    skills_root_raw = explicit_root or selected_root or _default_skills_root().expanduser().absolute()
    target_raw = (args.target or (skills_root_raw / name)).expanduser().absolute()
    if selected_root is not None:
        try:
            target_raw.relative_to(selected_root.absolute())
        except ValueError as exc:
            raise SystemExit(f"--target conflicts with --host {host}: target must stay under {selected_root}") from exc
    return host, skills_root_raw, target_raw


def _install_context(
    host: str | None,
    skills_root: Path,
    target: Path,
    args: argparse.Namespace,
    *,
    action: object,
) -> dict[str, Any]:
    replacing = target.exists() or target.is_symlink()
    return {
        "host": host,
        "skills_root": str(skills_root),
        "target": str(target),
        "dependency_plan": {
            "system_packages": "not installed by installer",
            "skill_runtime": "not prepared by installer",
            "frameworks": "not prepared unless explicitly requested after install",
        },
        "approvals_required": ["replace_existing_install"] if action == "update" else [],
    }


def _resolve_source(value: Path | None) -> Path:
    candidate = (value.expanduser() if value else Path(__file__).resolve().parents[1]).resolve()
    if (candidate / "SKILL.md").is_file():
        return candidate
    canonical = candidate / CANONICAL_SUBPATH
    if (canonical / "SKILL.md").is_file():
        return canonical.resolve()
    raise SystemExit(f"skill source missing SKILL.md: {candidate}")


def _skill_name(source: Path) -> str:
    return _frontmatter_name(source / "SKILL.md")


def validate_source(source: Path, name: str) -> list[Path]:
    if not source.is_dir():
        raise SystemExit(f"source directory missing: {source}")
    skill_name = _frontmatter_name(source / "SKILL.md")
    if skill_name != name:
        raise SystemExit(f"skill name mismatch: frontmatter={skill_name!r}")
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"invalid VERSION: {version!r}")

    files: list[Path] = []
    for relative in PAYLOAD_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"required payload file missing or unsafe: {relative}")
        files.append(Path(relative))
    for directory in PAYLOAD_DIRS:
        root = source / directory
        if not root.is_dir() or root.is_symlink():
            raise SystemExit(f"required payload directory missing or unsafe: {directory}")
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(source)
            if _excluded(relative):
                continue
            if path.is_symlink():
                raise SystemExit(f"symlink not allowed in payload: {relative}")
            if path.is_file():
                if path.suffix.lower() not in {".pyc", ".pyo"}:
                    files.append(relative)
    return sorted(files)


def install(
    source: Path,
    target: Path,
    skills_root: Path,
    payload: list[Path],
    *,
    force: bool,
    dry_run: bool,
    provenance: dict[str, Any],
    host: str | None = None,
) -> dict[str, Any]:
    if target.is_symlink() or skills_root.is_symlink():
        raise SystemExit("install target/root symlink not allowed")
    target = target.resolve()
    skills_root = skills_root.resolve()
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    files = [{"path": path.as_posix(), "sha256": _sha256(source / path)} for path in payload]
    payload_sha256 = _payload_sha256(files)
    if dry_run:
        exists = target.exists() or target.is_symlink()
        result: dict[str, Any] = {
            "schema_version": 2,
            "action": "update" if exists else "install",
            "source": str(source),
            "target": str(target),
            "skills_root": str(skills_root),
            "version": version,
            "payload_files": len(payload),
            "files": files,
            "dry_run": dry_run,
            "installer_version": INSTALLER_VERSION,
            "payload_sha256": payload_sha256,
            "host": host,
        }
        result["plan"] = ["validate source", "stage allowlisted payload", "hash staged payload", "backup existing target", "atomic replace", "write install receipt", "verify receipt"]
        if exists and not force:
            result["plan"].append("request approval before --force")
        return result

    skills_root.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(skills_root, target.name)
    stage: Path | None = None
    backup: Path | None = None
    moved_target = False
    installed_target = False
    try:
        _validate_target(target, skills_root, target.name)
        exists = target.exists() or target.is_symlink()
        if exists and not force:
            raise SystemExit(f"target exists; pass --force for safe backup/update: {target}")
        result = {
            "schema_version": 2,
            "action": "update" if exists else "install",
            "source": str(source),
            "target": str(target),
            "skills_root": str(skills_root),
            "version": version,
            "payload_files": len(payload),
            "files": files,
            "dry_run": dry_run,
            "installer_version": INSTALLER_VERSION,
            "payload_sha256": payload_sha256,
            "host": host,
        }
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=skills_root))
        for relative in payload:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
        _verify_hashes(stage, files)
        if exists:
            backup = skills_root / f".{target.name}.backup-{uuid.uuid4().hex}"
            os.replace(target, backup)
            moved_target = True
        os.replace(stage, target)
        installed_target = True
        receipt = {
            "schema_version": 2,
            "installer_version": INSTALLER_VERSION,
            "source": provenance,
            "target": str(target),
            "version": version,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "backup": str(backup) if backup else None,
            "files": files,
            "payload_sha256": payload_sha256,
            "host": host,
        }
        receipt_path = target / RECEIPT_NAME
        _write_receipt(receipt_path, receipt)
        verify_install(target, target.name)
        result.update({"backup": str(backup) if backup else None, "receipt": str(receipt_path)})
        return result
    except Exception:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        if installed_target and target.exists() and not target.is_symlink():
            shutil.rmtree(target)
        if moved_target and backup and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        _release_lock(lock)


def rollback(target: Path, skills_root: Path, *, dry_run: bool) -> dict[str, Any]:
    lock = _acquire_lock(skills_root, target.name)
    try:
        receipt = _read_receipt(target / RECEIPT_NAME)
        backup = Path(str(receipt.get("backup", ""))).expanduser() if receipt else Path()
        if not receipt:
            raise SystemExit(f"install receipt missing: {target / RECEIPT_NAME}")
        _validate_receipt(receipt, target, target.name, expected_target=target)
        _verify_receipt_payload(target, receipt, context="current install")
        _validate_backup(backup, skills_root, target)
        backup_receipt = _read_receipt(backup / RECEIPT_NAME)
        if not backup_receipt:
            raise SystemExit(f"receipt-linked rollback backup missing receipt: {backup}")
        _validate_receipt(backup_receipt, backup, target.name, expected_target=target)
        _verify_receipt_payload(backup, backup_receipt, context="rollback backup")
        result = {"schema_version": 2, "action": "rollback", "target": str(target), "backup": str(backup), "dry_run": dry_run}
        if dry_run:
            return result
        failed = skills_root / f".{target.name}.failed-{uuid.uuid4().hex}"
        try:
            if target.exists() or target.is_symlink():
                os.replace(target, failed)
            os.replace(backup, target)
            verify_install(target, target.name)
        except Exception as original_error:
            recovery_errors: list[str] = []
            try:
                if target.exists() or target.is_symlink():
                    if backup.exists():
                        recovery_errors.append(f"backup path occupied during recovery: {backup}")
                    else:
                        os.replace(target, backup)
            except Exception as recovery_error:
                recovery_errors.append(f"could not preserve rollback candidate at {backup}: {recovery_error}")
            try:
                if failed.exists() and not (target.exists() or target.is_symlink()):
                    os.replace(failed, target)
                elif failed.exists():
                    recovery_errors.append(f"active target path occupied during recovery: {target}")
            except Exception as recovery_error:
                recovery_errors.append(f"could not restore active install at {target}: {recovery_error}")
            if not (target.exists() and target.is_dir() and not target.is_symlink()):
                recovery_errors.append(f"active install missing after rollback failure: {target}")
            else:
                try:
                    _verify_receipt_payload(target, receipt, context="recovered current install")
                except Exception as recovery_error:
                    recovery_errors.append(f"recovered active install failed verification: {recovery_error}")
            if not (backup.exists() and backup.is_dir() and not backup.is_symlink()):
                recovery_errors.append(f"rollback backup missing after rollback failure: {backup}")
            else:
                try:
                    _verify_receipt_payload(backup, backup_receipt, context="recovered rollback backup")
                except Exception as recovery_error:
                    recovery_errors.append(f"recovered rollback backup failed verification: {recovery_error}")
            if recovery_errors:
                raise RuntimeError(
                    "rollback failed and exact recovery was incomplete; "
                    f"target={target} backup={backup} failed={failed}; "
                    + " | ".join(recovery_errors)
                ) from original_error
            raise
        result["restored"] = str(target)
        result["displaced"] = str(failed) if failed.exists() else None
        return result
    finally:
        _release_lock(lock)


def verify_install(target: Path, name: str) -> dict[str, Any]:
    receipt = _read_receipt(target / RECEIPT_NAME)
    if not receipt:
        raise SystemExit(f"install receipt missing: {target / RECEIPT_NAME}")
    _validate_receipt(receipt, target, name, expected_target=target)
    files = receipt["files"]
    expected = {item.as_posix() for item in _installed_payload_paths(target)}
    recorded = {item["path"] for item in files}
    if expected != recorded:
        raise SystemExit(f"installed payload set mismatch; missing={sorted(recorded - expected)}, unexpected={sorted(expected - recorded)}")
    _verify_hashes(target, files)
    actual = _payload_sha256(files)
    if actual != receipt.get("payload_sha256"):
        raise SystemExit("install receipt aggregate hash mismatch")
    return {"schema_version": 2, "action": "verify", "target": str(target), "ready": True, "version": receipt["version"], "payload_sha256": actual}


def _validate_target(target: Path, skills_root: Path, name: str) -> None:
    _reject_link_components(skills_root)
    if skills_root == Path.home().resolve() or skills_root.parent == skills_root:
        raise SystemExit(f"unsafe skills root: {skills_root}")
    try:
        target.relative_to(skills_root)
    except ValueError as exc:
        raise SystemExit(f"unsafe target outside skills root: {target}") from exc
    if target.parent != skills_root or target.name != name:
        raise SystemExit(f"target must be direct child of skills root with skill name: {skills_root}")
    if target.exists() and target.is_symlink():
        raise SystemExit(f"target symlink not allowed: {target}")


def _reject_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise SystemExit(f"symlink/junction path not allowed: {current}")


def _excluded(relative: Path) -> bool:
    if os.name == "nt":
        return any(part.casefold() in {value.casefold() for value in EXCLUDED_PARTS} for part in relative.parts)
    return any(part in EXCLUDED_PARTS for part in relative.parts)


def _installed_payload_paths(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir() or root.is_symlink():
        raise SystemExit(f"installed target missing or unsafe: {root}")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.as_posix() == RECEIPT_NAME:
            continue
        if path.is_symlink():
            raise SystemExit(f"installed payload symlink not allowed: {relative}")
        if path.is_file():
            files.append(relative)
    return files


def _validate_receipt(
    receipt: dict[str, Any],
    root: Path,
    name: str,
    *,
    expected_target: Path,
) -> None:
    if receipt.get("schema_version") != 2:
        raise SystemExit("unsupported install receipt schema")
    if receipt.get("target") != str(expected_target.resolve()):
        raise SystemExit("install receipt target mismatch")
    if receipt.get("installer_version") != INSTALLER_VERSION:
        raise SystemExit("install receipt installer version mismatch")
    version_path = root / "VERSION"
    if not version_path.is_file():
        raise SystemExit("installed VERSION missing")
    version = version_path.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version) or receipt.get("version") != version:
        raise SystemExit("install receipt version mismatch")
    if _frontmatter_name(root / "SKILL.md") != name:
        raise SystemExit("installed SKILL.md name mismatch")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("install receipt file list missing")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise SystemExit("invalid install receipt file entry")
        relative = _validate_receipt_path(item["path"])
        normalized = relative.as_posix()
        if normalized in seen:
            raise SystemExit(f"duplicate install receipt path: {normalized}")
        seen.add(normalized)
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise SystemExit(f"invalid install receipt hash: {normalized}")
    if _payload_sha256(files) != receipt.get("payload_sha256"):
        raise SystemExit("install receipt aggregate hash mismatch")


def _verify_receipt_payload(root: Path, receipt: dict[str, Any], *, context: str) -> None:
    files = receipt["files"]
    expected = {item.as_posix() for item in _installed_payload_paths(root)}
    recorded = {item["path"] for item in files}
    if expected != recorded:
        raise SystemExit(
            f"{context} payload set mismatch; missing={sorted(recorded - expected)}, "
            f"unexpected={sorted(expected - recorded)}"
        )
    try:
        _verify_hashes(root, files)
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"{context} payload hash verification failed: {exc}") from exc
    actual = _payload_sha256(files)
    if actual != receipt.get("payload_sha256"):
        raise SystemExit(f"{context} aggregate hash mismatch")


def _validate_receipt_path(value: str) -> Path:
    if not value or "\\" in value:
        raise SystemExit(f"unsafe install receipt path: {value!r}")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SystemExit(f"unsafe install receipt path: {value!r}")
    return path


def _validate_backup(backup: Path, skills_root: Path, target: Path) -> None:
    if not backup.is_absolute() or backup.parent.resolve() != skills_root.resolve():
        raise SystemExit(f"rollback backup escapes skills root: {backup}")
    if not backup.name.startswith(f".{target.name}.backup-") or not re.fullmatch(rf"\.{re.escape(target.name)}\.backup-[0-9a-f]+", backup.name):
        raise SystemExit(f"rollback backup name is not receipt-linked: {backup}")
    _reject_link_components(backup)
    if backup.is_symlink() or not backup.is_dir():
        raise SystemExit(f"receipt-linked rollback backup missing or unsafe: {backup}")


def _frontmatter_name(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"SKILL.md unreadable: {exc}") from exc
    if not lines or lines[0].strip() != "---":
        raise SystemExit("SKILL.md frontmatter missing")
    for line in lines[1:40]:
        if line.strip() == "---":
            break
        match = re.match(r"^name:\s*([^\s]+)\s*$", line)
        if match:
            return match.group(1)
    raise SystemExit("SKILL.md frontmatter name missing")


def _source_receipt(source: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            completed = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, encoding="utf-8", check=False)
        except OSError:
            return None
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and value else None

    url = git("remote", "get-url", "origin")
    commit = git("rev-parse", "HEAD")
    tag = git("describe", "--tags", "--exact-match")
    normalized_url = _normalize_github_url(url)
    return {
        "path": str(source),
        "url": normalized_url or url,
        "commit": commit,
        "tag": tag,
        "provenance": "github-tagged" if normalized_url and commit and tag else "local-uncommitted",
    }


def _validate_github_source(source: Path, payload: list[Path], provenance: dict[str, Any]) -> None:
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    url = _normalize_github_url(provenance.get("url"))
    if not url:
        raise SystemExit("--github requires an HTTPS or SSH GitHub origin URL")
    commit = provenance.get("commit")
    tag = provenance.get("tag")
    if not commit or not tag:
        raise SystemExit("--github requires an exact HEAD commit and release tag")
    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise SystemExit(f"release tag must be {expected_tag}, got {tag}")
    tag_commit = _git_output(source, "rev-parse", f"{tag}^{{commit}}")
    if tag_commit != commit:
        raise SystemExit("release tag does not point to HEAD")
    pathspecs = _git_payload_pathspecs(source)
    git_root = _git_repo_root(source)
    status = _git_status(git_root, *pathspecs)
    if status is None:
        raise SystemExit("--github requires a clean tracked and untracked payload: git status unavailable")
    if any(line.startswith("??") for line in status.splitlines()):
        raise SystemExit(f"--github requires a clean tracked and untracked payload: {status.strip()}")
    if not _git_command_ok(git_root, "diff", "--cached", "--quiet", tag, "--", *pathspecs):
        raise SystemExit("payload index differs from immutable Git tag")
    tagged = _git_tagged_payload_map(source, tag)
    current = {path.as_posix() for path in payload}
    if set(tagged) != current:
        raise SystemExit(
            "payload file set differs from immutable Git tag; "
            f"missing={sorted(set(tagged) - current)}, unexpected={sorted(current - set(tagged))}"
        )
    for relative in sorted(payload):
        path = relative.as_posix()
        current_oid = _git_clean_blob_oid(source, relative)
        if current_oid != tagged[path]["oid"]:
            if not _git_command_ok(git_root, "diff", "--quiet", "--", _git_payload_path(source, relative)):
                raise SystemExit(f"payload differs from immutable Git tag: {path} (Git blob mismatch)")
    provenance.update({"url": url, "commit": commit, "tag": tag, "version": version, "provenance": "github-tagged"})


def _normalize_github_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    if raw.startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
    else:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https", "ssh"} or parsed.hostname not in {"github.com", "www.github.com"}:
            return None
        if parsed.query or parsed.fragment or parsed.username not in {None, "git"}:
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git").strip("/")
    parts = path.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts):
        return None
    return f"https://github.com/{parts[0]}/{parts[1]}"


def _git_output(source: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git_repo_root(source: Path) -> Path:
    value = _git_output(source, "rev-parse", "--show-toplevel")
    if not value:
        raise SystemExit("--github requires a Git working tree")
    return Path(value).resolve()


def _git_repo_prefix(source: Path) -> str:
    value = _git_output(source, "rev-parse", "--show-prefix")
    if value is None:
        raise SystemExit("--github requires a Git working tree")
    return value.replace("\\", "/").strip("/")


def _git_payload_path(source: Path, relative: Path) -> str:
    prefix = _git_repo_prefix(source)
    return relative.as_posix() if not prefix else f"{prefix}/{relative.as_posix()}"


def _git_payload_pathspecs(source: Path) -> tuple[str, ...]:
    prefix = _git_repo_prefix(source)
    if not prefix:
        return (*PAYLOAD_FILES, *PAYLOAD_DIRS)
    return tuple(f"{prefix}/{path}" for path in (*PAYLOAD_FILES, *PAYLOAD_DIRS))


def _git_status(source: Path, *pathspecs: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source), "status", "--porcelain=1", "--untracked-files=all", "--", *pathspecs],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    return completed.stdout if completed.returncode == 0 else None


def _git_command_ok(source: Path, *args: str) -> bool:
    try:
        completed = subprocess.run(["git", "-C", str(source), *args], capture_output=True, check=False)
    except OSError:
        return False
    return completed.returncode == 0


def _git_blob_sha256(source: Path, tag: str, relative: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source), "show", f"{tag}:{relative.as_posix()}"],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"git unavailable while checking immutable payload: {exc}") from exc
    if completed.returncode:
        raise SystemExit(f"tagged payload file missing: {relative}")
    return hashlib.sha256(completed.stdout).hexdigest()


def _git_clean_blob_oid(source: Path, relative: Path) -> str:
    repo_root = _git_repo_root(source)
    repo_relative = _git_payload_path(source, relative)
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "hash-object", f"--path={repo_relative}", "--", repo_relative],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"git unavailable while checking immutable payload: {exc}") from exc
    if completed.returncode:
        raise SystemExit(f"unable to hash current payload file: {relative}")
    value = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise SystemExit(f"invalid Git blob ID for current payload file: {relative}")
    return value


def _git_tagged_payload_map(source: Path, tag: str) -> dict[str, dict[str, str]]:
    repo_root = _git_repo_root(source)
    prefix = _git_repo_prefix(source)
    pathspecs = _git_payload_pathspecs(source)
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "-z", tag, "--", *pathspecs],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"git unavailable while checking immutable payload: {exc}") from exc
    if completed.returncode:
        raise SystemExit("unable to enumerate immutable Git payload")
    paths: dict[str, dict[str, str]] = {}
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        fields = header.split()
        if len(fields) != 3:
            raise SystemExit(f"invalid immutable Git tree record: {record!r}")
        mode, type_name, oid = fields
        full_relative = raw_path.decode("utf-8")
        if prefix:
            marker = prefix + "/"
            if not full_relative.startswith(marker):
                continue
            full_relative = full_relative[len(marker):]
        relative = Path(full_relative)
        if type_name != b"blob" or mode not in {b"100644", b"100755"}:
            raise SystemExit(f"non-regular file not allowed in immutable payload: {relative}")
        if _is_payload_path(relative):
            paths[relative.as_posix()] = {"mode": mode.decode("ascii"), "type": "blob", "oid": oid.decode("ascii")}
    return paths


def _is_payload_path(relative: Path) -> bool:
    if _excluded(relative):
        return False
    if len(relative.parts) == 1:
        return relative.as_posix() in PAYLOAD_FILES
    if relative.parts[0] not in PAYLOAD_DIRS:
        return False
    return relative.suffix.lower() not in {".pyc", ".pyo"}


def _payload_sha256(files: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item["path"].encode("utf-8"))
        digest.update(item["sha256"].encode("ascii"))
    return digest.hexdigest()


def _acquire_lock(skills_root: Path, name: str) -> HeldFileLock:
    lock = skills_root / f".{name}.install.lock"
    try:
        return acquire_file_lock(lock, "install", attempts=120, delay=0.05)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def _release_lock(lock: HeldFileLock) -> None:
    lock.release()


def _read_receipt(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _verify_hashes(root: Path, files: list[dict[str, str]]) -> None:
    for item in files:
        relative = _validate_receipt_path(item["path"])
        actual = _sha256(root / relative)
        if actual != item["sha256"]:
            raise RuntimeError(f"staged hash mismatch: {item['path']}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        message = f"{payload.get('action')}: {payload.get('target')} ({payload.get('version', 'unknown')})"
        encoding = sys.stdout.encoding or "utf-8"
        print(message.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace"))
        if payload.get("backup"):
            backup = f"backup: {payload['backup']}"
            print(backup.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace"))


if __name__ == "__main__":
    raise SystemExit(main())
