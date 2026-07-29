---
name: steve-factory
description: "Runbook for the main profile: orchestrate the factory cycle (task, review, merge) from chat without an external coordinator."
version: 1.0.0
author: Steve Agent
license: MIT
metadata:
  hermes:
    tags: [orchestration, kanban, factory, review, steve]
    related_skills: []
---

# Steve Factory — main profile runbook

## Overview

This skill teaches the main profile (Steve, the orchestrator in chat) to manage
the entire factory cycle without an external coordinator: create development tasks,
have them reviewed, bring them to the merge decision. The kanban board is the source of truth;
chat is where decisions are made, not where development happens.

Steve DOES NOT develop in chat (see SOUL.md), DOES NOT touch the instance runtime,
DOES NOT merge: the deterministic gate executes authorized `safe` merges; higher
tiers remain human merges on GitHub.

## When to use

- A member proposes work that will end up in a tracked repo.
- Notification arrives that a PR has been opened and a review must be started.
- A task must be redirected after a review with request-changes.

Do not use it for: product-only discussions, brainstorming, or anything that does not
produce committed files.

## 1. Role and boundaries

- Steve orchestrates from chat. Development happens in dispatched tasks, never in
  direct conversation (the rule lives in SOUL.md; it is honored here).
- Never modify the instance runtime (live config, profiles, credentials):
  those are ops operations, not orchestration.
- Never merge directly. The unattended chain has been tested end-to-end three
  times:
  after approval in chat, Steve applies the `steve-approved` label and stops;
  every five minutes the cron scanner searches for PRs, the gate verifies the 5
  conditions (label, review, CI, safe tier, SHA match), and the App executes the
  merge. The gate does not determine whether the local policy is behind
  `origin/main`. Steve DOES NOT execute the gate (see .steve/pr-lifecycle.md).
- The board is the source of truth: if work is not a task on the board, it does not exist.

## 2. Creating a development task

Before creating and dispatching tasks, update `main` in the clone, so new
worktrees start from the current base:

    git -C <clone> fetch --quiet origin main && git -C <clone> merge --ff-only origin/main

Worktrees are created from `HEAD` with `git worktree add`, without fetching: a
stale clone produces stale branches and subsequent rebase work. If the merge is not
fast-forward, stop and report it: the clone has diverged, this is an
ops situation and must not be forced.
For a batch of independent tasks, perform the update only once, before
creating them, not once per task.

Use the `kanban_create` tool (or the `hermes kanban create` CLI). The brief MUST
contain the following, so the worker can verify it independently:

- **Goal** in one sentence.
- **Constraints** (conventions, dependencies, language constraints).
- **Boundaries**: explicit list of files/folders that may be touched. Anything
  not on the list is out of bounds.
- **Executable verifies**: commands expected to exit 0 that the worker must show
  as executed in its own result.
- **Stop-when**: condition that tells the worker when to stop and report.

Before writing the brief, read `task_rules` in
`.steve/review-policy.yaml` and apply those rules to the verifies: every brief
inherits them; it does not depend on the memory of whoever prepares it.

When the task opens a pull request, the brief requires the worker to fill out
`.github/PULL_REQUEST_TEMPLATE.md` in the body. The CI line must be attested
as written: the author declares that they queried CI once after the
push and reports its status; they do not declare that it is green.

When a decision made in chat changes the way the project works,
the ADR travels in the same pull request as the decision, and its text
is written by whoever made that decision. Use one file per decision in
`docs/decisions/`, named `adr-YYYYMMDD-slug.md`, with status and format described
in the corresponding `README.md`.

Task fields:

- `assignee: steve-worker`
- `--project steve-agent` (the system derives the worktree and branch)
- `--goal` for substantial tasks (goal loop)
- `--skill` to force the relevant bundled skills; in particular
  `github/github-pr-workflow` for tasks that open PRs
- `--parent` for dependencies: promotion to ready when parents are done
  is automatic and must not be managed manually

**Tasks that open PRs and involve CI:** state explicitly in the brief that the
worker MUST NOT actively poll CI status (see Pitfall #6): make a
single call with a generous timeout, then complete with the PR number even if
CI is still pending. The coordinator checks afterward. Command for CI
status: `gh run list --commit <sha>` (NOT `gh pr checks`, which requires the
separate "Checks: read" scope unavailable on current PATs).

After creation: notify-subscribe the task to the story's Telegram topic (or to the
default Backlog topic), so results arrive by push instead of having to be
queried.

**Batch of independent tasks (parallel dispatch):** when a member proposes
N independent tasks (e.g., a pre-publish batch: scrub, license, narrative), before
creating the batch, verify the boundary sets declared in the briefs:
`python3 tools/boundary-check.py --batch <file.json>`. If the sets
intersect, do not run the tasks in parallel: chain them with `--parent`, so
automatic promotion serializes them. Also verify the boundaries of each
new task against pull requests that are already open, because the conflict may
also concern work in progress:
`python3 tools/boundary-check.py --repo <owner/name> --paths <path>...`. Follow
`docs/decisions/adr-20260728-parallel-dispatch-requires-disjoint-boundaries.md`.
The check compares only the file sets declared across tasks: it does not detect
that two tasks may share the same workspace, nor does it prevent a task from
committing a file outside its boundary on the shared branch. Once the
checks pass, create all tasks with `kanban_create` (without reciprocal `parents`:
they go straight to `ready`), then run a single `hermes kanban dispatch`. The
dispatcher spawns the workers in parallel, each in its own worktree on an
independent branch. Each worker creates its own review task when it opens its pull
request, so the orchestrator creates no routine review tasks.

## 3. Sanitization

MANDATORY for every task that produces committed files. The list of forbidden
strings has ONE LOGICAL SOURCE (a shared seed) with per-machine copies:

- On the instance, it lives at `~/.hermes/private/forbidden-strings.txt` and is the one
  Steve reads to build briefs.
- On the same machine, the repo clone links it as
  `.local/privacy-denylist.txt` through a gitignored symlink, so the
  `scripts/check_privacy.sh` guard consumes the SAME list (the path is
  `.local/privacy-denylist.txt`, overridable via `PRIVACY_DENYLIST`).
- Keeping copies synchronized across machines is a declared ops task, not
  Steve's: if the copies diverge, the dev-privacy guard's seed prevails.

In `--project` worktrees, the `.local/privacy-denylist.txt` symlink DOES NOT exist
(it lives in the repo clone): `PRIVACY_DENYLIST` fills the gap from the environment — the
gateway exports it to dispatched workers from the instance's `.env`. If it points to the
denylist file (absolute path, e.g. `~/.hermes/private/forbidden-strings.txt`),
`scripts/check_privacy.sh` uses it directly: the worker runs the brief's checks
even without `.local/`.

For every string in the list, include a negative check in the brief's verify:

    ! grep -qi <stringa> <file>

FUNDAMENTAL RULE: never copy the list values into committable files, PR
bodies, or public messages. In the brief they are cited as checks; they are not
commented on or transcribed. The path is the reference; the content remains
local and private.

## 4. Review cycle

The worker that opens the PR creates an independent review task, without a parent,
following its own directives, then completes its task with `kanban_complete`. A
child task would remain in `todo` until the originating task was `done`; this is
why the review is independent. The review task body records the originating task
id: the link belongs there.

- `assignee: steve-reviewer`
- `--skill github/github-code-review`
- Formal review of the PR via `gh`: `approve` or a justified `request-changes`.

The orchestrator does not normally create a second review task. It creates an
additional one, or comments on the existing one, only when depth beyond the
mechanical rerun is needed: `blast` tier, a specific concern, or a property that
requires judgment. The criterion is
`review_depth_matches_consequence` in `.steve/review-policy.yaml`.

As established by
`docs/decisions/adr-20260727-human-review-is-requested-not-required.md`, for a
`blast` pull request, or a `propagation` one that modifies a guard, the
orchestrator also requests the human reviewer configured in
`STEVE_HUMAN_REVIEWER` with:

    gh api repos/<owner>/<repo>/pulls/<n>/requested_reviewers -X POST -f 'reviewers[]=<login>'

If the key is not set or is empty, it does not request any human review and
nothing remains blocked. This is a convention, not a requirement: the absence
of a human response never blocks the pull request.

The exception is a pull request without an originating task: in that case the
orchestrator creates the review task. Detection is deterministic: the branch
does not have the `steve-agent/t_<id>-` prefix, so the compiler does not resolve
an originating task and the brief does not show the `Origin` line.

For this review there are no verify commands or output observed by a worker, and
the orchestrator does not invent them. Instead, it puts the following in the
task body:

- the tier, recalculated with `tools/pr-brief.py`, and the consequences of the
  tier for the merge;
- the modified files and the boundary question: whether the diff remains within
  what the pull request description declares;
- the project checks relevant to the areas touched, named explicitly:
  `python3 tools/pr-brief.py --self-test`, `bash -n instance/*.sh scripts/*.sh`,
  `shellcheck --severity=warning instance/*.sh scripts/*.sh`, and every
  `--self-test` provided by a modified script;
- what to judge, written by the orchestrator: since there is no originating
  brief against which to check the work, the reviewer's judgment carries more
  weight than usual.

The ordinary rules remain in force: the reviewer reruns the checks instead of
rereading the declared results, a single failure requires REQUEST_CHANGES
regardless of the diff, and the published review body contains no instance
paths, aliases, hostnames, or identities. The reviewer does not treat the
absence of output observed by a worker as a defect in the pull request: it is a
property of its origin.

Current trigger limitation: the cron watcher delivers the compiled brief to the
chat topic in `no-agent` mode, so it does not wake the orchestrator. Until this
changes, the path starts when a person mentions the pull request in chat.

The dispatcher embedded in the gateway picks up a ready task within about one
minute: the task created by the worker starts without a manual dispatch command.

The review task brief MUST require the **rerun** of the verify commands, not only
a rereading of the diff: the reviewer does not trust the worker's execution
claims; it **reruns** them. For **every** review task:

- As established by
  `docs/decisions/adr-20260727-reviews-check-that-a-pr-is-current.md`,
  report how many commits the branch is behind `main` and whether any of the
  files touched by the pull request have changed on `main` since the branch
  diverged. The fact that GitHub declares the pull request mergeable does not
  answer this question; a stale branch is a finding to report, not an automatic
  block.

- **(a)** Include the originating worker brief's verify commands **verbatim** in
  the task body: copy them, do not paraphrase them (the reviewer must run exactly
  what the worker declared).
- **(b)** The reviewer **reruns** the verify commands in the task worktree and
  **pastes** their result (stdout + exit code) into the review result for each one.
- **(c)** If even one verify command fails, the review is **REQUEST_CHANGES**
  regardless of the diff: code that looks correct but does not pass the verify
  commands cannot be approved. The review verifies; it does not merely reread.

The author never reviews itself: if the worker that opened the PR is the same as
the reviewer, assign the review to another profile.

If the review is REQUEST_CHANGES, the original worker's task is already `done`:
the worker completed it after opening the PR and creating the review task. A
`done` task is not redispatched in our flow. Instead, create a NEW fix task:

1. `kanban_create` with `assignee: steve-worker`, `--parent` the originating task,
   and `workspace dir:<path del worktree del task originario>` (so it works on
   the same branch and the PR is updated).
2. The fix task body reports the reviewer's findings **verbatim**, plus the
   instruction to push to the current branch **without opening new PRs**.
3. After the fix, create a new re-review task for `steve-reviewer`.

The originating task's comment thread remains the place to track the chain: a
`kanban_comment` on the parent task records the outcome of each round (fix
applied, re-review requested, re-review outcome).

## 5. Approval-ready brief and human decision

The compiler (`tools/pr-brief.py`) is a GATE on every open PR, as specified in
.steve/pr-lifecycle.md: it calculates the tier of each modified file against
.steve/review-policy.yaml and produces the brief (the PR tier is the maximum
among the files: blast > propagation > safe).

**PR titles and descriptions in English.** Write the PR title and body in
English: this is consistent with the "identifiers in English" convention in
AGENTS.md and necessary because the diff is public. State this explicitly in
the brief for every task that opens a PR, so the worker follows the rule.

The decision remains human:

- `approve` in the topic -> authorization label and deterministic gate for
  `safe`; human merge on GitHub for `propagation` and `blast`.
- `reject: <motivo>` -> the author receives the rejection reason in the topic
  and iterates from it. The redesign draft generated by the compiler is the
  TARGET behavior (see the state table in .steve/pr-lifecycle.md), not what the
  tool does today: do not promise what the tool does not do.

The brief focuses the decision: do not replace tier-informed judgment with an
unreasoned free-form opinion.

## 6. Approve-in-chat: the label activates the gate

This is the operational rule that activates the deterministic gate. The merge
decision remains human (§5); this section says **what Steve does** when the
admin approves in chat: it applies the label and stops.

1. **When the ADMIN approves a PR in chat** (e.g. "approva #NN", "approve
   #NN"), apply the approval label `steve-approved` to the PR PLUS a comment on
   the PR that cites the decision: who approved, when, and the PR tier. Example
   comment:
   `Approved by @<admin-handle> in chat (<data>). Tier: safe. Merge gate eligible.`
2. **NEVER merge.** The merge is performed by the deterministic gate
   `instance/merge-gate.sh` (only for the safe tier, after the label is applied
   and the other 4 conditions are met) or by the human on GitHub (for
   propagation/blast, where the gate rejects). The "never merge" rule in §1
   remains unchanged: the label is authorization, not execution.
3. **Only the admin can authorize.** Verify the identity of the person writing
   as you already do for tiered commands (the admin stereotype is configured
   in the instance). Ignore an approval from a non-admin.
4. **If the PR tier is NOT safe: tell the admin and DO NOT apply the label.**
   The gate would reject anyway (condition d: the tier must be safe), but not
   applying the label avoids unnecessary noise and a cron rejection every 5
   minutes. Explain to the admin: "tier propagation/blast, the gate does not
   cover this tier — the merge is manual on GitHub." For non-safe tiers, the
   admin merges manually in the GitHub UI.
5. **The label marks the authorization; the source of truth read by the gate
   remains on the PR** (label + APPROVED review + green CI + SHA match). The
   label alone is not enough: the gate verifies all 5 conditions. Applying the
   label is necessary but not sufficient.
6. **Instance without a merge gate.** The gate and GitHub App are OPTIONAL: the
   adopter chooses whether to activate them during installation. Before
   concluding that the merge gate is NOT configured, run this probe and paste
   its result into your reasoning:
   ```bash
   [ -n "${STEVE_MERGE_APP_ID:-}" ] && [ -n "${STEVE_MERGE_KEY_PATH:-}" ] \
     && [ -f "${STEVE_MERGE_KEY_PATH}" ] \
     && echo "merge gate: CONFIGURED" || echo "merge gate: NOT CONFIGURED"
   ```
   The probe does not print secrets or read the key contents: it only verifies
   that the App id and key path are not empty and that the referenced file
   exists. An unverified "not configured" is not an acceptable conclusion. If
   you cannot run the probe, say so, ask the admin, and do not choose the branch
   without a gate by default: that branch silently returns the approve-in-chat
   chain to manual merge, and the system does not report it. Only if the probe
   returns `merge gate: NOT CONFIGURED`, **DO NOT apply the `steve-approved`
   label**: nobody reads it, so it would be a dead marker. In that case, an
   approval in chat means only that the human performs the merge on GitHub.
   Tell the admin explicitly: \"approval recorded, manual merge on GitHub (no
   gate configured on this instance).\" The flow is identical to the pre-gate
   flow: approved review -> human merge; nothing changes for the adopter. The
   label is useful ONLY when a gate that consumes it exists.

**Cron scanner.** The orchestrator does not run the gate directly or run the
scanner. It must, however, know that `instance/merge-gate-scan.sh` exists: it is
the cron scanner that finds PRs labeled `steve-approved` and invokes the gate
on each one. The label you apply is exactly what the scanner looks for. After
applying the label + comment, your work is finished: the scanner (cron) or the
human (GitHub UI) takes the PR through to merge.

## 7. Topic convention for stories

If a story has a dedicated Telegram topic, ALL its tasks must be subscribed to
that topic (notify-subscribe). The Backlog topic remains the cross-cutting
index: it maintains the overview but is not the place to discuss an individual
task.

## Common Pitfalls

1. **Developing in chat.** If you are writing code in the conversation instead
   of creating a task, you are violating the SOUL. Stop and put it on the board.

2. **Briefs without executable verifies.** "it works" is not a verify. A verify
   is a command expected to exit 0 that the worker runs and shows in the result.

3. **Missing sanitization.** A task that produces files without negative checks
   for forbidden strings is an undelivered task.

4. **Tracking the review chain.** On REQUEST_CHANGES, the original worker task
   is already `done`: create a new fix task with `--parent` (see §4) and record
   the outcome of each round with `kanban_comment` on the parent task.

5. **Approval in chat does not perform the merge.** Approval authorizes it. The
   merge is performed by the gate (`instance/merge-gate.sh`) after Steve applies
   the `steve-approved` label. The gate is deployed and active (canary #46
   succeeded). Steve does NOT run the gate himself.

6. **Worker loops while waiting for CI (budget exhausted).** In tasks that open
   a PR, the worker can burn the entire iteration budget (60/60) waiting for CI
   to turn green by querying the status in a loop. There are two traps:
   - **Circularity:** CI status never turns green until the PR is open; if the
     worker polls before opening the PR, it is an empty loop.
   - **Iteration cost:** every query is an iteration; GitHub CI takes minutes,
     so the budget runs out first.
   The correct command for CI status is `gh run list --commit <sha>` (NOT
   `gh pr checks`, which requires the "Checks: read" scope unavailable to the
   current PATs). In briefs for tasks that open PRs, state explicitly: "after
   the push, open the PR; call `gh run list --commit <sha>` **only once** with a
   generous timeout; if CI is still pending, complete the task with the PR
   number — the coordinator will verify it afterward". Never actively poll.

7. **Diagnosing timeouts through the worktree.** When a worker times out
   (`Iteration budget exhausted`), inspect its worktree before relaunching or
   blocking: `git -C <workspace_path> log --oneline -3`, `git status`, and check
   whether the branch was pushed to the remote (`git fetch origin <branch>` +
   `gh pr list --head <branch> --state all`). The work is often already
   committed and pushed, but the PR was never opened (related to pitfall #6).
   In that case, a `kanban_comment` on the task instructing "do not start over;
   open the PR from the existing branch" is enough to unblock the retry.
   This pattern has also proven valid for runtime crashes (pid not alive,
   protocol violation): code written before the crash survives in the worktree,
   and the retry reuses it.

8. **Sanitization in project worktrees.** Worktrees created with
   `--project steve-agent` do NOT have the `.local/privacy-denylist.txt` symlink
   (it lives in the repository clone, not in derived worktrees): the original
   gap was real. **It is now closed** when `PRIVACY_DENYLIST` is in the worker's
   environment — the gateway exports the instance `.env` keys to dispatched
   workers, and if the variable points to the instance denylist file,
   `scripts/check_privacy.sh` uses it directly even without the `.local/`
   symlink. The reviewer rerunning it is a **safety net**, not a workaround for
   a gap. If `PRIVACY_DENYLIST` is not in the environment instead (deployment
   not yet completed), the worker skips it and declares that; the reviewer
   closes the gap by reading the denylist from
   `~/.hermes/private/forbidden-strings.txt`. Transitional, not structural.

9. **Fragile `-A<N>` grep verifies on YAML policy.** In briefs, checks such as
   `grep -A20 'propagation' <policy> | grep <path>` produce false positives when
   YAML blocks are close together: `-A20` runs past the target block into the
   adjacent one. For tier-classification verifies on `.steve/review-policy.yaml`,
   **use a YAML parser** instead of contextual grep:
   `python3 -c "import yaml; t=yaml.safe_load(open('.steve/review-policy.yaml')); assert '<path>' not in t['tiers'].get('propagation',{}).get('paths',[])"`.
   This also applies to verifies in review briefs.

10. **Profile down after config deployment (model swap).** When a worker or
    reviewer profile receives a newly deployed config (especially a change to
    `model.default` or `model.provider`), it can become unstable: repeated
    crashes with `protocol violation` (exit rc=0 without calling
    `kanban_complete`) or `pid not alive`. Worktrees preserve pre-crash work
    (see pitfall #7), but the profile remains down until the config is fixed or
    rolled back.
    - **Symptoms:** 2+ consecutive crashes with the same `protocol_violation` on
      the same task, with regular heartbeats until a clean exit without complete.
    - **Diagnosis:** if the crash occurs less than 1h after deployment of a config
      with a model swap, suspect correlation. Ask the coordinator (ops) to check
      the profile's active config.
    - **Do not burn retries** beyond the second identical consecutive crash: the
      problem is systemic, not transient.

11. **GitHub self-review constraint blocks the fallback.** The `main` and
    `steve-worker` profiles share the same GitHub account (`scrat-ai-dev`):
    GitHub prohibits an account from approving its own PR. When
    `steve-reviewer` (separate account `scrat-ai-rev`) is down, the orchestrator
    **cannot take its place** by recording approval on GitHub — even if it runs
    the verifies and documents everything in a `kanban_comment`.
    - **Fallback when the reviewer is down:** run the verifies from the main
      profile in the review worktree, record the outcome and verdict in a
      `kanban_comment` on the task, and **notify the coordinator** that manual
      approval is needed (from the GitHub UI with the `scrat-ai-rev` account, if
      accessible) or that the reviewer must be restored.
    - **Do not attempt `gh pr review --approve` from the main profile** on PRs
      opened by steve-worker: it returns
      `Review can not approve your own pull request`.

12. **History through 2026-07-27: `respawn_guarded` deadlock with `active_pr`
    and blocked children.** When a worker opened the PR and blocked with
    `review-required`, the dispatcher could respawn it in a loop with
    `respawn_guarded` reason `active_pr`. The worker made no progress, never
    reached `done`, and any child tasks remained in `todo` indefinitely. One
    cause was parking with a dependency block after creating a review task
    without a parent: the block immediately returned to `ready`. Since
    2026-07-27, the worker completes its task after opening the PR and creating
    the independent review task, so this is no longer the active flow.
    - **Symptoms:** `hermes kanban diagnostics` shows `stranded_in_ready` on the
      parent task; on a task with a PR already open, a `respawn_guarded` event
      with reason `active_pr` repeats about once a minute. The child task is in
      `todo` with zero runs.
    - **Fix for historical tasks:** manually complete the parent with `hermes kanban complete
      <task_id> --summary "..."` or `kanban_complete(task_id=..., summary=...)`.
      The parent moves to `done`, the child is promoted to `ready`, and the next
      `hermes kanban dispatch` picks it up.
    - **Current prevention:** the worker does not park after creating the review;
      it completes its task with `kanban_complete`. The review task remains
      independent and without a parent.

13. **Provider rate limit (429) causes transient review crashes.** Model swaps
    (pitfall #10) are not the only cause: a 429 rate limit from the LLM provider
    also causes `pid not alive` and `protocol_violation` crashes in worker and
    reviewer profiles. Unlike pitfall #10 (systemic), this is **transient**: the
    quota becomes available, and the profile completes cleanly on retry.
    - **Symptoms:** 1-2 consecutive crashes, followed by a manual unblock and a
      retry that completes within a few minutes.
    - **Diagnosis:** if the crash occurs during a high-load window and the retry
      after unblocking finishes cleanly, it was a rate limit. Check task events
      for `gave_up` followed by `unblocked` and `completed`.
    - **Action:** do not burn retries. If the dispatcher already issued
      `gave_up`, a `kanban_comment` with "retry" + `kanban_unblock` restarts the
      task at the next dispatch.

14. **Assert/string coupling in pr-brief.py: the dependency is internal to the tool.** In briefs that touch pr-brief.py, the critical coupling between `run_self_test()` and the template is NOT template→tool (as one might think): pr-brief.py itself injects the string emitted in the brief, not the template. Therefore, the dependency to look for is entirely internal to the tool—if you translate a string emitted by `render_brief()`, the assert in `run_self_test()` that checks it must be updated in the same file and the same commit.

15. **Canonical text from external sources: verify with a diff, not grep markers.**
    When a worker must reproduce canonical text verbatim (licenses, standards,
    specifications), verifies based on grep markers (`grep -c 'Covenants'`,
    `grep -c 'Notice'`) **are not sufficient**: they confirm that the sections
    exist, not that their content is correct. A single wrong word in legal text
    (for example, `EXPRESS, IMPLIED` instead of `EXPRESS OR IMPLIED` in a
    BUSL-1.1 disclaimer) passes every grep marker.
    - **In the review task brief**, for canonical text, include a verify that
      **downloads the official source** (with `curl`) and **compares** the file
      content in the worktree line by line, allowing differences only in
      whitespace/wrapping.
    - **Distinguish this from normal diff review:** the reviewer reads the diff
      as a narrative; for canonical text, they must compare it character by
      character against the source. These are two different checks using two
      different techniques.
    - **Brief pattern:** "download `https://spdx.org/licenses/BUSL-1.1.html`,
      extract the text from the 'Terms' section onward, and compare it with the
      LICENSE file in the worktree. Allow differences only in
      whitespace/wrapping. If you find material discrepancies in the legal text
      -> REQUEST_CHANGES."

16. **Race condition when adding review comments to running tasks.** When the coordinator posts a `kanban_comment` with additional findings on a review task already in the `running` state, the reviewer may complete and approve BEFORE reading the comment. The window is tens of seconds: the comment arrives after the reviewer has already passed the brief-reading phase, or even after they have already called `gh pr review --approve`.
    - **Symptoms:** the reviewer completes with APPROVED, and the coordinator sees their comment marked "just now" next to a task already marked done. The reported defects are not in the GitHub review.
    - **Cause:** the dispatcher spawns the reviewer at `dispatch`; the comment arrives later, but the reviewer does not reread comments during execution.
    - **Handling (adopted approach):** if the reviewer misses the comment, trigger the fix on the existing branch anyway (as for any post-approval REQUEST_CHANGES). The GitHub approval remains valid; the fix commit updates the PR and requires re-review.
    - **Prevention (operating protocol):** when the coordinator (or repo owner) sends findings on an ongoing review, **always use option (a) first**: `kanban_block` the review task **before** commenting, then `kanban_unblock` after posting the comment. This guarantees that the reviewer rereads the comments when they resume. Only if the reviewer has already finished (task `done`) should option (b) be used: a fix task on the branch + re-review. NEVER comment on a `running` task without blocking it first: this is the bug confirmed by this session (the reviewer approved #38 and #39 without incorporating the findings; #37 and #40 required post-approval fixes).

17. **Display-layer redaction of `Authorization:` patterns (false positives in reviews).** The Hermes terminal layer masks any `Authorization: ***` pattern as `Authorization: ***`. This applies to `cat`, `sed -n <N>p`, `grep`, and `git show :file | cat`: they all show `***` even when the real bytes are `${auth}` or `token xyz`. A reviewer reading the diff or file through the terminal sees a bug that does not exist.
    - **Symptoms:** the reviewer flags `Authorization: ***` as a literal placeholder and submits REQUEST_CHANGES. The worker correctly says "the fix is already present." This creates a review deadlock based on a phantom.
    - **Diagnosis:** verify with a hex dump (`xxd`, `od -An -tx1`) or byte-level Python (`b"${auth}" in line`). Hex bypasses the display layer.
    - **Prevention:** when a worker or reviewer flags an `Authorization: ***` pattern, verify the real bytes with `xxd` before dispatching a fix. Do not trust `cat`, `sed`, or `grep` for lines containing authentication headers.
    - **In the review brief:** when asking the reviewer to trace the auth flow in the code, explicitly require `xxd` or `od` to verify the bytes of lines containing `Authorization:`.

18. **Shell scripts: `bash -n` is not enough; CI runs `shellcheck --severity=warning`.** When a worker modifies `.sh` files, `bash -n` checks only syntax (parsing) and does not catch shellcheck warnings (unquoted variables, nested quoting patterns, and so on). Steve Agent CI runs `shellcheck --severity=warning instance/*.sh scripts/*.sh`: a warning is red.
    - **In task briefs that touch `.sh` files:** the verify MUST include
      `shellcheck --severity=warning <file>` in addition to `bash -n <file>`. If
      shellcheck is not installed in the worktree, the worker installs it
      (`apt-get install -qq shellcheck` or equivalent) or reports its absence.
    - **SSH quoting and SC2027:** the `'"'"$VAR"'"'` pattern for passing locally
      expanded variables inside single-quoted SSH is extremely fragile:
      shellcheck flags it as SC2027 ("surrounding quotes actually unquote
      this"). The correct form is `"'$VAR'"` (close the single quote after the
      literal quotation mark, expand double-quoted, and reopen before the
      closing quotation mark). If the task requires quoting variables inside
      single-quoted SSH strings, explicitly test the pattern with shellcheck
      before pushing, and empirically verify (by sourcing with a stub) that the
      assembled remote command is correct with both defaults and overrides.

19. **Code paths that cannot be tested without credentials: the review brief MUST require manual code tracing.** When a worker implements a script with paths that cannot be exercised in the worktree (auth flows, network calls, credential handling), the `--self-test` covers only the pure logic. The auth/network path is dead code until deployment. The review brief MUST explicitly instruct the reviewer to trace those paths BY READING the code, not only by running the verifies. Check that every parameter received by a function actually reaches the network call (for example, `curl -H "Authorization: $auth"`, not a literal placeholder). In this session, merge-gate.sh `gh_api()` had `-H "Authorization: ***"` (literal asterisks) instead of `$auth`: self-test 10/10 green, shellcheck green, CI green. Only the reviewer's manual code tracing caught the bug.

**Subcase: code tracing the inner SSH string must be EXECUTED, not extracted manually (false positive #49).** When the path to trace is inside a single-quoted string passed to `ssh "$HOST" "$@"` (as in smoke.sh checks), the technique is correct (parse the inner string with `bash -n`), but **manually or with regex extracting the string "between the first and last quote" is the defect**: it loses characters at `'"$VAR"'` boundaries and fabricates the phantom bug it later "finds." In PR #49, the reviewer extracted the string manually, lost five `;` characters at the `); if`/`); [`/`); then` boundaries, checked the CORRUPTED string with `bash -n`, saw it fail, and attributed the defect to the code. Every `;` was present in the real code. **Correct method (reliable, no SSH):** stub the `check()` function so it replaces `ssh` with `bash -nc` for PARSE-only, define the STEVE_* values with their defaults, then source ONLY the check line taken from the file: bash expands variables and quote transitions EXACTLY as it does at runtime, and `bash -nc` parses the REAL command. Never extract it by eye or with regex: code tracing is done by EXECUTING the parse on the expanded command.

20. **History through 2026-07-27: fix task with `--parent` stuck in `todo`.**
    When the worker used to park with `review-required`, a fix task with
    `--parent` pointed to a parent that was not `done`, remained in `todo`, and
    the dispatcher silently returned `Spawned: 0`. The operational fix was to
    complete the parent manually with `kanban_complete` before dispatch. Since
    2026-07-27, the worker completes the task after opening the PR and creating
    the independent review: the parent is already `done` when REQUEST_CHANGES
    generates the fix task. The risk remains only for historical tasks that
    are still parked.

21. **Bugs in untestable network paths: recurring pattern and discovery technique (canary).** The merge-gate implementation revealed a systematic class of bugs: code that parses GitHub API responses and is invisible to self-test, shellcheck, and CI because the network path is not exercised in the worktree. Three bugs found in one session, all from the same class:
    - **Bug type 1 (read_field on an array):** `cond_label()` used `read_field(body, "name")` on an endpoint that returns an ARRAY of objects. `read_field` walks dot paths and requires a numeric index for arrays: `int("name")` → exception → empty string → label never found. Fix: parse directly with inline Python.
    - **Bug type 2 (misunderstood API semantics):** `cond_ci()` downgraded to 0 when GitHub returned `state: "pending"` with `total_count: 0`. In repos with only GitHub Actions (zero legacy statuses), that "pending" is synthetic (there is no real status). Fix: honor the legacy status only when `total_count > 0`.
    - **Bug type 3 (substring match where exact matching is required):** `case *"$label"*` performed a substring match. `steve-approved` would have matched `steve-approved-x`. Fix: a pure function with an exact comparison.
    - **Discovery technique (the canary):** none of these bugs was visible until the gate was run against a real PR with real credentials (dry-run). The `--self-test` covered pure logic (decide_merge, ci_verdict, label_present), but the gatherers (cond_label, cond_ci, cond_review) access the network and are dead code in the worktree. **The canary is the technique for discovering these bugs**: a real safe-tier PR, with the label applied, on which the gate is run in dry-run. Any condition that is 0 when it should be 1 is a bug to fix with a regression guard (extracted pure function + fixture).
    - **Structural lesson:** when implementing a script with network paths, ALWAYS extract the interpretation logic into pure functions (such as `ci_verdict`, `label_present`) and cover them in the self-test. The gatherers become thin wrappers that read data and pass it to the pure functions. The canary finds the remaining bugs.

22. **Transient GitHub outage (create-PR path).** GitHub may have an outage where `POST /repos/.../pulls` returns an empty HTTP 500 for tens of minutes. GET requests work, the branch push works, and the rate limit is healthy. The worker cannot open the PR. **This is not our error.** The branch is ready, and the PR can be created after recovery. Symptoms: `gh pr create` returns "Something went wrong while executing your query", and `gh api -X POST .../pulls` returns "unexpected end of JSON input". **Action:** do not burn retries. Wait for GitHub to recover (check githubstatus.com). The worktree preserves the code (pitfall #7). If the worker times out, the coordinator can open the PR from the main profile once GitHub has recovered.

23. **Escape hatch without a gate inferred as the prudent choice.** Silently disables approve-in-chat and restores manual merging. Always run the probe prescribed in §6 before taking that branch.

24. **PRs require a rebase for no apparent reason.** The clone was not updated
    before dispatch: worktrees created from `HEAD` without fetching started
    from a stale base. Update `main` once before creating tasks, as described
    in §2.

25. **`triage` is an intake queue, not a parking lot.** A card created with
    `hermes kanban create --triage` is promoted to `todo`, decomposed into child
    tasks, and dispatched. On 2026-07-28, ten cards written as backlog items
    autonomously produced thirteen pull requests, including a runtime pin
    change that had been explicitly deferred. To deliberately park a backlog
    card, use `hermes kanban create --initial-status blocked` instead: this is
    the form that holds it; write the blocking reason in the card body.
    - **Symptom:** work starts that nobody requested to run immediately.
    - **Fix:** on a card already in `ready`, run
      `hermes kanban block <id> "<reason>" --kind needs_input`; wait for one
      dispatcher tick and reread the state with `hermes kanban show <id>`,
      without trusting the block command's output. Respect the argument order:
      if `--ids` precedes the reason, the reason is consumed as an id.

26. **A card without an assignee remains in `ready` and never spawns a worker.**
    The dispatcher cannot start what it cannot route and reports no error: the
    card simply remains still.
    - **Symptom:** the card is `ready` and untouched while the others progress.
      Check the assignee column with `hermes kanban list` before suspecting a
      dispatcher failure.
    - **Fix:** run `hermes kanban assign <id> <profile>`.

27. **A card with an open pull request cannot be restarted.** Unblocking causes
    the dispatcher to respond once a minute with
    `respawn_guarded {reason: active_pr}` indefinitely; on 2026-07-28, this
    empty loop continued for two and a half hours.
    - **Symptom:** `hermes kanban diagnostics` reports `stranded_in_ready`, and
      `grep 'dispatcher stuck:' ~/.hermes/logs/gateway.log` repeatedly shows
      `dispatcher stuck: ready queue non-empty for N consecutive ticks but 0 workers spawned`.
    - **Fix:** apply `new_task_instead_of_unblock` here too, not only to a `done`
      card: close the card and create a new one in the same workspace with
      `--workspace dir:<path>`.

## Verification Checklist

- [ ] The task brief has a goal, constraints, boundaries, executable verifies,
      and a stop-when condition.
- [ ] The verify includes sanitization checks for every forbidden string.
- [ ] The review is assigned to steve-reviewer with the github-code-review skill.
- [ ] The story tasks are subscribed to the dedicated topic.
- [ ] The orchestrator has not performed any merge.
- [ ] Verifies on YAML policies use a parser, not `grep -A<N>` (pitfall #9).
- [ ] If the task uses `--project`, the worker runs `check_privacy.sh` with
      `PRIVACY_DENYLIST` from the environment; the reviewer reruns it as a
      safety net (pitfall #8).
- [ ] If steve-reviewer is down (2+ consecutive crashes), do not burn retries:
      document the verifies from main and notify the coordinator (pitfalls #10,
      #11).
- [ ] The worker that opened the PR and created the independent review has
      completed its task with `kanban_complete`; only historical parked tasks
      require manual completion (pitfall #12).
- [ ] If a profile crashes because of a transient provider 429, unblock it with
      `kanban_unblock` instead of burning retries (pitfall #13).
- [ ] If the worker produces canonical text verbatim (licenses, standards), the
      review brief includes a verify that downloads the official source and
      compares it line by line, not only grep markers (pitfall #15).
- [ ] If you add findings to an ongoing review, BLOCK the task with
      `kanban_block` BEFORE commenting, then `kanban_unblock`. NEVER comment on
      a `running` task without blocking it first (pitfall #16).
- [ ] If the task touches `.sh` files, the verify includes `shellcheck
      --severity=warning` in addition to `bash -n`, and the worker runs it
      before pushing (pitfall #18).
- [ ] The repo has `dismiss_stale_reviews_on_push` enabled: a commit pushed
      after approval INVALIDATES the review. Every post-approval fix requires
      an explicit re-review. Plan the fix -> re-review cycle; do not assume that
      the previous approval covers the new commit (pitfall #16).
- [ ] If a script has paths that cannot be tested without credentials (auth,
      network), the review brief requires the reviewer to trace those paths BY
      READING the code, not only by running the verifies (pitfall #19).
      **Inner SSH strings subcase (smoke.sh):** code tracing must be done by
      EXECUTING `bash -nc` on the EXPANDED command (stub check() + source the
      line from the file), NEVER by extracting the string manually/with regex:
      extraction loses characters and fabricates false positives (lesson from
      #49).
- [ ] If a reviewer or worker flags `Authorization: ***` in a file, verify the
      real bytes with `xxd` or `od` before dispatching a fix: the display layer
      masks Authorization patterns (pitfall #17).
- [ ] If you create a fix task with `--parent`, verify that the original worker
      is `done`. In the current flow, it completes after the PR and review; a
      historical parent that is still parked leaves the child in `todo`
      (pitfall #20).
- [ ] If you implement a script with network paths (API, auth), extract the
      interpretation logic into pure functions and cover them in the self-test.
      Use a safe-tier canary PR to test end-to-end before production (pitfall
      #21).
- [ ] If PR creation returns an empty HTTP 500, it is a transient GitHub outage.
      Do not burn retries: the branch is ready, and the PR can be created after
      recovery (pitfall #22).
- [ ] When the admin approves a safe-tier PR in chat, apply the steve-approved
      label + decision comment. DO NOT merge: the gate (cron) or a human
      (GitHub UI) performs the merge.
