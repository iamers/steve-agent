---
status: accepted
date: 2026-07-28
---

# Authorization covers the batch, not the pull request

## Context

Fifteen pull requests were open at once, thirteen produced by the factory from ten backlog
cards. The human owner was asked to merge them without knowing their order or their file
dependencies. Eleven were merged in an order derived from shared files rather than from
numbering.

The decisive case was a pull request that was approved, green and mergeable and still should
not be merged: it contradicted a decision taken an hour earlier, and it moved the pinned
runtime in the blueprint without upgrading the instance, which would have turned a guard
red. That is a property of the plan, not of the pull request, and no per-pull-request gate
can detect it.

At the same time the deterministic gate, whose conditions are stricter than a human merge
(approval label, an approving review from a different identity, green CI, tier, base branch,
unchanged head since the approval, and branch not behind main), is limited to the `safe`
tier and so does not apply to the pull requests that pile up.

## Decision

Human authorization applies to a **batch of briefs at dispatch time**, not to each pull
request at merge time. Once a batch is authorized, its pull requests are merged mechanically
by the deterministic gate as they become eligible, in an order that follows from their file
dependencies. Over a running batch the human keeps one power: stopping it.

## Consequences

The decision moves to the point where it carries information, which is when the briefs are
written and the order and dependencies are visible. Reviewer approval and every gate
condition are unchanged and still apply per pull request. A pull request that must not be
merged for a reason outside itself is now prevented by withholding authorization or by
stopping the batch, rather than by declining a merge.

The gate must be extended beyond the `safe` tier for authorized batches. That is a change to
condition (d), and it needs its own record, its own guard and its own self-test before it is
made. Until then this decision is recorded and not yet in force.

## Alternatives considered

Keeping the per-pull-request human merge: rejected, because it produced the situation this
record describes. With fifteen pull requests the human act carries almost no information,
and the one judgement that mattered was about the plan rather than about any pull request.

Raising the required approving review count: rejected for the same reason given in
`adr-20260727-human-review-is-requested-not-required.md`. The ruleset is per branch and
knows nothing about tiers, so it would also stop the automatic `safe` path.

Merging automatically with no human authorization at all: rejected. The factory would then
have no point at which a person can refuse the work, and the case above shows that point is
needed.
