from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunInput:
    video_url: str
    summary_point: str
    summary_source_path: Path | None = None
    local_video_path: Path | None = None
    work_dir: Path | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    source: str = "unknown"


@dataclass(frozen=True)
class IngestResult:
    work_dir: Path
    metadata_path: Path | None
    transcript_json_path: Path | None
    transcript_vtt_path: Path | None
    video_path: Path | None
    errors: list[str] = field(default_factory=list)
    tool_resolution: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSpan:
    span_id: str
    start: float
    end: float
    score: float
    reason: str
    transcript_refs: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceFrame:
    timestamp: float
    path: Path
    source_span_id: str


@dataclass(frozen=True)
class FrameAnalysis:
    timestamp: float
    ocr_text: str
    visual_summary: str
    relevance_score: float
    supports_summary_point: bool
    notes: list[str] = field(default_factory=list)
