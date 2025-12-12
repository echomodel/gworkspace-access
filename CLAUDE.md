# Claude Code Instructions for gworkspace-access

## Required Reading

Before making changes, read and follow:
- `CONTRIBUTING.md` - Version management, release workflow, development setup

## Version Bumps

**Always bump the version when making code changes that will be pushed.**

See `CONTRIBUTING.md` for details, but the key points:
- Version lives in `gwsa/__init__.py`
- Patch bump (0.2.0 → 0.2.1) for bug fixes
- Minor bump (0.2.0 → 0.3.0) for new features
- Tag releases: `git tag vX.Y.Z`

Without a version bump, `pip install --upgrade` will not pick up changes.

## Pre-Commit

Run `devws precommit` before committing. Findings in LICENSE (author name) are false positives.
