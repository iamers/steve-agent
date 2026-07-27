# PR Lifecycle v1, review process

This document defines how a pull request is born, evaluated, and reaches
`main` in the steve-agent repo. It executes the board brief `t_9c2689f2`
("PR Lifecycle v1"). The process relies on a single new tool, the brief
compiler (`tools/pr-brief.py`), and keeps the whole flow in this one
document: no second tool, no temporary scratch files in git.

## The four founding decisions

The founding decisions now live in [`docs/decisions/`](../docs/decisions/), one
file per decision, with each decision's current status recorded in its front
matter.

## The end-to-end flow

The brief verification criterion admits two paths.

### Happy path (approval)

1. A PR is opened.
2. The compiler (`tools/pr-brief.py`) computes the tier of every modified
   file against `.steve/review-policy.yaml` and produces the brief: the PR's
   tier is the max across its files (`blast > propagation > safe`).
3. The brief is delivered to the Backlog topic (today via the watcher
   `instance/pr-watch.sh` on cron).
4. A reviewer responds `approve` (or `approve with: <note>`).
5. For `safe`, the label lets the scanner invoke the merge gate; for
   `propagation` and `blast`, a human merges on GitHub.

### Iterate path (try again)

1. The reviewer responds `reject: <reason>`.
2. The compiler generates the **redesign draft**: a markdown comment on the
   PR that lists the violated constraints and what to change. No temporary
   file is written in git: the draft lives only as a PR comment.
3. The author fixes and repushes the PR (or forces a new compiler run).
4. The flow returns to the happy path or to a new iterate round.

In both paths the brief stays the central artifact: it is what concentrates
the decision, not the reviewer's free judgment.

## Implementation status (honest)

| Component | Today | To build |
|---|---|---|
| Brief compiler (`tools/pr-brief.py`) | exists: deterministic triage, template, `--self-test`, origin task id, "read first" section, minimal D4 gate | also generate the redesign draft on reject |
| PR watcher (`instance/pr-watch.sh`) | exists: runs on cron, detects new PRs | event trigger (webhook) instead of cron |
| Brief delivery | in the Backlog topic via cron | push delivery on event |
| CI (`.github/workflows/ci.yml`) | exists: `checks` job, 4 steps (runs on every PR) | brief validation step extension |
| Approval | tracked by the approval label plus an `APPROVED` review on the latest commit | tracked approve command |
| Auto-merge | exists for `safe`: the scanner invokes the deterministic gate, and the dedicated GitHub App merges when every condition passes | activation without an approve in chat (backlog, see phase 2) |
| "Constraints without test" check (D4) | exists: minimal D4 gate in the compiler (a constraint on review-policy with no test -> tier escalates to propagation plus human signature) | coverage of constraints beyond review-policy |

For `safe`, an approve can lead to a deterministic merge by the GitHub App;
for `propagation` and `blast`, the merge remains a human action on GitHub.

## Phase 2, safe auto-merge (as built)

Phase 2 takes approval from "decide" to "execute autonomously" while keeping
traceability and the guard on `main`. The implementation rests on two
independent gates, a deterministic merge script, and a dedicated merge
identity.

### Two independent gates: eligibility and authorization

Auto-merge is governed by two gates that do not depend on each other:

- **Eligibility (deterministic, path matching, no LLM).** Only the `safe`
  tier is a candidate for automatic merge. The `propagation` and `blast`
  tiers remain ALWAYS human merge, because their policy requires a
  human-signed brief (see `rules.brief_required_for` in
  `.steve/review-policy.yaml`).
- **Authorization.** The admin gives the approve in chat for EVERY merge,
  and Steve applies a label plus a comment on the PR that references the
  decision. The automation removes the mechanical work, NOT the decision.
  Auto-merge without an approve in chat is declared backlog, to be
  activated only after the gate has proven itself on real PRs.

### The gate

The gate is a deterministic script WITHOUT an LLM. Before evaluating any PR
condition, it fetches `origin/main` and refuses to decide if freshness cannot
be determined or if its local policy copy is behind. It then merges only if
ALL of the following are true:

- (a) the approval label is present on the PR;
- (b) there is a review in APPROVED state from the reviewer identity on the
  latest commit;
- (c) CI is green on the latest commit;
- (d) the PR tier is `safe`, recomputed locally by path matching, not
  trusted from the PR body;
- (e) base is `main`, the PR is mergeable, and no push happened after the
  approve, verified by comparing the head SHA recorded when the label was
  applied against the current head.

Point (e) stays necessary even now. The repo has
`dismiss_stale_reviews_on_push` active, so a push invalidates the REVIEW but
does NOT invalidate the LABEL. The SHA comparison is what protects the
label: if the head moved after the approve, the gate refuses.

### Merge identity

The merge identity is a GitHub App, and a key design decision is that each
instance owns its own App rather than sharing one centrally.

- **Per-instance, not shared.** The App is owned by the same org that owns
  the repo and is installed ONLY on that repo. Each instance of Steve has
  its own App. It is NOT a centrally shared App.
- **The technical reason (counterintuitive).** The private key of a GitHub
  App lives at the APP level, not the installation level. Whoever holds the
  key can list all installations of that App and generate tokens for ANY of
  them. A shared App with a distributed key would let one adopter of Steve
  merge into every other adopter's repos. This is why each adopter creates
  its own App.
- **No bypass privilege.** The App does NOT receive any bypass privilege.
  It merges by passing through the same rules as everyone else: a PR is
  required, an approved review from a different account is required, and CI
  is green. A merge-bot that cannot override anything is safer than one
  with an exception.

### App creation and operational permissions

App creation, installation steps, and the required permissions are documented
in `instance/INSTALL.md`, written against the real App. See that file for the
per-instance setup. Each instance creates its OWN App and the private key is
never shared, for the technical reason above.

## Phase 2 as built

`instance/merge-gate-scan.sh` finds open PRs carrying the approval label and
invokes `instance/merge-gate.sh`. The gate evaluates the precondition and the
five conditions above, then uses the per-instance GitHub App to merge only an
eligible PR.
