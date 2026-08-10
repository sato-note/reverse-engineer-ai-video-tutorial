from __future__ import annotations

from pathlib import Path

from .models import CandidateSpan, EvidenceFrame, RunInput


def write_report(
    path: Path,
    run_input: RunInput,
    spans: list[CandidateSpan],
    frames: list[EvidenceFrame],
) -> None:
    lines = [
        "# Tutorial workflow evidence report",
        "",
        "## input",
        "",
        f"- video: `{run_input.video_url}`",
        f"- summary point: {run_input.summary_point}",
        f"- summary source: `{run_input.summary_source_path}`" if run_input.summary_source_path else "- summary source: none",
        f"- local video: `{run_input.local_video_path}`" if run_input.local_video_path else "- local video: none",
        "",
        "## candidate spans",
        "",
    ]
    if not spans:
        lines.append("No candidate spans found.")
    for span in spans:
        lines.extend(
            [
                f"### {span.span_id}",
                "",
                f"- time: `{_fmt_seconds(span.start)}–{_fmt_seconds(span.end)}`",
                f"- score: `{span.score}`",
                f"- reason: {span.reason}",
                f"- transcript refs: `{span.transcript_refs[:12]}`",
                "",
            ]
        )

    lines.extend(["## frames", ""])
    if not frames:
        lines.append("No frames extracted. Pass `--download-video --extract-frames` or `--local-video-path ... --extract-frames`.")
    for frame in frames:
        lines.append(f"- `{_fmt_seconds(frame.timestamp)}` {frame.source_span_id}: `{frame.path}`")

    lines.extend(
        [
            "",
            "## Codex visual pass",
            "",
            "After frame extraction, Codex inspects `contact_sheet.jpg` or individual frame files via image view.",
            "No separate OCR/VLM API assumed.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02}:{secs:05.2f}"
