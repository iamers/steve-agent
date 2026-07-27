#!/usr/bin/env bash
# merge-gate-scan: scanner in front of the gate. It finds open PRs with the
# `steve-approved` label (configurable via STEVE_APPROVAL_LABEL) and invokes
# instance/merge-gate.sh on each one. No LLM, no merge logic of its own: it
# delegates entirely to the gate (already tested on canary #46; DO NOT modify
# it).
#
# Designed to run under cron --no-agent: EMPTY stdout = silence.
# - Feature not configured       -> empty stdout (STEVE_MERGE_APP_ID or
#                                  STEVE_MERGE_KEY_PATH missing/empty: the
#                                  merge gate is OPTIONAL, not a failure).
# - No labeled PRs               -> empty stdout (total silence, like
#                                  pr-watch.sh).
# - Same rejection already sent  -> empty stdout (anti-noise via state file).
# - Rejection with a NEW reason  -> print (only once per <pr, reason> pair).
# - Successful merge             -> ALWAYS print a readable announcement with
#                                  a link and clear the state for that PR
#                                  (one-shot event).
#
# Concurrency guard: flock on a lockfile in ~/.hermes/state. If an instance is
# already running, exit silently (exit 0).
#
# Usage:
#   ./merge-gate-scan.sh            runtime scanner (merges if the gate approves)
#   ./merge-gate-scan.sh --dry-run  list candidates + gate decisions,
#                                   DO NOT merge, DO NOT write state (manual
#                                   exploration: noise is acceptable here).
#   ./merge-gate-scan.sh --self-test
#                                   test the formatter without side effects
#
# Env vars (inherited from the cron environment, NOT passed in argv; credentials
# live in the instance .env and must NEVER be hardcoded here):
#   STEVE_REPO            owner/name (default: iamers/steve-agent)
#   STEVE_APPROVAL_LABEL  label that marks an approved PR
#                         (default: steve-approved, NOT the gate's "approved")
#   STEVE_MERGE_APP_ID, STEVE_MERGE_KEY_PATH, STEVE_REVIEWER_LOGIN
#                         gate credentials/identity (read by merge-gate.sh)
set -u

# format_merge_announcement <repository> <pr>
# Build the merge announcement. Pure function: no network, state, or reads.
format_merge_announcement() {
    local repository="$1" pr="$2"
    printf 'merged: PR #%s was merged by the gate.\n' "$pr"
    printf 'https://github.com/%s/pull/%s\n' "$repository" "$pr"
    printf 'Tier safe, and the label, the approved review, green CI and an unchanged head were all\n'
    printf 'verified before merging. Nothing for you to do.\n'
}

run_self_test() {
    local expected actual
    expected=$(printf '%s\n' \
        'merged: PR #123 was merged by the gate.' \
        'https://github.com/octo/example/pull/123' \
        'Tier safe, and the label, the approved review, green CI and an unchanged head were all' \
        'verified before merging. Nothing for you to do.')
    actual=$(format_merge_announcement "octo/example" "123")

    if [ "$actual" != "$expected" ]; then
        echo "FAIL: format_merge_announcement returned unexpected text"
        return 1
    fi
    echo "ok: format_merge_announcement -> https://github.com/octo/example/pull/123"
    echo "self-test ok"
    return 0
}

# Validate the mode before any side effects. Runtime accepts no arguments;
# --dry-run and --self-test are the explicit modes.
MODE="runtime"
case "$#:${1:-}" in
    0:) ;;
    1:--dry-run) MODE="dry-run" ;;
    1:--self-test) MODE="self-test" ;;
    *)
        echo "usage: $0 [--dry-run|--self-test]" >&2
        exit 2
        ;;
esac

if [ "$MODE" = "self-test" ]; then
    run_self_test
    exit $?
fi

# Find the repository root from the script path: instance/merge-gate-scan.sh -> root.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MERGE_GATE="$REPO_ROOT/instance/merge-gate.sh"

# Instance defaults. The canonical label is `steve-approved`, not the gate's
# internal "approved" default (the gate reads the label from the environment).
# Every fallback resolved here must be re-exported for each gate invocation.
REPO="${STEVE_REPO:-iamers/steve-agent}"
APPROVAL_LABEL="${STEVE_APPROVAL_LABEL:-steve-approved}"

# ---------------------------------------------------------------------------
# OPTIONAL feature. The merge gate (and its GitHub App) is optional: an adopter
# may not want it. If credentials are not configured, the product must work
# IDENTICALLY. In runtime mode, exit 0 in SILENCE (this is not a failure; it is
# an instance that does not use the gate). Only --dry-run prints an explanatory
# line (manual exploration: noise is acceptable).
# ---------------------------------------------------------------------------
if [ -z "${STEVE_MERGE_APP_ID:-}" ] || [ -z "${STEVE_MERGE_KEY_PATH:-}" ]; then
    if [ "$MODE" = "dry-run" ]; then
        echo "merge gate feature not configured: STEVE_MERGE_APP_ID/STEVE_MERGE_KEY_PATH not set"
    fi
    exit 0
fi

# --dry-run mode: manual exploration without lock or state. List candidates and
# call merge-gate.sh --dry-run for each one.
if [ "$MODE" = "dry-run" ]; then
    CANDIDATES=$(gh pr list --repo "$REPO" --state open \
        --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || exit 0
    [ -z "$CANDIDATES" ] && exit 0
    while IFS= read -r pr; do
        [ -z "$pr" ] && continue
        echo "=== PR #${pr} (${REPO}, label ${APPROVAL_LABEL}) ==="
        STEVE_REPO="$REPO" \
            STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
            "$MERGE_GATE" --dry-run "$pr" || true
    done <<< "$CANDIDATES"
    exit 0
fi

# From this point on, only runtime mode exists. State and lock are created after
# the optional guard, candidate query, and dry-run exit.
STATE_DIR="$HOME/.hermes/state"
STATE_FILE="$STATE_DIR/merge-gate-seen.txt"
LOCKFILE="$STATE_DIR/merge-gate-scan.lock"
mkdir -p "$STATE_DIR"
touch "$STATE_FILE"

# Concurrency LOCK: if an instance is already running, exit silently. File
# descriptor 9 remains open for the process lifetime; flock releases it on exit.
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

# The runtime query stays under the lock: two concurrent ticks must not evaluate
# or mutate the same PR in parallel. gh errors remain silent.
CANDIDATES=$(gh pr list --repo "$REPO" --state open \
    --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || exit 0
[ -z "$CANDIDATES" ] && exit 0

# ---------------------------------------------------------------------------
# Helper for anti-noise state. One line per event already reported, in
# `<pr>\t<reason>` format.
# ---------------------------------------------------------------------------

# report_reject <pr> <reason> <gate_stdout>
# Print gate output ONLY if the (pr, reason) pair is new; otherwise remain silent
# (same rejection as the previous tick). When new, record the key in the state
# file.
report_reject() {
    local pr="$1" reason="$2" gate_out="$3"
    local key
    key=$(printf '%s\t%s' "$pr" "$reason")
    if grep -qxF "$key" "$STATE_FILE" 2>/dev/null; then
        return 0
    fi
    printf '%s\n' "$gate_out"
    printf '%s\n' "$key" >> "$STATE_FILE"
}

# clear_state <pr>
# Remove all state lines for this PR. Called after successful merges: a merge is
# a one-shot event that resets noise for the PR.
clear_state() {
    local pr="$1" tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/merge-gate-seen.XXXXXX")
    # awk on the tab field: keep everything whose first column is not this PR.
    awk -F'\t' -v p="$pr" '$1 != p' "$STATE_FILE" > "$tmp" 2>/dev/null || true
    mv "$tmp" "$STATE_FILE"
}

# ---------------------------------------------------------------------------
# Execute a single PR.
# ---------------------------------------------------------------------------

# run_one <pr>: invoke merge-gate.sh <pr>, applying anti-noise handling. Print to
# stdout only what this tick must deliver. Always return 0 (a gate rejection is
# not a scanner error).
run_one() {
    local pr="$1"
    local out rc verdict_line reason

    # Capture gate stdout+stderr. The token and private key NEVER appear in gate
    # output (a merge-gate.sh guarantee): here we only pass them through; we do
    # not log them ourselves.
    out=$(STEVE_REPO="$REPO" \
        STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
        "$MERGE_GATE" "$pr" 2>&1); rc=$?

    # The verdict line is the last line that starts with MERGE: or REJECT:.
    verdict_line=$(printf '%s\n' "$out" | grep -E '^(MERGE|REJECT):' | tail -1)

    case "$verdict_line" in
        MERGE:*)
            if [ "$rc" -eq 0 ]; then
                # Successful merge: ALWAYS report it and reset noise for the PR.
                clear_state "$pr"
                format_merge_announcement "$REPO" "$pr"
            else
                # MERGE verdict but do_merge failed: one-shot anomaly, keyed on
                # "merge-failed" so identical repetitions remain quiet.
                report_reject "$pr" "merge-failed" "$out"
            fi
            ;;
        REJECT:*)
            # reason = text after "REJECT: " (for example, "(c) CI is not green ...").
            reason="${verdict_line#REJECT: }"
            report_reject "$pr" "$reason" "$out"
            ;;
        *)
            # No verdict line (for example, missing STEVE_REPO or a usage error).
            # Key on "eval-error" so identical repetitions remain quiet.
            report_reject "$pr" "eval-error" "$out"
            ;;
    esac
    return 0
}

# ---------------------------------------------------------------------------
# Runtime mode: one run_one per candidate. Anti-noise handling decides what to print.
# ---------------------------------------------------------------------------
while IFS= read -r pr; do
    [ -z "$pr" ] && continue
    run_one "$pr" || true
done <<< "$CANDIDATES"

# Silent by default: no output when there are no new events.
exit 0
