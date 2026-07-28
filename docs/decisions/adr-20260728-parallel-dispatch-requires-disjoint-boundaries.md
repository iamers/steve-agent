# Parallel dispatch requires disjoint boundaries

## Context

The factory skill instructs the orchestrator to dispatch batches of independent tasks in
parallel, and asserts that their pull requests cannot conflict because each worker works on
different files. That assertion is written as a fact and verified by nobody. On 2026-07-28
three pull requests touched one script and two touched another; one died of a conflict, and
the order in which the rest could be merged had to be reconstructed by hand from GitHub's
file lists by whoever was merging.

Every brief already declares the exact set of files its task may touch.

## Decision

Two tasks whose declared boundaries intersect are not dispatched in parallel. They are
chained with `--parent`, which serialises them through the promotion that already exists. The
check is deterministic, runs before dispatch, and compares the candidate boundaries both
against the other tasks in the batch and against the files of the pull requests already open.

## Consequences

A batch is either provably conflict-free or explicitly serialised, and merge order follows
from the dependency chain instead of from someone's reading of a file list. The check needs
boundaries to be machine-readable, which constrains how the Boundaries section of a brief is
written. Serialised tasks are slower than parallel ones; that cost is accepted, because a
collision costs a rebase plus a re-review.

## Alternatives considered

Resolving conflicts at merge time: rejected, that is the current behaviour and it moves the
ordering problem onto whoever merges, at the moment they have the least context.

Forbidding parallel dispatch altogether: rejected. The parallelism is real and worked for
nine of the eleven pull requests merged that day.

Trusting the orchestrator to notice: rejected. It did notice, three times, by hand, and three
pull requests still collided on the same file.
