# Agent install contract

Use this file when user asks to install this repository’s skill for Codex, Cursor, or shared agent storage.

## Required sequence

1. Default to universal user storage (`shared`) for Codex and Cursor. Use a host-specific compatibility target only when user explicitly requests it.
2. Read `skills/reverse-engineer-ai-video-tutorial/VERSION`, `README.md`, canonical `skills/reverse-engineer-ai-video-tutorial/SKILL.md`, installer help, `CHANGELOG.md`, and platform-status notes.
3. Detect OS, architecture, shell, writable user directories, Python candidates, Git, and only tools required by a workflow stated in the request.
4. Prefer immutable release tag `v<VERSION>`. Record source URL, tag, commit, canonical subtree, and provenance mode. A local/archive source must be reported as local provenance.
5. Run source validation and installer dry-run. Dry-run must precede install or update.
6. Treat the request as approval for clone/read/dry-run and fresh user-level skill installation only. Ask before native package-manager installs, privilege elevation, PATH edits, external downloads beyond requested repository, paid/provider calls, or replacing an existing install.
7. Install canonical subtree with `--host shared`. `--host codex|cursor` is an explicit compatibility override. Use `--target` or `--skills-root` only when explicitly needed and safely contained.
8. Verify install receipt and payload hash before runtime setup.
9. For install-only requests, run `base` doctor and defer optional tools. For a stated workflow, run its scoped doctor. Use compatible system runtime when healthy; offer pinned managed runtime only when needed or requested.
10. Prepare only requested framework/capability. Never prepare Remotion or HyperFrames for Guide-only work.
11. After use, verify receipt again and report result.

## Host targets

| Host | Installer selector | Default user target |
|---|---|---|
| Codex + Cursor default | `--host shared` | `~/.agents/skills/reverse-engineer-ai-video-tutorial` |
| Codex compatibility | `--host codex` | `~/.codex/skills/reverse-engineer-ai-video-tutorial` |
| Cursor compatibility | `--host cursor` | `~/.cursor/skills/reverse-engineer-ai-video-tutorial` |

`--host` rejects conflicting roots/targets unless target remains directly contained by the selected host root. Existing installs require explicit replacement approval and `--force`; backups remain receipt-linked. Keep advanced explicit-path usage available.

## Capability policy

- No Python: load instructions, report bundled-command blocker, ask once before approved user-level Python setup. Never silently install Python.
- No Git: ask before Git setup, or continue with clearly limited local/manual provenance.
- Missing optional framework/tool: do not block unrelated workflows.
- Missing native tool: report exact selected-capability blocker; do not improvise privileged changes.
- Guide-only work must not trigger Remotion, HyperFrames, Node, npm, or network-capable discovery.

## Stop conditions

Stop on ambiguous source/provenance, failed source validation, unsafe target, receipt/hash mismatch, unsupported host state, unapproved consequential change, or failed scoped doctor. Do not replace existing installs or mutate system state to force success.

## Final report

Report JSON-equivalent facts:

```text
status, host, version, runtime_version, target, source_url, provenance,
commit/tag, receipt, payload_sha256, runtime_route, capabilities,
warnings, backup, rollback, approvals_requested
```

Mention untested platform status and local/manual provenance limits. Keep provider credentials, user media, paid calls, and external uploads out of install.

## Other Agent Skills hosts

- Gemini CLI: use `--host shared`; Gemini discovers `~/.agents/skills`. After install, run `/skills reload` and `/skills list`.
- Claude Code: install canonical subtree under `~/.claude/skills/reverse-engineer-ai-video-tutorial` using explicit `--skills-root` and `--target`; installer has no `claude` selector.
- Other compatible hosts: place canonical subtree one level below host-documented skills root. Keep source validation, dry-run, receipt verification, and replacement approval. Treat `SKILL.md` as portable contract; `agents/openai.yaml` is optional OpenAI metadata.
- Map generation actions to host-native tools while preserving action semantics and provenance: Codex ImageGen, Cursor image capability, Gemini Nano Banana Flash/Pro, or configured Claude image capability. `imagegen_reconstruct` requires reference-image editing; `imagegen_generate` requires image generation. Never downgrade or replace requested production action.
- Missing optional host tool blocks only matching action, not installation or unrelated workflows. Report exact missing capability.
