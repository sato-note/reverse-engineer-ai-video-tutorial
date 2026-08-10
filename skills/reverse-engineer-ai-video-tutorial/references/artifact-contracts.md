# Artifact contracts

## Layout

```text
cache/<source_id>/
  source/source.json
  source/metadata.json
  source/transcript.json
  source/transcript.vtt
  source/source.mp4
  runs/<run_id>/
    run.json
    target.json
    candidate_spans.json
    section_map.json
    evidence_manifest.json
    detail_discovery.json
    scene_catalog.json
    workflow.md
    guide.md
    guide_review.json
    frames/
    crops/
      <name>.<ext>.crop.json
      <name>.<ext>.crop-qa.json
    contact_sheet.jpg
    scene_plan/asset_ledger.json
    scene_plan/reconstruction_spec.json
    scene_plan/reference_manifest.json
    scene_plan/pipeline_contract.json
    scene_plan/motion_manifest.json
    scene_plan/<framework-project>/studio-timeline.json
    scene_plan/asset_qa.json
    scene_plan/handoff.md
    scene_plan/assets/
    scene_plan/prompts/
    proof/input_ledger.json
    proof/prompt.txt
    proof/provider.json
    proof/output.mp4
    proof/qa.json
    production/master.mp4
    production/provider.json
    production/qa.json
```

## Run

Require schema/run/source IDs, parent ID, timestamps, target, requested action, current stage, config, artifacts, warnings, errors. Artifact record requires role, relative path, SHA-256, size, media type.

Never mutate sealed run. Create child run for correction, scene-plan revision, proof rerun.

## Evidence row

Require stable item, timestamp/range, evidence paths, required flag, visual/text state, extraction level, label, confidence, claim, unresolved question, reviewer status.

Required missed/pending/unresolved row blocks analysis completion.

Every cited crop requires registered crop, receipt, schema-v3 QA sidecar. Receipt binds full source frame/hash, source/output dimensions, pixel/normalized ROI, transform, crop hash. QA binds crop/receipt paths, purpose, crop-first blind observation, later source-context observation, semantic target ID, reviewer/time, six semantic checks, verdict rationale, and status. `evidence-complete` requires `status=pass`, no unrelated visible content, and every check `pass`. Failed candidate stays `reject`; remove it from claims, never from immutable evidence history.

## Guide review

Require run ID, guide SHA-256, approve/reject, reviewer, time, corrections. Edited guide invalidates review.

## Section map

Pass 1 writes schema-v4 `section_map.json` from full transcript/VTT. Record tutorial summary, showcased output, all sections, semantic roles, transcript evidence, count claims, autonomous pass-2 selections, and semantic `tail_coverage` through source duration. Tail coverage cites closing transcript evidence or a reviewed reason for trailing music/silence; timestamp extension alone is invalid.

## Detail discovery

Multi-scene pass-2 sections require schema-v1 `detail_discovery.json`. Runtime analyzes full selected range with adaptive scene-change detection and extracts before/after candidates. Agent resolves every candidate to source unit plus scene/same-scene/non-scene observation. Missing range, candidate, resolution, or completion status blocks guide publication.

## Scene catalog

Every guide requires schema-v13 `scene_catalog.json` plus matching stable IDs in `guide.md`. Catalog every high-level section through source duration. Non-selected, non-showcase sections stay overview-only. Every finished-output showcase is a pass-2 target inventory, even when implementation is explained later. Showcase units may map to scene IDs defined in later workflow sections so one logical scene is not duplicated. When source states a scene count, finished sequence must map that many logical scenes. Multi-scene pass-2 sections require full-range adaptive candidate resolution. Prompt carousels require prompt groups: stable group ID, approved prompt crop, exact/detailed prompt text, mapped scene IDs. Every carousel scene maps exactly one group and its prompt-evidence set equals the group's evidence set; prompt crop QA must name every scene whose row/card is visibly supported.

`production_routes` is the source-exact route registry. Each route names the demonstrated framework or provider, tool kind, evidence, and required capabilities. Generic labels such as `code_native`, `Studio`, or `hosted model` cannot replace Remotion, Gemini, or another named source tool. Every addressable scene binds one route ID and repeats its exact route label.

Keep tutorial workflow steps separate from addressable output scenes. Setup, prompt entry, editor/Studio operation, debugging, and export configuration remain guide steps/non-scenes. One logical output scene may have discontiguous `source_occurrences` for prompt, construction, preview, and final result. Only `scene_kind=output_scene` plus `recreate_addressable=true` belongs in a section's `scenes` array.

Catalog every workflow asset with role, pipeline role, visibility, reconstruction policy, `production_action`, source kind, deliverable kind, text-bearing state, consumers, and typed `evidence_bindings`. Production inputs use `input`/`shared_input` and cite `production_use_evidence` bound as shown input, target component, or construction spec; workflow explanation/route evidence cannot prove an input. A visible input/component uses `imagegen_reconstruct`, never `imagegen_generate`. `reuse_source` production input requires a registered isolated file path/hash; frames/crops cannot satisfy it. `code_native` also requires `code_native_kind=chart|counter|arrow|simple_geometry|layout|data_visualization`; semantic maps/portraits/objects require ImageGen reconstruction unless tutorial shows their source code. Every target reference must be visibly shown, source-exact, have unique target-output crop, and declare `target_state=representative_result|final_result`; scene-start/partial states remain input evidence. Every output scene declares nonempty `input_asset_ids`, `required_asset_ids`, and `target_reference_asset_ids`. Reference-video scenes additionally require `required_pre_provider_asset_ids`; image-to-video requires a `scene_start_image`.

Every source unit owns one same-ID `demonstrated_unit` evidence row; a shared evidence row does not prove unit-level coverage. Discovery disposition must match unit disposition; repeated candidates for one identity use `same_scene`, not repeated `scene`. Every cataloged/merged unit overlaps a typed source occurrence. Each occurrence reviews every cited image and binds visible fact candidates to `fact_claims` by subject/value/evidence. Text-bearing workflow assets require exact or detailed text extraction. Visible output-count language such as “ten separate scenes” becomes a `visual_count_claim`, links back through asset `count_claim_ids`, and receives one explicit `count_reconciliation` row beside transcript claims. Every target crop records visible fact candidates; conflicting values use `fact_claims` plus `fact_reconciliation`. Duration never defines boundary, but section map must cover full source duration.

All JSON uses runtime canonical writer: UTF-8 without BOM, two-space indent, final newline. Run `normalize-json` after agent edits; validator rejects BOM, mojibake, invalid UTF-8, parse errors, and noncanonical formatting.

## Scene preparation contracts

Require schema-v1 `recreate-preflight.json` from runtime `start-recreate`: canonical scene, publishing hashes, exact route, asset/prompt inventory, source-exact policy, terminal delivery type, still-is-intermediate lock. Require fidelity mode, immutable target lock, scene-bound start/mid/final roles, motion-reference status, typography refs, scene-specific motion, framework policy/decision, asset routes, exact prompts, provider intent. Start must be available for reference-image-to-video. Mid/final and motion may be explicitly unavailable with reasons; they must never be populated from adjacent prompt groups. Every available reference binds catalog source evidence, target prompt group, durable path/hash, reviewer, and `target_match: pass`. Semantic asset needs image generation/source transform. Typography needs bundled licensed font. Generated output needs path/hash/status and reference-backed QA. Remotion needs element-to-Sequence coverage, live prop controls, verified Studio timeline screenshot, native project/source/package/render log, composition ID, and MP4 terminal render.

## Proof

Require input ledger, exact prompt, provider/model/settings record, output, source refs, normalized comparison checkpoints, fidelity gates. No provider output may become source evidence.

## Validation

```text
python scripts/run.py validate --run <run-dir> --stage scaffold
python scripts/run.py validate --run <run-dir> --stage evidence-complete
python scripts/run.py publish-guide --run <run-dir> --workspace-root <repo-root>
python scripts/run.py validate --run <run-dir> --stage guide-complete
python scripts/run.py validate --run <run-dir> --stage scene-ready
python scripts/run.py validate --run <run-dir> --stage assets-approved
python scripts/run.py validate --run <run-dir> --stage comparison-complete
python scripts/run.py validate --run <run-dir> --stage delivery-complete
```

Validator returns named stage, validity, derived status, coded errors.

Durable scene delivery uses schema-v3 `artifact-manifest.json`. It binds current Recreate preflight and catalog-required assets to actual files and includes `reference_pack`: target prompt group; start/mid/final entries marked `available` or `unavailable`; motion-reference status/reason/samples. Available references must belong to catalog scene and pass identity review. Every ImageGen-required record needs approved output, prompt, ImageGen2 receipt, comparison QA, and hashes. Prompt transcript header must cite manifest approved prompt ROI exactly. Code-video delivery additionally declares `delivery_kind=video`, native `render`, shared `framework.project_root=videos/<source-id>/<framework>`, `studio_timeline`, `motion_manifest`, and `comparison.qa_path`. QA stores real 0/25/50/75/100% output frames, source refs, hashes, reviewer, differences, and gates. Still-only or self-asserted MP4 comparison fails.
