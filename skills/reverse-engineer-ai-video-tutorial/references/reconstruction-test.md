# Reconstruction test

## Select scene

Use one asset still and one motion clip when highest-risk asset and motion differ. Avoid easy decorative transition.

## Provenance

Save exact input hashes, prompt, provider/surface/model/version, settings, actor, time, output hash, defects. Reject bad reference text/logo before video generation.

## Authorization

State provider, model, cost, submitted inputs, owner. Generate one clip only after explicit approval. No batch first.

## Reference QA

Before temporal sampling, confirm every source frame belongs to the named scene occurrence and prompt group. Nearest timestamp is discovery only, never proof of identity. If the tutorial omits mid/final or motion evidence for the target occurrence, mark it unavailable and test only supported checkpoints; do not substitute an adjacent scene.

For ≤10 seconds:

1. extract every integer-second frame;
2. extract nearest final decodable frame;
3. build contact sheet;
4. probe duration/resolution/codecs/audio;
5. write per-second observation/result;
6. compare 0/25/50/75/100% progress to source refs;
7. gate reference composition, asset fidelity, identity, typography, motion topology, scene content, artifacts, audio, final state.

Save each extracted output frame, exact reference frame, hashes, reviewer, unresolved differences, and gate results. MP4 path alone is not checkpoint evidence. A final-frame contour/object/layout mismatch fails even when earlier timing passes.

Prompt compliance alone cannot pass. Missing source comparison blocks pass.

Derived result:

```text
any fail → FAIL
any partial → SALVAGEABLE BUT FAIL
all pass → PASS
pending → incomplete
```

Sampling cannot prove continuous trajectory. Add targeted frames or mark partial.

## Revision

1. Name one failed constraint.
2. Preserve passing blocks.
3. Patch one cause.
4. Create child run.
5. Repeat full QA.

Keep working base prompt. Avoid second-by-second timelines unless user requests controlled experiment.
