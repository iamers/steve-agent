# Glossary

The vocabulary this repository uses, in its documentation, its agent directive
files and its briefs. One definition per term, in one place: where another
document needs a term, it links here rather than restating it.

## Work artifacts

| Term | Meaning |
|---|---|
| Card | A unit of work on the Kanban board. Hermes stores it in a table named `tasks`, gives it an id prefixed `t_`, and its CLI verbs are task-shaped (`hermes kanban create`, `complete`, `block`); Hermes also calls the same row a card in its own code and comments. They are one thing, not two: prefer **card** in prose about the board, **task** in text about the CLI or the stored record. |
| Run | One execution attempt of a card by a profile. A card may have several runs — a retry after failure, a respawn — and `hermes kanban runs <card>` lists them. **A card is not its run.** A run can fail while the card stays open, and a card can be marked done while its run is still executing, so a card reading `done` is not evidence that work has stopped. |
| Issue | A GitHub issue: public, on a repository, addressed to people outside this deployment. Never a synonym for a card. A card may *plan* an issue — that is a relation between two artifacts, not two names for one. |
| Pull request | The unit a worker delivers. Work reaches `main` only through one, and its body fills `.github/PULL_REQUEST_TEMPLATE.md`. Abbreviated PR; not a synonym for the branch it is opened from. |
| Brief | The body of a card, written before dispatch by whoever made the decision, and not reworded by whoever executes it. It states goal, boundary, verifies and stop-when. An executor that finds the brief impossible reports the defect rather than improvising around it. |
| Verify | An executable command named in a brief, run by the executor and re-run by the reviewer. A verify that cannot fail is not a verify: a check that exits 0 without reading anything reads as a pass and is treated as a defect. |

## Factory

| Term | Meaning |
|---|---|
| Kanban board / dispatcher / worker | A durable work queue (SQLite) shared across Hermes profiles; the dispatcher (embedded in the gateway) does claim/spawn/heartbeat/reclaim; the worker is the profile that runs the task. |
| Completion contract | The completion contract of a `--goal` task: outcome plus `verify:` with a real command; "done" judged on evidence (re-run by the reviewer), not on self-assertion. |
| Brief compiler / gate | `tools/pr-brief.py`: derives the tier from the touched files and produces the review brief; the deterministic gate on every PR. |
| Worktree workspace | The Kanban workspace `worktree:<path>`: a git worktree with a dedicated branch, `main` never touched. |
| `channel_prompts` | Hermes config: a flat dictionary `{chat_id/thread_id: prompt}` that injects a per-topic system prompt. |
| Injector | An MTProto user-account (`tools/e2e/injector.py`) that simulates a real human in the group for e2e tests. |

## Governance

| Term | Meaning |
|---|---|
| Review tier | The risk class of a file (`blast > propagation > safe`) in `.steve/review-policy.yaml`; a PR's tier is the max of its files; it determines the sign-off and human signature required. |
| main-guard | Smoke checks 8-10: no worker or reviewer bot push/merge to `main`, every merge has an approved review from a different account, and any merge performed by the merge App carries both the approval label and an approved review. |
| Blueprint / drift | `instance/` = the versioned canonical copy of an instance's config; drift = live vs repo divergence, detected by `drift-check.sh` (flags, does not restore). |
