# AGENTS.md

Instructions for agent workers operating inside a steve-agent worktree.
This file complements `CLAUDE.md`: `CLAUDE.md` carries the project narrative
and conventions for Claude Code; this file carries the repo layout and the
process rules every worker must follow, regardless of which agent runtime
spawned it.

## What Steve Agent is

Steve Agent is a dev-coordination AI agent for small teams collaborating through
a Telegram forum group, built on [Hermes Agent](https://github.com/nousresearch/hermes-agent).
It handles the non-coding side of team work (task backlog, assignment, ideas,
member interaction) and optionally integrates per-feature in-chat development
assistance via git worktrees.

## Repository layout

- `instance/` — config-as-code for a steve-agent instance: config, profiles,
  scripts, skills. This is how a deployment is reproduced and drifted-checked.
- `.steve/` — review process and PR lifecycle artifacts. Holds the review-tier
  policy, the brief template, and the lifecycle doc. Modifying `.steve/` is
  modifying the coordination process itself.
- `tools/` — review and e2e tooling. The brief compiler (`tools/pr-brief.py`)
  lives here and is the deterministic gate on every PR.
- `scripts/` — operational helper scripts.
- `.github/` — CI and repo automation.
- Top-level (`README.md`, `CLAUDE.md`, `AGENTS.md`, `.gitignore`) — context
  files an agent or human reads first.
- `.local/` is gitignored (brainstorm notes, references, design drafts). Never
  commit anything from it; never copy private values out of it.

## Conventions

- **Identifiers** (files, folders, variables, keys, CLI flags, config fields):
  English, always. Non-negotiable.
- **Prose content** (inline comments, design docs): Italian is the current
  contributor-community language; long-term target is English, no hard deadline.
- **User-facing strings** (README, error messages, brief output): English.
- **Commits**: Conventional Commits — `feat:`, `fix:`, `docs:`, `ci:`,
  `refactor:`, `test:`, `chore:`. Keep the subject line imperative and under
  72 characters.

## Process rules (minimal)

These apply to every change made in a worktree:

1. **Open a PR against `main`.** Never push directly to `main`. A worker's
   output lands as a pull request; the branch is the worker's own worktree
   branch.
2. **Do not merge.** Until phase 2 auto-merge is in place, every merge is a
   human action on GitHub. Workers stop at "PR opened and verified."
3. **Show executed verification.** When a task lists verify commands, run them
   and report their real output (exit codes, command output) in the task
   result. Do not describe what would have run — run it. A green self-test in
   `tools/pr-brief.py` counts only if you actually executed it.
4. **Respect the review tiers.** Every file you touch falls into a tier
   (`blast` > `propagation` > `safe`) per `.steve/review-policy.yaml`. The
   PR's tier is the max of its files. Higher tiers require more sign-off; the
   tier determines whether a brief with human signature is required.

## Review tiers

The review-tier policy lives in `.steve/review-policy.yaml`. That file is the
single source of truth for which paths are `blast`, `propagation`, or
`safe`, and what each tier requires. `AGENTS.md` is `propagation`: it is loaded
natively into every worker, so changes reach every future task. See the policy
file for the mechanism and the full per-repo path list.
