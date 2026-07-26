#!/usr/bin/env python3
"""pr-brief: compiles the approvable review brief for a PR.

Deterministic path-based triage (not LLM): for each modified file it finds
the tier via the patterns in the .steve/review-policy.yaml policy; the PR's
tier is the max across all files (blast > propagation > safe).
It prints the compiled brief to stdout following .steve/review-brief-template.md.

Sending the brief and the merge decision are NOT this tool's job: merging
always stays human. This tool only concentrates the decision.

Usage:
  python3 tools/pr-brief.py --repo <owner/name> --pr <N> [--summary "text"]
  python3 tools/pr-brief.py --self-test
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Severity order: blast (outage) > propagation (replicated bug) > safe.
TIER_ORDER = {"safe": 0, "propagation": 1, "blast": 2}
# Default tier when no pattern matches: fail-safe, not fast.
DEFAULT_TIER = "propagation"

# Paths involved in the D4 gate (constraints without tests).
REVIEW_POLICY_PATH = ".steve/review-policy.yaml"
PR_BRIEF_PATH = "tools/pr-brief.py"


# ---------------------------------------------------------------------------
# Origin task id + D4 gate (deterministic, based on paths/patterns)
# ---------------------------------------------------------------------------

def parse_task_id(branch):
    """Extract the origin task id from the branch name.

    Matches the ``steve-agent/t_<id>-...`` pattern where ``<id>`` is [a-f0-9]+.
    Returns ``t_<id>`` or None if the branch does not match the expected
    prefix (e.g. feat/xxx, main, branches without steve-agent/).
    """
    if not branch:
        return None
    m = re.match(r"steve-agent/(t_[a-f0-9]+)-", branch)
    return m.group(1) if m else None


def check_d4_gate(files):
    """D4 gate: True if the diff touches review-policy BUT NOT pr-brief.py.

    Modifying the review policy without touching the compiler that tests it
    is an untested constraint: it requires an explicit human signature.
    Set comparison of paths, zero heuristics.
    """
    fileset = set(files)
    touches_policy = REVIEW_POLICY_PATH in fileset
    touches_compiler = PR_BRIEF_PATH in fileset
    return touches_policy and not touches_compiler


def escalate_tier_for_d4(pr_tier_name, d4_active):
    """If the D4 gate is active, the effective tier rises at least to propagation.

    If it was safe it becomes propagation; if it was already propagation or
    blast it stays as is.
    """
    if not d4_active:
        return pr_tier_name
    if TIER_ORDER.get(pr_tier_name, 1) < TIER_ORDER["propagation"]:
        return "propagation"
    return pr_tier_name


# ---------------------------------------------------------------------------
# Matcher: glob -> regex translation
# ---------------------------------------------------------------------------

def glob_to_regex(pattern):
    """Translates a glob pattern (with * and **) into an anchored regex.

    **  matches any sequence of characters, including directory separators
    *   matches any sequence except the '/' separator
    ?   matches a single character except the '/' separator
    other characters are literal (with escaping of regex metacharacters)

    fnmatch alone is not enough: it treats '*' as match-all including '/',
    so 'tools/*' would also match 'tools/sub/dir/file.py'.
    """
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** across directory boundaries
                out.append(".*")
                i += 2
            else:
                # * within a single path segment
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".^$+(){}[]|\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "^" + "".join(out) + "$"


def file_tier(path, tiers):
    """Finds a file's tier via pattern matching.

    Iterates tiers from most severe to least severe: the first tier with a
    matching pattern wins (the max). If no pattern matches, returns
    (DEFAULT_TIER, None).

    Returns (tier_name, matched_pattern).
    """
    for tier_name in sorted(tiers, key=lambda t: TIER_ORDER.get(t, 0), reverse=True):
        for pat in tiers[tier_name].get("paths", []):
            if re.match(glob_to_regex(pat), path):
                return tier_name, pat
    return DEFAULT_TIER, None


def compute_pr_tier(paths, tiers):
    """PR tier = max(tier of all modified files).

    Returns (pr_tier_name, [(path, file_tier, matched_pattern), ...]).
    """
    file_results = []
    for path in paths:
        ftier, pattern = file_tier(path, tiers)
        file_results.append((path, ftier, pattern))
    if not file_results:
        return DEFAULT_TIER, []
    pr_tier_name = max(
        (ftier for _, ftier, _ in file_results),
        key=lambda t: TIER_ORDER.get(t, 1),
    )
    return pr_tier_name, file_results


# ---------------------------------------------------------------------------
# Policy and template loading
# ---------------------------------------------------------------------------

def find_policy_path():
    """Finds .steve/review-policy.yaml: from cwd upward, then from the script."""
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        candidate = p / ".steve" / "review-policy.yaml"
        if candidate.is_file():
            return candidate
    # Fallback: tools/pr-brief.py -> the repo root is two levels up
    script_root = Path(__file__).resolve().parent.parent
    candidate = script_root / ".steve" / "review-policy.yaml"
    if candidate.is_file():
        return candidate
    return None


def load_policy(policy_path):
    """Loads the tiers from the YAML policy."""
    with open(policy_path) as f:
        data = yaml.safe_load(f)
    return data.get("tiers", {})


# ---------------------------------------------------------------------------
# Brief compilation
# ---------------------------------------------------------------------------

def extract_summary(body, override):
    """Summary for 'What changes': --summary, first 3 non-empty lines of the body, or fallback."""
    if override:
        return override
    if body:
        non_empty = [ln for ln in body.split("\n") if ln.strip()]
        if non_empty:
            return "\n".join(non_empty[:3])
    return "(summary unavailable)"


def render_brief(template_text, number, title, branch, tier_upper,
                 critical_files, summary_text, task_id=None, d4_active=False,
                 repo=None):
    """Compiles the template by filling dynamic fields, leaving static
    sections intact (footer, 'Non-obvious decisions' placeholder, checklist).

    critical_files: list of (path, tier_lowercase, matched_pattern_or_None).
    task_id: origin task id (``t_<id>``) or None.
    d4_active: if True, inserts the D4 marker (constraint without test).
    repo: repository owner/name or None.
    """
    lines = template_text.split("\n")
    output = []
    leggi_prima_emitted = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # Header line: PR #<N> — <title>
        if "<N>" in line and "<title>" in line:
            output.append("PR #{} — {}".format(number, title))
            if repo:
                output.append("Link: https://github.com/{}/pull/{}".format(
                    repo, number))
        # Branch line: Branch: <branch> -> main (+ optional Origin line)
        elif "<branch>" in line:
            output.append("Branch: {} -> main".format(branch))
            if task_id:
                output.append("Origin: task {}".format(task_id))
        # Fixed "Read first" section: injected once, right before
        # the ## Triage block (after the PR info, before critical files).
        elif not leggi_prima_emitted and line.strip() == "## Triage":
            output.append("Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml")
            output.append("")
            output.append(line)
            leggi_prima_emitted = True
        # Tier line (replaces the whole line) + optional D4 marker
        elif line.startswith("Tier:"):
            output.append("Tier: {}".format(tier_upper))
            if d4_active:
                output.append("D4: untested constraint - human signature required")
        # Critical files section: replaces placeholders with real files
        elif line.strip() == "Critical files:":
            output.append(line)
            # Skip the placeholder lines (- <path> ...)
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- <path>"):
                i += 1
            # Insert the real critical files (blast and propagation)
            for path, ftier, pattern in critical_files:
                perche = pattern if pattern else "default (no match)"
                output.append("- {}  ({}, {})".format(path, ftier, perche))
            continue  # i is already positioned on the next line
        # 'What changes' section: replaces the placeholder with the summary
        elif "<2-3 lines" in line:
            output.append(summary_text)
        # Approval placeholder: replace it with the tier-derived action block
        elif line.startswith("Approval:"):
            if tier_upper == "SAFE":
                output.extend([
                    "What you need to do: nothing on GitHub. Reply `approve #{}` in this chat and the approval".format(number),
                    "label is applied for you. The gate merges as soon as all five conditions hold: the label, an",
                    "approved review from the reviewer, green CI, tier safe, and a head unchanged since the",
                    "approval. If the review has not landed yet, the gate waits and merges on a later run.",
                    "To send it back instead, reply `reject: <reason>`.",
                ])
            else:
                output.extend([
                    "What you need to do: open the link above and merge it yourself in the GitHub app. Tier",
                    "{} is not auto-mergeable by design: an approve in this chat cannot merge it, and the".format(tier_upper),
                    "approval label will not be applied. Everything before the merge, the review and CI, is",
                    "handled here.",
                    "To send it back instead, reply `reject: <reason>`.",
                ])
        else:
            # All other lines stay as they are in the template
            output.append(line)
        i += 1
    return "\n".join(output)


# ---------------------------------------------------------------------------
# Fetch PR via gh
# ---------------------------------------------------------------------------

def fetch_pr(repo, pr_number):
    """Reads the PR data via the gh CLI. Returns the JSON dict."""
    cmd = [
        "gh", "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "number,title,headRefName,body,files",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        print("error: gh CLI not found in PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print("error: gh pr view failed (exit {})".format(e.returncode), file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    """Assertions on the matcher using the repo's real policy (no network)."""
    policy_path = find_policy_path()
    if not policy_path:
        print("error: .steve/review-policy.yaml not found", file=sys.stderr)
        sys.exit(1)
    tiers = load_policy(policy_path)

    cases = [
        ("instance/config.yaml", "blast"),
        (".steve/something/file.md", "propagation"),
        ("tools/x.py", "propagation"),
        ("scripts/foo.sh", "propagation"),
        (".github/workflows/ci.yml", "propagation"),
        ("README.md", "propagation"),
        ("CLAUDE.md", "propagation"),
        ("AGENTS.md", "propagation"),
        ("SECURITY.md", "propagation"),
        (".gitignore", "propagation"),
        ("docs/ARCHITECTURE.md", "safe"),
        ("docs/design/components/worker.md", "safe"),
        ("instance/README.md", "safe"),
        ("CONTRIBUTING.md", "safe"),
        ("CODE_OF_CONDUCT.md", "safe"),
        ("unknown-path.xyz", "propagation"),
    ]
    for path, expected in cases:
        got, _ = file_tier(path, tiers)
        assert got == expected, "{}: expected {}, got {}".format(
            path, expected, got)

    # --- Extension 1: origin task id from the branch name -----------------
    tid_cases = [
        ("steve-agent/t_4806977c-ci-workflow-fix-4-finding-shellcheck-ste",
         "t_4806977c"),
    ]
    for branch, expected in tid_cases:
        got = parse_task_id(branch)
        assert got == expected, "parse_task_id({!r}): expected {}, got {}".format(
            branch, expected, got)
    # Non-matching branches must return None
    for branch in ("feat/random", "main", "t_solo_id"):
        got = parse_task_id(branch)
        assert got is None, "parse_task_id({!r}): expected None, got {}".format(
            branch, got)

    # --- Extension 2: fixed "Read first" section ------------------------
    # Rendering with dummy input (no network): the string must be present.
    template_path = policy_path.parent / "review-brief-template.md"
    template_text = template_path.read_text()
    safe_brief = render_brief(
        template_text, number=1, title="sample", branch="feat/sample",
        tier_upper="SAFE", critical_files=[], summary_text="x",
        task_id=None, d4_active=False, repo="iamers/steve-agent")
    assert "Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml" in safe_brief, \
        "'Read first' section missing from rendered brief"
    assert "Link: https://github.com/iamers/steve-agent/pull/1" in safe_brief, \
        "PR link missing or malformed in rendered brief"
    assert "What you need to do: nothing on GitHub. Reply `approve #1` in this chat" in safe_brief, \
        "safe action text missing from rendered brief"
    assert "open the link above and merge it yourself" not in safe_brief, \
        "manual-merge action text must not appear for safe tier"

    propagation_brief = render_brief(
        template_text, number=2, title="sample", branch="feat/sample",
        tier_upper="PROPAGATION", critical_files=[], summary_text="x",
        task_id=None, d4_active=False)
    assert "What you need to do: open the link above and merge it yourself in the GitHub app" in propagation_brief, \
        "manual-merge action text missing from propagation brief"
    assert "PROPAGATION is not auto-mergeable by design" in propagation_brief, \
        "propagation tier missing from manual-merge action text"
    assert "nothing on GitHub" not in propagation_brief, \
        "safe action text must not appear for propagation tier"
    assert "Link:" not in propagation_brief, \
        "PR link must not appear when repository is absent"

    # --- Extension 3: D4 gate -------------------------------------------
    # review-policy only (without pr-brief.py) -> D4 active + tier escalates
    files_policy_only = [REVIEW_POLICY_PATH]
    assert check_d4_gate(files_policy_only) is True, \
        "D4 should trigger with review-policy.yaml alone"
    escalated = escalate_tier_for_d4("safe", True)
    assert escalated == "propagation", \
        "D4 active: safe tier should escalate to propagation, got {}".format(
            escalated)
    # Both files -> D4 NOT active (the compiler was touched)
    files_both = [REVIEW_POLICY_PATH, PR_BRIEF_PATH]
    assert check_d4_gate(files_both) is False, \
        "D4 should NOT trigger when pr-brief.py is in the diff"
    assert escalate_tier_for_d4("safe", False) == "safe", \
        "D4 inactive: tier must not change"

    print("self-test ok")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compiles the review brief for a PR (deterministic triage).")
    parser.add_argument("--repo", help="Repository owner/name (e.g. iamers/steve-agent)")
    parser.add_argument("--pr", type=int, help="PR number")
    parser.add_argument("--summary", help="Summary override for 'What changes'")
    parser.add_argument("--self-test", action="store_true",
                        help="Run assertions on the matcher without network")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    if not args.repo or args.pr is None:
        parser.error("--repo and --pr are required (unless --self-test)")

    # Load policy and template from the repo root
    policy_path = find_policy_path()
    if not policy_path:
        print("error: .steve/review-policy.yaml not found", file=sys.stderr)
        sys.exit(1)
    tiers = load_policy(policy_path)

    template_path = policy_path.parent / "review-brief-template.md"
    if not template_path.is_file():
        print("error: .steve/review-brief-template.md not found", file=sys.stderr)
        sys.exit(1)
    template_text = template_path.read_text()

    # Read the PR via gh
    pr_data = fetch_pr(args.repo, args.pr)

    number = pr_data.get("number", args.pr)
    title = pr_data.get("title", "(untitled)")
    branch = pr_data.get("headRefName", "(unknown)")
    body = pr_data.get("body") or ""
    files = [f["path"] for f in pr_data.get("files", [])]

    # Deterministic triage
    pr_tier_name, file_results = compute_pr_tier(files, tiers)

    # Origin task id from the branch name (deterministic)
    task_id = parse_task_id(branch)

    # D4 gate: constraint on review-policy without test -> tier escalates + human signature
    d4_active = check_d4_gate(files)
    pr_tier_name = escalate_tier_for_d4(pr_tier_name, d4_active)

    # Critical files: only blast and propagation (with the matching pattern)
    critical = [
        (path, ftier, pattern)
        for path, ftier, pattern in file_results
        if ftier in ("blast", "propagation")
    ]

    summary = extract_summary(body, args.summary)

    brief = render_brief(template_text, number, title, branch,
                         pr_tier_name.upper(), critical, summary,
                         task_id=task_id, d4_active=d4_active, repo=args.repo)
    # Normalize: a single trailing blank line
    brief = brief.rstrip("\n") + "\n"
    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
