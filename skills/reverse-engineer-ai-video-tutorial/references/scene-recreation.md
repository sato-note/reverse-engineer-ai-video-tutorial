# Named scene recreation

## Mandatory entry gate

Run `start-recreate` before viewing target crop, generating images, choosing framework, or writing outputs. It resolves human alias to canonical catalog ID, validates publishing run, locks source-exact route, records asset/prompt dependencies, and declares terminal artifact. Use returned canonical scene directory and preflight. Never hand-author this receipt. Failure means repair Guide; no generation.

For code-video route, terminal artifact is native rendered video. Still/crop may support reference or asset QA only. It cannot complete Recreate.

## Required evidence stack

Treat published workflow/catalog as index. Reopen source evidence for production detail:

```text
master motion/style sheet
→ reference/image/video overview
→ scene-by-scene prompt frame
→ generated scene output frames
```

Before generating, confirm the selected catalog row is `scene_kind=output_scene` and `recreate_addressable=true`; workflow/setup/debug/editor steps are not Recreate targets. Resolve every production input from the scene's `required_asset_ids` (and `required_pre_provider_asset_ids` for reference-video routes). Keep `target_reference_asset_ids` comparison-only; never feed a shown final composite back into production. Each target uses a scene-specific ROI whose receipt source is a scene reference frame. Tutorial-shown input assets are identity targets, not inspiration. Execute the cataloged `production_action`: `imagegen_reconstruct` uses ImageGen2 image edit with exact crop/full frame; `imagegen_generate` uses recovered prompt when target is unshown; `reuse_source` copies only a registered isolated source file. A source crop is evidence, never generated or reusable production input. Never recreate a shown asset from prose, palette notes, or prompt alone.

Build references by prompt-bound scene identity, never proximity. A prompt-card change ends an occurrence even when the catalog interval continues. For every available start/mid/final frame or motion sample, record its catalog source-evidence path, target prompt-group ID, durable hash, reviewer, and `target_match: pass`. If the tutorial does not show a role for that exact occurrence, write `availability: unavailable` plus a reason. Do not borrow a neighboring scene merely to complete three slots. Provider handoff requires a verified start frame; it does not require invented mid/final or motion evidence.

Before using Guide, validate its publishing run with current runtime at `guide-complete`. Recreate may not proceed against stale/invalid catalog. Public action is immutable: Recreate means exact scene match; Create-from-guide means adaptation. Never convert ID/title conflict into `adapt`.

For workflows showing `reference sheet → image prompt → still → video prompt → video`, recover both prompt jobs:

- image prompt: composition, subjects, spatial layers, materials, palette, text/logo constraints;
- video prompt: locked style repeated, action order, camera, focus, audio, avoid list, end state.

## Prompt recovery gate

Before any provider/framework decision:

1. Open full prompt screenshot at original resolution.
2. Create tracked ROI from full frame. Review full frame and crop side-by-side; reject crops that cut line endings, headings, or lower prompt blocks.
3. Extract adjacent frames when scrolling, overlays, presenter, or compression hides text.
4. Separate `EXACT-TRANSCRIPTION`, `DETAILED-PARAPHRASE`, `CONDENSED-RECONSTRUCTION`, `UNKNOWN`.
5. Preserve visible headings such as STYLE, SHOT, AUDIO, AVOID.
6. Write full prompt into per-scene doc. Do not promote inferred wording to exact.
7. Record hashes/paths for master sheet, overview, full prompt frame, approved ROI, output start/mid/end.
8. Save recovered source wording as standalone `prompts/source-image-prompt.txt` and `prompts/source-video-prompt.txt`; label unknown/reconstructed text outside exact blocks.

`prompt_recovery: complete` requires full visible prompt coverage or explicit `UNKNOWN` fields with best evidence, approved crop QA, registered crop provenance, standalone prompt files, canonical copies of full frame + ROI. “Guide has a summary” does not pass.

The standalone prompt file's `SOURCE PROMPT CROP` must resolve to the durable manifest reference with role `source_prompt_approved_roi`, whose `cache_origin` must match the scene catalog's `prompt_evidence`. A style sheet, result frame, adjacent scene, or generic full screenshot cannot satisfy this role.

## Route lock

- No explicit framework/method change → copy the guide's demonstrated production route exactly and set `framework_policy=source_exact`.
- Reject a guide scene whose route is generic (`code_native`, Studio, hosted model) or whose route record does not name the demonstrated framework/provider. Repair the guide before generation rather than choosing a substitute.
- Tutorial generative image-to-video route → same provider/model. A code-video framework is a different methodology, not an equivalent implementation.
- ImageGen policy → ImageGen2 creates still/reference assets, not code-drawn substitutes.
- HyperFrames/Remotion → only when tutorial stage is code-native, for exact overlays/assembly, or user explicitly requests code reconstruction.
- Provider unavailable/paid/unapproved → create only the source-route inputs, finish prompts/assets/handoff, mark `awaiting_user_approval`, and stop before submission. Do not create a fallback render.

For Remotion, use preflight `shared_framework_project_root`. Run `python <installed-skill-root>/scripts/prepare_remotion.py --source-id <source-id>` once, register all source scenes in one Root, and launch with `npm run studio`. Scene folders contain docs/refs/QA/renders; they do not own duplicate Remotion packages. Before delivery, launch Studio, verify live Inspector controls and named rows, save `studio-timeline-screenshot.png`, then extract and review 0/25/50/75/100% render frames.

For HyperFrames, use the native adapter: require Node.js 22+, FFmpeg, and FFprobe; run `python <installed-skill-root>/scripts/prepare_hyperframes.py --source-id <source-id>` with a direct CLI, or add `--setup-approved` only after approving CLI setup. Use the direct CLI recorded in readiness for `check` and `preview`, obtain approval, then run `python <installed-skill-root>/scripts/render_hyperframes.py --project-root videos/<source-id>/hyperframes --output out.mp4 --approved --reviewer <name>`. Never create Remotion files for this route.

For a source route of `style sheet → reference still → generative video`, the mandatory deliverables before the external gate are: an approved ImageGen2 shared style-reference asset, an approved ImageGen2 scene-start/reference still, the faithfully recovered source video prompt, and provider/model/settings handoff. Both generated images must have prompt, receipt, comparison QA, hash, and manifest record. Source screenshots do not satisfy either generated deliverable. Extra background plates or framework-only assets are forbidden unless the guide says they are inputs.

Keep two ImageGen prompt roles separate:

- Recreating master style sheet: use source sheet as edit reference; preserve board layout, panel structure, key text, palette, and components. Remove only surrounding UI/presenter. Generic form: “Recreate a clean standalone version of attached sheet. Preserve title hierarchy, panel grid, panel roles/order, readable labels, proportions, palette, and material language. Do not redesign.”
- Creating scene still: use recreated sheet for style/material reference only; do not copy sheet layout.

Always use built-in ImageGen2. Image tool has no `thinking` setting. If quality/fidelity control appears, choose highest. Inspect each output against correct target before approval; retry mismatched layout/text rather than accepting stylistic similarity.

Image generation is intermediate production, never endpoint for Recreate. Do not proceed to scene still, motion, or external provider while shown-image intermediate differs materially in subject identity, layout, objects, text hierarchy, palette, or composition. After targeted retries, exact source crop is preferred over loose synthetic substitute.

Framework selection before evidence/prompt recovery is a routing failure. Writing an ad-hoc pipeline contract or labeling generative-video → code-video as `capability_equivalent` is also a routing failure.

## Authorization order

Explicit scene recreation authorizes built-in ImageGen2 stills and raster assets immediately after prompt recovery. Save component images under `videos/<scene-id>/assets/`, final stills under `renders/`, prompts under `prompts/`, receipts under `receipts/`, and QA under `qa/`; do not demand guide approval first.

Before generation, publish source-wide reference inputs into `videos/<source-id>/shared/references/` and scene-only full frames plus approved ROI crops into `videos/<scene-id>/references/`. Source screenshots never count as generated assets. Generate reusable clean assets once under source `shared/assets/` with matching prompt/receipt/QA. Save recovered source prompt transcripts plus generation prompts, outputs, receipts, QA, and renders in named scene folders. Create both owning manifests; add direct links to scene doc. Cache paths remain provenance origins only.

Require human approval only before external image, audio, or video provider submission; paid provider use; credentials/data upload; or changed external provider/model. Guide approval gates external/full-pipeline scene preparation, not built-in ImageGen2.

Before reporting completion or `awaiting_user_approval`, run:

```text
python <skill-root>/scripts/run.py validate-scene-delivery --scene-dir <repo-root>/videos/<scene-id> --catalog <repo-root>/docs/reconstructions/<source-id>/scene-catalog.json
```

An empty `generated_assets` list, missing required asset ID, missing ImageGen2 receipt/QA, prompt-crop identity mismatch, adjacent-scene reference, unreviewed target match, or unbound external gate fails delivery.

## Target conflicts

Match ID + title + timestamp + description + prompt group + screenshot. If user-provided ID and descriptive target conflict, stop before files/generation and ask which target. Do not merge evidence, change fidelity to style match, or silently use adjacent scene.

## Start-state lock

ImageGen still represents video start/input state. Derive it from shown source start/result plus source image prompt. Do not bake later video-prompt events into still: counters appearing later, final text, alert washes, transitions, motion blur, or end-state composition stay absent unless source start visibly contains them. Exact shown logos, labels, object identities, counts, and spatial roles are mandatory; generic replacements fail.
