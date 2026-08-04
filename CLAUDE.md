# CLAUDE.md

Instructions for Claude Code when working on this repository.

## What Steve Agent is

Steve Agent runs a software team from your chat. It turns a messaging group into
a development pipeline: backlog, AI workers, adversarial review, and merges, all
driven from the conversation where your team already works. It is an operational
factory: tasks raised in chat land as reviewed pull requests.

It handles:

- Task backlog, assignment, ownership enforcement
- Ideas and brainstorming (future: round-table with multi-role subagents)
- Member interaction in the general topic
- Optional in-chat development assistance per feature topic (via git worktrees)

Steve Agent is built on [Hermes Agent](https://github.com/nousresearch/hermes-agent)
for coordination. Optionally, the product under development can run as a separate
bot in dedicated test topics for dogfooding.

## Status

A working factory: tasks flow from chat to reviewed PRs, with an instance
blueprint, CI, and a main-guard in place.

- Active design drafts (work in progress): `.local/design/`
- Brainstorm notes: `.local/brainstorm/`
- External references: `.local/references/`

`.local/` is gitignored. When the design stabilizes, the public-facing parts move
to a public `docs/` directory.

## Conventions

- **Identifiers** (files, folders, variables, keys, CLI flags, config fields): English, always. Non-negotiable.
- **Prose content** (design docs, inline comments): currently Italian, reflecting the contributor community; long-term target is English, no hard deadline.
- **User-facing strings** (README, CONTRIBUTING, LICENSE, error messages): English.
- **Agent personalities** (SOUL.md and analogs): any language.
- **Vocabulary**: defined once in [docs/GLOSSARY.md](docs/GLOSSARY.md). Use those terms; add a term there rather than coining one here.

## Working on this repo today

- Public top-level (tracked): `README.md`, `CLAUDE.md`, `.gitignore`, future `LICENSE`, future `docs/`, future implementation
- Private (gitignored): `.local/` contains brainstorm notes, external references, active design drafts
