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
  0  an explicit answer was found: "items" (one or more bullets) or "none"
     (the section reads the literal line "None.")
  2  every other status -- "missing" (no section, or one with no parseable
     content), "mixed" (bullets and prose both present, or an empty bullet
     payload, so an item would be dropped if it were reported), "not_closing"
     (a heading follows the section, so it is not the review's closing
     section) -- is a review process defect to flag, not silence to pass
     through. See STATUS_EXITS below for the routing this tool commits to.
     The body file being unreadable or not valid UTF-8 also exits 2, before
     any of the above classification runs.
"""
import argparse
import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TRUST_FAILURE = 2

# The single routing declaration: every status extract_follow_ups can return
# is a key here, mapped to the exit code report() gives it. --self-test
# derives the status set straight from extract_follow_ups's own Return nodes
# (see _emittable_statuses) and asserts it equals set(STATUS_EXITS), so an
# emittable status this map does not route fails the self-test instead of
# silently exiting 0.
STATUS_EXITS = {
    "items": 0,
    "none": 0,
    "missing": TRUST_FAILURE,
    "mixed": TRUST_FAILURE,
    "not_closing": TRUST_FAILURE,
}

HEADING_RE = re.compile(r"^#{1,6}\s")
FOLLOW_UPS_HEADING_RE = re.compile(r"^#{1,6}\s*Follow-ups:?\s*$", re.IGNORECASE)
# The policy names the literal line `None.`, so that is what is accepted:
# an optional period and a case-insensitive match were a looser grammar
# than the contract this tool exists to enforce.
NONE_LITERAL = "None."
BULLET_RE = re.compile(r"^[-*]\s+(.*\S)\s*$")
# A bullet marker with nothing after it: no payload group, so unlike
# BULLET_RE above there is nothing to capture. Matched separately rather than
# folded into BULLET_RE's payload group as optional, so the two stay simple
# to read against each other: one owns non-empty bullets, one owns empty
# ones, and classification below decides what an empty one means.
EMPTY_BULLET_RE = re.compile(r"^[-*]\s*$")


def extract_follow_ups(text):
    """Classify the Follow-ups section of a review body.

    Returns (status, items):
      ("none", [])          -- section present, explicitly says None.
      ("items", [...])      -- section present, one or more bullet items
      ("missing", [])       -- no Follow-ups section, or one with no
                               parseable content (neither None. nor bullets)
      ("mixed", [])         -- section present but mixes bullets with prose,
                               or has an empty bullet payload, so an item
                               would be dropped if it were reported
      ("not_closing", [])   -- a heading follows the Follow-ups section, so
                               it is not the review's closing section
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
    # empty bullet payload fails closed, and an indented line that is not
    # itself a bullet marker is folded into the item above it. The last clause
    # said "an indented line" until an isolated empty marker was made to fail
    # closed; indentation has never overridden bullet shape, so an indented
    # `- x` was already a new item rather than a continuation, and the loop
    # below is what that sentence has to match.
    kept = [ln.rstrip() for ln in body if ln.strip()]
    if not kept:
        return "missing", []

    if len(kept) == 1 and kept[0].strip() == NONE_LITERAL:
        return "none", []

    items = []
    unparsed = []
    empty_bullet = False
    for ln in kept:
        stripped = ln.strip()
        if EMPTY_BULLET_RE.match(stripped):
            empty_bullet = True
            continue
        match = BULLET_RE.match(stripped)
        if match:
            items.append(match.group(1).strip())
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
    """Print the classification and return the process exit code.

    The exit code is looked up in STATUS_EXITS rather than decided here, so
    that a status the map does not know how to route fails loudly instead of
    silently falling through to whichever branch happens to run last.
    """
    print("status: {}".format(status))
    if status == "items":
        print("count: {}".format(len(items)))
        for i, item in enumerate(items, start=1):
            print("{}. {}".format(i, item))
    elif status == "mixed":
        print("the Follow-ups section has an empty bullet marker, "
              "unindented prose beside a bullet, or both, so an observation "
              "would be dropped: the policy is one bullet per observation, "
              "each with a payload")
    elif status == "not_closing":
        print("the review does not end with its Follow-ups section: a heading "
              "follows it, so it is not the closing section the policy requires")
    if status not in STATUS_EXITS:
        raise ValueError("unrouted status: {!r}".format(status))
    return STATUS_EXITS[status]


def _emittable_statuses():
    """Derive, from this file's own source, every status extract_follow_ups
    can return.

    A hand-maintained list of statuses would only ever catch drift someone
    remembered to update by hand -- the same failure this check exists to
    close. Parsing the function's own Return nodes ties the assertion to the
    code that actually decides routing, so a status added here without being
    routed in STATUS_EXITS (or vice versa) fails --self-test instead of
    silently reaching report() and exiting 0.
    """
    source_path = Path(__file__)
    # Named by basename, never by path: self-test output is pasted into
    # published review bodies, and the deployment path of this file is the
    # class of value that must not travel with it -- the same reason
    # main() reports a body-file failure without its location.
    source_name = source_path.name
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=source_name)
    except OSError as error:
        # Same reasoning as main()'s body-file read: str(OSError) carries the
        # full path via error.filename, so only strerror is safe to print.
        raise AssertionError(
            "cannot read/parse {} to derive emittable statuses: {}".format(
                source_name, error.strerror or "unreadable"))
    except SyntaxError as error:
        # ast.parse was called with filename=source_name (the basename), so
        # str(SyntaxError) reports that name rather than the deployment path.
        raise AssertionError(
            "cannot read/parse {} to derive emittable statuses: {}".format(
                source_name, error))

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "extract_follow_ups":
            func_node = node
            break
    if func_node is None:
        raise AssertionError(
            "extract_follow_ups not found in {}; cannot derive its "
            "emittable statuses".format(source_name))

    statuses = set()
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if not isinstance(value, ast.Tuple) or not value.elts:
            raise AssertionError(
                "{}:{}: extract_follow_ups has a return that is not a "
                "(status, items) tuple; cannot derive its status".format(
                    source_name, node.lineno))
        first = value.elts[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            raise AssertionError(
                "{}:{}: extract_follow_ups returns a first element that is "
                "not a string literal; cannot derive its status".format(
                    source_name, node.lineno))
        statuses.add(first.value)
    return statuses


def run_invalid_utf8_body_fixture_test():
    """Exercise the real --body-file CLI on a file that is not valid UTF-8.

    In-process assertions call extract_follow_ups directly and never touch
    Path.read_text, so they cannot exercise the decode failure the finding
    this fixture proves fixed was about: a non-UTF-8 body file reaching an
    uncaught UnicodeDecodeError traceback that printed this script's own
    deployment path. Only a subprocess drives the real read boundary in
    main().
    """
    invalid_utf8_body = b"## Follow-ups\n- bad byte: \xff here\n"
    with tempfile.TemporaryDirectory() as fixture_dir:
        fixture_path = Path(fixture_dir) / "invalid-utf8-body.txt"
        fixture_path.write_bytes(invalid_utf8_body)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--body-file", str(fixture_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    combined = result.stdout + result.stderr
    assert result.returncode == TRUST_FAILURE, (
        "expected exit {}, got {}: {!r}".format(
            TRUST_FAILURE, result.returncode, combined))
    assert "Traceback" not in combined, (
        "a traceback leaked: {!r}".format(combined))
    checkout_dir = str(Path(__file__).resolve().parent)
    assert checkout_dir not in combined, (
        "the checkout path leaked: {!r}".format(combined))
    print("CLI fixture (invalid UTF-8 body file): exit {}, no traceback, "
          "no path".format(TRUST_FAILURE))


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
        ("a valid bullet followed by an empty bullet marker", "- a\n-\n"),
        ("an empty bullet marker alone, isolated with no other content", "-\n"),
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

    emittable = _emittable_statuses()
    assert emittable == set(STATUS_EXITS), (
        "extract_follow_ups can emit {!r} but STATUS_EXITS routes {!r} -- "
        "the sets must be equal".format(emittable, set(STATUS_EXITS)))
    print("ok: every status extract_follow_ups can emit is routed in "
          "STATUS_EXITS, and vice versa -- {}".format(sorted(emittable)))

    for status, expected_exit in sorted(STATUS_EXITS.items()):
        exit_code = report(status, ["x"] if status == "items" else [])
        assert exit_code == expected_exit, (
            "report({!r}, ...) returned {}, expected {}".format(
                status, exit_code, expected_exit))
    print("ok: report() exit code matches STATUS_EXITS for every routed "
          "status -- {}".format(sorted(STATUS_EXITS.items())))

    run_invalid_utf8_body_fixture_test()

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
        try:
            return run_self_test()
        except AssertionError as error:
            # Every self-test check is a bare assert: left uncaught, the
            # interpreter would print traceback lines carrying this file's
            # deployment path before the message below, and self-test output
            # is pasted verbatim into published review bodies. Catching here,
            # once, covers every assertion instead of hardening each one.
            print("self-test failed: {}".format(error), file=sys.stderr)
            return 1

    try:
        text = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as error:
        # The path is caller-supplied and can be a deployment path: report the
        # failure, never the location.
        print("error: cannot read the review body file: {}".format(
            error.strerror or "unreadable"), file=sys.stderr)
        return TRUST_FAILURE
    except UnicodeDecodeError:
        # UnicodeDecodeError is a ValueError, not an OSError, so the branch
        # above never catches it: a non-UTF-8 body file reached an uncaught
        # traceback here before this branch existed, and that traceback
        # printed this file's own deployment path -- the same disclosure the
        # OSError branch above exists to prevent. str(UnicodeDecodeError)
        # does not happen to include the file path, but that is not relied
        # on: the message is a fixed description, built the same way the
        # OSError branch builds one from strerror rather than the raw error.
        # Malformed input is a classification this tool has a vocabulary
        # for, not a bug, so it exits TRUST_FAILURE rather than crashing.
        print("error: cannot read the review body file: not valid UTF-8",
              file=sys.stderr)
        return TRUST_FAILURE

    status, items = extract_follow_ups(text)
    return report(status, items)


if __name__ == "__main__":
    sys.exit(main())
