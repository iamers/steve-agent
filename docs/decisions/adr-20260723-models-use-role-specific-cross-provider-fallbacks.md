---
status: accepted
date: 2026-07-23
---

# Models are assigned per role with cross-provider fallbacks

## Context

Not recorded when the decision was taken.

First recorded in the repository on 2026-07-23 (commit 8428b63). The decision may have
been taken earlier; the original date is not recorded.

## Decision

LLM: model-agnostic, assigned **per role**. Each role is already a separate Hermes profile with its own config, so worker, reviewer, and orchestrator take independent models with no extra machinery. A fallback chain is expected, and its links must sit on different providers with at least one that cannot exhaust a quota (§8.9). Running the reviewer on a different model family from the worker (so the same model does not both write and judge) is desirable; it is a per-instance choice, and an instance may knowingly trade it for judgement quality. Where a provider offers both an HTTP path and a CLI-subprocess runtime, prefer HTTP: the subprocess runtime forfeits the fallback chain (§8.9).

## Consequences

Not recorded when the decision was taken.

## Alternatives considered

Not recorded when the decision was taken.
