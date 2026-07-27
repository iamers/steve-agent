---
status: accepted
date: 2026-07-27
---

# The gate refuses a stale branch

## Context

The branch ruleset does not require a branch to be current before merging. For
tiers merged by a person that is acceptable, because a person is reading the
result. The `safe` tier is merged by the App with nobody watching, on the
strength of a CI run against a head that `main` may have moved past. The tier is
entirely prose, and prose merges cleanly into contradictions rather than into
conflicts, so git reports success in exactly the case that matters.

## Decision

The gate requires the pull request head to contain the current `main`, as a
sixth condition evaluated with the other five. If the branch is behind, or if
that cannot be determined, the gate refuses.

## Consequences

A `safe` pull request left open while `main` advances must be updated before it
merges, and its author sees a distinct reason rather than silence. The branch
ruleset does not change, so the tiers a human merges are unaffected.

## Alternatives considered

Enabling the strict policy in the ruleset: rejected, because the ruleset is
per-branch and knows nothing about tiers, so it would force a rebase on every
`propagation` and `blast` pull request that a person is already reading, to
protect a case that only arises where nobody is. Doing nothing: rejected,
because the case is real and it falls precisely where no human is looking.
