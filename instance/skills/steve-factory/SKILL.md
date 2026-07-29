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

14. **Accoppiamento assert/stringa in pr-brief.py: la dipendenza e' interna al tool.** Nei brief che toccano pr-brief.py, l'accoppiamento critico tra `run_self_test()` e il template NON e' template→tool (come si potrebbe pensare): la stringa emessa nel brief la inietta pr-brief.py stesso, non il template. Quindi la dipendenza da cercare e' tutta interna al tool — se traduci una stringa emessa da render_brief(), l'assert in run_self_test() che la controlla va aggiornato nello stesso file, nello stesso commit.

15. **Testo canonico da fonti esterne: verify con diff, non con grep marker.**
    Quando un worker deve riprodurre un testo canonico verbatim (licenze,
    standard, specifiche), i verify basati su grep marker (`grep -c
    'Covenants'`, `grep -c 'Notice'`) **non sono sufficienti**: confermano che
    le sezioni ci sono, non che il contenuto e' corretto. Una singola parola
    sbagliata nel testo legale (es. `EXPRESS, IMPLIED` invece di `EXPRESS OR
    IMPLIED` in una disclaimer BUSL-1.1) passa tutti i grep marker.
    - **Nel brief del task di review**, per testo canonico, includi un verify
      che **scarica la fonte ufficiale** (con `curl`) e **confronta** il
      contenuto del file nel worktree riga per riga, con tolleranza solo su
      whitespace/wrapping.
    - **Differenziare dal diff review normale:** il reviewer legge il diff come
      racconto; per testo canonico, deve confrontare carattere per carattera
      contro la fonte. Sono due check diversi con due tecniche diverse.
    - **Pattern di brief:** "scarica `https://spdx.org/licenses/BUSL-1.1.html`,
      estrai il testo dalla sezione 'Terms' in poi, confronta col file LICENSE
      nel worktree. Tolleranza solo su whitespace/wrapping. Se trovi
      discrepanze materiali nel testo legale -> REQUEST_CHANGES."

16. **Race condition sui commenti di review ai task running.** Quando il coordinatore posta un `kanban_comment` con findings aggiuntivi su un task di review gia' in stato `running`, il reviewer puo' completare e approvare PRIMA di leggere il commento. La finestra e' di decine di secondi: il commento arriva dopo che il reviewer ha gia' passato la fase di lettura del brief, o addirittura dopo che ha gia' chiamato `gh pr review --approve`.
    - **Sintomi:** il reviewer completa con APPROVED, e il coordinatore vede il proprio commento marcato "just now" accanto a un task gia' done. I difetti segnalati non sono nella review su GitHub.
    - **Causa:** il dispatcher spawna il reviewer al `dispatch`; il commento arriva dopo, ma il reviewer non rilegge i commenti durante l'esecuzione.
    - **Gestione (approccio adottato):** se il reviewer salta il commento, scatena comunque il fix sul branch esistente (come si fa per qualsiasi REQUEST_CHANGES post-approve). L'approve su GitHub resta valido; il fix commit aggiorna la PR e richiede re-review.
    - **Prevenzione (protocollo operativo):** quando il coordinatore (o il repo owner) manda rilievi su review in corso, **sempre opzione (a) prima**: `kanban_block` il task di review **prima** di commentare, poi `kanban_unblock` dopo aver postato il commento. Questo garantisce che il reviewer rilegga i commenti quando riprende. Solo se il reviewer ha gia' chiuso (task `done`), ricorrere all'opzione (b): fix task sul branch + re-review. Non commentare MAI un task `running` senza averlo prima bloccato: e' il bug che questa sessione ha confermato (reviewer ha approvato #38 e #39 senza incorporare i rilievi, #37 e #40 hanno richiesto fix post-approve).

17. **Redazione del display layer su pattern `Authorization:` (falsi positivi nei review).** Il terminal layer di Hermes maschera qualsiasi pattern `Authorization: *** come `Authorization: ***`. Questo vale per `cat`, `sed -n <N>p`, `grep`, `git show :file | cat`: tutti mostrano `***` anche quando i byte reali sono `${auth}` o `token xyz`. Un reviewer che legge il diff o il file via terminal vede un bug che non esiste.
    - **Sintomi:** il reviewer flagga `Authorization: ***` come literal placeholder, REQUEST_CHANGES. Il worker giustamente dice "il fix e' gia' presente". Si crea un deadlock di review basato su un fantasma.
    - **Diagnosi:** verifica con hex dump (`xxd`, `od -An -tx1`) o Python byte-level (`b"${auth}" in line`). L'hex bypassa il display layer.
    - **Prevenzione:** quando un worker o un reviewer flagga un pattern `Authorization: ***`, prima di dispatchare un fix, verifica i byte reali con `xxd`. Non fidarti di `cat`, `sed`, `grep` per linee che contengono header di autenticazione.
    - **Nel brief di review:** quando si chiede al reviewer di tracciare il flusso auth nel codice, specificare esplicitamente di usare `xxd` o `od` per verificare i byte delle righe con `Authorization:`.

18. **Shell scripts: `bash -n` non basta, la CI esegue `shellcheck --severity=warning`.** Quando un worker modifica file `.sh`, `bash -n` verifica solo la sintassi (parse) ma non catcha i warning di shellcheck (variabili non quotate, pattern di quoting annidato, ecc.). La CI di steve-agent esegue `shellcheck --severity=warning instance/*.sh scripts/*.sh`: un warning e' rosso.
    - **Nei brief di task che toccano `.sh`:** il verify DEVE includere
      `shellcheck --severity=warning <file>` oltre a `bash -n <file>`. Se
      shellcheck non e' installato nel worktree, il worker lo installa
      (`apt-get install -qq shellcheck` o equivalente) o dichiara l'assenza.
    - **Quoting SSH e SC2027:** il pattern `'"'"$VAR"'"'` per passare variabili
      localmente espandendole dentro single-quote SSH e' fragilissimo: shellcheck
      lo flagga come SC2027 ("surrounding quotes actually unquote this"). La
      forma corretta e' `"'$VAR'"` (close-single-quote dopo la virgoletta
      letterale, expand double-quoted, reopen prima della virgoletta di chiusura).
      Se il task richiede quoting di variabili dentro stringhe SSH single-quoted,
      testa il pattern esplicitamente con shellcheck prima di pushare, e verifica
      empiricamente (sourcing con stub) che il comando remoto assemblato sia
      corretto sotto default e override.

19. **Code path non testabili senza credenziali: il brief di review DEVE imporre code-tracing manuale.** Quando un worker implementa uno script con path che non possono essere esercitati nel worktree (flussi di auth, chiamate di rete, gestione credenziali), il `--self-test` copre solo la logica pura. Il path di auth/rete e' codice morto fino al deploy. Il brief di review DEVE istruire esplicitamente il reviewer di tracciare quei path LEGGENDO il codice, non solo eseguendo i verify. Verificare che ogni parametro ricevuto da una funione arrivi effettivamente alla chiamata di rete (es. `curl -H "Authorization: $auth"`, non un literal placeholder). Questa sessione: merge-gate.sh `gh_api()` aveva `-H "Authorization: ***"` (asterischi letterali) invece di `$auth`: self-test 10/10 verde, shellcheck verde, CI verde. Solo il code-tracing manuale del reviewer ha catturato il bug.

**Sottocaso: code-trace della stringa SSH interna va ESEGUITO, non estratto a mano (falso positivo #49).** Quando il path da tracciare e' dentro una stringa single-quoted passata a `ssh "$HOST" "$@"` (come i check di smoke.sh), la tecnica e' giusta (parsare la stringa interna con `bash -n`) ma **l'estrazione manuale/regex della stringa "tra il primo e l'ultimo apice" e' il difetto**: perde caratteri sui boundary `'"$VAR"'` e fabbrica il bug fantasma che poi "trova". PR #49: il reviewer ha estratto la stringa a mano, perso 5 `;` ai boundary `); if`/`); [`/`); then`, verificato la stringa CORROTTA con `bash -n`, visto fallire e attribuito il difetto al codice. I `;` c'erano tutti nel codice reale. **Metodo corretto (affidabile, niente SSH):** stub della funzione `check()` che rimpiazza `ssh` con `bash -nc` per PARSE-only, definisce le STEVE_* ai default, poi source la SOLA riga del check preso dal file: bash espande variabili e quote-transition ESATTAMENTE come a runtime, `bash -nc` parsa il comando REALE. Mai estrarre a occhio o con regex: il code-trace si fa ESEGUENDO il parse sul comando espanso.

20. **Storico fino al 2026-07-27: fix task con `--parent` fermo in `todo`.**
    Quando il worker parcheggiava con `review-required`, un task di fix con
    `--parent` puntava a un parent non `done`, restava in `todo` e il dispatcher
    ritornava `Spawned: 0` silenziosamente. Il fix operativo era completare
    manualmente il parent con `kanban_complete` prima del dispatch. Dal
    2026-07-27 il worker completa il task dopo avere aperto la PR e creato la
    review indipendente: il parent è già `done` quando una REQUEST_CHANGES genera
    il task di fix. Il rischio resta soltanto per task storici ancora parcheggiati.

21. **Bug nei path di rete non testabili: pattern ricorrente e tecnica di scoperta (canary).** L'implementazione del merge-gate ha rivelato una classe di bug sistematica: codice che parsa risposte API GitHub e che e' invisibile a self-test, shellcheck e CI perche' il path di rete non si esercita nel worktree. Tre bug trovati in una sessione, tutti della stessa classe:
    - **Bug tipo 1 (read_field su array):** `cond_label()` usava `read_field(body, "name")` su un endpoint che ritorna un ARRAY di oggetti. `read_field` cammina dot-path e per array pretende indice numerico: `int("name")` → eccezione → stringa vuota → label mai trovata. Fix: parse diretto con Python inline.
    - **Bug tipo 2 (semantica API misconosciuta):** `cond_ci()` declassava a 0 quando GitHub rispondeva `state: "pending"` con `total_count: 0`. Su repo con solo GitHub Actions (zero legacy status), quello "pending" e' sintetico (nessuno status reale). Fix: onorare il legacy status solo se `total_count > 0`.
    - **Bug tipo 3 (substring match dove serve exact):** il `case *"$label"*` faceva match substring. `steve-approved` avrebbe matchato `steve-approved-x`. Fix: funzione pura con confronto esatto.
    - **Tecnica di scoperta (il canary):** nessuno di questi bug era visibile finche' il gate non e' stato eseguito contro un PR reale con credenziali vere (dry-run). Il `--self-test` copriva la logica pura (decide_merge, ci_verdict, label_present), ma i gatherer (cond_label, cond_ci, cond_review) fanno rete e sono codice morto nel worktree. **Il canary e' la tecnica per scoprire questi bug**: una PR safe-tier reale, con label applicata, su cui il gate viene eseguito in dry-run. Ogni condizione che risulta 0 quando dovrebbe essere 1 e' un bug da fixare con regression guard (funzione pura estratta + fixture).
    - **Lezione strutturale:** quando implementi uno script con path di rete, estrai SEMPRE la logica di interpretazione in funzioni pure (come `ci_verdict`, `label_present`) e coprile nel self-test. I gatherer diventano thin wrapper che leggono i dati e li passano alle funzioni pure. Il canary scopre i bug residui.

22. **Outage GitHub transiente (create-PR path).** GitHub puo' andare in outage sul `POST /repos/.../pulls` con HTTP 500 vuoto per decine di minuti. I GET funzionano, il push del branch funziona, il rate-limit e' sano. Il worker non puo' aprire la PR. **Non e' un errore nostro.** Il branch e' pronto, la PR nasce alla ripresa. Sintomi: `gh pr create` ritorna "Something went wrong while executing your query", `gh api -X POST .../pulls` ritorna "unexpected end of JSON input". **Azione:** non bruciare retry. Aspetta che GitHub recuperi (controlla githubstatus.com). Il worktree conserva il codice (pitfall #7). Se il timeout del worker scade, il coordinatore puo' aprire la PR dal main profile quando GitHub e' tornato.

23. **Escape hatch senza gate inferita come scelta prudente.** Disabilita in silenzio l'approve-in-chat e ripristina il merge manuale. Esegui sempre il probe prescritto nel §6 prima di prendere quel ramo.

24. **PR che richiedono rebase senza motivo apparente.** Il clone non è stato
    aggiornato prima del dispatch: i worktree, creati da `HEAD` senza fetch,
    sono partiti da una base stale. Aggiorna `main` una volta prima di creare i
    task, come descritto nel §2.

25. **`triage` è una coda di ingresso, non un parcheggio.** Una card creata con
    `hermes kanban create --triage` viene promossa a `todo`, scomposta in task
    figli e dispatchata. Il 2026-07-28 dieci card scritte come backlog hanno
    prodotto autonomamente tredici pull request, compresa una modifica del pin
    del runtime che era stata esplicitamente rinviata. Per parcheggiare
    deliberatamente una card di backlog, usa invece
    `hermes kanban create --initial-status blocked`: è la forma che la trattiene;
    scrivi il motivo del blocco nel body della card.
    - **Sintomo:** parte lavoro che nessuno ha chiesto di eseguire subito.
    - **Fix:** su una card già `ready`, esegui
      `hermes kanban block <id> "<reason>" --kind needs_input`; attendi un tick
      del dispatcher e rileggi lo stato con `hermes kanban show <id>`, senza
      fidarti dell'output del comando di blocco. Rispetta l'ordine degli
      argomenti: se `--ids` precede il motivo, il motivo viene consumato come id.

26. **Una card senza assignee resta in `ready` e non genera mai un worker.** Il
    dispatcher non può avviare ciò che non può instradare e non segnala alcun
    errore: la card resta semplicemente ferma.
    - **Sintomo:** la card è `ready` e intatta mentre le altre avanzano. Controlla
      la colonna assignee con `hermes kanban list` prima di sospettare un guasto
      del dispatcher.
    - **Fix:** esegui `hermes kanban assign <id> <profile>`.

27. **Una card con una pull request già aperta non può essere riavviata.** Lo
    sblocco induce il dispatcher a rispondere una volta al minuto
    `respawn_guarded {reason: active_pr}` senza fine; il 2026-07-28 questo ciclo
    è rimasto vuoto per due ore e mezza.
    - **Sintomo:** `hermes kanban diagnostics` riporta `stranded_in_ready` e
      `grep 'dispatcher stuck:' ~/.hermes/logs/gateway.log` mostra ripetutamente
      `dispatcher stuck: ready queue non-empty for N consecutive ticks but 0 workers spawned`.
    - **Fix:** applica `new_task_instead_of_unblock` anche qui, non soltanto a
      una card `done`: chiudi la card e creane una nuova sullo stesso workspace
      con `--workspace dir:<path>`.

## Verification Checklist

- [ ] Il brief del task ha goal, vincoli, boundaries, verify eseguibili, stop-when.
- [ ] I check di sanitizzazione sono nel verify per ogni stringa vietata.
- [ ] La review e' assegnata a steve-reviewer con la skill github-code-review.
- [ ] I task della story sono iscritti al topic dedicato.
- [ ] Nessun merge eseguito dall'orchestratore.
- [ ] I verify su policy YAML usano un parser, non `grep -A<N>` (pitfall #9).
- [ ] Se il task usa `--project`, il worker esegue `check_privacy.sh` con
      `PRIVACY_DENYLIST` dall'ambiente; il reviewer lo riesegue come
      cintura di sicurezza (pitfall #8).
- [ ] Se steve-reviewer e' down (2+ crash consecutivi), non bruciare retry:
      documenta i verify dal main e segnala al coordinatore (pitfall #10, #11).
- [ ] Il worker che ha aperto la PR e creato la review indipendente ha completato
      il proprio task con `kanban_complete`; soltanto i task storici parcheggiati
      richiedono il completamento manuale (pitfall #12).
- [ ] Se un profilo crasha per 429 provider (transiente), sblocca con
      `kanban_unblock` invece di bruciare retry (pitfall #13).
- [ ] Se il worker produce testo canonico verbatim (licenze, standard), il
      brief della review include un verify che scarica la fonte ufficiale e
      confronta riga per riga, non solo grep marker (pitfall #15).
- [ ] Se aggiungi rilievi a una review in corso, BLOCCA il task con
      `kanban_block` PRIMA di commentare, poi `kanban_unblock`. Non
      commentare MAI un task `running` senza bloccarlo prima (pitfall #16).
- [ ] Se il task tocca file `.sh`, il verify include `shellcheck
      --severity=warning` oltre a `bash -n`, e il worker lo esegue prima del
      push (pitfall #18).
- [ ] Il repo ha `dismiss_stale_reviews_on_push` attivo: un commit spinto
      dopo l'approvazione INVALIDA la review. Ogni fix post-approve richiede
      una re-review esplicita. Pianifica il ciclo fix -> re-review, non
      assumere che l'approve precedente copra il nuovo commit (pitfall #16).
- [ ] Se uno script ha path non testabili senza credenziali (auth, rete), il
      brief della review impone al reviewer di tracciare quei path LEGGENDO
      il codice, non solo eseguendo i verify (pitfall #19).
      **Sottocaso stringhe SSH interne (smoke.sh):** il code-trace va fatto
      ESEGUENDO `bash -nc` sul comando ESPANSO (stub check() + source della
      riga dal file), MAI estraendo la stringa a mano/regex: l'estrazione
      perde caratteri e fabbrica falsi positivi (lesson da #49).
- [ ] Se un reviewer o un worker flagga `Authorization: ***` in un file,
      verifica i byte reali con `xxd` o `od` prima di dispatchare un fix:
      il display layer maschera i pattern Authorization (pitfall #17).
- [ ] Se crei un fix task con `--parent`, verifica che il worker originario sia
      `done`. Nel flusso attuale lo completa dopo PR e review; un parent storico
      ancora parcheggiato lascia il figlio in `todo` (pitfall #20).
- [ ] Se implementi uno script con path di rete (API, auth), estrai la logica
      di interpretazione in funzioni pure e coprile nel self-test. Usa una
      PR canary safe-tier per testare end-to-end prima della produzione
      (pitfall #21).
- [ ] Se la creazione di una PR ritorna HTTP 500 vuoto, e' un outage GitHub
      transiente. Non bruciare retry: il branch e' pronto, la PR nasce alla
      ripresa (pitfall #22).
- [ ] Quando l'admin approva in chat una PR safe-tier, applichi la label
      steve-approved + commento di decisione. NON mergi: il gate (cron) o
      l'umano (GitHub UI) eseguono il merge.
