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
# File locale all'istanza con gli endpoint non-loopback attesi. Un percorso
# relativo viene risolto dalla home dell'utente remoto.
STEVE_ALLOWED_LISTENERS_FILE="${STEVE_ALLOWED_LISTENERS_FILE:-~/.hermes/private/allowed-listeners.txt}"
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

# unexpected_listeners <instance-uid> legge l'output di `ss -H -O -tlne` e stampa
# i listener dell'utente istanza il cui indirizzo locale non è IPv4 127/8 né
# IPv6 ::1. I servizi di sistema (incluso SSH) hanno un owner diverso e restano
# fuori dal confine di questa verifica. Ritorna 0 quando trova almeno una riga
# inattesa, 1 quando tutte le righe sono ammesse e 2 per output non verificabile.
unexpected_listeners() {
  local instance_uid="$1" allowed_listeners="$2"
  awk -v instance_uid="$instance_uid" -v allowed_listeners="$allowed_listeners" '
    BEGIN {
      allowed_count = split(allowed_listeners, allowed_line, "\n")
      for (i = 1; i <= allowed_count; i++) {
        if (allowed_line[i] !~ /^[[:space:]]*$/ && \
            allowed_line[i] !~ /^[[:space:]]*#/) {
          allowed[allowed_line[i]] = 1
        }
      }
    }
    NF {
      if ($0 !~ / ino:[0-9]+/ || $0 !~ / sk:[0-9a-fA-F]+/) {
        invalid = 1
        next
      }
      if ($4 !~ /^127\./ && $4 !~ /^\[::1\]:/ && \
          $0 ~ (" uid:" instance_uid "([[:space:]]|$)") && !($4 in allowed)) {
        print
        found = 1
      }
    }
    END {
      if (invalid) exit 2
      exit(found ? 0 : 1)
    }
  '
}

# listener_verdict <query-rc> <instance-uid> <ss-output> <allowlist-rc> <allowlist-output>
# Ritorna 0 solo se la query remota è riuscita e ogni listener dell'utente
# istanza è loopback o compare esattamente nella allowlist. Metadata esteso
# assente, tool assente, errore di ss/SSH, allowlist illeggibile e ogni listener
# non-loopback non ammesso falliscono chiusi. Una allowlist assente equivale a
# una lista vuota.
listener_verdict() {
  local query_rc="$1" instance_uid="$2" listener_output="$3"
  local allowlist_rc="$4" allowlist_output="$5" unexpected parser_rc
  if [ "$query_rc" -ne 0 ]; then
    printf 'listener inspection unavailable (remote query exit %s): %s\n' \
      "$query_rc" "$listener_output"
    return 2
  fi
  case "$instance_uid" in
    ''|*[!0-9]*)
      printf 'listener inspection unavailable (invalid instance uid: %s)\n' "$instance_uid"
      return 2
      ;;
  esac
  if [ "$instance_uid" -eq 0 ]; then
    printf 'listener inspection unavailable (instance uid must be non-root)\n'
    return 2
  fi
  case "$allowlist_rc" in
    0) ;;
    1) allowlist_output='' ;;
    *)
      printf 'listener inspection unavailable (allowed listeners query exit %s): %s\n' \
        "$allowlist_rc" "$allowlist_output"
      return 2
      ;;
  esac
  unexpected=$(printf '%s\n' "$listener_output" | \
    unexpected_listeners "$instance_uid" "$allowlist_output")
  parser_rc=$?
  case "$parser_rc" in
    0)
      printf 'unexpected listener(s):\n%s\n' "$unexpected"
      return 1
      ;;
    1)
      return 0
      ;;
    *)
      printf 'listener inspection unavailable (local parser exit %s)\n' "$parser_rc"
      return 2
      ;;
  esac
}

listener_self_test_case() { # listener_self_test_case <label> <expected-rc> <query-rc> <instance-uid> <output> [<allowlist-rc> <allowlist-output>]
  local label="$1" expected="$2" query_rc="$3" instance_uid="$4" output="$5"
  local allowlist_rc="${6:-1}" allowlist_output="${7:-}" actual
  listener_verdict "$query_rc" "$instance_uid" "$output" \
    "$allowlist_rc" "$allowlist_output" >/dev/null 2>&1
  actual=$?
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: ${label}: expected rc=${expected}, got rc=${actual}"
    return 1
  fi
  echo "ok: ${label} -> rc=${actual}"
}

run_listener_self_test() {
  local failures=0
  listener_self_test_case "loopback instance and system listeners pass" 0 0 1001 \
    $'LISTEN 0 128 127.0.0.1:8000 0.0.0.0:* uid:1001 ino:10 sk:a\nLISTEN 0 128 [::1]:8000 [::]:* uid:1001 ino:11 sk:b\nLISTEN 0 128 0.0.0.0:22 0.0.0.0:* ino:12 sk:c\nLISTEN 0 128 [::]:22 [::]:* ino:13 sk:d' || failures=$((failures+1))
  listener_self_test_case "unexpected instance listener fails" 1 0 1001 \
    'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* uid:1001 ino:20 sk:e' || failures=$((failures+1))
  listener_self_test_case "allowlisted instance listener passes" 0 0 1001 \
    'LISTEN 0 128 192.0.2.10:8080 0.0.0.0:* uid:1001 ino:22 sk:10' 0 \
    $'# expected dashboard\n\n192.0.2.10:8080' || failures=$((failures+1))
  listener_self_test_case "non-allowlisted instance listener still fails" 1 0 1001 \
    'LISTEN 0 128 192.0.2.11:8080 0.0.0.0:* uid:1001 ino:23 sk:11' 0 \
    '192.0.2.10:8080' || failures=$((failures+1))
  listener_self_test_case "unreadable allowlist fails closed" 2 0 1001 \
    'LISTEN 0 128 192.0.2.10:8080 0.0.0.0:* uid:1001 ino:24 sk:12' 2 \
    'allowed listeners file is unreadable' || failures=$((failures+1))
  listener_self_test_case "absent allowlist keeps strict behaviour" 1 0 1001 \
    'LISTEN 0 128 192.0.2.10:8080 0.0.0.0:* uid:1001 ino:25 sk:13' 1 '' || failures=$((failures+1))
  listener_self_test_case "another user listener is outside scope" 0 0 1001 \
    'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* uid:1002 ino:21 sk:f' || failures=$((failures+1))
  listener_self_test_case "missing extended metadata fails closed" 2 0 1001 \
    'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*' || failures=$((failures+1))
  listener_self_test_case "unavailable ss fails closed" 2 127 '' \
    'ss is unavailable' || failures=$((failures+1))
  listener_self_test_case "root instance uid fails closed" 2 0 0 '' || failures=$((failures+1))
  PATH=/nonexistent listener_self_test_case "missing local parser fails closed" 2 0 1001 \
    'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* uid:1001 ino:20 sk:e' || failures=$((failures+1))
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
  local out rc verdict instance_uid listener_output
  local allowed_output allowed_rc allowed_file_q
  printf -v allowed_file_q '%q' "$STEVE_ALLOWED_LISTENERS_FILE"
  allowed_output=$(ssh -T -o ConnectTimeout=10 "$HOST" \
    "allowed_file=$allowed_file_q; "'case "$allowed_file" in "~/"*) allowed_file="$HOME/${allowed_file#??}" ;; /*) ;; *) allowed_file="$HOME/$allowed_file" ;; esac; if [ ! -e "$allowed_file" ]; then exit 1; fi; if [ ! -r "$allowed_file" ]; then echo "allowed listeners file is unreadable" >&2; exit 2; fi; cat -- "$allowed_file"' 2>&1)
  allowed_rc=$?
  out=$(ssh -T -o ConnectTimeout=10 "$HOST" \
    'command -v ss >/dev/null 2>&1 || { echo "ss is unavailable" >&2; exit 127; }; instance_uid=$(id -u) || { echo "instance uid is unavailable" >&2; exit 126; }; printf "%s\n" "$instance_uid"; unset COLUMNS; ss -H -O -tlne')
  rc=$?
  instance_uid=${out%%$'\n'*}
  if [ "$out" = "$instance_uid" ]; then
    listener_output=''
  else
    listener_output=${out#*$'\n'}
  fi
  if verdict=$(listener_verdict "$rc" "$instance_uid" "$listener_output" \
    "$allowed_rc" "$allowed_output"); then
    echo "PASS  no unexpected instance listeners"; pass=$((pass+1))
  else
    echo "FAIL  no unexpected instance listeners"
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
