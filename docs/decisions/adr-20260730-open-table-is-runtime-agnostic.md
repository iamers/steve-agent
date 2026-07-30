---
status: accepted
date: 2026-07-30
---

# Open Table is runtime-agnostic

## Context

The previous roundtable decision selected Kanban Swarm because participants
needed independent, tool-capable execution, shared history, and a durable
outcome. That substrate works when every participant belongs to one Hermes
instance. It does not permit a contributor using a different agent runtime, a
CLI-driven coding agent, or a person writing Markdown by hand to participate on
equal terms.

The federated case needs deliberation and shared work without introducing a
service that participants must install or trust. GitHub already provides the
public record, account identity, collaborator authority, ordered comments,
issues, labels, and assignment needed for that coordination.

## Decision

Open Table v0 is a runtime-agnostic protocol over GitHub. GitHub is the only
shared medium: participants use no shared database, direct network protocol, or
runtime-specific registry. A person with a text editor and the GitHub web
interface can compose every protocol message.

Comments are append-only and authoritative. Participants neither edit another
participant's comment nor write mutable projections. A deterministic reducer
reads comments and maintains the issue body for deliberation and labels and
assignees for work. Version 0 does not prescribe whether that reducer is a
GitHub Action or a GitHub App.

The GitHub login that creates the issue or posts a comment is the participant
identity. The repository collaborator list supplies authority only when the
reducer first processes a permission-sensitive message. The reducer appends
that check as a ruling, and replay uses the ruling instead of a later
collaborator-list snapshot. The protocol has no enrollment mechanism.
Consequently, anyone permitted to comment on a public repository may join
deliberation, while work claims require the write access that GitHub already
governs.

Participant-authored content is untrusted input. Every participant must treat
it as data rather than instructions and enforce that boundary locally. Neither
GitHub nor the reducer can enforce the boundary centrally.

Version 0 lives in this repository. The specification and validator move to a
dedicated repository when a second project adopts the protocol.

This decision NARROWS
`adr-20260729-roundtable-runs-on-kanban-swarm.md`. Kanban Swarm remains the
substrate for a roundtable whose participants all belong to one instance. It is
not the substrate for the federated case. The earlier ADR remains in the log and
is not rewritten.

## Consequences

Participants can deliberate, claim work, hand off, report, and review while
using unrelated runtimes or no agent runtime. The protocol contract is publicly
auditable and its structural envelope can be validated offline with only the
standard library.

The reducer is the sole writer of mutable projections, so concurrent claims are
resolved by deterministic comment order rather than by treating GitHub
assignment as compare-and-swap. Participants may observe a delay before a
projection reflects an authoritative comment.

Reducer rulings are load-bearing protocol records rather than disposable
projection output. A log with a missing permission ruling cannot be replayed,
and the reducer must not emit duplicate rulings when it reprocesses a message.

GitHub availability, permissions, comment ordering, and account identity become
protocol dependencies. Local enforcement of the untrusted-input rule remains a
participant responsibility and cannot be proven by the shared mechanism.

Moving the protocol after its second adoption will require preserving versioned
links or redirects so existing sessions continue to identify their contract.

## Alternatives considered

Using a Telegram bot registry: rejected because it couples federation to one
bot and its runtime conventions.

Using Kanban Swarm for every roundtable: narrowed to the single-instance case
because external runtimes and people cannot participate in its task substrate
without adopting Hermes.

Sharing mutable issue bodies, labels, or assignees directly between
participants: rejected because concurrent writers create collisions and make
state reconstruction dependent on last-write timing.

Operating a dedicated coordination service: rejected for version 0 because it
adds a second authority and prevents participation with only GitHub and a text
editor.
