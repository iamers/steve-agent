{{0}}
{{1}}
{{2}}
{{3}}

{{4}}

## Triage
{{5}}
{{6}}
Critical files:
{{7}}

## What changes
{{8}}

## Non-obvious decisions
- <technical decision + reason>

## Operational rules

Read `task_rules` in `.steve/review-policy.yaml` before starting. They are
constraints, not suggestions: each one has already killed at least one task.
The two that bite most often are no `rm` in any form inside a verify, and the
published review body carrying no instance paths, aliases or identities.

## Verification
- [ ] CI green
- [ ] <tier-specific criterion, e.g. "config loads in dry-run without errors">

---
{{9}}
