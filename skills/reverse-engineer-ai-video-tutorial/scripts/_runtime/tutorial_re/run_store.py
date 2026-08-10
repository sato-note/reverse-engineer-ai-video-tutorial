from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import TERMINAL_STAGES, require_action
from .manifest import read_json, write_json


@dataclass(frozen=True)
class RunPaths:
    source_id: str
    run_id: str
    source_dir: Path
    run_dir: Path
    manifest: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id_for_file(path: Path) -> str:
    safe = _slug(path.stem) or "local"
    return f"{safe}-{sha256_file(path)[:16]}"


def create_run(
    cache_root: Path,
    source_id: str,
    *,
    target: str,
    action: str,
    parent_run_id: str | None = None,
    config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> RunPaths:
    require_action(action)
    created = now or datetime.now(timezone.utc)
    config_payload = config or {}
    fingerprint = _short_hash(
        {"source_id": source_id, "target": target, "action": action, "parent": parent_run_id, "config": config_payload}
    )
    timestamp = created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{timestamp}-{_slug(target)[:32] or 'target'}-{fingerprint}"
    source_dir = cache_root / source_id / "source"
    run_dir = cache_root / source_id / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"run already exists: {run_id}")
    source_dir.mkdir(parents=True, exist_ok=True)
    for name in ("frames", "crops"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "source_id": source_id,
        "parent_run_id": parent_run_id,
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "target": target,
        "requested_action": action,
        "current_stage": "initialized",
        "sealed": False,
        "config": config_payload,
        "artifacts": [],
        "warnings": [],
        "errors": [],
    }
    write_json(run_dir / "run.json", manifest)
    return RunPaths(source_id, run_id, source_dir, run_dir, manifest)


def update_run(run_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    payload = read_json(manifest_path)
    _require_v2(payload)
    if payload.get("sealed"):
        raise RuntimeError(f"run is sealed: {payload.get('run_id')}")
    payload.update(patch)
    write_json(manifest_path, payload)
    return payload


def register_artifact(run_dir: Path, path: Path, *, role: str) -> dict[str, Any]:
    resolved_run = run_dir.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_run)
    except ValueError as exc:
        raise ValueError("artifact must be inside run directory") from exc
    if not resolved_path.is_file():
        raise FileNotFoundError(resolved_path)
    record = {
        "role": role,
        "path": relative.as_posix(),
        "sha256": sha256_file(resolved_path),
        "size": resolved_path.stat().st_size,
        "media_type": _media_type(resolved_path),
    }
    payload = read_json(run_dir / "run.json")
    _require_v2(payload)
    if payload.get("sealed"):
        raise RuntimeError(f"run is sealed: {payload.get('run_id')}")
    artifact_rows = payload.get("artifacts", [])
    if not isinstance(artifact_rows, list) or not all(isinstance(item, dict) for item in artifact_rows):
        raise ValueError("run.json artifacts must be a list of objects")
    payload["artifacts"] = [
        item
        for item in artifact_rows
        if not (item.get("role") == role and item.get("path") == record["path"])
    ]
    payload["artifacts"].append(record)
    write_json(run_dir / "run.json", payload)
    return record


def seal_run(run_dir: Path, stage: str) -> dict[str, Any]:
    if stage not in TERMINAL_STAGES:
        raise ValueError(f"non-terminal stage cannot seal run: {stage}")
    payload = read_json(run_dir / "run.json")
    _require_v2(payload)
    if payload.get("sealed"):
        raise RuntimeError(f"run is sealed: {payload.get('run_id')}")
    payload["current_stage"] = stage
    payload["sealed"] = True
    payload["sealed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(run_dir / "run.json", payload)
    return payload


def verify_artifacts(run_dir: Path) -> list[str]:
    payload = read_json(run_dir / "run.json")
    _require_v2(payload)
    errors: list[str] = []
    records = payload.get("artifacts", [])
    if not isinstance(records, list):
        return ["artifacts must be a list"]
    resolved_run = run_dir.resolve()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"artifact[{index}] must be an object")
            continue
        raw_relative = record.get("path")
        if not isinstance(raw_relative, str) or not raw_relative.strip():
            errors.append(f"artifact[{index}] path must be a non-empty string")
            continue
        relative = raw_relative.replace("\\", "/")
        path = (resolved_run / relative).resolve()
        try:
            path.relative_to(resolved_run)
        except ValueError:
            errors.append(f"artifact[{index}] path escapes run: {relative}")
            continue
        role = str(record.get("role", ""))
        quoted_run = _quote_cli_arg(resolved_run)
        quoted_relative = _quote_cli_arg(relative)
        quoted_role = _quote_cli_arg(role)
        repair_command = (
            f"run.py normalize-json --run {quoted_run} --path {quoted_relative} --role {quoted_role}"
            if path.suffix.lower() == ".json"
            else f"run.py artifact --run {quoted_run} --path {quoted_relative} --role {quoted_role}"
        )
        if not path.is_file():
            errors.append(f"artifact[{index}] missing: {relative}; repair: {repair_command}")
            continue
        if sha256_file(path) != record.get("sha256"):
            errors.append(f"artifact[{index}] hash mismatch: {relative}; repair: {repair_command}")
    return errors


def _quote_cli_arg(value: object) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def inspect_legacy_cache(work_dir: Path) -> dict[str, Any]:
    """Return migration inventory without changing legacy cache."""
    names = (
        "run.json",
        "metadata.json",
        "transcript.json",
        "transcript.vtt",
        "source.mp4",
        "candidate_spans.json",
        "evidence_frames.json",
        "evidence_manifest.json",
        "contact_sheet.jpg",
        "report.md",
    )
    artifacts = []
    for name in names:
        path = work_dir / name
        if path.is_file():
            artifacts.append(
                {
                    "path": name,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    return {"legacy_root": str(work_dir), "dry_run": True, "artifacts": artifacts}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _short_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:10]


def _media_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


def _require_v2(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 2:
        raise ValueError("unsupported run schema: v2 required")
