---
status: accepted
date: 2026-07-29
---

# Roundtables run on Kanban Swarm

## Context

A roundtable needs independent participants that can inspect sources, use tools,
contribute in parallel, review earlier phases, and converge on a durable
outcome. Mixture of Agents (MoA) does not provide that execution model. Its
reference path calls the language model with messages, temperature, token
limits, and runtime settings, but without tools. The references are independent
blind advisory calls: they cannot inspect a repository, run a command, or
search, and no preset can add those capabilities.

Kanban Swarm creates dispatched worker cards followed by a verifier and a
synthesizer. A spike on the instance confirmed that two cards assigned to the
same worker profile were claimed in the same second and had overlapping run
intervals. The root completed immediately, while the verifier depended on both
workers and the synthesizer depended on the verifier.

The spike also exposed limits in the pinned Kanban Swarm v1. It creates scratch
workspaces and offers no project or workspace option, so a repository-dependent
probe blocked both workers. Consequently, successful promotion through the
verifier and synthesizer was not demonstrated. The root blackboard was an
append-only comment with a `[swarm:blackboard]` prefix and a JSON object for the
topology. A worker's automatic parent context contained the root completion
handoff, but not that comment; participants must explicitly read the root or the
linked discussion artefact when they need the live history.

## Decision

Roundtables run on Kanban Swarm. MoA remains a separate, cheaper tier for quick
blind opinions that do not need tools or interdependence. Until the pin moves or
Swarm accepts a project workspace, roundtable work must be workspace-independent
and must use tool-accessible external sources rather than assume that a scratch
card contains a repository.

Each roundtable has one GitHub issue. Comments are the append-only deliberation,
with one comment per participant per phase; comments are never rewritten. At
the end of every phase, the issue body is rewritten to show the question,
participants, current phase, open points, and settled points. Every settled
point carries a permalink to the comment that settled it.

A multi-phase roundtable, such as Dreamer, Realist, and Critic, uses the same
issue for every phase. Later phases read the full earlier history instead of
receiving fragments split across issues.

The issue is the artefact and the board is the machinery. The root card body
links to the issue, and the issue body names the root card id. There is no third
record. Participants read the issue explicitly rather than relying on root
comments to be injected into their automatic Kanban context.

The outcome is an architecture decision record in `docs/decisions/`, not a
further issue.

## Consequences

The factory gets parallel, tool-capable participants and an auditable dependency
graph. The spike directly established same-profile parallel execution, but not
a successful end-to-end graph: both scratch workers blocked on a repository
assumption, leaving the verifier and synthesizer unstarted. The roundtable
implementation must therefore include a workspace-independent substrate test
before relying on verifier and synthesizer promotion in production.

Participants share one model in the pinned version because `hermes kanban
create` accepts neither `--model` nor `--provider`. Role diversity comes from
the card body and attached skills, not model diversity. Upstream has since
added per-card model selection, which is another reason to move the pin.

The single issue remains readable without access to the task board, while the
board preserves dispatch and dependency evidence. Rewriting the issue body
produces a useful current state without erasing the append-only comments that
support it. Keeping all phases in one issue increases the amount of history a
later participant must read, but avoids losing the context needed for
convergence.

## Alternatives considered

Using MoA for the roundtable: rejected because its reference agents have no
tools and no interdependence. It remains useful for cheap blind opinions.

Using one issue per phase: rejected because it fragments the history that later
phases and the final decision need.

Using the board as the public deliberation artefact: rejected because the issue
provides durable, linkable comments and a readable current state, while the
board is execution machinery.

Creating another issue for the outcome: rejected because the durable outcome is
an ADR, and a second issue would duplicate state without adding authority.
