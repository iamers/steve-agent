# Steve Agent Instance Installation Guide

This guide walks through deploying a new Steve Agent (Hermes Agent) instance on a Linux host. It covers prerequisites, Hermes installation, LLM provider setup, Telegram integration, gateway as a systemd service, and blueprint verification. The steps use Ubuntu and a subscription-backed Codex plan as concrete examples: adapt the package-manager commands to your distribution and the provider settings to any Hermes-supported model.

## 1. Prerequisites

### System Packages

Install required system packages before running the Hermes installer. The installer will prompt for these, but installing them system-wide first avoids permission issues with the service user.

```bash
sudo apt-get install -y ripgrep build-essential python3-dev libffi-dev pipx
```

Ensure `xz-utils`, `git`, `curl`, `ffmpeg`, and `jq` are also present.

### Dedicated Unprivileged User

Create a dedicated service user, using a naming pattern such as `ha-<name>`. This user will run the Hermes agent and should not have sudo privileges.

```bash
sudo useradd -r -s /bin/bash -d /srv/ha-<instance-name> -m ha-<instance-name>
sudo chmod 750 /srv/ha-<instance-name>
```

Enable linger for the service user so user services start at boot and persist after logout:

```bash
sudo loginctl enable-linger ha-<instance-name>
```

Set up SSH access for the service user by copying authorized keys:

```bash
sudo mkdir -p /srv/ha-<instance-name>/.ssh
sudo cp /home/<your-admin-user>/.ssh/authorized_keys /srv/ha-<instance-name>/.ssh/authorized_keys
sudo chown -R ha-<instance-name>:ha-<instance-name> /srv/ha-<instance-name>/.ssh
sudo chmod 700 /srv/ha-<instance-name>/.ssh
sudo chmod 600 /srv/ha-<instance-name>/.ssh/authorized_keys
```

Update SSH server configuration to allow the new user. Edit `/etc/ssh/sshd_config.d/99-hardening.conf` and append the user to the `AllowUsers` line:

```bash
sudo sshd -t
sudo systemctl reload ssh
```

Verify login as the service user and that user services are enabled:

```bash
ssh ha-<instance-name>@<host>
systemctl --user is-system-running
# Expected output: running
```

Configure git identity for the service user (needed for worktree commits):

```bash
git config --global user.name "ha-<instance-name>"
git config --global user.email "ha-<instance-name>@<host>.local"
```

## 2. Install Hermes

Switch to the service user and install a pinned version of Hermes Agent. Pinning by commit ensures reproducible re-installs (pinning by tag breaks on `git pull --ff-only`).

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
  | bash -s -- --skip-browser --skip-setup --commit c1b0f6f3c1d05f95fd3c9c96c37fc5c940898011
```

Even with `--skip-setup`, interactive prompts may appear if running in a TTY (e.g., tmux). Answer the following:

- "Install ripgrep? [Y/n]" → `n` (already installed system-wide)
- "Install build tools? [Y/n]" → `n` (already installed system-wide)

Verify installation:

```bash
hermes --version
# Expected output starts with: Hermes Agent v0.19.0 (2026.7.20)

git -C ~/.hermes/hermes-agent rev-parse HEAD
# Expected output: c1b0f6f3c1d05f95fd3c9c96c37fc5c940898011

hermes doctor
# Should show only warnings for optional tools (web search keys, etc.)
```

Installation creates the following layout:
- Config: `~/.hermes/config.yaml`
- Secrets: `~/.hermes/.env`
- Code: `~/.hermes/hermes-agent` (Python 3.11.15 venv managed by uv)
- CLI: `~/.local/bin/hermes` (added to PATH in `.bashrc`)

## 3. LLM Provider Setup

Steve Agent is model-agnostic: any Hermes-supported provider works (an API key, a subscription-backed plan, or a local OpenAI-compatible endpoint). Two things matter more than the specific model:

- **Do not put the whole factory on one quota.** Configure a `fallback_model` chain whose links sit on *different* providers, and make at least one link a provider that cannot run out of quota (a local endpoint). If the primary and the fallback are two external quotas, a busy day exhausts both and turns die with no retry.
- **Assign models per role.** The orchestrator, the worker, and the reviewer are separate Hermes profiles with their own `config.yaml`, so each can run a different model. See §5.

This guide uses a ChatGPT/Codex subscription as the concrete example, because it needs no API key. Substitute your provider's credentials and model ids if you use something else.

### Option A: subscription-backed provider (no API key)

Install the Codex CLI for the instance user. Set a user-level npm prefix so this needs no `sudo` and stays inside the instance's home:

```bash
npm config set prefix ~/.local
npm i -g @openai/codex
codex --version   # 0.130.0 or newer
```

Authenticate. On a headless host use `--device-auth`: the default flow starts a callback server on `localhost:1455`, which a browser on another machine cannot reach.

```bash
codex login --device-auth
# Open the printed URL, enter the one-time code, then verify:
codex login status   # -> "Logged in using ChatGPT"
```

That writes `~/.codex/auth.json`. Hermes keeps its own credential store, so register the credential with Hermes too, otherwise turns fail with `No Codex credentials stored`:

```bash
hermes auth add openai-codex --type oauth
# Offers to import the existing ~/.codex/auth.json. Requires a real terminal:
# with piped stdin the prompt is skipped and nothing is registered.
```

Two cautions:

- That command writes `model.provider` into `config.yaml` when it completes. On an instance where `config.yaml` is version-controlled and drift-checked, verify the file afterwards and keep the canonical copy authoritative.
- Models with a `-codex` suffix (for example `gpt-5.2-codex`) are **not** reachable on a ChatGPT subscription; the API returns `HTTP 400: The '<model>' model is not supported when using Codex with a ChatGPT account`. Use the current general models instead.

### Option B: API key provider

Add the key to `~/.hermes/.env` and set the base URL explicitly, since explicit beats auto-detection:

```bash
printf "\n<PROVIDER>_API_KEY=<your-api-key>\n" >> ~/.hermes/.env
printf "<PROVIDER>_BASE_URL=<https://your-provider/v1>\n" >> ~/.hermes/.env
```

Record the key name in `instance/env.template` as well: `drift-check.sh` compares the *names* of the populated keys, so an undocumented key reads as drift.

### Common steps

Secure the `.env` file:

```bash
chmod 600 ~/.hermes/.env
```

Set the provider and default model:

```bash
hermes config set model.provider <provider>
hermes config set model.default <model-id>
```

Clean up any default base URL from the template:

```bash
sed -i '/^model.base_url/d' ~/.hermes/config.yaml
```

### Smoke Test

Verify the installation works:

```bash
hermes -z "Reply with a single word: ok"
# Expected output: ok
```

The one-shot flag is `-z`, not `-q`.

## 4. Telegram Channel Setup

### Create Bot via BotFather

1. Start a chat with @BotFather
2. Send `/newbot` and follow the prompts
3. Choose a username (e.g., `@<your-bot-username>`)
4. Copy the bot token

### Add Bot Token to .env

Add the bot token to `~/.hermes/.env`:

```bash
printf "TELEGRAM_BOT_TOKEN=<your-bot-token>\n" >> ~/.hermes/.env
```

Never paste the token into chat or command history. Use `read -s` when entering it.

### Create Forum Group

1. Create a new Telegram group
2. Make it a forum group (enables topics)
3. Add the bot as an administrator
4. Create topics as needed (e.g., General, Backlog, Ideas, Admin)

### Discover Chat and Thread IDs

Use Telegram's `getUpdates` API to discover the group chat ID and topic thread IDs. Do this BEFORE starting the gateway—once the gateway is running, it consumes updates and concurrent `curl` calls will fail with 409.

```bash
# Trigger an update (mention the bot or send a message in the group)
curl -s "https://api.telegram.org/bot<your-bot-token>/getUpdates" | jq .
```

**Important**: The bot must receive a fresh event after being added to the group. The addition itself doesn't produce visible updates in `getUpdates`. Send a mention or message to the bot after adding it.

From the response, note:
- Group chat ID: negative number like -<group-chat-id>
- Topic IDs: forum topic IDs (General is usually 1, the default)

### Configure Telegram Environment

Add Telegram configuration to `~/.hermes/.env`:

```bash
printf "TELEGRAM_ALLOWED_USERS=<your-telegram-user-id>\n" >> ~/.hermes/.env
printf "TELEGRAM_GROUP_ALLOWED_CHATS=<group-chat-id>\n" >> ~/.hermes/.env
printf "TELEGRAM_HOME_CHANNEL=<group-chat-id>\n" >> ~/.hermes/.env
printf "TELEGRAM_HOME_CHANNEL_NAME=\"<group-name>\"\n" >> ~/.hermes/.env
```

Notes:
- `TELEGRAM_HOME_CHANNEL_THREAD_ID` is omitted to default to the General topic
- Multiple users can be comma-separated in `TELEGRAM_ALLOWED_USERS`
- Start with a strict allowlist posture (only you, only one group)

## 5. Gateway as Systemd User Service

Install the gateway as a user service and start it:

```bash
hermes gateway install
hermes gateway start
```

Verify the service is running:

```bash
systemctl --user is-active hermes-gateway.service
# Expected output: active
```

Check the gateway log:

```bash
tail -f ~/.hermes/logs/gateway.log
```

Expected log entries:
- "Connected to Telegram (polling mode)"
- "✓ telegram connected"
- Number of registered commands
- "Sent home-channel startup notification to telegram:<group-chat-id>"

The gateway uses long polling and doesn't open any listening ports. Any reserved port (e.g., `23789`) is for future use with a local dashboard/API.

## 6. Web dashboard (optional)

Hermes ships a native web UI (kanban board, session history, model settings). On a non-loopback bind, basic authentication is mandatory; credentials live in `~/.hermes/config.yaml` under the top-level `dashboard:` key (`basic_auth.username`, `basic_auth.password_hash`, and a `secret` used for cookie signing).

Set them up either via the interactive wizard of `hermes dashboard` or by editing `dashboard.basic_auth` directly in `~/.hermes/config.yaml`.

Never commit `password_hash` or `secret` to the blueprint repo. The drift check excludes the entire `dashboard:` block from its comparison precisely for this reason, so the canonical `instance/config.yaml` intentionally has no dashboard section while the live instance does.

Start the dashboard:

```bash
hermes dashboard --host <private-vpn-ip> --port <reserved-port> --no-open
```

The dashboard runs as a foreground process with no built-in service manager. Keep it alive with `tmux`, a `systemd --user` unit, or any process supervisor of your choice.

## 7. Blueprint Checks

The `instance/` directory in the steve-agent repo contains a blueprint for instance configuration and verification.

### Clone the Steve Agent Repository

```bash
mkdir -p ~/repos
cd ~/repos
git clone https://github.com/iamers/steve-agent.git
cd steve-agent
```

### Install the privacy guard hook

The privacy guard lives in the repository clone, so install it in the clone on the instance, not only in the operator's workstation clone. Install `pre-commit` as an isolated user-level tool and verify that it is available before installing the hook:

```bash
pipx install pre-commit
pre-commit --version
```

From the root of the instance clone, install the hook and verify that its file exists in the repository hooks directory:

```bash
cd ~/repos/steve-agent
pre-commit install
test -f "$(git rev-parse --git-path hooks/pre-commit)"
```

Git worktrees share the hooks of the main repository, so installing the hook once in the instance clone also covers its task worktrees.

Create the clone-local denylist before configuring the hook to use it. The file contains one case-insensitive extended-regex pattern per line; blank lines and lines beginning with `#` are ignored. Populate it only with instance-specific identifiers that must not appear in a public repository, such as categories of internal host names, operator identities, internal paths, private network addresses, and unannounced project names. Do not copy those values into this guide or any other tracked file.

```bash
mkdir -p .local
install -m 600 /dev/null .local/privacy-denylist.txt
# Populate .local/privacy-denylist.txt with the instance-specific patterns now.
```

The `.local/` path is gitignored, and the denylist must never be committed. A literal string is also a valid pattern, so an operator can enter a token directly. However, extended-regex metacharacters such as periods, asterisks, plus signs, parentheses, pipes, and backslashes are interpreted rather than matched literally unless escaped. An unescaped metacharacter can prevent the pattern from matching the literal token that the operator intended to block, creating a false negative that lets the sensitive identifier pass. Escape metacharacters when the intended value is literal, and verify every entry against the exact token it must catch rather than assuming that the pattern is correct.

Test one pattern and its intended token with the same matching flags used by the privacy script. For example, this deliberately generic escaped pattern must match the literal token and exit 0:

```bash
pattern='alpha\+beta'
token='alpha+beta'
printf '%s\n' "$token" | grep -nHiE -I -e "$pattern"
```

Replace both values when validating a real entry. Test the token the pattern is intended to catch; a project regex does not necessarily need to match its own pattern text.

Do not continue with an absent or empty denylist: in either case the privacy guard exits successfully without scanning and becomes a silent no-op. The active-pattern check below is therefore evidence that the guard is actually enabled, not an optional validation.

The clone-local `.local/privacy-denylist.txt` fallback works only when the check runs from the main clone. Task worktrees do not contain that file. Set `PRIVACY_DENYLIST` in the instance `~/.hermes/.env` to the denylist's absolute path so Hermes workers inherit a path that is readable from every task worktree:

```dotenv
PRIVACY_DENYLIST=<instance-home>/repos/steve-agent/.local/privacy-denylist.txt
```

Replace `<instance-home>` with the instance user's absolute home path. Worker profiles and task worktrees do not exist yet at this point in the installation. Verify the configured path immediately from the main clone by exporting the same value for the current shell, then prove that the file is readable and contains at least one active pattern before running the check:

```bash
cd ~/repos/steve-agent
export PRIVACY_DENYLIST=<instance-home>/repos/steve-agent/.local/privacy-denylist.txt
test -n "${PRIVACY_DENYLIST:-}"
test -r "$PRIVACY_DENYLIST"
grep -qEv '^[[:space:]]*(#|$)' "$PRIVACY_DENYLIST"
bash scripts/check_privacy.sh instance/INSTALL.md
```

The export and the next three commands prove that the configured denylist is actually reached. The privacy script also exits 0 when the denylist is missing or empty, so its exit status alone does not prove that a scan occurred. Without a reachable denylist, the installed hook is a silent no-op: it blocks nothing and emits no warning. Repeat the inheritance check from the first real task worktree after creating the worker profiles and kanban board, as required in the Next Steps section.

### Run Smoke Tests

The smoke script verifies core functionality:

```bash
./instance/smoke.sh
```

Expected: 10/10 checks PASS. Three of them are the main-guard: no bot pushes to `main`, every merge carries an approved review from a different account, and any merge performed by the optional merge App carries both the approval label and an approved review. The last one passes vacuously on an instance that does not use the merge App.

The script ships with defaults for the canonical `iamers/steve-agent` instance. Override the following environment variables to run it unchanged against another repo or bot account:

- `STEVE_HOST` — SSH alias for the instance host (or pass it as the first positional argument).
- `STEVE_BOT_PATTERN` — committer pattern used by the "main free of bot pushes" check, matched case-insensitively against `%cn|%ce` (default: `scrat-ai`).
- `STEVE_REPO` — `owner/name` passed to `gh pr view --repo` by the "main merges have approved reviews" check (default: `iamers/steve-agent`).
- `STEVE_REVIEW_BASELINE` — first-parent-history commit subject prefix that anchors the review guard; merges at or before it are treated as historical exceptions (default: `Merge pull request #26 `).

### Run Drift Check

The drift check compares live configuration against the blueprint:

```bash
./instance/drift-check.sh
```

If drift is detected (e.g., new keys added by the installer), update the `instance/env.template` file to include them, then re-run the check. The drift check also verifies worker profiles have the required symlinks for git and GitHub CLI access.

### Worker Profiles (Kanban)

Kanban workers run with an isolated home directory (`~/.hermes/profiles/<worker>/home`) and don't see the user's `~/.gitconfig` or `~/.config/gh`. Without proper setup, git pushes fail and `gh` CLI appears "not logged in."

#### Credential Modes

Worker profiles support two credential modes, controlled by `instance/profiles/<name>/credentials.mode`:

- **shared** (default): Credentials are symlinks to the instance user's config. Use `provision-worker.sh` to create the symlinks. The drift check verifies `home/.gitconfig` → `~/.gitconfig` and `home/.config/gh` → `~/.config/gh`.

- **isolated**: Credentials are independent from the instance user. The profile has its own GitHub identity (e.g., a reviewer profile with separate auth). For isolated profiles, run `HOME=~/.hermes/profiles/<name>/home gh auth login` directly—do not use `provision-worker.sh`. The drift check verifies `home/.config/gh` is a real directory containing `hosts.yml` and `home/.gitconfig` is not a symlink at all (regular file or absent).

Canonical profile configs (`instance/profiles/<name>/config.yaml`) are versioned in the repo and checked by drift-check for consistency with live instances.

Create a worker profile:

```bash
hermes profile create <worker-name> --clone
```

Provision shared profiles:

```bash
cd ~/repos/steve-agent/instance
./provision-worker.sh <worker-name>
```

If drift check reports non-conformant profiles, re-run `provision-worker.sh` on the instance (for shared) or re-authenticate with `gh auth login` (for isolated).

#### Kanban Board Backup

Schedule automated backups of `~/.hermes/kanban.db` (retains last 7 backups):

```bash
# Add to crontab: crontab -e
0 2 * * * cd ~/repos/steve-agent/instance && ./backup-kanban.sh
```

The backup script uses SQLite online backup API (safe with active databases) and is silent on success (designed for cron watchdog mode).

#### Merge-Gate Scan (Phase 2 Automation)

`instance/merge-gate-scan.sh` is the deterministic scanner that sits in front of
`merge-gate.sh`: every tick it finds open PRs carrying the approval label
(`steve-approved`) and invokes the gate on each one. It has no merge logic of
its own and no LLM — it is designed to run under a `--no-agent` cron job where
empty stdout means silence (nothing to report), exactly like `pr-watch.sh` and
`backup-kanban.sh`.

Anti-noise behavior (a cron ticks every 5 minutes, so it must not flood the
channel):

- No labeled PRs → empty stdout (total silence).
- A reject already reported with the same reason → silence (state tracked in
  `~/.hermes/state/merge-gate-seen.txt`, keyed by `<pr>\t<reason>`).
- A reject with a NEW reason → printed once, then recorded.
- A successful merge → ALWAYS printed (one-shot event) and the state for that
  PR is cleared.

Anti-concurrency: the scanner takes `flock` on
`~/.hermes/state/merge-gate-scan.lock`; if an instance is already running it
exits 0 silently.

Verify the scanner locally before registering it (both degrade cleanly without
credentials — the gate reports the missing auth, the scanner stays silent if
`gh` is unauthenticated):

```bash
./instance/merge-gate-scan.sh --dry-run      # list candidates + gate decisions, no merge
./instance/merge-gate-scan.sh                # runtime scan (silent on nothing-to-do)
```

##### Registering the cron job

Hermes cron jobs live in the Hermes DB, not on the filesystem. Register the
scanner as a thin wrapper that `exec`s the canonical repo script (same pattern
as the pr-watch and backup-kanban wrappers). Create
`~/.hermes/scripts/merge-gate-cron.sh`:

```bash
#!/usr/bin/env bash
# Wrapper cron: esegue lo scanner canonico del repo. Stdout vuoto = silenzio.
exec bash "$HOME/repos/steve-agent/instance/merge-gate-scan.sh" 2>&1
```

Then register it with the Hermes scheduler:

```bash
hermes cron create '*/5 * * * *' --script merge-gate-cron.sh --no-agent --deliver <platform:chat:thread>
```

Flag breakdown:

- `*/5 * * * *` — every 5 minutes.
- `--script merge-gate-cron.sh` — points at the wrapper (resolved under
  `~/.hermes/scripts/`).
- `--no-agent` — no LLM is spawned; the scheduler runs the script and delivers
  its stdout verbatim. Empty stdout = nothing is sent (the watchdog pattern).
- `--deliver <platform:chat:thread>` — the destination the scanner output is
  fanned out to (e.g. `telegram:<group-chat-id>:<topic-thread-id>`). Replace
  with the instance's merge-notifications topic.

The cron inherits its configuration from the instance `~/.hermes/.env`:
`STEVE_REPO`, `STEVE_MERGE_APP_ID`, `STEVE_MERGE_KEY_PATH`, and
`STEVE_APPROVAL_LABEL=steve-approved` (see section 8 for the full list). The
coordinator applies this canonical label and the scanner queries the same
value. These variables must be present in the cron's environment — the wrapper
relies on them, and no secrets are hardcoded in the script or the wrapper
itself.

IMPORTANT: none of this runtime wiring is covered by `drift-check.sh`. The
wrapper is runtime-only, the cron registration lives in the Hermes DB, and the
current drift check does not compare the versioned scanner with its deployed
copy. On a fresh instance, manually deploy or copy the scanner, recreate the
wrapper, re-run the `hermes cron create` command above, and verify all three.

##### Activation is an ops step

The repo ships only the scanner (`instance/merge-gate-scan.sh`) and this
documentation. Creating the wrapper at `~/.hermes/scripts/merge-gate-cron.sh`
and registering the cron job with `hermes cron create` are **runtime
activation steps** performed by the coordinator on the instance host, not
files committed to the repo. A fresh deploy needs both steps re-run by hand.

## 8. GitHub merge App (optional)

> Questa sezione è FACOLTATIVA. Se la salti, non creare la GitHub App, non
> valorizzare le chiavi `STEVE_MERGE_*`, NON registrare il cron del merge gate
> — e tutto il resto (board, worker, review, merge umano su GitHub) funziona
> identico. Il main-guard v2 in smoke.sh passa a vuoto (nessun merge App da
> verificare) e lo smoke resta verde. Lo scanner `merge-gate-scan.sh` esce in
> silenzio quando le credenziali non sono configurate (non è un guasto).

The deterministic merge gate (`instance/merge-gate.sh`) merges safe-tier PRs
under a dedicated GitHub App identity. Each instance owns its OWN App and
installs it on its repo only; the App private key is never shared. The reason
is technical: a GitHub App private key lives at the App level, so whoever
holds it can mint tokens for every installation of that App. A shared App
would let one instance merge into every other instance's repo. See
`.steve/pr-lifecycle.md` for the full design.

### Create the App

1. Under the owning org/user, create a new GitHub App
   (Settings -> Developer settings -> GitHub Apps -> New GitHub App).
2. Name and slug it for this instance. The canonical instance uses App slug
   `steve-merge`, owner `iamers`, installed on repo `steve-agent` only.
3. Set the permissions:
   - Repository permissions -> `Contents`: Read and write (required by the
     merge endpoint).
   - Repository permissions -> `Pull requests`: Read-only.
   - Repository permissions -> `Checks`: Read-only. Without `checks=read`,
     the check-runs endpoint returns 403 and condition (c) of the gate fails
     for every PR.
4. Leave `Webhook` disabled: the gate is invoked by cron or an operator, not
   by webhook events. No webhook URL is configured.
5. Create the App, then generate and download a private key (`.pem`). Store
   it on the instance host only.

### Install the App

Install the App on the repo only (the per-instance contract). After
installing, note the numeric App id shown on the App's General settings page.

### Configure the merge gate

Set these in `~/.hermes/.env` on the instance host (or pass them in the
environment when running the gate):

```bash
printf "STEVE_REPO=iamers/steve-agent\n" >> ~/.hermes/.env
printf "STEVE_MERGE_APP_ID=<numeric-app-id>\n" >> ~/.hermes/.env
printf "STEVE_MERGE_KEY_PATH=/srv/ha-<name>/keys/steve-merge.private-key.pem\n" >> ~/.hermes/.env
printf "STEVE_APPROVAL_LABEL=steve-approved\n" >> ~/.hermes/.env
```

Optional:

- `STEVE_REVIEWER_LOGIN` restricts condition (b) to an APPROVED review from
  this specific login. If unset, the gate accepts an APPROVED review from any
  account other than the PR author.

The installation id is NOT configured. The gate derives it at runtime from
the repo via the GitHub API, so a reinstall (which changes the id) is handled
automatically. The private key never appears in stdout, stderr, logs, or
error messages; on API failure the gate reports only the HTTP status.

### Verify the gate (no merge)

```bash
./instance/merge-gate.sh --self-test        # decision logic, no network
./instance/merge-gate.sh --dry-run <pr>      # evaluate one PR, print decision
```

`--self-test` exercises the decision logic with injected fixtures and needs
no credentials. `--dry-run` evaluates all conditions for a PR and prints the
decision without merging. Run `<pr>` (no flag) to evaluate and merge if every
condition passes; the gate always uses a merge commit, never squash (see the
comment in the script).

## 9. Gotchas and Common Issues

| # | Issue | Solution |
|---|-------|----------|
| 1 | When migrating from another agent runtime, its config may store an API key as a JSON *reference* to an env var (`{"id": "SOME_API_KEY", "source": "env"}`) rather than the literal secret | Resolve the reference and place the actual value in `~/.hermes/.env` |
| 2 | The `.env` file seeded by the installer doesn't end with a newline | Use `printf "\nKEY=...\n"` instead of `echo` or appending with `\n` prefix |
| 3 | The default `config.yaml` contains `model.base_url: https://openrouter.ai/api/v1` | Remove it with `sed -i '/^model.base_url/d'` once your provider is set (it's ignored, but it misleads readers) |
| 3b | `hermes auth add <provider> --type oauth` silently registers nothing when stdin is piped: the import prompt is skipped | Run it from a real terminal, or the first turn fails with `No Codex credentials stored` |
| 4 | `getUpdates` returns empty until the bot receives a fresh event after being added to the group | Send a mention or message to the bot after adding it, then call `getUpdates` |
| 5 | `journalctl --user` as the service user via non-interactive SSH gives "No journal files were opened" | Use `~/.hermes/logs/gateway.log` or `sudo journalctl _UID=<uid>` as a sudo user |
| 6 | `hermes gateway restart` makes the old process exit with status=75/TEMPFAIL, appearing as an error in logs | This is normal restart mechanics, not an error |
| 7 | The `--commit` pin must use a commit hash, not a tag | Tags break on `git pull --ff-only` when re-running the installer |
| 8 | Interactive prompts appear even with `--skip-setup` when running in a TTY (tmux) | Answer `n` to install prompts for ripgrep and build tools (pre-installed) |
| 9 | The pre-commit hook is not installed, or its denylist is not reachable | The privacy guard silently protects nothing and emits no warning; install the hook in the instance clone and verify that the denylist is reachable |

## 10. Next Steps

After installation is complete:

1. Create worker profiles for your team: `hermes profile create --clone`
2. Initialize the kanban board: `hermes kanban init`
3. Assign the first real repository task so Hermes creates its task worktree and launches a worker. From that worker process, verify that the denylist configured during privacy guard installation was inherited and is active:

   ```bash
   test -n "${PRIVACY_DENYLIST:-}"
   test -r "$PRIVACY_DENYLIST"
   grep -qEv '^[[:space:]]*(#|$)' "$PRIVACY_DENYLIST"
   bash scripts/check_privacy.sh instance/INSTALL.md
   ```

4. Configure topic-skill bindings and channel prompts for your workflow
5. Set up branch protection and rulesets on the main branch (requires paid GitHub plan)
6. Configure GitHub authentication for bot commits if needed

## 11. Maintenance

- Upgrades: Run the installer with the same `--commit` pin or a new commit hash
- Config changes: Commit changes to the blueprint repo, then apply to the instance
- Verification: Run smoke and drift checks regularly
- Monitoring: Check `~/.hermes/logs/gateway.log` and systemctl status
