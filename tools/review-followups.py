#!/usr/bin/env python3
"""review-followups: extract the structured Follow-ups section of a review body.

Deterministic parsing (not LLM): the review brief (see .steve/review-policy.yaml,
rule follow_ups_are_explicit) requires every published review to close with a
"## Follow-ups" section that either lists items or reads "None." verbatim, so
"no follow-ups" is an explicit, machine-readable answer instead of silence
(t_92bfeac5: work raised inside a review had no route into the development
queue, because the old convention -- "goes in the review body as a
non-blocking note" -- collected it nowhere).

This tool only extracts and classifies the section. Routing found items into
the kanban queue is done by whoever calls it (instance/skills/steve-factory/
SKILL.md, section 4): the orchestrator already reads every review outcome, so
filing follow-ups there does not require a new watcher.

Usage:
  python3 tools/review-followups.py --body-file <path>
  python3 tools/review-followups.py --self-test

Exit codes:
  0  an explicit answer was found: "none" or one or more "items"
  2  no explicit answer: the section is missing or has no parseable content
     (a review process defect to flag, not silence to pass through)
"""
import argparse
import re
import sys
from pathlib import Path

TRUST_FAILURE = 2

HEADING_RE = re.compile(r"^#{1,6}\s")
FOLLOW_UPS_HEADING_RE = re.compile(r"^#{1,6}\s*Follow-ups:?\s*$", re.IGNORECASE)
NONE_RE = re.compile(r"^None\.?$", re.IGNORECASE)
BULLET_RE = re.compile(r"^[-*]\s+(.*\S)\s*$")


def extract_follow_ups(text):
    """Classify the Follow-ups section of a review body.

    Returns (status, items):
      ("none", [])       -- section present, explicitly says None.
      ("items", [...])   -- section present, one or more bullet items
      ("missing", [])    -- no Follow-ups section, or one with no
                            parseable content (neither None. nor bullets)
    """
    lines = text.splitlines()
    section = None
    for i, line in enumerate(lines):
        if FOLLOW_UPS_HEADING_RE.match(line):
            section = lines[i + 1:]
            break
    if section is None:
        return "missing", []

    # The policy requires the review to CLOSE with this section, so a heading
    # after it is a format violation rather than a boundary to stop at.
    # Stopping silently would let this tool report success on exactly the shape
    # it exists to make explicit.
    body = []
    for line in section:
        if HEADING_RE.match(line):
            return "not_closing", []
        body.append(line)

    stripped = [ln.strip() for ln in body if ln.strip()]
    if not stripped:
        return "missing", []

    if len(stripped) == 1 and NONE_RE.match(stripped[0]):
        return "none", []

    items = []
    for ln in stripped:
        match = BULLET_RE.match(ln)
        if match:
            items.append(match.group(1))
    if items:
        return "items", items

    # Content present but neither "None." nor a bullet list: ambiguous,
    # treated the same as a missing section (an explicit answer we cannot
    # trust is not an explicit answer).
    return "missing", []


def report(status, items):
    """Print the classification and return the process exit code."""
    print("status: {}".format(status))
    if status == "items":
        print("count: {}".format(len(items)))
        for i, item in enumerate(items, start=1):
            print("{}. {}".format(i, item))
        return 0
    if status == "none":
        return 0
    if status == "not_closing":
        print("the review does not end with its Follow-ups section: a heading "
              "follows it, so it is not the closing section the policy requires")
    return TRUST_FAILURE


def run_self_test():
    """Drive extract_follow_ups over fixtures covering each classification."""
    items_body = (
        "## What changes\n"
        "Some diff summary.\n"
        "\n"
        "## Verification\n"
        "- [ ] CI green\n"
        "\n"
        "## Follow-ups\n"
        "- Update the core schema for the revised contract\n"
        "- Add CLI self-tests for the new reason catalog\n"
    )
    status, items = extract_follow_ups(items_body)
    assert status == "items", "expected 'items', got {!r}".format(status)
    assert items == [
        "Update the core schema for the revised contract",
        "Add CLI self-tests for the new reason catalog",
    ], "unexpected item text: {!r}".format(items)
    print("ok: bulleted Follow-ups section -> 2 items")

    not_closing_body = (
        "## Follow-ups\n"
        "- Something worth doing later\n"
        "\n"
        "## Verification\n"
        "- [ ] CI green\n"
    )
    status, items = extract_follow_ups(not_closing_body)
    assert status == "not_closing", "expected 'not_closing', got {!r}".format(status)
    assert items == [], "not_closing must not yield items, got {!r}".format(items)
    print("ok: a Follow-ups section that is not the closing one -> not_closing")

    none_body = (
        "## What changes\nSome diff summary.\n\n"
        "## Verification\n- [ ] CI green\n\n"
        "## Follow-ups\nNone.\n"
    )
    status, items = extract_follow_ups(none_body)
    assert (status, items) == ("none", []), "expected explicit 'none'"
    print("ok: 'None.' Follow-ups section -> none")

    missing_body = (
        "## What changes\nSome diff summary.\n\n"
        "## Verification\n- [ ] CI green\n"
    )
    status, items = extract_follow_ups(missing_body)
    assert (status, items) == ("missing", []), "expected 'missing' when the section is absent"
    print("ok: no Follow-ups heading at all -> missing")

    # Empty AND closing: the section is where it belongs and says nothing, which
    # is the case this fixture is for. Empty and NOT closing is the separate
    # not_closing case above.
    empty_section_body = (
        "## Verification\n- [ ] CI green\n\n## Follow-ups\n"
    )
    status, items = extract_follow_ups(empty_section_body)
    assert (status, items) == ("missing", []), "expected 'missing' for an empty section"
    print("ok: Follow-ups heading with no content -> missing")

    malformed_body = (
        "## Verification\n- [ ] CI green\n\n"
        "## Follow-ups\nSomething worth doing later, written as prose, not a bullet.\n"
    )
    status, items = extract_follow_ups(malformed_body)
    assert (status, items) == ("missing", []), "expected 'missing' for unparseable content"
    print("ok: Follow-ups heading with unparseable prose -> missing")

    eof_body = (
        "## Follow-ups\n- Only item, and the file ends right after it\n"
    )
    status, items = extract_follow_ups(eof_body)
    assert status == "items" and items == [
        "Only item, and the file ends right after it"
    ], "expected the trailing section (no closing heading) to still parse"
    print("ok: Follow-ups section with no trailing heading (EOF) -> 1 item")

    exit_code = report("items", ["x"])
    assert exit_code == 0, "'items' must exit 0 -- it is an explicit answer"
    exit_code = report("none", [])
    assert exit_code == 0, "'none' must exit 0 -- it is an explicit answer"
    exit_code = report("missing", [])
    assert exit_code == TRUST_FAILURE, "'missing' must exit {}".format(TRUST_FAILURE)
    print("ok: exit codes -- items/none 0, missing {}".format(TRUST_FAILURE))

    print("self-test ok")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract the Follow-ups section from a review body."
    )
    parser.add_argument("--body-file", help="Path to the review body text")
    parser.add_argument(
        "--self-test", action="store_true", help="Run deterministic assertions"
    )
    args = parser.parse_args()

    if args.self_test:
        if args.body_file:
            parser.error("--self-test cannot be combined with --body-file")
        return args
    if not args.body_file:
        parser.error("--body-file is required (or use --self-test)")
    return args


def main():
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        text = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as error:
        # The path is caller-supplied and can be a deployment path: report the
        # failure, never the location.
        print("error: cannot read the review body file: {}".format(
            error.strerror or "unreadable"), file=sys.stderr)
        return TRUST_FAILURE

    status, items = extract_follow_ups(text)
    return report(status, items)


if __name__ == "__main__":
    sys.exit(main())
