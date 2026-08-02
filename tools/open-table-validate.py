#!/usr/bin/env python3
"""Validate an Open Table v0 comment envelope without network access.

Usage:
  python3 tools/open-table-validate.py [COMMENT_PATH]
  printf '%s' "$COMMENT" | python3 tools/open-table-validate.py
  python3 tools/open-table-validate.py --integrity-bundle BUNDLE.json
  python3 tools/open-table-validate.py --self-test
"""

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path


COMMON_FIELDS = {"open-table", "message", "id"}
MESSAGE_FIELDS = {
    "configuration": {
        "phase", "sequence", "expected-actors", "authority-profile", "turn-limit"
    },
    "contribution": {"phase", "turn"},
    "proposal": {"phase", "turn", "point"},
    "settled": {
        "phase", "turn", "point", "proposal-id", "disposition", "terminal"
    },
    "claim": {"claim", "expires-at"},
    "renewal": {"claim", "expires-at"},
    "release": {"claim"},
    "handoff": {"claim", "to-actor-id", "expires-at"},
    "cancellation": {"claim"},
    "expiration": {"claim", "expired-at"},
    "result": {"claim", "result-id", "outcome", "artefact"},
    "review-request": {"claim", "review", "result-id", "artefact"},
    "verdict": {"claim", "review", "result-id", "artefact", "verdict"},
    "ruling": {
        "target-actor-id", "message-id", "source-comment-id", "source-digest",
        "decision"
    },
}
TOKEN_FIELDS = {"phase", "point", "claim", "proposal-id", "result-id", "review"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
KEY_RE = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
TIMESTAMP_RE = re.compile(
    r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-"
    r"(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GITHUB_ARTEFACT_RE = re.compile(
    r"^github:[1-9][0-9]*:pull:[1-9][0-9]*:head:(?:[0-9a-f]{40}|[0-9a-f]{64})$"
)
GENERIC_ARTEFACT_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s#]+#sha256=[0-9a-f]{64}$"
)
OPENING_RE = re.compile(r"\A\s*```open-table[ \t]*\r?\n")
CLOSING_RE = re.compile(r"^```[ \t]*(?:\r\n|\n)", re.MULTILINE)
BLOCK_OPENING_RE = re.compile(r"^```open-table[ \t]*(?:\r\n|\n)", re.MULTILINE)


class ValidationError(ValueError):
    """A readable structural validation failure."""


def canonical_digest(body):
    """Return the canonical digest of one complete GitHub comment body."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def parse_comment(body):
    """Return the validated header and human prose from a comment body."""
    opening = OPENING_RE.match(body)
    if not opening:
        raise ValidationError(
            "comment must begin with a fenced block whose info string is open-table"
        )

    closing = CLOSING_RE.search(body, opening.end())
    if not closing:
        raise ValidationError("open-table fenced block is not closed")

    header_text = body[opening.end():closing.start()]
    prose = body[closing.end():]

    if BLOCK_OPENING_RE.search(prose):
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

    for field in ("sequence", "turn-limit"):
        if field in header:
            if not header[field].isdigit() or int(header[field]) < 1:
                raise ValidationError(
                    "{} must be a base-10 integer of at least 1".format(field)
                )

    for field in ("expires-at", "expired-at"):
        if field in header:
            timestamp = header[field]
            if not TIMESTAMP_RE.fullmatch(timestamp):
                raise ValidationError(
                    "{} must use the exact RFC 3339 UTC form".format(field)
                )
            try:
                datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as error:
                raise ValidationError(
                    "{} is not a real UTC date and time".format(field)
                ) from error

    for field in ("target-actor-id", "to-actor-id", "source-comment-id"):
        if field in header:
            if not header[field].isdigit() or int(header[field]) < 1:
                raise ValidationError(
                    "{} must be a positive numeric GitHub id".format(field)
                )

    if "message-id" in header and not ID_RE.fullmatch(header["message-id"]):
        raise ValidationError("message-id does not match the Open Table token syntax")

    if "expected-actors" in header:
        actors = header["expected-actors"].split(",")
        if (
            any(not actor.isdigit() or int(actor) < 1 for actor in actors)
            or len(actors) != len(set(actors))
        ):
            raise ValidationError(
                "expected-actors must be unique numeric GitHub ids separated by commas"
            )

    if "source-digest" in header and not DIGEST_RE.fullmatch(header["source-digest"]):
        raise ValidationError("source-digest must be a canonical sha256 digest")

    if "artefact" in header and not (
        GITHUB_ARTEFACT_RE.fullmatch(header["artefact"])
        or GENERIC_ARTEFACT_RE.fullmatch(header["artefact"])
    ):
        raise ValidationError("artefact must be an immutable GitHub or generic reference")

    enumerations = {
        "disposition": {"accepted", "rejected"},
        "terminal": {"true", "false"},
        "outcome": {"completed", "failed"},
        "verdict": {"approved", "changes-requested"},
        "decision": {
            "authorized", "unauthorized", "awarded", "rejected", "invalidated"
        },
        "authority-profile": {
            "deliberation-only", "open-table/ordered-claims", "steve/kanban"
        },
    }
    for field, allowed in enumerations.items():
        if field in header and header[field] not in allowed:
            raise ValidationError(
                "{} must be one of: {}".format(field, ", ".join(sorted(allowed)))
            )


def validate_integrity_bundle(bundle):
    """Validate trusted event integrity without performing protocol reduction."""
    if not isinstance(bundle, dict) or set(bundle) != {"ordered_events"}:
        raise ValidationError("integrity bundle must contain only ordered_events")
    events = bundle["ordered_events"]
    if not isinstance(events, list) or not events:
        raise ValidationError("ordered_events must be a non-empty list")

    parsed = []
    by_comment_id = {}
    seen_messages = {}
    notices = []
    previous_order = None

    for index, event in enumerate(events, 1):
        required = {"actor_id", "comment_id", "created_at", "body"}
        if not isinstance(event, dict) or set(event) != required:
            raise ValidationError(
                "event {} must contain actor_id, comment_id, created_at, and body".format(
                    index
                )
            )
        actor_id = event["actor_id"]
        comment_id = event["comment_id"]
        created_at = event["created_at"]
        body = event["body"]
        if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id < 1:
            raise ValidationError("event {} actor_id must be a positive integer".format(index))
        if (
            isinstance(comment_id, bool)
            or not isinstance(comment_id, int)
            or comment_id < 1
        ):
            raise ValidationError(
                "event {} comment_id must be a positive integer".format(index)
            )
        if comment_id in by_comment_id:
            raise ValidationError("duplicate trusted comment id: {}".format(comment_id))
        if not isinstance(created_at, str) or not TIMESTAMP_RE.fullmatch(created_at):
            raise ValidationError(
                "event {} created_at must use the exact RFC 3339 UTC form".format(index)
            )
        try:
            datetime.datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as error:
            raise ValidationError(
                "event {} created_at is not a real UTC date and time".format(index)
            ) from error
        if not isinstance(body, str):
            raise ValidationError("event {} body must be a string".format(index))

        order = (created_at, comment_id)
        if previous_order is not None and order < previous_order:
            raise ValidationError("ordered_events are not in trusted GitHub order")
        previous_order = order

        header, _ = parse_comment(body)
        digest = canonical_digest(body)
        key = (actor_id, header["id"])
        if key in seen_messages:
            previous_digest = seen_messages[key]
            if digest != previous_digest:
                raise ValidationError(
                    "conflict: actor {} message id {} has a different digest; "
                    "it is not a duplicate".format(actor_id, header["id"])
                )
            notices.append(
                "exact duplicate: actor {} message id {} digest {}".format(
                    actor_id, header["id"], digest
                )
            )
        else:
            seen_messages[key] = digest

        record = {
            "actor_id": actor_id,
            "comment_id": comment_id,
            "header": header,
            "digest": digest,
        }
        parsed.append(record)
        by_comment_id[comment_id] = record

    ruled_sources = set()
    for record in parsed:
        header = record["header"]
        if header["message"] != "ruling":
            continue
        source_comment_id = int(header["source-comment-id"])
        source = by_comment_id.get(source_comment_id)
        if source is None:
            raise ValidationError(
                "ruling source comment {} is deleted or missing; fail closed".format(
                    source_comment_id
                )
            )
        if source["actor_id"] != int(header["target-actor-id"]):
            raise ValidationError("ruling target actor does not match trusted source actor")
        if source["header"]["id"] != header["message-id"]:
            raise ValidationError("ruling message id does not match its bound source")
        if source["digest"] != header["source-digest"]:
            raise ValidationError(
                "ruling source digest mismatch; source was edited or binding is invalid; "
                "fail closed"
            )
        ruled_sources.add(source_comment_id)

    requires_ruling = {
        "configuration", "settled", "claim", "renewal", "release", "handoff",
        "cancellation", "result", "review-request", "verdict"
    }
    for record in parsed:
        if (
            record["header"]["message"] in requires_ruling
            and record["comment_id"] not in ruled_sources
        ):
            raise ValidationError(
                "required ruling for source comment {} is deleted or missing; "
                "fail closed".format(record["comment_id"])
            )

    return notices


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
        "configuration": [
            ("phase", "dreamer"),
            ("sequence", "1"),
            ("expected-actors", "101,202"),
            ("authority-profile", "open-table/ordered-claims"),
            ("turn-limit", "3"),
        ],
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
        "renewal": [
            ("claim", "implementation"),
            ("expires-at", "2026-08-02T12:00:00Z"),
        ],
        "release": [("claim", "implementation")],
        "handoff": [
            ("claim", "implementation"),
            ("to-actor-id", "202"),
            ("expires-at", "2026-08-01T12:00:00Z"),
        ],
        "cancellation": [("claim", "implementation")],
        "expiration": [
            ("claim", "implementation"),
            ("expired-at", "2026-08-01T12:00:00Z"),
        ],
        "result": [
            ("claim", "implementation"),
            ("result-id", "result-1"),
            ("outcome", "completed"),
            ("artefact", "github:123:pull:45:head:" + "a" * 40),
        ],
        "review-request": [
            ("claim", "implementation"),
            ("review", "review-1"),
            ("result-id", "result-1"),
            ("artefact", "github:123:pull:45:head:" + "a" * 40),
        ],
        "verdict": [
            ("claim", "implementation"),
            ("review", "review-1"),
            ("result-id", "result-1"),
            ("artefact", "github:123:pull:45:head:" + "a" * 40),
            ("verdict", "approved"),
        ],
        "ruling": [
            ("target-actor-id", "101"),
            ("message-id", "fixture-claim-0001"),
            ("source-comment-id", "77"),
            ("source-digest", "sha256:" + "0" * 64),
            ("decision", "awarded"),
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
        "closing fence on header line": (
            "```open-table\nopen-table: 0\nmessage: contribution\n"
            "id: malformed-0004\nphase: dreamer\nturn: 1```\n\nA contribution."
        ),
        "duplicate block with CRLF": (
            "```open-table\r\nopen-table: 0\r\nmessage: release\r\n"
            "id: malformed-0005\r\nclaim: work\r\n```\r\n\r\nFirst block.\r\n"
            "```open-table\r\nopen-table: 0\r\nmessage: release\r\n"
            "id: malformed-0006\r\nclaim: work\r\n```\r\n\r\nSecond block."
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

    duplicate_body = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    )
    duplicate_bundle = {
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 1,
                "created_at": "2026-08-01T00:00:00Z",
                "body": duplicate_body,
            },
            {
                "actor_id": 101,
                "comment_id": 2,
                "created_at": "2026-08-01T00:00:01Z",
                "body": duplicate_body,
            },
        ]
    }
    notices = validate_integrity_bundle(duplicate_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (exact duplicate): accepted")

    conflict_bundle = json.loads(json.dumps(duplicate_bundle))
    conflict_bundle["ordered_events"][1]["body"] += "\nChanged prose."
    try:
        validate_integrity_bundle(conflict_bundle)
    except ValidationError as error:
        assert "conflict:" in str(error) and "not a duplicate" in str(error)
        print("integrity fixture (digest conflict): rejected: {}".format(error))
    else:
        raise AssertionError("digest conflict was accepted as a duplicate")

    source_body = make_fixture(
        "claim", [("claim", "implementation"), ("expires-at", "2026-08-01T12:00:00Z")]
    )
    mismatch_ruling = make_fixture(
        "ruling",
        [
            ("target-actor-id", "101"),
            ("message-id", "fixture-claim-0001"),
            ("source-comment-id", "3"),
            ("source-digest", "sha256:" + "0" * 64),
            ("decision", "awarded"),
        ],
    )
    mismatch_bundle = {
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 3,
                "created_at": "2026-08-01T00:00:00Z",
                "body": source_body,
            },
            {
                "actor_id": 999,
                "comment_id": 4,
                "created_at": "2026-08-01T00:00:01Z",
                "body": mismatch_ruling,
            },
        ]
    }
    try:
        validate_integrity_bundle(mismatch_bundle)
    except ValidationError as error:
        assert "digest mismatch" in str(error) and "fail closed" in str(error)
        print("integrity fixture (ruling digest mismatch): rejected: {}".format(error))
    else:
        raise AssertionError("ruling digest mismatch did not fail closed")

    print("self-test: 14 valid families, 5 malformed fixtures, and 3 integrity rules passed")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate an Open Table v0 comment from a path or stdin."
    )
    parser.add_argument("path", nargs="?", help="comment body path; omit to read stdin")
    parser.add_argument(
        "--self-test", action="store_true", help="run offline assertions and exit"
    )
    parser.add_argument(
        "--integrity-bundle",
        metavar="PATH",
        help="validate trusted event integrity from a JSON bundle",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        if args.path or args.integrity_bundle:
            print("error: --self-test does not accept another input", file=sys.stderr)
            return 2
        run_self_test()
        return 0

    if args.integrity_bundle:
        if args.path:
            print("error: --integrity-bundle does not accept a comment path", file=sys.stderr)
            return 2
        try:
            bundle = json.loads(Path(args.integrity_bundle).read_text(encoding="utf-8"))
            notices = validate_integrity_bundle(bundle)
        except (OSError, json.JSONDecodeError) as error:
            print("error: cannot read integrity bundle: {}".format(error), file=sys.stderr)
            return 2
        except ValidationError as error:
            print("invalid integrity bundle: {}".format(error), file=sys.stderr)
            return 1
        for notice in notices:
            print(notice)
        print("valid integrity bundle: {} ordered event(s)".format(len(bundle["ordered_events"])))
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
