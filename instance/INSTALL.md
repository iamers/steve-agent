# Steve Agent Instance Installation Guide

This guide walks through deploying a new Steve Agent (Hermes Agent) instance on an Ubuntu VPS. It covers prerequisites, Hermes installation, LLM provider setup, Telegram integration, gateway as a systemd service, and blueprint verification.

## 1. Prerequisites

### System Packages

Install required system packages before running the Hermes installer. The installer will prompt for these, but installing them system-wide first avoids permission issues with the service user.

```bash
sudo apt-get install -y ripgrep build-essential python3-dev libffi-dev
```

Ensure `xz-utils`, `git`, `curl`, `ffmpeg`, and `jq` are also present.

### Dedicated Unprivileged User

Create a dedicated service user following the `ha-<name>` pattern. This user will run the Hermes agent and should not have sudo privileges.

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
sudo cp /home/<your-admin-user>/.ssh/authorized_keys /srv/ha-<instance-name>.ssh/authorized_keys
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
ssh ha-<instance-name>@<vps-host>
systemctl --user is-system-running
# Expected output: running
```

Configure git identity for the service user (needed for worktree commits):

```bash
git config --global user.name "ha-<instance-name>"
git config --global user.email "ha-<instance-name>@<vps-host>.local"
```

## 2. Install Hermes

Switch to the service user and install a pinned version of Hermes Agent. Pinning by commit ensures reproducible re-installs (pinning by tag breaks on `git pull --ff-only`).

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
  | bash -s -- --skip-browser --skip-setup --commit 7c1a029553d87c43ecff8a3821336bc95872213b
```

Even with `--skip-setup`, interactive prompts may appear if running in a TTY (e.g., tmux). Answer the following:

- "Install ripgrep? [Y/n]" → `n` (already installed system-wide)
- "Install build tools? [Y/n]" → `n` (already installed system-wide)

Verify installation:

```bash
hermes --version
# Expected output: Hermes Agent v0.18.0 (2026.7.1) · local 7c1a0295

hermes doctor
# Should show only warnings for optional tools (web search keys, etc.)
```

Installation creates the following layout:
- Config: `~/.hermes/config.yaml`
- Secrets: `~/.hermes/.env`
- Code: `~/.hermes/hermes-agent` (Python 3.11.15 venv managed by uv)
- CLI: `~/.local/bin/hermes` (added to PATH in `.bashrc`)

## 3. LLM Provider Setup

This guide uses Z.AI GLM as the LLM provider with the coding plan endpoint.

### API Key Configuration

Add the API key to `~/.hermes/.env`:

```bash
printf "\nGLM_API_KEY=<your-zai-api-key>\n" >> ~/.hermes/.env
```

Set the base URL explicitly for the coding plan (Hermes can auto-detect, but explicit is deterministic):

```bash
printf "GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4\n" >> ~/.hermes/.env
```

Secure the `.env` file:

```bash
chmod 600 ~/.hermes/.env
```

### Hermes Configuration

Set the provider and default model:

```bash
hermes config set model.provider zai
hermes config set model.default glm-4.7
```

The coding plan also supports `glm-5.2`, `glm-5-turbo`, and `glm-4.5-air`. Rate limits are shared across instances on the same plan.

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

## 6. Blueprint Checks

The `instance/` directory in the steve-agent repo contains a blueprint for instance configuration and verification.

### Clone the Steve Agent Repository

```bash
mkdir -p ~/repos
cd ~/repos
git clone https://github.com/iamers/steve-agent.git
cd steve-agent
```

### Run Smoke Tests

The smoke script verifies core functionality:

```bash
./instance/smoke.sh
```

Expected: 8/8 checks PASS (latest version includes GitHub bot push protection).

### Run Drift Check

The drift check compares live configuration against the blueprint:

```bash
./instance/drift-check.sh
```

If drift is detected (e.g., new keys added by the installer), update the `instance/env.template` file to include them, then re-run the check.

## 7. Gotchas and Common Issues

| # | Issue | Solution |
|---|-------|----------|
| 1 | In openclaw.json, the `models.providers.zai.apiKey` field is a JSON reference to an env var (`{"id": "ZAI_API_KEY", "source": "env"}'), not the actual key | Place the actual key in `~/.hermes/.env` as `GLM_API_KEY=...` |
| 2 | The `.env` file seeded by the installer doesn't end with a newline | Use `printf "\nKEY=...\n"` instead of `echo` or appending with `\n` prefix |
| 3 | The default `config.yaml` contains `model.base_url: https://openrouter.ai/api/v1` | Remove it with `sed -i '/^model.base_url/d'` for the Z.AI provider (it's ignored but affects clarity) |
| 4 | `getUpdates` returns empty until the bot receives a fresh event after being added to the group | Send a mention or message to the bot after adding it, then call `getUpdates` |
| 5 | `journalctl --user` as the service user via non-interactive SSH gives "No journal files were opened" | Use `~/.hermes/logs/gateway.log` or `sudo journalctl _UID=<uid>` as a sudo user |
| 6 | `hermes gateway restart` makes the old process exit with status=75/TEMPFAIL, appearing as an error in logs | This is normal restart mechanics, not an error |
| 7 | The `--commit` pin must use a commit hash, not a tag | Tags break on `git pull --ff-only` when re-running the installer |
| 8 | Interactive prompts appear even with `--skip-setup` when running in a TTY (tmux) | Answer `n` to install prompts for ripgrep and build tools (pre-installed) |

## 8. Next Steps

After installation is complete:

1. Create worker profiles for your team: `hermes profile create --clone`
2. Initialize the kanban board: `hermes kanban init`
3. Configure topic-skill bindings and channel prompts for your workflow
4. Set up branch protection and rulesets on the main branch (requires paid GitHub plan)
5. Configure GitHub authentication for bot commits if needed

## 9. Maintenance

- Upgrades: Run the installer with the same `--commit` pin or a new commit hash
- Config changes: Commit changes to the blueprint repo, then apply to the instance
- Verification: Run smoke and drift checks regularly
- Monitoring: Check `~/.hermes/logs/gateway.log` and systemctl status