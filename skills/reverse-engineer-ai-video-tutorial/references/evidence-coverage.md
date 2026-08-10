# Evidence coverage

## Labels

| Label | Use |
|---|---|
| `SOURCE-EVIDENCE` | Direct frame/crop/transcript fact. |
| `EXACT-TRANSCRIPTION` | Verified visible/spoken wording. |
| `DETAILED-PARAPHRASE` | Full meaning; wording not exact. |
| `CONDENSED-RECONSTRUCTION` | Short operational summary. |
| `AGENT-INFERRED` | Necessary inference not directly shown. |
| `UNKNOWN` | Source cannot establish fact. |
| `GENERATED-TEST-INPUT` | Agent-created proof input. |
| `GENERATED-TEST-OUTPUT` | Provider output awaiting QA. |

## Procedure

1. Read full VTT/transcript before detailed frame work.
2. Write high-level section map covering source start through recorded duration: purpose, showcased output, section role, transcript evidence, source count claims. Review the actual closing content and complete `tail_coverage`; never satisfy duration by stretching the last section endpoint.
3. Select workflow-bearing sections and every finished-output `showcase_production` playback for autonomous detail pass.
4. Validate `section-mapped`; continue without user prompt.
5. Run adaptive discovery across full selected range for multi-scene sequences. Review every before/after change candidate. No fixed interval.
6. Resolve every candidate, then inventory each prompt, result, shot, panel, or continuation. Give every source unit its own same-ID `demonstrated_unit` evidence row; do not reuse one broad row for multiple units. One unit gets at most one new-`scene` resolution; subsequent views use `same_scene`, or split identity changes into new units.
7. For prompt carousel, group scenes by unique visible prompt card. Crop each group once; extract full prompt meaning.
8. Crop/upscale other prompt, code, config, or UI only after semantic target is known.
9. Inspect crop beside full source frame; fill crop QA sidecar. Prompt QA names only scenes whose rows/cards are visible. Target QA identifies representative/final state and records visible fact candidates. Separately review every image cited by every source occurrence and record its fact candidates, including none.
10. Record visual/text/extraction/label/confidence and cite paths beside claims.
11. Map every source section into catalog; keep non-selected, non-showcase sections overview-only. Inventory every finished-playback scene and bind discontiguous prompt/build/preview/final occurrences to the same logical scene.
12. Cover selected sections continuously with semantic source units and boundary ledger.
13. Extract scene/shot counts from both transcript and text-bearing visual assets. Reconcile each claim with observed inventory; preserve and explain scope conflicts.
14. Resolve required missed/pending rows; normalize JSON; validate.
15. Get human review before external/full-pipeline scene preparation.

## Detail-pass selection examples

- Finished output shown without production explanation → select `showcase_production` for full target-scene inventory; later workflow sections can provide the production occurrences for the same IDs.
- “Here are prompts/scenes used to make this output” → select full section for detail pass.
- Model benchmark unrelated to showcased build → overview unless it establishes required workflow choice.
- Setup/settings section → `method` overview; select only when settings are required to reproduce output.
- Case study tracing source/script → prompts → images/video → final edit → primary detail-pass target.

Do semantic review directly. Helper scripts may extract/format only; they cannot choose boundaries, author claims, or approve QA.

## Coverage row

```json
{
  "item": "stable-id",
  "coverage_kind": "demonstrated_unit",
  "required": true,
  "timestamp": 0.0,
  "evidence": ["frames/frame.jpg"],
  "visual": "covered",
  "text": "readable",
  "extraction": "full",
  "label": "EXACT-TRANSCRIPTION",
  "confidence": "high",
  "claim": "",
  "unresolved_question": "",
  "reviewer_status": "reviewed"
}
```

Coverage kinds: `overview`, `sampling_frame`, `demonstrated_unit`, `detail`. Keep uniform samples as `sampling_frame`; promote selected semantic anchors to `demonstrated_unit`. Every catalog source unit links to exactly one same-ID `demonstrated_unit` row. The row timestamp/range overlaps that unit and its claim describes that unit specifically. Repeated generic claims or one shared row do not prove inventory completeness.

## Partial-extraction check

- Long visible text reduced to short block?
- Every panel/continuation inspected?
- Small text cropped?
- Unreadable zones named?
- Exact/paraphrase/inference labels honest?
- Required evidence paths present?

No complete-prompt claim while uncertainty remains.

## Crop approval

Every cited `crops/*` image requires adjacent:

- `<crop>.<ext>.crop.json`: full-frame source path/hash/dimensions, pixel/normalized ROI, transform, output hash/dimensions;
- schema-v3 `<crop>.<ext>.crop-qa.json`: blind crop-first observation, later source-context comparison, reviewer/time, source/crop hashes, semantic target ID, expected/observed content, text coverage, supported evidence items, verdict rationale, crop-specific notes, semantic checks.

All QA checks must pass: source context verified, ROI matches label, boundaries complete, readable output, no required content clipped, no mislabeled adjacent content. Inspect the crop alone first and describe literal pixels before reading the intended label; then compare with the full frame and claim. Approved crops contain no presenter overlay, adjacent panel, or unrelated UI/content. Exact transcription requires full text coverage and literal visible text. Target-output/source-asset crops require at least two identity anchors. Generic batch notes fail. Receipt source must match asset evidence. Geometry-in-bounds is insufficient. Pending/rejected crop cannot support `covered`, `readable`, `full`, `reviewed`, or `EXACT-TRANSCRIPTION` claim.

Keep failed candidates as rejected cache evidence. Cited approved crop, receipt, QA must be registered in `run.json`. Named-scene handoff publishes full frame + approved ROI under scene `references/`; manifest retains cache origins/hashes.

## Recreation-addressable catalog check

- Every source section has ID, time range, summary, evidence.
- Every demonstrated output scene has stable ID and complete representative/final reference frame/crop; early animation state is not its target reference.
- Workflow/setup/debug/editor states are guide steps, not addressable output scenes.
- One logical output scene remains one ID when its prompt, construction, preview, and final result appear in separate source intervals; preserve those intervals as source occurrences.
- Every source occurrence has a completed fact review covering all cited images; each visible fact candidate binds an exact catalog claim.
- Scene row states content, composition, motion order, camera, text, audio, route, prompt reconstruction, confidence.
- Prompt carousel sampled card by card; one representative crop is not complete coverage.
- Catalog source-unit inventory accounts for every observed card/panel/shot/result/continuation as `cataloged`, `merged`, or `non_scene`; merged/non-scene units require reason.
- Sorted source units cover full section without unexplained gaps. Every later unit has boundary change point.
- New visible prompt has approved crop and exact or detailed-paraphrase extraction.
- Prompt/result/shot-goal/composition/text/transition change cannot use `merged` or `same_scene`.
- Duration never defines scene boundary.
- Every high-level section is present; detail-pass sections and all finished-output showcase sections require full scene inventory.
- Multi-scene detail sections cover full range with adaptive discovery; every candidate is resolved.
- Source count claims remain explicit and reconciled against observed scenes.
- Text-bearing image assets preserve visible output-count claims and link them to reconciliation rows.
- Every workflow asset explains what each evidence path proves. Production inputs cite production-use evidence; workflow explanation alone cannot establish an input.
- Every prompt-carousel scene maps one cropped prompt group with exact/detailed text.
- Guide mirrors section/scene IDs so user can request `section-04 scene 01–02` without another discovery pass.
- Claimed scene count mismatch stays explicit; catalog records observed scenes instead of guessing missing ones.
