# Steve Agent architecture (arc42-light)

Steve Agent as it exists today: a working factory that develops its own repository. Every
merged pull request here is evidence of the cycle. This is the arc42-light architecture; the
examples reference this repository's own instance (the "Steve develops Steve" pilot), not a
required configuration.

---

## 1. Introduction and goals

Steve Agent runs a software team from your chat. It turns a messaging group into a
development pipeline: backlog, AI workers, adversarial review, and merges, all driven from
the conversation where your team already works. It is two things at once:

- **dev-coordination**: it coordinates people (backlog, assignment, ownership, ideas) in the
  team group;
- **software factory**: it performs development work through a fleet of Hermes agents under
  governance, with the cycle brief -> worktree -> verification -> pull request -> human merge.

It is reusable: one instance per project or team, not a deployment tied to a single product.
The first pilot and the first proof is **Steve develops Steve**: this very repository is
built by its factory. The same instance can drive any software repository the same way.

**Quality drivers**, in priority order:

1. **Verifiability of work**: "done" is judged against real evidence (verification commands
   executed, and re-executed by the reviewer), never the model's self-assertion. These are
   *completion contracts*.
2. **Isolation**: every task runs in a git worktree with a dedicated branch, `main`
   untouched; the instance runs as a dedicated unix user on a Linux host. No agent touches its
   own runtime or `main`.
3. **Process governance as code**: review tiers, the brief template, the PR lifecycle, and
   the deterministic gate live in `.steve/` and are versioned; the coordination process is
   itself reviewed.
4. **Traceability**: config-as-code with drift-check, CI plus a main-guard, a privacy guard
   on commits, and an append-only ops journal (private) for every action on the instance.
5. **Multi-project reusability**: the versioned `instance/` blueprint is the seed for
   instantiating other teams.

## 2. Constraints

| Constraint | Detail |
|---|---|
| Platform | Telegram-first: a group in forum mode (topics -> backlog room, admin room, per-feature rooms); interaction via a bot, long polling. The Hermes base also speaks Discord, Slack, Teams, and Matrix; WhatsApp is on the roadmap. |
| Runtime | Hermes Agent, pinned **by commit** (not by tag): re-running the installer does `git pull --ff-only`, which breaks on tags. |
| Hosting | Any Linux host. Native install (no Docker), running as a non-sudoer service user. Low footprint: long polling means no inbound ports, and the runtime is modest, so a small machine is enough. No special hardware requirement. |
| LLM | Model-agnostic: any provider Hermes supports (OpenAI-compatible endpoints, hosted coding plans, or local models). A cross-provider fallback can be configured for resilience. Nothing in the design depends on a specific model. |
| Repo policy | No internal hostname/id/chat in versioned files: a local (gitignored) denylist plus `scripts/check_privacy.sh` plus a pre-commit hook plus gitleaks in CI act as guards. A gitignored `.local/` holds private design drafts, the ops journal, and e2e secrets. |
| Language | English for user-facing strings (README, errors, brief output) and for all identifiers. Some in-repo prose is still Italian (the current contributor community), migrating to English over time. |
| Merge | Human only. No agent merges to `main`; auto-merge (phase 2) is design, not code. |

## 3. Context and scope

### 3.1 Actors

| Actor | Role |
|---|---|
| Human team | Members of the forum group: they open tasks in the Backlog topic, discuss ideas, and receive reports. |
| Admin (human) | The single admin for tiered commands, the only user in `allow_from` for DMs, and the **human merge gate** for PRs on GitHub. |
| Steve instance | A Telegram bot: the main profile (Steve's "face" in the group) plus worker/reviewer profiles, a Kanban board, and factory execution. |
| Worker agent | A dedicated GitHub identity for the workers: creates the branch, commits, pushes, and opens the PR. Fine-grained PAT scoped to the target repos only; the git identity of the worktrees. It does not merge and does not approve. |
| Reviewer agent | A separate GitHub identity for the reviewer: **author != approver**, made real by GitHub's rule. Re-runs the brief's verification commands and answers APPROVED or REQUEST_CHANGES. It does not merge. |
| e2e tester | A real Telegram account, driven by the MTProto injector (`tools/e2e/injector.py`), which posts as a genuine human: it exercises allowlists and mention-gating exactly like a real member. |

The worker and reviewer are two distinct machine accounts: separating author from reviewer is
what makes the review adversarial (one account cannot approve its own work), and it stays
within GitHub's limit of one machine account per person because the phase-2 merge-bot will be
a **GitHub App** with a deterministic script, not a third account. (In this repository's own
factory these identities are `scrat-ai-dev` and `scrat-ai-rev`; the names are per-instance.)

### 3.2 Boundaries: what Steve does NOT do

- **It does not touch its own live runtime**: the instance develops the *repository* (worktree,
  PR, human merge gate), never its own config or installation. Instance upgrades happen only
  from the outside (admin via SSH) and are traced. The separation is strict (see 8.5).
- **No agent merges**: the worker and reviewer stop at "PR opened and verified". The merge is a
  human action on GitHub until phase 2 introduces a dedicated merge-bot on real enforcement.
- **It is not a multi-tenant render engine**: each instance is its own deployment; the
  `instance/` blueprint is the template candidate once a second instance exists, but the render
  is not built before then.
- **The product under development does not pollute the coordination flow**: optionally it runs
  as a separate bot in dedicated test topics (dogfooding in the same group), never as part of
  the main profile.

## 4. Solution strategy

Four load-bearing choices hold up the rest.

**1. Native Hermes primitives instead of custom scaffolding.** Worktree lifecycle, a dispatcher
with heartbeat/reclaim, completion contracts on `--goal`, `delegate_task` for sub-questions,
`channel_prompts`/`group_topics` for per-topic specialization, slash-command tiering, and the
dashboard as mission control: all covered by native primitives. Custom code is reserved for what
is genuinely domain-specific (the brief schema, the deterministic tier gate, the main-guard).

**2. Discipline on top of the primitives: briefs, gate, governance-as-code.** Primitives alone
are not enough. Steve adds: a brief schema with an explicit completion criterion (an executable
`verify:`); a **deterministic gate** (`tools/pr-brief.py`) that derives a PR's tier from the
files it touches, not from an LLM's opinion; review tiers, the brief template, and the PR
lifecycle versioned under `.steve/`; and an orchestration skill (`steve-factory`) that encodes
the main profile's runbook.

**3. Detective governance over a Free repo, then preventive on public.** On a private Free
repository there is no server-side enforcement (branch protection, rulesets, auto-merge are all
gated). The factory fills that gap with *detective* controls: CI on every PR, a main-guard that
flags bot pushes to `main` and merges without an approved review, and the human-only merge
discipline. With the repository public these become *preventive* (a ruleset on `main`, secret
scanning). Phase 2 (a merge-bot as a GitHub App plus main-guard v2) rests on that real
enforcement.

**4. One instance per project.** No runtime shared between teams: reusability comes from
replicating the `instance/` blueprint (canonical config plus env.template plus smoke plus
drift-check plus provisioning) onto a new service user/host, not from multi-tenancy.

## 5. Building block view

### 5.1 Instance (server side)

```
Linux host - dedicated unix user for the instance (home chmod 750)
|
+-- Hermes gateway (systemd user unit, Telegram long polling, zero exposed ports)
|   +-- embedded Kanban dispatcher (claim / heartbeat / reclaim of tasks)
+-- main profile          <- Steve's "face" in the group (single Telegram bot),
|                            orchestrates the factory via the steve-factory skill
+-- steve-worker profile  <- runs tasks: a clone of main WITHOUT TELEGRAM_* keys
|                            (never double-polling the bot); role SOUL and system_prompt
+-- steve-reviewer profile <- re-runs the verify commands and reviews; GitHub credentials
|                            ISOLATED in its own home (author != reviewer at the git level too)
+-- Kanban board          <- durable work queue (SQLite); per-task logs
+-- target repo           <- clone of the repo under development; per-task worktree in
|                            <repo>/.worktrees/<task>, dedicated branches
+-- dashboard/API         <- loopback only, started on demand
```

In the steve-agent repository (control and governance side):

- **`instance/` blueprint**: the canonical copy of `config.yaml`, the profiles
  (`profiles/steve-worker`, `profiles/steve-reviewer`: SOUL, config, `credentials.mode`), the
  skill (`skills/steve-factory/SKILL.md`), plus `env.template` (key names and non-secret
  defaults, never values), `smoke.sh` (9 checks over SSH), `drift-check.sh` (live vs repo diff,
  flags but does not restore), `provision-worker.sh`, `backup-kanban.sh`, `pr-watch.sh`,
  `INSTALL.md`, and the main's `SOUL.md`;
- **`.steve/` governance**: `review-policy.yaml` (deterministic tiers), `pr-lifecycle.md` (the
  process), `review-brief-template.md`;
- **`tools/` tooling**: the brief compiler (`pr-brief.py`, the gate) and the e2e injector
  (`e2e/injector.py`, a secret-free MTProto user-account);
- **`.github/` CI** and the **`scripts/` privacy guard** plus `.pre-commit-config.yaml`.

### 5.2 Telegram group (team side)

A typical forum-group layout, topics as rooms:

| Topic | Role |
|---|---|
| General | Everyday interaction; the default destination for proactive output (the home channel with no thread_id). |
| Backlog | Where the work lives: requests arrive here, Steve writes the briefs and dispatches; review briefs are delivered here (watcher on cron). |
| Ideas | Brainstorming; a candidate for the MoA (Mixture-of-Agents) preset or `delegate_task` fan-out. |
| Admin | Privileged actions; admin commands remain gated by tiering everywhere, not by the topic. |

Feature topics (`#feature-*`) arrive with the first real board: one topic per active
task/feature, specialized via `group_topics` (skill) and `channel_prompts` (prompt).

## 6. Runtime view

### 6.1 Scenario a: task factory (the cycle, proven over 30+ PRs)

1. A request in the Backlog topic becomes a brief. Steve (main) writes it with the expected
   outcome, a `verify:` with a real command, boundaries, and stop-when, **with no sensitive
   literals**, which would otherwise end up in the PR's public body.
2. The brief becomes a Kanban task: `--assignee steve-worker`, `--workspace
   worktree:<repo>/.worktrees/<task>`, `--branch`, `--goal`. The embedded dispatcher claims it
   (lock `host:PID`) and spawns the worker; heartbeat ~1/min.
3. The worker works **only** in the worktree: dedicated branch, commits there, `main` untouched.
   It opens the PR as the worker identity. It stops at "PR opened and verified": it does not merge.
4. The brief compiler (`tools/pr-brief.py`) computes the PR **tier** = max of the tiers of the
   touched files (`blast > propagation > safe`) and produces the review brief, delivered to the
   Backlog (the `pr-watch.sh` watcher on cron).
5. The reviewer identity **re-runs the brief's verification commands** (it does not trust the
   worker's claim) and answers APPROVED or REQUEST_CHANGES. On REQUEST_CHANGES the worker
   iterates on the same worktree.
6. On APPROVED, a **human merges** on GitHub. The merge signal for the human is the approval
   notification, not the green button. Post-merge: CI runs on `main`, and the main-guard stays
   green (human committer).

Tasks can be dispatched in a **parallel batch**: several concurrent workers on distinct
worktrees of the same repo, without interference.

### 6.2 Scenario b: worker crash and reclaim (proven)

1. The worker is killed mid-run.
2. The dispatcher detects the crash within the sweep (~60 s): a `crashed` event in the event log.
3. New run: `claimed` + `spawned`, regular heartbeats, `completed`.
4. The work lands on the expected branch, `main` untouched; multiple worktrees coexist without
   interference. Ephemeral workers, durable board, automatic retry with `max-retries`.

### 6.3 Scenario c: admin command denied/allowed via tiering (proven)

1. Config (group scope): `group_allow_admin_from: ['${TELEGRAM_ADMIN_ID}']`,
   `group_user_allowed_commands: [status, whoami]`. The real id is interpolated from `.env`,
   never committed.
2. A non-admin user in the group: `/status` -> answers (user tier); `/model` -> refused, with
   the list of allowed commands.
3. Structural gotcha: the DM keys (`allow_admin_from` / `user_allowed_commands`) do NOT apply in
   groups, and the admin is not cross-scope; a scope's gating activates only if that scope's
   admin key is set. It is this tiering that removes the second admin bot: a single Telegram
   profile, admin/user split per individual command.

### 6.4 Scenario d: Steve learns and self-patches (cycle observed 3 times)

1. During a cycle, Steve (main) hits a new operational lesson (for example, how to behave when
   the reviewer is down, or a pitfall in parsing the verify output).
2. Steve encodes it **in the live skill** `steve-factory` (its orchestration instruction).
3. `drift-check.sh` catches the divergence between the live skill and the canonical copy in the
   repo.
4. The factory ports the patch into the canonical copy via a reviewed PR -> zero drift. The
   process that governs the factory is itself subject to the process.

## 7. Deployment view

The real environment (node-specific values live in the server-side `.env`, not here):

| Aspect | Value |
|---|---|
| Node | Any Linux host. Native install (no Docker), non-sudoer service user; a few system prerequisites (ripgrep, build-essential, python3-dev, libffi-dev) installed by the admin beforehand. Modest CPU/RAM; no inbound ports. |
| User | Dedicated unix user (`useradd -r`, home chmod 750, `loginctl enable-linger`, an `AllowUsers` line in sshd). |
| Install | Official Hermes installer with `--commit <pin>`, as the service user without sudo. |
| Layout | Config `~/.hermes/config.yaml`, secrets `~/.hermes/.env` (600), code `~/.hermes/hermes-agent` (uv-managed Python venv), binary in `~/.local/bin` (PATH via profile). |
| Service | `hermes gateway install` -> systemd user unit; linger guarantees boot startup without login. |
| Network | Long polling: **zero listening ports**. The dashboard/API port is always loopback only, started on demand. |
| Logs | `~/.hermes/logs/gateway.log` (preferred: `journalctl --user` over a non-interactive SSH fails on journald permissions); per-task Kanban logs in `~/.hermes/kanban/logs/`. |
| Provider | The configured LLM provider's key lives in `~/.hermes/.env`, never in chat or logs, with an explicit endpoint. Model choice is per-instance; a cross-provider fallback can be set for resilience. |
| Bot | The instance's bot is an admin of the team's forum group. |

Remote administration from an ops workstation via an SSH alias; `smoke.sh` and `drift-check.sh`
run from there against the instance. `STEVE_HOST` is an **ops/clone-side** variable, not an
instance runtime variable: it does not appear in `env.template`.

## 8. Cross-cutting concepts

### 8.1 Security and ACL

Three access axes, with **OR and short-circuit** semantics:

- `allow_from` (`TELEGRAM_ALLOWED_USERS`): users allowed everywhere, DMs included;
- `group_allowed_chats` (`TELEGRAM_GROUP_ALLOWED_CHATS`): if the chat is whitelisted, **every
  group member is allowed** and `group_allow_from` is not even evaluated;
- `group_allow_from`: per-user selective in groups, effective only without a whitelisted chat.

Chosen posture: **whole-group** for the trusted team group plus `allow_from` = the admin for
DMs. A stranger in a DM is blocked with an explicit log. Above the chat ACLs, group-scope
slash-command tiering distinguishes admin from users per individual command inside the single
profile (6.3): this is what removes the second admin bot.

### 8.2 Anti-drift: config-as-code

The instance's configuration is code: the canonical copy lives in `instance/` (config.yaml,
profiles, skill, env.template with key names and non-secret defaults, never values). Changes are
born in the repo and applied to the instance; if one is born live (an emergency), it is ported
back to the repo immediately and noted in the journal. `drift-check.sh` compares live vs repo and
**flags without restoring** (exit 1 on drift), covering config, the main's SOUL, the SOUL and
config of the worker/reviewer profiles, `.env` keys (names, not values), profile conformance, and
the skill. `smoke.sh` verifies 9 health checks (8.7).

### 8.3 Process governance as code (`.steve/`)

**How** work is coordinated is versioned like any other code and changed only via PR:

- `review-policy.yaml`: deterministic path-based tiers. The mechanism (tier per path, PR = max,
  fail-safe default of `propagation`) is generic and part of the product; the paths are per-repo
  configuration. Forking Steve into a new repo means changing the paths, not the mechanism.
- `pr-lifecycle.md`: the four founding decisions (approve -> merge; reject -> redesign draft; the
  brief compiler is a gate on every PR; block a priori if a new constraint has no test) and the
  end-to-end flow, with an honest status table (what exists, what is still to build).
- `review-brief-template.md`: the template Steve fills when opening or summarizing a review.

The deterministic gate is `tools/pr-brief.py`: it computes the tier from the touched files,
produces the brief, has a `--self-test` (run in CI), and a minimal gate that raises the tier when
the policy introduces a constraint without the corresponding test.

### 8.4 Personas via SOUL and channel_prompts

Each profile loads its own `SOUL.md` from the profile home plus `CLAUDE.md`/`AGENTS.md` from the
worktree. The persona is per-instance and lives in `SOUL.md`; the worker and reviewer carry
distinct role personas. (This repository's own instance runs a Steve Jobs persona on the main:
direct and sharp about the why, "real artists ship", an obsession with simplicity, zero
sycophancy.) `channel_prompts` (flat string keys = chat_id or thread_id) applies a different
system prompt per topic and is the vehicle for any additional per-topic personalities.

### 8.5 Safe self-hosting

The instance develops the repo (worktree, PR, human merge gate) but the separation is strict:
worktree and PR on the repo, **never** any intervention on its own runtime, live config, or venv.
Instance upgrades happen only from the outside (admin via SSH) and are traced. The guard on
`main` (no bot push/merge) protects the case where the gate itself, which lives in the repo, is
modified by a PR: `tools/**`, `scripts/**`, `.github/**`, and `.steve/**` are tier `propagation`
(they require a human-signed brief).

### 8.6 Journaling and evidence

Every action on the instance appends to an append-only ops journal (private, in `.local/ops/`):
date, commands, outcomes, gotchas, never secret values. It is the operational source of truth and
the seed of the future public installation guide. Every technical assumption is validated with a
probe (verify at the source before claiming that an option exists).

### 8.7 The 9 smoke checks (main-guard)

`smoke.sh` runs over SSH and verifies: (1) ssh reachable; (2) pinned Hermes version; (3) gateway
active; (4) telegram connected (log); (5) `.env` keys present; (6) `.env` perms 600; (7) no
unexpected listeners (loopback only); (8) **main free of bot pushes**: on the first-parent history
of `origin/main` there is no commit whose committer is a bot identity (direct pushes or merges
executed by the bot; commits *authored* by the bot that arrived via a human merge are legitimate);
(9) **main merges have approved reviews**: every merge on `main` after a dynamic baseline has at
least one APPROVED review from an account different from the author. Checks 8 and 9 are the
**main-guard v2**: a detective guard while branch protection is not available (Free repo),
preventive after the flip to public.

### 8.8 Things that bite (structural gotchas)

> - The `.env` seeded by the installer **does not end with a newline**: append with
>   `printf "\nKEY=...\n"` or python-dotenv stops parsing.
> - `hermes gateway restart` makes the old process exit with status=75/TEMPFAIL: it looks like an
>   error in the journal, it is the normal mechanics.
> - The one-shot flag is `-z`. `-w/--worktree` is **silently ignored** in the one-shot path:
>   never point a `-z` run at a real repo counting on `-w`.
> - `delegate_task` in the background inside a one-shot **loses the result**: background only makes
>   sense in gateway sessions.
> - Fine-grained PATs **cannot have the Checks permission** (only GitHub Apps): `gh run list`
>   (Actions: read) is the standard way to see CI status, not a workaround.
> - `${VAR}` interpolation in config: it expands from `os.environ`, an unresolved ref is kept
>   verbatim. After a change touching the admin allowlist, a canary with a rollback backup is
>   required, to avoid locking out the admin.

## 9. Decisions

### 9.1 Fixed decisions (ADR-light)

| # | Decision |
|---|---|
| D1 | Runtime: Hermes pinned **by commit**, native install, a dedicated unix user on a Linux host, systemd user unit plus linger, long polling (zero ports); dashboard/API loopback only. |
| D2 | A SINGLE Telegram profile plus group-scope slash-command tiering; DM keys are a separate scope, the admin is NOT cross-scope; no second admin bot. |
| D3 | ACL: whole-group posture (`TELEGRAM_GROUP_ALLOWED_CHATS`) for the team group plus `allow_from` for DMs; axes in OR with short-circuit on the group. |
| D4 | Factory isolation: Kanban workspace `worktree:<path>` with a dedicated branch and an embedded dispatcher (crash/reclaim proven); NEVER rely on `hermes -w` in one-shot. |
| D5 | Verification of work: completion contracts (`--goal`) with `verify:` on real commands, **re-run by the reviewer**; synchronous `delegate_task` only for short sub-questions. |
| D6 | LLM: model-agnostic. An instance configures any Hermes-supported provider for worker/reviewer/main, optionally with a cross-provider fallback for resilience. Running the reviewer on a different model family from the worker (so the same model does not both write and judge) is desirable; it is a per-instance choice. |
| D7 | Roles with **separate GitHub identities**: a worker (commit/push/PR, fine-grained PAT) and a reviewer (author != approver, isolated credentials). No agent merges. The concrete account names and the persona are per-instance (this repository's factory uses `scrat-ai-dev`, `scrat-ai-rev`, and a Steve Jobs persona on the main). |
| D8 | Governance-as-code in `.steve/`: deterministic path-based tiers (`blast/propagation/safe`, PR = max, fail-safe default), `tools/pr-brief.py` as the gate on every PR, a versioned PR lifecycle. `tools/**` `scripts/**` `.github/**` `.steve/**` in `propagation` (the gate cannot tamper with itself cheaply). |
| D9 | Anti-drift and health: config-as-code in `instance/` (config plus profiles plus skill plus env.template), `drift-check.sh` that flags and does not restore, `smoke.sh` with 9 checks and main-guard v2, CI (`checks`: brief self-test, `bash -n`, shellcheck, gitleaks), a privacy guard (denylist plus pre-commit plus `check_privacy.sh`), and an append-only ops journal. |
| D10 | Safe self-hosting: the instance develops the REPO (worktree, PR, human merge gate), never its own runtime/live config; instance upgrades only from the outside, traced. |
| D11 | One instance per project: reusability via replicating the `instance/` blueprint onto a new service user/host, not multi-tenancy. |
| D12 | License: Business Source License (BUSL) 1.1: source-available, free for noncommercial use (personal, research, education, nonprofit, evaluation), Change License Apache-2.0 four years after each release. The MIT portions of Hermes Agent remain covered by the `NOTICE`. |

### 9.2 Phase 2: safe auto-merge (specification, not implementation)

Phase 2 takes approval from "decide" to "execute autonomously" while keeping traceability and the
guard on `main`. None of these parts is code yet (detail in `.steve/pr-lifecycle.md`):

1. **Tracked, verifiable approval**: no longer just a chat phrase, but a marking on the PR (a
   label or a comment signed by the coordination identity) issued by an admin command. The marking
   is the only acceptable proof.
2. **Auto-merge only from a dedicated bot identity**: a **GitHub App** (not a third account:
   GitHub ToS, max one machine account per person) with a deterministic script, which merges ONLY
   in the presence of the marking. The App has `Checks: Read-only` (which PATs cannot have).
3. **An evolving main-guard v2**: the guard accepts bot merges ONLY for PRs with tracked approval
   and keeps flagging everything else.
4. **Tiers excluded from auto-merge**: `blast` and `propagation` (the tiers with a human-signed
   brief) stay out; auto-merge stops at the `safe` tier.

Prerequisite: a public repo (or Team) for real server-side enforcement (a ruleset on `main`,
restricting merge to the App).

## 10. Risks and technical debt

| # | Risk / debt | Detail and mitigation |
|---|---|---|
| R1 | **LLM provider fragility** | Outages depend on the chosen provider: a primary can hit HTTP 429 (overload) and a free-tier fallback can exhaust its quota. **Mitigation**: a billed key or a reliable second provider before depending on it as a safety net; recovery = a read-only probe plus `kanban unblock` when the provider returns. |
| R2 | **Upstream `rc=0` bug on a fatal API error** | A worker can exit clean (exit 0) without `kanban_complete`/`block` on a fatal API error, violating the protocol and making the dispatcher give up on the task. Recurring. **Mitigation**: an upstream issue candidate; workaround = complete/unblock the task manually. |
| R3 | **Orphaned review dispatch after a session reset** | The daily reset leaves review tasks in `todo` with no auto-dispatch while the main is idle: a task can stay orphaned for hours. **Mitigation**: a message in the Backlog wakes Steve; a candidate for a cron-nudge or a todo auto-dispatcher. |
| R4 | **LLM-on-LLM chain** | Worker and reviewer are both LLMs: adversarial review reduces but does not eliminate the risk of correlated errors. **Mitigation**: re-run the verify (do not trust the claim), family diversity on the reviewer (D6), the guard on `main`. |
| R5 | **Completion contracts under the adverse case** | Proven mostly on the happy path. **Mitigation**: the reviewer re-running the verify and the deterministic gate cover most of it; a probe with a task designed to fail would close the remaining trust gap. |
| R6 | **Shared LLM plan rate limit** | If the provider plan is shared or rate-limited, frequent board runs can collide. **Mitigation**: monitor; a dedicated key/plan before increasing worker concurrency. |
| R7 | **Durability of the private design/journal** | The journal and private design live in `.local/` (gitignored), not versioned elsewhere. **Mitigation**: node backup plus distilling the public installation guide from the journal's seeds (this document is already the first public distillate). |

## 11. Minimal glossary

| Term | Meaning |
|---|---|
| Kanban board / dispatcher / worker | A durable work queue (SQLite) shared across Hermes profiles; the dispatcher (embedded in the gateway) does claim/spawn/heartbeat/reclaim; the worker is the profile that runs the task. |
| Completion contract | The completion contract of a `--goal` task: outcome plus `verify:` with a real command; "done" judged on evidence (re-run by the reviewer), not on self-assertion. |
| Review tier | The risk class of a file (`blast > propagation > safe`) in `.steve/review-policy.yaml`; a PR's tier is the max of its files; it determines the sign-off and human signature required. |
| Brief compiler / gate | `tools/pr-brief.py`: derives the tier from the touched files and produces the review brief; the deterministic gate on every PR. |
| main-guard | Smoke checks 8-9: no bot push/merge to `main`, and every merge has an approved review from a different account. |
| Worktree workspace | The Kanban workspace `worktree:<path>`: a git worktree with a dedicated branch, `main` never touched. |
| `channel_prompts` | Hermes config: a flat dictionary `{chat_id/thread_id: prompt}` that injects a per-topic system prompt. |
| Injector | An MTProto user-account (`tools/e2e/injector.py`) that simulates a real human in the group for e2e tests. |
| Blueprint / drift | `instance/` = the versioned canonical copy of an instance's config; drift = live vs repo divergence, detected by `drift-check.sh` (flags, does not restore). |

---

**End of document.**
