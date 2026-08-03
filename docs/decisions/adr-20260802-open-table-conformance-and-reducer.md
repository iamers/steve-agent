---
status: accepted
date: 2026-08-02
---

# Open Table conformance tiers, its first reducer, and matrix ownership

## Context

Three questions were left open when the Open Table contract was accepted. They
were settled on 2026-08-02 as points 11, 12, and 13 of issue #130. The rest of
the contract remains in `docs/specs/open-table-v0.md`.

Review of the first conformance implementation on 2026-08-03 showed that point
12 had selected an execution mechanism without selecting a durable home for the
creation receipts required by replay. This decision is narrowed accordingly:
the Action remains the intended implementation, but is not a selected conforming
deployment until that storage and authority decision is accepted.

## Decision

Conformance has two tiers. Participant conformance is composing and parsing the
envelope correctly and treating peer content as untrusted. A participant never
computes a canonical digest, validates a replay bundle, or implements replay.
Reducer conformance is everything else in the contract. The split exists
because the roles carry very different burdens, and collapsing them would put
the reducer's cost on every participant, contradicting the razor.

A GitHub Action remains the intended first reducer implementation in this
repository, not a selected conforming deployment. Before that selection can be
made, a separate accepted decision must define a durable, authenticated,
non-circular GitHub-resident store for creation receipts and deletion evidence,
plus its minimum permissions, retention, concurrent-write behavior, and
fail-closed recovery. No such store is selected today. In particular, the
mutable issue projection, workflow caches, and retention-bound Action artefacts
are not replay sources. A protected Git-backed ledger is a candidate, but its
need for `contents: write` and its failure/concurrency model require explicit
review rather than being implied by this ADR. A future Action implementation's
authenticated issuer will be its token and its principal the bot identity
GitHub reports. The principal is per-repository deployment configuration;
another repository selects its own. A GitHub App is the graduation path when a
second repository adopts the protocol.

The adapter compatibility matrix is maintained by this project, one row per
upstream release, evaluated on the same pass that evaluates the pin. An adapter
profile may declare a supported runtime pin internally when its safety
properties were verified against a specific source. That declaration creates
the matrix and recurring work; no Open Table adapter currently declares such a
pin. The work is owned here rather than left unowned.

## Consequences

The protocol can be implemented by a participant without any of the reducer
machinery, which is what makes it runtime-agnostic in practice rather than only
in principle. Nothing runs until both the receipt-store decision and reducer
exist, no current artifact may claim reducer conformance, and work claims remain
advisory in the meantime. The matrix obligation begins when an adapter declares
a supported runtime pin.

## Alternatives considered

A single conformance tier: rejected as contradicting the razor and raising the
entry cost for the contributors the protocol exists to include.

A GitHub App as the first reducer: rejected for now because it is a service with
hosting and availability obligations and would become a dependency of this
project's own factory.

Leaving the matrix unowned: rejected because the reason the pin is declared at
all is that someone verified it.
