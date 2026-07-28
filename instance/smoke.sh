#!/usr/bin/env bash
# Smoke test di una istanza Steve (Hermes). Esegue da una macchina admin con
# alias SSH verso l'utente dell'istanza.
# Uso: ./smoke.sh [ssh-alias] [--llm] | ./smoke.sh --self-test
# --llm aggiunge una query reale al modello (costa una chiamata LLM).
set -u

HERMES_PIN="3ef6bbd2"   # commit del tag v2026.7.20 (v0.19.0)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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

# unexpected_listeners <instance-uid> <allowlist-file> reads the allowlist as
# literal records and the output of `ss -H -O -tlne` from standard input, then
# prints listeners owned by the instance user whose local address is neither
# IPv4 127/8 nor IPv6 ::1. System services (including SSH) have a different
# owner and remain outside this check's boundary. Returns 0 when it finds at
# least one unexpected line, 1 when all lines are allowed, and 2 when the
# output cannot be verified.
unexpected_listeners() {
  local instance_uid="$1" allowed_listeners_file="$2"
  awk -v instance_uid="$instance_uid" '
    FILENAME != "-" {
      if ($0 !~ /^[[:space:]]*$/ && $0 !~ /^[[:space:]]*#/) {
        allowed[$0] = 1
      }
      next
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
  ' "$allowed_listeners_file" -
}

# Reads the allowlist records. Returns 3 only when the path does not exist and
# 2 when an existing path cannot be read in full.
read_allowed_listeners() { # read_allowed_listeners <path>
  local allowed_file="$1"
  case "$allowed_file" in
    \~/*) allowed_file="$HOME/${allowed_file#??}" ;;
    /*) ;;
    *) allowed_file="$HOME/$allowed_file" ;;
  esac
  if [ ! -e "$allowed_file" ]; then
    return 3
  fi
  if [ ! -r "$allowed_file" ]; then
    printf 'allowed listeners file is unreadable\n' >&2
    return 2
  fi
  if ! cat -- "$allowed_file"; then
    printf 'allowed listeners file could not be read\n' >&2
    return 2
  fi
}

# listener_verdict <query-rc> <instance-uid> <ss-output> <allowlist-rc> <allowlist-output>
# Returns 0 only if the remote query succeeded and every listener owned by the
# instance user is loopback or appears exactly in the allowlist. Missing
# extended metadata, a missing tool, an ss/SSH error, an unreadable allowlist,
# and every non-loopback listener not in the allowlist fail closed. A missing
# allowlist is equivalent to an empty list.
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
    3) allowlist_output='' ;;
    *)
      printf 'listener inspection unavailable (allowed listeners query exit %s): %s\n' \
        "$allowlist_rc" "$allowlist_output"
      return 2
      ;;
  esac
  unexpected=$(printf '%s\n' "$listener_output" | \
    unexpected_listeners "$instance_uid" <(printf '%s\n' "$allowlist_output"))
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
  local allowlist_rc="${6:-3}" allowlist_output="${7:-}" actual
  listener_verdict "$query_rc" "$instance_uid" "$output" \
    "$allowlist_rc" "$allowlist_output" >/dev/null 2>&1
  actual=$?
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: ${label}: expected rc=${expected}, got rc=${actual}"
    return 1
  fi
  echo "ok: ${label} -> rc=${actual}"
}

listener_self_test_path_case() { # listener_self_test_path_case <label> <expected-rc> <instance-uid> <output> <allowlist-path>
  local label="$1" expected="$2" instance_uid="$3" output="$4" allowlist_path="$5"
  local allowlist_output allowlist_rc actual
  allowlist_output=$(read_allowed_listeners "$allowlist_path" 2>&1)
  allowlist_rc=$?
  listener_verdict 0 "$instance_uid" "$output" \
    "$allowlist_rc" "$allowlist_output" >/dev/null 2>&1
  actual=$?
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: ${label}: expected rc=${expected}, got rc=${actual}"
    return 1
  fi
  echo "ok: ${label} -> rc=${actual}"
}

run_listener_self_test() {
  local failures=0 fixture_dir read_failure_path literal_allowlist
  fixture_dir=$(mktemp -d) || {
    echo "listener self-test FAILED: cannot create fixture directory"
    return 1
  }
  read_failure_path="$fixture_dir/read-failure"
  literal_allowlist="$fixture_dir/literal-backslash"
  mkdir "$read_failure_path" || return 1
  printf '%s\n' 'junk\n192.0.2.10:8080' >"$literal_allowlist" || return 1
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
    'LISTEN 0 128 192.0.2.10:8080 0.0.0.0:* uid:1001 ino:25 sk:13' 3 '' || failures=$((failures+1))
  listener_self_test_path_case "present directory read failure fails closed" 2 1001 '' \
    "$read_failure_path" || failures=$((failures+1))
  listener_self_test_path_case "literal backslash cannot inject an allowed listener" 1 1001 \
    'LISTEN 0 128 192.0.2.10:8080 0.0.0.0:* uid:1001 ino:26 sk:14' \
    "$literal_allowlist" || failures=$((failures+1))
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

run_pr_watch_self_test() {
  local fixture_dir output last_non_empty non_empty_count
  fixture_dir=$(mktemp -d "${TMPDIR:-/tmp}/pr-watch-selftest.XXXXXX")
  mkdir -p "$fixture_dir/bin" "$fixture_dir/home"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'printf '\''called\\n'\'' >"$HOME/gh-called"' \
    'printf '\''[]\\n'\''' >"$fixture_dir/bin/gh"
  chmod +x "$fixture_dir/bin/gh"

  output=$(HOME="$fixture_dir/home" PATH="$fixture_dir/bin:$PATH" \
    "$SCRIPT_DIR/pr-watch.sh" "owner/repo")
  if [ ! -s "$fixture_dir/home/gh-called" ]; then
    echo "FAIL: pr-watch no-PR output: gh fixture was not exercised"
    return 1
  fi
  last_non_empty=$(printf '%s\n' "$output" | awk 'NF { last=$0 } END { print last }')
  non_empty_count=$(printf '%s\n' "$output" | awk 'NF { count++ } END { print count+0 }')

  if [ "$last_non_empty" != '{"wakeAgent": false}' ]; then
    echo "FAIL: pr-watch no-PR output: expected final non-empty line {\"wakeAgent\": false}, got '${last_non_empty}'"
    return 1
  fi
  if [ "$non_empty_count" -ne 1 ]; then
    echo "FAIL: pr-watch no-PR output: expected only the wake gate, got ${non_empty_count} non-empty lines"
    return 1
  fi
  echo "ok: pr-watch no-PR output ends with the silent wake gate and nothing else"
}

if [ "${1:-}" = "--self-test" ]; then
  [ "$#" -eq 1 ] || { echo "usage: $0 --self-test" >&2; exit 2; }
  self_test_failures=0
  run_listener_self_test || self_test_failures=$((self_test_failures+1))
  run_pr_watch_self_test || self_test_failures=$((self_test_failures+1))
  [ "$self_test_failures" -eq 0 ]
  exit $?
fi

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"
LLM_CHECK=0
[ "${2:-}" = "--llm" ] && LLM_CHECK=1

check_listeners() {
  local out rc verdict instance_uid listener_output
  local allowed_output allowed_rc allowed_file_q allowed_reader
  printf -v allowed_file_q '%q' "$STEVE_ALLOWED_LISTENERS_FILE"
  allowed_reader=$(declare -f read_allowed_listeners)
  allowed_output=$(ssh -T -o ConnectTimeout=10 "$HOST" \
    "$allowed_reader; read_allowed_listeners $allowed_file_q" 2>&1)
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
# Post-hoc guard on main (until branch protection is available on the private
# repo): the first-parent history of origin/main must contain no commit with a
# scrat-ai-* COMMITTER (direct bot pushes or merges performed by the bot).
# Commits AUTHORED by the bot that arrived through a PR merged/squashed by a
# human are legitimate and do not match (committer = human or GitHub).
check "main free of bot pushes" 'if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && ! git log --first-parent origin/main -30 --format="%cn|%ce" | grep -qi "'"$STEVE_BOT_PATTERN"'"; else true; fi'
# Post-hoc review guard (main-guard v2, building block 1): Free GitHub cannot
# enforce "require review before merge". For each merge commit on main after
# the merge that introduced this check (PR #26, dynamic baseline), verify that
# the PR has at least one APPROVED review from an account other than the author.
# Merges before the baseline (including PR #23, an operations hotfix without a
# review during a reviewer outage) are historical exceptions documented in the
# operations journal. Direct pushes without a PR remain covered by the check
# above.
check "main merges have approved reviews" 'export PATH=$HOME/.local/bin:$PATH; if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main && baseline=$(git log --first-parent origin/main --format="%H %s" | grep "'"$STEVE_REVIEW_BASELINE"'" | head -1 | cut -d" " -f1); if [ -z "$baseline" ]; then echo "review baseline not in first-parent history (main-guard v2 not yet active; nothing to audit)"; else prs=$(git log --first-parent ${baseline}..origin/main --format="%s" | grep -oE "Merge pull request #[0-9]+" | grep -oE "[0-9]+" || true); for pr in $prs; do data=$(gh pr view "$pr" --repo "'"$STEVE_REPO"'" --json reviews,author 2>/dev/null); [ -n "$data" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) gh lookup failed or not authenticated" >&2; exit 1; }; author=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[\"author\"][\"login\"])" 2>/dev/null); [ -n "$author" ] || { echo "REVIEW MISSING: PR #$pr (author: unknown) malformed review data" >&2; exit 1; }; approved=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d[\"author\"][\"login\"]; print(any(r.get(\"state\")==\"APPROVED\" and (r.get(\"author\") or {}).get(\"login\") not in (None, \"\", a) for r in d.get(\"reviews\",[])))" 2>/dev/null); [ "$approved" = "True" ] || { echo "REVIEW MISSING: PR #$pr (author: $author) merged without approved review from a different account" >&2; exit 1; }; done; fi; fi'

# Main-guard v2 guard (building block 2): for every merge commit on origin/main
# whose AUTHOR is the merge App identity (STEVE_MERGE_BOT, for example
# steve-merge[bot]), require the corresponding PR to have BOTH:
# 1. The approval label (STEVE_APPROVAL_LABEL, exact match)
# 2. An APPROVED review from an account other than the PR author.
# An App-authored merge without a label or a review is an INCIDENT (compromised
# key or bypassed gate): the check FAILS and prints the PR number. If there are
# no App-authored merges yet, it passes vacuously. Human merges and bot pushes
# remain covered by the two checks above.
check "app merges are gated (label + review)" 'export PATH=$HOME/.local/bin:$PATH; if [ -d ~/repos/steve-agent/.git ]; then cd ~/repos/steve-agent && git fetch -q origin main; bot_prs=$(git log --first-parent origin/main --format="%an|%s" | { while IFS="|" read -r an subject; do [ "$an" = "'"$STEVE_MERGE_BOT"'" ] && printf "%s\n" "$subject"; done; } | grep -oE "Merge pull request #[0-9]+" | grep -oE "[0-9]+" || true); if [ -z "$bot_prs" ]; then echo "no App-authored merges in first-parent history (nothing to audit)"; else for pr in $bot_prs; do data=$(gh pr view "$pr" --repo "'"$STEVE_REPO"'" --json labels,reviews,author 2>/dev/null); [ -n "$data" ] || { echo "APP MERGE UNGATED: PR #$pr merged by App identity '"$STEVE_MERGE_BOT"'; gh lookup failed or not authenticated" >&2; exit 1; }; label_ok=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(any(i.get(\"name\")==sys.argv[1] for i in d.get(\"labels\",[])))" "'"$STEVE_APPROVAL_LABEL"'" 2>/dev/null); approved=$(printf "%s" "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d[\"author\"][\"login\"]; print(any(r.get(\"state\")==\"APPROVED\" and (r.get(\"author\") or {}).get(\"login\") not in (None, \"\", a) for r in d.get(\"reviews\",[])))" 2>/dev/null); [ "$label_ok" = "True" ] && [ "$approved" = "True" ] || { echo "APP MERGE UNGATED: PR #$pr (merged by App identity '"$STEVE_MERGE_BOT"') missing approval label '"$STEVE_APPROVAL_LABEL"' or approved review from a different account" >&2; exit 1; }; done; fi; fi'

if [ "$LLM_CHECK" = 1 ]; then
  check "llm one-shot reply"   'export PATH=$HOME/.local/bin:$PATH; timeout 120 hermes -z "Rispondi con una sola parola: ok" | grep -qi ok'
fi

echo "----"
echo "smoke: $pass pass, $fail fail"
exit "$([ "$fail" -eq 0 ] && echo 0 || echo 1)"
