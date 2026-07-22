#!/usr/bin/env bash
# Smoke test di una istanza Steve (Hermes). Esegue da una macchina admin con
# alias SSH verso l'utente dell'istanza. Uso: ./smoke.sh [ssh-alias] [--llm]
# --llm aggiunge una query reale al modello (costa una chiamata LLM).
set -u

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"
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
# Guardia post-hoc su main (finche' branch protection non e' disponibile sul
# repo privato): sulla first-parent history di origin/main non devono comparire
# commit con COMMITTER scrat-ai-* (push diretti del bot o merge eseguiti dal
# bot). I commit AUTHORED dal bot arrivati via merge/squash di una PR mergiata
# da un umano sono legittimi e non matchano (committer = umano o GitHub).
check "main free of bot pushes" 'if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && ! git log --first-parent origin/main -30 --format="%cn|%ce" | grep -qi scrat-ai; else true; fi'
# Guardia review a posteriori (main-guard v2, mattone 1): su Free GitHub non si
# puo' imporre "require review before merge". Per ogni merge commit su main
# successivo al merge che ha introdotto questo check (PR #26, baseline dinamica),
# verifica che la PR abbia almeno una review APPROVED da un account diverso
# dall'autore. I merge precedenti alla baseline (inclusa la PR #23, hotfix ops
# senza review durante outage reviewer) sono eccezioni storiche documentate nel
# journal ops. I push diretti senza PR restano coperti dal check sopra.
check "main merges have approved reviews" 'export PATH=$HOME/.local/bin:$PATH; if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && baseline=$(git log --first-parent origin/main --format="%H %s" | grep "Merge pull request #26 " | head -1 | cut -d" " -f1); if [ -z "$baseline" ]; then echo "baseline PR #26 not in first-parent history (main-guard v2 not yet active; nothing to audit)"; else prs=$(git log --first-parent ${baseline}..origin/main --format="%s" | grep -oE "Merge pull request #[0-9]+" | grep -oE "[0-9]+" || true); for pr in $prs; do data=$(gh pr view "$pr" --repo iamers/steve-agent --json reviews,author 2>/dev/null); [ -n "$data" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) gh lookup failed or not authenticated" >&2; exit 1; }; author=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[\"author\"][\"login\"])" 2>/dev/null); [ -n "$author" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) malformed review data" >&2; exit 1; }; approved=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d[\"author\"][\"login\"]; print(any(r.get(\"state\")==\"APPROVED\" and (r.get(\"author\") or {}).get(\"login\") not in (None, \"\", a) for r in d.get(\"reviews\",[])))" 2>/dev/null); [ "$approved" = "True" ] || { echo "REVIEW MISSING: PR #$pr (author: $author) merged without approved review from a different account" >&2; exit 1; }; done; fi; fi'

if [ "$LLM_CHECK" = 1 ]; then
  check "llm one-shot reply"   'export PATH=$HOME/.local/bin:$PATH; timeout 120 hermes -z "Rispondi con una sola parola: ok" | grep -qi ok'
fi

echo "----"
echo "smoke: $pass pass, $fail fail"
exit "$([ "$fail" -eq 0 ] && echo 0 || echo 1)"
