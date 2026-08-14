#!/usr/bin/env python3
"""review-followups: extract the structured Follow-ups section of a review body.

Deterministic parsing (not LLM): the review brief (see .steve/review-policy.yaml,
rule follow_ups_are_explicit) requires every published review to close with a
"## Follow-ups" section that either lists items or reads "None." verbatim, so
"no follow-ups" is an explicit, machine-readable answer instead of silence
(t_92bfeac5: work raised inside a review had no route into the development
queue, because the old convention -- "goes in the review body as a
non-blocking note" -- collected it nowhere).

This tool only extracts and classifies the section. Routing what it finds is
done by whoever calls it (instance/skills/steve-factory/SKILL.md, section 4),
and the destination is a repository issue rather than a board card: the
dispatcher promotes a card carrying no sticky block and claims assigned ready
cards in the same pass, so a follow-up placed on the board can start running
before anything can hold it. The orchestrator already reads every review
outcome, so filing them does not require a new watcher either way.

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
# The policy names the literal line `None.`, so that is what is accepted:
# an optional period and a case-insensitive match were a looser grammar
# than the contract this tool exists to enforce.
NONE_LITERAL = "None."
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

    # Indentation is load-bearing here and must survive until classification:
    # it is the only thing distinguishing a continuation line, which belongs to
    # the bullet above it, from a separate observation written as prose. The
    # boundary, decided in review: unindented prose anywhere fails closed, an
    # empty bullet payload fails closed, and an indented line after a nonempty
    # bullet is folded into that item.
    kept = [ln.rstrip() for ln in body if ln.strip()]
    if not kept:
        return "missing", []

    if len(kept) == 1 and kept[0].strip() == NONE_LITERAL:
        return "none", []

    items = []
    unparsed = []
    empty_bullet = False
    for ln in kept:
        match = BULLET_RE.match(ln.strip())
        if match:
            payload = match.group(1).strip()
            if not payload:
                empty_bullet = True
                continue
            items.append(payload)
            continue
        if ln[:1].isspace() and items:
            items[-1] = items[-1] + " " + ln.strip()
            continue
        unparsed.append(ln.strip())

    # The verdict is taken here rather than at the first surprise, because
    # unindented prose BEFORE the first bullet is only distinguishable from
    # prose that is the whole section once the rest has been read.
    if empty_bullet or (items and unparsed):
        return "mixed", []
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
    if status == "mixed":
        print("the Follow-ups section mixes bullets with prose, so an "
              "observation would be dropped: the policy is one bullet per "
              "observation")
        return TRUST_FAILURE
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

    continuation_body = (
        "## Verification\n- [ ] CI green\n\n"
        "## Follow-ups\n- One observation\n  continued on a second line\n"
    )
    status, items = extract_follow_ups(continuation_body)
    assert status == "items", "a continuation must not read as mixed"
    assert items == ["One observation continued on a second line"], (
        "the continuation must be folded into its item, got {!r}".format(items))
    print("ok: an indented continuation folds into its bullet -> one complete item")

    for label, section in [
        ("prose before the first bullet", "prose first\n- a bullet\n"),
        ("prose between two bullets", "- a\nprose between\n- b\n"),
        ("an empty bullet payload", "- a\n-\n"),
    ]:
        status, items = extract_follow_ups(
            "## Verification\n- [ ] CI green\n\n## Follow-ups\n" + section)
        assert status == "mixed", "{} must fail closed, got {!r}".format(label, status)
        assert items == [], "{} must report no item".format(label)
        print("ok: {} -> mixed, and no item is reported".format(label))

    mixed_body = (
        "## Verification\n- [ ] CI green\n\n"
        "## Follow-ups\n- One observation as a bullet\n"
        "and a second one written as prose beside it\n"
    )
    status, items = extract_follow_ups(mixed_body)
    assert status == "mixed", "expected 'mixed', got {!r}".format(status)
    assert items == [], "mixed must not report the bullets it can parse"
    print("ok: bullets mixed with prose -> mixed, and no item is reported")

    loose_none_body = (
        "## Verification\n- [ ] CI green\n\n## Follow-ups\nNONE\n"
    )
    status, items = extract_follow_ups(loose_none_body)
    assert status == "missing", "a non-literal None must not read as 'none'"
    print("ok: 'NONE' is not the literal the policy names -> missing")

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
