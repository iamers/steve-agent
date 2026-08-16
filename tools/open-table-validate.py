#!/usr/bin/env python3
"""Validate an Open Table v0 comment envelope without network access.

Usage:
  python3 tools/open-table-validate.py [COMMENT_PATH]
  printf '%s' "$COMMENT" | python3 tools/open-table-validate.py
  python3 tools/open-table-validate.py --integrity-bundle BUNDLE.json
  python3 tools/open-table-validate.py --self-test
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from open_table_core import (
    MAX_PROTOCOL_INTEGER,
    MESSAGE_FIELDS,
    REASON_CATALOG,
    ValidationError,
    canonical_digest,
    make_diagnostic,
    parse_comment,
    parse_integrity_bundle_json,
    validate_integrity_bundle,
    validate_integrity_bundle_diagnostics,
)


def assert_live_case_names(cases, label):
    """Reject empty or duplicate external fixture case lists."""
    if not isinstance(cases, list) or not cases:
        raise AssertionError("{} fixture manifest must contain cases".format(label))
    names = [case.get("name") for case in cases]
    if any(not isinstance(name, str) or not name for name in names):
        raise AssertionError("{} fixture names must be non-empty strings".format(label))
    if len(names) != len(set(names)):
        raise AssertionError("{} fixture names must be unique".format(label))
    return names


def run_integrity_fixture_test():
    """Run external integrity cases through structured production entry points."""
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "docs/specs/open-table-v0/fixtures/integrity.json"
    )
    manifest = parse_integrity_bundle_json(fixture_path.read_text(encoding="utf-8"))
    if set(manifest) != {"open_table", "suite_version", "cases"}:
        raise AssertionError("integrity fixture manifest must use the closed suite shape")
    if manifest["open_table"] != 0 or manifest["suite_version"] != 1:
        raise AssertionError("integrity fixture manifest version is unsupported")
    cases = manifest["cases"]
    names = assert_live_case_names(cases, "integrity")
    expected_names = {
        "integrity.valid_comment", "integrity.valid_bundle",
        "integrity.invalid_bundle", "integrity.malformed_bundle_json",
        "integrity.event_order_invalid",
        "integrity.non_protocol_comment", "integrity.invalid_envelope",
        "integrity.invalid_field", "integrity.invalid_artefact",
        "integrity.exact_duplicate", "integrity.message_id_conflict",
        "integrity.unauthorized_reducer_output",
        "integrity.ruling_missing", "integrity.ruling_duplicate",
        "integrity.ruling_binding_invalid", "integrity.ruling_decision_invalid",
    }
    assert set(names) == expected_names
    entry_points = {
        "parse_comment": parse_comment,
        "parse_integrity_bundle_json": parse_integrity_bundle_json,
        "validate_integrity_bundle_diagnostics": validate_integrity_bundle_diagnostics,
    }
    observed = {}
    for case in cases:
        if set(case) != {"name", "entry_point", "input", "expected"}:
            raise AssertionError("integrity fixture case must use the closed case shape")
        entry_point = entry_points.get(case["entry_point"])
        if entry_point is None:
            raise AssertionError(
                "integrity fixture names unknown entry point: {}".format(
                    case["entry_point"]
                )
            )
        expected = case["expected"]
        diagnostic = None
        try:
            result = entry_point(case["input"])
        except ValidationError as error:
            diagnostic = error.diagnostic
            assert diagnostic is not None
        else:
            if expected == {"status": "success"}:
                if case["entry_point"] != "parse_comment":
                    assert result == []
                continue
            assert isinstance(result, list) and len(result) == 1
            diagnostic = result[0]
        assert set(expected) == {"severity", "code", "rule"}
        assert diagnostic.severity == expected["severity"]
        assert diagnostic.code == expected["code"]
        assert diagnostic.rule == expected["rule"]
        assert diagnostic.comment_id is not None or diagnostic.field is not None
        assert isinstance(diagnostic.detail, str) and diagnostic.detail
        observed[case["name"]] = diagnostic.code
    print("integrity fixtures: {} structured cases passed".format(len(cases)))
    return observed


def run_reason_fixture_test(observed):
    """Prove external/production catalog parity and live coverage."""
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "docs/specs/open-table-v0/fixtures/reason-codes.json"
    )
    manifest = parse_integrity_bundle_json(fixture_path.read_text(encoding="utf-8"))
    if set(manifest) != {"open_table", "suite_version", "reasons"}:
        raise AssertionError("reason manifest must use the closed suite shape")
    if manifest["open_table"] != 0 or manifest["suite_version"] != 1:
        raise AssertionError("reason manifest version is unsupported")
    reasons = manifest["reasons"]
    assert isinstance(reasons, list) and reasons
    codes = [reason.get("code") for reason in reasons]
    assert len(codes) == len(set(codes))
    external = {}
    external_rules = {}
    for reason in reasons:
        assert set(reason) == {"code", "rule", "fixture"}
        external[reason["code"]] = {
            "rule": reason["rule"],
            "fixture": reason["fixture"],
        }
        external_rules[reason["code"]] = {"rule": reason["rule"]}
    assert external_rules == REASON_CATALOG
    assert len(external) == 13
    for code, row in external.items():
        assert observed.get(row["fixture"]) == code
    original = make_diagnostic(
        "excluded", "invalid_field", "original detail", comment_id=7, field="turn"
    ).to_dict()
    revised = make_diagnostic(
        "excluded", "invalid_field", "revised detail", comment_id=7, field="turn"
    ).to_dict()
    original.pop("detail")
    revised.pop("detail")
    assert original == revised
    rejected_probes = 0
    for invalid_cases in ([], [{"name": "duplicate"}, {"name": "duplicate"}]):
        try:
            assert_live_case_names(invalid_cases, "probe")
        except AssertionError:
            rejected_probes += 1
    unknown = dict(external_rules)
    unknown["unknown_reason"] = {"rule": "0"}
    try:
        assert unknown == REASON_CATALOG
    except AssertionError:
        rejected_probes += 1
    assert rejected_probes == 3
    print("reason fixtures: 13 live catalog entries passed")
    print("fixture liveness probes: zero cases, duplicate names, unknown code rejected")


def run_core_import_contract_test():
    """Verify the documented public core surface in a fresh interpreter."""
    expected = {
        "Diagnostic", "MAX_PROTOCOL_INTEGER", "REASON_CATALOG",
        "ValidationError", "canonical_digest", "make_diagnostic",
        "parse_comment", "parse_integrity_bundle_json", "render_diagnostics",
        "validate_integrity_bundle", "validate_integrity_bundle_diagnostics",
    }
    code = (
        "import open_table_core as core; "
        "expected = {!r}; "
        "assert set(core.__all__) == expected; "
        "assert all(hasattr(core, name) for name in expected); "
        "assert core.canonical_digest('fixture').startswith('sha256:')"
    ).format(expected)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr
    print("core public API: fresh import and direct call passed")


def run_external_cli_fixture_test():
    """Exercise the four real external CLI files and stable exits."""
    root = Path(__file__).resolve().parents[1]
    fixture_root = root / "docs/specs/open-table-v0/fixtures"
    commands = [
        ([sys.executable, str(Path(__file__)), str(fixture_root / "valid-comment.md")], 0, "valid: "),
        ([sys.executable, str(Path(__file__)), str(fixture_root / "invalid-comment.md")], 1, "invalid: "),
        ([sys.executable, str(Path(__file__)), "--integrity-bundle", str(fixture_root / "valid-integrity-bundle.json")], 0, "valid integrity bundle: "),
        ([sys.executable, str(Path(__file__)), "--integrity-bundle", str(fixture_root / "invalid-integrity-bundle.json")], 1, "invalid integrity bundle: "),
    ]
    for command, expected_exit, prefix in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        assert result.returncode == expected_exit
        output = result.stdout if expected_exit == 0 else result.stderr
        assert output.startswith(prefix)
    print("CLI fixtures: valid/invalid comment and integrity exits 0/1/0/1 passed")

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
            ("proposal-comment-id", "41"),
            ("disposition", "accepted"),
            ("terminal", "true"),
        ],
        "claim": [("expires-at", "2026-08-01T12:00:00Z")],
        "renewal": [
            ("claim-comment-id", "51"),
            ("expires-at", "2026-08-02T12:00:00Z"),
        ],
        "release": [("claim-comment-id", "51")],
        "handoff": [
            ("claim-comment-id", "51"),
            ("to-actor-id", "202"),
            ("expires-at", "2026-08-01T12:00:00Z"),
        ],
        "cancellation": [("claim-comment-id", "51")],
        "expiration": [
            ("claim-comment-id", "51"),
            ("expired-at", "2026-08-01T12:00:00Z"),
        ],
        "result": [
            ("claim-comment-id", "51"),
            ("outcome", "completed"),
            ("artefact", "github:123:pull:45:head:" + "a" * 40),
        ],
        "review-request": [
            ("claim-comment-id", "51"),
            ("result-comment-id", "61"),
            ("artefact", "github:123:pull:45:head:" + "a" * 40),
        ],
        "verdict": [
            ("claim-comment-id", "51"),
            ("review-comment-id", "71"),
            ("result-comment-id", "61"),
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
        "manifest": [
            ("deletions-accounted", "2"),
            (
                "entries",
                "301/sha256:{}/contribution,304/sha256:{}/settled/311".format(
                    "a" * 64, "b" * 64
                ),
            ),
            ("frozen", "307/2"),
        ],
    }

    # The fixture table is the grammar's, not a hand-kept copy of it: a family
    # added to MESSAGE_FIELDS without a fixture would otherwise be untested and
    # the suite would still pass.
    # Section 3.5: a family name may not contain the character section 4.18 uses
    # to separate the fields of a manifest record. Asserted over the table rather
    # than over a copy of the current names, so it holds for families not yet
    # written: such a family would be a valid envelope that the reducer's own
    # memory could not represent. It runs before the coverage assertion below,
    # which would otherwise fire first on a new family and hide this one.
    assert not [name for name in MESSAGE_FIELDS if "/" in name], sorted(
        name for name in MESSAGE_FIELDS if "/" in name
    )
    print("family names: none contains the manifest record separator")

    assert set(valid) == set(MESSAGE_FIELDS), sorted(
        set(valid) ^ set(MESSAGE_FIELDS)
    )
    print("family coverage: every section 4 family has a valid fixture")

    for message, fields in valid.items():
        header, prose = parse_comment(make_fixture(message, fields))
        assert header["message"] == message
        assert prose.strip()
        print("valid fixture ({}): ok".format(message))

    generic_artefact = make_fixture(
        "result",
        [
            ("claim-comment-id", "51"),
            ("outcome", "completed"),
            (
                "artefact",
                "https://example.com/build%20output#sha256=" + "a" * 64,
            ),
        ],
    )
    assert parse_comment(generic_artefact)[0]["message"] == "result"
    print("integrity fixture (RFC 3986 generic artefact): accepted")

    authority_artefact = generic_artefact.replace(
        "https://example.com/build%20output",
        "https://user:pass@[2001:db8::1]:443/build?format=json",
    )
    assert parse_comment(authority_artefact)[0]["message"] == "result"
    print("integrity fixture (RFC 3986 URI authority): accepted")

    ipvfuture_artefact = generic_artefact.replace(
        "https://example.com/build%20output",
        "https://[V1.example]/build",
    )
    assert parse_comment(ipvfuture_artefact)[0]["message"] == "result"
    print("integrity fixture (uppercase IPvFuture authority): accepted")

    accounting_only_manifest = make_fixture(
        "manifest", [("deletions-accounted", "4")]
    )
    assert parse_comment(accounting_only_manifest)[0]["message"] == "manifest"
    print("integrity fixture (manifest with neither entries nor frozen): accepted")

    zero_count_manifest = make_fixture(
        "manifest",
        [
            ("deletions-accounted", "0"),
            ("entries", "301/sha256:{}/contribution".format("a" * 64)),
        ],
    )
    assert parse_comment(zero_count_manifest)[0]["deletions-accounted"] == "0"
    print("integrity fixture (manifest count of zero, no frozen): accepted")

    crlf_envelope = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    ).replace("\n", "\r\n")
    assert parse_comment(crlf_envelope)[0]["message"] == "contribution"
    print("integrity fixture (CRLF physical lines): accepted")

    indented_fence = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    ).replace("```open-table\n", "   ```open-table\n", 1).replace(
        "\n```\n", "\n   ```\n", 1
    )
    assert parse_comment(indented_fence)[0]["message"] == "contribution"
    print("integrity fixture (three-space fence indentation): accepted")

    malformed = {
        "missing prose": (
            "```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0001\nclaim-comment-id: 51\n```\n"
        ),
        "missing required field": (
            "```open-table\nopen-table: 0\nmessage: claim\n"
            "id: malformed-0002\n```\n\nClaiming work."
        ),
        "participant-allocated claim reference": (
            "```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0010\nclaim: work\n```\n\nRelease."
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
            "id: malformed-0005\r\nclaim-comment-id: 51\r\n```\r\n\r\nFirst block.\r\n"
            "```open-table\r\nopen-table: 0\r\nmessage: release\r\n"
            "id: malformed-0006\r\nclaim-comment-id: 51\r\n```\r\n\r\nSecond block."
        ),
        "four-space opening fence": (
            "    ```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0007\nclaim-comment-id: 51\n```\n\nRelease."
        ),
        "indented duplicate block": (
            "```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0008\nclaim-comment-id: 51\n```\n\nFirst block.\n"
            "   ```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0009\nclaim-comment-id: 51\n   ```\n\nSecond block."
        ),
        "generic artefact with backslash": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://example.com\\artifact#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with invalid percent escape": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://example.com/%GG#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with bracket in path": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://example.com/a[b]#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with malformed IP literal": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://[not-ip]/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with duplicate at-sign": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://user@@example.com/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with nonnumeric port": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://example.com:no/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with raw tab": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://exam\tple.com/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with scoped IPv6": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://[fe80::1%eth0]/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with non-ASCII port": make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", "https://example.com:１２/a#sha256=" + "a" * 64),
            ],
        ),
        "U+0085 header separator": make_fixture(
            "contribution", [("phase", "dreamer"), ("turn", "1")]
        ).replace("open-table: 0\nmessage:", "open-table: 0\u0085message:"),
        "U+2028 header separator": make_fixture(
            "contribution", [("phase", "dreamer"), ("turn", "1")]
        ).replace("open-table: 0\nmessage:", "open-table: 0\u2028message:"),
        "bare carriage return": make_fixture(
            "contribution", [("phase", "dreamer"), ("turn", "1")]
        ).replace("turn: 1\n```", "turn: 1\r\r\n```"),
        "manifest without its required count": make_fixture(
            "manifest", [("entries", "301/sha256:{}/contribution".format("a" * 64))]
        ),
        "manifest count with a leading zero": make_fixture(
            "manifest", [("deletions-accounted", "01")]
        ),
        "manifest count that is negative": make_fixture(
            "manifest", [("deletions-accounted", "-1")]
        ),
        "manifest entry missing its family": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                ("entries", "301/sha256:" + "a" * 64),
            ],
        ),
        "manifest entry with an unknown family": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                ("entries", "301/sha256:{}/checkpoint".format("a" * 64)),
            ],
        ),
        "manifest entry with a truncated digest": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                ("entries", "301/sha256:{}/contribution".format("a" * 63)),
            ],
        ),
        "manifest entry naming one comment twice": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                (
                    "entries",
                    "301/sha256:{}/contribution,301/sha256:{}/proposal".format(
                        "a" * 64, "b" * 64
                    ),
                ),
            ],
        ),
        "manifest entries with a trailing separator": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                ("entries", "301/sha256:{}/contribution,".format("a" * 64)),
            ],
        ),
        "manifest entry ruling id that is not an id": make_fixture(
            "manifest",
            [
                ("deletions-accounted", "0"),
                ("entries", "301/sha256:{}/settled/none".format("a" * 64)),
            ],
        ),
        "manifest frozen record without its watermark": make_fixture(
            "manifest", [("deletions-accounted", "1"), ("frozen", "307")]
        ),
        "manifest frozen naming one comment twice": make_fixture(
            "manifest", [("deletions-accounted", "1"), ("frozen", "307/1,307/1")]
        ),
        # Section 3.3 makes optionality a property of one family. Without this
        # case the optional set could be read as globally permitted keys and
        # every other family would silently accept them.
        "contribution carrying a manifest optional field": make_fixture(
            "contribution",
            [("phase", "dreamer"), ("turn", "1"), ("frozen", "307/1")],
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

    malformed_profile_bundle = {
        "authority_policy": {"profile": [], "reducer_principals": [999]},
        "ordered_events": [],
    }
    try:
        validate_integrity_bundle(malformed_profile_bundle)
    except ValidationError as error:
        assert "profile is not supported" in str(error)
        print("integrity fixture (nonscalar authority profile): rejected")
    else:
        raise AssertionError("a nonscalar authority profile was accepted")

    bare_cr_body = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    ).replace("turn: 1\n```", "turn: 1\r\r\n```").encode("utf-8")
    with tempfile.TemporaryDirectory() as fixture_dir:
        fixture_path = Path(fixture_dir) / "bare-cr-comment.md"
        fixture_path.write_bytes(bare_cr_body)
        path_result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(fixture_path)],
            capture_output=True,
            check=False,
        )
    assert path_result.returncode == 1
    assert b"bare carriage return" in path_result.stderr
    stdin_result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=bare_cr_body,
        capture_output=True,
        check=False,
    )
    assert stdin_result.returncode == 1
    assert b"bare carriage return" in stdin_result.stderr
    print("CLI fixture (bare carriage return via path and stdin): rejected")

    duplicate_body = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    )
    duplicate_bundle = {
        "authority_policy": {
            "profile": "open-table/ordered-claims",
            "reducer_principals": [999],
        },
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 1,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": duplicate_body,
            },
            {
                "actor_id": 101,
                "comment_id": 2,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": duplicate_body,
            },
        ]
    }
    notices = validate_integrity_bundle(duplicate_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (exact duplicate): accepted")

    edited_bundle = {
        "authority_policy": duplicate_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 1,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": "2026-08-01T00:00:01Z",
                "body": duplicate_body,
            },
        ],
    }
    assert validate_integrity_bundle(edited_bundle) == []
    print("integrity fixture (edited trusted comment): accepted; edit signal is not fatal")

    missing_update_bundle = json.loads(json.dumps(duplicate_bundle))
    del missing_update_bundle["ordered_events"][0]["updated_at"]
    try:
        validate_integrity_bundle(missing_update_bundle)
    except ValidationError as error:
        assert "must contain" in str(error) and "updated_at" in str(error)
        print("integrity fixture (missing trusted updated_at): rejected")
    else:
        raise AssertionError("an event without trusted updated_at was accepted")

    missing_edit_marker_bundle = json.loads(json.dumps(duplicate_bundle))
    del missing_edit_marker_bundle["ordered_events"][0]["last_edited_at"]
    try:
        validate_integrity_bundle(missing_edit_marker_bundle)
    except ValidationError as error:
        assert "must contain" in str(error) and "last_edited_at" in str(error)
        print("integrity fixture (missing trusted last_edited_at): rejected")
    else:
        raise AssertionError("an event without trusted last_edited_at was accepted")

    malformed_edit_marker_bundle = json.loads(json.dumps(duplicate_bundle))
    malformed_edit_marker_bundle["ordered_events"][0]["last_edited_at"] = "not-a-timestamp"
    try:
        validate_integrity_bundle(malformed_edit_marker_bundle)
    except ValidationError as error:
        assert "last_edited_at" in str(error) and "RFC 3339" in str(error)
        print("integrity fixture (malformed trusted last_edited_at): rejected")
    else:
        raise AssertionError("a malformed trusted last_edited_at was accepted")

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
        "claim", [("expires-at", "2026-08-01T12:00:00Z")]
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
        "authority_policy": {
            "profile": "open-table/ordered-claims",
            "reducer_principals": [999],
        },
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 3,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": source_body,
            },
            {
                "actor_id": 999,
                "comment_id": 4,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
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

    valid_ruling = make_fixture(
        "ruling",
        [
            ("target-actor-id", "101"),
            ("message-id", "fixture-claim-0001"),
            ("source-comment-id", "3"),
            ("source-digest", canonical_digest(source_body)),
            ("decision", "awarded"),
        ],
    )
    illegal_claim_decision_bundle = json.loads(json.dumps(mismatch_bundle))
    illegal_claim_decision_bundle["ordered_events"][1]["body"] = valid_ruling.replace(
        "decision: awarded", "decision: authorized"
    )
    try:
        validate_integrity_bundle(illegal_claim_decision_bundle)
    except ValidationError as error:
        assert "decision authorized is not legal for claim" in str(error)
        print("integrity fixture (illegal claim ruling decision): rejected")
    else:
        raise AssertionError("an authorized decision was accepted for a claim")

    deliberation_award_bundle = json.loads(json.dumps(mismatch_bundle))
    deliberation_award_bundle["authority_policy"]["profile"] = "deliberation-only"
    deliberation_award_bundle["ordered_events"][1]["body"] = valid_ruling
    try:
        validate_integrity_bundle(deliberation_award_bundle)
    except ValidationError as error:
        assert "decision awarded is not legal for claim" in str(error)
        print("integrity fixture (deliberation-only claim award): rejected")
    else:
        raise AssertionError("deliberation-only accepted an awarded claim ruling")

    invalidated_claim_bundle = json.loads(json.dumps(mismatch_bundle))
    invalidated_claim_bundle["ordered_events"][1]["body"] = valid_ruling.replace(
        "decision: awarded", "decision: invalidated"
    )
    assert validate_integrity_bundle(invalidated_claim_bundle) == []
    print("integrity fixture (sole invalidated ruling): accepted")

    contribution_ruling = make_fixture(
        "ruling",
        [
            ("target-actor-id", "101"),
            ("message-id", "fixture-contribution-0001"),
            ("source-comment-id", "1"),
            ("source-digest", canonical_digest(duplicate_body)),
            ("decision", "authorized"),
        ],
    )
    non_rulable_source_bundle = {
        "authority_policy": duplicate_bundle["authority_policy"],
        "ordered_events": [
            duplicate_bundle["ordered_events"][0],
            {
                "actor_id": 999,
                "comment_id": 2,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": contribution_ruling,
            },
        ],
    }
    try:
        validate_integrity_bundle(non_rulable_source_bundle)
    except ValidationError as error:
        assert "does not accept rulings" in str(error)
        print("integrity fixture (ruling for non-rulable source): rejected")
    else:
        raise AssertionError("a ruling for a contribution was accepted")

    late_duplicate_bundle = {
        "authority_policy": mismatch_bundle["authority_policy"],
        "ordered_events": [
            mismatch_bundle["ordered_events"][0],
            {
                "actor_id": 101,
                "comment_id": 4,
                "created_at": "2026-08-02T00:00:00Z",
                "updated_at": "2026-08-02T00:00:00Z",
                "last_edited_at": None,
                "body": source_body,
            },
            {
                "actor_id": 999,
                "comment_id": 5,
                "created_at": "2026-08-02T00:00:01Z",
                "updated_at": "2026-08-02T00:00:01Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
        ],
    }
    notices = validate_integrity_bundle(late_duplicate_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (late exact duplicate): ignored before timestamp checks")

    second_ruling = valid_ruling.replace(
        "id: fixture-ruling-0001", "id: fixture-ruling-0002"
    ).replace("decision: awarded", "decision: rejected")
    duplicate_ruling_bundle = {
        "authority_policy": {
            "profile": "open-table/ordered-claims",
            "reducer_principals": [999],
        },
        "ordered_events": [
            mismatch_bundle["ordered_events"][0],
            {
                "actor_id": 999,
                "comment_id": 4,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
            {
                "actor_id": 999,
                "comment_id": 5,
                "created_at": "2026-08-01T00:00:02Z",
                "updated_at": "2026-08-01T00:00:02Z",
                "last_edited_at": None,
                "body": second_ruling,
            },
        ],
    }
    try:
        validate_integrity_bundle(duplicate_ruling_bundle)
    except ValidationError as error:
        assert "duplicate ruling fixture-ruling-0002" in str(error)
        assert "source comment 3" in str(error)
        print("integrity fixture (duplicate ruling): rejected: {}".format(error))
    else:
        raise AssertionError("second ruling for one source was accepted")

    unauthorized_ruling = make_fixture(
        "ruling",
        [
            ("target-actor-id", "101"),
            ("message-id", "fixture-contribution-0001"),
            ("source-comment-id", "6"),
            ("source-digest", canonical_digest(duplicate_body)),
            ("decision", "authorized"),
        ],
    )
    unauthorized_bundle = {
        "authority_policy": {
            "profile": "open-table/ordered-claims",
            "reducer_principals": [999],
        },
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 6,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": duplicate_body,
            },
            {
                "actor_id": 888,
                "comment_id": 7,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": unauthorized_ruling,
            },
        ],
    }
    notices = validate_integrity_bundle(unauthorized_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; treated as prose"
    ]
    print("integrity fixture (unauthorized ruling author): excluded as prose")

    empty_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [],
    }
    assert validate_integrity_bundle(empty_bundle) == []
    print("integrity fixture (empty event stream): accepted")

    duplicate_json_members = {
        "top-level": (
            '{"authority_policy":{},"authority_policy":{},"ordered_events":[]}'
        ),
        "authority-policy": (
            '{"authority_policy":{"profile":"deliberation-only",'
            '"profile":"deliberation-only","reducer_principals":[999]},'
            '"ordered_events":[]}'
        ),
        "event": (
            '{"authority_policy":{"profile":"deliberation-only",'
            '"reducer_principals":[999]},"ordered_events":['
            '{"actor_id":1,"actor_id":2}]}'
        ),
    }
    for level, raw_bundle in duplicate_json_members.items():
        try:
            parse_integrity_bundle_json(raw_bundle)
        except ValidationError as error:
            assert "duplicate JSON object member" in str(error)
        else:
            raise AssertionError(
                "duplicate JSON member at {} level was accepted".format(level)
            )
    print("integrity fixture (duplicate JSON object members): rejected")

    oversized_bundle_values = {}
    oversized_principal_bundle = json.loads(json.dumps(empty_bundle))
    oversized_principal_bundle["authority_policy"]["reducer_principals"] = [
        MAX_PROTOCOL_INTEGER + 1
    ]
    oversized_bundle_values["reducer principal"] = oversized_principal_bundle
    oversized_actor_bundle = json.loads(json.dumps(duplicate_bundle))
    oversized_actor_bundle["ordered_events"][0]["actor_id"] = (
        MAX_PROTOCOL_INTEGER + 1
    )
    oversized_bundle_values["event actor"] = oversized_actor_bundle
    oversized_comment_bundle = json.loads(json.dumps(duplicate_bundle))
    oversized_comment_bundle["ordered_events"][0]["comment_id"] = (
        MAX_PROTOCOL_INTEGER + 1
    )
    oversized_bundle_values["event comment"] = oversized_comment_bundle
    for label, fixture in oversized_bundle_values.items():
        try:
            validate_integrity_bundle(fixture)
        except ValidationError as error:
            assert "at most 20 digits" in str(error)
            print("integrity fixture (oversized {} id): rejected".format(label))
        else:
            raise AssertionError("oversized {} id was accepted".format(label))

    invalid_claim = (
        "```open-table\nopen-table: 0\nmessage: claim\n"
        "id: invalid-claim-0001\n```\n\nMissing expiry."
    )
    public_input_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 8,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": "Ordinary public prose.",
            },
            {
                "actor_id": 101,
                "comment_id": 9,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": invalid_claim,
            },
        ],
    }
    notices = validate_integrity_bundle(public_input_bundle)
    assert notices[0].startswith("excluded non-protocol comment 8")
    assert notices[1].startswith("excluded invalid open-table comment 9")
    print("integrity fixture (ordinary and malformed public input): excluded")

    invalid_lease_body = make_fixture(
        "claim",
        [("expires-at", "2026-08-20T00:00:00Z")],
    )
    invalid_lease_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 8,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": invalid_lease_body,
            }
        ],
    }
    notices = validate_integrity_bundle(invalid_lease_bundle)
    assert len(notices) == 1 and "seven days later" in notices[0]
    print("integrity fixture (invalid public lease interval): excluded")

    malformed_unauthorized_ruling = unauthorized_ruling.replace(
        "source-digest: {}\n".format(canonical_digest(duplicate_body)), ""
    )
    malformed_unauthorized_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            unauthorized_bundle["ordered_events"][0],
            {
                "actor_id": 888,
                "comment_id": 7,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": malformed_unauthorized_ruling,
            },
        ],
    }
    notices = validate_integrity_bundle(malformed_unauthorized_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; "
        "treated as prose"
    ]
    print("integrity fixture (malformed unauthorized ruling): excluded as prose")

    truncated_ruling = unauthorized_ruling.rsplit("```", 1)[0]
    truncated_unauthorized_bundle = json.loads(
        json.dumps(malformed_unauthorized_bundle)
    )
    truncated_unauthorized_bundle["ordered_events"][1]["body"] = truncated_ruling
    notices = validate_integrity_bundle(truncated_unauthorized_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; "
        "treated as prose"
    ]
    print("integrity fixture (truncated unauthorized ruling): excluded as prose")

    truncated_authenticated_bundle = json.loads(
        json.dumps(truncated_unauthorized_bundle)
    )
    truncated_authenticated_bundle["ordered_events"][1]["actor_id"] = 999
    try:
        validate_integrity_bundle(truncated_authenticated_bundle)
    except ValidationError as error:
        assert "invalid authenticated ruling" in str(error)
        print(
            "integrity fixture (truncated authenticated ruling): rejected: {}".format(
                error
            )
        )
    else:
        raise AssertionError("truncated authenticated ruling did not fail closed")

    malformed_discriminator_bundle = json.loads(
        json.dumps(truncated_authenticated_bundle)
    )
    malformed_discriminator_bundle["ordered_events"][1]["body"] = (
        unauthorized_ruling.replace("message: ruling\n", "message: ruling \n")
    )
    try:
        validate_integrity_bundle(malformed_discriminator_bundle)
    except ValidationError as error:
        assert "invalid authenticated ruling" in str(error)
        print(
            "integrity fixture (malformed authenticated discriminator): "
            "rejected: {}".format(error)
        )
    else:
        raise AssertionError("malformed authenticated discriminator did not fail closed")

    for malformed_message_line in (
        "message:ruling\n",
        "message=ruling\n",
        "message.ruling\n",
        "message_ruling\n",
    ):
        malformed_delimiter_bundle = json.loads(
            json.dumps(truncated_authenticated_bundle)
        )
        malformed_delimiter_bundle["ordered_events"][1]["body"] = (
            duplicate_body.replace("message: contribution\n", malformed_message_line)
        )
        try:
            validate_integrity_bundle(malformed_delimiter_bundle)
        except ValidationError as error:
            assert "invalid authenticated ruling" in str(error)
        else:
            raise AssertionError(
                "malformed authenticated delimiter did not fail closed: {}".format(
                    malformed_message_line.rstrip()
                )
            )
    print("integrity fixture (malformed authenticated delimiters): rejected")

    missing_discriminator_bundle = json.loads(json.dumps(malformed_discriminator_bundle))
    missing_discriminator_bundle["ordered_events"][1]["body"] = (
        unauthorized_ruling.replace("message: ruling\n", "")
    )
    try:
        validate_integrity_bundle(missing_discriminator_bundle)
    except ValidationError as error:
        assert "invalid authenticated ruling" in str(error)
        print(
            "integrity fixture (missing authenticated discriminator): rejected: {}".format(
                error
            )
        )
    else:
        raise AssertionError("missing authenticated discriminator did not fail closed")

    four_space_authenticated_bundle = json.loads(json.dumps(unauthorized_bundle))
    four_space_authenticated_bundle["ordered_events"][1]["actor_id"] = 999
    four_space_authenticated_bundle["ordered_events"][1]["body"] = (
        unauthorized_ruling.replace("```open-table\n", "    ```open-table\n", 1)
    )
    try:
        validate_integrity_bundle(four_space_authenticated_bundle)
    except ValidationError as error:
        assert "invalid authenticated open-table" in str(error)
        assert "fenced block" in str(error)
        print(
            "integrity fixture (four-space authenticated opening): rejected: "
            "{}".format(error)
        )
    else:
        raise AssertionError("four-space authenticated output did not fail closed")

    reused_forged_id = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1")]
    ).replace("fixture-contribution-0001", "fixture-ruling-0001")
    forged_id_conflict_bundle = json.loads(json.dumps(malformed_unauthorized_bundle))
    forged_id_conflict_bundle["ordered_events"].append(
        {
            "actor_id": 888,
            "comment_id": 8,
            "created_at": "2026-08-01T00:00:02Z",
            "updated_at": "2026-08-01T00:00:02Z",
            "last_edited_at": None,
            "body": reused_forged_id,
        }
    )
    notices = validate_integrity_bundle(forged_id_conflict_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; "
        "treated as prose"
    ]
    print("integrity fixture (malformed unauthorized id reuse): accepted")

    valid_forged_id_conflict_bundle = json.loads(json.dumps(unauthorized_bundle))
    valid_forged_id_conflict_bundle["ordered_events"].append(
        {
            "actor_id": 888,
            "comment_id": 8,
            "created_at": "2026-08-01T00:00:02Z",
            "updated_at": "2026-08-01T00:00:02Z",
            "last_edited_at": None,
            "body": reused_forged_id,
        }
    )
    notices = validate_integrity_bundle(valid_forged_id_conflict_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; "
        "treated as prose"
    ]
    print("integrity fixture (valid unauthorized id reuse): accepted")

    expiration_body = make_fixture(
        "expiration",
        [("claim-comment-id", "51"), ("expired-at", "2026-08-01T12:00:00Z")],
    )
    unauthorized_expiration_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 888,
                "comment_id": 10,
                "created_at": "2026-08-01T13:00:00Z",
                "updated_at": "2026-08-01T13:00:00Z",
                "last_edited_at": None,
                "body": expiration_body,
            }
        ],
    }
    notices = validate_integrity_bundle(unauthorized_expiration_bundle)
    assert notices == [
        "excluded expiration-shaped comment 10 from unauthorized actor 888; treated as prose"
    ]
    print("integrity fixture (unauthorized expiration): excluded as prose")

    surrogate_public_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 13,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": "Ordinary prose with a lone surrogate: \ud800",
            }
        ],
    }
    notices = validate_integrity_bundle(surrogate_public_bundle)
    assert len(notices) == 1 and "not valid UTF-8 scalar text" in notices[0]
    print("integrity fixture (lone-surrogate public text): excluded")

    surrogate_expiration_bundle = json.loads(
        json.dumps(unauthorized_expiration_bundle)
    )
    surrogate_expiration_bundle["ordered_events"][0]["actor_id"] = 999
    surrogate_expiration_bundle["ordered_events"][0]["body"] += "\ud800"
    try:
        validate_integrity_bundle(surrogate_expiration_bundle)
    except ValidationError as error:
        assert "invalid authenticated expiration" in str(error)
        print(
            "integrity fixture (lone-surrogate authenticated output): rejected: "
            "{}".format(error)
        )
    else:
        raise AssertionError("invalid authenticated UTF-8 scalar text was accepted")

    duplicate_source_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            mismatch_bundle["ordered_events"][0],
            {
                "actor_id": 101,
                "comment_id": 4,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": source_body,
            },
            {
                "actor_id": 999,
                "comment_id": 5,
                "created_at": "2026-08-01T00:00:02Z",
                "updated_at": "2026-08-01T00:00:02Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
        ],
    }
    notices = validate_integrity_bundle(duplicate_source_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (duplicate ruled source): ignored")

    duplicate_ruling_retry_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            mismatch_bundle["ordered_events"][0],
            {
                "actor_id": 999,
                "comment_id": 4,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
            {
                "actor_id": 999,
                "comment_id": 5,
                "created_at": "2026-08-01T00:00:02Z",
                "updated_at": "2026-08-01T00:00:02Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
        ],
    }
    notices = validate_integrity_bundle(duplicate_ruling_retry_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (duplicate ruling retry): ignored")

    preemptive_ruling_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 999,
                "comment_id": 2,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": valid_ruling,
            },
            {
                "actor_id": 101,
                "comment_id": 3,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": source_body,
            },
        ],
    }
    try:
        validate_integrity_bundle(preemptive_ruling_bundle)
    except ValidationError as error:
        assert "appended after" in str(error)
        print("integrity fixture (preemptive ruling): rejected: {}".format(error))
    else:
        raise AssertionError("a ruling before its source was accepted")

    early_expiration_bundle = json.loads(json.dumps(unauthorized_expiration_bundle))
    early_expiration_bundle["ordered_events"][0]["actor_id"] = 999
    early_expiration_bundle["ordered_events"][0]["created_at"] = (
        "2026-08-01T11:59:59Z"
    )
    early_expiration_bundle["ordered_events"][0]["updated_at"] = (
        "2026-08-01T11:59:59Z"
    )
    try:
        validate_integrity_bundle(early_expiration_bundle)
    except ValidationError as error:
        assert "at or after expired-at" in str(error)
        print("integrity fixture (early expiration): rejected: {}".format(error))
    else:
        raise AssertionError("an expiration before expired-at was accepted")

    unicode_integer = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "١")]
    )
    try:
        parse_comment(unicode_integer)
    except ValidationError as error:
        assert "base-10 integer" in str(error)
        print("integrity fixture (non-ASCII integer): rejected: {}".format(error))
    else:
        raise AssertionError("a non-ASCII integer was accepted")

    overlong_integer = make_fixture(
        "contribution", [("phase", "dreamer"), ("turn", "1" * 5000)]
    )
    try:
        parse_comment(overlong_integer)
    except ValidationError as error:
        assert "base-10 integer" in str(error)
        print("integrity fixture (overlong integer): rejected: {}".format(error))
    else:
        raise AssertionError("an overlong integer was accepted")

    for invalid_comment_reference in ("0", "١", "1" * 21):
        invalid_reference_message = make_fixture(
            "release", [("claim-comment-id", invalid_comment_reference)]
        )
        try:
            parse_comment(invalid_reference_message)
        except ValidationError as error:
            assert "positive numeric GitHub id" in str(error)
        else:
            raise AssertionError("an invalid GitHub comment reference was accepted")
    print("integrity fixture (invalid GitHub comment references): rejected")

    for oversized_artefact in (
        "github:{}:pull:45:head:{}".format("1" * 21, "a" * 40),
        "github:123:pull:{}:head:{}".format("1" * 21, "a" * 40),
    ):
        oversized_artefact_message = make_fixture(
            "result",
            [
                ("claim-comment-id", "51"),
                ("outcome", "completed"),
                ("artefact", oversized_artefact),
            ],
        )
        try:
            parse_comment(oversized_artefact_message)
        except ValidationError as error:
            assert "immutable GitHub or generic reference" in str(error)
        else:
            raise AssertionError("an oversized GitHub artefact id was accepted")
    print("integrity fixture (oversized GitHub artefact ids): rejected")

    impossible_timestamp = make_fixture(
        "expiration",
        [("claim-comment-id", "51"), ("expired-at", "2026-02-31T12:00:00Z")],
    )
    try:
        parse_comment(impossible_timestamp)
    except ValidationError as error:
        assert "not a real UTC date" in str(error)
        print("integrity fixture (impossible timestamp): rejected: {}".format(error))
    else:
        raise AssertionError("an impossible timestamp was accepted")

    corrected_invalid_claim = invalid_claim.replace(
        "id: invalid-claim-0001\n",
        "id: invalid-claim-0001\nexpires-at: 2026-08-02T00:00:00Z\n",
    )
    reserved_id_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 11,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": invalid_claim,
            },
            {
                "actor_id": 101,
                "comment_id": 12,
                "created_at": "2026-08-01T00:00:01Z",
                "updated_at": "2026-08-01T00:00:01Z",
                "last_edited_at": None,
                "body": corrected_invalid_claim,
            },
        ],
    }
    try:
        validate_integrity_bundle(reserved_id_bundle)
    except ValidationError as error:
        assert "conflict:" in str(error)
        print("integrity fixture (invalid earliest id reservation): {}".format(error))
    else:
        raise AssertionError("an invalid earliest occurrence did not reserve its id")

    repeated_id_invalid_claim = invalid_claim.replace(
        "id: invalid-claim-0001\n",
        "id: invalid-claim-0001\nid: invalid-claim-0001\n",
    )
    repeated_id_bundle = json.loads(json.dumps(reserved_id_bundle))
    repeated_id_bundle["ordered_events"][0]["body"] = repeated_id_invalid_claim
    try:
        validate_integrity_bundle(repeated_id_bundle)
    except ValidationError as error:
        assert "conflict:" in str(error)
        print(
            "integrity fixture (repeated unambiguous invalid id): {}".format(error)
        )
    else:
        raise AssertionError("a repeated unambiguous invalid id was not reserved")

    ambiguous_id_claim = invalid_claim.replace(
        "id: invalid-claim-0001\n",
        "id: invalid-claim-0001\nid: other-invalid-0002\n",
    )
    ambiguous_id_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [
            {
                "actor_id": 101,
                "comment_id": 13,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
                "last_edited_at": None,
                "body": ambiguous_id_claim,
            }
        ],
    }
    notices = validate_integrity_bundle(ambiguous_id_bundle)
    assert len(notices) == 1 and "no unambiguous message id reserved" in notices[0]
    print("integrity fixture (ambiguous invalid ids): no id reserved")

    ambiguous_surrogate_bundle = json.loads(json.dumps(ambiguous_id_bundle))
    ambiguous_surrogate_bundle["ordered_events"][0]["body"] += "\ud800"
    notices = validate_integrity_bundle(ambiguous_surrogate_bundle)
    assert len(notices) == 1 and "no unambiguous message id reserved" in notices[0]
    print("integrity fixture (ambiguous surrogate ids): no id reserved")

    observed = run_integrity_fixture_test()
    run_reason_fixture_test(observed)
    run_core_import_contract_test()
    run_external_cli_fixture_test()

    # The first two counts are read from the tables themselves: a hand-kept copy
    # of a list the code already has goes stale silently, and both of these did.
    # The third has no collection to measure -- its cases are separate calls --
    # so it stays a hand-maintained number and is marked as one.
    print(
        "self-test: {} valid families, {} malformed fixtures, and 55 integrity "
        "rules passed".format(len(valid), len(malformed))
    )


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
            bundle = parse_integrity_bundle_json(
                Path(args.integrity_bundle).read_text(encoding="utf-8")
            )
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
        raw_body = Path(args.path).read_bytes() if args.path else sys.stdin.buffer.read()
        body = raw_body.decode("utf-8")
    except OSError as error:
        print("error: cannot read comment: {}".format(error), file=sys.stderr)
        return 2
    except UnicodeDecodeError as error:
        print("invalid: comment is not valid UTF-8: {}".format(error), file=sys.stderr)
        return 1

    try:
        header, _ = parse_comment(body)
    except ValidationError as error:
        print("invalid: {}".format(error), file=sys.stderr)
        return 1

    print("valid: Open Table v0 {} message".format(header["message"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
