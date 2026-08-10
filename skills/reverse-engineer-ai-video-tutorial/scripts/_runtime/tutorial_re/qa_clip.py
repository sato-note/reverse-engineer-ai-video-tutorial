from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .contact_sheet import write_contact_sheet
from .manifest import write_json
from .models import EvidenceFrame
from .tools import require_tool


def analyze_short_clip(
    video_path: Path,
    output_dir: Path,
    *,
    scene_id: str,
    max_seconds: float = 10.1,
    fidelity_mode: str = "reference_reconstruction",
    reference_paths: list[str] | None = None,
) -> dict[str, Any]:
    metadata = _probe(video_path)
    duration = float(metadata["format"]["duration"])
    if duration > max_seconds:
        raise ValueError(f"clip duration {duration:.3f}s exceeds {max_seconds:.3f}s QA limit")

    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    integer_seconds = _integer_seconds(duration)
    frames: list[EvidenceFrame] = []

    for second in integer_seconds:
        path = frames_dir / f"t_{second:02d}.jpg"
        _extract_at(video_path, float(second), path)
        frames.append(EvidenceFrame(float(second), path, scene_id))

    final_path = frames_dir / "t_final.jpg"
    _extract_final(video_path, duration, final_path)
    frames.append(EvidenceFrame(duration, final_path, f"{scene_id}_final"))
    contact_sheet = write_contact_sheet(frames, output_dir / "contact_sheet.jpg")

    audio = _probe_audio(video_path, metadata)
    metadata_path = output_dir / "metadata.json"
    write_json(metadata_path, metadata)

    record = {
        "version": 2,
        "scene_id": scene_id,
        "fidelity_mode": fidelity_mode,
        "video_path": str(video_path),
        "duration_seconds": round(duration, 3),
        "qa_dir": str(output_dir),
        "frame_seconds": integer_seconds,
        "final_frame_path": str(final_path),
        "contact_sheet_path": str(contact_sheet) if contact_sheet else None,
        "metadata_path": str(metadata_path),
        "audio_probe": audio,
        "per_second": [
            {
                "second": second,
                "path": str(frames_dir / f"t_{second:02d}.jpg"),
                "observed": "",
                "result": "pending",
            }
            for second in integer_seconds
        ],
        "final": {"path": str(final_path), "observed": "", "result": "pending"},
        "comparison": {
            "reference_paths": reference_paths or [],
            "checkpoints": [],
        },
        "gates": {
            "reference_composition": "pending",
            "asset_fidelity": "pending",
            "identity": "pending",
            "typography": "pending",
            "motion_topology": "pending",
            "scene_content": "pending",
            "artifacts": "pending",
            "audio": "pending",
            "final_state": "pending",
        },
        "status": "pending_visual_review",
        "failed_constraints": [],
        "next_prompt_revision": "",
    }
    write_json(output_dir / "qa.json", record)
    return record


def _integer_seconds(duration: float) -> list[int]:
    count = max(1, math.ceil(max(0.0, duration - 0.05)))
    return list(range(count))


def _probe(video_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            *require_tool("ffprobe"),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _extract_at(video_path: Path, second: float, output: Path) -> None:
    subprocess.run(
        [
            *require_tool("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-ss",
            f"{second:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
    )


def _extract_final(video_path: Path, duration: float, output: Path) -> None:
    _extract_at(video_path, max(0.0, duration - 0.1), output)


def _probe_audio(video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    has_audio = any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", []))
    result: dict[str, Any] = {"stream_present": has_audio, "mean_db": None, "max_db": None}
    if not has_audio:
        return result
    completed = subprocess.run(
        [
            *require_tool("ffmpeg"),
            "-v",
            "info",
            "-i",
            str(video_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            os.devnull,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = completed.stderr
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", output)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", output)
    result["mean_db"] = float(mean.group(1)) if mean else None
    result["max_db"] = float(peak.group(1)) if peak else None
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract QA evidence from a generated clip up to 10s")
    parser.add_argument("video", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--max-seconds", type=float, default=10.1)
    parser.add_argument(
        "--fidelity-mode",
        choices=("method_only", "style_match", "reference_reconstruction"),
        default="reference_reconstruction",
    )
    parser.add_argument("--reference", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = analyze_short_clip(
        args.video,
        args.output_dir,
        scene_id=args.scene_id,
        max_seconds=args.max_seconds,
        fidelity_mode=args.fidelity_mode,
        reference_paths=args.reference,
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
