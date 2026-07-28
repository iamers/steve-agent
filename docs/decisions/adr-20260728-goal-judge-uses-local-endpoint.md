---
status: accepted
date: 2026-07-28
---

# The goal judge uses the local endpoint

## Context

Goal-mode tasks ask an auxiliary judge whether a card's goal has been met before the card can
close. Both coding profiles routed that judge to Gemini, while the base configuration routed
other high-volume auxiliary work to the local endpoint.

On 2026-07-28 a reviewer published an approving GitHub review and read it back as approved,
but its card did not close. Three completion attempts failed with `GeminiAPIError`. The work
was finished and published; the external provider failure affected only the goal judge and
therefore prevented the completed card from closing.

## Decision

Route `auxiliary.goal_judge` to the `lab-gpu` provider with the
`qwen36-35b-a3b-fp8` model in both the worker and reviewer profiles. This matches the local
provider and model already used for other auxiliary tasks in the base configuration.

## Consequences

A quota wall or outage at an external provider no longer prevents the goal judge from deciding
whether a worker or reviewer card can close. Goal-mode completion now depends on the local
endpoint being available instead.

This is a different failure mode, not a smaller one. If the local endpoint is down, the judge
cannot answer and cards will again fail to close.

## Alternatives considered

Keeping Gemini for the goal judge: rejected because the observed provider failure prevented a
completed and published review task from closing, and made every goal-mode completion depend
on the same external free tier.

Removing the goal judge from goal-mode completion: rejected because this change is routing an
existing control, not weakening or redesigning that control.

Falling back from Gemini to the local endpoint only after an error: rejected because the base
configuration already establishes the local endpoint for auxiliary work, and a fallback would
retain an unnecessary external dependency on the completion path.
