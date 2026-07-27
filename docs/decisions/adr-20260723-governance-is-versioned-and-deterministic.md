---
status: accepted
date: 2026-07-23
---

# Governance is versioned and deterministic

## Context

Not recorded when the decision was taken.

First recorded in the repository on 2026-07-23 (commit 7a3ffc5). The decision may have
been taken earlier; the original date is not recorded.

## Decision

Governance-as-code in `.steve/`: deterministic path-based tiers (`blast/propagation/safe`, PR = max, fail-safe default), `tools/pr-brief.py` as the gate on every PR, a versioned PR lifecycle. `tools/**` `scripts/**` `.github/**` `.steve/**` in `propagation` (the gate cannot tamper with itself cheaply).

## Consequences

Not recorded when the decision was taken.

## Alternatives considered

Not recorded when the decision was taken.
