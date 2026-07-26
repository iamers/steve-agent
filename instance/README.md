# instance/ — Steve instance blueprint

Canonical, versioned, secret-free copy of the configuration of a Steve instance
(Hermes Agent). It originates from the first development instance; when a second
instance exists, this blueprint is the candidate to become a rendered template.

## Contents

| File | Role |
|---|---|
| `config.yaml` | canonical copy of the instance's `~/.hermes/config.yaml` |
| `env.template` | keys required in `~/.hermes/.env` (names only, never values) |
| `smoke.sh` | checks instance health (pinned version, gateway, telegram, env) |
| `drift-check.sh` | compares live config with repo; reports drift, does not restore |

## Anti-drift rule

1. Make configuration changes FIRST in the repo copy, then apply them to the
   instance (never hand-edit live only).
2. If a change originated live (emergency, experiment), bring it back here
   immediately afterward and record it in the operational journal (private, `.local/ops/`).
3. When in doubt, run `drift-check.sh`: it exits 1 if drift exists.

Instance-specific identifiers (chat id, user id, host) live only in the
server-side `.env` and the private journal, never in these files.

## Usage

```bash
./smoke.sh              # default: instance via SSH alias (set STEVE_HOST or pass it as arg1)
./smoke.sh <alias> --llm   # includes a real query to the model
./drift-check.sh        # diff live config vs repo
```

Prerequisite: an SSH alias to the instance user on the machine where this is
run. The expected Hermes version is pinned in `smoke.sh` (`HERMES_PIN`).

`STEVE_HOST` is an **ops/clone-side** variable, not an instance runtime variable:
the `drift-check.sh` and `smoke.sh` scripts read it from the first argument or the
environment and run from the management clone against the instance via SSH. This
is why it does not appear in `env.template` (which lists only the instance runtime
`.env` keys): set it in the management clone environment or pass it as arg1.
