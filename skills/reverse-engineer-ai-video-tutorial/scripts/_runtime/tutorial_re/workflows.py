from __future__ import annotations

import shutil
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import FIDELITY_POLICIES, fidelity_for_target_choice
from .manifest import read_json, write_json
from .run_store import register_artifact, sha256_file, update_run


FIDELITY_MODES = FIDELITY_POLICIES


def _target_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def resolve_recreate_scene(catalog: dict[str, Any], target: str) -> tuple[dict[str, Any], str]:
    """Resolve exact scene ID/title or a human folder alias without guessing across scenes."""
    scenes = [
        scene
        for section in catalog.get("sections", [])
        for scene in (section.get("scenes") or [])
        if isinstance(scene, dict)
    ]
    target_key = _target_key(target)
    exact = [
        scene for scene in scenes
        if target == scene.get("scene_id") or target_key == _target_key(scene.get("title"))
    ]
    if len(exact) == 1:
        return exact[0], "scene_id" if target == exact[0].get("scene_id") else "title"
    if len(exact) > 1:
        raise ValueError(f"ambiguous Recreate target: {target}")

    alias = re.fullmatch(r"scene-(\d{1,2})(?:-(.+))?", target_key)
    if alias:
        ordinal = int(alias.group(1))
        suffix = alias.group(2) or ""
        if 1 <= ordinal <= len(scenes):
            scene = scenes[ordinal - 1]
            title_key = _target_key(scene.get("title"))
            if not suffix or title_key.startswith(suffix):
                return scene, "ordered_folder_alias"
            raise ValueError(
                f"Recreate alias conflicts with scene {ordinal:02}: "
                f"{scene.get('scene_id')} / {scene.get('title')}"
            )
    raise ValueError(f"Recreate target not found: {target}")


def _find_publishing_run(workspace_root: Path, source_id: str, guide_hash: str, catalog_hash: str) -> Path:
    runs_root = workspace_root / "cache" / source_id / "runs"
    if not runs_root.is_dir():
        raise FileNotFoundError(f"run history missing: {runs_root}")
    for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), reverse=True):
        publication_path = run_dir / "guide_publication.json"
        if not publication_path.is_file():
            continue
        publication = read_json(publication_path)
        if (
            publication.get("guide_sha256") == guide_hash
            and publication.get("scene_catalog_sha256") == catalog_hash
        ):
            return run_dir
    raise ValueError("published guide/catalog do not match any publishing run")


def start_recreate(
    workspace_root: Path,
    *,
    source_id: str,
    target: str,
) -> dict[str, Any]:
    """Create mandatory route/asset/output preflight before any Recreate generation."""
    workspace_root = workspace_root.expanduser().resolve()
    if Path(source_id).name != source_id:
        raise ValueError("invalid source_id")
    public_dir = workspace_root / "docs" / "reconstructions" / source_id
    guide_path = public_dir / "workflow.md"
    catalog_path = public_dir / "scene-catalog.json"
    if not guide_path.is_file() or not catalog_path.is_file():
        raise FileNotFoundError("published workflow and scene catalog required")
    guide_hash = sha256_file(guide_path)
    catalog_hash = sha256_file(catalog_path)
    publishing_run = _find_publishing_run(workspace_root, source_id, guide_hash, catalog_hash)
    from .validate import validate_stage
    from .framework_adapters import build_adapter_plan

    validation = validate_stage(publishing_run, "guide-complete")
    if not validation["valid"]:
        codes = sorted({row["code"] for row in validation["errors"]})
        raise ValueError(f"publishing run guide-complete failed: {', '.join(codes)}")

    catalog = read_json(catalog_path)
    scene, resolved_by = resolve_recreate_scene(catalog, target)
    if scene.get("scene_kind") != "output_scene" or scene.get("recreate_addressable") is not True:
        raise ValueError("target is not a Recreate-addressable output scene")
    routes = {
        route.get("route_id"): route
        for route in catalog.get("production_routes", [])
        if isinstance(route, dict)
    }
    route = routes.get(scene.get("production_route_id"))
    if route is None:
        raise ValueError("scene production route missing")
    assets = {
        asset.get("asset_id"): asset
        for asset in catalog.get("workflow_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
    required_ids = list(scene.get("required_asset_ids") or [])
    missing_assets = [asset_id for asset_id in required_ids if asset_id not in assets]
    if missing_assets:
        raise ValueError(f"required assets absent from catalog: {missing_assets}")
    consumed_inputs = {
        asset_id
        for asset_id, asset in assets.items()
        if asset.get("pipeline_role") in {"input", "shared_input"}
        and scene.get("scene_id") in (asset.get("consumed_by_scene_ids") or [])
    }
    missing_required = sorted(consumed_inputs - set(required_ids))
    if missing_required:
        raise ValueError(f"scene omits consumed production assets: {missing_required}")
    prompt_reference_ids = sorted(
        asset_id
        for asset_id, asset in assets.items()
        if asset.get("pipeline_role") == "prompt_reference"
        and scene.get("scene_id") in (asset.get("consumed_by_scene_ids") or [])
    )
    tool_kind = route.get("tool_kind")
    adapter_plan = build_adapter_plan(source_id, route) if tool_kind == "code_video" else None
    if adapter_plan and adapter_plan["state"] == "adapter_unavailable":
        raise ValueError(adapter_plan["next_action"])
    expected_delivery = {
        "kind": "video" if tool_kind == "code_video" else "external_video_handoff",
        "terminal_extension": ".mp4" if tool_kind == "code_video" else None,
        "still_role": "intermediate_only",
        "standalone_still_satisfies_recreate": False,
    }
    if adapter_plan:
        expected_delivery.update({
            "framework_adapter": adapter_plan["adapter"],
            "framework_readiness": adapter_plan["state"],
            "framework_setup": adapter_plan,
            **adapter_plan.get("delivery_fields", {}),
        })
    scene_dir = workspace_root / "videos" / str(scene["scene_id"])
    scene_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "status": "ready",
        "source_id": source_id,
        "requested_target": target,
        "resolved_by": resolved_by,
        "publishing_run_id": publishing_run.name,
        "guide_path": str(guide_path),
        "guide_sha256": guide_hash,
        "catalog_path": str(catalog_path),
        "catalog_sha256": catalog_hash,
        "scene": {
            "scene_id": scene.get("scene_id"),
            "title": scene.get("title"),
            "description": scene.get("description"),
            "composition": scene.get("composition"),
            "motion_order": scene.get("motion_order"),
            "prompt_evidence": scene.get("prompt_evidence"),
        },
        "production_route": route,
        "framework_adapter": adapter_plan,
        "framework_policy": "source_exact",
        "required_asset_ids": required_ids,
        "required_assets": [assets[asset_id] for asset_id in required_ids],
        "prompt_reference_asset_ids": prompt_reference_ids,
        "prompt_reference_assets": [assets[asset_id] for asset_id in prompt_reference_ids],
        "target_reference_asset_ids": list(scene.get("target_reference_asset_ids") or []),
        "expected_delivery": expected_delivery,
        "next_gate": "prepare exact source route; no generation may be terminal before route delivery",
    }
    path = write_json(scene_dir / "recreate-preflight.json", record)
    return {**record, "preflight_path": str(path), "publishing_run": str(publishing_run)}


GUIDE_TEMPLATE = """# Recreation guide

## Scope and source

## High-level tutorial map

## Workflow-bearing sections selected for detail pass

## Tools, models, surfaces, settings

## Source and reference hierarchy

## Source-exact production routes

List each demonstrated framework/provider stage. Name exact tool and tool kind. `code_native` is an asset technique, never a substitute for Remotion or another observed runtime.

| Route ID | Exact tool/provider | Tool kind | Evidence | Required capabilities |
|---|---|---|---|---|

## Workflow input and target-reference inventory

Inventory every shown style sheet, reference image, generated still, diagram, or other image later consumed by tutorial pipeline. Link exact full-frame/crop evidence. Mark shown images `exact_source`; mark prompt-only/unshown images `prompt_derived`.

| Asset ID | Pipeline role | Asset role | Source kind | Deliverable kind | Shown? | Exact crop/file | Production action | Consumed by output scene(s) |
|---|---|---|---|---|---|---|---|---|

## Source section map and scene catalog

Describe workflow/setup steps here. Do not assign Recreate scene IDs to connector setup, folder navigation, Studio debugging, prompt cards, or other production-process screens.

## Addressable scene inventory

Only demonstrated output-video scenes belong here. One logical output scene may cite discontiguous prompt, build, Studio, and final-preview occurrences.

| Scene ID | Title | Exact route | Source occurrences | Required inputs | Target reference |
|---|---|---|---|---|---|

## Prompt group inventory

For every prompt carousel, group scenes that share one stable visible prompt card. Include the cropped prompt evidence and recovered prompt text; do not substitute an output description.

| Prompt group ID | Scene ID(s) | Source interval | Extraction | Prompt crop | Recovered prompt |
|---|---|---|---|---|---|

## Source fact conflicts

Preserve differing numbers, names, settings, or labels. Reconcile scope; never silently choose one value.

## Fixed system or style block

## Variable shot and action blocks

## Camera, motion, audio, negatives

## Edit strategy

## Evidence citations and labels

## Human and agent ownership

## Limits, unresolved gaps, recreation checklist
"""


def create_guide_scaffold(run_dir: Path) -> Path:
    guide = run_dir / "guide.md"
    if not guide.exists():
        guide.write_text(GUIDE_TEMPLATE, encoding="utf-8")
        register_artifact(run_dir, guide, role="guide")
    scene_catalog = run_dir / "scene_catalog.json"
    if not scene_catalog.exists():
        manifest = read_json(run_dir / "run.json")
        write_json(scene_catalog, {
            "schema_version": 13,
            "source_id": manifest["source_id"],
            "status": "pending",
            "catalog_scope": "",
            "segmentation_policy": "semantic-boundary",
            "analysis_passes": {"high_level": "pending", "detail": "pending"},
            "production_routes": [],
            "visual_count_claims": [],
            "count_reconciliation": [],
            "fact_claims": [],
            "fact_reconciliation": [],
            "workflow_assets": [],
            "sections": [],
        })
        register_artifact(run_dir, scene_catalog, role="scene_catalog")
    update_run(run_dir, {"current_stage": "guide-draft"})
    return guide


def publish_guide(run_dir: Path, workspace_root: Path) -> dict[str, Any]:
    """Publish durable guide/catalog while retaining frozen run snapshots."""
    resolved_run = run_dir.resolve()
    resolved_workspace = workspace_root.resolve()
    try:
        resolved_run.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError("run must be inside workspace") from exc

    guide = resolved_run / "guide.md"
    catalog = resolved_run / "scene_catalog.json"
    if not guide.is_file() or not catalog.is_file():
        raise FileNotFoundError("guide.md and scene_catalog.json required")
    register_artifact(resolved_run, guide, role="guide")
    register_artifact(resolved_run, catalog, role="scene_catalog")
    from .validate import validate_stage

    preflight = validate_stage(resolved_run, "guide-complete", require_publication=False)
    if not preflight["valid"]:
        codes = sorted({item["code"] for item in preflight["errors"]})
        raise ValueError(f"guide preflight failed: {', '.join(codes)}")
    manifest = read_json(resolved_run / "run.json")
    source_id = str(manifest.get("source_id", ""))
    if not source_id or Path(source_id).name != source_id:
        raise ValueError("invalid source_id")

    public_dir = resolved_workspace / "docs" / "reconstructions" / source_id
    public_dir.mkdir(parents=True, exist_ok=True)
    public_guide = public_dir / "workflow.md"
    public_catalog = public_dir / "scene-catalog.json"
    shutil.copy2(guide, public_guide)
    shutil.copy2(catalog, public_catalog)

    record = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "source_id": source_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(resolved_workspace),
        "guide_path": public_guide.relative_to(resolved_workspace).as_posix(),
        "guide_sha256": sha256_file(public_guide),
        "scene_catalog_path": public_catalog.relative_to(resolved_workspace).as_posix(),
        "scene_catalog_sha256": sha256_file(public_catalog),
    }
    record_path = write_json(resolved_run / "guide_publication.json", record)
    register_artifact(resolved_run, guide, role="guide")
    register_artifact(resolved_run, catalog, role="scene_catalog")
    register_artifact(resolved_run, record_path, role="guide_publication")
    config = dict(manifest.get("config", {}))
    config.update({
        "workspace_root": str(resolved_workspace),
        "public_guide_required": True,
    })
    update_run(resolved_run, {
        "config": config,
        "public_guide": record["guide_path"],
        "public_scene_catalog": record["scene_catalog_path"],
    })
    return record


def write_guide_review(
    run_dir: Path,
    *,
    decision: str,
    reviewer: str,
    required_corrections: list[str] | None = None,
) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ValueError(f"unsupported review decision: {decision}")
    guide = run_dir / "guide.md"
    if not guide.is_file():
        raise FileNotFoundError("guide.md missing")
    manifest = read_json(run_dir / "run.json")
    register_artifact(run_dir, guide, role="guide")
    manifest = read_json(run_dir / "run.json")
    record = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "guide_sha256": sha256_file(guide),
        "decision": decision,
        "reviewer": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "required_corrections": required_corrections or [],
    }
    path = write_json(run_dir / "guide_review.json", record)
    register_artifact(run_dir, path, role="guide_review")
    update_run(run_dir, {"current_stage": "guide-approved" if decision == "approve" else "guide-rejected"})
    return record


def create_scene_scaffold(
    run_dir: Path,
    *,
    target_choice: str = "match",
) -> dict[str, Any]:
    fidelity_mode = fidelity_for_target_choice(target_choice)
    manifest = read_json(run_dir / "run.json")
    requested_action = manifest.get("requested_action")
    if requested_action == "recreate" and target_choice != "match":
        raise ValueError("recreate action requires target-choice match; use create action for adapt/method")
    if requested_action == "create" and target_choice == "match":
        raise ValueError("create action requires target-choice adapt or method")
    guide = run_dir / "guide.md"
    review_path = run_dir / "guide_review.json"
    if not guide.is_file() or not review_path.is_file():
        raise ValueError("scene preparation requires approved guide")
    review = read_json(review_path)
    if review.get("decision") != "approve" or review.get("guide_sha256") != sha256_file(guide):
        raise ValueError("scene preparation requires approved guide with current hash")
    scene_plan_dir = run_dir / "scene_plan"
    (scene_plan_dir / "assets").mkdir(parents=True, exist_ok=True)
    (scene_plan_dir / "prompts").mkdir(parents=True, exist_ok=True)
    spec = {
        "schema_version": 2,
        "run_id": manifest["run_id"],
        "guide_sha256": review["guide_sha256"],
        "fidelity_mode": fidelity_mode,
        "lifecycle_stage": "scene-planned",
        "target_lock": {
            "content": "pending",
            "style": "pending",
            "composition": "pending",
            "typography": "pending",
            "motion": "pending",
            "immutable": True,
        },
        "approved_deviations": [],
    }
    references = {
        "schema_version": 3,
        "run_id": manifest["run_id"],
        "fidelity_mode": fidelity_mode,
        "scenes": [],
    }
    pipeline = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "guide_sha256": review["guide_sha256"],
        "requested_action": requested_action,
        "target_choice": target_choice,
        "policy": "source-faithful-pipeline",
        "framework_policy": "source_exact",
        "requested_framework": "",
        "asset_policy": {
            "raster_generator": "imagegen2",
            "code_native": ["charts", "counters", "labels", "paths", "geometry"],
            "generate_only_required": True,
        },
        "tutorial_stages": [],
        "selected_stages": [],
    }
    motion = {
        "schema_version": 2,
        "run_id": manifest["run_id"],
        "fidelity_mode": fidelity_mode,
        "scenes": [],
        "timeline_track_contract": {
            "required_fields": [
                "name", "role", "element_ids", "from", "duration_in_frames",
                "source_component", "prop_controls",
            ],
            "chart_roles": [
                "chart_container", "chart_axes", "chart_series", "chart_points", "chart_labels",
            ],
        },
    }
    ledger = {
        "schema_version": 2,
        "status": "planning",
        "lifecycle_stage": "scene-planned",
        "run_id": manifest["run_id"],
        "guide_sha256": review["guide_sha256"],
        "fidelity_mode": fidelity_mode,
        "provider_submission": "not_authorized",
        "provider_authorization": {
            "status": "not_authorized",
            "provider": "",
            "model": "",
            "cost": "",
            "inputs": [],
            "owner": "",
        },
        "assets": [],
        "prompts": [],
    }
    spec_path = write_json(scene_plan_dir / "reconstruction_spec.json", spec)
    references_path = write_json(scene_plan_dir / "reference_manifest.json", references)
    pipeline_path = write_json(scene_plan_dir / "pipeline_contract.json", pipeline)
    motion_path = write_json(scene_plan_dir / "motion_manifest.json", motion)
    ledger_path = write_json(scene_plan_dir / "asset_ledger.json", ledger)
    handoff = scene_plan_dir / "handoff.md"
    handoff.write_text(
        "# Scene preparation handoff\n\n"
        "## Creative brief or script\n\n"
        "## Master and reference specifications\n\n"
        f"Fidelity: `{fidelity_mode}`. Target lock may change only through recorded user-approved deviation.\n\n"
        "## Asset route and typography plan\n\n"
        "## Shot list and storyboard plan\n\n"
        "## Scene motion manifests\n\n"
        "## Source-faithful pipeline and framework readiness\n\n"
        "## Exact prompts and settings intent\n\n"
        "## Input dependency graph\n\n"
        "## Provider submission\n\nNot authorized. Stop for user approval.\n",
        encoding="utf-8",
    )
    for path, role in (
        (spec_path, "reconstruction_spec"),
        (references_path, "reference_manifest"),
        (pipeline_path, "pipeline_contract"),
        (motion_path, "motion_manifest"),
        (ledger_path, "scene_plan_ledger"),
        (handoff, "scene_plan_handoff"),
    ):
        register_artifact(run_dir, path, role=role)
    update_run(run_dir, {"current_stage": "scene-preparation"})
    return ledger
