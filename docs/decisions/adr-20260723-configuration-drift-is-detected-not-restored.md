---
status: accepted
date: 2026-07-23
---

# Configuration drift is detected but not restored

## Context

Not recorded when the decision was taken.

First recorded in the repository on 2026-07-23 (commit 7a3ffc5). The decision may have
been taken earlier; the original date is not recorded.

## Decision

Anti-drift and health: config-as-code in `instance/` (config plus profiles plus skill plus env.template), `drift-check.sh` that flags and does not restore, `smoke.sh` with 10 checks and main-guard v2, CI (`checks`: brief self-test, `bash -n`, shellcheck, gitleaks), a privacy guard (denylist plus pre-commit plus `check_privacy.sh`), and an append-only ops journal.

## Consequences

Not recorded when the decision was taken.

## Alternatives considered

Not recorded when the decision was taken.
