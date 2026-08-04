# Contributing to Steve Agent

Thanks for considering a contribution. This document explains how the repository
is laid out and how a change moves from idea to merged pull request. It is
intentionally short and points to the files that hold the full detail.

## Repository structure

The layout is described in `AGENTS.md` (repo map and process rules) and in
`docs/ARCHITECTURE.md` (the full arc42-light architecture, actors, and quality
drivers). The review process lives under `.steve/`. The deployment blueprint and
install steps live under `instance/`, starting with `instance/INSTALL.md`. Read
those three first:

- `AGENTS.md` for the repo map and the process rules every worker follows.
- `docs/ARCHITECTURE.md` for the big picture and the quality drivers.
- `instance/INSTALL.md` for how an instance is deployed and verified.

## Contribution flow

Every change lands through a pull request against `main`. There is no other path.

1. Branch from `main`. Create one branch per change.
2. Make your change on the branch. Run the local checks (below) before pushing.
3. Open a pull request against `main`. Use a Conventional Commits subject
   (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`, `chore:`).
4. CI must be green on the PR.
5. The PR needs one review approved by a GitHub account different from the
   author. A self-approval does not count.
6. For `safe`-tier pull requests, once all five deterministic gate conditions
   below hold, the merge is performed by the project's GitHub App identity. For
   `propagation` and `blast` pull requests, a human merges on GitHub. In both
   cases, approval is a human decision, with no bypass of review or CI.

## Review tiers

Review effort is not opinion. It is derived deterministically from the paths a
pull request touches, by `tools/pr-brief.py`. The source of truth for which paths
map to which tier is `.steve/review-policy.yaml`.

The tier of a PR is the highest tier among all the files it touches:

- `safe`: human-facing documentation that no agent loads and no script executes.
  This is the only tier the merge gate can merge.
- `propagation`: a bug here is replicated across many installations or future
  environments.
- `blast`: an immediate outage or a block of the whole factory.

The deterministic merge gate requires all five of these conditions:

- The approval label is present on the pull request.
- An `APPROVED` review exists from a reviewer account other than the author.
- CI is green on the latest commit.
- The recomputed pull request tier is `safe`.
- The base is `main`, the pull request is mergeable, and the head has not moved
  since the approval.

Anything not matched by the policy defaults to `propagation`, fail safe rather
than fast.

A `blast` change touches paths such as the instance config or the credentials
mode. It requires extra scrutiny: more sign-off, a human-signed brief, and the
highest reviewer attention. `brief_required_for` in `.steve/review-policy.yaml`
lists which tiers require a brief. Read that file for the exact rules and the
per-path tier list.

## Language rules

- Identifiers (files, folders, variables, keys, CLI flags, config fields) are
  English, always.
- User-facing strings (README, error messages, brief output) are English.
- PR titles and descriptions are English.

Some in-repo prose is still Italian (the current contributor community) and is
migrating to English over time. New contributions should be English.

Terms used across the project are defined in [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Local checks before pushing

Run these before you push a branch:

```bash
# Privacy guard: block tokens from the local denylist.
scripts/check_privacy.sh <files-you-changed>

# The deterministic brief gate.
python3 tools/pr-brief.py --self-test
```

The privacy guard reads a denylist that lives outside version control. When the
denylist file is absent (for example in CI or for an external contributor) the
check is a no-op, so it never fails in the wrong place. Point it at the files you
are committing, not the whole tree.

## No secrets or deployment-specific identifiers

Do not commit secrets, tokens, internal hostnames, chat ids, or anything specific
to a single deployment. Version control holds only generic, reusable content.
The local denylist, the pre-commit hook, and gitleaks in CI all guard this. If a
check blocks your commit, remove the sensitive content and retry; do not weaken
the guard.
