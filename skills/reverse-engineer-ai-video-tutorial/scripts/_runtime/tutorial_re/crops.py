from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageFilter

from .manifest import read_json, write_json
from .run_store import register_artifact, sha256_file


QA_CHECKS = (
    "source_context_verified",
    "roi_matches_label",
    "boundaries_complete",
    "readable_at_output_resolution",
    "no_required_content_clipped",
    "no_mislabeled_adjacent_content",
)

CROP_PURPOSES = (
    "prompt",
    "code",
    "settings",
    "ui",
    "typography",
    "target_output",
    "source_asset",
    "other",
)


def write_crop(
    source: Path,
    output: Path,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    scale_width: int | None = None,
    sharpen: bool = True,
) -> Path:
    image = Image.open(source).convert("RGB")
    if min(x, y, width, height) < 0 or width == 0 or height == 0:
        raise ValueError("crop geometry must be positive")
    if x + width > image.width or y + height > image.height:
        raise ValueError("crop exceeds source bounds")

    cropped = image.crop((x, y, x + width, y + height))
    if scale_width and scale_width != cropped.width:
        scale_height = max(1, round(cropped.height * scale_width / cropped.width))
        cropped = cropped.resize((scale_width, scale_height), Image.Resampling.LANCZOS)
    if sharpen:
        cropped = cropped.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3))

    output.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(output)
    return output


def write_crop_evidence(
    run_dir: Path,
    source: Path,
    output: Path,
    *,
    purpose: str,
    x: int,
    y: int,
    width: int,
    height: int,
    scale_width: int | None = None,
    sharpen: bool = True,
) -> dict:
    run_dir = run_dir.resolve()
    source = source.resolve()
    output = output.resolve()
    run_manifest = run_dir / "run.json"
    if not run_manifest.is_file():
        raise ValueError("run.json missing")
    if read_json(run_manifest).get("sealed"):
        raise RuntimeError("run is sealed; create child run for corrected crop")
    source_relative = _relative_inside(source, run_dir, "source")
    output_relative = _relative_inside(output, run_dir, "output")
    if not source_relative.parts or source_relative.parts[0] != "frames":
        raise ValueError("crop source must be full source-extracted frame under run/frames")
    if not output_relative.parts or output_relative.parts[0] != "crops":
        raise ValueError("crop output must be under run/crops")
    if source == output:
        raise ValueError("crop source and output must differ")
    if not source.is_file():
        raise FileNotFoundError(f"crop source missing: {source_relative.as_posix()}")
    if output.exists() and not output.is_file():
        raise ValueError("crop output must be a file path")

    with Image.open(source) as image:
        source_width, source_height = image.size
    path = write_crop(
        source,
        output,
        x=x,
        y=y,
        width=width,
        height=height,
        scale_width=scale_width,
        sharpen=sharpen,
    )
    with Image.open(path) as image:
        output_width, output_height = image.size

    receipt_path = output.with_suffix(output.suffix + ".crop.json")
    qa_path = output.with_suffix(output.suffix + ".crop-qa.json")
    receipt_relative = receipt_path.relative_to(run_dir)
    qa_relative = qa_path.relative_to(run_dir)
    created_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "purpose": purpose,
        "source_path": source_relative.as_posix(),
        "source_sha256": sha256_file(source),
        "source_dimensions": {"width": source_width, "height": source_height},
        "crop_path": output_relative.as_posix(),
        "crop_sha256": sha256_file(path),
        "crop_box_pixels": {"x": x, "y": y, "width": width, "height": height},
        "crop_box_normalized": {
            "x": round(x / source_width, 8),
            "y": round(y / source_height, 8),
            "width": round(width / source_width, 8),
            "height": round(height / source_height, 8),
        },
        "output_dimensions": {"width": output_width, "height": output_height},
        "transform": {"scale_width": scale_width, "sharpen": sharpen},
        "qa_path": qa_relative.as_posix(),
        "created_at": created_at,
    }
    qa = {
        "schema_version": 3,
        "purpose": purpose,
        "crop_path": output_relative.as_posix(),
        "receipt_path": receipt_relative.as_posix(),
        "source_path": source_relative.as_posix(),
        "source_sha256": sha256_file(source),
        "crop_sha256": sha256_file(path),
        "inspection_method": "pending",
        "inspection_sequence": "pending",
        "blind_crop_observation": {
            "dominant_content": "",
            "visible_text": [],
            "visual_anchors": [],
            "unrelated_content": [],
            "crop_fills_semantic_target": False,
        },
        "source_context_observation": "",
        "semantic_target": "",
        "semantic_target_id": "",
        "supported_scene_ids": [],
        "target_state": "not_applicable",
        "complete_scene_state": False,
        "visible_fact_candidates": [],
        "expected_content": [],
        "observed_content": [],
        "text_coverage": "pending",
        "supported_evidence_items": [],
        "status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "verdict_rationale": "",
        "checks": {name: "pending" for name in QA_CHECKS},
        "notes": "Inspect the saved crop alone first and record literal pixels. Only then open the full source and compare with the intended claim.",
    }
    write_json(receipt_path, receipt)
    write_json(qa_path, qa)
    records = [
        register_artifact(run_dir, path, role="evidence_crop"),
        register_artifact(run_dir, receipt_path, role="crop_receipt"),
        register_artifact(run_dir, qa_path, role="crop_qa"),
    ]
    return {
        "crop": str(path),
        "receipt": str(receipt_path),
        "qa": str(qa_path),
        "status": "pending_visual_review",
        "artifacts": records,
    }


def _relative_inside(path: Path, root: Path, label: str) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"crop {label} must be inside run directory") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crop and enlarge tutorial evidence panels")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--purpose",
        choices=CROP_PURPOSES,
        required=True,
    )
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--scale-width", type=int)
    parser.add_argument("--no-sharpen", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _resolve_cli_path(run_dir: Path, candidate: Path, label: str) -> Path:
    resolved_run = run_dir.expanduser().resolve()
    raw = candidate.expanduser()
    resolved = (raw if raw.is_absolute() else resolved_run / raw).resolve()
    try:
        resolved.relative_to(resolved_run)
    except ValueError as exc:
        raise ValueError(f"crop {label} must be inside run directory") from exc
    return resolved


def main() -> int:
    args = build_parser().parse_args()
    import json

    try:
        run_dir = args.run.expanduser().resolve()
        result = write_crop_evidence(
            run_dir,
            _resolve_cli_path(run_dir, args.source, "source"),
            _resolve_cli_path(run_dir, args.output, "output"),
            purpose=args.purpose,
            x=args.x,
            y=args.y,
            width=args.width,
            height=args.height,
            scale_width=args.scale_width,
            sharpen=not args.no_sharpen,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        message = str(exc) or exc.__class__.__name__
        normalized = message.casefold()
        if any(token in normalized for token in ("inside run", "under run/crops", "escapes run")):
            error_code = "PATH_OUTSIDE_RUN"
        else:
            error_code = "INVALID_ARGUMENT"
        payload = {"ok": False, "error_code": error_code, "error": message, "details": []}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            import sys

            print(f"error: {message}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
