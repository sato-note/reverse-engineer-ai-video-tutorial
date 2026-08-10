# Contributing

Contributions welcome through pull requests. Public repo contains shippable skill only. Private tests, fixtures, caches, postmortems, and machine paths stay in separate dev repo.

The installable skill is exactly `skills/reverse-engineer-ai-video-tutorial/`. Root README, changelog, contributor policy, CI, and `tests/` are public-repository assurance files and are not part of the installed payload.

## Before work

- Read [`SKILL.md`](skills/reverse-engineer-ai-video-tutorial/SKILL.md) and relevant files under `skills/reverse-engineer-ai-video-tutorial/references/`.
- Create branch from default branch.
- Use `feat/`, `fix/`, `docs/`, `test/`, `chore/`, or `release/` prefix.
- Keep one coherent concern per PR.

## Change rules

- Skill behavior change → update `SKILL.md` or references, tests, and `CHANGELOG.md`.
- Runtime change → update validators/tests, run doctor, document dependency impact.
- Lock change → regenerate exact pins, run binary-wheel dry-run on advertised Python versions, record lock SHA-256, run bootstrap check.
- Schema/template change → update matching validator, template, reference, and migration notes.
- Release change → update `VERSION`, bundled `__version__`, launcher exact-version guard, and changelog together.
- Do not add caches, media, credentials, tokens, private paths, generated evidence, or `__pycache__`.
- Preserve source evidence, generated output, provenance, hashes, and QA boundaries.
- Avoid network/provider calls in tests.

## Local checks

Public package:

```text
python skills/reverse-engineer-ai-video-tutorial/scripts/run.py --help
python skills/reverse-engineer-ai-video-tutorial/scripts/run.py doctor --json
python skills/reverse-engineer-ai-video-tutorial/scripts/validate_bundle.py --run "<run-dir>" --stage guide-complete
python -m unittest discover -s tests -v
python skills/reverse-engineer-ai-video-tutorial/scripts/install_skill.py --source . --dry-run --json
python skills/reverse-engineer-ai-video-tutorial/scripts/prepare_remotion.py --help
python skills/reverse-engineer-ai-video-tutorial/scripts/prepare_hyperframes.py --help
python -S skills/reverse-engineer-ai-video-tutorial/scripts/run.py doctor --profile base --allow-missing --json
```

Dev regression suite:

```text
PYTHONPATH=<public-repo>/skills/reverse-engineer-ai-video-tutorial/scripts/_runtime pytest -q
```

Run checks from Windows, macOS, or Linux. Report exact commands/results in PR description. Explain skipped checks.

## PR standard

PR description must include:

- Summary and motivation
- User-visible behavior and affected files
- Risk, compatibility, dependency, and migration impact
- Tests/checks with results
- Docs/changelog status
- Follow-up work or known limits

Reviewer checks: scope, evidence/provenance, validator behavior, clean package boundary, dependency docs, security, and changelog accuracy.

## Commits and releases

Use imperative Conventional Commit prefixes: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `release:`. Keep subject concise.

Do not bump release version for ordinary PRs. Release PR keeps package/runtime versions identical, moves `[Unreleased]` entries into a dated section, runs full gates, and tags `v<VERSION>` after merge.

CI action policy: workflow dependencies use reviewed major-version tags during
this initial release line. A release PR must either pin each third-party action
to a reviewed commit SHA or record an explicit maintainer-approved tag-policy
exception in the release checklist.
