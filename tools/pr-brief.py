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
import os
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

# Language-neutral anchors in .steve/review-brief-template.md.
BRIEF_TOKENS = {
    "header": "{{header}}",
    "link": "{{link}}",
    "branch": "{{branch}}",
    "origin": "{{origin}}",
    "read_first": "{{read_first}}",
    "tier": "{{tier}}",
    "d4": "{{d4}}",
    "critical_files": "{{critical_files}}",
    "summary": "{{summary}}",
    "approval": "{{approval}}",
}

BRIEF_STRINGS = {
    "en": {
        "read_first": "Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml",
        "d4": "D4: untested constraint - human signature required",
        "safe_action": [
            "What you need to do: reply `approve #{number}` in this chat.",
            "Where the merge gate is configured, that is the whole path: the approval label is applied for",
            "you, and the gate merges once the label, an approved review from the reviewer, green CI, tier",
            "safe, and a pull request that still targets main, is still mergeable and whose head has not",
            "moved since the approval are all true. If the review or CI have not landed yet, the gate waits",
            "and merges on a later run.",
            "Where no merge gate is configured, your approve is recorded and the merge is a human action on",
            "the link above. You will be told which of the two applies when you approve.",
            "To send it back instead, reply `reject: <reason>`.",
        ],
        "manual_action": [
            "What you need to do: open the link above and merge it yourself in the GitHub app. Tier",
            "{tier} is not auto-mergeable by design: an approve in this chat cannot merge it, and the",
            "approval label will not be applied. Everything before the merge, the review and CI, is",
            "handled here.",
            "To send it back instead, reply `reject: <reason>`.",
        ],
    },
    "it": {
        "read_first": "Leggi prima (nel worktree): README.md, CLAUDE.md, .steve/review-policy.yaml",
        "d4": "D4: vincolo non testato - firma umana richiesta",
        "safe_action": [
            "Cosa devi fare: rispondi `approve #{number}` in questa chat.",
            "Dove il merge gate è configurato, questo è l'intero percorso: l'etichetta di approvazione viene",
            "applicata per te e il gate esegue il merge quando sono presenti l'etichetta, una review approvata",
            "dal reviewer, CI verde, tier SAFE e una pull request che punta ancora a main, è ancora mergeable e",
            "il cui head non si è spostato dall'approvazione. Se review o CI non sono ancora arrivate, il gate",
            "attende ed esegue il merge in una run successiva.",
            "Dove non è configurato alcun merge gate, il tuo approve viene registrato e il merge è un'azione",
            "umana sul link sopra. Quando approvi, ti verrà indicato quale dei due casi si applica.",
            "Per rimandarla indietro, rispondi `reject: <reason>`.",
        ],
        "manual_action": [
            "Cosa devi fare: apri il link sopra ed esegui personalmente il merge nell'app GitHub. Il tier",
            "{tier} non consente l'auto-merge per scelta progettuale: un approve in questa chat non può",
            "eseguire il merge e l'etichetta di approvazione non verrà applicata. Tutto ciò che precede il",
            "merge, cioè review e CI, viene gestito qui.",
            "Per rimandarla indietro, rispondi `reject: <reason>`.",
        ],
    },
}

FALLBACK_NOTICE = "Chat language {requested!r} is unavailable; using English."


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


# See docs/decisions/adr-20260724-untested-constraints-block-review.md.
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


def resolve_brief_language(template_dir, requested_lang):
    """Selects a supported brief language, falling back visibly to English."""
    if requested_lang is None:
        requested_lang = "en"
    template_name = ("review-brief-template.md" if requested_lang == "en" else
                     "review-brief-template.{}.md".format(requested_lang))
    template_path = template_dir / template_name
    if requested_lang in BRIEF_STRINGS and template_path.is_file():
        return requested_lang, template_path, None
    english_path = template_dir / "review-brief-template.md"
    return "en", english_path, FALLBACK_NOTICE.format(requested=requested_lang)


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
                 repo=None, language="en", fallback_notice=None):
    """Compiles the template by filling dynamic fields, leaving static
    sections intact (footer, 'Non-obvious decisions' placeholder, checklist).

    critical_files: list of (path, tier_lowercase, matched_pattern_or_None).
    task_id: origin task id (``t_<id>``) or None.
    d4_active: if True, inserts the D4 marker (constraint without test).
    repo: repository owner/name or None.
    """
    strings = BRIEF_STRINGS[language]
    lines = template_text.split("\n")
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == BRIEF_TOKENS["header"]:
            output.append("PR #{} — {}".format(number, title))
            if fallback_notice:
                output.append(fallback_notice)
        elif line == BRIEF_TOKENS["link"]:
            if repo:
                output.append("Link: https://github.com/{}/pull/{}".format(
                    repo, number))
        elif line == BRIEF_TOKENS["branch"]:
            output.append("Branch: {} -> main".format(branch))
        elif line == BRIEF_TOKENS["origin"]:
            if task_id:
                output.append("Origin: task {}".format(task_id))
        elif line == BRIEF_TOKENS["read_first"]:
            output.append(strings["read_first"])
        elif line == BRIEF_TOKENS["tier"]:
            output.append("Tier: {}".format(tier_upper))
        elif line == BRIEF_TOKENS["d4"]:
            if d4_active:
                output.append(strings["d4"])
        elif line == BRIEF_TOKENS["critical_files"]:
            for path, ftier, pattern in critical_files:
                match_reason = pattern if pattern else "default (no match)"
                output.append("- {}  ({}, {})".format(path, ftier, match_reason))
        elif line == BRIEF_TOKENS["summary"]:
            output.append(summary_text)
        elif line == BRIEF_TOKENS["approval"]:
            action_key = "safe_action" if tier_upper == "SAFE" else "manual_action"
            output.extend(
                action_line.format(number=number, tier=tier_upper)
                for action_line in strings[action_key]
            )
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
    def assert_golden(label, actual, expected):
        if actual == expected:
            print("golden assertion ({}): ok".format(label))
            return
        actual_lines = actual.split("\n")
        expected_lines = expected.split("\n")
        for line_number in range(
                1, max(len(actual_lines), len(expected_lines)) + 1):
            actual_line = (actual_lines[line_number - 1]
                           if line_number <= len(actual_lines) else "<missing>")
            expected_line = (expected_lines[line_number - 1]
                             if line_number <= len(expected_lines) else "<missing>")
            if actual_line != expected_line:
                raise AssertionError(
                    "{} differs at line {}: expected {!r}, got {!r}".format(
                        label, line_number, expected_line, actual_line))

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

    # --- Extension 2: language templates and injected strings -------------
    template_path = policy_path.parent / "review-brief-template.md"
    template_text = template_path.read_text()
    token_pattern = re.compile(r"{{[a-z0-9_]+}}")
    expected_tokens = set(BRIEF_TOKENS.values())
    template_paths = sorted(policy_path.parent.glob("review-brief-template*.md"))
    assert template_paths, "no brief templates discovered"
    for discovered_template in template_paths:
        actual_tokens = set(token_pattern.findall(discovered_template.read_text()))
        assert actual_tokens == expected_tokens, \
            "{} tokens differ: missing {}, extra {}".format(
                discovered_template.name,
                sorted(expected_tokens - actual_tokens),
                sorted(actual_tokens - expected_tokens))
        print("template token assertion ({}): ok".format(discovered_template.name))
    discovered_languages = {
        "en" if path.name == "review-brief-template.md" else
        path.name[len("review-brief-template."):-len(".md")]
        for path in template_paths
    }
    assert discovered_languages == set(BRIEF_STRINGS), \
        "template languages and injected-string languages differ"
    print("template language-set assertion: ok")

    italian_template_path = policy_path.parent / "review-brief-template.it.md"
    assert italian_template_path.is_file(), "Italian brief template missing"
    italian_template_text = italian_template_path.read_text()

    # Rendering with dummy input (no network): each language must be isolated.
    safe_brief = render_brief(
        template_text, number=1, title="sample", branch="feat/sample",
        tier_upper="SAFE", critical_files=[], summary_text="x",
        task_id=None, d4_active=False, repo="iamers/steve-agent")
    assert "Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml" in safe_brief, \
        "'Read first' section missing from rendered brief"
    assert "Link: https://github.com/iamers/steve-agent/pull/1" in safe_brief, \
        "PR link missing or malformed in rendered brief"
    assert "What you need to do: reply `approve #1` in this chat" in safe_brief, \
        "safe action text missing from rendered brief"
    assert "is still mergeable" in safe_brief, \
        "safe action must state that the pull request remains mergeable"
    assert "Where no merge gate is configured" in safe_brief, \
        "safe action must cover installations without a merge gate"
    assert "open the link above and merge it yourself" not in safe_brief, \
        "manual-merge action text must not appear for safe tier"
    assert "Cosa devi fare:" not in safe_brief, \
        "Italian action text must not appear in English brief"
    print("language action assertion (en): ok")

    italian_safe_brief = render_brief(
        italian_template_text, number=1, title="sample", branch="feat/sample",
        tier_upper="SAFE", critical_files=[], summary_text="x",
        task_id=None, d4_active=False, repo="iamers/steve-agent",
        language="it")
    assert "Cosa devi fare: rispondi `approve #1` in questa chat" in italian_safe_brief, \
        "safe Italian action text missing from rendered brief"
    assert "è ancora mergeable" in italian_safe_brief, \
        "safe Italian action must state that the pull request remains mergeable"
    assert "Dove non è configurato alcun merge gate" in italian_safe_brief, \
        "safe Italian action must cover installations without a merge gate"
    assert "What you need to do:" not in italian_safe_brief, \
        "English action text must not appear in Italian brief"

    italian_propagation_brief = render_brief(
        italian_template_text, number=2, title="sample", branch="feat/sample",
        tier_upper="PROPAGATION", critical_files=[], summary_text="x",
        language="it")
    assert "Cosa devi fare: apri il link sopra" in italian_propagation_brief, \
        "manual-merge Italian action text missing from propagation brief"
    assert "PROPAGATION non consente l'auto-merge" in italian_propagation_brief, \
        "propagation tier missing from Italian manual-merge action text"
    assert "What you need to do:" not in italian_propagation_brief, \
        "English action text must not appear in Italian propagation brief"
    print("language action assertion (it): ok")

    selected_lang, fallback_path, fallback_notice = resolve_brief_language(
        policy_path.parent, "xx")
    assert selected_lang == "en" and fallback_path == template_path, \
        "unknown language must select the English template"
    fallback_brief = render_brief(
        fallback_path.read_text(), number=1, title="sample", branch="feat/sample",
        tier_upper="SAFE", critical_files=[], summary_text="x",
        language=selected_lang, fallback_notice=fallback_notice)
    assert "Chat language 'xx' is unavailable; using English." in fallback_brief, \
        "unknown-language fallback notice missing or does not name the value"
    assert "What you need to do:" in fallback_brief and "Cosa devi fare:" not in fallback_brief, \
        "unknown language must render English strings only"
    print("language fallback assertion (xx -> en, visible notice): ok")

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

    # Golden output: token-based rendering must remain byte-identical.
    golden_brief = render_brief(
        template_text, number=7, title="sample title",
        branch="steve-agent/t_abc1234-sample", tier_upper="PROPAGATION",
        critical_files=[("tools/x.py", "propagation", "tools/**")],
        summary_text="A one line summary.", task_id="t_abc1234",
        d4_active=True, repo="o/r")
    expected_golden = """\
PR #7 — sample title
Link: https://github.com/o/r/pull/7
Branch: steve-agent/t_abc1234-sample -> main
Origin: task t_abc1234

Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml

## Triage
Tier: PROPAGATION
D4: untested constraint - human signature required
Critical files:
- tools/x.py  (propagation, tools/**)

## What changes
A one line summary.

## Non-obvious decisions
- <technical decision + reason>

## Operational rules

Read `task_rules` in `.steve/review-policy.yaml` before starting. They are
constraints, not suggestions: each one has already killed at least one task.
The two that bite most often are no `rm` in any form inside a verify, and the
published review body carrying no instance paths, aliases or identities.

## Verification
- [ ] CI green
- [ ] <tier-specific criterion, e.g. "config loads in dry-run without errors">

---
What you need to do: open the link above and merge it yourself in the GitHub app. Tier
PROPAGATION is not auto-mergeable by design: an approve in this chat cannot merge it, and the
approval label will not be applied. Everything before the merge, the review and CI, is
handled here.
To send it back instead, reply `reject: <reason>`.
"""
    assert_golden("optional lines present", golden_brief, expected_golden)

    # Golden output with every optional line absent. The link, origin and D4
    # tokens must disappear without leaving blank lines in their place.
    absent_golden_brief = render_brief(
        template_text, number=7, title="sample title",
        branch="steve-agent/t_abc1234-sample", tier_upper="PROPAGATION",
        critical_files=[("tools/x.py", "propagation", "tools/**")],
        summary_text="A one line summary.", task_id=None,
        d4_active=False, repo=None)
    expected_absent_golden = """\
PR #7 — sample title
Branch: steve-agent/t_abc1234-sample -> main

Read first (in the worktree): README.md, CLAUDE.md, .steve/review-policy.yaml

## Triage
Tier: PROPAGATION
Critical files:
- tools/x.py  (propagation, tools/**)

## What changes
A one line summary.

## Non-obvious decisions
- <technical decision + reason>

## Operational rules

Read `task_rules` in `.steve/review-policy.yaml` before starting. They are
constraints, not suggestions: each one has already killed at least one task.
The two that bite most often are no `rm` in any form inside a verify, and the
published review body carrying no instance paths, aliases or identities.

## Verification
- [ ] CI green
- [ ] <tier-specific criterion, e.g. "config loads in dry-run without errors">

---
What you need to do: open the link above and merge it yourself in the GitHub app. Tier
PROPAGATION is not auto-mergeable by design: an approve in this chat cannot merge it, and the
approval label will not be applied. Everything before the merge, the review and CI, is
handled here.
To send it back instead, reply `reject: <reason>`.
"""
    assert_golden("optional lines absent", absent_golden_brief,
                  expected_absent_golden)
    optional_lines = {
        "Link: https://github.com/o/r/pull/7",
        "Origin: task t_abc1234",
        "D4: untested constraint - human signature required",
    }
    expected_absent_from_present = "\n".join(
        line for line in expected_golden.split("\n")
        if line not in optional_lines)
    assert expected_absent_golden == expected_absent_from_present, \
        "absent golden must differ only by the link, origin and D4 lines"

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

    requested_lang = os.environ.get("STEVE_CHAT_LANG", "en")
    language, template_path, fallback_notice = resolve_brief_language(
        policy_path.parent, requested_lang)
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
                         task_id=task_id, d4_active=d4_active, repo=args.repo,
                         language=language, fallback_notice=fallback_notice)
    # Normalize: a single trailing blank line
    brief = brief.rstrip("\n") + "\n"
    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
