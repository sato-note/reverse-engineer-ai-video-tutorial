from __future__ import annotations

import json
import re
from pathlib import Path

from .manifest import write_json
from .models import TranscriptSegment


TIMECODE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{3})"
)


def load_transcript_file(path: Path) -> list[TranscriptSegment]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            raw = raw.get("segments", [])
        return [
            TranscriptSegment(
                start=float(item["start"]),
                end=float(item.get("end", float(item["start"]) + float(item.get("duration", 0.0)))),
                text=str(item["text"]).replace("\n", " ").strip(),
                source=str(item.get("source", "supplied_json")),
            )
            for item in raw
        ]
    if suffix not in {".vtt", ".srt"}:
        raise ValueError(f"unsupported transcript format: {suffix}")
    return _parse_timed_text(path.read_text(encoding="utf-8-sig"), source=f"supplied_{suffix[1:]}")


def write_transcript_json(path: Path, segments: list[TranscriptSegment]) -> Path:
    payload = [
        {"start": item.start, "end": item.end, "text": item.text, "source": item.source}
        for item in segments
    ]
    write_json(path, payload)
    return path


def write_transcript_vtt(path: Path, segments: list[TranscriptSegment]) -> Path:
    lines = ["WEBVTT", ""]
    for item in segments:
        lines.extend([f"{_format_time(item.start)} --> {_format_time(item.end)}", item.text, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _parse_timed_text(text: str, *, source: str) -> list[TranscriptSegment]:
    lines = text.replace("\r\n", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        match = TIMECODE_RE.search(lines[index])
        if not match:
            index += 1
            continue
        start = _parse_time(match.group("start"))
        end = _parse_time(match.group("end"))
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            body.append(re.sub(r"<[^>]+>", "", lines[index].strip()))
            index += 1
        value = " ".join(body).strip()
        if value:
            segments.append(TranscriptSegment(start=start, end=end, text=value, source=source))
        index += 1
    return segments


def _parse_time(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _format_time(seconds: float) -> str:
    millis_total = max(0, round(seconds * 1000))
    millis = millis_total % 1000
    total = millis_total // 1000
    secs = total % 60
    minutes_total = total // 60
    minutes = minutes_total % 60
    hours = minutes_total // 60
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
