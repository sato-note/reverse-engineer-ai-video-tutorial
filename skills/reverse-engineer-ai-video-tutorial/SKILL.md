---
name: reverse-engineer-ai-video-tutorial
description: Turn YouTube or local AI video tutorials into evidence-backed reusable guides, faithful scene recreations, or new work built from recovered methods. Use when Codex must recover prompts, settings, code, assets, typography, motion, tool sequences, or production logic from transcript plus visual evidence; publish a standalone guide and scene catalog; recreate a named section; create new content from a recovered workflow; or compare generated output with source references. Any request containing “recreate” plus a scene/section ID, title, or folder-like alias—including bare requests such as “scene-01, recreate this”—must trigger this skill before ImageGen or video skills. Do not use for generic summaries, transcription-only work, ordinary footage editing, style inspiration without workflow recovery, or bulk cloning.
---

# Reverse Engineer AI Video Tutorial

Treat tutorial as evidence. Keep source facts, reconstruction, and generated work distinct. Compare output with source or approved creative target—not prompt alone.

## Resolve user action

Choose from request language. Do not ask user to select mode.

- `Guide`: turn URL/local tutorial into reusable guide. Default for vague requests.
- `Recreate`: reproduce named tutorial section/scene, then compare.
- `Create from guide`: use recovered method or visual system for new brief, then compare.

Generation requires explicit `recreate` or `create` intent. Existing guide continuation must not re-ingest full tutorial.

When target is unclear, ask one plain question: “Match tutorial scene, or use its method for new content?” Keep internal fidelity policy names hidden.

## Anchor workspace

Use user workspace as output root. Resolve installed skill separately. Host chooses install root; default installer target is `~/.agents/skills/reverse-engineer-ai-video-tutorial`. Never assume `.codex`, Cursor internals, or a Windows path.

```text
<repo-root> = user workspace
<skill-root> = host-reported installed skill directory
python <skill-root>/scripts/run.py doctor --profile base --json
```

Require runtime `tutorial-re ==0.0.1`, matching skill `VERSION`. Never write into installed skill. Use
`run.py --runtime auto|managed|system`; `auto` prefers a healthy managed
receipt and otherwise admits selected-profile compatibility probes. The
managed `requirements.lock` is an exact fallback contract, not a global host
Python requirement. Doctor probes only its selected profile unless a maintainer
passes `--all-profiles`. Pass absolute workspace/cache roots. Creating a missing
`<repo-root>/cache/` is normal requested-workflow setup; reject a cache outside
the workspace. Verify returned run path begins under `<repo-root>/cache/`.

Read [workspace layout](references/workspace-layout.md) before first run in new repo.

## Guide

One user request covers internal evidence analysis plus guide publication.

```text
python <skill-root>/scripts/run.py ingest --video-url "<url>" --target "<scope>" --workspace-root <repo-root> --cache-root <repo-root>/cache --source-cache-root <user-cache-root> --download-video --extract-frames
```

Local source: use `--video-file`; add `--transcript` when needed. Use `--stop-after evidence` only for maintainer audit/debug work.

Source reuse is automatic. Resolution order: workspace `cache/<source-id>/source/` → shared `--source-cache-root/<source-id>/source/` → network. Keep `--download-video`: it means “ensure video is available”; downloader runs only when no cached video exists. Reuse cached video, transcript, and metadata for every later run from same source ID. Do not re-download or refetch unless user explicitly requests a source refresh. Cached bytes provide stable evidence; remote metadata/captions may change later.

Then run two autonomous passes. Do not ask user between passes.

1. Read [evidence coverage](references/evidence-coverage.md).
2. Pass 1 — read full VTT/transcript. Build schema-v4 `section_map.json`: tutorial purpose, showcased output, section roles, transcript evidence, workflow-bearing sections, every source scene/unit count claim. Preserve contradictory counts. Cover source from start through recorded duration; outro/conclusion remains a section even when it has no workflow detail. Complete `tail_coverage` from actual closing transcript content, or explicitly classify verified trailing music/silence. Extending the last timestamp without reviewing the tail fails.
3. Select pass-2 sections by meaning: where tutorial explains production workflow or how showcased output was made. Always select any `showcase_production` section that plays the finished output; playback is target evidence even when implementation is explained later. Validate `section-mapped`.
4. Pass 2 — inspect only selected sections in detail. For multi-scene/carousel/storyboard/finished sequence, run adaptive discovery across full section range. Inventory every visible output-scene boundary in finished playback and bind later prompt/build/Studio occurrences to those same logical IDs. Review every before/after change candidate. Use explicit timestamps only for extra evidence. Never use fixed intervals or representative samples as scene logic.
5. Resolve every adaptive candidate in `detail_discovery.json` to scene/same-scene/non-scene plus source unit and observation. Give every source unit its own same-ID `demonstrated_unit` evidence row and specific claim. One unit may receive only one `scene` resolution; later candidates for that identity use `same_scene`, or split the unit when identity changes. A `scene` resolution maps only a cataloged unit, `same_scene` only cataloged/merged, `non_scene` only non-scene. Changed prompt, result, shot goal, composition, text, or transition starts new scene. Duration alone never starts or merges scene.
6. Separate tutorial workflow steps from output scenes. Connector setup, folder architecture, prompt UI, Studio debugging, and render settings remain workflow steps/non-scenes. Only demonstrated output-video shots receive Recreate-addressable scene IDs. Bind one logical output scene across discontiguous prompt, build, preview, and final-result occurrences instead of creating process-state scene IDs.
7. Recover source-exact production routes before scene cataloging. Each route names exact demonstrated framework/provider, tool kind, evidence, and required capabilities. `code_native`, Studio, or a generic hosted model is not a production route. Remotion stays Remotion; Gemini stays named generative provider/model.
8. Inventory every workflow input, shared input, prompt reference, and target reference. Bind every asset evidence path to what it proves: shown input, target component, construction spec, prompt mention, workflow explanation, route evidence, target output, or prompt. Production inputs require separate `production_use_evidence` with a production-role binding; an explanatory tutorial card cannot become a shared input. A visibly shown isolated input or target component is source-visible and uses `imagegen_reconstruct`, never prose-only `imagegen_generate`. Give each asset pipeline role, production action, source kind, deliverable kind, consuming output scenes, text-extraction status, and count-claim links when visible text states a scene/shot count. `reuse_source` production input requires a real isolated source file registered by path/hash; a screenshot or composite crop cannot qualify. `code_native` requires `code_native_kind` and is limited to charts, counters, arrows, simple geometry/layout, or data visualization. A detailed map, portrait, object, or textured semantic component visible only inside a composite uses `imagegen_reconstruct` from that full-frame evidence unless source code for it is shown. Split combined screenshot concepts into executable component assets. Final composite/result frames are target references, not scene-start inputs. For every output scene list required production assets separately from target references.
9. For prompt carousel, group motion states by stable visible prompt card. Create one prompt group per unique card; map every scene to one group. Each mapped scene's `prompt_evidence` must equal its group's `prompt_evidence`; verify subject/action meaning, not ID sequence alone. Prompt crop QA lists only scene IDs whose prompt row/card is literally visible; one table crop cannot support unseen rows. Crop prompt region, run semantic crop QA, store exact transcription or detailed paraphrase in catalog. Never substitute output description for prompt.
10. Inspect other prompt/settings/code details at readable resolution. New visible prompt requires approved ROI crop plus exact transcription or detailed paraphrase.
11. Complete schema-v3 semantic crop QA one crop at a time. First open the saved crop alone, without using its filename or intended label as the observation, and record literal dominant content, visible text, visual anchors, unrelated content, and visible fact candidates. Then open the full frame and compare against the intended claim. A crop passes only when it fills the semantic target and contains no presenter, adjacent panel, or unrelated UI/content. Prompt QA needs literal visible text plus supported scene IDs. Target-output QA must show a complete representative/final scene state; an early animation state belongs only to a scene-start input. Bind `semantic_target_id` to the asset or prompt record. Exact text needs full coverage. Generic/batch approval fails. Crop receipt source must appear in every asset using that crop. Each target reference needs a scene-specific ROI whose receipt source is in that scene's reference frames.
12. Review every image in every typed source occurrence for visible numeric/name/setting candidates, not only approved target crops. Record the reviewed image list and candidates in the occurrence `fact_review`. Bind each candidate to an exact `fact_claim` by subject, value, and evidence. Reconcile transcript and onscreen scene/shot count claims against addressable output scenes. Differing values for one subject require explicit `fact_reconciliation`. Preserve contradictions and explain scope; never select one silently.
13. Mark detail-pass/discovery rows complete. Write guide plus schema-v13 scene catalog. Every output scene requires `scene_kind=output_scene`, exact `production_route_id`, typed source occurrences with complete fact reviews, input/required asset IDs, target-reference IDs, and prompt fields. Every target reference is visibly shown, source-exact, scene-cropped, and labeled `representative_result` or `final_result`. Every cataloged/merged source unit must overlap a matching scene occurrence. A finished showcase may map its units to logical scene IDs defined in a later workflow section; do not duplicate those scenes. Its mapped scene count must agree with a preserved source count claim when one exists. External reference-video routes additionally require pre-provider assets and a scene-start image.
14. Validate `evidence-complete`; normalize/register edited semantic JSON.
15. Run `publish-guide`; it performs the prepublication `guide-complete` gate and writes the public snapshot only after that gate passes. Then validate final published `guide-complete`.
16. Report public workflow/catalog paths plus exact routes, output scenes, workflow assets, prompt crops/groups. Stop; do not generate.

Segmentation examples:

- prompt card + bound result for one shot → one scene;
- changed prompt, result, shot goal, composition, or continuation beat → new scene;
- carousel/storyboard/multi-shot sequence → inventory every card/panel/shot;
- finished output playback → inventory every visible scene, even when production details appear later;
- zoom, crop, replay, or alternate view of same unit → same scene;
- style sheet, setup UI, or global config → non-scene unless it defines an addressable output.
- one output scene shown during prompt, Studio tuning, and final preview → one scene with multiple source occurrences;

A prompt-card change ends the current prompt-bound scene occurrence. Give each occurrence one kind (`prompt`, `build`, `preview`, `final_result`, `beat_sheet`, `motion_sample`, or `other`) plus a specific purpose. Never use one compound interval to cover prompt, debugging, and final result. Never stretch one scene interval across intervening prompt groups or fill its reference frames from nearest timestamps. If the same output reappears later, record a separate occurrence or additional evidence for that same identity only.

Do not summarize pass-2 sequence or choose representative cards. `guide-complete` requires full-range discovery, every candidate resolved, count reconciliation, unit evidence, scene IDs, and—for prompt carousels—cropped prompt groups with extracted text.

```text
python <skill-root>/scripts/run.py normalize-json --run <run-dir> --path section_map.json --role section_map
python <skill-root>/scripts/run.py validate --run <run-dir> --stage section-mapped
python <skill-root>/scripts/run.py extract-detail --run <run-dir> --section-id <section-id> --range <start:end>
python <skill-root>/scripts/run.py normalize-json --run <run-dir> --path detail_discovery.json --role detail_discovery
python <skill-root>/scripts/run.py normalize-json --run <run-dir> --path evidence_manifest.json --role evidence_manifest
python <skill-root>/scripts/run.py normalize-json --run <run-dir> --path scene_catalog.json --role scene_catalog
```

```text
python <skill-root>/scripts/run.py validate --run <run-dir> --stage evidence-complete --json
python <skill-root>/scripts/run.py publish-guide --run <run-dir> --workspace-root <repo-root> --json
python <skill-root>/scripts/run.py validate --run <run-dir> --stage guide-complete --json
```

If a registered JSON artifact was edited, repair its hash explicitly before validating:

```text
python <skill-root>/scripts/run.py normalize-json --run <run-dir> --path scene_catalog.json --role scene_catalog --json
```

Crop paths are resolved relative to the run, never the current directory. Keep source frames under `frames/` and outputs under `crops/`:

```text
python <skill-root>/scripts/run.py crop --run <run-dir> frames/<frame>.jpg crops/<crop>.jpg --purpose prompt --x <x> --y <y> --width <width> --height <height> --json
```

## Recreate

Read [scene recreation](references/scene-recreation.md), then:

1. Make `start-recreate` first task action. Do not open a target crop, call ImageGen, select framework, or create scene output before this succeeds:

```text
python <skill-root>/scripts/run.py start-recreate --workspace-root <repo-root> --source-id <source-id> --target "<user scene ID, title, or folder alias>"
```

This validates current publishing run, resolves alias to canonical scene ID, locks exact production route, inventories required/prompt assets, writes `videos/<canonical-scene-id>/recreate-preflight.json`, and declares terminal delivery type. Failure blocks generation; repair Guide first. Never hand-author or bypass preflight.
2. Lock public action: Recreate always uses `target-choice=match`. Never silently switch to `adapt`/style match. Only explicit Create-from-guide request may adapt.
3. Use only canonical scene returned by preflight. Resolve content from ID, title, occurrences, prompt evidence, target refs, required assets, composition, motion order, and exact route. Workflow-step IDs are not targets. Alias conflict blocks generation; ask user which target.
4. Follow catalog evidence into publishing run. Inspect only relevant source region.
5. Resolve every `required_asset_id`; for external reference-video routes also resolve every `required_pre_provider_asset_id`. Target-reference assets are comparison evidence, never production inputs. If tutorial shows an input, locate exact approved crop/full frame; never generate from prose alone.
6. Recover full image prompt, video prompt, ref hierarchy, and scene-bound reference pack. Verify every available start/mid/final or motion frame against the target prompt group and catalog evidence. If a role is not shown, record it as `unavailable` with a reason; missing is safer than an adjacent-scene substitute.
7. Build explicit start-state lock from shown source start/result. Keep later video-prompt actions, counters, text, and end states out of ImageGen start still unless visible at start.
8. Publish full-frame plus approved ROI evidence into scene `references/`.
9. Create scene doc and standalone source prompt files.
10. Execute each cataloged `production_action`. `imagegen_reconstruct` and `imagegen_generate` require actual built-in ImageGen2 outputs; a source crop is evidence/reference and cannot satisfy them. `reuse_source` is valid only when the guide explicitly records that source route.
11. For `imagegen_reconstruct`, use the exact shown crop/full frame as ImageGen2 edit reference and preserve visible identity/layout/content. Never redesign from guide prose. Generate prompt-derived images only for `imagegen_generate` when the tutorial does not show the target.
12. Classify each ImageGen job: source asset reconstruction, style-conditioned scene, or new asset. Never apply downstream “style only/do not copy layout” wording to source asset reconstruction.
13. Preserve exact visible brands, labels, objects, counts, and positions. Generic icons or invented substitutes fail when source shows named logos/assets.
14. Save preflight, prompts, assets, receipts, QA, framework source, manifests, and renders in canonical scene workspace.
15. Compare every generated intermediate directly with shown tutorial image—not generation prompt. Failed intermediate blocks motion; retry targeted edit or use exact crop.
16. Write canonical pipeline contract. With no explicit method change, set `framework_policy=source_exact` and copy every guide stage's tool kind and tool.
17. Reject generative-video → HyperFrames/Remotion/GSAP/FFmpeg substitution. Code video is not equivalent to generative video provider.
18. Generate only source-route inputs. Do not make background plates or framework assets source route does not consume.
19. Treat still generation as intermediate only. For `code_video`, dispatch exact route through framework adapter. Remotion: create one shared project at `videos/<source-id>/remotion/`; run `python <skill-root>/scripts/prepare_remotion.py --repo-root <workspace> --source-id <source-id> --setup-shared` only after approval for Node/npm package download; later projects reuse versioned user-data toolchain; preview with `npm run studio`. HyperFrames: require Node.js 22+, FFmpeg, and FFprobe. Doctor/preflight may inspect only a direct configured/global CLI; they must not run plain `npx` before approval. If no direct CLI exists, run `python <skill-root>/scripts/prepare_hyperframes.py --repo-root <workspace> --source-id <source-id> --setup-approved` only after setup approval; otherwise omit the flag. Use the CLI recorded in readiness for native `check` and `preview`, obtain final preview approval, then run `python <skill-root>/scripts/render_hyperframes.py --project-root <workspace>/videos/<source-id>/hyperframes --output out.mp4 --approved --reviewer <name>`. Never emit Remotion files/commands for this route. Unknown local framework → actionable `adapter unavailable`; never default Remotion. Keep framework-native source, readiness, structured check/render receipts, approval record, motion manifest, and native MP4. A crop, generated still, or still-only manifest always fails Recreate. When exact external video stage needs cost/provider approval, finish and approve every `required_pre_provider_asset_id`, including shared style/reference and scene-start image where cataloged; finish recovered prompt/handoff; mark `awaiting_user_approval`; stop without substitute render.
20. After authorization, build one high-risk proof, compare, fix one cause, repeat.
21. Extract 0/25/50/75/100% render frames plus every available source-role checkpoint. Open source and output side-by-side; record hashes, reviewer, differences, and all fidelity gates. Final-frame mismatch blocks delivery. Run `validate-scene-delivery`; code-video additionally requires shared framework root, runnable Studio launcher, real editable props/tracks, motion manifest, native render provenance, MP4, and checkpoint QA.

Built-in ImageGen generation needs no extra approval after explicit recreation request. External image/audio/video providers, paid calls, credential use, data upload, or provider/model changes require approval.

For external/full-pipeline preparation, approve current guide hash, then run:

```text
python <skill-root>/scripts/run.py review --run <run-dir> --decision approve --reviewer <name>
python <skill-root>/scripts/run.py prepare-scene --run <run-dir> --target-choice match
python <skill-root>/scripts/run.py validate --run <run-dir> --stage scene-ready
python <skill-root>/scripts/run.py validate-scene-delivery --scene-dir <repo-root>/videos/<scene-id> --catalog <repo-root>/docs/reconstructions/<source-id>/scene-catalog.json
```

## Create from guide

Use published guide as production system, not content to copy.

1. Confirm new brief plus what must remain: method, visual system, or both.
2. Use `adapt` for same visual system/new content; use `method` for workflow only.
3. Keep new prompts/assets/results labeled generated, never source evidence.
4. Give new work its own scene ID/workspace.
5. Reuse approved shared assets only when brief needs them.
6. Compare against selected guide constraints plus new brief. Do not require source-content identity.
7. Apply same receipts, manifests, auth, QA, delivery rules as recreation.

For external/full-pipeline preparation:

```text
python <skill-root>/scripts/run.py prepare-scene --run <run-dir> --target-choice adapt
```

## QA is mandatory

No test action exists. Apply QA throughout:

- evidence QA before guide;
- guide coverage/provenance QA before publication;
- scene target/prompt QA before generation;
- asset QA before motion/render;
- source/brief comparison after every generated proof;
- file, receipt, hash, render QA before delivery.

Any failure blocks later completion. Corrections use `tutorial-re` runtime-created child runs with the publishing run as parent; never copy a run directory or hand-author its ID/timestamps. Never let prose override validator failure.

Read [reconstruction test](references/reconstruction-test.md) for comparison procedure and [artifact contracts](references/artifact-contracts.md) when writing run records.

## Pipeline and asset rules

Read [fidelity and production](references/fidelity-production.md) before assets, framework setup, motion, or render.

Core rules:

- explicit user framework wins;
- otherwise reproduce the demonstrated pipeline and methodology exactly;
- deterministic code-video cannot replace a demonstrated generative video stage;
- generated raster assets use built-in ImageGen;
- ImageGen uses `highest_available` quality when exposed; image tool has no thinking-effort control;
- source asset reconstruction uses ImageGen edit references and preserves source layout/content hierarchy;
- semantic assets from composite frames use ImageGen edit with full frame;
- charts/arrows/counters/simple geometry may be code-native;
- placeholders cannot pass recreation QA;
- all required raster assets must be approved before render;
- Remotion request requires real Remotion project, Studio tracks, native render provenance;
- run `render_guard.py` before native render.

## Storage boundary

Cache holds source-derived evidence and run bookkeeping only. Publish durable guide under `docs/reconstructions/<source-id>/`. Store scene prompts, refs, assets, receipts, QA, framework source, renders under `videos/`.

Never create workspace-root `tools/`. Put temporary helpers under current run `tools/`; publish no helper unless user requested it.

Helpers may extract frames or crop known ROI. They must not write section map, discovery resolutions, evidence manifest, scene catalog, guide, claims, or QA decisions. Validator rejects semantic materializer scripts.

Source screenshot is `source_reference`, never generated asset. Shared asset used by 2+ scenes belongs under `videos/<source-id>/shared/` with prompt, receipt, QA, manifest.

## Human gates

Continue autonomously through requested local work, built-in ImageGen, local post-processing, and QA. Stop for ambiguous target, external provider submission, paid use, credential/data upload, provider/model change, or source-faithful target deviation.

## Report

Report outcome first. Link public guide/catalog or scene doc, manifest, refs, prompts, generated assets, final still/render, receipts, QA. Never report cache path as final deliverable. Never claim pass from structural validation alone.
