from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import require_action


EVIDENCE_LABELS = {
    "SOURCE-EVIDENCE",
    "EXACT-TRANSCRIPTION",
    "DETAILED-PARAPHRASE",
    "CONDENSED-RECONSTRUCTION",
    "AGENT-INFERRED",
    "UNKNOWN",
    "GENERATED-TEST-INPUT",
    "GENERATED-TEST-OUTPUT",
}

MOJIBAKE_MARKERS = ("\ufffd", "\u00e2\u20ac", "\u00c2\u00a0", "\u00ef\u00bb\u00bf")


def init_run_manifest(
    path: Path,
    *,
    source: str,
    target: str,
    action: str = "guide",
) -> dict[str, Any]:
    require_action(action)
    payload = {
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "target": target,
        "requested_action": action,
        "current_stage": "initialized",
        "artifacts": {},
        "errors": [],
    }
    write_json(path, payload)
    return payload


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonicalize_json(path: Path) -> Path:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
    if markers:
        raise ValueError(f"mojibake markers found: {markers}")
    return write_json(path, json.loads(text))


def validate_json_encoding(path: Path) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append(("JSON_BOM", "UTF-8 BOM forbidden; run normalize-json"))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [("JSON_UTF8_INVALID", f"invalid UTF-8: {exc}")]
    markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
    if markers:
        errors.append(("JSON_MOJIBAKE", f"mojibake markers found: {markers}"))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(("JSON_PARSE_INVALID", f"invalid JSON: {exc}"))
        return errors
    canonical = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if text.replace("\r\n", "\n") != canonical:
        errors.append(("JSON_NONCANONICAL", "expected UTF-8, two-space indent, final newline"))
    return errors
