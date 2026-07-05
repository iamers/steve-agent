# CLAUDE.md

Instructions for Claude Code when working on this repository.

## What Steve Agent is

Steve Agent is a dev-coordination AI agent for small development teams collaborating through a Telegram forum group. It is designed to handle:

- Task backlog, assignment, ownership enforcement
- Ideas and brainstorming (future: round-table with multi-role subagents)
- Member interaction in the general topic
- Optional in-chat development assistance per feature topic (via git worktrees)

Steve Agent is built on [Hermes Agent](https://github.com/nousresearch/hermes-agent) for coordination. An optional [OpenClaw](https://github.com/openclaw) instance of the product-under-development can run in the same group for dogfooding, restricted to dedicated test topics.

## First use case

Coordinating development of [rene-agent](https://github.com/iamers/rene-agent), a community-management agent for Telegram. Rene-agent and Steve Agent are part of a potential suite of AI agents built on Telegram plus open agent frameworks; running Steve in the rene-agent dev group is itself the first dogfooding exercise for the suite.

Steve Agent is designed to be reusable for any small dev team, not tied to rene-agent.

## Status

Early design stage. No shipped artifact yet.

- Design conversation and current iteration: `.local/brainstorm/`
- External references and inspiration: `.local/references/`
- Active design document (work in progress): `.local/design/`

`.local/` is gitignored. When the design stabilizes, the public-facing parts move to a public `design/` directory.

## Conventions (inherited from rene-agent)

- **Identifiers** (files, folders, variables, keys, CLI flags, config fields): English, always. Non-negotiable.
- **Prose content** (design docs, inline comments): currently Italian, reflecting the contributor community; long-term target is English, no hard deadline.
- **User-facing strings** (README, CONTRIBUTING, LICENSE, error messages): English.
- **Agent personalities** (SOUL.md and analogs): any language.

## Working on this repo today

- Public top-level (tracked): `README.md`, `CLAUDE.md`, `.gitignore`, future `LICENSE`, future `design/`, future implementation
- Private (gitignored): `.local/` contains brainstorm notes, external references, active design drafts
- See [rene-agent](https://github.com/iamers/rene-agent) as sibling project for convention patterns and repo structure once the design matures
