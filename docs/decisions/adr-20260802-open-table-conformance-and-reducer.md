---
status: accepted
date: 2026-08-02
---

# Open Table conformance tiers, its first reducer, and matrix ownership

## Context

Three questions were left open when the Open Table contract was accepted. They
were settled on 2026-08-02 as points 11, 12, and 13 of issue #130. The rest of
the contract remains in `docs/specs/open-table-v0.md`.

## Decision

Conformance has two tiers. Participant conformance is composing and parsing the
envelope correctly and treating peer content as untrusted. A participant never
computes a canonical digest, validates a replay bundle, or implements replay.
Reducer conformance is everything else in the contract. The split exists
because the roles carry very different burdens, and collapsing them would put
the reducer's cost on every participant, contradicting the razor.

The first reducer deployment will be a GitHub Action in this repository. This
is a deployment selection, not a statement that the reducer already exists.
When implemented, its authenticated issuer will be the Action's token and its
principal will be the bot identity GitHub reports. This keeps it inside the
standing non-goal of no App, no hosting, and no service, and makes the
authentication rule checkable rather than abstract. The principal is
per-repository deployment configuration; another repository selects its own. A
GitHub App is the graduation path when a second repository adopts the protocol.

The adapter compatibility matrix is maintained by this project, one row per
upstream release, evaluated on the same pass that evaluates the pin. An adapter
profile may declare a supported runtime pin internally when its safety
properties were verified against a specific source. That declaration creates
the matrix and recurring work; no Open Table adapter currently declares such a
pin. The work is owned here rather than left unowned.

## Consequences

The protocol can be implemented by a participant without any of the reducer
machinery, which is what makes it runtime-agnostic in practice rather than only
in principle. Nothing runs until the Action exists, no current artifact may
claim reducer conformance, and work claims remain advisory in the meantime. The
matrix obligation begins when an adapter declares a supported runtime pin.

## Alternatives considered

A single conformance tier: rejected as contradicting the razor and raising the
entry cost for the contributors the protocol exists to include.

A GitHub App as the first reducer: rejected for now because it is a service with
hosting and availability obligations and would become a dependency of this
project's own factory.

Leaving the matrix unowned: rejected because the reason the pin is declared at
all is that someone verified it.
