## Summary

<!-- What changed? Why? -->

## Scope

- [ ] Skill contract / routing
- [ ] Runtime / validator
- [ ] Schema / template
- [ ] Docs
- [ ] Release metadata

## Checks

- [ ] `python skills/reverse-engineer-ai-video-tutorial/scripts/run.py --help`
- [ ] `python skills/reverse-engineer-ai-video-tutorial/scripts/run.py doctor --json`
- [ ] `python skills/reverse-engineer-ai-video-tutorial/scripts/validate_bundle.py ...` or reason not run
- [ ] Dev `pytest` suite or reason not run
- [ ] Version surfaces aligned, if release PR
- [ ] Changelog updated, if user-visible

Result:

## Safety and package boundary

- [ ] No secrets, credentials, private paths, caches, media, or generated evidence
- [ ] No unapproved provider/network calls
- [ ] Source evidence, generated output, provenance, hashes, and QA remain distinct
- [ ] README/reference docs updated where behavior changed

## Risk / follow-up

<!-- Compatibility impact, migration, known limits, follow-up issues. -->
