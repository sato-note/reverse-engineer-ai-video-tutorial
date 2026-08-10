from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .contact_sheet import write_contact_sheet
from .contracts import INTERNAL_STAGES, PUBLIC_ACTIONS, STOP_POINTS, TARGET_CHOICES, VALIDATION_STAGES
from .frames import (
    extract_span_frames,
    extract_timestamp_frames,
    safe_video_end,
    uniform_timestamps,
    write_frame_manifest,
)
from .ingest import hydrate_source_cache, run_ingest
from .manifest import canonicalize_json, read_json, write_json
from .models import EvidenceFrame, RunInput
from .paths import video_id_from_url
from .report import write_report
from .run_store import create_run, register_artifact, sha256_file, source_id_for_file, update_run
from .spans import find_candidate_spans, load_transcript, write_candidate_spans
from .transcripts import load_transcript_file, write_transcript_json, write_transcript_vtt
from .tools import require_tool


def _default_source_cache_root() -> Path:
    configured = os.environ.get("TUTORIAL_RE_SOURCE_CACHE")
    return Path(configured) if configured else Path.home() / ".cache" / "tutorial-re"


def _guide_requires_initial_frames(args: argparse.Namespace) -> bool:
    return args.action == "guide" and args.stop_after == "guide"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI tutorial workflow reverse engineering")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check runtime capabilities")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--profile", choices=("base", "local-guide", "youtube-guide", "recreate", "remotion", "hyperframes"), default="base")
    doctor.add_argument("--workspace-root", type=Path)
    doctor.add_argument("--cache-root", type=Path)
    doctor.add_argument("--install-root", type=Path)
    doctor.add_argument("--runtime", choices=("auto", "managed", "system"), default=None)
    doctor.add_argument("--all-profiles", action="store_true")

    ingest = commands.add_parser("ingest", help="Create immutable evidence run")
    source = ingest.add_mutually_exclusive_group(required=True)
    source.add_argument("--video-url")
    source.add_argument("--video-file", type=Path)
    ingest.add_argument("--target", required=True)
    ingest.add_argument("--summary-source", type=Path)
    ingest.add_argument("--transcript", type=Path)
    ingest.add_argument("--cache-root", type=Path, default=Path("cache"))
    ingest.add_argument("--workspace-root", type=Path)
    ingest.add_argument(
        "--source-cache-root",
        type=Path,
        default=_default_source_cache_root(),
        help="Reusable immutable source bundle root; analysis outputs remain under --cache-root",
    )
    ingest.add_argument("--download-video", action="store_true")
    ingest.add_argument("--extract-frames", action="store_true")
    ingest.add_argument("--timestamps", help="Comma-separated seconds")
    ingest.add_argument("--uniform-seconds", type=float)
    ingest.add_argument("--section-start", type=float)
    ingest.add_argument("--section-end", type=float)
    ingest.add_argument("--timestamp-label", default="manual")
    ingest.add_argument("--frames-per-span", type=int, default=3)
    ingest.add_argument("--top-k", type=int, default=8)
    ingest.add_argument("--window-seconds", type=float, default=45.0)
    ingest.add_argument("--stride-seconds", type=float, default=15.0)
    ingest.add_argument("--skip-transcript", action="store_true")
    ingest.add_argument("--strict", action="store_true")
    ingest.add_argument("--json", action="store_true")
    ingest.add_argument("--action", choices=PUBLIC_ACTIONS, default="guide")
    ingest.add_argument("--stop-after", choices=STOP_POINTS, default="guide")
    ingest.add_argument("--parent-run-id")

    validate = commands.add_parser("validate", help="Validate run stage")
    validate.add_argument("--run", type=Path, required=True)
    validate.add_argument("--stage", choices=VALIDATION_STAGES, required=True)
    validate.add_argument("--json", action="store_true")

    validate_delivery = commands.add_parser(
        "validate-scene-delivery",
        help="Validate durable Recreate assets before completion or external-provider approval",
    )
    validate_delivery.add_argument("--scene-dir", type=Path, required=True)
    validate_delivery.add_argument("--catalog", type=Path, required=True)
    validate_delivery.add_argument("--json", action="store_true")

    start_recreate = commands.add_parser(
        "start-recreate",
        help="Resolve scene, validate published guide, and lock exact production route before generation",
    )
    start_recreate.add_argument("--workspace-root", type=Path, required=True)
    start_recreate.add_argument("--source-id", required=True)
    start_recreate.add_argument("--target", required=True)
    start_recreate.add_argument("--json", action="store_true")

    detail = commands.add_parser("extract-detail", help="Extract semantically selected pass-2 frames")
    detail.add_argument("--run", type=Path, required=True)
    detail_source = detail.add_mutually_exclusive_group(required=True)
    detail_source.add_argument("--timestamps", help="Additional semantic timestamps")
    detail_source.add_argument("--range", dest="detail_range", help="Full selected range: start:end")
    detail.add_argument("--section-id", help="Required with --range")
    detail.add_argument("--threshold", type=float, default=0.20)
    detail.add_argument("--label", default="detail")
    detail.add_argument("--json", action="store_true")

    review = commands.add_parser("review", help="Record guide review")
    review.add_argument("--run", type=Path, required=True)
    review.add_argument("--decision", choices=("approve", "reject"), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--correction", action="append", default=[])
    review.add_argument("--json", action="store_true")

    prepare = commands.add_parser("prepare-scene", help="Create scene preparation scaffold")
    prepare.add_argument("--run", type=Path, required=True)
    prepare.add_argument("--target-choice", choices=TARGET_CHOICES, default="match")
    prepare.add_argument("--json", action="store_true")

    publish = commands.add_parser("publish-guide", help="Publish durable guide outside cache")
    publish.add_argument("--run", type=Path, required=True)
    publish.add_argument("--workspace-root", type=Path, required=True)
    publish.add_argument("--json", action="store_true")

    artifact = commands.add_parser("artifact", help="Register current artifact hash")
    artifact.add_argument("--run", type=Path, required=True)
    artifact.add_argument("--path", type=Path, required=True)
    artifact.add_argument("--role", required=True)
    artifact.add_argument("--json", action="store_true")

    normalize = commands.add_parser("normalize-json", help="Canonicalize JSON and refresh artifact hash")
    normalize.add_argument("--run", type=Path, required=True)
    normalize.add_argument("--path", type=Path, required=True)
    normalize.add_argument("--role", required=True)
    normalize.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return _dispatch(args)
    except SystemExit as exc:
        if exc.code in (None, 0):
            raise
        return _emit_cli_error(args, str(exc) or "command failed")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        return _emit_cli_error(args, str(exc) or exc.__class__.__name__)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "ingest":
        return _run_ingest_command(args)
    if args.command == "doctor":
        from .doctor import doctor_report

        report = doctor_report(
            args.profile,
            workspace_root=args.workspace_root,
            cache_root=args.cache_root,
            install_root=args.install_root,
            runtime=args.runtime,
            all_profiles=args.all_profiles,
        )
        print(json.dumps(report, indent=2) if args.json else _doctor_text(report))
        return 0 if report["state"] in {"ready", "ready_with_warnings", "needs_context"} else 2
    if args.command == "validate":
        from .validate import validate_stage

        result = validate_stage(args.run, args.stage)
        if result["valid"]:
            _advance_validated_stage(args.run, args.stage)
        return _emit_validation_result(result, args)
    if args.command == "validate-scene-delivery":
        from .validate import validate_scene_delivery

        result = validate_scene_delivery(args.scene_dir, args.catalog)
        return _emit_validation_result(result, args, stage="scene-delivery")
    if args.command == "start-recreate":
        from .workflows import start_recreate

        try:
            result = start_recreate(
                args.workspace_root,
                source_id=args.source_id,
                target=args.target,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "extract-detail":
        return _run_extract_detail(args)
    if args.command == "review":
        from .workflows import write_guide_review

        result = write_guide_review(
            args.run,
            decision=args.decision,
            reviewer=args.reviewer,
            required_corrections=args.correction,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "prepare-scene":
        from .workflows import create_scene_scaffold

        print(json.dumps(create_scene_scaffold(args.run, target_choice=args.target_choice), indent=2))
        return 0
    if args.command == "publish-guide":
        from .workflows import publish_guide

        print(json.dumps(publish_guide(args.run, args.workspace_root), indent=2))
        return 0
    if args.command == "artifact":
        path = args.path if args.path.is_absolute() else args.run / args.path
        print(json.dumps(register_artifact(args.run, path, role=args.role), indent=2))
        return 0
    if args.command == "normalize-json":
        run_dir = args.run.resolve()
        path = args.path if args.path.is_absolute() else run_dir / args.path
        path = path.resolve()
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise SystemExit("JSON path must stay inside run") from exc
        canonicalize_json(path)
        print(json.dumps(register_artifact(run_dir, path, role=args.role), indent=2))
        return 0
    raise AssertionError(args.command)


def _emit_validation_result(
    result: dict[str, object],
    args: argparse.Namespace,
    *,
    stage: str | None = None,
) -> int:
    if result.get("valid"):
        print(json.dumps({"ok": True, **result}, indent=2))
        return 0
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    code = "VALIDATION_FAILED"
    if any(
        isinstance(item, dict)
        and item.get("code") in {"ARTIFACT_HASH_MISMATCH", "ARTIFACT_MISSING", "PUBLIC_GUIDE_STALE"}
        for item in errors
    ):
        code = "ARTIFACT_STALE"
    message = f"{stage or result.get('stage', 'validation')} failed"
    payload = {
        "ok": False,
        "error_code": code,
        "error": message,
        "details": errors,
        **result,
    }
    print(json.dumps(payload, indent=2))
    return 2


def _emit_cli_error(args: argparse.Namespace, message: str) -> int:
    normalized = message.casefold()
    if args.command == "publish-guide" and "preflight" in normalized:
        error_code = "PUBLICATION_PREFLIGHT_FAILED"
    elif any(token in normalized for token in ("inside run", "inside the run", "under run/crops", "escapes run", "outside run")):
        error_code = "PATH_OUTSIDE_RUN"
    elif "hash mismatch" in normalized or "stale" in normalized:
        error_code = "ARTIFACT_STALE"
    elif args.command in {"validate", "validate-scene-delivery"} or "validation" in normalized:
        error_code = "VALIDATION_FAILED"
    else:
        error_code = "INVALID_ARGUMENT"
    payload = {
        "ok": False,
        "error_code": error_code,
        "error": message,
        "details": [],
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _run_ingest_command(args: argparse.Namespace) -> int:
    skill_root = Path(__file__).resolve().parents[3]
    try:
        Path.cwd().resolve().relative_to(skill_root)
        running_inside_skill = True
    except ValueError:
        running_inside_skill = False
    if not args.cache_root.is_absolute() and running_inside_skill:
        raise SystemExit(
            "refusing to write cache inside installed skill; run from user workspace "
            "and pass an absolute --cache-root <workspace>/cache"
        )
    if args.video_file and not args.video_file.is_file():
        raise SystemExit(f"video file not found: {args.video_file}")
    if args.transcript and not args.transcript.is_file():
        raise SystemExit(f"transcript not found: {args.transcript}")
    if args.summary_source and not args.summary_source.is_file():
        raise SystemExit(f"summary source not found: {args.summary_source}")

    workspace_root = (
        args.workspace_root.expanduser().resolve()
        if args.workspace_root
        else args.cache_root.expanduser().resolve().parent
    )
    try:
        args.cache_root.expanduser().resolve().relative_to(workspace_root)
    except ValueError as exc:
        raise SystemExit("--cache-root must resolve inside --workspace-root") from exc
    source_id = video_id_from_url(args.video_url) if args.video_url else source_id_for_file(args.video_file)
    run = create_run(
        args.cache_root,
        source_id,
        target=args.target,
        action=args.action,
        parent_run_id=args.parent_run_id,
        config={
            "timestamps": args.timestamps,
            "uniform_seconds": args.uniform_seconds,
            "section_start": args.section_start,
            "section_end": args.section_end,
            "source_cache_root": str(args.source_cache_root.expanduser().resolve()),
            "workspace_root": str(workspace_root),
            "public_guide_required": args.stop_after == "guide",
        },
    )
    source_cache = hydrate_source_cache(
        args.source_cache_root,
        source_id,
        run.source_dir,
    )
    source_record = {
        "schema_version": 1,
        "source_id": source_id,
        "video_url": args.video_url,
        "video_file": str(args.video_file.resolve()) if args.video_file else None,
        "video_sha256": sha256_file(args.video_file) if args.video_file else None,
        "source_cache": source_cache,
    }
    write_json(run.source_dir / "source.json", source_record)

    ingest = run_ingest(
        args.video_url,
        run.source_dir,
        local_video_path=args.video_file,
        download_video=args.download_video,
        fetch_transcript=not args.skip_transcript and not args.transcript,
    )
    update_run(
        run.run_dir,
        {
            "runtime": {
                "mode": os.environ.get("TUTORIAL_RE_RUNTIME", "auto"),
                "python": str(Path(sys.executable).resolve()),
                "tools": ingest.tool_resolution,
                "source": os.environ.get("TUTORIAL_RE_RUNTIME_SOURCE", "system_compatible"),
                "verified": "managed_lock" if os.environ.get("TUTORIAL_RE_RUNTIME_SOURCE") == "managed_exact" else "feature_probe",
            }
        },
    )
    transcript_json = ingest.transcript_json_path
    transcript_vtt = ingest.transcript_vtt_path
    if args.transcript:
        segments = load_transcript_file(args.transcript)
        transcript_json = write_transcript_json(run.source_dir / "transcript.json", segments)
        transcript_vtt = write_transcript_vtt(run.source_dir / "transcript.vtt", segments)

    summary_text = args.summary_source.read_text(encoding="utf-8") if args.summary_source else ""
    target_record = {
        "target": args.target,
        "summary_source": str(args.summary_source.resolve()) if args.summary_source else None,
        "summary_sha256": sha256_file(args.summary_source) if args.summary_source else None,
        "summary_text": summary_text,
    }
    target_path = write_json(run.run_dir / "target.json", target_record)
    query = "\n".join(value for value in (args.target, summary_text) if value).strip()

    spans = []
    candidate_path: Path | None = None
    section_map_path: Path | None = None
    if transcript_json:
        transcript = load_transcript(transcript_json)
        spans = find_candidate_spans(
            transcript,
            query,
            window_seconds=args.window_seconds,
            stride_seconds=args.stride_seconds,
            top_k=args.top_k,
        )
        candidate_path = run.run_dir / "candidate_spans.json"
        write_candidate_spans(candidate_path, spans)
        section_map_path = write_json(
            run.run_dir / "section_map.json",
            {
                "schema_version": 4,
                "source_id": source_id,
                "status": "pending",
                "tutorial_summary": "",
                "showcased_output": "",
                "source_count_claims": [],
                "detailed_workflow_present": None,
                "no_detail_reason": "",
                "sections": [],
                "detail_pass": [],
            },
        )

    video_path = ingest.video_path
    frames = []
    timestamps = _parse_timestamps(args.timestamps)
    if args.uniform_seconds:
        if not video_path:
            ingest.errors.append("frames: uniform sampling requires video")
        else:
            start = args.section_start if args.section_start is not None else 0.0
            duration = _probe_duration(video_path)
            requested_end = args.section_end if args.section_end is not None else duration
            end = min(requested_end, safe_video_end(duration))
            if end < start:
                raise ValueError("section start is beyond final decodable frame")
            timestamps = uniform_timestamps(start, end, args.uniform_seconds)
    guide_requires_frames = _guide_requires_initial_frames(args)
    if args.extract_frames or guide_requires_frames or timestamps:
        if video_path:
            if timestamps:
                frames = extract_timestamp_frames(
                    video_path,
                    timestamps,
                    run.run_dir / "frames",
                    source_span_id=args.timestamp_label,
                )
            else:
                frames = extract_span_frames(
                    video_path,
                    spans,
                    run.run_dir / "frames",
                    frames_per_span=args.frames_per_span,
                )
        else:
            ingest.errors.append("frames: extraction requires available video")

    frame_manifest: Path | None = None
    contact_sheet: Path | None = None
    if frames:
        frame_manifest = run.run_dir / "evidence_frames.json"
        write_frame_manifest(frame_manifest, frames)
        contact_sheet = write_contact_sheet(frames, run.run_dir / "contact_sheet.jpg")

    evidence_path = _write_evidence_scaffold(
        run.run_dir,
        spans=spans,
        frames=frames,
        contact_sheet=contact_sheet,
        transcript_available=bool(transcript_json),
    )
    report_path = run.run_dir / "workflow.md"
    write_report(
        report_path,
        RunInput(
            video_url=args.video_url or str(args.video_file),
            summary_point=args.target,
            summary_source_path=args.summary_source,
            local_video_path=args.video_file,
            work_dir=run.run_dir,
        ),
        spans,
        frames,
    )

    for path, role in (
        (target_path, "target"),
        (candidate_path, "candidate_spans"),
        (section_map_path, "section_map"),
        (frame_manifest, "evidence_frames"),
        (contact_sheet, "contact_sheet"),
        (evidence_path, "evidence_manifest"),
        (report_path, "workflow"),
    ):
        if path:
            register_artifact(run.run_dir, path, role=role)
    warnings = list(ingest.errors)
    if not transcript_json:
        warnings.append("transcript unavailable: supply JSON/VTT/SRT; spoken evidence cannot complete")
    update_run(
        run.run_dir,
        {
            "current_stage": "evidence-scaffold",
            "source": source_record,
            "warnings": warnings,
        },
    )
    guide_path = None
    if args.stop_after == "guide":
        from .workflows import create_guide_scaffold

        guide_path = create_guide_scaffold(run.run_dir)
    payload = {
        "source_id": source_id,
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "requested_action": args.action,
        "stop_after": args.stop_after,
        "transcript": str(transcript_json) if transcript_json else None,
        "frame_count": len(frames),
        "guide": str(guide_path) if guide_path else None,
        "warnings": warnings,
        "source_cache": source_cache,
    }
    print(json.dumps(payload, indent=2))
    return 1 if args.strict and warnings else 0


def _run_extract_detail(args: argparse.Namespace) -> int:
    run_dir = args.run.expanduser().resolve()
    if not (run_dir / "run.json").is_file():
        raise SystemExit("run.json missing")
    source_dir = run_dir.parent.parent / "source"
    video_candidates = [source_dir / "source.mp4", *sorted(source_dir.glob("*.mp4"))]
    video_path = next((path for path in video_candidates if path.is_file()), None)
    if video_path is None:
        raise SystemExit("cached source video missing")
    discovery_path: Path | None = None
    if args.detail_range:
        if not args.section_id:
            raise SystemExit("--section-id required with --range")
        start, end = _parse_range(args.detail_range)
        if not 0 < args.threshold < 1:
            raise SystemExit("--threshold must be between 0 and 1")
        section_map = read_json(run_dir / "section_map.json")
        selected = {row.get("section_id") for row in section_map.get("detail_pass", [])}
        if args.section_id not in selected:
            raise SystemExit("section must be selected by section_map detail_pass")
        change_points = _discover_visual_changes(video_path, start, end, args.threshold)
        timestamps = _candidate_timestamps(start, end, change_points)
        discovery_path = run_dir / "detail_discovery.json"
        discovery = read_json(discovery_path) if discovery_path.is_file() else {
            "schema_version": 1,
            "ranges": [],
        }
        entry = {
            "section_id": args.section_id,
            "start_seconds": start,
            "end_seconds": end,
            "method": "adaptive_scene_change",
            "threshold": args.threshold,
            "change_points": change_points,
            "candidate_timestamps": timestamps,
            "status": "pending",
            "resolutions": [],
        }
        discovery["ranges"] = [
            row for row in discovery.get("ranges", []) if row.get("section_id") != args.section_id
        ] + [entry]
        write_json(discovery_path, discovery)
    else:
        timestamps = sorted(set(_parse_timestamps(args.timestamps)))
    if not timestamps or any(value < 0 for value in timestamps):
        raise SystemExit("provide non-negative semantic timestamps or range")
    new_frames = extract_timestamp_frames(
        video_path,
        timestamps,
        run_dir / "frames",
        source_span_id=args.section_id or args.label,
    )
    frame_manifest = run_dir / "evidence_frames.json"
    existing = read_json(frame_manifest) if frame_manifest.is_file() else []
    records = {
        (float(row["timestamp"]), str(row["path"])): row
        for row in existing
        if isinstance(row, dict) and isinstance(row.get("timestamp"), (int, float)) and row.get("path")
    }
    for frame in new_frames:
        relative = frame.path.relative_to(run_dir).as_posix()
        records[(frame.timestamp, relative)] = {
            "timestamp": frame.timestamp,
            "path": relative,
            "source_span_id": frame.source_span_id,
        }
    ordered_records = [records[key] for key in sorted(records)]
    write_json(frame_manifest, ordered_records)
    all_frames = [
        EvidenceFrame(
            timestamp=float(row["timestamp"]),
            path=run_dir / str(row["path"]),
            source_span_id=str(row.get("source_span_id", "detail")),
        )
        for row in ordered_records
    ]
    contact_sheet = write_contact_sheet(all_frames, run_dir / "contact_sheet.jpg")
    evidence_path = run_dir / "evidence_manifest.json"
    evidence = read_json(evidence_path)
    coverage = evidence.setdefault("coverage", [])
    known = {row.get("item") for row in coverage if isinstance(row, dict)}
    for frame in new_frames:
        item = f"detail-{args.section_id or args.label}-{frame.timestamp:010.3f}".replace(".", "_")
        if item in known:
            continue
        coverage.append({
            "item": item,
            "coverage_kind": "sampling_frame",
            "required": True,
            "timestamp": frame.timestamp,
            "evidence": [frame.path.relative_to(run_dir).as_posix()],
            "visual": "pending",
            "text": "pending",
            "extraction": "not-attempted",
            "label": "SOURCE-EVIDENCE",
            "confidence": "unknown",
            "claim": "",
            "unresolved_question": "Resolve during semantic detail pass",
            "reviewer_status": "pending",
        })
    write_json(evidence_path, evidence)
    for path, role in (
        (frame_manifest, "evidence_frames"),
        (contact_sheet, "contact_sheet"),
        (evidence_path, "evidence_manifest"),
    ):
        register_artifact(run_dir, path, role=role)
    if discovery_path:
        register_artifact(run_dir, discovery_path, role="detail_discovery")
    print(json.dumps({
        "run": str(run_dir),
        "frame_count": len(new_frames),
        "timestamps": [frame.timestamp for frame in new_frames],
    }, indent=2))
    return 0


def _parse_range(value: str) -> tuple[float, float]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise SystemExit("range must be start:end")
    start, end = (float(part.strip()) for part in parts)
    if start < 0 or end <= start:
        raise SystemExit("range must satisfy 0 <= start < end")
    return start, end


def _discover_visual_changes(video_path: Path, start: float, end: float, threshold: float) -> list[float]:
    duration = end - start
    completed = subprocess.run(
        [
            *require_tool("ffmpeg"), "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(video_path),
            "-vf", f"scale=320:-1,select='gt(scene,{threshold:.4f})',showinfo",
            "-an", "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    values = [
        round(start + float(match.group(1)), 3)
        for match in re.finditer(r"pts_time:([0-9.]+)", completed.stderr)
    ]
    kept: list[float] = []
    for value in values:
        if not kept or value - kept[-1] >= 0.75:
            kept.append(value)
    return kept


def _candidate_timestamps(start: float, end: float, changes: list[float]) -> list[float]:
    safe_end = max(start, end - 0.25)
    values = [start, safe_end]
    for change in changes:
        values.extend((max(start, change - 0.25), min(safe_end, change + 0.50)))
    ordered: list[float] = []
    for value in sorted(round(item, 3) for item in values):
        if not ordered or value - ordered[-1] >= 0.35:
            ordered.append(value)
    return ordered


def _write_evidence_scaffold(
    run_dir: Path,
    *,
    spans: list,
    frames: list,
    contact_sheet: Path | None,
    transcript_available: bool,
) -> Path:
    coverage = []
    if contact_sheet:
        coverage.append(
            {
                "item": "full-section-contact-sheet",
                "coverage_kind": "overview",
                "required": True,
                "range": [min(item.timestamp for item in frames), max(item.timestamp for item in frames)],
                "evidence": [str(contact_sheet.relative_to(run_dir))],
                "visual": "pending",
                "text": "pending",
                "extraction": "not-attempted",
                "label": "SOURCE-EVIDENCE",
                "confidence": "unknown",
                "claim": "",
                "unresolved_question": "Inspect full target section",
                "reviewer_status": "pending",
            }
        )
    for index, frame in enumerate(frames):
        coverage.append(
            {
                "item": f"anchor-{index:03}",
                "coverage_kind": "sampling_frame",
                "required": True,
                "timestamp": frame.timestamp,
                "evidence": [str(frame.path.relative_to(run_dir))],
                "visual": "pending",
                "text": "pending",
                "extraction": "not-attempted",
                "label": "SOURCE-EVIDENCE",
                "confidence": "unknown",
                "claim": "",
                "unresolved_question": "Inspect anchor and continuation",
                "reviewer_status": "pending",
            }
        )
    payload = {
        "schema_version": 1,
        "transcript_available": transcript_available,
        "candidate_spans": len(spans),
        "coverage": coverage,
        "status": "scaffold",
    }
    return write_json(run_dir / "evidence_manifest.json", payload)


def _parse_timestamps(value: str | None) -> list[float]:
    if not value:
        return []
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _advance_validated_stage(run_dir: Path, stage: str) -> None:
    run = read_json(run_dir / "run.json")
    current = run.get("current_stage")
    if current not in INTERNAL_STAGES or stage not in INTERNAL_STAGES:
        return
    if INTERNAL_STAGES.index(stage) > INTERNAL_STAGES.index(current):
        update_run(run_dir, {"current_stage": stage})


def _probe_duration(video_path: Path) -> float:
    completed = subprocess.run(
        [*require_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return float(completed.stdout.strip())


def _doctor_text(report: dict) -> str:
    lines = [f"ready: {report['ready']}"]
    for name, value in report["tools"].items():
        lines.append(f"{name}: {value.get('version') or 'missing'}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
