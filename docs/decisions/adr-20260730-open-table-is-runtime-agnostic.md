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
runtime-specific registry. A person with a text editor can participate as a participant without running
particular software or calculating canonical digests by hand. Authenticated
software remains necessary to issue authoritative rulings.

The protocol treats comments as append-only, but GitHub does not guarantee that
property. Each authenticated ruling binds to a numeric source comment id and a
canonical digest of the complete message. Edits, deletions, missing rulings,
and conflicting reuse fail closed. Corrections are new messages rather than
silent edits.

A deterministic reducer maintains the issue body for deliberation and labels
and assignees for work. Replay uses
`reduce(ordered_events, trusted_context, authority_policy, as_of)` and trusted
GitHub event timestamps, never the reducer's wall clock. Session configuration
is a protocol event with trusted metadata rather than hidden mutable-body input.
The selected first reducer deployment is a GitHub Action. It is not implemented
in the version 0 artifacts currently shipped. When implemented, its issuer will
be the Action's token and its principal will be the bot identity GitHub reports,
selected per repository; see
`adr-20260802-open-table-conformance-and-reducer.md`.

Participant identity is the numeric GitHub user id; the login is display only.
Authenticated GitHub context supplies identity, repository and source metadata.
The repository permission check occurs once when the first ruling is created,
and replay uses that recorded outcome instead of current permissions. The
protocol has no enrollment mechanism. Consequently, anyone permitted to comment
on a public repository may join deliberation, while exclusive work requires an
authenticated authority profile and the write access GitHub already governs.

A session selects `deliberation-only`, `open-table/ordered-claims`, or
`steve/kanban`. Claims are proposals. Ordered claims receive one award or reject
ruling; under `steve/kanban`, the claim may request the Kanban lease but cannot
create a competing ownership store. Renewals, releases, handoffs,
cancellations, and expirations are recorded events.

Participant-authored content is untrusted input. Every participant treats it as
data rather than instructions. A reducer deterministically excludes invalid or
over-limit events from projections and keeps peer text outside agent instruction
boundaries.

Results carry stable result ids and machine-readable immutable artefact
references. Review requests and verdicts bind to the same result and artefact
version, and reviewer independence compares numeric actor ids.

The conformance tiers and adapter compatibility matrix are settled in
`adr-20260802-open-table-conformance-and-reducer.md`.

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

The reducer is the sole writer of mutable projections. Under ordered claims,
candidate claims are ordered by trusted GitHub creation time and numeric comment
id, then resolved by an award or reject ruling. Participants may observe a delay
before a projection reflects a ruling.

Reducer rulings are load-bearing protocol records rather than disposable
projection output. A replay bundle with a missing source or ruling, source
digest mismatch, or conflicting actor/message-id reuse cannot be replayed, and
the reducer must not emit duplicate rulings when it reprocesses a message.

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
