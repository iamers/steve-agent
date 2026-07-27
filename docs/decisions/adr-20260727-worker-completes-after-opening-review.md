---
status: accepted
date: 2026-07-27
---

# A worker completes after opening its review

## Context

A worker opened its pull request, created an independent review task, and then
blocked its own task with `review-required`. The coordinator had previously
closed that task while creating the review by hand. Once review creation moved
to the worker, no component remained responsible for closing the blocked task.
The `active_pr` guard only recognizes recent task comments; it does not inspect
GitHub or determine whether a pull request has merged. Several otherwise
finished worker tasks therefore required manual closure.

## Decision

A worker completes its task with `kanban_complete` after it has implemented the
brief, opened the pull request, and created the independent review task. The
completion carries the changed files, executed verification, and pull request
metadata. The review task remains a sibling with no parent link and retains the
originating task id in its body. Review, requested changes, and merge handling
continue in the review task and on GitHub.

## Consequences

The worker lifecycle has a deterministic end and no coordinator action is
needed to close an implementation task. An independent review can be dispatched
immediately, while a later fix task may depend on an originating task that is
already `done`. Historical worker tasks parked with `review-required` may still
need manual closure, but new tasks do not enter that state.

## Alternatives considered

Keeping the worker blocked until review or merge: rejected, because no current
component can close that task and `active_pr` is not a GitHub state observer.
Making the review task a child of the worker: rejected, because the child would
remain in `todo` until its parent completed. Restoring coordinator-created
reviews: rejected, because it duplicates the worker's established review-task
creation and reintroduces a manual lifecycle step.
