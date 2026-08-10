from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .manifest import write_json
from .models import IngestResult, TranscriptSegment
from .paths import ensure_run_dirs, video_id_from_url
from .transcripts import write_transcript_json, write_transcript_vtt
from .tools import probe_tool, require_tool


DEFAULT_LANGS = ["en", "en-US", "en-GB"]
SOURCE_CACHE_FILES = (
    "metadata.json",
    "transcript.json",
    "transcript.vtt",
    "source.mp4",
    "source.webm",
    "source.mkv",
    "source.mov",
)


def hydrate_source_cache(
    source_cache_root: Path,
    source_id: str,
    work_dir: Path,
) -> dict[str, Any]:
    """Link immutable source inputs into a new workspace run."""
    source_dir = source_cache_root.expanduser().resolve() / source_id / "source"
    result: dict[str, Any] = {
        "root": str(source_cache_root.expanduser().resolve()),
        "source_dir": str(source_dir),
        "status": "miss",
        "files": [],
    }
    ensure_run_dirs(work_dir)
    local_names: set[str] = set()
    for name in SOURCE_CACHE_FILES:
        destination = work_dir / name
        if destination.is_file():
            local_names.add(name)
            result["files"].append(
                {"name": name, "method": "local-reuse", "bytes": destination.stat().st_size}
            )
    if not source_dir.is_dir():
        if local_names:
            result["status"] = "local-hit"
        return result

    hydrated = False
    for name in SOURCE_CACHE_FILES:
        source = source_dir / name
        if not source.is_file() or name in local_names:
            continue
        destination = work_dir / name
        try:
            os.link(source, destination)
            method = "hardlink"
        except OSError:
            shutil.copy2(source, destination)
            method = "copy"
        hydrated = True
        result["files"].append(
            {"name": name, "method": method, "bytes": destination.stat().st_size}
        )
    if local_names and hydrated:
        result["status"] = "mixed-hit"
    elif local_names:
        result["status"] = "local-hit"
    elif hydrated:
        result["status"] = "shared-hit"
    return result


def run_ingest(
    video_url: str | None,
    work_dir: Path,
    *,
    local_video_path: Path | None = None,
    download_video: bool = False,
    fetch_transcript: bool = True,
) -> IngestResult:
    ensure_run_dirs(work_dir)
    errors: list[str] = []
    tool_resolution = {}
    if video_url:
        tool_resolution["yt-dlp"] = probe_tool("yt-dlp", python_module="yt_dlp").as_dict()

    cached_metadata = work_dir / "metadata.json"
    metadata_path = cached_metadata if cached_metadata.is_file() else None
    if video_url and metadata_path is None:
        metadata_path = _try_write_metadata(video_url, work_dir, errors)
    transcript_json_path: Path | None = None
    transcript_vtt_path: Path | None = None
    if fetch_transcript and video_url:
        cached_json = work_dir / "transcript.json"
        cached_vtt = work_dir / "transcript.vtt"
        if cached_json.is_file():
            transcript_json_path = cached_json
            transcript_vtt_path = cached_vtt if cached_vtt.is_file() else None
        else:
            segments = _try_fetch_transcript(video_url, errors)
            if segments:
                transcript_json_path = cached_json
                transcript_vtt_path = cached_vtt
                write_transcript_json(transcript_json_path, segments)
                write_transcript_vtt(transcript_vtt_path, segments)

    video_path: Path | None = _resolve_existing_video(work_dir, local_video_path, errors)
    if download_video and video_path is None and video_url:
        video_path = _try_download_video(video_url, work_dir, errors)
    elif download_video and video_path is None:
        errors.append("download: --download-video requires --video-url")

    result = IngestResult(
        work_dir=work_dir,
        metadata_path=metadata_path,
        transcript_json_path=transcript_json_path,
        transcript_vtt_path=transcript_vtt_path,
        video_path=video_path,
        errors=errors,
        tool_resolution=tool_resolution,
    )
    _write_ingest_summary(work_dir / "ingest.json", result)
    return result


def _try_write_metadata(video_url: str, work_dir: Path, errors: list[str]) -> Path | None:
    try:
        completed = subprocess.run(
            [*require_tool("yt-dlp", python_module="yt_dlp"), "--dump-json", "--skip-download", "--no-warnings", video_url],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        path = work_dir / "metadata.json"
        write_json(path, payload)
        return path
    except Exception as exc:
        errors.append(f"metadata: {type(exc).__name__}: {exc}")
        return None


def _try_fetch_transcript(video_url: str, errors: list[str]) -> list[TranscriptSegment]:
    video_id = video_id_from_url(video_url)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            raw = YouTubeTranscriptApi().fetch(video_id, languages=DEFAULT_LANGS)
        except Exception:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=DEFAULT_LANGS)

        segments: list[TranscriptSegment] = []
        for item in raw:
            text = _field(item, "text")
            start = float(_field(item, "start"))
            duration = float(_field(item, "duration", 0.0))
            segments.append(
                TranscriptSegment(
                    start=start,
                    end=start + duration,
                    text=str(text).replace("\n", " ").strip(),
                    source="youtube_transcript_api",
                )
            )
        return segments
    except Exception as exc:
        errors.append(f"transcript: {type(exc).__name__}: {exc}")
        return []


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _try_download_video(video_url: str, work_dir: Path, errors: list[str]) -> Path | None:
    output = work_dir / "source.%(ext)s"
    try:
        subprocess.run(
            [
                *require_tool("yt-dlp", python_module="yt_dlp"),
                "-f",
                "bv*+ba/b",
                "--merge-output-format",
                "mp4",
                "-o",
                str(output),
                video_url,
            ],
            check=True,
        )
        mp4 = work_dir / "source.mp4"
        if mp4.exists():
            return mp4
        candidates = sorted(work_dir.glob("source.*"))
        return candidates[0] if candidates else None
    except Exception as exc:
        errors.append(f"download: {type(exc).__name__}: {exc}")
        return None


def _resolve_existing_video(
    work_dir: Path,
    local_video_path: Path | None,
    errors: list[str],
) -> Path | None:
    if local_video_path:
        if local_video_path.exists():
            return local_video_path
        errors.append(f"local_video: not found: {local_video_path}")
        return None
    for pattern in ("source.mp4", "source.webm", "source.mkv", "source.mov"):
        candidate = work_dir / pattern
        if candidate.exists():
            return candidate
    return None


def _write_transcript_json(path: Path, segments: list[TranscriptSegment]) -> None:
    payload = [
        {"start": s.start, "end": s.end, "text": s.text, "source": s.source}
        for s in segments
    ]
    write_json(path, payload)


def _write_transcript_vtt(path: Path, segments: list[TranscriptSegment]) -> None:
    lines = ["WEBVTT", ""]
    for segment in segments:
        lines.extend(
            [
                f"{_fmt_vtt_time(segment.start)} --> {_fmt_vtt_time(segment.end)}",
                segment.text,
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _fmt_vtt_time(seconds: float) -> str:
    millis_total = max(0, round(seconds * 1000))
    millis = millis_total % 1000
    total_seconds = millis_total // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02}:{mins:02}:{secs:02}.{millis:03}"


def _write_ingest_summary(path: Path, result: IngestResult) -> None:
    payload = {
        "work_dir": str(result.work_dir),
        "metadata_path": str(result.metadata_path) if result.metadata_path else None,
        "transcript_json_path": str(result.transcript_json_path) if result.transcript_json_path else None,
        "transcript_vtt_path": str(result.transcript_vtt_path) if result.transcript_vtt_path else None,
        "video_path": str(result.video_path) if result.video_path else None,
        "tool_resolution": result.tool_resolution,
        "errors": result.errors,
    }
    write_json(path, payload)
