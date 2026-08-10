from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from .contracts import FIDELITY_POLICIES, VALIDATION_STAGES
from .manifest import EVIDENCE_LABELS, read_json, validate_json_encoding
from .run_store import sha256_file, verify_artifacts


CROP_QA_CHECKS = {
    "source_context_verified",
    "roi_matches_label",
    "boundaries_complete",
    "readable_at_output_resolution",
    "no_required_content_clipped",
    "no_mislabeled_adjacent_content",
}

CROP_PURPOSES = {
    "prompt", "code", "settings", "ui", "typography",
    "target_output", "source_asset", "other",
}

SEMANTIC_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "full", "in", "into", "is", "it", "of", "on", "or", "scene", "the",
    "this", "to", "with", "visible", "shown", "shows", "image", "crop",
}

EVIDENCE_KINDS = {"overview", "sampling_frame", "demonstrated_unit", "detail"}
SEQUENCE_KINDS = {
    "single_scene", "multi_scene", "prompt_carousel", "storyboard",
    "finished_sequence", "workflow_only", "unknown",
}
MULTI_SCENE_KINDS = {"multi_scene", "prompt_carousel", "storyboard", "finished_sequence"}
UNIT_KINDS = {
    "prompt_card", "result", "prompt_result_pair", "shot", "continuation",
    "comparison", "storyboard_panel", "setup", "other",
}
UNIT_DISPOSITIONS = {"cataloged", "merged", "non_scene"}
CHANGE_TYPES = {
    "section_start", "prompt", "result", "shot_goal", "composition", "text",
    "camera", "audio", "transition", "continuation", "none",
}
HARD_CHANGE_TYPES = {"prompt", "result", "shot_goal", "composition", "text", "transition"}
CHANGE_DISPOSITIONS = {"new_scene", "same_scene", "non_scene"}
PROMPT_EXTRACTIONS = {
    "exact", "detailed_paraphrase", "condensed_reconstruction", "not_applicable", "unknown",
}
SECTION_ROLES = {
    "context", "method", "workflow_breakdown", "showcase_production",
    "demonstration", "comparison", "conclusion", "other",
}
DETAIL_LEVELS = {"overview", "workflow_detail"}
WORKFLOW_ASSET_ROLES = {
    "style_reference", "scene_start_image", "character_reference", "object_reference",
    "layout_reference", "source_upload", "background", "font", "palette",
    "scene_target_reference", "prompt_reference", "media_clip", "other",
}
PRODUCTION_ACTIONS = {
    "imagegen_reconstruct", "imagegen_generate", "reuse_source", "code_native",
    "controlled_text", "bundled_font", "external_media",
}
CODE_NATIVE_KINDS = {"chart", "counter", "arrow", "simple_geometry", "layout", "data_visualization"}
PIPELINE_ROLES = {"input", "shared_input", "target_reference", "prompt_reference"}
ASSET_SOURCE_KINDS = {"isolated_source_file", "composite_only", "code_native", "unshown", "reference_only"}
ASSET_DELIVERABLE_KINDS = {"source_file", "generated_raster", "code_component", "media_file", "reference_only"}
OCCURRENCE_KINDS = {"prompt", "build", "preview", "final_result", "beat_sheet", "motion_sample", "other"}
ASSET_EVIDENCE_ROLES = {
    "shown_input", "target_component", "construction_spec", "prompt_mention",
    "workflow_explanation", "route_evidence", "target_output", "prompt",
}
PRODUCTION_EVIDENCE_ROLES = {"shown_input", "target_component", "construction_spec"}
PRODUCTION_TOOL_KINDS = {
    "code_video", "generative_video", "asset_generation", "audio", "assembly", "external_media",
}
GENERIC_PRODUCTION_TOOLS = {"", "unknown", "code_native", "generic", "equivalent"}
GENERIC_SCENE_ROUTES = {"unknown", "code_native", "hosted_video_model", "remotion_studio"}
COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


STAGES = VALIDATION_STAGES
FIDELITY_MODES = set(FIDELITY_POLICIES)
SEMANTIC_ASSETS = {"person", "building", "vehicle", "editorial_object"}
RASTER_ASSETS = SEMANTIC_ASSETS | {"background", "environment", "illustration", "photograph", "texture"}
SEMANTIC_ROUTES = {"image_generation"}
COMPOSITE_REFERENCE_TYPES = {"composite_frame", "full_scene_frame", "screenshot"}
IMAGE_GENERATION_INTENTS = {"source_asset_reconstruction", "style_conditioned_generation", "new_asset"}
SOURCE_RECONSTRUCTION_LOCKS = {"layout", "section_inventory", "readable_text", "palette_materials"}
SOURCE_RECONSTRUCTION_PROMPT_CONFLICTS = {
    "do not copy source layout",
    "do not copy the source layout",
    "do not copy board layout",
    "do not copy the board layout",
    "style reference only",
    "style/material reference only",
}
RASTER_ONLY_MODELS = {"pillow", "ffmpeg", "imagemagick", "opencv"}
REQUIRED_FIDELITY_GATES = {
    "reference_composition",
    "asset_fidelity",
    "identity",
    "typography",
    "motion_topology",
    "scene_content",
    "artifacts",
    "audio",
    "final_state",
}
REQUIRED_ASSET_GATES = {"identity", "silhouette", "style", "transparency", "composition", "typography"}
REQUIRED_SOURCE_RECONSTRUCTION_GATES = {
    "layout_structure", "section_inventory", "readable_text", "palette_materials", "ui_cleanup",
}


def validate_evidence_manifest(payload: dict[str, Any], *, require_complete: bool = False) -> list[str]:
    errors: list[str] = []
    coverage = payload.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        return ["coverage must be a non-empty list"] if require_complete else []
    seen_items: set[str] = set()
    demonstrated_claims: dict[str, int] = {}
    for index, row in enumerate(coverage):
        if not isinstance(row, dict):
            errors.append(f"coverage[{index}] must be an object")
            continue
        item = row.get("item")
        if not isinstance(item, str) or not item.strip():
            errors.append(f"coverage[{index}].item missing")
        elif item in seen_items:
            errors.append(f"coverage[{index}].item duplicate: {item}")
        else:
            seen_items.add(item)
        coverage_kind = row.get("coverage_kind")
        if coverage_kind not in EVIDENCE_KINDS:
            errors.append(f"coverage[{index}].coverage_kind invalid: {coverage_kind}")
        visual = row.get("visual", row.get("status"))
        if visual == "missed":
            errors.append(f"coverage[{index}] is missed")
        allowed_visual = {"covered", "uncertain", "readable", "partial", "unreadable", "pending"}
        if visual not in allowed_visual | {"missed"}:
            errors.append(f"coverage[{index}] has invalid visual/status: {visual}")
        label = row.get("label")
        if label and label not in EVIDENCE_LABELS:
            errors.append(f"coverage[{index}] has invalid label: {label}")
        if require_complete and row.get("required", True):
            if visual in {"missed", "uncertain", "pending", None}:
                errors.append(f"coverage[{index}] required visual unresolved")
            if not row.get("evidence"):
                errors.append(f"coverage[{index}] required evidence missing")
            if row.get("unresolved_question"):
                errors.append(f"coverage[{index}] unresolved question")
            if row.get("reviewer_status") not in {"reviewed", "approved"}:
                errors.append(f"coverage[{index}] reviewer status incomplete")
            claim = row.get("claim")
            if not isinstance(claim, str) or not claim.strip():
                errors.append(f"coverage[{index}] required claim missing")
            elif coverage_kind == "demonstrated_unit":
                normalized = " ".join(claim.lower().split())
                if normalized in demonstrated_claims:
                    first = demonstrated_claims[normalized]
                    errors.append(
                        f"coverage[{index}] duplicates demonstrated-unit claim from coverage[{first}]"
                    )
                else:
                    demonstrated_claims[normalized] = index
    if require_complete and payload.get("status") != "pass":
        errors.append("status must be pass")
    return errors


def validate_crop_evidence(
    run_dir: Path,
    evidence: dict[str, Any],
    *,
    require_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    run_dir = run_dir.resolve()
    run_path = run_dir / "run.json"
    run = read_json(run_path) if run_path.is_file() else {"artifacts": []}
    artifact_rows = run.get("artifacts", [])
    if not isinstance(artifact_rows, list):
        artifact_rows = []
    registered = {
        (item.get("role"), item.get("path"))
        for item in artifact_rows
        if isinstance(item, dict)
    }
    crop_refs: set[str] = set()
    crop_items: dict[str, set[str]] = {}
    crop_exact_text: dict[str, bool] = {}
    crop_claims: dict[str, list[str]] = {}
    coverage = evidence.get("coverage", [])
    if not isinstance(coverage, list):
        errors.append("coverage must be a list")
        coverage = []
    for row in coverage:
        if not isinstance(row, dict):
            errors.append("coverage row must be an object")
            continue
        row_evidence = row.get("evidence", [])
        if not isinstance(row_evidence, list):
            errors.append(f"coverage[{row.get('item', '?')}].evidence must be a list")
            continue
        for value in row_evidence:
            if not isinstance(value, str):
                continue
            relative = value.replace("\\", "/")
            if relative.startswith("crops/") and _is_image_path(relative):
                crop_refs.add(relative)
                item = row.get("item")
                if isinstance(item, str):
                    crop_items.setdefault(relative, set()).add(item)
                exact = row.get("label") == "EXACT-TRANSCRIPTION" or row.get("extraction") == "full"
                crop_exact_text[relative] = crop_exact_text.get(relative, False) or exact
                claim = row.get("claim")
                if isinstance(claim, str) and claim.strip():
                    crop_claims.setdefault(relative, []).append(claim)

    for relative in sorted(crop_refs):
        crop_path = _safe_run_path(run_dir, relative)
        prefix = f"crop {relative}"
        if crop_path is None:
            errors.append(f"{prefix} escapes run directory")
            continue
        if not crop_path.is_file():
            errors.append(f"{prefix} missing")
            continue
        receipt_relative = f"{relative}.crop.json"
        qa_relative = f"{relative}.crop-qa.json"
        receipt_path = run_dir / receipt_relative
        qa_path = run_dir / qa_relative
        if not receipt_path.is_file():
            errors.append(f"{prefix} receipt missing: {receipt_relative}")
            continue
        if not qa_path.is_file():
            errors.append(f"{prefix} QA missing: {qa_relative}")
            continue
        receipt = read_json(receipt_path)
        qa = read_json(qa_path)
        errors.extend(_validate_crop_receipt(run_dir, relative, receipt, prefix))
        errors.extend(_validate_crop_qa(
            relative,
            receipt_relative,
            receipt,
            qa,
            prefix,
            require_complete,
            expected_items=crop_items.get(relative, set()),
            exact_text_required=crop_exact_text.get(relative, False),
            expected_claims=crop_claims.get(relative, []),
        ))
        if require_complete:
            for role, path in (
                ("evidence_crop", relative),
                ("crop_receipt", receipt_relative),
                ("crop_qa", qa_relative),
            ):
                if (role, path) not in registered:
                    errors.append(f"{prefix} unregistered {role}: {path}")
    return errors


def _validate_crop_receipt(
    run_dir: Path,
    relative: str,
    receipt: dict[str, Any],
    prefix: str,
) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema_version") != 1:
        errors.append(f"{prefix} receipt schema_version must be 1")
    if receipt.get("purpose") not in CROP_PURPOSES:
        errors.append(f"{prefix} receipt purpose invalid")
    if not receipt.get("created_at"):
        errors.append(f"{prefix} receipt created_at missing")
    if receipt.get("crop_path") != relative:
        errors.append(f"{prefix} receipt crop_path mismatch")
    crop_path = run_dir / relative
    if receipt.get("crop_sha256") != sha256_file(crop_path):
        errors.append(f"{prefix} receipt crop hash mismatch")
    source_relative = receipt.get("source_path")
    source_path = _safe_run_path(run_dir, source_relative) if isinstance(source_relative, str) else None
    if source_path is None or not source_path.is_file():
        errors.append(f"{prefix} full source frame missing or unsafe")
        return errors
    if not source_relative.replace("\\", "/").startswith("frames/"):
        errors.append(f"{prefix} source must be full frame under frames/")
    if receipt.get("source_sha256") != sha256_file(source_path):
        errors.append(f"{prefix} source hash mismatch")
    try:
        with Image.open(source_path) as image:
            source_width, source_height = image.size
        with Image.open(crop_path) as image:
            crop_width, crop_height = image.size
    except OSError as exc:
        errors.append(f"{prefix} unreadable image: {exc}")
        return errors
    if receipt.get("source_dimensions") != {"width": source_width, "height": source_height}:
        errors.append(f"{prefix} source dimensions mismatch")
    if receipt.get("output_dimensions") != {"width": crop_width, "height": crop_height}:
        errors.append(f"{prefix} output dimensions mismatch")
    box = receipt.get("crop_box_pixels", {})
    values = [box.get(name) for name in ("x", "y", "width", "height")]
    valid_box = False
    if not all(isinstance(value, int) for value in values):
        errors.append(f"{prefix} pixel crop box invalid")
    else:
        x, y, width, height = values
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            errors.append(f"{prefix} pixel crop box invalid")
        elif x + width > source_width or y + height > source_height:
            errors.append(f"{prefix} pixel crop box exceeds source")
        else:
            valid_box = True
    if valid_box:
        expected_normalized = {
            "x": round(x / source_width, 8),
            "y": round(y / source_height, 8),
            "width": round(width / source_width, 8),
            "height": round(height / source_height, 8),
        }
        if receipt.get("crop_box_normalized") != expected_normalized:
            errors.append(f"{prefix} normalized crop box mismatch")
    transform = receipt.get("transform")
    if not isinstance(transform, dict) or not isinstance(transform.get("sharpen"), bool):
        errors.append(f"{prefix} transform invalid")
    elif transform.get("scale_width") is not None:
        scale_width = transform.get("scale_width")
        if not isinstance(scale_width, int) or scale_width <= 0 or crop_width != scale_width:
            errors.append(f"{prefix} scale_width/output mismatch")
    if receipt.get("qa_path") != f"{relative}.crop-qa.json":
        errors.append(f"{prefix} receipt qa_path mismatch")
    return errors


def _validate_crop_qa(
    relative: str,
    receipt_relative: str,
    receipt: dict[str, Any],
    qa: dict[str, Any],
    prefix: str,
    require_complete: bool,
    *,
    expected_items: set[str],
    exact_text_required: bool,
    expected_claims: list[str],
) -> list[str]:
    errors: list[str] = []
    if qa.get("schema_version") != 3:
        errors.append(f"{prefix} QA schema_version must be 3")
    if qa.get("purpose") != receipt.get("purpose"):
        errors.append(f"{prefix} QA purpose mismatch")
    if qa.get("crop_path") != relative or qa.get("receipt_path") != receipt_relative:
        errors.append(f"{prefix} QA path mismatch")
    if qa.get("status") not in {"pending", "pass", "reject"}:
        errors.append(f"{prefix} QA status invalid")
    if qa.get("source_path") != receipt.get("source_path"):
        errors.append(f"{prefix} QA source_path mismatch")
    if qa.get("source_sha256") != receipt.get("source_sha256"):
        errors.append(f"{prefix} QA source hash mismatch")
    if qa.get("crop_sha256") != receipt.get("crop_sha256"):
        errors.append(f"{prefix} QA crop hash mismatch")
    if qa.get("inspection_method") not in {"pending", "multimodal_blind_crop_then_source"}:
        errors.append(f"{prefix} QA inspection_method invalid")
    if qa.get("inspection_sequence") not in {"pending", "crop_first_then_source"}:
        errors.append(f"{prefix} QA inspection_sequence invalid")
    if not isinstance(qa.get("supported_scene_ids"), list):
        errors.append(f"{prefix} QA supported_scene_ids must be a list")
    if not isinstance(qa.get("visible_fact_candidates"), list):
        errors.append(f"{prefix} QA visible_fact_candidates must be a list")
    else:
        for fact_index, fact in enumerate(qa["visible_fact_candidates"]):
            if (
                not isinstance(fact, dict)
                or not isinstance(fact.get("subject"), str)
                or not fact["subject"].strip()
                or not isinstance(fact.get("value"), str)
                or not fact["value"].strip()
            ):
                errors.append(f"{prefix} QA visible_fact_candidates[{fact_index}] invalid")
    for field in ("expected_content", "observed_content", "supported_evidence_items"):
        value = qa.get(field)
        if not isinstance(value, list):
            errors.append(f"{prefix} QA {field} must be a list")
    supported_items = qa.get("supported_evidence_items")
    if isinstance(supported_items, list):
        if any(not isinstance(value, str) for value in supported_items):
            errors.append(f"{prefix} QA supported_evidence_items must be a string list")
        elif set(supported_items) != expected_items:
            errors.append(f"{prefix} QA supported_evidence_items mismatch")
    if qa.get("text_coverage") not in {"pending", "full", "partial", "unreadable", "not_applicable"}:
        errors.append(f"{prefix} QA text_coverage invalid")
    checks = qa.get("checks")
    if not isinstance(checks, dict) or set(checks) != CROP_QA_CHECKS:
        errors.append(f"{prefix} QA checks incomplete")
        return errors
    invalid = {name: value for name, value in checks.items() if value not in {"pending", "pass", "fail"}}
    if invalid:
        errors.append(f"{prefix} QA check values invalid: {invalid}")
    if require_complete:
        if qa.get("status") != "pass":
            errors.append(f"{prefix} QA status must be pass")
        failed = [name for name in CROP_QA_CHECKS if checks.get(name) != "pass"]
        if failed:
            errors.append(f"{prefix} QA checks not passed: {sorted(failed)}")
        if not qa.get("reviewer") or not qa.get("reviewed_at"):
            errors.append(f"{prefix} QA reviewer/reviewed_at missing")
        if qa.get("inspection_method") != "multimodal_blind_crop_then_source":
            errors.append(f"{prefix} QA requires blind crop-first multimodal inspection")
        if qa.get("inspection_sequence") != "crop_first_then_source":
            errors.append(f"{prefix} QA requires crop_first_then_source sequence")
        blind = qa.get("blind_crop_observation")
        if not isinstance(blind, dict):
            errors.append(f"{prefix} QA blind_crop_observation missing")
            blind = {}
        dominant = blind.get("dominant_content")
        if not isinstance(dominant, str) or len(dominant.strip()) < 12:
            errors.append(f"{prefix} QA blind dominant_content too short")
        visible_text = blind.get("visible_text")
        if not isinstance(visible_text, list) or any(not isinstance(value, str) for value in visible_text):
            errors.append(f"{prefix} QA blind visible_text must be a string list")
            visible_text = []
        anchors = blind.get("visual_anchors")
        if not isinstance(anchors, list) or len(anchors) < 2 or any(
            not isinstance(value, str) or len(value.strip()) < 3 for value in anchors
        ):
            errors.append(f"{prefix} QA blind visual_anchors needs at least two literal anchors")
            anchors = []
        unrelated = blind.get("unrelated_content")
        if not isinstance(unrelated, list) or any(not isinstance(value, str) for value in unrelated):
            errors.append(f"{prefix} QA blind unrelated_content must be a string list")
        elif unrelated:
            errors.append(f"{prefix} QA pass cannot retain unrelated visible content: {unrelated}")
        if blind.get("crop_fills_semantic_target") is not True:
            errors.append(f"{prefix} QA crop_fills_semantic_target must be true")
        source_observation = qa.get("source_context_observation")
        if not isinstance(source_observation, str) or len(source_observation.strip()) < 12:
            errors.append(f"{prefix} QA source_context_observation too short")
        semantic_target = qa.get("semantic_target")
        if not isinstance(semantic_target, str) or len(semantic_target.strip()) < 12:
            errors.append(f"{prefix} QA semantic_target too short")
        semantic_target_id = qa.get("semantic_target_id")
        if not isinstance(semantic_target_id, str) or len(semantic_target_id.strip()) < 3:
            errors.append(f"{prefix} QA semantic_target_id missing")
        for field in ("expected_content", "observed_content"):
            value = qa.get(field)
            if not isinstance(value, list) or not value or any(
                not isinstance(item, str) or len(item.strip()) < 3 for item in value
            ):
                errors.append(f"{prefix} QA {field} needs claim-specific entries")
        if exact_text_required and qa.get("text_coverage") != "full":
            errors.append(f"{prefix} QA exact text requires full text_coverage")
        if receipt.get("purpose") == "prompt":
            if not visible_text:
                errors.append(f"{prefix} prompt QA requires literal visible_text")
            if qa.get("text_coverage") not in {"full", "partial"}:
                errors.append(f"{prefix} prompt QA requires readable text coverage")
            observed_tokens = _semantic_tokens([dominant, *visible_text, *anchors])
            claim_tokens = _semantic_tokens(expected_claims)
            required_overlap = min(2, len(claim_tokens))
            if required_overlap and len(observed_tokens & claim_tokens) < required_overlap:
                errors.append(f"{prefix} prompt blind observation does not support evidence claim")
            if not qa.get("supported_scene_ids"):
                errors.append(f"{prefix} prompt QA requires supported_scene_ids")
        if receipt.get("purpose") == "target_output":
            if qa.get("target_state") not in {"representative_result", "final_result"}:
                errors.append(f"{prefix} target_output QA target_state invalid")
            if qa.get("complete_scene_state") is not True:
                errors.append(f"{prefix} target_output QA requires complete_scene_state=true")
        if receipt.get("purpose") in {"target_output", "source_asset"} and len(anchors) < 2:
            errors.append(f"{prefix} {receipt.get('purpose')} QA requires visual identity anchors")
        rationale = qa.get("verdict_rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 30:
            errors.append(f"{prefix} QA verdict_rationale must explain the semantic match")
        notes = qa.get("notes")
        if not isinstance(notes, str) or len(notes.strip()) < 30 or "preserves labeled" in notes.lower():
            errors.append(f"{prefix} QA notes must describe crop-specific comparison")
    return errors


def _semantic_tokens(values: Any) -> set[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return set()
    tokens: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for token in re.findall(r"[a-z0-9$]+", value.lower()):
            if len(token) >= 2 and token not in SEMANTIC_STOPWORDS:
                tokens.add(token)
    return tokens


def _safe_run_path(run_dir: Path, relative: str) -> Path | None:
    try:
        path = (run_dir / relative).resolve()
        path.relative_to(run_dir)
        return path
    except (OSError, ValueError):
        return None


def _is_image_path(relative: str) -> bool:
    return Path(relative).suffix.lower() in {".jpg", ".jpeg", ".png"}


def _validate_registered_json(run_dir: Path, run: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    relatives = {"run.json"}
    artifact_rows = run.get("artifacts", [])
    if not isinstance(artifact_rows, list):
        artifact_rows = []
    relatives.update(
        str(item.get("path")).replace("\\", "/")
        for item in artifact_rows
        if isinstance(item, dict) and str(item.get("path", "")).lower().endswith(".json")
    )
    for relative in sorted(relatives):
        path = _safe_run_path(run_dir.resolve(), relative)
        if path is None or not path.is_file():
            continue
        for code, message in validate_json_encoding(path):
            errors.append({"code": code, "path": relative, "message": message})
    return errors


def derive_qa_status(payload: dict[str, Any]) -> str:
    results = [row.get("result") for row in payload.get("per_second", [])]
    results.extend(row.get("result") for row in payload.get("comparison", {}).get("checkpoints", []))
    final = payload.get("final", {}).get("result")
    gates = list(payload.get("gates", {}).values())
    combined = results + [final] + gates
    if "fail" in combined:
        return "fail"
    if "partial" in combined:
        return "salvageable_but_fail"
    if combined and all(value == "pass" for value in combined):
        return "pass"
    return "pending_visual_review"


def validate_qa_record(
    payload: dict[str, Any],
    *,
    require_complete: bool = False,
    require_fidelity: bool = False,
) -> list[str]:
    errors: list[str] = []
    rows = payload.get("per_second")
    if not isinstance(rows, list) or not rows:
        errors.append("per_second must be a non-empty list")
    else:
        expected = payload.get("frame_seconds", [])
        actual = [row.get("second") for row in rows]
        if actual != expected:
            errors.append("per_second rows do not match frame_seconds")
        if require_complete:
            for row in rows:
                if not row.get("observed"):
                    errors.append(f"second {row.get('second')} missing observation")
                if row.get("result") not in {"pass", "partial", "fail"}:
                    errors.append(f"second {row.get('second')} has invalid result")
    if require_complete:
        final = payload.get("final", {})
        if not final.get("observed") or final.get("result") not in {"pass", "partial", "fail"}:
            errors.append("final frame review incomplete")
        gates = payload.get("gates")
        if not isinstance(gates, dict) or not gates:
            errors.append("QA gates missing")
        else:
            for name, result in gates.items():
                if result not in {"pass", "partial", "fail"}:
                    errors.append(f"gate {name} has invalid result")
            if require_fidelity:
                missing = REQUIRED_FIDELITY_GATES - set(gates)
                if missing:
                    errors.append(f"fidelity gates missing: {', '.join(sorted(missing))}")
        if require_fidelity:
            comparison = payload.get("comparison", {})
            if not comparison.get("reference_paths"):
                errors.append("fidelity comparison reference_paths missing")
            checkpoints = comparison.get("checkpoints")
            if not isinstance(checkpoints, list) or len(checkpoints) < 3:
                errors.append("fidelity comparison needs at least 3 checkpoints")
            else:
                for index, row in enumerate(checkpoints):
                    if row.get("progress") is None or not row.get("reference_path") or not row.get("output_path"):
                        errors.append(f"comparison checkpoint[{index}] provenance missing")
                    if not row.get("observed") or row.get("result") not in {"pass", "partial", "fail"}:
                        errors.append(f"comparison checkpoint[{index}] review incomplete")
        derived = derive_qa_status(payload)
        claimed = payload.get("status")
        if claimed == "pass" and derived != "pass":
            errors.append(f"claimed pass contradicts derived {derived}")
        if claimed not in {"pass", "fail", "salvageable_but_fail"}:
            errors.append("QA status incomplete")
        elif claimed != derived:
            errors.append(f"QA status {claimed} does not match derived {derived}")
    return errors


def validate_section_map(
    payload: dict[str, Any],
    *,
    require_detail_complete: bool = False,
    source_duration_seconds: float | None = None,
) -> list[str]:
    """Validate transcript-led pass 1 plus autonomous pass-2 selection."""
    errors: list[str] = []
    if payload.get("schema_version") != 4:
        errors.append("schema_version must be 4")
    if payload.get("status") != "complete":
        errors.append("status must be complete")
    if not payload.get("source_id") or not payload.get("tutorial_summary"):
        errors.append("source_id/tutorial_summary missing")
    showcased = payload.get("showcased_output")
    if not isinstance(showcased, str) or not showcased.strip():
        errors.append("showcased_output missing; use 'none identified' when absent")
    claims = payload.get("source_count_claims")
    if not isinstance(claims, list):
        errors.append("source_count_claims must be a list")
        claims = []
    for index, claim in enumerate(claims):
        prefix = f"source_count_claims[{index}]"
        if not isinstance(claim.get("count"), int) or claim["count"] <= 0:
            errors.append(f"{prefix}.count invalid")
        for field in ("label", "scope", "text"):
            if not claim.get(field):
                errors.append(f"{prefix}.{field} missing")
        if not isinstance(claim.get("timestamp"), (int, float)):
            errors.append(f"{prefix}.timestamp invalid")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return errors + ["sections must be a non-empty list"]
    section_ids: set[str] = set()
    previous_end: float | None = None
    for index, section in enumerate(sections):
        prefix = f"sections[{index}]"
        section_id = section.get("section_id")
        if not isinstance(section_id, str) or not re.fullmatch(r"section-\d{2}", section_id):
            errors.append(f"{prefix}.section_id invalid")
        elif section_id in section_ids:
            errors.append(f"{prefix}.section_id duplicate: {section_id}")
        else:
            section_ids.add(section_id)
        for field in ("title", "summary", "selection_reason"):
            if not section.get(field):
                errors.append(f"{prefix}.{field} missing")
        start, end = section.get("start_seconds"), section.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            errors.append(f"{prefix} time range invalid")
        elif previous_end is not None and start < previous_end:
            errors.append(f"{prefix} overlaps previous section")
        if isinstance(end, (int, float)):
            previous_end = float(end)
        if section.get("role") not in SECTION_ROLES:
            errors.append(f"{prefix}.role invalid")
        transcript_evidence = section.get("transcript_evidence")
        if not isinstance(transcript_evidence, list) or not transcript_evidence:
            errors.append(f"{prefix}.transcript_evidence missing")
        else:
            for evidence_index, row in enumerate(transcript_evidence):
                if not isinstance(row.get("text"), str) or not row["text"].strip():
                    errors.append(f"{prefix}.transcript_evidence[{evidence_index}].text missing")
                if not isinstance(row.get("start_seconds"), (int, float)):
                    errors.append(f"{prefix}.transcript_evidence[{evidence_index}].start_seconds invalid")
    first_start = sections[0].get("start_seconds")
    if isinstance(first_start, (int, float)) and first_start > 2:
        errors.append(f"sections must begin near source start; first start is {first_start}")
    if isinstance(source_duration_seconds, (int, float)) and source_duration_seconds > 0:
        if previous_end is None or abs(float(source_duration_seconds) - previous_end) > 2:
            errors.append(
                "sections must cover source duration within 2 seconds: "
                f"mapped_end={previous_end}, source_duration={float(source_duration_seconds)}"
            )
        tail = payload.get("tail_coverage")
        if not isinstance(tail, dict):
            errors.append("tail_coverage required")
        else:
            if tail.get("status") != "complete":
                errors.append("tail_coverage.status must be complete")
            if tail.get("section_id") != sections[-1].get("section_id"):
                errors.append("tail_coverage.section_id must equal final section")
            tail_start, tail_end = tail.get("start_seconds"), tail.get("end_seconds")
            if not isinstance(tail_start, (int, float)) or not isinstance(tail_end, (int, float)):
                errors.append("tail_coverage time range invalid")
            elif tail_end <= tail_start or abs(float(source_duration_seconds) - float(tail_end)) > 2:
                errors.append("tail_coverage must reach source duration")
            if tail.get("disposition") not in {"mapped_content", "trailing_music_or_silence"}:
                errors.append("tail_coverage.disposition invalid")
            if not isinstance(tail.get("summary"), str) or len(tail["summary"].strip()) < 12:
                errors.append("tail_coverage.summary too short")
            tail_evidence = tail.get("transcript_evidence")
            if tail.get("disposition") == "mapped_content":
                if not isinstance(tail_evidence, list) or not tail_evidence:
                    errors.append("tail_coverage mapped_content requires transcript_evidence")
                elif isinstance(tail_start, (int, float)) and not any(
                    isinstance(row, dict)
                    and isinstance(row.get("start_seconds"), (int, float))
                    and row["start_seconds"] >= tail_start
                    and isinstance(row.get("text"), str)
                    and row["text"].strip()
                    for row in tail_evidence
                ):
                    errors.append("tail_coverage transcript evidence must overlap tail range")
            elif not tail.get("reason"):
                errors.append("tail_coverage trailing silence/music requires reason")
    detailed = payload.get("detailed_workflow_present")
    detail_pass = payload.get("detail_pass")
    if detailed not in {True, False}:
        errors.append("detailed_workflow_present must be boolean")
    if not isinstance(detail_pass, list):
        return errors + ["detail_pass must be a list"]
    if detailed is True and not detail_pass:
        errors.append("detailed workflow requires autonomous detail_pass selection")
    if detailed is False and not payload.get("no_detail_reason"):
        errors.append("no_detail_reason required when detailed workflow is absent")
    seen_detail: set[str] = set()
    roles_by_id = {
        row.get("section_id"): row.get("role")
        for row in sections
        if isinstance(row.get("section_id"), str)
    }
    for index, item in enumerate(detail_pass):
        prefix = f"detail_pass[{index}]"
        section_id = item.get("section_id")
        if section_id not in section_ids:
            errors.append(f"{prefix}.section_id unknown: {section_id}")
        elif section_id in seen_detail:
            errors.append(f"{prefix}.section_id duplicate: {section_id}")
        seen_detail.add(section_id)
        if not item.get("reason") or not isinstance(item.get("questions"), list) or not item["questions"]:
            errors.append(f"{prefix}.reason/questions missing")
        if roles_by_id.get(section_id) not in {"method", "workflow_breakdown", "showcase_production", "demonstration"}:
            errors.append(f"{prefix}.section role cannot support workflow detail")
        if item.get("status") not in {"planned", "complete"}:
            errors.append(f"{prefix}.status invalid")
        if require_detail_complete and item.get("status") != "complete":
            errors.append(f"{prefix}.status must be complete")
    missing_showcases = sorted(
        section_id for section_id, role in roles_by_id.items()
        if role == "showcase_production" and section_id not in seen_detail
    )
    if missing_showcases:
        errors.append(
            "showcase_production sections require autonomous detail inventory: "
            f"{missing_showcases}"
        )
    return errors


def _visible_output_count(text: Any) -> int | None:
    normalized = " ".join(str(text or "").lower().split())
    pattern = r"\b(\d+|" + "|".join(COUNT_WORDS) + r")\s+(?:separate\s+)?(?:scenes?|shots?|clips?)\b"
    match = re.search(pattern, normalized)
    if not match:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else COUNT_WORDS.get(token)


def _catalog_list_shape_errors(payload: Any) -> list[str]:
    """Validate JSON list boundaries before semantic code uses set/dict operations."""
    errors: list[str] = []

    def check_list(owner: Any, field: str, path: str, *, string_items: bool = False) -> None:
        if not isinstance(owner, dict) or field not in owner:
            return
        value = owner.get(field)
        if not isinstance(value, list):
            errors.append(f"{path} must be a list")
            return
        if string_items:
            for index, item in enumerate(value):
                if not isinstance(item, str):
                    errors.append(f"{path}[{index}] must be string")
            if len(value) != len(set(item for item in value if isinstance(item, str))):
                errors.append(f"{path} must not contain duplicate values")

    def check_rows(owner: Any, field: str, path: str) -> list[dict[str, Any]]:
        if not isinstance(owner, dict) or field not in owner:
            return []
        value = owner.get(field)
        if not isinstance(value, list):
            errors.append(f"{path} must be a list")
            return []
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{path}[{index}] must be an object")
            else:
                rows.append(item)
        return rows

    if not isinstance(payload, dict):
        return ["scene_catalog must be an object"]

    routes = check_rows(payload, "production_routes", "production_routes")
    for index, route in enumerate(routes):
        check_list(route, "evidence", f"production_routes[{index}].evidence", string_items=True)
        check_list(route, "required_capabilities", f"production_routes[{index}].required_capabilities", string_items=True)

    for field in ("visual_count_claims", "fact_claims", "fact_reconciliation", "count_reconciliation"):
        check_rows(payload, field, field)
    for index, claim in enumerate(check_rows(payload, "visual_count_claims", "visual_count_claims")):
        check_list(claim, "evidence", f"visual_count_claims[{index}].evidence", string_items=True)
    for index, claim in enumerate(check_rows(payload, "fact_claims", "fact_claims")):
        check_list(claim, "evidence", f"fact_claims[{index}].evidence", string_items=True)
    for index, row in enumerate(check_rows(payload, "fact_reconciliation", "fact_reconciliation")):
        check_list(row, "claim_ids", f"fact_reconciliation[{index}].claim_ids", string_items=True)
    for index, row in enumerate(check_rows(payload, "count_reconciliation", "count_reconciliation")):
        check_list(row, "claim_ids", f"count_reconciliation[{index}].claim_ids", string_items=True)
        check_list(row, "section_ids", f"count_reconciliation[{index}].section_ids", string_items=True)

    assets = check_rows(payload, "workflow_assets", "workflow_assets")
    for index, asset in enumerate(assets):
        prefix = f"workflow_assets[{index}]"
        for field in ("evidence", "production_use_evidence", "crop_evidence", "count_claim_ids", "code_source_evidence", "consumed_by_scene_ids"):
            check_list(asset, field, f"{prefix}.{field}", string_items=True)
        bindings = check_rows(asset, "evidence_bindings", f"{prefix}.evidence_bindings")
        for binding_index, binding in enumerate(bindings):
            check_list(binding, "evidence", f"{prefix}.evidence_bindings[{binding_index}].evidence", string_items=True)

    sections = check_rows(payload, "sections", "sections")
    for section_index, section in enumerate(sections):
        prefix = f"sections[{section_index}]"
        for field in ("evidence", "unresolved_units"):
            check_list(section, field, f"{prefix}.{field}", string_items=True)
        units = check_rows(section, "source_units", f"{prefix}.source_units")
        for unit_index, unit in enumerate(units):
            unit_prefix = f"{prefix}.source_units[{unit_index}]"
            for field in ("change_types", "evidence", "evidence_items", "scene_ids"):
                check_list(unit, field, f"{unit_prefix}.{field}", string_items=True)
        changes = check_rows(section, "change_points", f"{prefix}.change_points")
        for change_index, change in enumerate(changes):
            change_prefix = f"{prefix}.change_points[{change_index}]"
            for field in ("change_types", "evidence_items"):
                check_list(change, field, f"{change_prefix}.{field}", string_items=True)
        scenes = check_rows(section, "scenes", f"{prefix}.scenes")
        for scene_index, scene in enumerate(scenes):
            scene_prefix = f"{prefix}.scenes[{scene_index}]"
            for field in (
                "evidence", "reference_frames", "motion_order", "text", "audio",
                "input_asset_ids", "required_asset_ids", "target_reference_asset_ids",
                "required_pre_provider_asset_ids", "prompt_evidence",
            ):
                check_list(scene, field, f"{scene_prefix}.{field}", string_items=True)
            occurrences = check_rows(scene, "source_occurrences", f"{scene_prefix}.source_occurrences")
            for occurrence_index, occurrence in enumerate(occurrences):
                occurrence_prefix = f"{scene_prefix}.source_occurrences[{occurrence_index}]"
                check_list(occurrence, "evidence", f"{occurrence_prefix}.evidence", string_items=True)
                fact_review = occurrence.get("fact_review")
                if fact_review is not None and not isinstance(fact_review, dict):
                    errors.append(f"{occurrence_prefix}.fact_review must be an object")
                elif isinstance(fact_review, dict):
                    check_list(fact_review, "reviewed_evidence", f"{occurrence_prefix}.fact_review.reviewed_evidence", string_items=True)
                    check_rows(fact_review, "visible_fact_candidates", f"{occurrence_prefix}.fact_review.visible_fact_candidates")
        groups = check_rows(section, "prompt_groups", f"{prefix}.prompt_groups")
        for group_index, group in enumerate(groups):
            group_prefix = f"{prefix}.prompt_groups[{group_index}]"
            check_list(group, "prompt_evidence", f"{group_prefix}.prompt_evidence", string_items=True)
            check_list(group, "scene_ids", f"{group_prefix}.scene_ids", string_items=True)

    return errors


def validate_scene_catalog_v13(
    payload: dict[str, Any],
    *,
    require_complete: bool = False,
    evidence_manifest: dict[str, Any] | None = None,
    section_map: dict[str, Any] | None = None,
    detail_discovery: dict[str, Any] | None = None,
    crop_receipts: dict[str, dict[str, Any]] | None = None,
    crop_qas: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Validate semantic pass 2. Duration never defines scene boundaries."""
    errors: list[str] = []
    shape_errors = _catalog_list_shape_errors(payload)
    if shape_errors:
        return shape_errors
    if payload.get("schema_version") != 13:
        errors.append("schema_version must be 13")
    if not payload.get("source_id") or not payload.get("catalog_scope"):
        errors.append("source_id/catalog_scope missing")
    if require_complete and payload.get("status") != "complete":
        errors.append("status must be complete")
    if payload.get("segmentation_policy") != "semantic-boundary":
        errors.append("segmentation_policy must be semantic-boundary")
    passes = payload.get("analysis_passes")
    if not isinstance(passes, dict) or passes.get("high_level") != "complete":
        errors.append("high-level analysis pass must be complete")
    if require_complete and (not isinstance(passes, dict) or passes.get("detail") != "complete"):
        errors.append("detail analysis pass must be complete")
    production_routes = payload.get("production_routes")
    if not isinstance(production_routes, list) or not production_routes:
        errors.append("production_routes must be a non-empty list")
        production_routes = []
    route_by_id: dict[str, dict[str, Any]] = {}
    for route_index, route_record in enumerate(production_routes):
        route_prefix = f"production_routes[{route_index}]"
        for field in (
            "route_id", "route", "tool", "tool_kind", "framework_policy",
            "evidence", "required_capabilities",
        ):
            if not route_record.get(field):
                errors.append(f"{route_prefix}.{field} missing")
        route_id = route_record.get("route_id")
        if not isinstance(route_id, str) or not re.fullmatch(r"route-[a-z0-9-]+", route_id):
            errors.append(f"{route_prefix}.route_id invalid")
        elif route_id in route_by_id:
            errors.append(f"{route_prefix}.route_id duplicate: {route_id}")
        else:
            route_by_id[route_id] = route_record
        if route_record.get("tool_kind") not in PRODUCTION_TOOL_KINDS:
            errors.append(f"{route_prefix}.tool_kind invalid")
        if route_record.get("framework_policy") != "source_exact":
            errors.append(f"{route_prefix}.framework_policy must be source_exact")
        tool_key = _tool_key(route_record.get("tool"))
        if route_record.get("tool_kind") in {"code_video", "generative_video"} and tool_key in {
            _tool_key(value) for value in GENERIC_PRODUCTION_TOOLS
        }:
            errors.append(f"{route_prefix}.tool must name demonstrated framework/provider")

    visual_claims = payload.get("visual_count_claims")
    if not isinstance(visual_claims, list):
        errors.append("visual_count_claims must be a list")
        visual_claims = []
    visual_claim_by_id: dict[str, dict[str, Any]] = {}
    for claim_index, claim in enumerate(visual_claims):
        claim_prefix = f"visual_count_claims[{claim_index}]"
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not re.fullmatch(r"visual-count-\d{2}", claim_id):
            errors.append(f"{claim_prefix}.claim_id invalid")
        elif claim_id in visual_claim_by_id:
            errors.append(f"{claim_prefix}.claim_id duplicate")
        else:
            visual_claim_by_id[claim_id] = claim
        if not isinstance(claim.get("count"), int) or claim.get("count", 0) <= 0:
            errors.append(f"{claim_prefix}.count invalid")
        if claim.get("claim_kind") != "output_scene_count":
            errors.append(f"{claim_prefix}.claim_kind must be output_scene_count")
        for field in ("label", "scope", "text", "evidence"):
            if not claim.get(field):
                errors.append(f"{claim_prefix}.{field} missing")
    fact_claims = payload.get("fact_claims")
    if not isinstance(fact_claims, list):
        errors.append("fact_claims must be a list")
        fact_claims = []
    fact_claim_by_id: dict[str, dict[str, Any]] = {}
    for claim_index, claim in enumerate(fact_claims):
        claim_prefix = f"fact_claims[{claim_index}]"
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not re.fullmatch(r"fact-[a-z0-9-]+-\d{2}", claim_id):
            errors.append(f"{claim_prefix}.claim_id invalid")
        elif claim_id in fact_claim_by_id:
            errors.append(f"{claim_prefix}.claim_id duplicate")
        else:
            fact_claim_by_id[claim_id] = claim
        for field in ("subject", "value", "scope", "evidence"):
            if not claim.get(field):
                errors.append(f"{claim_prefix}.{field} missing")
    fact_reconciliation = payload.get("fact_reconciliation")
    if not isinstance(fact_reconciliation, list):
        errors.append("fact_reconciliation must be a list")
        fact_reconciliation = []
    reconciled_fact_ids: list[str] = []
    for row_index, row in enumerate(fact_reconciliation):
        row_prefix = f"fact_reconciliation[{row_index}]"
        claim_ids = row.get("claim_ids")
        if not isinstance(claim_ids, list) or len(claim_ids) < 2:
            errors.append(f"{row_prefix}.claim_ids requires at least two claims")
            claim_ids = []
        unknown = [value for value in claim_ids if value not in fact_claim_by_id]
        if unknown:
            errors.append(f"{row_prefix}.claim_ids unknown: {unknown}")
        subjects = {fact_claim_by_id[value].get("subject") for value in claim_ids if value in fact_claim_by_id}
        if len(subjects) > 1:
            errors.append(f"{row_prefix}.claim_ids mix subjects")
        if row.get("status") not in {"matched", "explained_mismatch", "not_comparable"}:
            errors.append(f"{row_prefix}.status invalid")
        if row.get("status") != "matched" and not row.get("explanation"):
            errors.append(f"{row_prefix}.explanation required")
        reconciled_fact_ids.extend(claim_ids)
    claims_by_subject: dict[str, list[dict[str, Any]]] = {}
    for claim in fact_claims:
        if isinstance(claim.get("subject"), str):
            claims_by_subject.setdefault(claim["subject"], []).append(claim)
    for subject, claims in claims_by_subject.items():
        values = {str(claim.get("value")).strip().lower() for claim in claims}
        if len(values) > 1:
            ids = {claim.get("claim_id") for claim in claims}
            if not ids.issubset(set(reconciled_fact_ids)):
                errors.append(f"fact_reconciliation missing conflicting subject: {subject}")
    workflow_assets = payload.get("workflow_assets", [])
    if not isinstance(workflow_assets, list):
        errors.append("workflow_assets must be a list")
        workflow_assets = []
    workflow_asset_by_id: dict[str, dict[str, Any]] = {}
    manifest_paths = {
        str(path).replace("\\", "/")
        for row in (evidence_manifest or {}).get("coverage", [])
        for path in row.get("evidence", [])
        if isinstance(path, str)
    }
    for asset_index, asset in enumerate(workflow_assets):
        asset_prefix = f"workflow_assets[{asset_index}]"
        for field in (
            "asset_id", "role", "source_visibility", "reconstruction_policy",
            "production_action", "pipeline_role", "source_kind", "deliverable_kind",
            "consumed_by_scene_ids",
        ):
            if not asset.get(field):
                errors.append(f"{asset_prefix}.{field} missing")
        asset_id = asset.get("asset_id")
        if isinstance(asset_id, str):
            if asset_id in workflow_asset_by_id:
                errors.append(f"{asset_prefix}.asset_id duplicate: {asset_id}")
            workflow_asset_by_id[asset_id] = asset
        visibility = asset.get("source_visibility")
        role = asset.get("role")
        production_action = asset.get("production_action")
        pipeline_role = asset.get("pipeline_role")
        source_kind = asset.get("source_kind")
        deliverable_kind = asset.get("deliverable_kind")
        evidence = asset.get("evidence")
        bindings = asset.get("evidence_bindings")
        production_use_evidence = asset.get("production_use_evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{asset_prefix}.evidence required")
            evidence = []
        if not isinstance(bindings, list) or not bindings:
            errors.append(f"{asset_prefix}.evidence_bindings required")
            bindings = []
        bound_paths: set[str] = set()
        binding_roles: dict[str, str] = {}
        for binding_index, binding in enumerate(bindings):
            binding_prefix = f"{asset_prefix}.evidence_bindings[{binding_index}]"
            path = str((binding or {}).get("path") or "").replace("\\", "/")
            evidence_role = (binding or {}).get("evidence_role")
            if not path or path not in {str(value).replace("\\", "/") for value in evidence}:
                errors.append(f"{binding_prefix}.path must reference asset evidence")
            if evidence_role not in ASSET_EVIDENCE_ROLES:
                errors.append(f"{binding_prefix}.evidence_role invalid")
            if not isinstance((binding or {}).get("observation"), str) or len(binding["observation"].strip()) < 12:
                errors.append(f"{binding_prefix}.observation too short")
            if path:
                bound_paths.add(path)
                binding_roles[path] = str(evidence_role)
        unbound_evidence = sorted(
            {str(value).replace("\\", "/") for value in evidence} - bound_paths
        )
        if unbound_evidence:
            errors.append(f"{asset_prefix}.evidence lacks role binding: {unbound_evidence}")
        if pipeline_role in {"input", "shared_input"}:
            if not isinstance(production_use_evidence, list) or not production_use_evidence:
                errors.append(f"{asset_prefix}.production_use_evidence required for production input")
                production_use_evidence = []
            invalid_use = [
                value for value in production_use_evidence
                if binding_roles.get(str(value).replace("\\", "/")) not in PRODUCTION_EVIDENCE_ROLES
            ]
            if invalid_use:
                errors.append(
                    f"{asset_prefix}.production_use_evidence lacks production-role evidence: {invalid_use}"
                )
        elif production_use_evidence not in ([], None):
            errors.append(f"{asset_prefix}.production_use_evidence only valid for production input")
        if role not in WORKFLOW_ASSET_ROLES:
            errors.append(f"{asset_prefix}.role invalid")
        if production_action not in PRODUCTION_ACTIONS:
            errors.append(f"{asset_prefix}.production_action invalid")
        if pipeline_role not in PIPELINE_ROLES:
            errors.append(f"{asset_prefix}.pipeline_role invalid")
        if source_kind not in ASSET_SOURCE_KINDS:
            errors.append(f"{asset_prefix}.source_kind invalid")
        if deliverable_kind not in ASSET_DELIVERABLE_KINDS:
            errors.append(f"{asset_prefix}.deliverable_kind invalid")
        if visibility not in {"shown", "not_shown"}:
            errors.append(f"{asset_prefix}.source_visibility invalid")
        if visibility == "not_shown" and any(role == "shown_input" for role in binding_roles.values()):
            errors.append(f"{asset_prefix}.source_visibility contradicts shown_input evidence")
        if pipeline_role == "target_reference":
            if visibility != "shown":
                errors.append(f"{asset_prefix}.target_reference must be visibly shown")
            if asset.get("target_state") not in {"representative_result", "final_result"}:
                errors.append(
                    f"{asset_prefix}.target_state must be representative_result or final_result"
                )
        if visibility == "shown":
            if asset.get("reconstruction_policy") != "exact_source":
                errors.append(f"{asset_prefix} shown asset must use exact_source reconstruction")
            evidence = asset.get("evidence")
            crops = asset.get("crop_evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{asset_prefix}.evidence required for shown asset")
            if not isinstance(crops, list) or not crops or not all(_is_image_path(value) for value in crops):
                errors.append(f"{asset_prefix}.crop_evidence image required for shown asset")
                crops = []
            missing_crops = [
                value for value in crops if str(value).replace("\\", "/") not in manifest_paths
            ]
            if missing_crops:
                errors.append(f"{asset_prefix}.crop_evidence absent from evidence manifest: {missing_crops}")
            if crop_receipts is not None:
                normalized_evidence = {str(value).replace("\\", "/") for value in (asset.get("evidence") or [])}
                for crop in crops:
                    normalized_crop = str(crop).replace("\\", "/")
                    receipt = crop_receipts.get(normalized_crop)
                    if receipt is None:
                        errors.append(f"{asset_prefix}.crop_evidence receipt missing: {normalized_crop}")
                    elif str(receipt.get("source_path") or "").replace("\\", "/") not in normalized_evidence:
                        errors.append(f"{asset_prefix}.crop receipt source absent from asset evidence: {normalized_crop}")
            if crop_qas is not None:
                expected_purpose = (
                    "target_output" if pipeline_role == "target_reference"
                    else "prompt" if pipeline_role == "prompt_reference"
                    else "source_asset"
                )
                for crop in crops:
                    normalized_crop = str(crop).replace("\\", "/")
                    qa = crop_qas.get(normalized_crop)
                    if qa is None:
                        errors.append(f"{asset_prefix}.crop_evidence QA missing: {normalized_crop}")
                    else:
                        if qa.get("purpose") != expected_purpose:
                            errors.append(
                                f"{asset_prefix}.crop QA purpose must be {expected_purpose}: {normalized_crop}"
                            )
                        if qa.get("semantic_target_id") != asset_id:
                            errors.append(
                                f"{asset_prefix}.crop QA semantic_target_id must equal asset_id: {normalized_crop}"
                            )
                        if pipeline_role == "target_reference":
                            if qa.get("target_state") != asset.get("target_state"):
                                errors.append(
                                    f"{asset_prefix}.crop QA target_state must equal asset target_state: "
                                    f"{normalized_crop}"
                                )
                            if qa.get("complete_scene_state") is not True:
                                errors.append(
                                    f"{asset_prefix}.target crop must show complete representative scene state: "
                                    f"{normalized_crop}"
                                )
        elif visibility == "not_shown" and asset.get("reconstruction_policy") == "exact_source":
            errors.append(f"{asset_prefix} unshown asset cannot claim exact_source reconstruction")
        reconstructable_roles = {"shown_input", "target_component"}
        if production_action == "imagegen_reconstruct" and not any(
            role in reconstructable_roles for role in binding_roles.values()
        ):
            errors.append(f"{asset_prefix}.imagegen_reconstruct requires shown_input or target_component evidence")
        if production_action == "imagegen_generate" and visibility != "not_shown":
            errors.append(f"{asset_prefix}.imagegen_generate is only for unshown assets")
        if production_action == "imagegen_generate" and any(
            role in reconstructable_roles for role in binding_roles.values()
        ):
            errors.append(f"{asset_prefix}.imagegen_generate cannot replace visible source component")
        text_bearing = asset.get("text_bearing")
        if text_bearing not in {True, False}:
            errors.append(f"{asset_prefix}.text_bearing must be boolean")
        elif text_bearing:
            if asset.get("text_extraction") not in {"exact", "detailed_paraphrase"}:
                errors.append(f"{asset_prefix}.text_extraction required for text-bearing asset")
            visible_text = asset.get("visible_text")
            if not isinstance(visible_text, str) or not visible_text.strip():
                errors.append(f"{asset_prefix}.visible_text required for text-bearing asset")
            visible_count = _visible_output_count(visible_text)
            claim_ids = asset.get("count_claim_ids")
            if visible_count is not None:
                if not isinstance(claim_ids, list) or not claim_ids:
                    errors.append(f"{asset_prefix}.count_claim_ids required for visible scene count")
                else:
                    unknown_claims = [value for value in claim_ids if value not in visual_claim_by_id]
                    if unknown_claims:
                        errors.append(f"{asset_prefix}.count_claim_ids unknown: {unknown_claims}")
                    if not any(
                        visual_claim_by_id.get(value, {}).get("count") == visible_count
                        for value in claim_ids
                    ):
                        errors.append(f"{asset_prefix}.count_claim_ids do not preserve visible count {visible_count}")
        elif asset.get("text_extraction") not in {None, "", "not_applicable"}:
            errors.append(f"{asset_prefix}.text_extraction must be not_applicable for non-text asset")
        if pipeline_role in {"target_reference", "prompt_reference"} and production_action != "reuse_source":
            errors.append(f"{asset_prefix}.{pipeline_role} must use reuse_source")
        if pipeline_role in {"target_reference", "prompt_reference"}:
            if source_kind != "reference_only" or deliverable_kind != "reference_only":
                errors.append(f"{asset_prefix}.{pipeline_role} must be reference_only")
        else:
            if source_kind == "reference_only" or deliverable_kind == "reference_only":
                errors.append(f"{asset_prefix} production input cannot be reference_only")
            if production_action == "reuse_source":
                source_asset_path = asset.get("source_asset_path")
                if source_kind != "isolated_source_file":
                    errors.append(f"{asset_prefix}.reuse_source requires isolated_source_file")
                if deliverable_kind not in {"source_file", "media_file"}:
                    errors.append(f"{asset_prefix}.reuse_source deliverable must be source_file or media_file")
                normalized_source_asset = str(source_asset_path or "").replace("\\", "/")
                if (
                    not normalized_source_asset
                    or normalized_source_asset.startswith(("frames/", "crops/"))
                    or normalized_source_asset not in manifest_paths
                ):
                    errors.append(f"{asset_prefix}.reuse_source requires registered isolated source_asset_path")
                if not asset.get("source_asset_sha256"):
                    errors.append(f"{asset_prefix}.reuse_source requires source_asset_sha256")
            if production_action == "code_native" and (
                source_kind != "code_native" or deliverable_kind != "code_component"
            ):
                errors.append(f"{asset_prefix}.code_native requires code_native/code_component")
            if production_action == "code_native" and asset.get("code_native_kind") not in CODE_NATIVE_KINDS:
                errors.append(
                    f"{asset_prefix}.code_native_kind must name a supported procedural primitive; "
                    "semantic maps/portraits/objects require imagegen_reconstruct unless source code is shown"
                )
            if production_action == "code_native":
                semantic_text = " ".join([
                    str(asset_id or ""),
                    str(role or ""),
                    *(str((binding or {}).get("observation") or "") for binding in bindings),
                ]).lower()
                semantic_terms = re.search(r"\b(map|portrait|person|character|building|vehicle|photo|photograph)\b", semantic_text)
                code_source_evidence = asset.get("code_source_evidence")
                valid_code_evidence = (
                    isinstance(code_source_evidence, list)
                    and bool(code_source_evidence)
                    and set(code_source_evidence).issubset(set(evidence))
                )
                if semantic_terms and not valid_code_evidence:
                    errors.append(
                        f"{asset_prefix} semantic {semantic_terms.group(1)} cannot be code_native without "
                        "demonstrated code_source_evidence; use imagegen_reconstruct from source frame"
                    )
            if production_action == "imagegen_reconstruct" and deliverable_kind != "generated_raster":
                errors.append(f"{asset_prefix}.imagegen_reconstruct requires generated_raster")
            if production_action == "imagegen_generate" and (
                source_kind != "unshown" or deliverable_kind != "generated_raster"
            ):
                errors.append(f"{asset_prefix}.imagegen_generate requires unshown/generated_raster")
            if production_action == "external_media" and deliverable_kind != "media_file":
                errors.append(f"{asset_prefix}.external_media requires media_file")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return errors + ["sections must be a non-empty list"]

    evidence_rows = {
        row.get("item"): row for row in (evidence_manifest or {}).get("coverage", [])
        if isinstance(row.get("item"), str)
    }
    evidence_paths = {
        str(path).replace("\\", "/")
        for row in evidence_rows.values()
        for path in row.get("evidence", [])
        if isinstance(path, str)
    }
    for route_id, route_record in route_by_id.items():
        route_evidence = route_record.get("evidence")
        if not isinstance(route_evidence, list) or not route_evidence:
            errors.append(f"production route {route_id}.evidence must be a non-empty list")
        else:
            missing_route_evidence = [
                value for value in route_evidence
                if str(value).replace("\\", "/") not in evidence_paths
            ]
            if missing_route_evidence:
                errors.append(
                    f"production route {route_id}.evidence absent from evidence manifest: "
                    f"{missing_route_evidence}"
                )
    for claim_id, claim in visual_claim_by_id.items():
        claim_evidence = claim.get("evidence")
        if not isinstance(claim_evidence, list) or not claim_evidence:
            errors.append(f"visual count claim {claim_id}.evidence must be a non-empty list")
        else:
            missing_claim_evidence = [
                value for value in claim_evidence
                if str(value).replace("\\", "/") not in evidence_paths
            ]
            if missing_claim_evidence:
                errors.append(
                    f"visual count claim {claim_id}.evidence absent from evidence manifest: "
                    f"{missing_claim_evidence}"
                )
    for claim_id, claim in fact_claim_by_id.items():
        claim_evidence = claim.get("evidence")
        if not isinstance(claim_evidence, list) or not claim_evidence:
            errors.append(f"fact claim {claim_id}.evidence must be a non-empty list")
        else:
            missing_claim_evidence = [
                value for value in claim_evidence
                if str(value).replace("\\", "/") not in evidence_paths
            ]
            if missing_claim_evidence:
                errors.append(
                    f"fact claim {claim_id}.evidence absent from evidence manifest: "
                    f"{missing_claim_evidence}"
                )
    mapped_sections = {
        row.get("section_id"): row for row in (section_map or {}).get("sections", [])
        if isinstance(row.get("section_id"), str)
    }
    detail_ids = {
        row.get("section_id") for row in (section_map or {}).get("detail_pass", [])
        if isinstance(row.get("section_id"), str)
    }
    discovery_ranges = {
        row.get("section_id"): row for row in (detail_discovery or {}).get("ranges", [])
        if isinstance(row.get("section_id"), str)
    }
    scene_by_id = {
        scene.get("scene_id"): scene
        for section in sections
        for scene in (section.get("scenes") or [])
        if isinstance(scene, dict) and isinstance(scene.get("scene_id"), str)
    }
    all_declared_scene_ids = set(scene_by_id)
    seen_sections: set[str] = set()
    seen_scenes: set[str] = set()
    seen_units: set[str] = set()
    detail_scene_count = 0

    for section_index, section in enumerate(sections):
        prefix = f"sections[{section_index}]"
        section_id = section.get("section_id")
        for field in ("section_id", "title", "summary"):
            if not section.get(field):
                errors.append(f"{prefix}.{field} missing")
        if isinstance(section_id, str):
            if section_id in seen_sections:
                errors.append(f"{prefix}.section_id duplicate: {section_id}")
            seen_sections.add(section_id)
        mapped = mapped_sections.get(section_id)
        if section_map is not None and mapped is None:
            errors.append(f"{prefix}.section_id absent from section_map")
        if mapped and section.get("role") != mapped.get("role"):
            errors.append(f"{prefix}.role differs from section_map")
        if section.get("role") not in SECTION_ROLES:
            errors.append(f"{prefix}.role invalid")
        expected_level = "workflow_detail" if section_id in detail_ids else "overview"
        if section.get("detail_level") != expected_level:
            errors.append(f"{prefix}.detail_level must be {expected_level}")
        start, end = section.get("start_seconds"), section.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            errors.append(f"{prefix} time range invalid")
        if not isinstance(section.get("evidence"), list) or not section.get("evidence"):
            errors.append(f"{prefix}.evidence missing")
        scenes, units = section.get("scenes"), section.get("source_units")
        if not isinstance(scenes, list) or not isinstance(units, list):
            errors.append(f"{prefix}.scenes/source_units must be lists")
            continue
        if section.get("cataloged_scene_count") != len(scenes):
            errors.append(f"{prefix}.cataloged_scene_count mismatch")
        if section.get("observed_unit_count") != len(units):
            errors.append(f"{prefix}.observed_unit_count mismatch")
        if expected_level == "overview":
            if scenes or units:
                errors.append(f"{prefix} overview must not invent pass-2 scenes/units")
            continue

        if not section.get("focus_reason"):
            errors.append(f"{prefix}.focus_reason missing")
        if require_complete and section.get("segmentation_status") != "complete":
            errors.append(f"{prefix}.segmentation_status must be complete")
        if not units:
            errors.append(f"{prefix}.source_units must be a non-empty list")
        if not isinstance(section.get("unresolved_units"), list) or (require_complete and section.get("unresolved_units")):
            errors.append(f"{prefix}.unresolved_units must be empty list")
        sequence_kind = section.get("sequence_kind")
        if sequence_kind not in SEQUENCE_KINDS:
            errors.append(f"{prefix}.sequence_kind invalid")
        tolerance = section.get("coverage_tolerance_seconds", 1)
        if not isinstance(tolerance, (int, float)) or tolerance < 0 or tolerance > 2.5:
            errors.append(f"{prefix}.coverage_tolerance_seconds must be between 0 and 2.5")
            tolerance = 0

        section_scene_ids: set[str] = set()
        scene_prompt_evidence: dict[str, set[str]] = {}
        detail_scene_count += len(scenes)
        for scene_index, scene in enumerate(scenes):
            scene_prefix = f"{prefix}.scenes[{scene_index}]"
            for field in (
                "scene_id", "title", "description", "composition", "camera", "route",
                "production_route_id", "prompt_reconstruction", "confidence",
            ):
                if not scene.get(field):
                    errors.append(f"{scene_prefix}.{field} missing")
            if scene.get("scene_kind") != "output_scene":
                errors.append(f"{scene_prefix}.scene_kind must be output_scene")
            if scene.get("recreate_addressable") is not True:
                errors.append(f"{scene_prefix}.recreate_addressable must be true")
            scene_id = scene.get("scene_id")
            expected = rf"{re.escape(section_id)}-scene-\d{{2}}" if isinstance(section_id, str) else r"$^"
            if not isinstance(scene_id, str) or not re.fullmatch(expected, scene_id):
                errors.append(f"{scene_prefix}.scene_id must match <section-id>-scene-NN")
            elif scene_id in seen_scenes:
                errors.append(f"{scene_prefix}.scene_id duplicate: {scene_id}")
            else:
                seen_scenes.add(scene_id)
                section_scene_ids.add(scene_id)
            scene_start, scene_end = scene.get("start_seconds"), scene.get("end_seconds")
            if not isinstance(scene_start, (int, float)) or not isinstance(scene_end, (int, float)) or scene_end <= scene_start:
                errors.append(f"{scene_prefix} time range invalid")
            elif isinstance(start, (int, float)) and isinstance(end, (int, float)) and (scene_start < start or scene_end > end):
                errors.append(f"{scene_prefix} time range outside section")
            for field in ("evidence", "reference_frames", "motion_order", "text", "audio"):
                if not isinstance(scene.get(field), list) or not scene.get(field):
                    errors.append(f"{scene_prefix}.{field} missing")
            route = str(scene.get("route") or "").lower()
            route_record = route_by_id.get(scene.get("production_route_id"))
            if route_record is None:
                errors.append(f"{scene_prefix}.production_route_id unknown")
            elif route != str(route_record.get("route") or "").lower():
                errors.append(f"{scene_prefix}.route differs from production route")
            if route in GENERIC_SCENE_ROUTES:
                errors.append(f"{scene_prefix}.route must name exact demonstrated production route")
            occurrences = scene.get("source_occurrences")
            if not isinstance(occurrences, list) or not occurrences:
                errors.append(f"{scene_prefix}.source_occurrences missing")
            else:
                for occurrence_index, occurrence in enumerate(occurrences):
                    occurrence_prefix = f"{scene_prefix}.source_occurrences[{occurrence_index}]"
                    for field in ("section_id", "occurrence_kind", "purpose", "evidence"):
                        if not occurrence.get(field):
                            errors.append(f"{occurrence_prefix}.{field} missing")
                    if occurrence.get("occurrence_kind") not in OCCURRENCE_KINDS:
                        errors.append(f"{occurrence_prefix}.occurrence_kind invalid")
                    occurrence_section_id = occurrence.get("section_id")
                    if section_map is not None and occurrence_section_id not in mapped_sections:
                        errors.append(f"{occurrence_prefix}.section_id unknown: {occurrence_section_id}")
                    occurrence_evidence = occurrence.get("evidence")
                    if isinstance(occurrence_evidence, list):
                        missing_occurrence_evidence = [
                            value for value in occurrence_evidence
                            if str(value).replace("\\", "/") not in evidence_paths
                        ]
                        if missing_occurrence_evidence:
                            errors.append(
                                f"{occurrence_prefix}.evidence absent from evidence manifest: "
                                f"{missing_occurrence_evidence}"
                            )
                    else:
                        occurrence_evidence = []
                    fact_review = occurrence.get("fact_review")
                    if not isinstance(fact_review, dict):
                        errors.append(f"{occurrence_prefix}.fact_review missing")
                    else:
                        if fact_review.get("status") != "complete":
                            errors.append(f"{occurrence_prefix}.fact_review.status must be complete")
                        reviewed_evidence = fact_review.get("reviewed_evidence")
                        expected_reviewed = {
                            str(value).replace("\\", "/")
                            for value in occurrence_evidence
                            if isinstance(value, str) and _is_image_path(value)
                        }
                        if not isinstance(reviewed_evidence, list) or {
                            str(value).replace("\\", "/") for value in reviewed_evidence
                        } != expected_reviewed:
                            errors.append(
                                f"{occurrence_prefix}.fact_review.reviewed_evidence must cover occurrence images"
                            )
                        candidates = fact_review.get("visible_fact_candidates")
                        if not isinstance(candidates, list):
                            errors.append(
                                f"{occurrence_prefix}.fact_review.visible_fact_candidates must be a list"
                            )
                            candidates = []
                        for candidate_index, candidate in enumerate(candidates):
                            candidate_prefix = (
                                f"{occurrence_prefix}.fact_review.visible_fact_candidates[{candidate_index}]"
                            )
                            if not isinstance(candidate, dict):
                                errors.append(f"{candidate_prefix} invalid")
                                continue
                            subject = str(candidate.get("subject") or "").strip()
                            value = str(candidate.get("value") or "").strip()
                            candidate_evidence = str(candidate.get("evidence") or "").replace("\\", "/")
                            if not subject or not value:
                                errors.append(f"{candidate_prefix}.subject/value missing")
                            if candidate_evidence not in expected_reviewed:
                                errors.append(f"{candidate_prefix}.evidence must be reviewed occurrence evidence")
                            matching_claim = any(
                                str(claim.get("subject") or "").strip().casefold() == subject.casefold()
                                and str(claim.get("value") or "").strip().casefold() == value.casefold()
                                and candidate_evidence in {
                                    str(path).replace("\\", "/") for path in (claim.get("evidence") or [])
                                }
                                for claim in fact_claims
                            )
                            if subject and value and candidate_evidence and not matching_claim:
                                errors.append(f"{candidate_prefix} missing matching fact_claim")
                    occurrence_start = occurrence.get("start_seconds")
                    occurrence_end = occurrence.get("end_seconds")
                    if (
                        not isinstance(occurrence_start, (int, float))
                        or not isinstance(occurrence_end, (int, float))
                        or occurrence_end <= occurrence_start
                    ):
                        errors.append(f"{occurrence_prefix} time range invalid")
            input_asset_ids = scene.get("input_asset_ids", [])
            required_asset_ids = scene.get("required_asset_ids", [])
            target_reference_asset_ids = scene.get("target_reference_asset_ids", [])
            required_pre_provider_asset_ids = scene.get("required_pre_provider_asset_ids", [])
            if not isinstance(input_asset_ids, list) or not input_asset_ids:
                errors.append(f"{scene_prefix}.input_asset_ids required for output scene")
                input_asset_ids = []
            unknown_assets = [value for value in input_asset_ids if value not in workflow_asset_by_id]
            if unknown_assets:
                errors.append(f"{scene_prefix}.input_asset_ids unknown: {unknown_assets}")
            if not isinstance(required_asset_ids, list) or not required_asset_ids:
                errors.append(f"{scene_prefix}.required_asset_ids required for output scene")
                required_asset_ids = []
            unknown_required_assets = [value for value in required_asset_ids if value not in workflow_asset_by_id]
            if unknown_required_assets:
                errors.append(f"{scene_prefix}.required_asset_ids unknown: {unknown_required_assets}")
            missing_required_inputs = [value for value in required_asset_ids if value not in input_asset_ids]
            if missing_required_inputs:
                errors.append(f"{scene_prefix}.required_asset_ids not in input_asset_ids: {missing_required_inputs}")
            invalid_input_roles = [
                value for value in input_asset_ids
                if value in workflow_asset_by_id
                and workflow_asset_by_id[value].get("pipeline_role") not in {"input", "shared_input"}
            ]
            if invalid_input_roles:
                errors.append(f"{scene_prefix}.input_asset_ids contain non-input references: {invalid_input_roles}")
            if not isinstance(target_reference_asset_ids, list) or not target_reference_asset_ids:
                errors.append(f"{scene_prefix}.target_reference_asset_ids required for output scene")
                target_reference_asset_ids = []
            invalid_targets = [
                value for value in target_reference_asset_ids
                if value not in workflow_asset_by_id
                or workflow_asset_by_id[value].get("pipeline_role") != "target_reference"
            ]
            if invalid_targets:
                errors.append(f"{scene_prefix}.target_reference_asset_ids invalid: {invalid_targets}")
            if crop_receipts is not None:
                normalized_reference_frames = {
                    str(value).replace("\\", "/") for value in (scene.get("reference_frames") or [])
                }
                for target_id in target_reference_asset_ids:
                    target_asset = workflow_asset_by_id.get(target_id, {})
                    for crop in target_asset.get("crop_evidence") or []:
                        receipt = crop_receipts.get(str(crop).replace("\\", "/"), {})
                        source_path = str(receipt.get("source_path") or "").replace("\\", "/")
                        if source_path and source_path not in normalized_reference_frames:
                            errors.append(
                                f"{scene_prefix}.target {target_id} crop source absent from scene reference_frames"
                            )
            if "reference" in route and "video" in route:
                if not isinstance(required_pre_provider_asset_ids, list) or not required_pre_provider_asset_ids:
                    errors.append(f"{scene_prefix}.required_pre_provider_asset_ids required for reference-video route")
                    required_pre_provider_asset_ids = []
                unknown_required = [
                    value for value in required_pre_provider_asset_ids if value not in workflow_asset_by_id
                ]
                if unknown_required:
                    errors.append(
                        f"{scene_prefix}.required_pre_provider_asset_ids unknown: {unknown_required}"
                    )
                missing_inputs = [
                    value for value in required_pre_provider_asset_ids if value not in input_asset_ids
                ]
                if missing_inputs:
                    errors.append(
                        f"{scene_prefix}.required_pre_provider_asset_ids not in input_asset_ids: {missing_inputs}"
                    )
                if "image-to-video" in route:
                    roles = {
                        workflow_asset_by_id[value].get("role")
                        for value in input_asset_ids if value in workflow_asset_by_id
                    }
                    if "scene_start_image" not in roles:
                        errors.append(
                            f"{scene_prefix}.input_asset_ids requires scene_start_image for image-to-video route"
                        )
            elif required_pre_provider_asset_ids not in ([], None):
                errors.append(f"{scene_prefix}.required_pre_provider_asset_ids only valid for external reference-video route")
            prompt_evidence = scene.get("prompt_evidence")
            extraction = scene.get("prompt_extraction")
            if not isinstance(prompt_evidence, list):
                errors.append(f"{scene_prefix}.prompt_evidence must be a list")
                prompt_evidence = []
            if extraction not in PROMPT_EXTRACTIONS:
                errors.append(f"{scene_prefix}.prompt_extraction invalid")
            if extraction in {"exact", "detailed_paraphrase"} and not prompt_evidence:
                errors.append(f"{scene_prefix}.visible prompt requires crop evidence")
            if crop_qas is not None:
                for prompt_crop in prompt_evidence:
                    qa = crop_qas.get(str(prompt_crop).replace("\\", "/"))
                    if qa is None or qa.get("purpose") != "prompt":
                        errors.append(f"{scene_prefix}.prompt_evidence requires prompt-purpose crop QA")
                    elif scene_id not in (qa.get("supported_scene_ids") or []):
                        errors.append(
                            f"{scene_prefix}.prompt_evidence crop does not visibly support this scene"
                        )
            if isinstance(scene_id, str):
                scene_prompt_evidence[scene_id] = {
                    str(value).replace("\\", "/")
                    for value in prompt_evidence
                    if isinstance(value, str)
                }

        if sequence_kind == "prompt_carousel":
            prompt_groups = section.get("prompt_groups")
            if not isinstance(prompt_groups, list) or not prompt_groups:
                errors.append(f"{prefix}.prompt_groups required for prompt carousel")
                prompt_groups = []
            seen_group_ids: set[str] = set()
            grouped_scene_ids: list[str] = []
            for group_index, group in enumerate(prompt_groups):
                group_prefix = f"{prefix}.prompt_groups[{group_index}]"
                group_id = group.get("prompt_group_id")
                expected_group = rf"{re.escape(section_id)}-prompt-\d{{2}}" if isinstance(section_id, str) else r"$^"
                if not isinstance(group_id, str) or not re.fullmatch(expected_group, group_id):
                    errors.append(f"{group_prefix}.prompt_group_id must match <section-id>-prompt-NN")
                elif group_id in seen_group_ids:
                    errors.append(f"{group_prefix}.prompt_group_id duplicate")
                seen_group_ids.add(str(group_id))
                extraction = group.get("prompt_extraction")
                if extraction not in {"exact", "detailed_paraphrase"}:
                    errors.append(f"{group_prefix}.prompt_extraction must be exact or detailed_paraphrase")
                prompt_text = group.get("prompt_text")
                if not isinstance(prompt_text, str) or len(prompt_text.split()) < 15:
                    errors.append(f"{group_prefix}.prompt_text too short")
                prompt_evidence = group.get("prompt_evidence")
                if not isinstance(prompt_evidence, list) or not prompt_evidence:
                    errors.append(f"{group_prefix}.prompt_evidence crop required")
                    prompt_evidence = []
                elif not all(
                    isinstance(value, str)
                    and value.replace("\\", "/").startswith("crops/")
                    and _is_image_path(value)
                    for value in prompt_evidence
                ):
                    errors.append(f"{group_prefix}.prompt_evidence must be crop images")
                missing_evidence = [
                    value for value in prompt_evidence
                    if str(value).replace("\\", "/") not in evidence_paths
                ]
                if missing_evidence:
                    errors.append(f"{group_prefix}.prompt_evidence absent from evidence manifest: {missing_evidence}")
                group_scene_ids = group.get("scene_ids")
                if not isinstance(group_scene_ids, list) or not group_scene_ids:
                    errors.append(f"{group_prefix}.scene_ids missing")
                    group_scene_ids = []
                unknown_scenes = [value for value in group_scene_ids if value not in section_scene_ids]
                if unknown_scenes:
                    errors.append(f"{group_prefix}.scene_ids unknown: {unknown_scenes}")
                normalized_group_evidence = {
                    str(value).replace("\\", "/")
                    for value in prompt_evidence
                    if isinstance(value, str)
                }
                for mapped_scene_id in group_scene_ids:
                    if (
                        mapped_scene_id in scene_prompt_evidence
                        and scene_prompt_evidence[mapped_scene_id] != normalized_group_evidence
                    ):
                        errors.append(
                            f"{group_prefix}.scene_ids {mapped_scene_id} prompt_evidence differs from group"
                        )
                grouped_scene_ids.extend(group_scene_ids)
            missing_group_scenes = sorted(section_scene_ids - set(grouped_scene_ids))
            duplicate_group_scenes = sorted({value for value in grouped_scene_ids if grouped_scene_ids.count(value) > 1})
            if missing_group_scenes:
                errors.append(f"{prefix}.prompt_groups missing scenes: {missing_group_scenes}")
            if duplicate_group_scenes:
                errors.append(f"{prefix}.prompt_groups duplicate scenes: {duplicate_group_scenes}")

        mapped_scene_ids: set[str] = set()
        timed_units: list[tuple[float, float, str, int]] = []
        unit_by_id: dict[str, dict[str, Any]] = {}
        for unit_index, unit in enumerate(units):
            unit_prefix = f"{prefix}.source_units[{unit_index}]"
            unit_id = unit.get("unit_id")
            expected = rf"{re.escape(section_id)}-unit-\d{{2}}" if isinstance(section_id, str) else r"$^"
            if not isinstance(unit_id, str) or not re.fullmatch(expected, unit_id):
                errors.append(f"{unit_prefix}.unit_id must match <section-id>-unit-NN")
            elif unit_id in seen_units:
                errors.append(f"{unit_prefix}.unit_id duplicate: {unit_id}")
            else:
                seen_units.add(unit_id)
                unit_by_id[unit_id] = unit
            unit_start, unit_end = unit.get("start_seconds"), unit.get("end_seconds")
            if not isinstance(unit_start, (int, float)) or not isinstance(unit_end, (int, float)) or unit_end <= unit_start:
                errors.append(f"{unit_prefix} time range invalid")
            elif isinstance(start, (int, float)) and isinstance(end, (int, float)):
                if unit_start < start or unit_end > end:
                    errors.append(f"{unit_prefix} time range outside section")
                else:
                    timed_units.append((float(unit_start), float(unit_end), str(unit_id), unit_index))
            changes = unit.get("change_types")
            if not isinstance(changes, list) or not changes or any(value not in CHANGE_TYPES for value in changes):
                errors.append(f"{unit_prefix}.change_types invalid")
                changes = []
            if unit_index == 0 and "section_start" not in changes:
                errors.append(f"{unit_prefix}.change_types must include section_start")
            evidence_items, unit_evidence = unit.get("evidence_items"), unit.get("evidence")
            if not isinstance(evidence_items, list) or not evidence_items or not isinstance(unit_evidence, list) or not unit_evidence:
                errors.append(f"{unit_prefix}.evidence/evidence_items missing")
                evidence_items = []
            if isinstance(unit_id, str) and evidence_items != [unit_id]:
                errors.append(f"{unit_prefix}.evidence_items must be exactly [{unit_id!r}]")
            for item in evidence_items:
                row = evidence_rows.get(item)
                if evidence_manifest is not None and row is None:
                    errors.append(f"{unit_prefix}.evidence_items unknown: {item}")
                elif row is not None:
                    if row.get("coverage_kind") != "demonstrated_unit":
                        errors.append(f"{unit_prefix}.evidence_items must link demonstrated_unit rows: {item}")
                    row_start = row.get("timestamp")
                    row_range = row.get("range")
                    row_end = row_start
                    if isinstance(row_range, list) and len(row_range) == 2:
                        row_start, row_end = row_range
                    if not isinstance(row_start, (int, float)) or not isinstance(row_end, (int, float)) or row_end < unit_start or row_start > unit_end:
                        errors.append(f"{unit_prefix}.evidence timestamp does not overlap unit: {item}")
            disposition, scene_ids = unit.get("disposition"), unit.get("scene_ids")
            if disposition not in UNIT_DISPOSITIONS or not isinstance(scene_ids, list):
                errors.append(f"{unit_prefix}.disposition/scene_ids invalid")
                scene_ids = []
            if disposition in {"cataloged", "merged"}:
                if len(scene_ids) != 1 or scene_ids[0] not in all_declared_scene_ids:
                    errors.append(f"{unit_prefix}.{disposition} requires one known scene ID")
                else:
                    mapped_scene_id = scene_ids[0]
                    mapped_scene_ids.add(mapped_scene_id)
                    mapped_scene = scene_by_id.get(mapped_scene_id, {})
                    covering_occurrences = []
                    if isinstance(unit_start, (int, float)) and isinstance(unit_end, (int, float)):
                        covering_occurrences = [
                            occurrence for occurrence in (mapped_scene.get("source_occurrences") or [])
                            if occurrence.get("section_id") == section_id
                            and isinstance(occurrence.get("start_seconds"), (int, float))
                            and isinstance(occurrence.get("end_seconds"), (int, float))
                            and occurrence["start_seconds"] < unit_end
                            and occurrence["end_seconds"] > unit_start
                        ]
                    if not covering_occurrences:
                        errors.append(
                            f"{unit_prefix}.{disposition} lacks matching scene source_occurrence"
                        )
            if disposition == "non_scene" and scene_ids:
                errors.append(f"{unit_prefix}.non_scene must not map scene IDs")
            if disposition in {"merged", "non_scene"} and not unit.get("rationale"):
                errors.append(f"{unit_prefix}.{disposition} rationale missing")
            if disposition == "merged" and HARD_CHANGE_TYPES.intersection(changes):
                errors.append(f"{unit_prefix}.merged forbidden for hard visual change")

        ordered = sorted(timed_units, key=lambda item: (item[0], item[1]))
        if [item[3] for item in ordered] != list(range(len(ordered))):
            errors.append(f"{prefix}.source_units must be sorted by start_seconds")
        if ordered and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            if ordered[0][0] > float(start) + tolerance:
                errors.append(f"{prefix}.source_units leave uncovered section start")
            covered_end = ordered[0][1]
            for unit_start, unit_end, unit_id, _ in ordered[1:]:
                if unit_start > covered_end + tolerance:
                    errors.append(f"{prefix}.source_units gap {covered_end:g}-{unit_start:g} before {unit_id}")
                covered_end = max(covered_end, unit_end)
            if covered_end < float(end) - tolerance:
                errors.append(f"{prefix}.source_units leave uncovered section end")
        change_points = section.get("change_points")
        if not isinstance(change_points, list):
            errors.append(f"{prefix}.change_points must be a list")
            change_points = []
        expected_to = [item[2] for item in ordered[1:]]
        if len(change_points) != len(expected_to):
            errors.append(f"{prefix}.change_points must cover every source-unit boundary")
        for point_index, point in enumerate(change_points):
            point_prefix = f"{prefix}.change_points[{point_index}]"
            if point_index >= len(expected_to) or point.get("to_unit_id") != expected_to[point_index]:
                errors.append(f"{point_prefix}.to_unit_id must follow unit order")
                continue
            if point.get("from_unit_id") != ordered[point_index][2]:
                errors.append(f"{point_prefix}.from_unit_id must be previous source unit")
            to_unit = unit_by_id.get(point.get("to_unit_id"), {})
            changes = point.get("change_types")
            if not isinstance(changes, list) or set(changes) != set(to_unit.get("change_types", [])):
                errors.append(f"{point_prefix}.change_types must match to-unit change_types")
            disposition = point.get("disposition")
            if disposition not in CHANGE_DISPOSITIONS:
                errors.append(f"{point_prefix}.disposition invalid")
            if HARD_CHANGE_TYPES.intersection(changes or []) and disposition != "new_scene":
                errors.append(f"{point_prefix}.hard visual change requires cataloged new scene")
        missing_scene_units = sorted(section_scene_ids - mapped_scene_ids)
        if missing_scene_units:
            errors.append(f"{prefix}.scenes lack source-unit mapping: {missing_scene_units}")
        if sequence_kind in MULTI_SCENE_KINDS and len(mapped_scene_ids) < 2:
            errors.append(f"{prefix}.{sequence_kind} requires at least two mapped addressable scenes")
        if sequence_kind in MULTI_SCENE_KINDS:
            discovery = discovery_ranges.get(section_id)
            if discovery is None:
                errors.append(f"{prefix} multi-scene detail requires adaptive range discovery")
            else:
                if discovery.get("method") != "adaptive_scene_change":
                    errors.append(f"{prefix} detail discovery method invalid")
                discovery_start = discovery.get("start_seconds")
                discovery_end = discovery.get("end_seconds")
                if not isinstance(discovery_start, (int, float)) or not isinstance(start, (int, float)) or discovery_start > start + tolerance:
                    errors.append(f"{prefix} detail discovery misses section start")
                if not isinstance(discovery_end, (int, float)) or not isinstance(end, (int, float)) or discovery_end < end - tolerance:
                    errors.append(f"{prefix} detail discovery misses section end")
                raw_candidates = discovery.get("candidate_timestamps")
                resolutions = discovery.get("resolutions")
                if not isinstance(raw_candidates, list) or not raw_candidates:
                    errors.append(f"{prefix} detail discovery candidates missing")
                    candidates = []
                else:
                    candidates = [value for value in raw_candidates if isinstance(value, (int, float))]
                    if len(candidates) != len(raw_candidates):
                        errors.append(f"{prefix} detail discovery candidates invalid")
                if discovery.get("status") != "complete":
                    errors.append(f"{prefix} detail discovery status must be complete")
                if not isinstance(resolutions, list):
                    errors.append(f"{prefix} detail discovery resolutions must be a list")
                    resolutions = []
                resolved: set[float] = set()
                scene_resolutions_by_unit: dict[str, int] = {}
                for resolution_index, resolution in enumerate(resolutions):
                    resolution_prefix = f"{prefix}.discovery_resolutions[{resolution_index}]"
                    timestamp = resolution.get("timestamp")
                    if not isinstance(timestamp, (int, float)) or not any(abs(timestamp - value) <= 0.02 for value in candidates):
                        errors.append(f"{resolution_prefix}.timestamp not a discovery candidate")
                        continue
                    if float(timestamp) in resolved:
                        errors.append(f"{resolution_prefix}.timestamp duplicate")
                    resolved.add(float(timestamp))
                    unit = unit_by_id.get(resolution.get("unit_id"))
                    if unit is None:
                        errors.append(f"{resolution_prefix}.unit_id unknown")
                    elif not (
                        float(unit.get("start_seconds", timestamp + 1)) - tolerance
                        <= timestamp
                        <= float(unit.get("end_seconds", timestamp - 1)) + tolerance
                    ):
                        errors.append(f"{resolution_prefix}.unit_id does not contain timestamp")
                    if resolution.get("disposition") not in {"scene", "same_scene", "non_scene"}:
                        errors.append(f"{resolution_prefix}.disposition invalid")
                    elif unit is not None:
                        resolution_disposition = resolution.get("disposition")
                        unit_disposition = unit.get("disposition")
                        if resolution_disposition == "scene":
                            if unit_disposition != "cataloged":
                                errors.append(f"{resolution_prefix}.scene requires cataloged unit")
                            unit_id = str(unit.get("unit_id"))
                            scene_resolutions_by_unit[unit_id] = scene_resolutions_by_unit.get(unit_id, 0) + 1
                        elif resolution_disposition == "same_scene" and unit_disposition not in {"cataloged", "merged"}:
                            errors.append(f"{resolution_prefix}.same_scene requires cataloged or merged unit")
                        elif resolution_disposition == "non_scene" and unit_disposition != "non_scene":
                            errors.append(f"{resolution_prefix}.non_scene requires non_scene unit")
                    if not resolution.get("observation"):
                        errors.append(f"{resolution_prefix}.observation missing")
                missing_candidates = [value for value in candidates if float(value) not in resolved]
                if missing_candidates:
                    errors.append(f"{prefix} unresolved detail candidates: {missing_candidates}")
                duplicate_scene_units = sorted(
                    unit_id for unit_id, count in scene_resolutions_by_unit.items() if count > 1
                )
                if duplicate_scene_units:
                    errors.append(
                        f"{prefix} multiple scene resolutions mapped to same source unit; use same_scene or split units: "
                        f"{duplicate_scene_units}"
                    )

    if section_map is not None:
        missing = sorted(set(mapped_sections) - seen_sections)
        if missing:
            errors.append(f"catalog missing high-level sections: {missing}")
    if detail_ids and detail_scene_count == 0:
        errors.append("detail pass requires at least one addressable scene")
    for asset_id, asset in workflow_asset_by_id.items():
        consumed = asset.get("consumed_by_scene_ids")
        if not isinstance(consumed, list) or not consumed:
            continue
        unknown_scenes = [value for value in consumed if value not in seen_scenes]
        if unknown_scenes:
            errors.append(f"workflow asset {asset_id}.consumed_by_scene_ids unknown: {unknown_scenes}")
        for scene_id in consumed or []:
            scene = scene_by_id.get(scene_id, {})
            pipeline_role = asset.get("pipeline_role")
            if pipeline_role in {"input", "shared_input"} and asset_id not in (scene.get("input_asset_ids") or []):
                errors.append(f"workflow asset {asset_id} missing from {scene_id}.input_asset_ids")
            if pipeline_role == "target_reference" and asset_id not in (scene.get("target_reference_asset_ids") or []):
                errors.append(f"workflow asset {asset_id} missing from {scene_id}.target_reference_asset_ids")
    target_crop_owners: dict[str, list[str]] = {}
    for asset_id, asset in workflow_asset_by_id.items():
        if asset.get("pipeline_role") != "target_reference":
            continue
        for crop in asset.get("crop_evidence") or []:
            target_crop_owners.setdefault(str(crop).replace("\\", "/"), []).append(asset_id)
    for crop, owners in target_crop_owners.items():
        if len(owners) > 1:
            errors.append(f"target reference crop must be scene-specific: {crop} used by {sorted(owners)}")

    if crop_qas is not None:
        normalized_fact_claims = {
            (
                str(claim.get("subject") or "").strip().lower(),
                str(claim.get("value") or "").strip().lower(),
                str(evidence_path).replace("\\", "/"),
            )
            for claim in fact_claims
            for evidence_path in (claim.get("evidence") or [])
        }
        for crop_path, qa in crop_qas.items():
            if qa.get("purpose") != "target_output":
                continue
            candidates = qa.get("visible_fact_candidates")
            if not isinstance(candidates, list):
                errors.append(f"target crop QA visible_fact_candidates must be a list: {crop_path}")
                continue
            for candidate in candidates:
                subject = str((candidate or {}).get("subject") or "").strip().lower()
                value = str((candidate or {}).get("value") or "").strip().lower()
                if not subject or not value:
                    errors.append(f"target crop QA fact candidate incomplete: {crop_path}")
                elif (subject, value, crop_path) not in normalized_fact_claims:
                    errors.append(
                        f"target crop visible fact missing from fact_claims: {subject}={value} ({crop_path})"
                    )

    transcript_scene_claims = [
        claim for claim in (section_map or {}).get("source_count_claims", [])
        if str(claim.get("label") or "").lower() in {"scene", "scenes", "shot", "shots", "clip", "clips"}
    ]
    scene_claims: dict[str, dict[str, Any]] = {
        f"transcript-count-{index + 1:02}": claim
        for index, claim in enumerate(transcript_scene_claims)
    }
    scene_claims.update(visual_claim_by_id)
    scene_claim_counts = {
        claim.get("count") for claim in scene_claims.values()
        if isinstance(claim.get("count"), int)
    }
    for section_index, section in enumerate(sections):
        if section.get("role") != "showcase_production" or section.get("sequence_kind") != "finished_sequence":
            continue
        mapped_ids = {
            scene_id
            for unit in section.get("source_units", [])
            if unit.get("disposition") in {"cataloged", "merged"}
            for scene_id in unit.get("scene_ids", [])
        }
        if scene_claim_counts and len(mapped_ids) not in scene_claim_counts:
            errors.append(
                f"sections[{section_index}].finished_sequence maps {len(mapped_ids)} scenes; "
                f"must match a preserved source scene-count claim {sorted(scene_claim_counts)}"
            )
    reconciliation = payload.get("count_reconciliation")
    if not isinstance(reconciliation, list):
        errors.append("count_reconciliation must be a list")
        reconciliation = []
    reconciled_claim_ids: list[str] = []
    known_section_ids = {section.get("section_id") for section in sections}
    for row_index, row in enumerate(reconciliation):
        row_prefix = f"count_reconciliation[{row_index}]"
        claim_ids = row.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids:
            errors.append(f"{row_prefix}.claim_ids missing")
            claim_ids = []
        unknown_claim_ids = [value for value in claim_ids if value not in scene_claims]
        if unknown_claim_ids:
            errors.append(f"{row_prefix}.claim_ids unknown: {unknown_claim_ids}")
        reconciled_claim_ids.extend(claim_ids)
        section_ids = row.get("section_ids")
        if not isinstance(section_ids, list) or not section_ids:
            errors.append(f"{row_prefix}.section_ids missing")
            section_ids = []
        unknown_section_ids = [value for value in section_ids if value not in known_section_ids]
        if unknown_section_ids:
            errors.append(f"{row_prefix}.section_ids unknown: {unknown_section_ids}")
        observed = sum(
            len(section.get("scenes", []))
            for section in sections
            if section.get("section_id") in section_ids
        )
        if row.get("observed_scene_count") != observed:
            errors.append(f"{row_prefix}.observed_scene_count mismatch")
        status = row.get("status")
        if status not in {"matched", "explained_mismatch", "not_comparable"}:
            errors.append(f"{row_prefix}.status invalid")
        claim_counts = {scene_claims[value].get("count") for value in claim_ids if value in scene_claims}
        if status == "matched" and observed not in claim_counts:
            errors.append(f"{row_prefix} matched without matching source count")
        if status != "matched" and not row.get("explanation"):
            errors.append(f"{row_prefix}.explanation required")
    missing_claims = sorted(set(scene_claims) - set(reconciled_claim_ids))
    duplicate_claims = sorted({value for value in reconciled_claim_ids if reconciled_claim_ids.count(value) > 1})
    if missing_claims:
        errors.append(f"count_reconciliation missing claims: {missing_claims}")
    if duplicate_claims:
        errors.append(f"count_reconciliation duplicate claims: {duplicate_claims}")
    return errors


validate_scene_catalog = validate_scene_catalog_v13


def _source_duration_seconds(run: dict[str, Any]) -> float | None:
    source = run.get("source")
    source = source if isinstance(source, dict) else {}
    source_cache = source.get("source_cache")
    source_cache = source_cache if isinstance(source_cache, dict) else {}
    source_dir = source_cache.get("source_dir")
    config = run.get("config")
    config = config if isinstance(config, dict) else {}
    workspace_root = config.get("workspace_root")
    source_id = run.get("source_id")
    candidates: list[Path] = []
    if isinstance(source_dir, str) and source_dir:
        candidates.append(Path(source_dir) / "metadata.json")
    if isinstance(workspace_root, str) and workspace_root and isinstance(source_id, str) and source_id:
        candidates.append(Path(workspace_root) / "cache" / source_id / "source" / "metadata.json")
    for metadata_path in candidates:
        if not metadata_path.is_file():
            continue
        try:
            metadata = read_json(metadata_path)
            duration = metadata.get("duration") if isinstance(metadata, dict) else None
        except (OSError, ValueError):
            continue
        if isinstance(duration, (int, float)) and duration > 0:
            return float(duration)
    return None


def _parse_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_run_provenance(run_dir: Path, run: dict[str, Any]) -> list[str]:
    """Require every run, including repairs, to come from the runtime run factory."""
    errors: list[str] = []
    run_id = run.get("run_id")
    if run_id != run_dir.name:
        errors.append("run_id must equal run directory name")
    match = re.fullmatch(
        r"(\d{8}T\d{12}Z)-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{10}",
        str(run_id or ""),
    )
    created_at = _parse_created_at(run.get("created_at"))
    if match is None:
        errors.append("run_id must use runtime timestamp-target-fingerprint format")
        run_timestamp = None
    else:
        try:
            run_timestamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S%fZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            run_timestamp = None
            errors.append("run_id timestamp invalid")
    if created_at is None:
        errors.append("created_at must be a valid timezone-aware timestamp")
    elif run_timestamp is not None and abs((created_at - run_timestamp).total_seconds()) > 2:
        errors.append("created_at must match run_id timestamp")

    parent_run_id = run.get("parent_run_id")
    if parent_run_id:
        parent_path = run_dir.parent / str(parent_run_id) / "run.json"
        if not parent_path.is_file():
            errors.append("parent_run_id must reference an existing sibling run")
        else:
            try:
                parent = read_json(parent_path)
                if not isinstance(parent, dict):
                    parent = {}
                    errors.append("parent run manifest must be an object")
            except (OSError, ValueError, json.JSONDecodeError):
                parent = {}
                errors.append("parent run manifest unreadable")
            if parent.get("run_id") != parent_run_id:
                errors.append("parent run manifest identity mismatch")
            if parent.get("source_id") != run.get("source_id"):
                errors.append("repair child and parent source_id must match")
            parent_created = _parse_created_at(parent.get("created_at"))
            if created_at is not None and parent_created is not None and created_at <= parent_created:
                errors.append("repair child created_at must be later than parent created_at")
    return errors


def validate_run_helpers(run_dir: Path) -> list[str]:
    """Reject ad hoc scripts that author semantic/QA artifacts."""
    tools_dir = run_dir / "tools"
    if not tools_dir.is_dir():
        return []
    protected = {
        "section_map.json", "detail_discovery.json", "evidence_manifest.json",
        "scene_catalog.json", "guide.md", "guide_review.json",
    }
    write_markers = {
        "write_text", "writefile", "writefilesync", "set-content", "out-file",
        "open(", "convertto-json",
    }
    errors: list[str] = []
    for path in tools_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".js", ".mjs", ".cjs", ".ts"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        artifacts = sorted(name for name in protected if name in text)
        if artifacts and any(marker in text for marker in write_markers):
            relative = path.relative_to(run_dir).as_posix()
            errors.append(f"{relative} may not author semantic artifacts: {artifacts}")
    return errors


def validate_stage(
    run_dir: Path,
    stage: str,
    *,
    require_publication: bool | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"unsupported validation stage: {stage}")
    errors: list[dict[str, str]] = []
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        return _result(stage, [{"code": "RUN_MISSING", "path": "run.json", "message": "run manifest missing"}])
    run = read_json(run_path)
    if not isinstance(run, dict):
        return _result(stage, [{"code": "RUN_SCHEMA_UNSUPPORTED", "path": "run.json", "message": "v2 run object required"}])
    if run.get("schema_version") != 2:
        return _result(stage, [{"code": "RUN_SCHEMA_UNSUPPORTED", "path": "run.json", "message": "v2 run schema required"}])
    for message in validate_run_provenance(run_dir, run):
        errors.append({"code": "RUN_PROVENANCE_INVALID", "path": "run.json", "message": message})
    artifact_rows = run.get("artifacts", [])
    if not isinstance(artifact_rows, list):
        errors.append({"code": "RUN_ARTIFACTS_INVALID", "path": "run.json.artifacts", "message": "artifacts must be a list"})
        artifact_rows = []
    seen_artifact_keys: set[tuple[str, str]] = set()
    for index, record in enumerate(artifact_rows):
        if not isinstance(record, dict):
            errors.append({
                "code": "RUN_ARTIFACTS_INVALID",
                "path": f"run.json.artifacts[{index}]",
                "message": "artifact record must be an object",
            })
            continue
        key = (str(record.get("role", "")), str(record.get("path", "")).replace("\\", "/"))
        if key in seen_artifact_keys:
            errors.append({
                "code": "ARTIFACT_ROLE_AMBIGUOUS",
                "path": f"run.json.artifacts[{index}]",
                "message": f"duplicate current artifact role/path: {key[0]} / {key[1]}",
            })
        seen_artifact_keys.add(key)
    errors.extend(_validate_registered_json(run_dir, run))
    for message in verify_artifacts(run_dir):
        if "hash mismatch" in message:
            code = "ARTIFACT_HASH_MISMATCH"
        elif " missing:" in message:
            code = "ARTIFACT_MISSING"
        else:
            code = "ARTIFACT_INVALID"
        errors.append({"code": code, "path": "run.json.artifacts", "message": message})

    evidence: dict[str, Any] | None = None
    evidence_path = run_dir / "evidence_manifest.json"
    if not evidence_path.is_file():
        errors.append({"code": "EVIDENCE_MISSING", "path": "evidence_manifest.json", "message": "evidence manifest missing"})
    else:
        evidence_value = read_json(evidence_path)
        if not isinstance(evidence_value, dict):
            errors.append({"code": "EVIDENCE_INVALID", "path": "evidence_manifest.json", "message": "evidence manifest must be an object"})
        else:
            evidence = evidence_value
            complete = stage not in {"scaffold", "section-mapped"}
            for message in validate_evidence_manifest(evidence, require_complete=complete):
                errors.append({"code": "EVIDENCE_INCOMPLETE", "path": "evidence_manifest.json", "message": message})
            for message in validate_crop_evidence(run_dir, evidence, require_complete=complete):
                errors.append({"code": "CROP_EVIDENCE_INVALID", "path": "evidence_manifest.json", "message": message})
            if complete and evidence.get("transcript_available") is False:
                errors.append(
                    {
                        "code": "TRANSCRIPT_UNAVAILABLE",
                        "path": "evidence_manifest.json.transcript_available",
                        "message": "supply JSON/VTT/SRT or mark target visual-only with reviewed justification",
                    }
                )

    section_map: dict[str, Any] | None = None
    section_map_path = run_dir / "section_map.json"
    if stage != "scaffold":
        if not section_map_path.is_file():
            errors.append({"code": "SECTION_MAP_MISSING", "path": "section_map.json", "message": "transcript-led section map missing"})
        else:
            section_map_value = read_json(section_map_path)
            if not isinstance(section_map_value, dict):
                errors.append({"code": "SECTION_MAP_INVALID", "path": "section_map.json", "message": "section map must be an object"})
            else:
                section_map = section_map_value
                for message in validate_section_map(
                    section_map,
                    require_detail_complete=stage not in {"section-mapped", "evidence-complete"},
                    source_duration_seconds=_source_duration_seconds(run),
                ):
                    errors.append({"code": "SECTION_MAP_INVALID", "path": "section_map.json", "message": message})
            roles = {item.get("role") for item in artifact_rows}
            if "section_map" not in roles:
                errors.append({"code": "SECTION_MAP_UNREGISTERED", "path": "run.json.artifacts", "message": "section map artifact not registered"})

    detail_discovery: dict[str, Any] | None = None
    discovery_path = run_dir / "detail_discovery.json"
    if discovery_path.is_file():
        detail_value = read_json(discovery_path)
        if not isinstance(detail_value, dict):
            errors.append({"code": "DETAIL_DISCOVERY_INVALID", "path": "detail_discovery.json", "message": "detail discovery must be an object"})
        else:
            detail_discovery = detail_value
        if detail_discovery is not None and (detail_discovery.get("schema_version") != 1 or not isinstance(detail_discovery.get("ranges"), list)):
            errors.append({"code": "DETAIL_DISCOVERY_INVALID", "path": "detail_discovery.json", "message": "schema-v1 ranges required"})
        roles = {item.get("role") for item in artifact_rows}
        if "detail_discovery" not in roles:
            errors.append({"code": "DETAIL_DISCOVERY_UNREGISTERED", "path": "run.json.artifacts", "message": "detail discovery artifact not registered"})

    if stage in {"guide-complete", "scene-ready", "assets-approved", "comparison-complete", "delivery-complete"}:
        for message in validate_run_helpers(run_dir):
            errors.append({"code": "SEMANTIC_HELPER_FORBIDDEN", "path": "tools", "message": message})
        guide = run_dir / "guide.md"
        if not guide.is_file():
            errors.append({"code": "GUIDE_MISSING", "path": "guide.md", "message": "guide missing"})
        catalog_path = run_dir / "scene_catalog.json"
        if not catalog_path.is_file():
            errors.append({"code": "SCENE_CATALOG_MISSING", "path": "scene_catalog.json", "message": "source section and scene catalog missing"})
        else:
            catalog = read_json(catalog_path)
            crop_receipts: dict[str, dict[str, Any]] = {}
            crop_qas: dict[str, dict[str, Any]] = {}
            for receipt_path in (run_dir / "crops").glob("*.crop.json"):
                receipt = read_json(receipt_path)
                if not isinstance(receipt, dict):
                    errors.append({"code": "CROP_EVIDENCE_INVALID", "path": receipt_path.relative_to(run_dir).as_posix(), "message": "crop receipt must be an object"})
                    continue
                crop_path = receipt.get("crop_path")
                if isinstance(crop_path, str):
                    crop_receipts[crop_path.replace("\\", "/")] = receipt
            for qa_path in (run_dir / "crops").glob("*.crop-qa.json"):
                qa = read_json(qa_path)
                if not isinstance(qa, dict):
                    errors.append({"code": "CROP_EVIDENCE_INVALID", "path": qa_path.relative_to(run_dir).as_posix(), "message": "crop QA must be an object"})
                    continue
                crop_path = qa.get("crop_path")
                if isinstance(crop_path, str):
                    crop_qas[crop_path.replace("\\", "/")] = qa
            for message in validate_scene_catalog_v13(
                catalog,
                require_complete=True,
                evidence_manifest=evidence,
                section_map=section_map,
                detail_discovery=detail_discovery,
                crop_receipts=crop_receipts,
                crop_qas=crop_qas,
            ):
                errors.append({"code": "SCENE_CATALOG_INCOMPLETE", "path": "scene_catalog.json", "message": message})
            roles = {item.get("role") for item in artifact_rows}
            if "scene_catalog" not in roles:
                errors.append({"code": "SCENE_CATALOG_UNREGISTERED", "path": "run.json.artifacts", "message": "scene catalog artifact not registered"})
            if guide.is_file() and catalog.get("status") == "complete":
                guide_text = guide.read_text(encoding="utf-8")
                required_ids = [section.get("section_id") for section in catalog.get("sections", [])]
                required_ids.extend(
                    scene.get("scene_id")
                    for section in catalog.get("sections", [])
                    for scene in section.get("scenes", [])
                )
                required_ids.extend(
                    group.get("prompt_group_id")
                    for section in catalog.get("sections", [])
                    for group in section.get("prompt_groups", [])
                )
                required_ids.extend(
                    asset.get("asset_id") for asset in catalog.get("workflow_assets", [])
                )
                missing_ids = [item for item in required_ids if item and item not in guide_text]
                if missing_ids:
                    errors.append({
                        "code": "GUIDE_SCENE_CATALOG_MISSING",
                        "path": "guide.md",
                        "message": f"guide must expose addressable section/scene IDs: {missing_ids}",
                    })
                for message in _validate_guide_scene_inventory(guide_text, catalog):
                    errors.append({
                        "code": "GUIDE_SCENE_INVENTORY_INVALID",
                        "path": "guide.md",
                        "message": message,
                    })
        config = run.get("config")
        if not isinstance(config, dict):
            errors.append({"code": "RUN_CONFIG_INVALID", "path": "run.json.config", "message": "config must be an object"})
            config = {}
        publication_required = (
            require_publication
            if require_publication is not None
            else config.get("public_guide_required")
            or (run_dir / "guide_publication.json").exists()
        )
        if publication_required:
            _validate_guide_publication(run_dir, run, errors)

    if stage in {"scene-ready", "assets-approved", "comparison-complete", "delivery-complete"}:
        _validate_scene_preparation(run_dir, errors, stage=stage)

    derived_status = "valid"
    if stage in {"assets-approved", "comparison-complete", "delivery-complete"}:
        _validate_asset_proof(run_dir, errors)
    if stage in {"comparison-complete", "delivery-complete"}:
        derived_status = _validate_proof(run_dir, errors)
    if stage == "delivery-complete":
        _validate_production(run_dir, errors)
    elif errors:
        derived_status = "invalid"
    return _result(stage, errors, derived_status=derived_status)


def _validate_guide_scene_inventory(guide_text: str, catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    lines = guide_text.splitlines()
    all_scene_ids = [
        scene.get("scene_id")
        for section in catalog.get("sections", [])
        for scene in section.get("scenes", [])
        if scene.get("scene_id")
    ]
    used_lines: set[int] = set()
    for section in catalog.get("sections", []):
        for scene in section.get("scenes", []):
            scene_id = scene.get("scene_id")
            title = scene.get("title")
            matching = [index for index, line in enumerate(lines) if scene_id and scene_id in line]
            if len(matching) != 1:
                errors.append(f"{scene_id} must appear in exactly one guide inventory row")
                continue
            line_index = matching[0]
            line = lines[line_index]
            if line_index in used_lines or sum(item in line for item in all_scene_ids) != 1:
                errors.append(f"{scene_id} must have its own guide inventory row")
            used_lines.add(line_index)
            if isinstance(title, str) and title.strip() and title.lower() not in line.lower():
                errors.append(f"{scene_id} guide inventory row must include title: {title}")
    return errors


def _validate_guide_publication(
    run_dir: Path,
    run: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    publication_path = run_dir / "guide_publication.json"
    if not publication_path.is_file():
        errors.append({
            "code": "PUBLIC_GUIDE_MISSING",
            "path": "guide_publication.json",
            "message": (
                "publish guide under docs/reconstructions/<source-id>/workflow.md; "
                "run publish-guide after local guide-complete preflight"
            ),
        })
        return
    publication = read_json(publication_path)
    if not isinstance(publication, dict):
        errors.append({"code": "PUBLIC_GUIDE_INVALID", "path": "guide_publication.json", "message": "publication receipt must be an object"})
        return
    workspace_text = publication.get("workspace_root")
    if not isinstance(workspace_text, str) or not workspace_text.strip():
        errors.append({"code": "PUBLIC_GUIDE_INVALID", "path": "guide_publication.json", "message": "workspace_root missing"})
        return
    workspace = Path(workspace_text).resolve()
    expected_guide = f"docs/reconstructions/{run.get('source_id')}/workflow.md"
    expected_catalog = f"docs/reconstructions/{run.get('source_id')}/scene-catalog.json"
    for key, expected, source_name, hash_key in (
        ("guide_path", expected_guide, "guide.md", "guide_sha256"),
        ("scene_catalog_path", expected_catalog, "scene_catalog.json", "scene_catalog_sha256"),
    ):
        relative = publication.get(key)
        if relative != expected:
            errors.append({"code": "PUBLIC_GUIDE_INVALID", "path": f"guide_publication.json.{key}", "message": f"expected {expected}"})
            continue
        public_path = (workspace / relative).resolve()
        try:
            public_path.relative_to(workspace / "docs" / "reconstructions")
        except ValueError:
            errors.append({"code": "PUBLIC_GUIDE_INVALID", "path": relative, "message": "publication escaped docs/reconstructions"})
            continue
        source_path = run_dir / source_name
        if not public_path.is_file():
            errors.append({
                "code": "PUBLIC_GUIDE_MISSING",
                "path": relative,
                "message": "published artifact missing; run publish-guide after local snapshot validates",
            })
        elif sha256_file(public_path) != publication.get(hash_key) or sha256_file(public_path) != sha256_file(source_path):
            errors.append({
                "code": "PUBLIC_GUIDE_STALE",
                "path": relative,
                "message": (
                    "published artifact differs from run snapshot; run publish-guide again "
                    "only after local snapshot validates"
                ),
            })
    if "guide_publication" not in {item.get("role") for item in run.get("artifacts", [])}:
        errors.append({"code": "PUBLIC_GUIDE_UNREGISTERED", "path": "run.json.artifacts", "message": "guide publication record not registered"})


def validate_bundle(root: Path, *, require_complete_qa: bool = False) -> list[str]:
    errors: list[str] = []
    if not (root / "run.json").exists():
        errors.append("missing run.json")
    evidence_path = root / "evidence_manifest.json"
    if evidence_path.exists():
        evidence = read_json(evidence_path)
        errors.extend(validate_evidence_manifest(evidence))
        errors.extend(validate_crop_evidence(root, evidence, require_complete=require_complete_qa))
    for qa_path in root.rglob("qa.json"):
        qa_errors = validate_qa_record(read_json(qa_path), require_complete=require_complete_qa)
        errors.extend(f"{qa_path}: {error}" for error in qa_errors)
    return errors


def _validate_scene_preparation(run_dir: Path, errors: list[dict[str, str]], *, stage: str) -> None:
    guide = run_dir / "guide.md"
    review_path = run_dir / "guide_review.json"
    if not review_path.is_file():
        errors.append({"code": "GUIDE_REVIEW_MISSING", "path": "guide_review.json", "message": "approved guide review missing"})
    elif guide.is_file():
        review = read_json(review_path)
        if review.get("decision") != "approve":
            errors.append({"code": "GUIDE_REJECTED", "path": "guide_review.json.decision", "message": "guide not approved"})
        if review.get("guide_sha256") != sha256_file(guide):
            errors.append({"code": "GUIDE_REVIEW_STALE", "path": "guide_review.json.guide_sha256", "message": "guide changed after review"})
    required_scene_plan = (
        "scene_plan/reconstruction_spec.json",
        "scene_plan/reference_manifest.json",
        "scene_plan/pipeline_contract.json",
        "scene_plan/motion_manifest.json",
        "scene_plan/asset_ledger.json",
        "scene_plan/handoff.md",
    )
    for relative in required_scene_plan:
        if not (run_dir / relative).is_file():
            errors.append({"code": "SCENE_PLAN_ARTIFACT_MISSING", "path": relative, "message": "scene plan artifact missing"})
    spec_path = run_dir / "scene_plan/reconstruction_spec.json"
    references_path = run_dir / "scene_plan/reference_manifest.json"
    motion_path = run_dir / "scene_plan/motion_manifest.json"
    pipeline_path = run_dir / "scene_plan/pipeline_contract.json"
    fidelity = None
    if spec_path.is_file():
        spec = read_json(spec_path)
        fidelity = spec.get("fidelity_mode")
        for message in validate_reconstruction_spec(spec):
            errors.append({"code": "RECONSTRUCTION_SPEC_INVALID", "path": "scene_plan/reconstruction_spec.json", "message": message})
    if references_path.is_file():
        for message in validate_reference_manifest(read_json(references_path), run_dir=run_dir):
            errors.append({"code": "REFERENCE_MANIFEST_INVALID", "path": "scene_plan/reference_manifest.json", "message": message})
    if motion_path.is_file():
        for message in validate_motion_manifest(read_json(motion_path)):
            errors.append({"code": "MOTION_MANIFEST_INVALID", "path": "scene_plan/motion_manifest.json", "message": message})
    if pipeline_path.is_file():
        for message in validate_pipeline_contract(read_json(pipeline_path), run_dir=run_dir, require_ready=True):
            errors.append({"code": "PIPELINE_CONTRACT_INVALID", "path": "scene_plan/pipeline_contract.json", "message": message})
    ledger_path = run_dir / "scene_plan/asset_ledger.json"
    if ledger_path.is_file():
        ledger = read_json(ledger_path)
        if ledger.get("guide_sha256") != (read_json(review_path).get("guide_sha256") if review_path.is_file() else None):
            errors.append({"code": "SCENE_PLAN_GUIDE_STALE", "path": "scene_plan/asset_ledger.json.guide_sha256", "message": "scene plan guide hash mismatch"})
        for message in validate_asset_ledger(ledger, require_planned=stage == "scene-ready"):
            errors.append({"code": "SCENE_PLAN_LEDGER_INVALID", "path": "scene_plan/asset_ledger.json", "message": message})
        if fidelity and ledger.get("fidelity_mode") != fidelity:
            errors.append({"code": "FIDELITY_MODE_MISMATCH", "path": "scene_plan/asset_ledger.json.fidelity_mode", "message": "ledger fidelity differs from target lock"})


def _validate_proof(run_dir: Path, errors: list[dict[str, str]]) -> str:
    required = ("proof/input_ledger.json", "proof/prompt.txt", "proof/provider.json", "proof/output.mp4", "proof/qa.json")
    for relative in required:
        if not (run_dir / relative).is_file():
            errors.append({"code": "PROOF_ARTIFACT_MISSING", "path": relative, "message": "proof provenance incomplete"})
    qa_path = run_dir / "proof/qa.json"
    if not qa_path.is_file():
        return "invalid"
    qa = read_json(qa_path)
    _validate_pipeline_execution(run_dir, errors, provider_path=run_dir / "proof/provider.json", output_path=run_dir / "proof/output.mp4")
    spec_path = run_dir / "scene_plan/reconstruction_spec.json"
    fidelity = read_json(spec_path).get("fidelity_mode") if spec_path.is_file() else None
    for message in validate_qa_record(qa, require_complete=True, require_fidelity=fidelity != "method_only"):
        errors.append({"code": "QA_INCOMPLETE", "path": "proof/qa.json", "message": message})
    return derive_qa_status(qa) if not errors else "invalid"


def validate_reconstruction_spec(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if payload.get("fidelity_mode") not in FIDELITY_MODES:
        errors.append("fidelity_mode invalid")
    if payload.get("lifecycle_stage") != "scene-planned":
        errors.append("lifecycle_stage must be scene-planned")
    lock = payload.get("target_lock")
    if not isinstance(lock, dict) or lock.get("immutable") is not True:
        errors.append("immutable target_lock missing")
    else:
        for field in ("content", "style", "composition", "typography", "motion"):
            if lock.get(field) in {None, "", "pending"}:
                errors.append(f"target_lock.{field} unresolved")
    return errors


def validate_reference_manifest(payload: dict[str, Any], *, run_dir: Path | None = None) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 3:
        errors.append("schema_version must be 3")
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["scenes must be non-empty"]
    for index, scene in enumerate(scenes):
        prefix = f"scenes[{index}]"
        if not scene.get("scene_id") or not scene.get("prompt_group_id") or not scene.get("observed_elements"):
            errors.append(f"{prefix} identity/elements missing")
        frames = scene.get("reference_frames")
        if not isinstance(frames, list):
            errors.append(f"{prefix} needs start/mid/final reference roles")
        else:
            roles = {item.get("role") for item in frames}
            if not {"start", "mid", "final"}.issubset(roles):
                errors.append(f"{prefix} reference roles incomplete")
            for item in frames:
                _validate_semantic_reference(item, scene, prefix, errors, run_dir)
            start = next((item for item in frames if item.get("role") == "start"), {})
            if start.get("availability", "available") != "available":
                errors.append(f"{prefix} start reference must be available")
        if payload.get("fidelity_mode") != "method_only":
            motion_status = scene.get("motion_reference_status")
            motion_samples = scene.get("motion_samples")
            if motion_status not in {"complete", "partial", "not_demonstrated"}:
                errors.append(f"{prefix} motion_reference_status invalid")
            if motion_status == "complete" and not motion_samples:
                errors.append(f"{prefix} complete motion reference needs samples")
            if motion_status in {"partial", "not_demonstrated"} and not scene.get("motion_reference_reason"):
                errors.append(f"{prefix} motion_reference_reason missing")
            if not scene.get("typography_refs"):
                errors.append(f"{prefix} typography_refs missing")
            for item in motion_samples or []:
                _validate_semantic_reference(item, scene, prefix, errors, run_dir)
            for item in scene.get("typography_refs", []):
                _validate_reference_path(item, prefix, errors, run_dir)
    return errors


def _validate_semantic_reference(
    item: dict[str, Any],
    scene: dict[str, Any],
    prefix: str,
    errors: list[str],
    run_dir: Path | None,
) -> None:
    availability = item.get("availability", "available")
    if availability == "unavailable":
        if not item.get("reason"):
            errors.append(f"{prefix} unavailable reference reason missing")
        if item.get("path") or item.get("sha256"):
            errors.append(f"{prefix} unavailable reference must not bind a file")
        return
    if availability != "available":
        errors.append(f"{prefix} reference availability invalid")
        return
    if item.get("target_match") != "pass" or not item.get("reviewer"):
        errors.append(f"{prefix} available reference needs reviewed target_match=pass")
    if item.get("prompt_group_id") != scene.get("prompt_group_id"):
        errors.append(f"{prefix} reference prompt group mismatch")
    if not item.get("source_evidence_path"):
        errors.append(f"{prefix} source_evidence_path missing")
    _validate_reference_path(item, prefix, errors, run_dir)


def _validate_reference_path(item: dict[str, Any], prefix: str, errors: list[str], run_dir: Path | None) -> None:
    path_value = item.get("path")
    if not path_value or not item.get("sha256"):
        errors.append(f"{prefix} reference path/hash missing")
        return
    if run_dir:
        path = run_dir / path_value
        if not path.is_file():
            errors.append(f"{prefix} reference file missing: {path_value}")
        elif sha256_file(path) != item.get("sha256"):
            errors.append(f"{prefix} reference hash mismatch: {path_value}")


def validate_motion_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["scenes must be non-empty"]
    for index, scene in enumerate(scenes):
        prefix = f"scenes[{index}]"
        for field in ("scene_id", "observed_motion", "elements", "timing_refs", "code_strategy"):
            if not scene.get(field):
                errors.append(f"{prefix}.{field} missing")
        if scene.get("implementation") != "scene-specific":
            errors.append(f"{prefix} must use scene-specific implementation")
        tracks = scene.get("timeline_tracks")
        track_roles: set[str] = set()
        if not isinstance(tracks, list) or not tracks:
            errors.append(f"{prefix} named timeline_tracks missing")
        else:
            element_ids = {
                element.get("id") for element in scene.get("elements", []) if element.get("id")
            }
            covered_ids: set[str] = set()
            for track_index, track in enumerate(tracks):
                track_prefix = f"{prefix}.timeline_tracks[{track_index}]"
                required = (
                    track.get("name"), track.get("role"), track.get("element_ids"),
                    track.get("source_component"), track.get("prop_controls"),
                )
                if (
                    not all(required)
                    or track.get("from") is None
                    or not track.get("duration_in_frames")
                ):
                    errors.append(f"{prefix}.timeline_tracks[{track_index}] incomplete")
                    continue
                unknown = set(track["element_ids"]) - element_ids
                if unknown:
                    errors.append(f"{track_prefix} references unknown elements: {sorted(unknown)}")
                covered_ids.update(track["element_ids"])
                track_roles.add(track["role"])
            uncovered = element_ids - covered_ids
            if uncovered:
                errors.append(f"{prefix} elements missing timeline track coverage: {sorted(uncovered)}")
        for element in scene.get("elements", []):
            if element.get("kind") == "chart":
                if element.get("code_native") is not True or not element.get("series") or not element.get("draw_behavior"):
                    errors.append(f"{prefix} chart must be code-native with series and draw behavior")
                if not element.get("research"):
                    errors.append(f"{prefix} chart implementation research missing")
                required_chart_roles = {
                    "chart_container", "chart_axes", "chart_series", "chart_points", "chart_labels",
                }
                missing_roles = required_chart_roles - track_roles
                if missing_roles:
                    errors.append(f"{prefix} chart timeline breakdown missing roles: {sorted(missing_roles)}")
                series_ids = {
                    str(series.get("id") or series.get("name")) if isinstance(series, dict) else str(series)
                    for series in (element.get("series") or [])
                }
                series_ids.discard("None")
                if len(series_ids) > 1:
                    for series_index, series in enumerate(element.get("series") or []):
                        if not isinstance(series, dict) or not series.get("id"):
                            errors.append(f"{prefix}.series[{series_index}] needs stable id")
                            continue
                        if series.get("draw_behavior") not in {
                            "self_draw", "partial_polyline", "clip_reveal", "path_evolution"
                        }:
                            errors.append(
                                f"{prefix}.series[{series_index}] needs independent frame-derived draw_behavior"
                            )
                        if series.get("initial_state") not in {"hidden", "zero_progress"}:
                            errors.append(
                                f"{prefix}.series[{series_index}] must begin hidden or at zero_progress"
                            )
                    series_tracks = [
                        track for track in (tracks or []) if track.get("role") == "chart_series"
                    ]
                    if any(len(track.get("series_ids") or []) != 1 for track in series_tracks):
                        errors.append(f"{prefix} each chart series needs its own named timeline row")
                    covered_series = {
                        str(series_id)
                        for track in series_tracks
                        for series_id in (track.get("series_ids") or [])
                    }
                    missing_series = series_ids - covered_series
                    if missing_series:
                        errors.append(
                            f"{prefix} independently tweakable chart series missing timeline rows: {sorted(missing_series)}"
                        )
    return errors


def _tool_key(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def validate_pipeline_contract(
    payload: dict[str, Any], *, run_dir: Path | None = None, require_ready: bool = False
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    requested_action = payload.get("requested_action")
    target_choice = payload.get("target_choice")
    if requested_action not in {"recreate", "create"}:
        errors.append("requested_action must be recreate or create")
    if target_choice not in {"match", "adapt", "method"}:
        errors.append("target_choice must be match, adapt, or method")
    if requested_action == "recreate" and target_choice != "match":
        errors.append("recreate pipeline must use target_choice match")
    if requested_action == "create" and target_choice == "match":
        errors.append("create pipeline must use target_choice adapt or method")
    framework_policy = payload.get("framework_policy", "source_exact")
    if framework_policy not in {"source_exact", "user_required"}:
        errors.append("framework_policy must be source_exact or user_required")
    requested_framework = payload.get("requested_framework")
    if framework_policy == "user_required" and not requested_framework:
        errors.append("requested_framework required when framework_policy is user_required")
    policy = payload.get("asset_policy", {})
    if _tool_key(policy.get("raster_generator")) != "imagegen2":
        errors.append("asset_policy.raster_generator must be imagegen2")
    if policy.get("generate_only_required") is not True:
        errors.append("asset_policy.generate_only_required must be true")
    tutorial = payload.get("tutorial_stages")
    selected = payload.get("selected_stages")
    if not isinstance(tutorial, list) or not tutorial:
        return errors + ["tutorial_stages must be non-empty"]
    if not isinstance(selected, list) or not selected:
        return errors + ["selected_stages must be non-empty"]
    selected_by_id = {item.get("stage_id"): item for item in selected if item.get("stage_id")}
    production_roles = {"motion_runtime", "video_generation", "assembly", "render"}
    if not any(item.get("role") in production_roles for item in tutorial):
        errors.append("tutorial production stage missing")
    for index, source in enumerate(tutorial):
        prefix = f"tutorial_stages[{index}]"
        for field in ("stage_id", "role", "tool_kind", "observed_tool", "evidence_refs"):
            if not source.get(field):
                errors.append(f"{prefix}.{field} missing")
        stage_id = source.get("stage_id")
        target = selected_by_id.get(stage_id)
        if not target:
            errors.append(f"{prefix} has no selected stage")
            continue
        for field in ("selected_tool", "selected_tool_kind", "match", "status"):
            if not target.get(field):
                errors.append(f"selected stage {stage_id}.{field} missing")
        kind = source.get("tool_kind")
        match = target.get("match")
        if source.get("role") == "asset_generation":
            if (
                _tool_key(target.get("selected_tool")) != "imagegen2"
                or match != "policy_override"
                or target.get("status") not in {"ready", "authorized"}
            ):
                errors.append(f"selected stage {stage_id} must use ready ImageGen2 policy override")
            continue
        selected_kind = target.get("selected_tool_kind")
        if framework_policy == "source_exact":
            if match != "exact":
                errors.append(f"selected stage {stage_id} must exactly follow the source pipeline")
            if _tool_key(target.get("selected_tool")) != _tool_key(source.get("observed_tool")):
                errors.append(f"selected stage {stage_id} exact source tool mismatch")
            if selected_kind != kind:
                errors.append(f"selected stage {stage_id} tool kind must remain {kind}")
        elif framework_policy == "user_required":
            if match != "exact" or _tool_key(target.get("selected_tool")) != _tool_key(requested_framework):
                errors.append(f"selected stage {stage_id} must use explicitly requested method {requested_framework}")

        code_video_tools = {"hyperframes", "remotion", "gsap", "ffmpeg", "aftereffects"}
        selected_tool_key = _tool_key(target.get("selected_tool"))
        if (
            source.get("role") == "video_generation"
            and kind == "external_provider"
            and framework_policy != "user_required"
            and any(tool in selected_tool_key for tool in code_video_tools)
        ):
            errors.append(
                f"selected stage {stage_id} cannot replace generative video with a code-video framework"
            )

        if kind == "local_framework":
            selected_tool = target.get("selected_tool")
            observed_tool = source.get("observed_tool")
            if framework_policy == "user_required":
                if match != "exact" or _tool_key(selected_tool) != _tool_key(requested_framework):
                    errors.append(f"selected stage {stage_id} must use requested local framework {requested_framework}")
            elif match != "exact" or _tool_key(selected_tool) != _tool_key(observed_tool):
                errors.append(f"selected stage {stage_id} must use exact source local framework")
            framework_key = _tool_key(selected_tool)
            required_fields = (
                ("project_root", "source_files", "readiness_record", "check_command", "preview_command", "render_command")
                if framework_key == "hyperframes"
                else ("project_root", "package_manifest", "lockfile", "source_files", "readiness_record", "studio_command", "render_command")
            )
            for field in required_fields:
                if not target.get(field):
                    errors.append(f"selected stage {stage_id}.{field} missing")
            if require_ready and target.get("status") != "ready":
                errors.append(f"selected stage {stage_id} local framework not ready")
            if require_ready and run_dir:
                _validate_local_framework_files(run_dir, target, errors)
        elif kind == "external_provider":
            status = target.get("status")
            if status == "awaiting_user_approval":
                forbidden = [field for field in ("output", "render_command", "native_source") if target.get(field)]
                if forbidden:
                    errors.append(
                        f"selected stage {stage_id} awaiting approval must not have executed outputs: {forbidden}"
                    )
            elif status not in {"ready", "authorized", "blocked_external"}:
                errors.append(f"selected stage {stage_id}.status invalid for external provider")
            if require_ready and status not in {"ready", "authorized"}:
                errors.append(f"selected stage {stage_id} external provider not authorized/ready")
        else:
            errors.append(f"{prefix}.tool_kind invalid")
    return errors


def _validate_local_framework_files(run_dir: Path, target: dict[str, Any], errors: list[str]) -> None:
    stage_id = target.get("stage_id")
    selected_tool = _tool_key(target.get("selected_tool"))
    if selected_tool == "hyperframes":
        required_paths = [
            target.get("project_root"),
            target.get("readiness_record"),
            target.get("project_marker"),
            target.get("check_receipt"),
            target.get("render_receipt"),
            target.get("approval_record"),
        ]
        required_paths.extend(target.get("source_files") or [])
        for relative in required_paths:
            if not relative or not (run_dir / relative).exists():
                errors.append(f"selected stage {stage_id} framework file missing: {relative}")
        readiness_path = run_dir / str(target.get("readiness_record") or "")
        if readiness_path.is_file():
            readiness = read_json(readiness_path)
            if readiness.get("status") != "ready" or _tool_key(readiness.get("framework")) != "hyperframes":
                errors.append(f"selected stage {stage_id} HyperFrames readiness record invalid")
        _validate_hyperframes_receipts(run_dir, target, errors, stage_id)
        return
    required_paths = [target.get("project_root"), target.get("package_manifest"), target.get("lockfile"), target.get("readiness_record")]
    required_paths.extend(target.get("source_files") or [])
    for relative in required_paths:
        if not relative or not (run_dir / relative).exists():
            errors.append(f"selected stage {stage_id} framework file missing: {relative}")
    readiness_path = run_dir / str(target.get("readiness_record") or "")
    if readiness_path.is_file():
        readiness = read_json(readiness_path)
        if readiness.get("status") != "ready" or _tool_key(readiness.get("framework")) != _tool_key(target.get("selected_tool")):
            errors.append(f"selected stage {stage_id} readiness record invalid")
    if _tool_key(target.get("selected_tool")) == "remotion":
        manifest_path = run_dir / str(target.get("package_manifest") or "")
        if manifest_path.is_file():
            package = read_json(manifest_path)
            dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            if "remotion" not in dependencies or "@remotion/cli" not in dependencies:
                errors.append(f"selected stage {stage_id} package must install remotion and @remotion/cli")
        source_files = target.get("source_files") or []
        if not any(str(path).lower().endswith((".tsx", ".jsx")) for path in source_files):
            errors.append(f"selected stage {stage_id} Remotion React composition source missing")


def _validate_hyperframes_receipts(run_dir: Path, target: dict[str, Any], errors: list[str], stage_id: object) -> None:
    check_path = run_dir / str(target.get("check_receipt") or "")
    render_path = run_dir / str(target.get("render_receipt") or "")
    approval_path = run_dir / str(target.get("approval_record") or "")
    marker_path = run_dir / str(target.get("project_marker") or "")
    if not check_path.is_file() or not render_path.is_file() or not approval_path.is_file():
        errors.append(f"selected stage {stage_id} HyperFrames native receipts missing")
        return
    try:
        check = read_json(check_path)
        render = read_json(render_path)
        approval = read_json(approval_path)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append(f"selected stage {stage_id} HyperFrames native receipt invalid")
        return
    if check.get("framework") != "HyperFrames" or check.get("status") != "pass" or check.get("exit_code") != 0:
        errors.append(f"selected stage {stage_id} HyperFrames check receipt invalid")
    if not _is_hyperframes_command(check.get("command"), "check"):
        errors.append(f"selected stage {stage_id} HyperFrames check command provenance invalid")
    if marker_path.is_file() and check.get("project_marker", {}).get("sha256") != sha256_file(marker_path):
        errors.append(f"selected stage {stage_id} HyperFrames project marker hash mismatch")
    for source in check.get("source_files") or []:
        if not isinstance(source, dict) or not source.get("path") or not source.get("sha256"):
            errors.append(f"selected stage {stage_id} HyperFrames source hash record invalid")
            continue
        try:
            source_path = (marker_path.parent / str(source["path"])).resolve()
            source_path.relative_to(marker_path.parent.resolve())
        except ValueError:
            source_path = None
        if source_path is None or not source_path.is_file() or source["sha256"] != sha256_file(source_path):
            errors.append(f"selected stage {stage_id} HyperFrames source hash mismatch: {source.get('path')}")
    check_log = run_dir / str(target.get("check_log") or "")
    if not check_log.is_file() or check.get("log", {}).get("sha256") != sha256_file(check_log):
        errors.append(f"selected stage {stage_id} HyperFrames check log hash mismatch")
    if render.get("framework") != "HyperFrames" or render.get("status") != "pass" or render.get("exit_code") != 0:
        errors.append(f"selected stage {stage_id} HyperFrames render receipt invalid")
    if not _is_hyperframes_command(render.get("command"), "render"):
        errors.append(f"selected stage {stage_id} HyperFrames render command provenance invalid")
    if render.get("check_receipt_sha256") != sha256_file(check_path):
        errors.append(f"selected stage {stage_id} HyperFrames render is not bound to current check receipt")
    render_log = run_dir / str(target.get("render_log") or "")
    if not render_log.is_file() or render.get("render_log", {}).get("sha256") != sha256_file(render_log):
        errors.append(f"selected stage {stage_id} HyperFrames render log hash mismatch")
    if approval.get("framework") != "HyperFrames" or approval.get("status") != "approved" or not approval.get("reviewer"):
        errors.append(f"selected stage {stage_id} HyperFrames preview approval record invalid")
    if not marker_path.is_file() or render.get("project_marker_sha256") != sha256_file(marker_path):
        errors.append(f"selected stage {stage_id} HyperFrames render marker binding invalid")


def _validate_hyperframes_delivery_receipts(
    scene_dir: Path,
    framework: dict[str, Any],
    project_root: Path | None,
    errors: list[dict[str, str]],
) -> None:
    fields = (
        ("check_receipt", "HYPERFRAMES_CHECK_RECEIPT_MISSING"),
        ("render_receipt", "HYPERFRAMES_RENDER_RECEIPT_MISSING"),
        ("approval_record", "HYPERFRAMES_APPROVAL_MISSING"),
    )
    paths: dict[str, Path] = {}
    for field, code in fields:
        path = _resolve_delivery_path(scene_dir, framework.get(field))
        if path is None or not path.is_file():
            errors.append({"code": code, "path": f"artifact-manifest.json.framework.{field}", "message": f"HyperFrames {field} missing"})
        else:
            paths[field] = path
    if len(paths) != len(fields):
        return
    try:
        check = read_json(paths["check_receipt"])
        render = read_json(paths["render_receipt"])
        approval = read_json(paths["approval_record"])
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append({"code": "HYPERFRAMES_RECEIPT_INVALID", "path": "artifact-manifest.json.framework", "message": "HyperFrames receipt JSON invalid"})
        return
    if check.get("framework") != "HyperFrames" or check.get("status") != "pass" or check.get("exit_code") != 0:
        errors.append({"code": "HYPERFRAMES_CHECK_RECEIPT_INVALID", "path": str(paths["check_receipt"]), "message": "native HyperFrames check receipt invalid"})
    if render.get("framework") != "HyperFrames" or render.get("status") != "pass" or render.get("exit_code") != 0:
        errors.append({"code": "HYPERFRAMES_RENDER_RECEIPT_INVALID", "path": str(paths["render_receipt"]), "message": "native HyperFrames render receipt invalid"})
    if approval.get("framework") != "HyperFrames" or approval.get("status") != "approved" or not approval.get("reviewer"):
        errors.append({"code": "HYPERFRAMES_APPROVAL_INVALID", "path": str(paths["approval_record"]), "message": "preview approval record invalid"})
    check_log = _resolve_delivery_path(scene_dir, framework.get("check_log"))
    render_log = _resolve_delivery_path(scene_dir, framework.get("render_log"))
    if check_log is None or not check_log.is_file() or check.get("log", {}).get("sha256") != sha256_file(check_log):
        errors.append({"code": "HYPERFRAMES_CHECK_LOG_HASH", "path": "artifact-manifest.json.framework.check_log", "message": "check log hash mismatch"})
    if render_log is None or not render_log.is_file() or render.get("render_log", {}).get("sha256") != sha256_file(render_log):
        errors.append({"code": "HYPERFRAMES_RENDER_LOG_HASH", "path": "artifact-manifest.json.framework.render_log", "message": "render log hash mismatch"})
    if render.get("check_receipt_sha256") != sha256_file(paths["check_receipt"]):
        errors.append({"code": "HYPERFRAMES_RECEIPT_CHAIN", "path": str(paths["render_receipt"]), "message": "render receipt is not bound to current check receipt"})
    marker = _resolve_delivery_path(scene_dir, framework.get("project_marker"))
    if marker is None or render.get("project_marker_sha256") != sha256_file(marker):
        errors.append({"code": "HYPERFRAMES_RENDER_MARKER", "path": str(paths["render_receipt"]), "message": "render receipt is not bound to current project marker"})
    if marker is None or not marker.is_file() or check.get("project_marker", {}).get("sha256") != sha256_file(marker):
        errors.append({"code": "HYPERFRAMES_MARKER_HASH", "path": "artifact-manifest.json.framework.project_marker", "message": "project marker hash mismatch"})
    for source in check.get("source_files") or []:
        if not isinstance(source, dict) or not source.get("path") or not source.get("sha256"):
            errors.append({"code": "HYPERFRAMES_SOURCE_HASH", "path": str(paths["check_receipt"]), "message": "source hash record invalid"})
            continue
        try:
            source_path = (project_root / str(source["path"])).resolve() if project_root is not None else None
            if source_path is not None:
                source_path.relative_to(project_root.resolve())
        except ValueError:
            source_path = None
        if source_path is None or not source_path.is_file() or source["sha256"] != sha256_file(source_path):
            errors.append({"code": "HYPERFRAMES_SOURCE_HASH", "path": str(paths["check_receipt"]), "message": f"source hash mismatch: {source.get('path')}"})
    output = render.get("output") or {}
    output_path = None
    if isinstance(output, dict) and output.get("path") and project_root is not None:
        try:
            output_path = (project_root / str(output["path"])).resolve()
            output_path.relative_to(project_root.resolve())
        except ValueError:
            output_path = None
    if output_path is None or not output_path.is_file() or output.get("sha256") != sha256_file(output_path):
        errors.append({"code": "HYPERFRAMES_OUTPUT_HASH", "path": str(paths["render_receipt"]), "message": "native output hash mismatch"})
    if not isinstance(render.get("ffprobe"), dict) or not render.get("ffprobe"):
        errors.append({"code": "HYPERFRAMES_FFPROBE_MISSING", "path": str(paths["render_receipt"]), "message": "native output FFprobe facts missing"})


def _is_hyperframes_command(value: object, action: str) -> bool:
    tokens = str(value or "").casefold().split()
    return any(token == "hyperframes" or token.startswith("hyperframes@") for token in tokens) and action.casefold() in tokens


def _validate_pipeline_execution(
    run_dir: Path, errors: list[dict[str, str]], *, provider_path: Path, output_path: Path
) -> None:
    contract_path = run_dir / "scene_plan/pipeline_contract.json"
    if not contract_path.is_file() or not provider_path.is_file():
        return
    contract = read_json(contract_path)
    local_stages = [
        (source, next((item for item in contract.get("selected_stages", []) if item.get("stage_id") == source.get("stage_id")), {}))
        for source in contract.get("tutorial_stages", [])
        if source.get("tool_kind") == "local_framework"
    ]
    if not local_stages:
        return
    provider = read_json(provider_path)
    ledger_path = run_dir / "scene_plan/asset_ledger.json"
    ledger = read_json(ledger_path) if ledger_path.is_file() else {"assets": []}
    approved_raster = [
        asset for asset in ledger.get("assets", [])
        if asset.get("semantic_type") in RASTER_ASSETS and asset.get("status") == "approved"
    ]
    bindings = {item.get("asset_id"): item for item in provider.get("asset_bindings", []) if item.get("asset_id")}
    for asset in approved_raster:
        binding = bindings.get(asset.get("id"), {})
        output = asset.get("output", {})
        if (
            binding.get("asset_path") != output.get("path")
            or binding.get("asset_sha256") != output.get("sha256")
            or binding.get("source_file") not in provider.get("source_files", [])
        ):
            errors.append({"code": "RASTER_ASSET_BINDING_INVALID", "path": str(provider_path.relative_to(run_dir)), "message": f"approved ImageGen2 asset not bound in render source: {asset.get('id')}"})
    for source, selected in local_stages:
        framework = selected.get("selected_tool")
        if _tool_key(provider.get("framework")) != _tool_key(framework):
            errors.append({"code": "PIPELINE_EXECUTION_MISMATCH", "path": str(provider_path.relative_to(run_dir)), "message": f"proof must be rendered by {framework}"})
        for field in ("project_root", "composition_id", "source_files", "render_command", "render_log", "output_sha256"):
            if not provider.get(field):
                errors.append({"code": "PIPELINE_EXECUTION_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": f"framework render provenance missing: {field}"})
        if provider.get("project_root") != selected.get("project_root"):
            errors.append({"code": "PIPELINE_EXECUTION_MISMATCH", "path": str(provider_path.relative_to(run_dir)), "message": "render project differs from approved pipeline"})
        for relative in (provider.get("source_files") or []) + [provider.get("render_log")]:
            if relative and not (run_dir / relative).is_file():
                errors.append({"code": "PIPELINE_EXECUTION_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": f"render provenance file missing: {relative}"})
        if _tool_key(framework) == "remotion":
            studio = provider.get("studio_timeline", {})
            for field in ("manifest_path", "screenshot_path", "visible_track_names", "status"):
                if not studio.get(field):
                    errors.append({"code": "REMOTION_STUDIO_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": f"Remotion Studio timeline provenance missing: {field}"})
            if studio.get("status") != "pass":
                errors.append({"code": "REMOTION_STUDIO_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": "Remotion Studio timeline verification must pass"})
            for field in ("manifest_path", "screenshot_path"):
                relative = studio.get(field)
                if relative and not (run_dir / relative).is_file():
                    errors.append({"code": "REMOTION_STUDIO_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": f"Remotion Studio evidence file missing: {relative}"})
            manifest_relative = studio.get("manifest_path")
            if manifest_relative and (run_dir / manifest_relative).is_file():
                timeline = read_json(run_dir / manifest_relative)
                expected = {track.get("name") for track in timeline.get("tracks", []) if track.get("name")}
                visible = set(studio.get("visible_track_names") or [])
                if expected - visible:
                    errors.append({"code": "REMOTION_STUDIO_PROVENANCE", "path": str(provider_path.relative_to(run_dir)), "message": f"Studio screenshot verification missing tracks: {sorted(expected - visible)}"})
        if output_path.is_file() and provider.get("output_sha256") != sha256_file(output_path):
            errors.append({"code": "PIPELINE_OUTPUT_HASH_MISMATCH", "path": str(provider_path.relative_to(run_dir)), "message": "render output hash mismatch"})


def validate_asset_ledger(payload: dict[str, Any], *, require_planned: bool = False) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if payload.get("fidelity_mode") not in FIDELITY_MODES:
        errors.append("fidelity_mode invalid")
    if require_planned:
        if payload.get("status") != "planning" or payload.get("lifecycle_stage") != "scene-planned":
            errors.append("scene ledger must be planning/scene-planned")
        if payload.get("provider_submission") != "not_authorized":
            errors.append("scene preparation must stop before provider submission")
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append("assets must be non-empty")
    else:
        for index, asset in enumerate(assets):
            prefix = f"assets[{index}]"
            for field in ("id", "scene_id", "role", "semantic_type", "route", "reference_paths", "target", "status"):
                if not asset.get(field):
                    errors.append(f"{prefix}.{field} missing")
            semantic = asset.get("semantic_type") in SEMANTIC_ASSETS
            route = asset.get("route")
            reference_type = asset.get("reference_input_type")
            provider = asset.get("provider_intent", {})
            if semantic and route not in SEMANTIC_ROUTES:
                errors.append(f"{prefix} semantic asset requires image_generation")
            if semantic and not reference_type:
                errors.append(f"{prefix}.reference_input_type missing")
            if semantic and reference_type in COMPOSITE_REFERENCE_TYPES:
                if route != "image_generation" or provider.get("capability") != "image_edit":
                    errors.append(f"{prefix} composite-frame semantic asset requires image_generation/image_edit")
                if not asset.get("reference_image_paths"):
                    errors.append(f"{prefix} composite-frame image edit needs reference_image_paths")
            if asset.get("semantic_type") in RASTER_ASSETS:
                model_text = f"{provider.get('provider', '')} {provider.get('model', '')}".lower()
                if any(name in model_text for name in RASTER_ONLY_MODELS):
                    errors.append(f"{prefix} Pillow/FFmpeg/raster crop cannot create semantic asset")
                if route != "image_generation" or _tool_key(provider.get("model")) != "imagegen2":
                    errors.append(f"{prefix} raster asset must use built-in ImageGen2")
                generation_intent = asset.get("generation_intent")
                if generation_intent not in IMAGE_GENERATION_INTENTS:
                    errors.append(f"{prefix}.generation_intent invalid or missing")
                if (
                    payload.get("fidelity_mode") == "reference_reconstruction"
                    and reference_type in COMPOSITE_REFERENCE_TYPES
                    and generation_intent != "source_asset_reconstruction"
                ):
                    errors.append(
                        f"{prefix} Recreate shown-image raster must use source_asset_reconstruction"
                    )
                if provider.get("quality_policy") != "highest_available":
                    errors.append(f"{prefix} ImageGen2 quality_policy must be highest_available")
                if generation_intent == "source_asset_reconstruction":
                    if provider.get("capability") != "image_edit" or not asset.get("reference_image_paths"):
                        errors.append(f"{prefix} source asset reconstruction requires ImageGen2 image_edit references")
                    source_lock = asset.get("source_lock", {})
                    missing_locks = sorted(
                        field for field in SOURCE_RECONSTRUCTION_LOCKS if source_lock.get(field) is not True
                    )
                    if missing_locks:
                        errors.append(f"{prefix} source reconstruction locks missing: {missing_locks}")
                    prompt_text = str(asset.get("exact_prompt") or "").lower()
                    conflicts = sorted(
                        phrase for phrase in SOURCE_RECONSTRUCTION_PROMPT_CONFLICTS if phrase in prompt_text
                    )
                    if conflicts:
                        errors.append(f"{prefix} source reconstruction prompt contradicts exact layout target: {conflicts}")
            if route in SEMANTIC_ROUTES:
                if not asset.get("exact_prompt") or not asset.get("negative_constraints") or not asset.get("provider_intent"):
                    errors.append(f"{prefix} generation prompt/provider intent missing")
            if asset.get("semantic_type") == "typography":
                if asset.get("route") != "bundled_font" or not asset.get("font_name") or not asset.get("license"):
                    errors.append(f"{prefix} typography requires bundled licensed font")
        if payload.get("fidelity_mode") != "method_only" and not any(
            asset.get("semantic_type") == "typography" for asset in assets
        ):
            errors.append("style/reference reconstruction needs typography asset plan")
    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        errors.append("exact provider-ready prompts missing")
    else:
        for index, prompt in enumerate(prompts):
            if not prompt.get("id") or not prompt.get("target_ref") or not prompt.get("exact_prompt"):
                errors.append(f"prompts[{index}] incomplete")
    return errors


def validate_source_reconstruction_result(asset: dict[str, Any], result: dict[str, Any]) -> list[str]:
    if asset.get("generation_intent") != "source_asset_reconstruction":
        return []
    gates = result.get("source_reconstruction_gates", {})
    missing = sorted(REQUIRED_SOURCE_RECONSTRUCTION_GATES - set(gates))
    errors: list[str] = []
    if missing:
        errors.append(f"source reconstruction QA gates missing: {missing}")
    failed = sorted(name for name, status in gates.items() if status != "pass")
    if failed:
        errors.append(f"source reconstruction QA gates not passed: {failed}")
    return errors


def _validate_asset_proof(run_dir: Path, errors: list[dict[str, str]]) -> None:
    ledger_path = run_dir / "scene_plan/asset_ledger.json"
    qa_path = run_dir / "scene_plan/asset_qa.json"
    if not ledger_path.is_file() or not qa_path.is_file():
        errors.append({"code": "ASSET_PROOF_MISSING", "path": "scene_plan/asset_qa.json", "message": "approved asset proof missing"})
        return
    ledger = read_json(ledger_path)
    if ledger.get("lifecycle_stage") not in {"assets-approved", "motion-proof-approved", "full-rendered"}:
        errors.append({"code": "ASSET_LIFECYCLE_INVALID", "path": "scene_plan/asset_ledger.json", "message": "assets not approved"})
    assets = ledger.get("assets", [])
    raster_assets = [asset for asset in assets if asset.get("semantic_type") in RASTER_ASSETS]
    generated = [asset for asset in assets if asset.get("status") in {"generated", "approved"}]
    if not generated:
        errors.append({"code": "ASSET_OUTPUT_MISSING", "path": "scene_plan/asset_ledger.json.assets", "message": "no generated asset output"})
    incomplete_raster = [asset.get("id") for asset in raster_assets if asset.get("status") != "approved"]
    if incomplete_raster:
        errors.append({"code": "RASTER_ASSETS_NOT_APPROVED", "path": "scene_plan/asset_ledger.json.assets", "message": f"all raster assets must be ImageGen2-approved before rendering: {incomplete_raster}"})
    for asset in generated:
        output = asset.get("output", {})
        if not output.get("path") or not output.get("sha256"):
            errors.append({"code": "ASSET_OUTPUT_PROVENANCE", "path": "scene_plan/asset_ledger.json.assets", "message": f"asset {asset.get('id')} output path/hash missing"})
        elif not (run_dir / output["path"]).is_file():
            errors.append({"code": "ASSET_OUTPUT_PROVENANCE", "path": "scene_plan/asset_ledger.json.assets", "message": f"asset {asset.get('id')} output file missing"})
        elif sha256_file(run_dir / output["path"]) != output.get("sha256"):
            errors.append({"code": "ASSET_OUTPUT_PROVENANCE", "path": "scene_plan/asset_ledger.json.assets", "message": f"asset {asset.get('id')} output hash mismatch"})
        if asset.get("semantic_type") in RASTER_ASSETS:
            receipt = asset.get("generation_receipt", {})
            if (
                _tool_key(receipt.get("provider")) not in {"imagegen", "builtinimagegen"}
                or _tool_key(receipt.get("model")) != "imagegen2"
                or not receipt.get("tool_call_id")
                or not receipt.get("prompt_sha256")
                or not receipt.get("reference_sha256s")
            ):
                errors.append({"code": "IMAGEGEN2_RECEIPT_INVALID", "path": "scene_plan/asset_ledger.json.assets", "message": f"asset {asset.get('id')} needs built-in ImageGen2 tool receipt"})
    if any(asset.get("route") in SEMANTIC_ROUTES for asset in generated):
        authorization = ledger.get("provider_authorization", {})
        if (
            authorization.get("status") != "authorized"
            or _tool_key(authorization.get("provider")) not in {"imagegen", "builtinimagegen"}
            or _tool_key(authorization.get("model")) != "imagegen2"
        ):
            errors.append({"code": "PROVIDER_AUTH_INVALID", "path": "scene_plan/asset_ledger.json.provider_authorization", "message": "generated semantic assets need named provider/model authorization"})
    qa = read_json(qa_path)
    gates = qa.get("gates", {})
    asset_results = qa.get("asset_results", [])
    result_by_id = {item.get("asset_id"): item for item in asset_results if item.get("asset_id")}
    semantic_generated = [asset for asset in generated if asset.get("semantic_type") in RASTER_ASSETS]
    matte_invalid = False
    source_reconstruction_invalid = False
    for asset in semantic_generated:
        result = result_by_id.get(asset.get("id"), {})
        edge_checks = result.get("edge_checks", {})
        if (
            result.get("result") != "pass"
            or not result.get("reference_path")
            or not result.get("output_path")
            or not result.get("matte_method")
            or result.get("defects")
            or not edge_checks
            or any(value != "pass" for value in edge_checks.values())
        ):
            matte_invalid = True
        if validate_source_reconstruction_result(asset, result):
            source_reconstruction_invalid = True
    if (
        qa.get("status") != "pass"
        or not qa.get("reference_paths")
        or not qa.get("output_path")
        or not qa.get("output_sha256")
        or not qa.get("observations")
        or REQUIRED_ASSET_GATES - set(gates)
        or any(value != "pass" for value in gates.values())
        or matte_invalid
        or source_reconstruction_invalid
        or len(result_by_id) < len(semantic_generated)
    ):
        errors.append({"code": "ASSET_QA_INVALID", "path": "scene_plan/asset_qa.json", "message": "reference-backed asset QA must pass"})


def _validate_production(run_dir: Path, errors: list[dict[str, str]]) -> None:
    for relative in ("production/master.mp4", "production/provider.json", "production/qa.json"):
        if not (run_dir / relative).is_file():
            errors.append({"code": "PRODUCTION_ARTIFACT_MISSING", "path": relative, "message": "production output missing"})
    qa_path = run_dir / "production/qa.json"
    if qa_path.is_file():
        qa = read_json(qa_path)
        if qa.get("status") != "pass" or not qa.get("reference_paths") or not qa.get("scene_results"):
            errors.append({"code": "PRODUCTION_QA_INVALID", "path": "production/qa.json", "message": "production reference QA must pass"})
    _validate_pipeline_execution(run_dir, errors, provider_path=run_dir / "production/provider.json", output_path=run_dir / "production/master.mp4")


def _find_catalog_scene(catalog: dict[str, Any], scene_id: str) -> dict[str, Any] | None:
    for section in catalog.get("sections", []):
        for scene in section.get("scenes", []):
            if scene.get("scene_id") == scene_id:
                return scene
    return None


def _catalog_scene_prompt_group(catalog: dict[str, Any], scene: dict[str, Any]) -> str | None:
    explicit = scene.get("prompt_group_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    scene_id = scene.get("scene_id")
    for section in catalog.get("sections", []):
        for group in section.get("prompt_groups", []):
            if scene_id in (group.get("scene_ids") or []):
                return group.get("prompt_group_id")
    return None


def _catalog_scene_reference_paths(scene: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for field in ("evidence", "reference_frames"):
        for value in scene.get(field, []) or []:
            if isinstance(value, str):
                paths.add(value.replace("\\", "/"))
            elif isinstance(value, dict) and isinstance(value.get("path"), str):
                paths.add(value["path"].replace("\\", "/"))
    return paths


def _resolve_delivery_path(scene_dir: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (scene_dir / path).resolve()


def _delivery_file_error(
    scene_dir: Path,
    record: dict[str, Any],
    *,
    field: str,
    code: str,
    errors: list[dict[str, str]],
) -> Path | None:
    path = _resolve_delivery_path(scene_dir, record.get(field))
    if path is None or not path.is_file():
        errors.append({"code": code, "path": str(record.get(field) or field), "message": "file missing"})
        return None
    expected_hash = record.get("sha256") if field == "path" else record.get(f"{field}_sha256")
    if expected_hash and sha256_file(path) != expected_hash:
        errors.append({"code": f"{code}_HASH", "path": str(path), "message": "hash mismatch"})
    return path


def _validate_delivery_reference_pack(
    manifest: dict[str, Any],
    catalog: dict[str, Any],
    scene: dict[str, Any],
    scene_dir: Path,
    errors: list[dict[str, str]],
) -> None:
    pack = manifest.get("reference_pack")
    if not isinstance(pack, dict):
        errors.append({"code": "REFERENCE_PACK_MISSING", "path": "artifact-manifest.json.reference_pack", "message": "scene-bound reference pack missing"})
        return
    expected_group = _catalog_scene_prompt_group(catalog, scene)
    if expected_group and pack.get("target_prompt_group_id") != expected_group:
        errors.append({"code": "REFERENCE_PACK_PROMPT_GROUP_MISMATCH", "path": "artifact-manifest.json.reference_pack.target_prompt_group_id", "message": "reference pack must bind the catalog scene prompt group"})
    catalog_paths = _catalog_scene_reference_paths(scene)
    frames = pack.get("frames")
    if not isinstance(frames, list):
        errors.append({"code": "REFERENCE_PACK_FRAMES_MISSING", "path": "artifact-manifest.json.reference_pack.frames", "message": "start/mid/final reference roles missing"})
        frames = []
    roles = {item.get("role") for item in frames if isinstance(item, dict)}
    if not {"start", "mid", "final"}.issubset(roles):
        errors.append({"code": "REFERENCE_PACK_ROLES_INCOMPLETE", "path": "artifact-manifest.json.reference_pack.frames", "message": "start, mid, and final roles must each be available or explicitly unavailable"})

    def validate_item(item: dict[str, Any], index_path: str) -> None:
        availability = item.get("availability")
        if availability == "unavailable":
            if not item.get("reason"):
                errors.append({"code": "REFERENCE_UNAVAILABLE_REASON_MISSING", "path": index_path, "message": "unavailable reference needs a reason"})
            if item.get("path") or item.get("sha256") or item.get("source_evidence_path"):
                errors.append({"code": "REFERENCE_UNAVAILABLE_HAS_FILE", "path": index_path, "message": "unavailable reference must not bind a file"})
            return
        if availability != "available":
            errors.append({"code": "REFERENCE_AVAILABILITY_INVALID", "path": index_path, "message": "availability must be available or unavailable"})
            return
        if item.get("target_match") != "pass" or not item.get("reviewer"):
            errors.append({"code": "REFERENCE_TARGET_QA_MISSING", "path": index_path, "message": "available reference needs reviewed target_match=pass"})
        if item.get("prompt_group_id") != expected_group:
            errors.append({"code": "REFERENCE_PROMPT_GROUP_MISMATCH", "path": index_path, "message": "reference belongs to a different prompt group"})
        source_path = str(item.get("source_evidence_path") or "").replace("\\", "/")
        if not source_path or source_path not in catalog_paths:
            errors.append({"code": "REFERENCE_CATALOG_MISMATCH", "path": index_path, "message": "reference source is not cataloged evidence for this scene"})
        _delivery_file_error(scene_dir, item, field="path", code="REFERENCE_FILE", errors=errors)

    for index, item in enumerate(frames):
        if isinstance(item, dict):
            validate_item(item, f"artifact-manifest.json.reference_pack.frames[{index}]")
    start = next((item for item in frames if isinstance(item, dict) and item.get("role") == "start"), {})
    if start.get("availability") != "available":
        errors.append({"code": "REFERENCE_START_REQUIRED", "path": "artifact-manifest.json.reference_pack.frames", "message": "provider handoff requires a verified scene-start reference"})

    motion_status = pack.get("motion_reference_status")
    motion_samples = pack.get("motion_samples")
    if not isinstance(motion_samples, list):
        motion_samples = []
        errors.append({"code": "MOTION_REFERENCE_SAMPLES_INVALID", "path": "artifact-manifest.json.reference_pack.motion_samples", "message": "motion_samples must be a list"})
    if motion_status not in {"complete", "partial", "not_demonstrated"}:
        errors.append({"code": "MOTION_REFERENCE_STATUS_INVALID", "path": "artifact-manifest.json.reference_pack.motion_reference_status", "message": "motion reference status invalid"})
    elif motion_status == "complete" and not motion_samples:
        errors.append({"code": "MOTION_REFERENCE_MISSING", "path": "artifact-manifest.json.reference_pack.motion_samples", "message": "complete motion reference needs samples"})
    elif motion_status in {"partial", "not_demonstrated"} and not pack.get("motion_reference_reason"):
        errors.append({"code": "MOTION_REFERENCE_REASON_MISSING", "path": "artifact-manifest.json.reference_pack.motion_reference_reason", "message": "partial or unavailable motion reference needs a reason"})
    for index, item in enumerate(motion_samples):
        if isinstance(item, dict):
            validate_item(item, f"artifact-manifest.json.reference_pack.motion_samples[{index}]")


def _validate_recreate_preflight(
    scene_dir: Path,
    catalog_path: Path,
    scene: dict[str, Any],
    route: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    path = scene_dir / "recreate-preflight.json"
    if not path.is_file():
        errors.append({"code": "RECREATE_PREFLIGHT_MISSING", "path": str(path), "message": "run start-recreate before generation"})
        return
    try:
        preflight = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append({"code": "RECREATE_PREFLIGHT_INVALID", "path": str(path), "message": "preflight JSON unreadable"})
        return
    if preflight.get("schema_version") != 1 or preflight.get("status") != "ready":
        errors.append({"code": "RECREATE_PREFLIGHT_INVALID", "path": str(path), "message": "ready schema-v1 preflight required"})
    if preflight.get("scene", {}).get("scene_id") != scene.get("scene_id"):
        errors.append({"code": "RECREATE_PREFLIGHT_TARGET_MISMATCH", "path": str(path), "message": "preflight resolved another scene"})
    if preflight.get("production_route", {}).get("route_id") != route.get("route_id"):
        errors.append({"code": "RECREATE_PREFLIGHT_ROUTE_MISMATCH", "path": str(path), "message": "preflight route differs from catalog"})
    if preflight.get("catalog_sha256") != sha256_file(catalog_path):
        errors.append({"code": "RECREATE_PREFLIGHT_STALE", "path": str(path), "message": "catalog changed after preflight"})
    expected = preflight.get("expected_delivery", {})
    if expected.get("standalone_still_satisfies_recreate") is not False:
        errors.append({"code": "RECREATE_PREFLIGHT_ENDPOINT_INVALID", "path": str(path), "message": "standalone still may not satisfy Recreate"})


def _validate_code_video_delivery(
    manifest: dict[str, Any],
    route: dict[str, Any],
    scene_dir: Path,
    errors: list[dict[str, str]],
) -> None:
    if manifest.get("delivery_kind") != "video":
        errors.append({"code": "CODE_VIDEO_DELIVERY_KIND", "path": "artifact-manifest.json.delivery_kind", "message": "code-video route requires video delivery; still is intermediate only"})
    render = manifest.get("render")
    if not isinstance(render, dict):
        errors.append({"code": "CODE_VIDEO_RENDER_MISSING", "path": "artifact-manifest.json.render", "message": "native MP4 render missing"})
    else:
        render_path = _delivery_file_error(scene_dir, render, field="path", code="CODE_VIDEO_RENDER_FILE", errors=errors)
        if render_path is not None and render_path.suffix.lower() != ".mp4":
            errors.append({"code": "CODE_VIDEO_RENDER_FORMAT", "path": str(render_path), "message": "terminal render must be MP4"})
    framework = manifest.get("framework")
    if not isinstance(framework, dict):
        errors.append({"code": "CODE_VIDEO_FRAMEWORK_MISSING", "path": "artifact-manifest.json.framework", "message": "native framework provenance missing"})
        return
    if _tool_key(framework.get("tool")) != _tool_key(route.get("tool")):
        errors.append({"code": "CODE_VIDEO_FRAMEWORK_MISMATCH", "path": "artifact-manifest.json.framework.tool", "message": "framework must match catalog route"})
    framework_key = _tool_key(framework.get("tool"))
    if not framework.get("composition_id") and not framework.get("composition_ids"):
        errors.append({"code": "CODE_VIDEO_COMPOSITION_MISSING", "path": "artifact-manifest.json.framework.composition_id", "message": "composition ID missing"})
    project_root = _resolve_delivery_path(scene_dir, framework.get("project_root"))
    if project_root is None or not project_root.is_dir():
        errors.append({"code": "CODE_VIDEO_PROJECT_MISSING", "path": str(framework.get("project_root") or "project_root"), "message": "framework project missing"})
    source_id = str(manifest.get("source_id") or "")
    expected_project = (scene_dir.parent / source_id / framework_key).resolve() if source_id and framework_key else None
    if project_root is not None and expected_project is not None and project_root != expected_project:
        errors.append({
            "code": "FRAMEWORK_SHARED_PROJECT_REQUIRED",
            "path": "artifact-manifest.json.framework.project_root",
            "message": f"all {source_id} {framework_key} scenes must share {expected_project}",
        })
    log_fields = (("check_log", "CODE_VIDEO_CHECK_LOG_MISSING"), ("render_log", "CODE_VIDEO_RENDER_LOG_MISSING")) if framework_key == "hyperframes" else (("package_manifest", "CODE_VIDEO_PACKAGE_MISSING"), ("render_log", "CODE_VIDEO_RENDER_LOG_MISSING"))
    for field, code in log_fields:
        _delivery_file_error(scene_dir, framework, field=field, code=code, errors=errors)
    source_files = framework.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        errors.append({"code": "CODE_VIDEO_SOURCE_MISSING", "path": "artifact-manifest.json.framework.source_files", "message": "native scene source missing"})
    else:
        for index, value in enumerate(source_files):
            path = _resolve_delivery_path(scene_dir, value)
            if path is None or not path.is_file():
                errors.append({"code": "CODE_VIDEO_SOURCE_MISSING", "path": f"framework.source_files[{index}]", "message": "source file missing"})
    for sibling_manifest in scene_dir.parent.glob("*/artifact-manifest.json"):
        if sibling_manifest == scene_dir / "artifact-manifest.json":
            continue
        try:
            sibling = read_json(sibling_manifest)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        sibling_framework = sibling.get("framework") or {}
        if sibling.get("source_id") != source_id or _tool_key(sibling_framework.get("tool")) != framework_key:
            continue
        sibling_root = _resolve_delivery_path(sibling_manifest.parent, sibling_framework.get("project_root"))
        if sibling_root is not None and expected_project is not None and sibling_root != expected_project:
            errors.append({
                "code": "FRAMEWORK_DUPLICATE_PROJECT",
                "path": str(sibling_manifest),
                "message": f"another scene from this source uses a separate {framework_key} project",
            })

    if framework_key == "hyperframes":
        marker_name = str(framework.get("project_marker") or "hyperframes.json")
        marker = _resolve_delivery_path(scene_dir, marker_name)
        if marker is None and project_root is not None:
            marker = project_root / Path(marker_name).name
        if marker is None or not marker.is_file():
            errors.append({"code": "HYPERFRAMES_PROJECT_MARKER_MISSING", "path": "artifact-manifest.json.framework.project_marker", "message": f"{marker_name} project marker missing"})
        _validate_hyperframes_delivery_receipts(scene_dir, framework, project_root, errors)
    else:
        studio_manifest = _resolve_delivery_path(scene_dir, framework.get("studio_timeline"))
        if project_root is not None and project_root.is_dir() and studio_manifest is not None:
            guard = Path(__file__).resolve().parents[2] / "studio_timeline_guard.py"
            completed = subprocess.run(
                [sys.executable, str(guard), "--project", str(project_root), "--manifest", str(studio_manifest)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                detail = " ".join((completed.stderr or completed.stdout).split())
                errors.append({"code": "REMOTION_STUDIO_NOT_EDITABLE", "path": str(studio_manifest), "message": detail})
        else:
            errors.append({"code": "REMOTION_STUDIO_MANIFEST_MISSING", "path": "artifact-manifest.json.framework.studio_timeline", "message": "Studio timeline manifest missing"})

    motion_manifest_path = _resolve_delivery_path(scene_dir, framework.get("motion_manifest"))
    if motion_manifest_path is None or not motion_manifest_path.is_file():
        errors.append({"code": "MOTION_MANIFEST_MISSING", "path": "artifact-manifest.json.framework.motion_manifest", "message": "code-video delivery needs validated motion manifest"})
    else:
        try:
            motion_payload = read_json(motion_manifest_path)
            motion_errors = validate_motion_manifest(motion_payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            motion_errors = [str(exc)]
        for message in motion_errors:
            errors.append({"code": "MOTION_MANIFEST_INVALID", "path": str(motion_manifest_path), "message": message})

    comparison = manifest.get("comparison")
    if not isinstance(comparison, dict) or comparison.get("status") != "pass":
        errors.append({"code": "RENDER_COMPARISON_MISSING", "path": "artifact-manifest.json.comparison", "message": "rendered-frame comparison must pass"})
        return
    qa_path = _resolve_delivery_path(scene_dir, comparison.get("qa_path"))
    if qa_path is None or not qa_path.is_file():
        errors.append({"code": "RENDER_COMPARISON_QA_MISSING", "path": "artifact-manifest.json.comparison.qa_path", "message": "comparison QA file missing"})
        return
    try:
        qa = read_json(qa_path)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append({"code": "RENDER_COMPARISON_QA_INVALID", "path": str(qa_path), "message": "comparison QA unreadable"})
        return
    if qa.get("status") != "pass" or not render or qa.get("output_sha256") != render.get("sha256"):
        errors.append({"code": "RENDER_COMPARISON_QA_INVALID", "path": str(qa_path), "message": "comparison QA must bind current render hash"})
    checkpoints = qa.get("checkpoints")
    required_progress = {0.0, 0.25, 0.5, 0.75, 1.0}
    actual_progress = {
        round(float(row.get("progress")), 2)
        for row in (checkpoints or [])
        if isinstance(row, dict) and isinstance(row.get("progress"), (int, float))
    }
    if not isinstance(checkpoints, list) or not required_progress.issubset(actual_progress):
        errors.append({"code": "RENDER_CHECKPOINTS_INCOMPLETE", "path": str(qa_path), "message": "extract and review 0/25/50/75/100% render frames"})
        checkpoints = checkpoints if isinstance(checkpoints, list) else []
    required_gates = {"composition", "asset_fidelity", "identity", "typography", "motion_topology", "scene_content", "artifacts", "final_state"}
    for index, row in enumerate(checkpoints):
        if not isinstance(row, dict):
            continue
        output_frame = _delivery_file_error(scene_dir, row, field="output_frame_path", code="RENDER_CHECKPOINT_FRAME_MISSING", errors=errors)
        reference = _delivery_file_error(scene_dir, row, field="reference_path", code="RENDER_CHECKPOINT_REFERENCE_MISSING", errors=errors)
        if output_frame is not None and row.get("output_frame_sha256") != sha256_file(output_frame):
            errors.append({"code": "RENDER_CHECKPOINT_HASH_MISMATCH", "path": f"{qa_path}.checkpoints[{index}]", "message": "output frame hash mismatch"})
        if reference is not None and row.get("reference_sha256") != sha256_file(reference):
            errors.append({"code": "RENDER_CHECKPOINT_HASH_MISMATCH", "path": f"{qa_path}.checkpoints[{index}]", "message": "reference hash mismatch"})
        gates = row.get("gates") or {}
        if row.get("result") != "pass" or not row.get("reviewer") or row.get("differences") not in ([], None):
            errors.append({"code": "RENDER_CHECKPOINT_REVIEW_INVALID", "path": f"{qa_path}.checkpoints[{index}]", "message": "checkpoint must be reviewed, pass, and list no unresolved differences"})
        if any(gates.get(gate) != "pass" for gate in required_gates):
            errors.append({"code": "RENDER_CHECKPOINT_GATES_FAILED", "path": f"{qa_path}.checkpoints[{index}]", "message": "all visual fidelity gates must pass"})


def validate_scene_delivery(scene_dir: Path, catalog_path: Path) -> dict[str, Any]:
    """Validate durable Recreate deliverables before an external-provider approval gate."""
    scene_dir = scene_dir.resolve()
    catalog_path = catalog_path.resolve()
    errors: list[dict[str, str]] = []
    manifest_path = scene_dir / "artifact-manifest.json"
    if not manifest_path.is_file():
        return _result(
            "scene-delivery",
            [{"code": "SCENE_MANIFEST_MISSING", "path": str(manifest_path), "message": "artifact manifest missing"}],
        )
    try:
        manifest = read_json(manifest_path)
        catalog = read_json(catalog_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _result(
            "scene-delivery",
            [{"code": "SCENE_DELIVERY_JSON_INVALID", "path": str(manifest_path), "message": str(exc)}],
        )

    if manifest.get("schema_version") != 3:
        errors.append({"code": "SCENE_MANIFEST_SCHEMA", "path": "artifact-manifest.json.schema_version", "message": "schema_version must be 3"})
    scene_id = manifest.get("scene_id")
    if not scene_id or scene_dir.name != scene_id:
        errors.append({"code": "SCENE_ID_MISMATCH", "path": "artifact-manifest.json.scene_id", "message": "manifest scene ID must match directory"})
    scene = _find_catalog_scene(catalog, str(scene_id))
    if scene is None:
        errors.append({"code": "CATALOG_SCENE_MISSING", "path": str(catalog_path), "message": f"scene not found: {scene_id}"})
        return _result("scene-delivery", errors)

    route = next(
        (item for item in catalog.get("production_routes", []) if item.get("route_id") == scene.get("production_route_id")),
        None,
    )
    if route is None:
        errors.append({"code": "CATALOG_ROUTE_MISSING", "path": "scene.production_route_id", "message": "scene route missing"})
        return _result("scene-delivery", errors)
    _validate_recreate_preflight(scene_dir, catalog_path, scene, route, errors)

    _validate_delivery_reference_pack(manifest, catalog, scene, scene_dir, errors)

    workflow_assets = {
        asset.get("asset_id"): asset
        for asset in catalog.get("workflow_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
    code_video = route.get("tool_kind") == "code_video"
    required_field = "required_asset_ids" if code_video else "required_pre_provider_asset_ids"
    required_ids = scene.get(required_field)
    if not isinstance(required_ids, list) or not required_ids:
        errors.append({"code": "REQUIRED_ASSET_CONTRACT_MISSING" if code_video else "PRE_PROVIDER_CONTRACT_MISSING", "path": f"scene.{required_field}", "message": "catalog must declare route-required assets"})
        required_ids = []
    manifest_required = manifest.get(required_field)
    if not isinstance(manifest_required, list) or set(manifest_required) != set(required_ids):
        errors.append({"code": "REQUIRED_ASSET_CONTRACT_MISMATCH" if code_video else "PRE_PROVIDER_CONTRACT_MISMATCH", "path": f"artifact-manifest.json.{required_field}", "message": "manifest must copy catalog required asset IDs exactly"})

    generated = {
        asset.get("asset_id"): asset
        for asset in manifest.get("generated_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
    reused = {
        asset.get("asset_id"): asset
        for asset in manifest.get("input_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
    for asset_id in required_ids:
        contract = workflow_assets.get(asset_id)
        if contract is None:
            errors.append({"code": "REQUIRED_ASSET_UNKNOWN", "path": str(asset_id), "message": "required asset absent from workflow_assets"})
            continue
        action = contract.get("production_action")
        if action in {"imagegen_reconstruct", "imagegen_generate"}:
            record = generated.get(asset_id)
            if record is None:
                errors.append({"code": "GENERATED_ASSET_MISSING", "path": str(asset_id), "message": "required ImageGen asset not generated"})
                continue
            output = _delivery_file_error(scene_dir, record, field="path", code="GENERATED_ASSET_FILE", errors=errors)
            if record.get("status") != "approved":
                errors.append({"code": "GENERATED_ASSET_NOT_APPROVED", "path": str(asset_id), "message": "required asset QA status must be approved"})
            generation = record.get("generation", {})
            if _tool_key(generation.get("provider")) not in {"imagegen", "builtinimagegen"} or _tool_key(generation.get("model")) != "imagegen2":
                errors.append({"code": "IMAGEGEN2_REQUIRED", "path": str(asset_id), "message": "required raster must use built-in ImageGen2"})
            for field, code in (
                ("prompt_path", "GENERATION_PROMPT_MISSING"),
                ("receipt_path", "GENERATION_RECEIPT_MISSING"),
                ("qa_path", "GENERATION_QA_MISSING"),
            ):
                _delivery_file_error(scene_dir, generation, field=field, code=code, errors=errors)
            receipt_path = _resolve_delivery_path(scene_dir, generation.get("receipt_path"))
            if receipt_path and receipt_path.is_file():
                try:
                    receipt = read_json(receipt_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    receipt = {}
                if (
                    _tool_key(receipt.get("provider")) not in {"imagegen", "builtinimagegen"}
                    or _tool_key(receipt.get("model")) != "imagegen2"
                    or not receipt.get("tool_call_id")
                    or not receipt.get("prompt_sha256")
                    or not receipt.get("reference_sha256s")
                ):
                    errors.append({"code": "IMAGEGEN2_RECEIPT_INVALID", "path": str(receipt_path), "message": "receipt lacks ImageGen2 provenance"})
            qa_path = _resolve_delivery_path(scene_dir, generation.get("qa_path"))
            if qa_path and qa_path.is_file():
                try:
                    qa = read_json(qa_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    qa = {}
                if qa.get("status") != "pass" or (output and qa.get("output_sha256") != sha256_file(output)):
                    errors.append({"code": "GENERATION_QA_INVALID", "path": str(qa_path), "message": "asset comparison QA must pass and bind output hash"})
        elif action == "reuse_source":
            record = reused.get(asset_id)
            if record is None:
                errors.append({"code": "REUSED_ASSET_MISSING", "path": str(asset_id), "message": "required source input not published"})
            else:
                _delivery_file_error(scene_dir, record, field="path", code="REUSED_ASSET_FILE", errors=errors)

    if code_video:
        _validate_code_video_delivery(manifest, route, scene_dir, errors)
        if manifest.get("status") not in {"complete", "approved"}:
            errors.append({"code": "CODE_VIDEO_STATUS_INVALID", "path": "artifact-manifest.json.status", "message": "code-video Recreate must finish native render and comparison"})
        return _result("scene-delivery", errors)

    references = manifest.get("references", [])
    prompt_ref = next(
        (item for item in references if isinstance(item, dict) and item.get("role") == "source_prompt_approved_roi"),
        None,
    )
    prompts = manifest.get("prompts", [])
    video_prompt = next(
        (item for item in prompts if isinstance(item, dict) and item.get("role") == "recovered_source_video_prompt"),
        None,
    )
    prompt_ref_path = None
    if prompt_ref is None:
        errors.append({"code": "PROMPT_ROI_MISSING", "path": "artifact-manifest.json.references", "message": "approved source prompt ROI missing"})
    else:
        prompt_ref_path = _delivery_file_error(scene_dir, prompt_ref, field="path", code="PROMPT_ROI_FILE", errors=errors)
        expected_prompt_evidence = {
            str(value).replace("\\", "/") for value in scene.get("prompt_evidence", []) if isinstance(value, str)
        }
        cache_origin = str(prompt_ref.get("cache_origin") or "").replace("\\", "/")
        if expected_prompt_evidence and not any(cache_origin.endswith(value) for value in expected_prompt_evidence):
            errors.append({"code": "PROMPT_ROI_CATALOG_MISMATCH", "path": str(prompt_ref.get("path") or ""), "message": "prompt ROI cache origin differs from catalog prompt evidence"})
    if video_prompt is None:
        errors.append({"code": "SOURCE_VIDEO_PROMPT_MISSING", "path": "artifact-manifest.json.prompts", "message": "recovered source video prompt missing"})
    else:
        prompt_path = _delivery_file_error(scene_dir, video_prompt, field="path", code="SOURCE_VIDEO_PROMPT_FILE", errors=errors)
        if prompt_path:
            text = prompt_path.read_text(encoding="utf-8-sig")
            match = re.search(r"^SOURCE PROMPT CROP:\s*(.+?)\s*$", text, re.MULTILINE)
            if not match:
                errors.append({"code": "SOURCE_PROMPT_CROP_HEADER_MISSING", "path": str(prompt_path), "message": "SOURCE PROMPT CROP header missing"})
            else:
                cited = (prompt_path.parent / match.group(1).strip()).resolve()
                if prompt_ref_path is None or cited != prompt_ref_path:
                    errors.append({"code": "SOURCE_PROMPT_CROP_IDENTITY_MISMATCH", "path": str(prompt_path), "message": "prompt header must cite the manifest prompt ROI exactly"})

    if manifest.get("status") == "awaiting_user_approval":
        external = manifest.get("external_stage", {})
        if not external.get("provider") or not external.get("model") or external.get("submission") != "not_submitted":
            errors.append({"code": "EXTERNAL_GATE_INVALID", "path": "artifact-manifest.json.external_stage", "message": "approval gate must name provider/model and remain not_submitted"})
    elif manifest.get("status") not in {"complete", "approved"}:
        errors.append({"code": "SCENE_DELIVERY_STATUS_INVALID", "path": "artifact-manifest.json.status", "message": "status must be awaiting_user_approval, approved, or complete"})
    return _result("scene-delivery", errors)


def _result(stage: str, errors: list[dict[str, str]], *, derived_status: str | None = None) -> dict[str, Any]:
    return {
        "stage": stage,
        "valid": not errors,
        "derived_status": derived_status or ("valid" if not errors else "invalid"),
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate tutorial reconstruction run")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = validate_stage(args.run, args.stage)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
