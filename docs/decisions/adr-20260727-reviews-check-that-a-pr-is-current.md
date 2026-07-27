---
status: accepted
date: 2026-07-27
---

# Reviews check that a pull request is current

## Context

A review of an external pull request confirmed its substance in detail and never
noticed the branch was fifteen commits behind `main`, and that two of the files it
changed had been rewritten on `main` in that window. GitHub reported it mergeable,
and it was: git can merge two texts cleanly and produce a document that contradicts
itself. No review brief in this project has ever asked the question. The merge gate
was taught the same lesson earlier and refuses to decide when its own copy of the
policy is behind `origin/main`; the reviewer was never taught it.

## Decision

Every review brief requires the reviewer to report how far behind `main` the branch
is, and whether any file the pull request touches was changed on `main` since the
branch left it. A stale branch is a finding to state, not a blocker by itself: the
reviewer reports it and the decision to rebase stays with the author and the
maintainer.

## Consequences

One more mandatory question in every review. Staleness stops being something the
coordinator remembers and becomes something the review records. This is symmetric
with the gate, which already refuses on a stale policy copy.

## Alternatives considered

Only for pull requests with no originating task: rejected, because our own pull
requests also stay open for hours and the risk is the same. Leaving it to the
coordinator at merge time: rejected, because it is exactly the class of remembered
step this project has spent the week removing.
