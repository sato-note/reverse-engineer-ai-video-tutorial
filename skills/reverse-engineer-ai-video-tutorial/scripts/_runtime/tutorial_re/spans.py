from __future__ import annotations

import math
import re
from pathlib import Path

from .manifest import read_json, write_json
from .models import CandidateSpan, TranscriptSegment


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
}


def load_transcript(path: Path) -> list[TranscriptSegment]:
    raw = read_json(path)
    return [
        TranscriptSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item["text"]),
            source=str(item.get("source", "unknown")),
        )
        for item in raw
    ]


def find_candidate_spans(
    segments: list[TranscriptSegment],
    summary_point: str,
    *,
    window_seconds: float = 45.0,
    stride_seconds: float = 15.0,
    top_k: int = 8,
) -> list[CandidateSpan]:
    if not segments:
        return []
    query_tokens = _tokens(summary_point)
    if not query_tokens:
        return []

    duration = max(segment.end for segment in segments)
    starts = _window_starts(duration, window_seconds, stride_seconds)
    scored: list[CandidateSpan] = []
    for idx, start in enumerate(starts):
        end = min(duration, start + window_seconds)
        refs = [
            seg_idx
            for seg_idx, segment in enumerate(segments)
            if segment.end >= start and segment.start <= end
        ]
        text = " ".join(segments[i].text for i in refs)
        score, reason = _score_text(query_tokens, text)
        if score <= 0:
            continue
        scored.append(
            CandidateSpan(
                span_id=f"span_{idx:03}",
                start=round(start, 3),
                end=round(end, 3),
                score=round(score, 4),
                reason=reason,
                transcript_refs=refs,
            )
        )

    ranked = sorted(scored, key=lambda span: (-span.score, span.start))
    return _dedupe_overlapping(ranked, top_k=top_k)


def write_candidate_spans(path: Path, spans: list[CandidateSpan]) -> None:
    payload = [
        {
            "span_id": span.span_id,
            "start": span.start,
            "end": span.end,
            "score": span.score,
            "reason": span.reason,
            "transcript_refs": span.transcript_refs,
        }
        for span in spans
    ]
    write_json(path, payload)


def read_candidate_spans(path: Path) -> list[CandidateSpan]:
    raw = read_json(path)
    return [
        CandidateSpan(
            span_id=str(item["span_id"]),
            start=float(item["start"]),
            end=float(item["end"]),
            score=float(item["score"]),
            reason=str(item["reason"]),
            transcript_refs=[int(ref) for ref in item.get("transcript_refs", [])],
        )
        for item in raw
    ]


def _score_text(query_tokens: set[str], text: str) -> tuple[float, str]:
    text_tokens = _tokens(text)
    overlap = query_tokens & text_tokens
    if not overlap:
        return 0.0, "no token overlap"
    recall = len(overlap) / len(query_tokens)
    density = len(overlap) / math.sqrt(max(len(text_tokens), 1))
    score = recall * 0.75 + density * 0.25
    reason = "matched: " + ", ".join(sorted(overlap)[:12])
    return score, reason


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
    return {token for token in raw if token not in STOPWORDS}


def _window_starts(duration: float, window_seconds: float, stride_seconds: float) -> list[float]:
    if duration <= window_seconds:
        return [0.0]
    starts: list[float] = []
    cur = 0.0
    while cur < duration:
        starts.append(cur)
        cur += stride_seconds
    final_start = max(0.0, duration - window_seconds)
    if final_start not in starts:
        starts.append(final_start)
    return starts


def _dedupe_overlapping(spans: list[CandidateSpan], *, top_k: int) -> list[CandidateSpan]:
    selected: list[CandidateSpan] = []
    for span in spans:
        if any(_overlap_ratio(span, existing) > 0.6 for existing in selected):
            continue
        selected.append(span)
        if len(selected) >= top_k:
            break
    return selected


def _overlap_ratio(a: CandidateSpan, b: CandidateSpan) -> float:
    overlap = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shortest = max(0.001, min(a.end - a.start, b.end - b.start))
    return overlap / shortest
