---
status: accepted
date: 2026-07-28
---

# Session checkpoint pilot is deferred

## Context

A pilot for session checkpoints in `steve-worker` was considered. The worker
cycle was recently simplified, and checkpoints would add state to that cycle.
There is no observed failure, recovery gap, or other concrete problem that
currently justifies the additional mechanism.

## Decision

Do not implement session checkpoints for `steve-worker` now. Record the pilot
as deferred rather than adding a checkpoint mechanism or its supporting state.
Revisit this decision only when concrete evidence shows a problem that
checkpoints would solve.

## Consequences

The simplified cycle remains the product baseline. There is no new state to
create, persist, restore, or maintain. A future proposal must bring observed
evidence and show why a checkpoint is the smallest effective response.

## Alternatives considered

Implementing the pilot now: rejected, because it adds state without an observed
problem to justify its cost. Keeping the idea unrecorded: rejected, because it
would allow deferred scope to return as if no decision had been made.
