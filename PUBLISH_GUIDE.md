# Publishing guide

Maintainer runbook for `sato-note/reverse-engineer-ai-video-tutorial`.

Use for commits, pushes, CI checks, tags, GitHub Releases, tagged-install proof. Read before any GitHub mutation.

## Account boundary

Rule: everything under `~/work/` uses work identity.

```text
Repository:   ~/work/reverse-engineer-ai-video-tutorial
Git name:     sato-note
Git email:    franca00523@gmail.com
Git remote:   git@github-work:sato-note/reverse-engineer-ai-video-tutorial.git
Public URL:   https://github.com/sato-note/reverse-engineer-ai-video-tutorial
Branch:       main
```

Work identity comes from conditional Git config:

```ini
[includeIf "gitdir:~/work/**"]
  path = ~/.gitconfig-work
```

```ini
# ~/.gitconfig-work
[user]
  name = sato-note
  email = franca00523@gmail.com
```

Three identities are separate:

| Layer | Controls | Required identity |
|---|---|---|
| Git config | Commit author | `sato-note` / `franca00523@gmail.com` |
| SSH alias `github-work` | Fetch/push/tag transport | GitHub account `sato-note` |
| GitHub CLI/API | Actions, Releases, repo API | Do not assume work identity |

Git config does not switch `gh`. SSH alias does not switch `gh`.

Default `gh` login on this machine is personal. Do not use `gh` for work-repo mutations. Use Git through `github-work`; use GitHub website signed in as `sato-note` for Release publication.

If `gh` use becomes necessary, stop first. Verify API login is exactly `sato-note` plus repo permission includes `push: true`. Never rely on Git name/email as API proof. Never print tokens.

## Hard stops

Stop before mutation when any item differs:

- resolved repo root;
- branch `main`;
- Git name/email;
- origin URL;
- SSH account;
- clean/intended worktree state;
- version/tag target;
- hosted CI result;
- GitHub website account.

Never compensate with force-push, tag movement, default GitHub SSH host, personal `gh` auth, copied private files, hidden credentials.

## Preflight

Run from repo root:

```powershell
$repoRoot = Join-Path $env:USERPROFILE "work\reverse-engineer-ai-video-tutorial"
Set-Location $repoRoot

git rev-parse --show-toplevel
git branch --show-current
git config --show-origin user.name
git config --show-origin user.email
git remote -v
git status --short --branch
git log -5 --oneline --decorate
```

Expected:

```text
root:   <home>/work/reverse-engineer-ai-video-tutorial
branch: main
name:   sato-note
email:  franca00523@gmail.com
origin: git@github-work:sato-note/reverse-engineer-ai-video-tutorial.git
```

Verify SSH transport:

```powershell
ssh -T -o BatchMode=yes git@github-work
```

Expected message:

```text
Hi sato-note! You've successfully authenticated, but GitHub does not provide shell access.
```

GitHub returns exit code `1` for this successful no-shell test. Validate message, not exit code alone.

Verify remote refs without `gh`:

```powershell
git ls-remote origin refs/heads/main
git ls-remote --tags origin
```

Blank tag output means no remote tags. `ERROR: Repository not found` means wrong repo/account/remote or missing access.

## Repository boundaries

| Path | Role | Publish? |
|---|---|---|
| Current repo root under `~/work/` | Public Git checkout | Yes |
| `<source-mirror>` | Source mirror | No direct push |
| `<private-dev-repo>` | Private tests/docs | Never |
| `<private-release-records>` | Audit, handoff, TODO | Never |

Only public checkout may push `origin`.

Canonical install payload:

```text
skills/reverse-engineer-ai-video-tutorial/
```

Root docs, CI, tests, Git metadata are repository content, not installed payload.

Never publish:

- `.hermes.md`;
- private dev docs/tests;
- cache or runtime dirs;
- `.pytest_cache`, `__pycache__`, bytecode;
- credentials, cookies, tokens, auth receipts;
- user media, downloaded tutorials, generated output;
- local managed environments.

## Release preparation

1. Confirm requested scope.
2. Inspect user changes; preserve unrelated work.
3. Update public checkout only.
4. Mirror source content only when release process requires parity.
5. Update version set together for version changes:
   - `skills/reverse-engineer-ai-video-tutorial/VERSION`;
   - bundled runtime `__version__`;
   - launcher exact-version guard;
   - `SKILL.md` runtime requirement;
   - `CHANGELOG.md`.
6. Keep public URLs as HTTPS. Keep maintainer Git transport on `github-work` SSH alias.
7. Recompute counts/hashes. Never reuse stale file count or payload SHA.

Inspect package boundary:

```powershell
git ls-files
git ls-files --stage | Select-String 'install_skill\.sh|prepare_remotion\.sh|prepare_hyperframes\.sh'
```

POSIX wrappers must retain mode `100755`.

## Local release gates

Run public tests:

```powershell
$env:PYTHONUTF8 = "1"
py -3.11 -m unittest discover -s tests -v
py -3.14 -m unittest discover -s tests -v
```

Run skill validator:

```powershell
$validator = Join-Path $env:USERPROFILE ".codex\skills\.system\skill-creator\scripts\quick_validate.py"
py -3.11 $validator `
  "skills\reverse-engineer-ai-video-tutorial"
```

Run installer dry-run plus base doctor:

```powershell
py -3.11 skills\reverse-engineer-ai-video-tutorial\scripts\install_skill.py `
  --source . --host shared --dry-run --json

py -3.11 skills\reverse-engineer-ai-video-tutorial\scripts\run.py `
  doctor --profile base --allow-missing --json
```

Record payload file count and SHA-256 from current output.

Run private regression suite without copying private files into public repo:

```powershell
Set-Location "<private-dev-repo>"
python -m pytest tests -q
Set-Location $repoRoot
```

Run hygiene checks:

```powershell
git diff --check
git status --short
git ls-files | Select-String -Pattern '\.hermes\.md|\.pytest_cache|__pycache__|\.pyc$|cache/'
```

Expected final command: no output. Inspect tracked content for credentials, private paths, user media.

Any failed gate → stop. Fix forward, rerun full affected suite, then full release gate.

## Commit

Stage explicit paths. Never use broad staging when worktree contains unrelated changes.

```powershell
git add -- <intended-paths>
git diff --cached --check
git diff --cached --stat
git diff --cached
git status --short
```

Confirm staged files only. Commit:

```powershell
git commit -m "<concise message>"
git rev-parse HEAD
git show --stat --oneline HEAD
```

After an already-public commit, fix with forward commit. Never amend public history.

## Push `main`

Recheck identity immediately before push:

```powershell
git config user.name
git config user.email
git remote get-url origin
git branch --show-current
git status --short
```

Push only through work alias:

```powershell
git push origin main
```

Never replace origin with `git@github.com:...`. Never force-push.

Verify local/remote parity:

```powershell
git rev-parse HEAD
git ls-remote origin refs/heads/main
git status --short --branch
```

## Hosted CI

Use work-account browser session:

```text
https://github.com/sato-note/reverse-engineer-ai-video-tutorial/actions
```

Require run whose head SHA equals pushed commit. Require all six Windows/macOS/Ubuntu × Python 3.11/3.14 jobs green. Inspect annotations and each failed step.

Also verify rendered pages:

- repository README;
- relative links and GIF;
- license;
- canonical skill subtree;
- issue/PR templates;
- no private/cache artifacts.

CI failure before tag → reproduce locally, add regression when useful, push forward fix, rerun full matrix.

## Immutable tag

Tag only when:

- final public URLs work;
- local gates pass;
- matching hosted CI is green;
- version, runtime, launcher, `SKILL.md`, changelog agree;
- worktree is clean;
- local SHA equals remote `main`;
- target SHA is recorded;
- tag does not exist locally or remotely.

Check tag absence:

```powershell
git tag --list v0.0.1
git ls-remote --tags origin refs/tags/v0.0.1
```

Create annotated tag:

```powershell
git pull --ff-only origin main
git status --short
git tag -a v0.0.1 -m "reverse-engineer-ai-video-tutorial v0.0.1"
git show --no-patch --decorate v0.0.1
git push origin v0.0.1
git ls-remote --tags origin refs/tags/v0.0.1
```

Verify peeled annotated-tag target when needed:

```powershell
git rev-list -n 1 v0.0.1
git rev-parse HEAD
```

Both SHAs must match.

Published tag is immutable. Failure after tag push → never delete, move, or retarget tag. Fix code/version/changelog, publish next patch version.

## GitHub Release

Default route: GitHub website signed in as `sato-note`. Do not use personal `gh` session.

```text
https://github.com/sato-note/reverse-engineer-ai-video-tutorial/releases/new
```

Before publish:

1. Confirm browser account is `sato-note`.
2. Select existing pushed tag.
3. Title matches tag, for example `v0.0.1`.
4. Use matching `CHANGELOG.md` entry plus concise install links.
5. Link README install section and tagged canonical skill subtree.
6. Mark prerelease only when release policy requires it.
7. Attach no binaries, private docs, caches, envs, media, generated output.
8. Publish.
9. Record Release URL.
10. Verify Release resolves to exact immutable tag/commit.

GitHub-generated source archives plus tagged subtree are release artifacts. Manual asset upload is unnecessary.

## Fresh tagged-install proof

Use new unique temp checkout. Do not reuse maintainer worktree or installed skill.

```powershell
$auditRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
  ("reverse-engineer-ai-video-tutorial-v0.0.1-audit-" + [guid]::NewGuid().ToString("N"))

git clone --branch v0.0.1 --depth 1 `
  https://github.com/sato-note/reverse-engineer-ai-video-tutorial.git `
  $auditRoot

Set-Location $auditRoot
$skillsRoot = Join-Path $auditRoot "audit-skills"
$target = Join-Path $skillsRoot "reverse-engineer-ai-video-tutorial"
```

Dry-run, install, verify, doctor:

```powershell
py -3.11 skills\reverse-engineer-ai-video-tutorial\scripts\install_skill.py `
  --source . --skills-root $skillsRoot --target $target --dry-run --github --json

py -3.11 skills\reverse-engineer-ai-video-tutorial\scripts\install_skill.py `
  --source . --skills-root $skillsRoot --target $target --github --json

py -3.11 skills\reverse-engineer-ai-video-tutorial\scripts\install_skill.py `
  --source . --skills-root $skillsRoot --target $target --verify --json

py -3.11 "$target\scripts\run.py" doctor --profile base --allow-missing --json
```

Record:

- tag + commit;
- provenance mode `github`;
- install target + receipt;
- version;
- payload file count + SHA-256;
- doctor state/capabilities/warnings;
- rollback command.

Then run one real agent install from public tag. Existing user-level install requires explicit replacement approval and `--force`; temp proof does not.

Delete temp audit data only after evidence is recorded. Validate resolved path remains inside system temp dir before recursive removal.

## Close release

Post-release checks:

- Release page → exact tag/commit;
- README URLs and install prompts work;
- YouTube timestamp works;
- Actions green for release commit;
- fresh clone contains intended tracked files only;
- tagged installer receipt/hash/doctor verified;
- rollback command recorded.

Update private trackers without staging them in public repo:

```text
<private-release-records>
<private-dev-repo>/docs
```

Status language:

| Status | Meaning |
|---|---|
| Public `main` | Branch pushed; not immutable release |
| Verified `main` | SHA parity + hosted CI green |
| Tagged release | Immutable tag on verified commit |
| GitHub Release | Release page binds exact tag |
| Fully published | Fresh tagged install + receipt/hash/doctor proof passed |

Never call `main` alone an immutable release.

## `v0.0.1` continuation checkpoint

Baseline before final docs commit:

```text
Public commit: a0be93ea9acdcacf516c7f54eacfb0fb861d3f6a
Hosted run:   https://github.com/sato-note/reverse-engineer-ai-video-tutorial/actions/runs/31355101549
Result:       six jobs passed
Tag:          not published
Release:      not published
```

Required README edits:

```text
Walkthrough: https://www.youtube.com/watch?v=sEfhY-ICW_M&t=272s
GitHub:      https://github.com/sato-note/reverse-engineer-ai-video-tutorial
Windows:     `Verified: install, doctor, runtime, spaced/Unicode paths, rollback, Remotion smoke.`
Other OS:    `Implemented to platform standards; untested.`
```

After adding this guide, recompute tracked repository file count. Prior `83` count is stale. Installer payload should remain unchanged unless canonical skill subtree changes.

Continuation order:

```text
README + guide review
→ local gates
→ commit through work Git identity
→ push through github-work SSH alias
→ hosted CI in sato-note browser session
→ immutable v0.0.1 tag
→ GitHub Release in sato-note browser session
→ fresh tagged-install proof
→ real agent install
→ private tracker closure
```

## Failure policy

- Before commit: fix, restage, rerun gates.
- Local commit not pushed: amend only when safe; otherwise forward commit.
- After `main` push: forward fix only; never force-push.
- Before tag: fix, push, rerun hosted matrix.
- After tag push: never retarget; release next patch.
- Release auth mismatch: stop; switch browser account. Do not use personal API session.
- Fresh install failure: do not mark fully published.
- Broken README link: fix before tag.
- Receipt/hash mismatch: stop; preserve evidence; repair before completion.

## Final report

Report:

- repo + branch;
- Git commit identity;
- SSH push identity;
- final commit SHA;
- hosted CI run URL/result;
- tag + target SHA;
- Release URL;
- README URLs;
- payload count + SHA-256;
- fresh-install target + receipt;
- doctor result;
- rollback command;
- tracker closure;
- remaining warnings.
