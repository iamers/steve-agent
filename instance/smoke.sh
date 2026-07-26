#!/usr/bin/env bash
# Smoke test di una istanza Steve (Hermes). Esegue da una macchina admin con
# alias SSH verso l'utente dell'istanza.
# Uso: ./smoke.sh [ssh-alias] [--llm] | ./smoke.sh --self-test
# --llm aggiunge una query reale al modello (costa una chiamata LLM).
set -u

HERMES_PIN="7c1a0295"   # commit del tag v2026.7.1 (v0.18.0)

# Instance-specific knobs (defaults reproduce the canonical iamers/steve-agent
# instance; override via the environment to reuse the script on another repo).
STEVE_BOT_PATTERN="${STEVE_BOT_PATTERN:-scrat-ai}"
STEVE_REPO="${STEVE_REPO:-iamers/steve-agent}"
STEVE_REVIEW_BASELINE="${STEVE_REVIEW_BASELINE:-Merge pull request #26 }"
# App author identity whose merges are audited by the main-guard v2 check
# below: a merge executed by the GitHub App has AUTHOR = this identity while
# COMMITTER = GitHub/web-flow, so App merges are matched by author, not committer.
STEVE_MERGE_BOT="${STEVE_MERGE_BOT:-steve-merge[bot]}"
# Approval label required on every App-merged PR (same label the merge gate
# checks; exact match, no substring, like label_present in merge-gate.sh).
STEVE_APPROVAL_LABEL="${STEVE_APPROVAL_LABEL:-steve-approved}"

pass=0; fail=0
check() { # check <label> <command>
  local label="$1"; shift
  if out=$(ssh -o ConnectTimeout=10 "$HOST" "$@" 2>&1); then
    echo "PASS  $label"; pass=$((pass+1))
  else
    echo "FAIL  $label"; echo "      $out" | head -3; fail=$((fail+1))
  fi
}

# unexpected_listeners <ssh-port> legge l'output di `ss -H -tln` e stampa le
# righe il cui indirizzo locale non e' IPv4 127/8 ne' IPv6 ::1, eccetto il porto
# server della connessione SSH usata come control plane. Come grep, ritorna 0
# quando trova almeno una riga inattesa e 1 quando tutte le righe sono ammesse.
unexpected_listeners() {
  local ssh_port="$1"
  awk -v ssh_port="$ssh_port" '
    function listener_port(address, value) {
      value = address
      sub(/^.*:/, "", value)
      return value
    }
    NF && $4 !~ /^127\./ && $4 !~ /^\[::1\]:/ && listener_port($4) != ssh_port {
      print
      found = 1
    }
    END { exit(found ? 0 : 1) }
  '
}

# listener_verdict <query-rc> <ssh-port> <ss-output>
# Ritorna 0 solo se la query remota e' riuscita e ogni listener e' loopback.
# Il listener SSH sul porto della connessione corrente e' il solo control-plane
# ammesso. Metadata assente, tool assente, errore di ss/SSH e ogni altro listener
# non-loopback falliscono chiusi.
listener_verdict() {
  local query_rc="$1" ssh_port="$2" listener_output="$3" unexpected
  if [ "$query_rc" -ne 0 ]; then
    printf 'listener inspection unavailable (remote query exit %s): %s\n' \
      "$query_rc" "$listener_output"
    return 2
  fi
  case "$ssh_port" in
    ''|*[!0-9]*)
      printf 'listener inspection unavailable (invalid SSH server port: %s)\n' "$ssh_port"
      return 2
      ;;
  esac
  if [ "$ssh_port" -lt 1 ] || [ "$ssh_port" -gt 65535 ]; then
    printf 'listener inspection unavailable (invalid SSH server port: %s)\n' "$ssh_port"
    return 2
  fi
  if unexpected=$(printf '%s\n' "$listener_output" | unexpected_listeners "$ssh_port"); then
    printf 'unexpected listener(s):\n%s\n' "$unexpected"
    return 1
  fi
  return 0
}

listener_self_test_case() { # listener_self_test_case <label> <expected-rc> <query-rc> <ssh-port> <output>
  local label="$1" expected="$2" query_rc="$3" ssh_port="$4" output="$5" actual
  listener_verdict "$query_rc" "$ssh_port" "$output" >/dev/null
  actual=$?
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: ${label}: expected rc=${expected}, got rc=${actual}"
    return 1
  fi
  echo "ok: ${label} -> rc=${actual}"
}

run_listener_self_test() {
  local failures=0
  listener_self_test_case "loopback and SSH listeners pass" 0 0 22 \
    $'LISTEN 0 128 127.0.0.1:8000 0.0.0.0:*\nLISTEN 0 128 [::1]:8000 [::]:*\nLISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 128 [::]:22 [::]:*' || failures=$((failures+1))
  listener_self_test_case "unexpected non-loopback listener fails" 1 0 22 \
    'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*' || failures=$((failures+1))
  listener_self_test_case "unavailable ss fails closed" 2 127 '' \
    'ss is unavailable' || failures=$((failures+1))
  listener_self_test_case "missing SSH port fails closed" 2 0 '' '' || failures=$((failures+1))
  if [ "$failures" -ne 0 ]; then
    echo "listener self-test FAILED: ${failures} assertion(s) failed"
    return 1
  fi
  echo "listener self-test ok"
}

if [ "${1:-}" = "--self-test" ]; then
  [ "$#" -eq 1 ] || { echo "usage: $0 --self-test" >&2; exit 2; }
  run_listener_self_test
  exit $?
fi

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"
LLM_CHECK=0
[ "${2:-}" = "--llm" ] && LLM_CHECK=1

check_listeners() {
  local out rc verdict ssh_port listener_output
  out=$(ssh -o ConnectTimeout=10 "$HOST" \
    'command -v ss >/dev/null 2>&1 || { echo "ss is unavailable" >&2; exit 127; }; set -- ${SSH_CONNECTION:-}; [ "$#" -eq 4 ] || { echo "SSH_CONNECTION is unavailable" >&2; exit 126; }; printf "%s\n" "$4"; ss -H -tln')
  rc=$?
  ssh_port=${out%%$'\n'*}
  if [ "$out" = "$ssh_port" ]; then
    listener_output=''
  else
    listener_output=${out#*$'\n'}
  fi
  if verdict=$(listener_verdict "$rc" "$ssh_port" "$listener_output"); then
    echo "PASS  no unexpected listeners"; pass=$((pass+1))
  else
    echo "FAIL  no unexpected listeners"
    echo "      $verdict" | head -3
    fail=$((fail+1))
  fi
}

check "ssh reachable"        'true'
check "hermes version pinned" "export PATH=\$HOME/.local/bin:\$PATH; hermes --version | grep -q $HERMES_PIN"
check "gateway service active" 'systemctl --user is-active hermes-gateway | grep -qx active'
check "telegram connected (log)" 'grep -q "telegram connected" ~/.hermes/logs/gateway.log'
# Credenziali: le chiavi Telegram vivono nel .env, quella del provider LLM nel
# pool `hermes auth` (OAuth, non una variabile d'ambiente). Verificarle entrambe
# nello stesso check tiene il conto degli step invariato e copre il percorso LLM
# vero, non la sola presenza di una stringa nel .env.
check "credentials present"  'for k in TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS TELEGRAM_GROUP_ALLOWED_CHATS TELEGRAM_HOME_CHANNEL; do grep -qE "^$k=." ~/.hermes/.env || exit 1; done; export PATH=$HOME/.local/bin:$PATH; hermes auth status openai-codex 2>&1 | grep -q "logged in"'
check "env perms 600"        'stat -c %a ~/.hermes/.env | grep -qx 600'
check_listeners
# Guardia post-hoc su main (finche' branch protection non e' disponibile sul
# repo privato): sulla first-parent history di origin/main non devono comparire
# commit con COMMITTER scrat-ai-* (push diretti del bot o merge eseguiti dal
# bot). I commit AUTHORED dal bot arrivati via merge/squash di una PR mergiata
# da un umano sono legittimi e non matchano (committer = umano o GitHub).
check "main free of bot pushes" 'if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && ! git log --first-parent origin/main -30 --format="%cn|%ce" | grep -qi "'"$STEVE_BOT_PATTERN"'"; else true; fi'
# Guardia review a posteriori (main-guard v2, mattone 1): su Free GitHub non si
# puo' imporre "require review before merge". Per ogni merge commit su main
# successivo al merge che ha introdotto questo check (PR #26, baseline dinamica),
# verifica che la PR abbia almeno una review APPROVED da un account diverso
# dall'autore. I merge precedenti alla baseline (inclusa la PR #23, hotfix ops
# senza review durante outage reviewer) sono eccezioni storiche documentate nel
# journal ops. I push diretti senza PR restano coperti dal check sopra.
check "main merges have approved reviews" 'export PATH=$HOME/.local/bin:$PATH; if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && baseline=$(git log --first-parent origin/main --format="%H %s" | grep "'"$STEVE_REVIEW_BASELINE"'" | head -1 | cut -d" " -f1); if [ -z "$baseline" ]; then echo "review baseline not in first-parent history (main-guard v2 not yet active; nothing to audit)"; else prs=$(git log --first-parent ${baseline}..origin/main --format="%s" | grep -oE "Merge pull request #[0-9]+" | grep -oE "[0-9]+" || true); for pr in $prs; do data=$(gh pr view "$pr" --repo "'"$STEVE_REPO"'" --json reviews,author 2>/dev/null); [ -n "$data" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) gh lookup failed or not authenticated" >&2; exit 1; }; author=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[\"author\"][\"login\"])" 2>/dev/null); [ -n "$author" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) malformed review data" >&2; exit 1; }; approved=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d[\"author\"][\"login\"]; print(any(r.get(\"state\")==\"APPROVED\" and (r.get(\"author\") or {}).get(\"login\") not in (None, \"\", a) for r in d.get(\"reviews\",[])))" 2>/dev/null); [ "$approved" = "True" ] || { echo "REVIEW MISSING: PR #$pr (author: $author) merged without approved review from a different account" >&2; exit 1; }; done; fi; fi'

# Guardia main-guard v2 (mattone 2): per ogni merge commit su origin/main
# il cui AUTHOR e' l'identita' del merge App (STEVE_MERGE_BOT, es.
# steve-merge[bot]), richiede che la PR corrispondente abbia ENTRAMBE:
# 1. L'etichetta di approvazione (STEVE_APPROVAL_LABEL, match esatto)
# 2. Una review APPROVED da un account diverso dall'autore della PR.
# Un App-authored merge senza label o senza review e' un INCIDENT (chiave
# compromessa o gate bypassato): il check FALLISCE e stampa il numero di PR.
# Se non esiste ancora nessun App-authored merge, passa vacuamente. I merge
# umani e i push del bot restano coperti dai due check sopra.
check "app merges are gated (label + review)" 'export PATH=$HOME/.local/bin:$PATH; if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main; bot_prs=$(git log --first-parent origin/main --format="%an|%s" | { while IFS="|" read -r an subject; do [ "$an" = "'"$STEVE_MERGE_BOT"'" ] && printf "%s\n" "$subject"; done; } | grep -oE "Merge pull request #[0-9]+" | grep -oE "[0-9]+" || true); if [ -z "$bot_prs" ]; then echo "no App-authored merges in first-parent history (nothing to audit)"; else for pr in $bot_prs; do data=$(gh pr view "$pr" --repo "'"$STEVE_REPO"'" --json labels,reviews,author 2>/dev/null); [ -n "$data" ] || { echo "APP MERGE UNGATED: PR #$pr merged by App identity '"$STEVE_MERGE_BOT"'; gh lookup failed or not authenticated" >&2; exit 1; }; label_ok=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(any(i.get(\"name\")==sys.argv[1] for i in d.get(\"labels\",[])))" "'"$STEVE_APPROVAL_LABEL"'" 2>/dev/null); approved=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d[\"author\"][\"login\"]; print(any(r.get(\"state\")==\"APPROVED\" and (r.get(\"author\") or {}).get(\"login\") not in (None, \"\", a) for r in d.get(\"reviews\",[])))" 2>/dev/null); [ "$label_ok" = "True" ] && [ "$approved" = "True" ] || { echo "APP MERGE UNGATED: PR #$pr (merged by App identity '"$STEVE_MERGE_BOT"') missing approval label '"$STEVE_APPROVAL_LABEL"' or approved review from a different account" >&2; exit 1; }; done; fi; fi'

if [ "$LLM_CHECK" = 1 ]; then
  check "llm one-shot reply"   'export PATH=$HOME/.local/bin:$PATH; timeout 120 hermes -z "Rispondi con una sola parola: ok" | grep -qi ok'
fi

echo "----"
echo "smoke: $pass pass, $fail fail"
exit "$([ "$fail" -eq 0 ] && echo 0 || echo 1)"
