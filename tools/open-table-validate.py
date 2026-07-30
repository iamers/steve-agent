#!/usr/bin/env python3
"""Validate an Open Table v0 comment envelope without network access.

Usage:
  python3 tools/open-table-validate.py [COMMENT_PATH]
  printf '%s' "$COMMENT" | python3 tools/open-table-validate.py
  python3 tools/open-table-validate.py --self-test
"""

import argparse
import datetime
import re
import sys
from pathlib import Path


COMMON_FIELDS = {"open-table", "message", "id"}
MESSAGE_FIELDS = {
    "contribution": {"phase", "turn"},
    "proposal": {"phase", "turn", "point"},
    "settled": {
        "phase", "turn", "point", "proposal-id", "disposition", "terminal"
    },
    "claim": {"claim", "expires-at"},
    "release": {"claim"},
    "handoff": {"claim", "to", "expires-at"},
    "result": {"claim", "outcome"},
    "review-request": {"claim", "review"},
    "verdict": {"claim", "review", "verdict"},
}
TOKEN_FIELDS = {"phase", "point", "claim", "proposal-id", "review"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
KEY_RE = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
TIMESTAMP_RE = re.compile(
    r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-"
    r"(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
OPENING_RE = re.compile(r"\A\s*```open-table[ \t]*\r?\n")


class ValidationError(ValueError):
    """A readable structural validation failure."""


def parse_comment(body):
    """Return the validated header and human prose from a comment body."""
    opening = OPENING_RE.match(body)
    if not opening:
        raise ValidationError(
            "comment must begin with a fenced block whose info string is open-table"
        )

    closing_start = body.find("```", opening.end())
    if closing_start < 0:
        raise ValidationError("open-table fenced block is not closed")

    header_text = body[opening.end():closing_start]
    after_fence = body[closing_start + 3:]
    if after_fence.startswith("\r\n"):
        prose = after_fence[2:]
    elif after_fence.startswith("\n"):
        prose = after_fence[1:]
    else:
        raise ValidationError("closing fence must end its line before the prose")

    if re.search(r"^```open-table[ \t]*$", prose, re.MULTILINE):
        raise ValidationError("comment must contain exactly one open-table fenced block")
    if not prose.strip():
        raise ValidationError("comment must contain human-readable prose after the header")

    header = parse_header(header_text)
    validate_header(header)
    return header, prose


def parse_header(header_text):
    """Parse strict single-line key/value pairs from an envelope header."""
    header = {}
    lines = header_text.splitlines()
    if not lines:
        raise ValidationError("open-table header is empty")

    for number, line in enumerate(lines, 1):
        if not line:
            raise ValidationError("header line {} is empty".format(number))
        if ": " not in line:
            raise ValidationError(
                "header line {} must have the form key: value".format(number)
            )
        key, value = line.split(": ", 1)
        if not KEY_RE.fullmatch(key):
            raise ValidationError("invalid header key on line {}".format(number))
        if not value or value != value.strip():
            raise ValidationError(
                "header value for {} must be non-empty and unpadded".format(key)
            )
        if key in header:
            raise ValidationError("duplicate header key: {}".format(key))
        header[key] = value
    return header


def validate_header(header):
    """Validate common fields and the exact field set for one message family."""
    if header.get("open-table") != "0":
        raise ValidationError("open-table must be the literal 0")

    message = header.get("message")
    if message not in MESSAGE_FIELDS:
        raise ValidationError("unknown or missing message type: {}".format(message))

    expected = COMMON_FIELDS | MESSAGE_FIELDS[message]
    missing = sorted(expected - set(header))
    unknown = sorted(set(header) - expected)
    if missing:
        raise ValidationError("missing required field(s): {}".format(", ".join(missing)))
    if unknown:
        raise ValidationError("unknown field(s): {}".format(", ".join(unknown)))

    if not ID_RE.fullmatch(header["id"]):
        raise ValidationError("id does not match the Open Table token syntax")

    for field in TOKEN_FIELDS & set(header):
        if not TOKEN_RE.fullmatch(header[field]):
            raise ValidationError("{} does not match the token syntax".format(field))

    if "turn" in header:
        if not header["turn"].isdigit() or int(header["turn"]) < 1:
            raise ValidationError("turn must be a base-10 integer of at least 1")

    if "expires-at" in header:
        timestamp = header["expires-at"]
        if not TIMESTAMP_RE.fullmatch(timestamp):
            raise ValidationError("expires-at must use the exact RFC 3339 UTC form")
        try:
            datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as error:
            raise ValidationError("expires-at is not a real UTC date and time") from error

    if "to" in header and not LOGIN_RE.fullmatch(header["to"]):
        raise ValidationError("to must be a syntactically valid GitHub login")

    enumerations = {
        "disposition": {"accepted", "rejected"},
        "terminal": {"true", "false"},
        "outcome": {"completed", "failed"},
        "verdict": {"approved", "changes-requested"},
    }
    for field, allowed in enumerations.items():
        if field in header and header[field] not in allowed:
            raise ValidationError(
                "{} must be one of: {}".format(field, ", ".join(sorted(allowed)))
            )


def make_fixture(message, fields):
    """Build a self-test comment from a message name and its specific fields."""
    lines = [
        "```open-table",
        "open-table: 0",
        "message: {}".format(message),
        "id: fixture-{}-0001".format(message),
    ]
    lines.extend("{}: {}".format(key, value) for key, value in fields)
    lines.extend(["```", "", "Human-readable fixture for {}.".format(message)])
    return "\n".join(lines)


def run_self_test():
    """Exercise every family and malformed envelopes without network access."""
    valid = {
        "contribution": [("phase", "dreamer"), ("turn", "1")],
        "proposal": [("phase", "dreamer"), ("turn", "1"), ("point", "scope")],
        "settled": [
            ("phase", "critic"),
            ("turn", "1"),
            ("point", "scope"),
            ("proposal-id", "proposal-0001"),
            ("disposition", "accepted"),
            ("terminal", "true"),
        ],
        "claim": [("claim", "implementation"), ("expires-at", "2026-08-01T12:00:00Z")],
        "release": [("claim", "implementation")],
        "handoff": [
            ("claim", "implementation"),
            ("to", "next-contributor"),
            ("expires-at", "2026-08-01T12:00:00Z"),
        ],
        "result": [("claim", "implementation"), ("outcome", "completed")],
        "review-request": [("claim", "implementation"), ("review", "review-1")],
        "verdict": [
            ("claim", "implementation"),
            ("review", "review-1"),
            ("verdict", "approved"),
        ],
    }

    for message, fields in valid.items():
        header, prose = parse_comment(make_fixture(message, fields))
        assert header["message"] == message
        assert prose.strip()
        print("valid fixture ({}): ok".format(message))

    malformed = {
        "missing prose": (
            "```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0001\nclaim: work\n```\n"
        ),
        "missing required field": (
            "```open-table\nopen-table: 0\nmessage: claim\n"
            "id: malformed-0002\nclaim: work\n```\n\nClaiming work."
        ),
        "unknown field": (
            "```open-table\nopen-table: 0\nmessage: contribution\n"
            "id: malformed-0003\nphase: dreamer\nturn: 1\nruntime: required\n"
            "```\n\nA contribution."
        ),
    }
    for label, fixture in malformed.items():
        try:
            parse_comment(fixture)
        except ValidationError as error:
            assert str(error)
            print("malformed fixture ({}): rejected: {}".format(label, error))
        else:
            raise AssertionError("malformed fixture was accepted: {}".format(label))

    print("self-test: 9 valid families and 3 malformed fixtures passed")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate an Open Table v0 comment from a path or stdin."
    )
    parser.add_argument("path", nargs="?", help="comment body path; omit to read stdin")
    parser.add_argument(
        "--self-test", action="store_true", help="run offline assertions and exit"
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        if args.path:
            print("error: --self-test does not accept a comment path", file=sys.stderr)
            return 2
        run_self_test()
        return 0

    try:
        body = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
    except OSError as error:
        print("error: cannot read comment: {}".format(error), file=sys.stderr)
        return 2

    try:
        header, _ = parse_comment(body)
    except ValidationError as error:
        print("invalid: {}".format(error), file=sys.stderr)
        return 1

    print("valid: Open Table v0 {} message".format(header["message"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
