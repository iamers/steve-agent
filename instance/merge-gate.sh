#!/usr/bin/env bash
# merge-gate.sh: deterministic merge gate for safe-tier pull requests.
#
# Decides whether a PR meets ALL merge conditions from .steve/pr-lifecycle.md
# and, only if every condition is true, executes the merge. The pure decision
# logic is separated from execution, so --self-test exercises it with injected
# fixtures (no network, no credentials), the same way tools/pr-brief.py does.
#
# Conditions (pr-lifecycle.md, the gate):
#   (a) the approval label is present on the PR
#   (b) there is a review in APPROVED state from the reviewer identity on the
#       latest commit
#   (c) CI is green on the latest commit
#   (d) the PR tier is 'safe', recomputed locally by tools/pr-brief.py
#       (path matching), NEVER trusted from the PR body
#   (e) base is main, the PR is mergeable, and no push happened after the
#       approve (recorded approve SHA == current head SHA)
#
# Merge method: MERGE COMMIT, not squash. This is binding and intentional: the
# review guard in instance/smoke.sh finds merged PRs by searching for
# "Merge pull request #<n>" in the first-parent history subjects. Squash
# removes that pattern, so App-merged PRs become invisible to the guard and
# open a detection hole. Do NOT change merge_method to squash.
#
# Auth: a JWT signed with the GitHub App private key, exchanged for an
# ephemeral installation token. The token and the key NEVER appear in stdout,
# stderr, logs, or error messages. On API failure only the HTTP status is
# reported, never the token.
#
# Usage:
#   ./merge-gate.sh --self-test                 decision logic with fixtures
#   ./merge-gate.sh --dry-run <pr>              evaluate, print decision, no merge
#   ./merge-gate.sh <pr>                        evaluate and merge if approved
#
# Env vars (see instance/env.template):
#   STEVE_REPO            owner/name (e.g. iamers/steve-agent)
#   STEVE_MERGE_APP_ID    GitHub App id (the per-instance merge identity)
#   STEVE_MERGE_KEY_PATH  path to the App private key (.pem)
#   STEVE_REVIEWER_LOGIN  authorized reviewer GitHub login (optional; if unset,
#                         (b) accepts an APPROVED review from any non-author)
#   STEVE_APPROVAL_LABEL  approval label (default: approved)
set -u

readonly APPROVAL_LABEL_DEFAULT="approved"
readonly API_BASE="https://api.github.com"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly SCRIPT_DIR
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
readonly REPO_ROOT

# ===========================================================================
# Pure decision logic (no network, no credentials). --self-test covers this.
# Inputs are simple strings: "1" = true, "0" = false; d_tier is a tier name.
# ===========================================================================

# policy_copy_verdict <behind_count>
# Prints "ok" when origin/main has no commits absent from HEAD, "stale" when it
# does, and "unknown" for an invalid count. Pure: no git repository or network.
policy_copy_verdict() {
    local behind_count="$1"
    case "$behind_count" in
        ''|*[!0-9]*) echo "unknown"; return 2 ;;
    esac
    if [ "$behind_count" -gt 0 ]; then
        echo "stale"
        return 1
    fi
    echo "ok"
    return 0
}

# decide_merge <a_label> <b_review> <c_ci> <d_tier> <e_base_main> <e_mergeable> <e_sha_match>
# Prints "MERGE: ..." and returns 0 if all conditions pass.
# Prints "REJECT: ..." and returns 1 otherwise. Order is deliberate: the first
# failing condition names itself in the reason.
decide_merge() {
    local a_label="$1" b_review="$2" c_ci="$3" d_tier="$4"
    local e_base_main="$5" e_mergeable="$6" e_sha_match="$7"

    if [ "$a_label" != "1" ]; then
        echo "REJECT: (a) approval label is not present"
        return 1
    fi
    if [ "$b_review" != "1" ]; then
        echo "REJECT: (b) no APPROVED review from the reviewer on the latest commit"
        return 1
    fi
    if [ "$c_ci" != "1" ]; then
        echo "REJECT: (c) CI is not green on the latest commit"
        return 1
    fi
    if [ "$d_tier" != "safe" ]; then
        echo "REJECT: (d) PR tier is ${d_tier}, not safe"
        return 1
    fi
    if [ "$e_base_main" != "1" ]; then
        echo "REJECT: (e) base branch is not main"
        return 1
    fi
    if [ "$e_mergeable" != "1" ]; then
        echo "REJECT: (e) PR is not mergeable"
        return 1
    fi
    if [ "$e_sha_match" != "1" ]; then
        echo "REJECT: (e) head moved after the approve (recorded SHA differs from current head)"
        return 1
    fi
    echo "MERGE: all conditions met"
    return 0
}

# ci_verdict <checkruns_ok> <combined_state> <legacy_total_count>
# Prints "1" (green) or "0" (not green). Pure: no network, no credentials.
# Encodes the SOLE interpretation of CI state so --self-test can cover it;
# cond_ci() calls this after gathering the raw fields.
#
# Inputs:
#   checkruns_ok        "1" if every check-run is completed+success, else "0".
#   combined_state      legacy /commits/<sha>/status "state" field (may be "").
#   legacy_total_count  legacy /commits/<sha>/status "total_count" field.
#
# The legacy combined state is honored ONLY when legacy statuses actually exist
# (total_count > 0). GitHub sends state="pending" with total_count=0 on repos
# that use only GitHub Actions: that aggregate "pending" must NOT declass a
# green check-run result, since there are no real statuses to evaluate.
ci_verdict() {
    local checkruns_ok="$1" combined_state="$2" legacy_total_count="$3"
    # Check-runs are the primary verdict: not all success -> not green.
    [ "$checkruns_ok" = "1" ] || { echo "0"; return; }
    # Sanitize total_count to an integer (treat non-numeric/empty as 0).
    case "$legacy_total_count" in
        ''|*[!0-9]*) legacy_total_count=0 ;;
    esac
    # Degrade only when a real legacy status exists and is not green.
    if [ "$legacy_total_count" -gt 0 ]; then
        case "$combined_state" in
            success) : ;;            # legacy statuses are green
            *) echo "0"; return ;;   # pending/failure/error/"" -> a legacy status is not green
        esac
    fi
    echo "1"
}

# label_present <target> <name1> <name2> ...
# Prints "1" if <target> exactly equals one of the provided names, else "0".
# Pure: no network, no file reads. Exact comparison only (no substring), so
# "steve-approved" will NOT match "steve-approved-x". cond_label() gathers the
# names from the labels endpoint and hands them here; --self-test covers the
# membership edge cases directly.
label_present() {
    local target="$1"; shift
    local n
    for n in "$@"; do
        [ "$n" = "$target" ] && { echo "1"; return; }
    done
    echo "0"
}

# ===========================================================================
# Self-test: exercises decide_merge with injected fixtures (no network).
# Mirrors tools/pr-brief.py --self-test.
# ===========================================================================

SELFTEST_FAILS=0

# _selftest_check <desc> <expected(MERGE|REJECT)> <reason-substring> <7 args>
_selftest_check() {
    local desc="$1" exp_verdict="$2" exp_reason="$3"; shift 3
    local verdict got_verdict
    verdict=$(decide_merge "$@")
    got_verdict=${verdict%%:*}
    if [ "$got_verdict" != "$exp_verdict" ]; then
        echo "FAIL: ${desc}: expected ${exp_verdict}, got verdict '${got_verdict}' (full: ${verdict})"
        SELFTEST_FAILS=$((SELFTEST_FAILS + 1))
        return
    fi
    if [ -n "$exp_reason" ]; then
        case "$verdict" in
            *"$exp_reason"*) ;;
            *)
                echo "FAIL: ${desc}: expected reason containing '${exp_reason}', got '${verdict}'"
                SELFTEST_FAILS=$((SELFTEST_FAILS + 1))
                return
                ;;
        esac
    fi
    echo "ok: ${desc} -> ${verdict}"
}

# _selftest_ci <desc> <checkruns_ok> <combined_state> <legacy_total_count> <expected(1|0)>
# Exercises the pure ci_verdict() function with injected inputs.
_selftest_ci() {
    local desc="$1" exp="$5"
    local got
    got=$(ci_verdict "$2" "$3" "$4")
    if [ "$got" != "$exp" ]; then
        echo "FAIL: ${desc}: ci_verdict($2,$3,$4) expected ${exp}, got '${got}'"
        SELFTEST_FAILS=$((SELFTEST_FAILS + 1))
        return
    fi
    echo "ok: ${desc} -> ${got}"
}

# _selftest_label <desc> <target> <name1> <name2> ... <expected(1|0)>
# Last positional arg is the expected value. Exercises the pure label_present()
# function with injected inputs. Guards the array-parsing bug and the substring
# trap: a partial name must NOT count as a match.
_selftest_label() {
    local desc="$1" target="$2"; shift 2
    local exp="${!#}"        # last positional parameter (indirect expansion)
    local got
    got=$(label_present "$target" "${@:1:$#-1}")
    if [ "$got" != "$exp" ]; then
        echo "FAIL: ${desc}: label_present($target, [${*}]) expected ${exp}, got '${got}'"
        SELFTEST_FAILS=$((SELFTEST_FAILS + 1))
        return
    fi
    echo "ok: ${desc} -> ${got}"
}

# _selftest_policy_copy <desc> <behind_count> <expected_verdict> <expected_rc>
# Exercises the pure policy_copy_verdict() function with injected inputs.
_selftest_policy_copy() {
    local desc="$1" behind_count="$2" exp_verdict="$3" exp_rc="$4"
    local got_verdict got_rc
    got_verdict=$(policy_copy_verdict "$behind_count")
    got_rc=$?
    if [ "$got_verdict" != "$exp_verdict" ] || [ "$got_rc" -ne "$exp_rc" ]; then
        echo "FAIL: ${desc}: expected ${exp_verdict} (rc=${exp_rc}), got '${got_verdict}' (rc=${got_rc})"
        SELFTEST_FAILS=$((SELFTEST_FAILS + 1))
        return
    fi
    echo "ok: ${desc} -> ${got_verdict} (rc=${got_rc})"
}

run_self_test() {
    # Policy-copy freshness is an evaluator precondition, not a PR condition.
    _selftest_policy_copy "policy copy: behind=0 is current" 0 ok 0
    _selftest_policy_copy "policy copy: behind=3 is stale" 3 stale 1
    _selftest_policy_copy "policy copy: invalid count is unknown" invalid unknown 2

    # All conditions true -> MERGE.
    _selftest_check "all conditions true" "MERGE" "" 1 1 1 safe 1 1 1

    # Each condition false individually -> REJECT, with the right reason.
    _selftest_check "(a) label absent" "REJECT" "(a)" 0 1 1 safe 1 1 1
    _selftest_check "(b) no approved review" "REJECT" "(b)" 1 0 1 safe 1 1 1
    _selftest_check "(c) CI not green" "REJECT" "(c)" 1 1 0 safe 1 1 1
    _selftest_check "(e) base not main" "REJECT" "main" 1 1 1 safe 0 1 1
    _selftest_check "(e) not mergeable" "REJECT" "mergeable" 1 1 1 safe 1 0 1
    _selftest_check "(e) head moved" "REJECT" "head moved" 1 1 1 safe 1 1 0

    # Tier above safe -> REJECT even when everything else is green.
    _selftest_check "(d) tier=propagation" "REJECT" "propagation" 1 1 1 propagation 1 1 1
    _selftest_check "(d) tier=blast" "REJECT" "blast" 1 1 1 blast 1 1 1

    # (d) safe-tier reason must not be confused with the others.
    _selftest_check "(d) tier=safe passes" "MERGE" "" 1 1 1 safe 1 1 1

    # ci_verdict: the pure CI interpretation extracted from cond_ci. These guard
    # the bug where state="pending" with total_count=0 declasses a green
    # check-run result on repos that use only GitHub Actions.
    _selftest_ci "ci_verdict: checkruns ok, no legacy statuses (THE BUG)" 1 pending 0 1
    _selftest_ci "ci_verdict: checkruns ok, legacy green" 1 success 3 1
    _selftest_ci "ci_verdict: checkruns ok, legacy failure declasses" 1 failure 2 0
    _selftest_ci "ci_verdict: checkruns red stays red" 0 success 0 0
    # Edge: non-numeric/empty total_count is treated as 0 (no legacy statuses).
    _selftest_ci "ci_verdict: garbage total_count treated as 0" 1 pending "" 1

    # label_present: the pure membership check extracted from cond_label. These
    # guard the bug where the labels endpoint returns an ARRAY of objects and
    # read_field("name") threw on int("name") -> empty -> label never found.
    # They also guard the substring trap: a partial name must NOT match.
    _selftest_label "label_present: exact single" "steve-approved" "steve-approved" 1
    _selftest_label "label_present: exact in list" "steve-approved" "other" "steve-approved" 1
    _selftest_label "label_present: empty list" "steve-approved" 0
    _selftest_label "label_present: substring must not match" "steve-approved" "steve-approved-x" 0
    _selftest_label "label_present: split tokens must not match" "steve-approved" "steve" "approved" 0

    if [ "$SELFTEST_FAILS" -ne 0 ]; then
        echo "self-test FAILED: ${SELFTEST_FAILS} assertion(s) failed"
        return 1
    fi
    echo "self-test ok"
    return 0
}

# ===========================================================================
# JSON helper (python3, like tools/pr-brief.py). Reads a file and prints the
# value at a dot path, or empty string when absent. Never prints errors to
# stderr that could leak response bodies: failures are silent (empty value).
# ===========================================================================

read_field() {
    # read_field <file> <dot.path>  -> prints value (or empty)
    python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, json
file_path, dot_path = sys.argv[1], sys.argv[2]
try:
    with open(file_path) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
val = data
for key in dot_path.split("."):
    if isinstance(val, list):
        try:
            val = val[int(key)]
        except (ValueError, IndexError):
            val = None
    elif isinstance(val, dict):
        val = val.get(key)
    else:
        val = None
    if val is None:
        break
print("" if val is None else val)
PY
}

# ===========================================================================
# HTTP + auth helpers. The token and key never reach stdout/stderr.
# ===========================================================================

GH_API_BODY=""

setup_temp() {
    GH_API_BODY=$(mktemp "${TMPDIR:-/tmp}/merge-gate.XXXXXX")
    trap 'rm -f "$GH_API_BODY"' EXIT
}

# b64url: base64url without padding.
b64url() {
    openssl base64 -A 2>/dev/null | tr '+/' '-_' | tr -d '='
}

# build_jwt <app_id> <key_path>: prints a GitHub App JWT (RS256) to stdout.
# The key is read by openssl only; nothing sensitive is printed.
build_jwt() {
    local app_id="$1" key_path="$2"
    local now exp header payload header_b64 payload_b64 signing_input sig
    now=$(date +%s)
    exp=$((now + 600))
    header='{"alg":"RS256","typ":"JWT"}'
    payload="{\"iat\":${now},\"exp\":${exp},\"iss\":\"${app_id}\"}"
    header_b64=$(printf '%s' "$header" | b64url)
    payload_b64=$(printf '%s' "$payload" | b64url)
    signing_input="${header_b64}.${payload_b64}"
    sig=$(printf '%s' "$signing_input" | openssl dgst -sha256 -sign "$key_path" 2>/dev/null | b64url)
    [ -n "$sig" ] || return 1
    printf '%s.%s\n' "$signing_input" "$sig"
}

# gh_api <method> <auth_value> <path> [json_body]
# Writes the response body to $GH_API_BODY and prints ONLY the HTTP status code
# to stdout. Never prints the body or the auth value.
gh_api() {
    local method="$1" auth="$2" path="$3" body="${4:-}"
    local args=(-sS -o "$GH_API_BODY" -w '%{http_code}'
        -H "Authorization: ${auth}"
        -H "Accept: application/vnd.github+json"
        -H "X-GitHub-Api-Version: 2022-11-28"
        -X "$method")
    [ -n "$body" ] && args+=(-d "$body")
    curl "${args[@]}" "${API_BASE}${path}"
}

# fail_status <label> <status>: report a non-2xx with only the status code.
fail_status() {
    echo "error: $1 (HTTP $2)" >&2
    return 1
}

# resolve_installation_token <app_id> <key_path> <repo>
# Derives the installation id at runtime from the repo, then exchanges a JWT
# for an ephemeral token. Sets MERGE_TOKEN. Never prints the token.
# Returns 1 (with HTTP status) on any failure.
resolve_installation_token() {
    local app_id="$1" key_path="$2" repo="$3"
    local jwt owner repo_name status inst_id tok
    jwt=$(build_jwt "$app_id" "$key_path") || { echo "error: could not build App JWT (is the private key readable?)" >&2; return 1; }
    owner=${repo%%/*}
    repo_name=${repo#*/}
    # Installation id derived from the repo, never hardcoded (survives reinstall).
    status=$(gh_api GET "Bearer ${jwt}" "/repos/${owner}/${repo_name}/installation")
    if ! echo "$status" | grep -q '^2'; then
        fail_status "could not resolve installation for ${repo}" "$status"
        return 1
    fi
    inst_id=$(read_field "$GH_API_BODY" "id")
    [ -n "$inst_id" ] || { echo "error: installation id missing from response" >&2; return 1; }
    status=$(gh_api POST "Bearer ${jwt}" "/app/installations/${inst_id}/access_tokens")
    if ! echo "$status" | grep -q '^2'; then
        fail_status "could not mint installation token" "$status"
        return 1
    fi
    tok=$(read_field "$GH_API_BODY" "token")
    [ -n "$tok" ] || { echo "error: token missing from response" >&2; return 1; }
    MERGE_TOKEN="$tok"
    return 0
}

# ===========================================================================
# Condition gatherers. Each sets a COND_* global ("1"/"0") and, when it cannot
# be determined, a NOTE_* message. They never print the token.
# ===========================================================================

# fetch_pr_meta <token> <repo> <pr>: sets PR_HEAD_SHA, PR_BASE, PR_MERGEABLE.
fetch_pr_meta() {
    local token="$1" repo="$2" pr="$3" status
    PR_HEAD_SHA="" PR_BASE="" PR_MERGEABLE="0"
    status=$(gh_api GET "token ${token}" "/repos/${repo}/pulls/${pr}")
    echo "$status" | grep -q '^2' || return 1
    PR_HEAD_SHA=$(read_field "$GH_API_BODY" "head.sha")
    PR_BASE=$(read_field "$GH_API_BODY" "base.ref")
    PR_MERGEABLE=$(read_field "$GH_API_BODY" "mergeable")
    return 0
}

# cond_label <token> <repo> <pr> <label>: sets COND_A_LABEL.
cond_label() {
    local token="$1" repo="$2" pr="$3" label="$4" status names
    COND_A_LABEL="0"
    status=$(gh_api GET "token ${token}" "/repos/${repo}/issues/${pr}/labels")
    echo "$status" | grep -q '^2' || return 1
    # The labels endpoint returns an ARRAY of objects ([{"name":"steve-approved",...}]).
    # read_field() walks a dot path and for arrays expects a NUMERIC index, so
    # read_field(...,"name") does int("name") -> exception -> empty string. That
    # made the label unreachable for ANY label. Parse the array directly here,
    # then do an exact membership check via label_present() (no substring match,
    # so "steve-approved" will not match "steve-approved-x").
    names=$(python3 - "$GH_API_BODY" <<'PY' 2>/dev/null
import sys, json
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
print("\n".join(str(l.get("name", "")) for l in data if isinstance(l, dict)))
PY
)
    local -a name_arr=()
    if [ -n "$names" ]; then
        # name_arr is the whitespace-separated list of label names.
        while IFS= read -r ln; do
            [ -n "$ln" ] && name_arr+=("$ln")
        done <<<"$names"
    fi
    COND_A_LABEL=$(label_present "$label" "${name_arr[@]}")
    return 0
}

# cond_review <token> <repo> <pr> <head_sha> [reviewer_login]
# Sets COND_B_REVIEW and APPROVE_SHA (the SHA the approval was made against).
cond_review() {
    local token="$1" repo="$2" pr="$3" head_sha="$4" reviewer="${5:-}" status
    COND_B_REVIEW="0"; APPROVE_SHA=""
    status=$(gh_api GET "token ${token}" "/repos/${repo}/pulls/${pr}/reviews")
    echo "$status" | grep -q '^2' || return 1
    # Walk the reviews; an APPROVED on the head commit (from the reviewer, if
    # configured, else any non-author) provides the approve SHA.
    APPROVE_SHA=$(python3 - "$GH_API_BODY" "$head_sha" "$reviewer" <<'PY' 2>/dev/null
import sys, json
body_file, head_sha, reviewer = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    reviews = json.load(open(body_file))
except Exception:
    sys.exit(0)
# Newest-first ordering is not guaranteed; prefer the latest APPROVED on head.
best = ""
for r in reviews:
    if r.get("state") != "APPROVED":
        continue
    if reviewer and (r.get("user") or {}).get("login") != reviewer:
        continue
    if r.get("commit_id") == head_sha:
        best = r.get("commit_id", "")
        break
    if not best:
        best = r.get("commit_id", "") or best
print(best)
PY
)
    [ -n "$APPROVE_SHA" ] && COND_B_REVIEW="1"
    return 0
}

# cond_ci <token> <repo> <head_sha>: sets COND_C_CI.
# Green = all check-runs completed with conclusion success, and the legacy
# combined commit status is green OR absent (total_count=0). Incomplete or
# failing -> not green. The state interpretation lives in ci_verdict() (pure).
cond_ci() {
    local token="$1" repo="$2" head_sha="$3" status
    local checkruns_ok combined_state legacy_total_count
    COND_C_CI="0"
    status=$(gh_api GET "token ${token}" "/repos/${repo}/commits/${head_sha}/check-runs")
    echo "$status" | grep -q '^2' || return 1
    checkruns_ok=$(python3 - "$GH_API_BODY" <<'PY' 2>/dev/null
import sys, json
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
runs = data.get("check_runs", []) if isinstance(data, dict) else []
if not runs:
    print("0")          # no CI at all -> not green
    sys.exit(0)
ok = all(r.get("status") == "completed" and r.get("conclusion") == "success" for r in runs)
print("1" if ok else "0")
PY
)
    # Legacy combined status: green by default; honored only if it exists.
    combined_state=""
    legacy_total_count=0
    status=$(gh_api GET "token ${token}" "/repos/${repo}/commits/${head_sha}/status")
    if echo "$status" | grep -q '^2'; then
        combined_state=$(read_field "$GH_API_BODY" "state")
        legacy_total_count=$(read_field "$GH_API_BODY" "total_count")
    fi
    COND_C_CI=$(ci_verdict "$checkruns_ok" "$combined_state" "$legacy_total_count")
    return 0
}

# cond_tier <repo> <pr>: recomputes the tier locally via tools/pr-brief.py
# (path matching), never trusting the PR body. Sets COND_D_TIER.
cond_tier() {
    local repo="$1" pr="$2" tier
    COND_D_TIER=""
    tier=$(cd "$REPO_ROOT" && python3 tools/pr-brief.py --repo "$repo" --pr "$pr" 2>/dev/null \
        | sed -n 's/^Tier:[[:space:]]*//p' | head -1 | tr '[:upper:]' '[:lower:]')
    COND_D_TIER=${tier:-""}
    return 0
}

# ===========================================================================
# Evaluator precondition. This describes the machine making the decision, not
# the pull request, so it deliberately stays outside decide_merge().
# ===========================================================================

check_policy_copy_current() {
    local behind_count verdict

    echo "policy precondition: checking local policy copy against origin/main"
    if ! git -C "$REPO_ROOT" fetch --quiet origin main; then
        echo "REFUSE: policy copy freshness is unknown: fetch of origin/main failed" >&2
        return 2
    fi
    if ! behind_count=$(git -C "$REPO_ROOT" rev-list --count HEAD..origin/main); then
        echo "REFUSE: policy copy freshness is unknown: could not count commits behind origin/main" >&2
        return 2
    fi

    verdict=$(policy_copy_verdict "$behind_count")
    case "$verdict" in
        ok)
            echo "policy precondition: local policy copy is current (0 commits behind origin/main)"
            return 0
            ;;
        stale)
            echo "REFUSE: policy copy is stale by ${behind_count} commit(s) behind origin/main" >&2
            return 1
            ;;
        *)
            echo "REFUSE: policy copy freshness is unknown: invalid behind count '${behind_count}'" >&2
            return 2
            ;;
    esac
}

# ===========================================================================
# Evaluate all conditions and decide. Prints the verdict + per-condition
# detail. Returns decide_merge's exit code (0 = MERGE).
# ===========================================================================

evaluate() {
    local pr="$1" repo="${STEVE_REPO:-}" app_id="${STEVE_MERGE_APP_ID:-}"
    local key_path="${STEVE_MERGE_KEY_PATH:-}" reviewer="${STEVE_REVIEWER_LOGIN:-}"
    local label="${STEVE_APPROVAL_LABEL:-$APPROVAL_LABEL_DEFAULT}"
    local token

    COND_A_LABEL="0"; COND_B_REVIEW="0"; COND_C_CI="0"; COND_D_TIER=""
    COND_E_BASE_MAIN="0"; COND_E_MERGEABLE="0"; COND_E_SHA_MATCH="0"
    NOTE_AUTH=""

    if [ -z "$repo" ]; then
        echo "error: STEVE_REPO is not set (e.g. iamers/steve-agent)" >&2
        return 2
    fi

    # Tier is computed locally (path matching); it does not need the App token,
    # only an authenticated gh for pr-brief.py. Best-effort; "" = cannot check.
    cond_tier "$repo" "$pr" || true

    # Conditions that need the App identity. Degrade gracefully: without auth,
    # report "cannot check" and run the decision logic on what we have.
    if [ -z "$app_id" ] || [ -z "$key_path" ] || [ ! -f "$key_path" ]; then
        NOTE_AUTH="cannot check label/review/CI/base/mergeable (STEVE_MERGE_APP_ID or STEVE_MERGE_KEY_PATH not available)"
    else
        setup_temp
        if resolve_installation_token "$app_id" "$key_path" "$repo"; then
            token="$MERGE_TOKEN"
            fetch_pr_meta "$token" "$repo" "$pr" || true
            cond_label "$token" "$repo" "$pr" "$label" || true
            cond_review "$token" "$repo" "$pr" "$PR_HEAD_SHA" "$reviewer" || true
            cond_ci "$token" "$repo" "$PR_HEAD_SHA" || true
            [ "$PR_BASE" = "main" ] && COND_E_BASE_MAIN="1"
            [ "$PR_MERGEABLE" = "True" ] && COND_E_MERGEABLE="1"
            if [ -n "$APPROVE_SHA" ] && [ -n "$PR_HEAD_SHA" ] \
               && [ "$APPROVE_SHA" = "$PR_HEAD_SHA" ]; then
                COND_E_SHA_MATCH="1"
            fi
            # Unset the token as soon as the conditions are gathered.
            token=""; MERGE_TOKEN=""
        else
            NOTE_AUTH="cannot check label/review/CI/base/mergeable (auth failed; see HTTP status above)"
        fi
    fi

    local d_tier="${COND_D_TIER:-unknown}"
    [ -z "$COND_D_TIER" ] && d_tier="unknown"

    echo "---- conditions for PR #${pr} (${repo}) ----"
    echo "  (a) approval label '${label}': ${COND_A_LABEL}"
    echo "  (b) approved review on latest commit: ${COND_B_REVIEW}"
    echo "  (c) CI green on latest commit: ${COND_C_CI}"
    echo "  (d) tier (local recompute): ${d_tier}"
    echo "  (e) base=main: ${COND_E_BASE_MAIN}, mergeable: ${COND_E_MERGEABLE}, sha match: ${COND_E_SHA_MATCH}"
    [ -n "$NOTE_AUTH" ] && echo "  note: ${NOTE_AUTH}"

    decide_merge "$COND_A_LABEL" "$COND_B_REVIEW" "$COND_C_CI" "$d_tier" \
        "$COND_E_BASE_MAIN" "$COND_E_MERGEABLE" "$COND_E_SHA_MATCH"
}

# ===========================================================================
# Merge execution. Called only after a MERGE verdict. Uses merge commit.
# ===========================================================================

do_merge() {
    local pr="$1" repo="${STEVE_REPO:-}" app_id="${STEVE_MERGE_APP_ID:-}"
    local key_path="${STEVE_MERGE_KEY_PATH:-}" token status
    setup_temp
    resolve_installation_token "$app_id" "$key_path" "$repo" || return 1
    token="$MERGE_TOKEN"
    status=$(gh_api PUT "token ${token}" "/repos/${repo}/pulls/${pr}/merge" \
        "{\"merge_method\":\"merge\",\"commit_title\":\"Merge pull request #${pr}\"}")
    token=""; MERGE_TOKEN=""
    if echo "$status" | grep -q '^2'; then
        echo "merged: PR #${pr} via merge commit (HTTP ${status})"
        return 0
    fi
    fail_status "merge failed for PR #${pr}" "$status"
    return 1
}

# ===========================================================================
# Entry point / arg parsing
# ===========================================================================

main() {
    local pr
    case "${1:-}" in
        --self-test)
            run_self_test
            return $?
            ;;
        --dry-run)
            pr="${2:-}"
            [ -n "$pr" ] || { echo "usage: merge-gate.sh --dry-run <pr>" >&2; return 2; }
            check_policy_copy_current || return $?
            evaluate "$pr"
            return $?
            ;;
        ""|-h|--help)
            sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            return 0
            ;;
        *)
            pr="$1"
            local verdict rc
            check_policy_copy_current || return $?
            verdict=$(evaluate "$pr"); rc=$?
            echo "$verdict"
            if [ "$rc" -eq 0 ]; then
                do_merge "$pr" || return $?
                return 0
            fi
            return "$rc"
            ;;
    esac
}

main "$@"
