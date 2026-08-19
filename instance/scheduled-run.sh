#!/usr/bin/env bash
# scheduled-run: update the blueprint clone before a scheduled target executes.
# It keeps silent watchdog output trustworthy by refusing to run stale code and
# reporting every update failure on the scheduler's delivered stdout channel.
set -u

SELFTEST_FAILURES=0

selftest_assert_equal() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
        printf 'ok: %s\n' "$label"
    else
        printf 'not ok: %s (expected %s, got %s)\n' "$label" "$expected" "$actual"
        SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
    fi
}

selftest_assert_nonempty() {
    local label="$1" actual="$2"
    if [ -n "$actual" ]; then
        printf 'ok: %s\n' "$label"
    else
        printf 'not ok: %s (expected non-empty stdout)\n' "$label"
        SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
    fi
}

selftest_assert_absent() {
    local label="$1" path="$2"
    if [ ! -e "$path" ]; then
        printf 'ok: %s\n' "$label"
    else
        printf 'not ok: %s (unexpected sentinel exists)\n' "$label"
        SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
    fi
}

run_self_test() {
    local fixture_root run_number run_root origin seed deployment
    local updated_output updated_status refused_output refused_status sentinel

    fixture_root="/tmp/steve-scheduled-run-self-test"
    mkdir -p "$fixture_root"
    run_number=1
    while ! mkdir "$fixture_root/run-$run_number" 2>/dev/null; do
        run_number=$((run_number + 1))
    done
    run_root="$fixture_root/run-$run_number"
    origin="$run_root/origin.git"
    seed="$run_root/seed"
    deployment="$run_root/deployment"

    git init -q --bare --initial-branch=main "$origin"
    git init -q --initial-branch=main "$seed"
    git -C "$seed" config user.name "Scheduled Run Self-Test"
    git -C "$seed" config user.email "scheduled-run-self-test@example.invalid"
    mkdir -p "$seed/instance"
    cp "$0" "$seed/instance/scheduled-run.sh"
    chmod +x "$seed/instance/scheduled-run.sh"
    printf '%s\n' '#!/usr/bin/env bash' 'set -u' 'cat "$(dirname "$0")/../observed.txt"' > "$seed/instance/backup-kanban.sh"
    chmod +x "$seed/instance/backup-kanban.sh"
    printf '%s\n' 'old content' > "$seed/observed.txt"
    git -C "$seed" add instance/scheduled-run.sh instance/backup-kanban.sh observed.txt
    git -C "$seed" commit -q -m "test: create stale deployment"
    git -C "$seed" remote add origin "$origin"
    git -C "$seed" push -q -u origin main
    git clone -q "$origin" "$deployment"

    printf '%s\n' 'new content' > "$seed/observed.txt"
    git -C "$seed" add observed.txt
    git -C "$seed" commit -q -m "test: update observed content"
    git -C "$seed" push -q

    updated_output="$($deployment/instance/scheduled-run.sh backup-kanban.sh 2>/dev/null)"
    updated_status=$?
    selftest_assert_equal "updated exits zero" "0" "$updated_status"
    selftest_assert_equal "updated target observes new content" "new content" "$updated_output"

    sentinel="$deployment/refused-target-ran"
    printf '%s\n' '#!/usr/bin/env bash' 'set -u' 'touch "$(dirname "$0")/../refused-target-ran"' > "$deployment/instance/backup-kanban.sh"
    git -C "$deployment" remote set-url origin "file://$run_root/missing-origin.git"

    refused_output="$($deployment/instance/scheduled-run.sh backup-kanban.sh 2>/dev/null)"
    refused_status=$?
    selftest_assert_nonempty "refused emits stdout" "$refused_output"
    if [ "$refused_status" -ne 0 ]; then
        printf '%s\n' "ok: refused exits non-zero"
    else
        printf '%s\n' "not ok: refused exits non-zero (got 0)"
        SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
    fi
    selftest_assert_absent "refused target did not run" "$sentinel"

    if [ "$SELFTEST_FAILURES" -ne 0 ]; then
        printf 'self-test FAILED: %s assertion(s) failed\n' "$SELFTEST_FAILURES"
        return 1
    fi
    printf '%s\n' "self-test ok"
    return 0
}

if [ "${1:-}" = "--self-test" ]; then
    run_self_test
    exit $?
fi

TARGET="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

fail_run() {
    local target="$1" commit="$2" reason="$3"
    printf 'scheduled-run: target=%s commit=%s: %s\n' "$target" "$commit" "$reason"
    exit 1
}

if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail_run "$TARGET" "unknown" "repository root is not a git worktree"
fi

CURRENT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null)" || CURRENT_COMMIT="unknown"
case "$TARGET" in
    pr-watch.sh|merge-gate-scan.sh|backup-kanban.sh) ;;
    *) fail_run "${TARGET:-<missing>}" "$CURRENT_COMMIT" "unsupported target" ;;
esac
shift

CURRENT_BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null)" || {
    fail_run "$TARGET" "$CURRENT_COMMIT" "HEAD is detached"
}
if [ "$CURRENT_BRANCH" != "main" ]; then
    fail_run "$TARGET" "$CURRENT_COMMIT" "HEAD is on $CURRENT_BRANCH, not main"
fi

UPSTREAM="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" || {
    fail_run "$TARGET" "$CURRENT_COMMIT" "main has no upstream"
}
if [ "$UPSTREAM" != "origin/main" ]; then
    fail_run "$TARGET" "$CURRENT_COMMIT" "main upstream is $UPSTREAM, not origin/main"
fi

if ! git -C "$REPO_ROOT" fetch --quiet origin 2>/dev/null; then
    fail_run "$TARGET" "$CURRENT_COMMIT" "fetch failed"
fi
if ! git -C "$REPO_ROOT" merge --ff-only "$UPSTREAM" --quiet 2>/dev/null; then
    fail_run "$TARGET" "$CURRENT_COMMIT" "fast-forward failed"
fi

TARGET_PATH="$REPO_ROOT/instance/$TARGET"
if [ ! -f "$TARGET_PATH" ]; then
    CURRENT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null)" || CURRENT_COMMIT="unknown"
    fail_run "$TARGET" "$CURRENT_COMMIT" "target does not exist"
fi

exec bash "$TARGET_PATH" "$@"
