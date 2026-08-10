# Workspace layout

Do not create workspace-root `tools/`. Temporary helper scripts belong under active run `cache/<source_id>/runs/<run_id>/tools/`.

Use this layout for new repositories:

```text
<repo>/
├── .gitignore
├── docs/
│   └── reconstructions/
│       └── <source-id>/
│           ├── workflow.md          # canonical user-facing guide
│           ├── scene-catalog.json   # addressable sections/scenes
│           └── scenes/              # later per-scene reconstruction docs
├── cache/
│   └── <source-id>/
│       ├── source/                  # hydrated source/transcript
│       └── runs/<run-id>/           # section map, targeted frames, evidence, bookkeeping
└── videos/
    ├── <source-id>/
    │   └── shared/                   # source-wide refs and reusable assets
    │       ├── artifact-manifest.json
    │       ├── references/          # original/source-derived refs
    │       ├── prompts/             # reusable asset prompts
    │       ├── assets/              # generated assets used by 2+ scenes
    │       ├── receipts/
    │       └── qa/
    └── <scene-id>/                  # durable, user-facing recreation workspace
        ├── artifact-manifest.json   # complete artifact index + provenance
        ├── references/              # selected source refs copied out of cache
        ├── prompts/                 # recovered and generation-ready prompts
        ├── assets/                  # generated/recreated component assets
        ├── receipts/                # provider/tool generation receipts
        ├── qa/                      # asset and render QA
        └── renders/                 # final stills, clips, and deliverables
```

Rules:

- Track `docs/reconstructions/**`; never ignore it.
- Ignore `cache/`, dependency folders, temporary scratch renders, and secrets.
- Treat `cache/.../guide.md` as frozen run snapshot, not handoff path.
- Publish via `run.py publish-guide`; command copies guide plus catalog and records hashes.
- Cache is evidence-only: original downloads, transcripts/metadata, frames/crops/contact sheets derived from source, crop receipts, crop QA may live there. Recreated or generated artifacts may not.
- Reuse `cache/<source-id>/source/` before shared source cache or network. `--download-video` ensures availability; it must not redownload an existing cached video. Treat cached source bytes as frozen evidence. Refresh only on explicit user request because remote metadata/captions may drift.
- Candidate/rejected crops stay in cache. Scene-used evidence publishes as full-frame + approved-ROI pair under `videos/<scene-id>/references/`; scene manifest records cache origin/hash.
- Recovered exact source prompt text publishes under scene `prompts/source-*.txt`; scene doc links it. Generation prompts use distinct names.
- Before generation, copy source-wide refs into `videos/<source-id>/shared/references/` and scene-only refs into `videos/<scene-id>/references/`. Record cache origin and SHA-256 in owning manifest.
- A tutorial screenshot of a master/style sheet is a `source_reference`, not rendered output. Use `source-*-screenshot.*` naming. A clean recreated master sheet requires ImageGen2 output plus prompt, receipt, QA, and hash.
- Put any generated asset expected in 2+ scenes under `videos/<source-id>/shared/assets/`. Scene manifests reference shared paths/hashes instead of duplicating files.
- Put recovered prompts in `prompts/`, component images in `assets/`, ImageGen/provider records in `receipts/`, QA in `qa/`, and final stills/clips in `renders/`.
- Do not ignore `videos/`; it is the durable handoff surface. Framework source may live inside the scene workspace or a clearly linked sibling project.
- Completion reporting must link the manifest, published references, prompts, generated assets, final render/still when authorized, receipts, and QA. A scene-doc-only, references-only, empty-`generated_assets`, or cache-only handoff is incomplete. `awaiting_user_approval` is valid only after `validate-scene-delivery` passes.

For empty repo, copy `assets/workspace.gitignore` to root `.gitignore` only when user has no existing policy. Preserve existing `.hermes.md` unchanged.
