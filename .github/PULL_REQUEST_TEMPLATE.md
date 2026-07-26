# Pull Request

## What

<!-- What this PR does. One or two sentences. -->

## Why

<!-- Motivation. The problem or need this addresses. -->

## Review tier

<!-- State one: safe / propagation / blast.
     The tier is derived from the paths touched, by tools/pr-brief.py,
     with the max tier winning. See .steve/review-policy.yaml. -->

- [ ] safe
- [ ] propagation
- [ ] blast

## Verification

<!-- Commands run, with their real output (stdout and exit codes).
     Do not paste what would have run; paste what did run. -->

```

```

## Checklist

- [ ] Privacy: `scripts/check_privacy.sh` run on the changed files, no denylist hits.
- [ ] The Verification block above is real output from this worktree, not what would have run.
- [ ] CI was queried once after the push; its state at that moment is stated above.
      (Green CI is enforced by the merge gate, condition (c) — not attested here.)
- [ ] No secrets or deployment-specific identifiers committed.
