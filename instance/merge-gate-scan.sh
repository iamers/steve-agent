#!/usr/bin/env bash
# merge-gate-scan: scanner in front of the gate. It finds open PRs with the
# `steve-approved` label (configurable via STEVE_APPROVAL_LABEL) and invokes
# instance/merge-gate.sh on each one. No LLM, no merge logic of its own: it
# delegates entirely to the gate (already tested on canary #46; DO NOT modify
# it).
#
# It also watches a second, smaller candidate set: open PRs that carry NO
# label but are otherwise merge-ready (approved review, green CI, safe tier,
# current branch) -- the state t_cf1a09fa measured on PR #161, where the
# factory was waiting on a human authorization and told nobody, because the
# label-only candidate set above never includes an unlabelled PR. See
# waiting_for_human() below.
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
# - PR ready except for the      -> print ONCE per PR (anti-noise, same state
#   approval label (nobody          file, distinct key) naming the PR and the
#   authorized it yet)              admin. This is not a delivered personal
#                                    notification: it only reaches whoever
#                                    reads this channel, and the message says
#                                    so explicitly (see format_waiting_announcement).
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
#   TELEGRAM_ADMIN_ID     numeric id of the instance admin, read ONLY to name
#                         them in the waiting-for-authorization message
#                         (optional; the message degrades honestly if unset)
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

# waiting_for_human <gate_output>
# Pure function, no network: inspects the condition block that
# instance/merge-gate.sh's evaluate() prints for EVERY invocation (before
# decide_merge() short-circuits on the first false condition), and returns
# "1" only when (a) the label is absent AND (b) through (f) are all true --
# i.e. the gate would merge if a human applied the label. Returns "0" for
# every other combination, including "not ready yet for reasons besides the
# label" (a PR that is merely unreviewed or red is not "waiting for a
# human": nobody is blocked on it).
#
# Matched against the exact text evaluate() emits:
#   "  (a) approval label '<label>': 0"
#   "  (b) approved review on latest commit: 1"
#   "  (c) CI green on latest commit: 1"
#   "  (d) tier (local recompute): safe"
#   "  (e) base=main: 1, mergeable: 1, sha match: 1"
#   "  (f) commits behind current main: 0"
waiting_for_human() {
    local out="$1"
    printf '%s\n' "$out" | grep -qE "^  \(a\) approval label '[^']*': 0\$" || { echo "0"; return; }
    printf '%s\n' "$out" | grep -qE '^  \(b\) approved review on latest commit: 1$' || { echo "0"; return; }
    printf '%s\n' "$out" | grep -qE '^  \(c\) CI green on latest commit: 1$' || { echo "0"; return; }
    printf '%s\n' "$out" | grep -qE '^  \(d\) tier \(local recompute\): safe$' || { echo "0"; return; }
    printf '%s\n' "$out" | grep -qE '^  \(e\) base=main: 1, mergeable: 1, sha match: 1$' || { echo "0"; return; }
    printf '%s\n' "$out" | grep -qE '^  \(f\) commits behind current main: 0$' || { echo "0"; return; }
    echo "1"
}

# format_waiting_announcement <repository> <pr> <label> <admin_id>
# Build the waiting-for-authorization message. Pure function: no network,
# state, or reads. <admin_id> may be empty (TELEGRAM_ADMIN_ID unset on this
# instance): the message still names the role and says so honestly, rather
# than silently dropping the identification.
#
# Deliberately NOT phrased as a delivered notification (per the product rule
# this card exists to satisfy): it names who is expected to act and states
# outright that they were not notified, because posting into this channel is
# not the same as reaching that person -- a display name in prose reads as
# delivered from both ends and is not. Moving this onto the future
# deterministic notification service later only replaces this printf with a
# real call to it; the detection logic above does not change.
format_waiting_announcement() {
    local repository="$1" pr="$2" label="$3" admin_id="${4:-}"
    local who
    if [ -n "$admin_id" ]; then
        who="the admin (Telegram id ${admin_id})"
    else
        who="the admin (TELEGRAM_ADMIN_ID is not set on this instance)"
    fi
    printf 'waiting: PR #%s is approved, CI is green, and the tier is safe.\n' "$pr"
    printf 'https://github.com/%s/pull/%s\n' "$repository" "$pr"
    printf 'The only missing condition is the %s label, which only %s can apply (approve in chat).\n' "$label" "$who"
    printf '%s has NOT been notified: no notification service is wired up yet, and this message only reaches whoever reads this channel.\n' "$who"
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

    # waiting_for_human: the state measured on PR #161 -- everything green,
    # only the label missing.
    local ready_except_label
    ready_except_label=$(printf '%s\n' \
        "---- conditions for PR #161 (octo/example) ----" \
        "  (a) approval label 'steve-approved': 0" \
        "  (b) approved review on latest commit: 1" \
        "  (c) CI green on latest commit: 1" \
        "  (d) tier (local recompute): safe" \
        "  (e) base=main: 1, mergeable: 1, sha match: 1" \
        "  (f) commits behind current main: 0" \
        "REJECT: (a) approval label is not present")
    if [ "$(waiting_for_human "$ready_except_label")" != "1" ]; then
        echo "FAIL: waiting_for_human must be 1 when only (a) is false"
        return 1
    fi
    echo "ok: waiting_for_human -> 1 on the all-green-except-label fixture"

    # A labelled PR is never "waiting for a human": (a) is already true, so
    # this function's own precondition on (a) must reject it regardless of
    # the rest -- it is a different problem (or no problem at all).
    local label_present_case
    label_present_case=$(printf '%s\n' \
        "---- conditions for PR #161 (octo/example) ----" \
        "  (a) approval label 'steve-approved': 1" \
        "  (b) approved review on latest commit: 1" \
        "  (c) CI green on latest commit: 1" \
        "  (d) tier (local recompute): safe" \
        "  (e) base=main: 1, mergeable: 1, sha match: 1" \
        "  (f) commits behind current main: 0" \
        "MERGE: all conditions met")
    if [ "$(waiting_for_human "$label_present_case")" != "0" ]; then
        echo "FAIL: waiting_for_human must be 0 when the label is already present"
        return 1
    fi
    echo "ok: waiting_for_human -> 0 when the label is present"

    # Not ready for a reason besides the label (CI still red): must NOT be
    # reported as "waiting for a human" -- nobody is blocked on a person here.
    local ci_red_case
    ci_red_case=$(printf '%s\n' \
        "---- conditions for PR #161 (octo/example) ----" \
        "  (a) approval label 'steve-approved': 0" \
        "  (b) approved review on latest commit: 1" \
        "  (c) CI green on latest commit: 0" \
        "  (d) tier (local recompute): safe" \
        "  (e) base=main: 1, mergeable: 1, sha match: 1" \
        "  (f) commits behind current main: 0" \
        "REJECT: (a) approval label is not present")
    if [ "$(waiting_for_human "$ci_red_case")" != "0" ]; then
        echo "FAIL: waiting_for_human must be 0 when CI is not green"
        return 1
    fi
    echo "ok: waiting_for_human -> 0 when CI is not green"

    # Behind main: also not "waiting for a human" in the sense this scanner
    # reports -- a rebase is needed first.
    local behind_case
    behind_case=$(printf '%s\n' \
        "---- conditions for PR #161 (octo/example) ----" \
        "  (a) approval label 'steve-approved': 0" \
        "  (b) approved review on latest commit: 1" \
        "  (c) CI green on latest commit: 1" \
        "  (d) tier (local recompute): safe" \
        "  (e) base=main: 1, mergeable: 1, sha match: 1" \
        "  (f) commits behind current main: 3" \
        "REJECT: (a) approval label is not present")
    if [ "$(waiting_for_human "$behind_case")" != "0" ]; then
        echo "FAIL: waiting_for_human must be 0 when the branch is behind main"
        return 1
    fi
    echo "ok: waiting_for_human -> 0 when the branch is behind main"

    expected=$(printf '%s\n' \
        'waiting: PR #161 is approved, CI is green, and the tier is safe.' \
        'https://github.com/octo/example/pull/161' \
        'The only missing condition is the steve-approved label, which only the admin (Telegram id 555) can apply (approve in chat).' \
        'the admin (Telegram id 555) has NOT been notified: no notification service is wired up yet, and this message only reaches whoever reads this channel.')
    actual=$(format_waiting_announcement "octo/example" "161" "steve-approved" "555")
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: format_waiting_announcement (admin id set) returned unexpected text"
        return 1
    fi
    echo "ok: format_waiting_announcement -> names the admin by id when TELEGRAM_ADMIN_ID is set"

    expected=$(printf '%s\n' \
        'waiting: PR #161 is approved, CI is green, and the tier is safe.' \
        'https://github.com/octo/example/pull/161' \
        'The only missing condition is the steve-approved label, which only the admin (TELEGRAM_ADMIN_ID is not set on this instance) can apply (approve in chat).' \
        'the admin (TELEGRAM_ADMIN_ID is not set on this instance) has NOT been notified: no notification service is wired up yet, and this message only reaches whoever reads this channel.')
    actual=$(format_waiting_announcement "octo/example" "161" "steve-approved" "")
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: format_waiting_announcement (admin id unset) returned unexpected text"
        return 1
    fi
    echo "ok: format_waiting_announcement -> degrades honestly when TELEGRAM_ADMIN_ID is unset"

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

# fetch_unlabelled_approved <repo> <label>
# Print one PR number per line: open PRs with reviewDecision=APPROVED that do
# NOT carry <label>. This is the second, smaller candidate set (see the
# header comment): a PR can only be "waiting for a human" in the sense this
# scanner reports if a human review already approved it, so pre-filtering on
# reviewDecision keeps this to a handful of gate calls, not every open PR.
# Silent (empty output) on any gh/network error, matching the rest of this
# scanner's error handling.
fetch_unlabelled_approved() {
    local repo="$1" label="$2"
    gh pr list --repo "$repo" --state open \
        --json number,labels,reviewDecision \
        --jq --arg label "$label" \
        '.[] | select(.reviewDecision == "APPROVED") | select([.labels[].name] | index($label) | not) | .number' \
        2>/dev/null
}

# --dry-run mode: manual exploration without lock or state. List candidates and
# call merge-gate.sh --dry-run for each one.
if [ "$MODE" = "dry-run" ]; then
    CANDIDATES=$(gh pr list --repo "$REPO" --state open \
        --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || exit 0
    if [ -n "$CANDIDATES" ]; then
        while IFS= read -r pr; do
            [ -z "$pr" ] && continue
            echo "=== PR #${pr} (${REPO}, label ${APPROVAL_LABEL}) ==="
            STEVE_REPO="$REPO" \
                STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
                "$MERGE_GATE" --dry-run "$pr" || true
        done <<< "$CANDIDATES"
    fi

    UNLABELLED=$(fetch_unlabelled_approved "$REPO" "$APPROVAL_LABEL")
    if [ -n "$UNLABELLED" ]; then
        while IFS= read -r pr; do
            [ -z "$pr" ] && continue
            echo "=== PR #${pr} (${REPO}, no ${APPROVAL_LABEL} label, review APPROVED) ==="
            out=$(STEVE_REPO="$REPO" \
                STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
                "$MERGE_GATE" --dry-run "$pr" 2>&1)
            printf '%s\n' "$out"
            if [ "$(waiting_for_human "$out")" = "1" ]; then
                echo "--- would report (waiting for a human to apply the label) ---"
                format_waiting_announcement "$REPO" "$pr" "$APPROVAL_LABEL" "${TELEGRAM_ADMIN_ID:-}"
            fi
        done <<< "$UNLABELLED"
    fi
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
# NOTE: no early exit when this is empty -- the second candidate set below
# (unlabelled but approved) is independent and must still run, otherwise an
# instance with zero labeled PRs would never detect one waiting on a human.
CANDIDATES=$(gh pr list --repo "$REPO" --state open \
    --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || CANDIDATES=""

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

# report_waiting <pr> <message>
# Same anti-noise contract as report_reject (print + record once per key,
# silent on repeat), on a fixed reason key so it never collides with a real
# REJECT reason: the labeled path above only reaches decide_merge with (a)=1,
# so it can never itself produce the literal reason string used here.
report_waiting() {
    local pr="$1" message="$2"
    local key
    key=$(printf '%s\twaiting-for-authorization' "$pr")
    if grep -qxF "$key" "$STATE_FILE" 2>/dev/null; then
        return 0
    fi
    printf '%s\n' "$message"
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
if [ -n "$CANDIDATES" ]; then
    while IFS= read -r pr; do
        [ -z "$pr" ] && continue
        run_one "$pr" || true
    done <<< "$CANDIDATES"
fi

# ---------------------------------------------------------------------------
# Second candidate set: open PRs with no approval label but an APPROVED
# review. Calling the real (not --dry-run) gate here is safe even though this
# path never merges: decide_merge() always returns REJECT (a) when the label
# is absent (see decide_merge in merge-gate.sh), so do_merge() is never
# reached. What we want from the call is the full condition block evaluate()
# always prints, which waiting_for_human() inspects below.
# ---------------------------------------------------------------------------
UNLABELLED=$(fetch_unlabelled_approved "$REPO" "$APPROVAL_LABEL")
if [ -n "$UNLABELLED" ]; then
    while IFS= read -r pr; do
        [ -z "$pr" ] && continue
        out=$(STEVE_REPO="$REPO" \
            STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
            "$MERGE_GATE" "$pr" 2>&1)
        if [ "$(waiting_for_human "$out")" = "1" ]; then
            report_waiting "$pr" "$(format_waiting_announcement "$REPO" "$pr" "$APPROVAL_LABEL" "${TELEGRAM_ADMIN_ID:-}")"
        fi
    done <<< "$UNLABELLED"
fi

# Silent by default: no output when there are no new events.
exit 0
