#!/usr/bin/env bash
# Smoke test di una istanza Steve (Hermes). Esegue da una macchina admin con
# alias SSH verso l'utente dell'istanza. Uso: ./smoke.sh [ssh-alias] [--llm]
# --llm aggiunge una query reale al modello (costa una chiamata LLM).
set -u

HOST="${1:-ha-steve-dev}"
HERMES_PIN="7c1a0295"   # commit del tag v2026.7.1 (v0.18.0)
LLM_CHECK=0
[ "${2:-}" = "--llm" ] && LLM_CHECK=1

pass=0; fail=0
check() { # check <label> <command>
  local label="$1"; shift
  if out=$(ssh -o ConnectTimeout=10 "$HOST" "$@" 2>&1); then
    echo "PASS  $label"; pass=$((pass+1))
  else
    echo "FAIL  $label"; echo "      $out" | head -3; fail=$((fail+1))
  fi
}

check "ssh reachable"        'true'
check "hermes version pinned" "export PATH=\$HOME/.local/bin:\$PATH; hermes --version | grep -q $HERMES_PIN"
check "gateway service active" 'systemctl --user is-active hermes-gateway | grep -qx active'
check "telegram connected (log)" 'grep -q "telegram connected" ~/.hermes/logs/gateway.log'
check "env keys present"     'for k in GLM_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS TELEGRAM_GROUP_ALLOWED_CHATS TELEGRAM_HOME_CHANNEL; do grep -qE "^$k=." ~/.hermes/.env || exit 1; done'
check "env perms 600"        'stat -c %a ~/.hermes/.env | grep -qx 600'
check "no unexpected listeners" '! ss -tln 2>/dev/null | grep -vE "127.0.0.1|\[::1\]" | grep -q LISTEN || true'

if [ "$LLM_CHECK" = 1 ]; then
  check "llm one-shot reply"   'export PATH=$HOME/.local/bin:$PATH; timeout 120 hermes -z "Rispondi con una sola parola: ok" | grep -qi ok'
fi

echo "----"
echo "smoke: $pass pass, $fail fail"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
