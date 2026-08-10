# Fidelity and production

## Target lock

Resolve plain target choice before scene preparation. Store internal content, style, composition, typography, motion policy. Treat fields as immutable. Record user-approved deviations with actor, time, reason, changed field.

Action lock: `recreate` requires `match`/reference reconstruction. `adapt` and `method` require explicit Create-from-guide action. ID/title/description conflict is unresolved target, not user-approved deviation.

## Reference pack

Per scene require:

- start, mid, final frame paths + hashes;
- observed element inventory;
- 4–8 FPS motion samples around key action;
- typography crops;
- palette/material notes;
- invented elements list, normally empty.

Reference reconstruction forbids adding headings, counters, labels, framing devices, or transitions absent from evidence.

## Asset route

| Type | Route |
|---|---|
| generated raster image | built-in ImageGen2 |
| semantic asset inside composite/full scene frame | ImageGen2 `image_edit` with full frame reference |
| exact isolated tutorial asset | unchanged source asset with provenance, or ImageGen2 replacement |
| chart, counter, arrow, simple geometry/layout | `code_native_svg` + `code_native_kind` |
| detailed map/portrait/object visible in composite | ImageGen2 edit from full-frame reference |
| exact label/logo | `controlled_text` or authored SVG |
| style-critical type | `bundled_font` |

Semantic asset record needs `reference_input_type`, ref paths, `reference_image_paths`, exact prompt, negatives, ImageGen2 provider/capability/cost intent, size/alpha target, output hash, QA. Procedural SVG faces fail. Pillow/FFmpeg/ImageMagick semantic extraction fails. Raster tools may post-process ImageGen2 output only.

`reuse_source` means real isolated file bytes are available and registered by path/hash. A screenshot, composite crop, visible local filename, or target frame is evidence only. Composite-only static input requires ImageGen2 reconstruction; demonstrated code graphics require `code_native`; unavailable motion/media requires exact external-media handoff. Split tanker, keyed ocean, counter, background, map, chart, character, and typography dependencies when source route consumes them separately.

Use built-in ImageGen2 for every generated raster. Current image tool exposes no `thinking`/reasoning-effort parameter; never invent one or imply host-model reasoning changes ImageGen2. Record `quality_policy=highest_available`; use highest fidelity option only when tool exposes one. Reliability comes from reference-image edit, correct prompt role, and source comparison.

Classify image generation before prompting:

- `source_asset_reconstruction`: recreate source asset itself. Use source crop/full frame as ImageGen2 edit reference. Preserve layout, section inventory, readable text hierarchy, palette, materials, and proportions; remove only presenter/player/UI contamination. Never say “style only” or “do not copy layout.”
- `style_conditioned_generation`: create downstream scene using master sheet for style/materials only. Do not copy board layout.
- `new_asset`: no source asset identity target.

Shown-image rule: if tutorial displays a workflow input or generated image, guide must catalog exact visual evidence, its pipeline role, and `production_action`; Recreate treats it as identity target. If the tutorial generated that intermediate, use `imagegen_reconstruct` and produce a real ImageGen2 output from the crop/full frame—do not relabel the source crop as generated. Use `reuse_source` only for an actual unchanged source input or an explicitly documented fallback after failed faithful edits. Prose reconstruction is forbidden. Prompt-derived synthesis is allowed only when image is not shown; label uncertainty.

For master/style-sheet reconstruction, inspect source and output side by side at original resolution. Gate layout structure, every panel/section, readable key text, palette/materials, and UI cleanup. Style ingredients alone cannot pass. Failed first output stays candidate; issue targeted correction and retry before approval.

Apply same identity-first gate to every shown intermediate image, not only style sheets. Downstream stages may consume only exact crop/reuse or ImageGen2 candidate that passes subject identity, object inventory, layout/composition, key text, palette/materials, and absence of invented replacements.

Compare ImageGen start still against source start/result, not video prompt's eventual end state. Require exact shown brands/logos and named objects; generic icon substitution fails. Later counter/text/action may appear only after motion stage when source shows that ordering.

All raster rows must be approved before motion source/render. Record ImageGen2 tool-call ID, prompt hash, reference hashes, output path/hash. Bind each output filename in scene source. Placeholder semantic SVG/React/CSS drawings fail even when labeled preflight. Do not render failed candidate first and ask permission later.

## Pipeline lock

Treat tutorial toolchain as a locked production route. Record each motion/video/assembly stage in the canonical `pipeline_contract.json`: evidence refs, observed tool, tool kind, required capabilities, selected tool, selected tool kind, exact match, readiness. Do not invent a smaller ad-hoc contract.

The published guide/catalog must establish this lock before Recreate. Every output scene points to a source-exact route record naming the demonstrated framework/provider. `code_native`, Studio UI, a generic “hosted model,” or an implementation capability is not a production tool identity. Remotion evidence publishes a Remotion route; Gemini evidence publishes the demonstrated Gemini provider/model route. A generic route is a guide-validation failure, not a choice deferred to Recreate.

- Explicit framework in the recreation request → `framework_policy=user_required`; selected tool must exactly match `requested_framework`.
- No explicit framework or methodology change → `framework_policy=source_exact`; follow the demonstrated guide route exactly.
- A generative image-to-video/video-generation stage is not capability-equivalent to HyperFrames, Remotion, GSAP, FFmpeg animation, or another deterministic code-video runtime. Those tools may only perform a separately observed assembly/overlay stage.
- If the exact hosted provider is paid, unavailable, or unapproved, complete the required reference assets, recovered prompt, provider/model/settings handoff, set the stage to `awaiting_user_approval`, and stop. Never render a local substitute.
- Downloadable local framework → repo-local install, native project source, dependency manifest/lock, readiness record, preview command, render command.
- Remotion → `remotion` + `@remotion/cli`, React TSX scene components, composition ID, Studio command, CLI render command/log. Pillow/FFmpeg frame generator cannot satisfy this stage.
- Hosted provider → exact provider/model. Changing provider or methodology requires an explicit user request plus the normal external-provider approval gate.
- FFmpeg may mux/encode/post-process native output. It may not replace required motion runtime.

Generate only assets required by the locked source route. For `style reference sheet → scene reference still → generative video`, create/reuse the shared style sheet and one scene reference still, then submit the recovered video prompt. Do not create a separate background plate or framework-only asset unless the source route requires it.

Separate production inputs from comparison targets. A shown final composite, final preview, or motion sample is a `target_reference`; it is used for QA and must not appear in `input_asset_ids` or `required_asset_ids`. Component images, fonts, palettes, media, code, and required generated start/reference images are production inputs. This contract applies equally to generative-video and code-video routes.

Proof and production provider records must match pipeline contract and include project root, source files, composition/job ID, native command, log, output hash.

Use one Remotion project per tutorial source at `videos/<source-id>/remotion/`. Every scene is one registered composition. Prepare with `python <installed-skill-root>/scripts/prepare_remotion.py --source-id <source-id>`; launch with `npm run studio`. Project must expose Zod schema/default props, live Inspector controls, and named Sequence rows. Per-scene framework copies fail.

For HyperFrames, require Node.js 22+, FFmpeg, and FFprobe. Prepare the native project with `python <installed-skill-root>/scripts/prepare_hyperframes.py --source-id <source-id>` when a direct CLI is already available; if setup is needed, use `--setup-approved` only after explicit approval. Doctor/preflight never performs plain `npx` discovery. Use the direct CLI recorded in readiness for `check` and `preview`, obtain final preview approval, and render through `python <installed-skill-root>/scripts/render_hyperframes.py --project-root videos/<source-id>/hyperframes --output out.mp4 --approved --reviewer <name>`. Preserve authored files, structured receipts, approval record, marker/source hashes, and logs; never create Remotion files for this route.

Studio timeline is part of proof. Components and schema props do not create timeline rows. Every visible element and motion phase requires a named `<Sequence>`/`<Series.Sequence>` track, explicit frame range, default `showInTimeline`, element mapping, and live controls. Internal spring delays alone do not expose tracks. Use `layout="none"` for already-positioned layers. `studio-timeline.json` must link exact Root composition ID/component and actual component source; copied smoke manifests fail. Save screenshot confirming every named row, then pass `studio_timeline_guard.py` before render. Keep native config render gate enabled.

## Asset QA

Compare each isolated asset plus representative composite still to source. Gate identity, silhouette, architecture/object class, editorial treatment, halftone density, palette, transparency, composition, type. Record per-asset matte method, defects, background leak, halo, foreign occlusion. Any defect blocks animation.

For `source_asset_reconstruction`, require additional passing gates: `layout_structure`, `section_inventory`, `readable_text`, `palette_materials`, `ui_cleanup`. Prompt compliance never overrides visual mismatch.

## Motion manifest

Record each element's start/end state, z-order, entrance order, frame window, easing, trajectory, narration anchor, reference timing, code strategy. Every timeline track records name, role, element IDs, range, source component, and prop controls; every element must be covered.

Chart shown drawing over time must remain code-native. Use frame-derived line reveal, partial polyline, path evolution, or clip mask. Static completed chart + whole-layer spring fails motion topology. Break chart timeline into container, axes/grid, series, points, and labels. Every visible series starts hidden/zero-progress, declares its own draw behavior, and owns one named timeline row.

## Research rule

When implementation is missing, search official framework docs/repos first. Save source URL and adopted pattern in motion manifest. Install downloadable dependency in repo. Do not simplify source behavior or switch framework before research.

## Proof QA

Compare source, target lock, output. Inspect integer seconds plus normalized progress checkpoints. Required gates: reference composition, asset fidelity, identity, typography, motion topology, scene content, artifacts, audio, final state.

Self-authored prompt compliance cannot override source mismatch.

## Lifecycle

```text
guide-approved
→ scene-planned
→ generation-authorized
→ assets-approved
→ motion-proof-approved
→ full-rendered
→ final-reference-qa-passed
```

Do not claim later state early. Provider authorization must match actual provider/model/input scope.
