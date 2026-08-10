from __future__ import annotations

import subprocess
from pathlib import Path

from .manifest import write_json
from .models import CandidateSpan, EvidenceFrame
from .tools import require_tool


def extract_span_frames(
    video_path: Path,
    spans: list[CandidateSpan],
    frames_dir: Path,
    *,
    frames_per_span: int = 3,
) -> list[EvidenceFrame]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[EvidenceFrame] = []
    for span in spans:
        for timestamp in _sample_timestamps(span.start, span.end, frames_per_span):
            out_path = frames_dir / f"{span.span_id}_{timestamp:010.3f}.jpg".replace(".", "_")
            out_path = out_path.with_suffix(".jpg")
            _extract_frame(video_path, timestamp, out_path)
            frames.append(EvidenceFrame(timestamp=timestamp, path=out_path, source_span_id=span.span_id))
    return frames


def extract_timestamp_frames(
    video_path: Path,
    timestamps: list[float],
    frames_dir: Path,
    *,
    source_span_id: str = "manual",
) -> list[EvidenceFrame]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[EvidenceFrame] = []
    for index, timestamp in enumerate(timestamps):
        out_path = frames_dir / f"{source_span_id}_{timestamp:010.3f}.jpg".replace(".", "_")
        out_path = out_path.with_suffix(".jpg")
        try:
            _extract_frame(video_path, timestamp, out_path)
        except subprocess.CalledProcessError:
            out_path.unlink(missing_ok=True)
            if frames and index == len(timestamps) - 1:
                break
            raise
        frames.append(EvidenceFrame(timestamp=timestamp, path=out_path, source_span_id=source_span_id))
    return frames


def uniform_timestamps(start: float, end: float, interval: float) -> list[float]:
    if interval <= 0:
        raise ValueError("interval must be positive")
    if end < start:
        raise ValueError("end must be greater than or equal to start")
    timestamps: list[float] = []
    current = start
    while current <= end + 1e-9:
        timestamps.append(round(current, 3))
        current += interval
    if not timestamps or timestamps[-1] < round(end, 3):
        timestamps.append(round(end, 3))
    return timestamps


def safe_video_end(duration: float, *, margin: float = 0.25) -> float:
    if duration <= 0:
        raise ValueError("duration must be positive")
    if margin <= 0:
        raise ValueError("margin must be positive")
    return round(max(0.0, duration - min(margin, duration / 2)), 3)


def write_frame_manifest(path: Path, frames: list[EvidenceFrame]) -> None:
    payload = [
        {
            "timestamp": frame.timestamp,
            "path": str(frame.path),
            "source_span_id": frame.source_span_id,
        }
        for frame in frames
    ]
    write_json(path, payload)


def _sample_timestamps(start: float, end: float, count: int) -> list[float]:
    if count <= 1 or end <= start:
        return [round(start, 3)]
    step = (end - start) / (count + 1)
    return [round(start + step * (idx + 1), 3) for idx in range(count)]


def _extract_frame(video_path: Path, timestamp: float, out_path: Path) -> None:
    subprocess.run(
        [
            *require_tool("ffmpeg"),
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
