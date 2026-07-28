---
status: accepted
date: 2026-07-27
---

# Human review is requested, not required

## Context

A human contributor found that a check in the smoke suite ended with `|| true` and
had therefore never been able to fail. It had been reporting a pass for weeks. No
automated guard and no agent review had seen it; a person reading the script did.
That is concrete evidence that human review adds something the pipeline does not.

## Decision

The orchestrator requests the human reviewer configured in
`STEVE_HUMAN_REVIEWER` on `blast` pull requests, and on `propagation` pull
requests that change a guard, using:

```sh
gh api repos/<owner>/<repo>/pulls/<n>/requested_reviewers -X POST -f 'reviewers[]=<login>'
```

Here, `<login>` is the value of `STEVE_HUMAN_REVIEWER`. This REST API call
requests a pull request reviewer directly, without relying on the deprecated
classic Projects GraphQL fields queried by `gh pr edit`. When the key is unset,
no human review is requested and nothing blocks. This is a convention, not
enforcement: the absence of a human response never blocks a pull request.

## Consequences

No change to the branch ruleset, so the `safe` automatic merge path is untouched.
The value depends on people actually responding, and nothing degrades if they do
not.

## Alternatives considered

Raising the required approving review count to two: rejected, because the ruleset
is per-branch and knows nothing about tiers, so it would also stop the `safe`
automatic merge that phase 2 exists for. Doing nothing: rejected, because the
evidence for the value is concrete and recent.
