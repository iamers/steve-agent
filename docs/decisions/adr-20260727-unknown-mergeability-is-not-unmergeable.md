---
status: accepted
date: 2026-07-27
---

# Unknown mergeability does not make a pull request unmergeable

## Context

GitHub calculates a pull request's mergeability asynchronously. The first read
can therefore return `null`, while a subsequent read returns the calculated
value. The gate converted that `null` into an empty string and reported it as
an unmergeable pull request. The rejection was prudent, but the reason
communicated in chat was false.

## Decision

When the first metadata read returns unknown mergeability, the gate waits for a
short, fixed pause, then repeats the same request once. This follows GitHub's
documented remedy for asynchronous calculation and removes the transient state
in the ordinary case.

If the second response also does not contain a value, the gate preserves the
unknown state as a distinct third state. The gate still rejects the pull
request, but states that mergeability is not yet known instead of stating that
the pull request is unmergeable.

## Consequences

In the ordinary case, the gate uses the value available on the second read. The
evaluation adds at most one request and one fixed pause, without loops. If
GitHub has not yet finished the calculation, the behavior remains fail-closed
and the message accurately describes the uncertainty.

## Alternatives considered

Do not repeat the request: rejected because it would preserve a transient state
that GitHub says to resolve with another read. Repeat in a loop: rejected
because it offers no fixed limit on either the wait or the number of requests.
Treat the unknown state as unmergeable: rejected because it produces a false
reason. Allow the merge when the state is unknown: rejected because it would
violate the fail-closed principle.
