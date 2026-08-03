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
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
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
POSITIVE_ASCII_INTEGER_RE = re.compile(r"^[1-9][0-9]{0,19}$")
MAX_PROTOCOL_INTEGER = 10 ** 20 - 1
TIMESTAMP_RE = re.compile(
    r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-"
    r"(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GITHUB_ARTEFACT_RE = re.compile(
    r"^github:[1-9][0-9]{0,19}:pull:[1-9][0-9]{0,19}:head:"
    r"(?:[0-9a-f]{40}|[0-9a-f]{64})$"
)
GENERIC_ARTEFACT_RE = re.compile(
    r"^(?P<uri>[^#]+)#sha256=[0-9a-f]{64}$"
)
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
URI_PATH_RE = re.compile(
    r"^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2}|[!$&'()*+,;=]|[:@/])*$"
)
URI_QUERY_RE = re.compile(
    r"^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2}|[!$&'()*+,;=]|[:@/?])*$"
)
URI_USERINFO_RE = re.compile(
    r"^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2}|[!$&'()*+,;=]|:)*$"
)
URI_REG_NAME_RE = re.compile(
    r"^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2}|[!$&'()*+,;=])*$"
)
URI_IPVFUTURE_RE = re.compile(
    r"^[vV][0-9A-Fa-f]+\.(?:[A-Za-z0-9._~-]|[!$&'()*+,;=]|:)+$"
)
UNSUPPORTED_LINE_SEPARATOR_RE = re.compile(r"[\v\f\x1c-\x1e\x85\u2028\u2029]")
OPENING_RE = re.compile(
    r"\A(?:[ \t]*\r?\n)* {0,3}```open-table[ \t]*\r?\n"
)
OPEN_TABLE_CANDIDATE_RE = re.compile(
    r"\A\s*```open-table(?=[ \t\r\n]|\Z)"
)
CLOSING_RE = re.compile(r"^ {0,3}```[ \t]*(?:\r\n|\n)", re.MULTILINE)
BLOCK_OPENING_RE = re.compile(
    r"^ {0,3}```open-table[ \t]*(?:\r\n|\n)", re.MULTILINE
)
REDUCER_OUTPUT_MESSAGES = {"ruling", "expiration"}
REDUCER_OUTPUT_MARKERS = {
    "ruling": {
        "target-actor-id", "message-id", "source-comment-id", "source-digest",
        "decision"
    },
    "expiration": {"expired-at"},
}
RULING_REQUIRED_MESSAGES = {
    "configuration", "settled", "claim", "renewal", "release", "handoff",
    "cancellation", "result", "review-request", "verdict"
}


class ValidationError(ValueError):
    """A readable structural validation failure."""


def canonical_digest(body):
    """Return the canonical digest of one complete GitHub comment body."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def is_positive_ascii_integer(value):
    """Return whether value is the protocol's canonical positive integer text."""
    return bool(POSITIVE_ASCII_INTEGER_RE.fullmatch(value))


def is_positive_protocol_integer(value):
    """Return whether a decoded JSON value fits the protocol integer range."""
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 1 <= value <= MAX_PROTOCOL_INTEGER
    )


def is_valid_uri_authority(authority):
    """Return whether an RFC 3986 authority uses supported canonical syntax."""
    host_port = authority
    if "@" in authority:
        userinfo, host_port = authority.rsplit("@", 1)
        if not URI_USERINFO_RE.fullmatch(userinfo):
            return False

    if host_port.startswith("["):
        close = host_port.find("]")
        if close < 0:
            return False
        literal = host_port[1:close]
        suffix = host_port[close + 1:]
        if not URI_IPVFUTURE_RE.fullmatch(literal):
            if "%" in literal:
                return False
            try:
                if ipaddress.ip_address(literal).version != 6:
                    return False
            except ValueError:
                return False
        if suffix:
            if not suffix.startswith(":"):
                return False
            if suffix[1:] and not re.fullmatch(r"[0-9]+", suffix[1:]):
                return False
        return True

    if host_port.count(":") > 1:
        return False
    host, separator, port = host_port.rpartition(":")
    if not separator:
        host = host_port
    elif port and not re.fullmatch(r"[0-9]+", port):
        return False
    return bool(URI_REG_NAME_RE.fullmatch(host))


def is_generic_artefact(value):
    """Validate a generic immutable artefact as an absolute RFC 3986 URI."""
    match = GENERIC_ARTEFACT_RE.fullmatch(value)
    if match is None:
        return False
    uri = match.group("uri")
    if any(ord(character) < 0x21 or ord(character) > 0x7e for character in uri):
        return False
    scheme, separator, remainder = uri.partition(":")
    if not separator or not URI_SCHEME_RE.fullmatch(scheme):
        return False
    has_authority = remainder.startswith("//")
    if has_authority:
        authority_and_suffix = remainder[2:]
        boundaries = [
            position
            for delimiter in ("/", "?")
            if (position := authority_and_suffix.find(delimiter)) >= 0
        ]
        boundary = min(boundaries) if boundaries else len(authority_and_suffix)
        authority = authority_and_suffix[:boundary]
        suffix = authority_and_suffix[boundary:]
        if not is_valid_uri_authority(authority):
            return False
        if suffix and not suffix.startswith(("/", "?")):
            return False
    else:
        suffix = remainder
    path, query_separator, query = suffix.partition("?")
    return bool(
        URI_PATH_RE.fullmatch(path)
        and (not query_separator or URI_QUERY_RE.fullmatch(query))
    )


def peek_header_values(body, key):
    """Read exact key lines from a leading block without accepting the envelope."""
    prefix = key + ": "
    return [
        line[len(prefix):]
        for line in peek_header_lines(body)
        if line.startswith(prefix)
    ]


def peek_header_lines(body):
    """Read raw lines from a leading block without accepting the envelope."""
    opening = OPENING_RE.match(body)
    if not opening:
        return []
    closing = CLOSING_RE.search(body, opening.end())
    header_end = closing.start() if closing else len(body)
    return split_physical_lines(body[opening.end():header_end])


def split_physical_lines(text):
    """Split LF/CRLF source lines without treating Unicode separators as lines."""
    ends_with_lf = text.endswith("\n")
    lines = text.split("\n")
    if ends_with_lf:
        lines.pop()
    return [
        line[:-1]
        if line.endswith("\r") and (number < len(lines) - 1 or ends_with_lf)
        else line
        for number, line in enumerate(lines)
    ]


def identify_reducer_output_shapes(body):
    """Identify reserved reducer output even when its discriminator is malformed."""
    shapes = set()
    for line in peek_header_lines(body):
        normalized = re.sub(r"[^A-Za-z0-9]", "", line).lower()
        for message in REDUCER_OUTPUT_MESSAGES:
            if normalized == "message" + message:
                shapes.add(message)
        for message, markers in REDUCER_OUTPUT_MARKERS.items():
            for marker in markers:
                normalized_marker = marker.replace("-", "")
                if (
                    normalized.startswith(normalized_marker)
                    and len(normalized) > len(normalized_marker)
                ):
                    shapes.add(message)
    return shapes


def recover_message_id(body):
    """Return one unambiguous valid id value from a malformed leading block."""
    candidates = {
        value for value in peek_header_values(body, "id") if ID_RE.fullmatch(value)
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def id_reservation_notice(candidate_id):
    """Describe whether malformed input reserved one recoverable message id."""
    return (
        "; recoverable message id reserved"
        if candidate_id is not None
        else "; no unambiguous message id reserved"
    )


def unauthorized_reducer_output_notice(shapes, comment_id, actor_id):
    """Describe reducer-shaped prose excluded before protocol processing."""
    return (
        "excluded {}-shaped comment {} from unauthorized actor {}; "
        "treated as prose".format(sorted(shapes)[0], comment_id, actor_id)
    )


def parse_utc_timestamp(value, field):
    """Parse one already shape-checked protocol timestamp."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValidationError(
            "{} is not a real UTC date and time".format(field)
        ) from error


def validate_event_local(header, created_at):
    """Validate constraints that need only one trusted comment event."""
    message = header["message"]
    created = parse_utc_timestamp(created_at, "created_at")
    if message in {"claim", "renewal", "handoff"}:
        expires = parse_utc_timestamp(header["expires-at"], "expires-at")
        if expires <= created or expires - created > datetime.timedelta(days=7):
            raise ValidationError(
                "{} expires-at must be later than created_at and no more than "
                "seven days later".format(message)
            )
    if message == "expiration":
        expired = parse_utc_timestamp(header["expired-at"], "expired-at")
        if created < expired:
            raise ValidationError(
                "expiration trusted created_at must be at or after expired-at"
            )


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
    if UNSUPPORTED_LINE_SEPARATOR_RE.search(header_text):
        raise ValidationError("header contains an unsupported Unicode line separator")
    lines = split_physical_lines(header_text)
    if any("\r" in line for line in lines):
        raise ValidationError("header contains a bare carriage return")
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
        if not is_positive_ascii_integer(header["turn"]):
            raise ValidationError("turn must be a base-10 integer of at least 1")

    for field in ("sequence", "turn-limit"):
        if field in header:
            if not is_positive_ascii_integer(header[field]):
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
            parse_utc_timestamp(timestamp, field)

    for field in ("target-actor-id", "to-actor-id", "source-comment-id"):
        if field in header:
            if not is_positive_ascii_integer(header[field]):
                raise ValidationError(
                    "{} must be a positive numeric GitHub id".format(field)
                )

    if "message-id" in header and not ID_RE.fullmatch(header["message-id"]):
        raise ValidationError("message-id does not match the Open Table token syntax")

    if "expected-actors" in header:
        actors = header["expected-actors"].split(",")
        if (
            any(not is_positive_ascii_integer(actor) for actor in actors)
            or len(actors) != len(set(actors))
        ):
            raise ValidationError(
                "expected-actors must be unique numeric GitHub ids separated by commas"
            )

    if "source-digest" in header and not DIGEST_RE.fullmatch(header["source-digest"]):
        raise ValidationError("source-digest must be a canonical sha256 digest")

    if "artefact" in header and not (
        GITHUB_ARTEFACT_RE.fullmatch(header["artefact"])
        or is_generic_artefact(header["artefact"])
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
    required_bundle_fields = {"authority_policy", "ordered_events"}
    if not isinstance(bundle, dict) or set(bundle) != required_bundle_fields:
        raise ValidationError(
            "integrity bundle must contain only authority_policy and ordered_events"
        )
    authority_policy = bundle["authority_policy"]
    if not isinstance(authority_policy, dict) or set(authority_policy) != {
        "profile", "reducer_principals"
    }:
        raise ValidationError(
            "authority_policy must contain only profile and reducer_principals"
        )
    authority_profile = authority_policy["profile"]
    if not isinstance(authority_profile, str) or authority_profile not in {
        "deliberation-only", "open-table/ordered-claims", "steve/kanban"
    }:
        raise ValidationError("authority_policy profile is not supported")
    reducer_principals = authority_policy["reducer_principals"]
    if (
        not isinstance(reducer_principals, list)
        or not reducer_principals
        or any(
            not is_positive_protocol_integer(principal)
            for principal in reducer_principals
        )
        or len(reducer_principals) != len(set(reducer_principals))
    ):
        raise ValidationError(
            "authority_policy reducer_principals must be unique positive numeric "
            "GitHub actor ids of at most 20 digits"
        )
    allowed_reducer_principals = set(reducer_principals)
    events = bundle["ordered_events"]
    if not isinstance(events, list):
        raise ValidationError("ordered_events must be a list")

    parsed = []
    by_comment_id = {}
    seen_comment_ids = set()
    seen_messages = {}
    notices = []
    previous_order = None

    for index, event in enumerate(events, 1):
        required = {
            "actor_id", "comment_id", "created_at", "updated_at",
            "last_edited_at", "created_body_digest", "body"
        }
        if not isinstance(event, dict) or set(event) != required:
            raise ValidationError(
                "event {} must contain actor_id, comment_id, created_at, updated_at, "
                "last_edited_at, created_body_digest, and body".format(index)
            )
        actor_id = event["actor_id"]
        comment_id = event["comment_id"]
        created_at = event["created_at"]
        updated_at = event["updated_at"]
        last_edited_at = event["last_edited_at"]
        created_body_digest = event["created_body_digest"]
        body = event["body"]
        if not is_positive_protocol_integer(actor_id):
            raise ValidationError(
                "event {} actor_id must be a positive integer of at most 20 "
                "digits".format(index)
            )
        if not is_positive_protocol_integer(comment_id):
            raise ValidationError(
                "event {} comment_id must be a positive integer of at most 20 "
                "digits".format(index)
            )
        if comment_id in seen_comment_ids:
            raise ValidationError("duplicate trusted comment id: {}".format(comment_id))
        seen_comment_ids.add(comment_id)
        for timestamp_field, timestamp_value in (
            ("created_at", created_at),
            ("updated_at", updated_at),
        ):
            if (
                not isinstance(timestamp_value, str)
                or not TIMESTAMP_RE.fullmatch(timestamp_value)
            ):
                raise ValidationError(
                    "event {} {} must use the exact RFC 3339 UTC form".format(
                        index, timestamp_field
                    )
                )
            try:
                datetime.datetime.strptime(timestamp_value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as error:
                raise ValidationError(
                    "event {} {} is not a real UTC date and time".format(
                        index, timestamp_field
                    )
                ) from error
        if updated_at != created_at:
            raise ValidationError(
                "trusted comment {} was edited: updated_at differs from created_at; "
                "fail closed".format(comment_id)
            )
        if last_edited_at is not None:
            raise ValidationError(
                "trusted comment {} was edited: GitHub last_edited_at is non-null; "
                "fail closed".format(comment_id)
            )
        if (
            not isinstance(created_body_digest, str)
            or not DIGEST_RE.fullmatch(created_body_digest)
        ):
            raise ValidationError(
                "event {} created_body_digest must be a canonical sha256 digest".format(
                    index
                )
            )
        if not isinstance(body, str):
            raise ValidationError("event {} body must be a string".format(index))

        order = (created_at, comment_id)
        if previous_order is not None and order < previous_order:
            raise ValidationError("ordered_events are not in trusted GitHub order")
        previous_order = order

        reducer_output_shapes = identify_reducer_output_shapes(body)
        authenticated_open_table_candidate = (
            actor_id in allowed_reducer_principals
            and bool(OPEN_TABLE_CANDIDATE_RE.match(body))
        )
        unauthorized_reducer_shape = (
            bool(reducer_output_shapes)
            and actor_id not in allowed_reducer_principals
        )

        try:
            digest = canonical_digest(body)
        except UnicodeEncodeError as error:
            if authenticated_open_table_candidate:
                output_shape = (
                    sorted(reducer_output_shapes)[0]
                    if reducer_output_shapes
                    else "open-table"
                )
                raise ValidationError(
                    "invalid authenticated {} comment {}: body is not valid UTF-8 "
                    "scalar text".format(
                        output_shape, comment_id
                    )
                ) from error
            if unauthorized_reducer_shape:
                notices.append(
                    unauthorized_reducer_output_notice(
                        reducer_output_shapes, comment_id, actor_id
                    )
                )
                continue
            candidate_id = recover_message_id(body)
            if candidate_id is not None:
                key = (actor_id, candidate_id)
                if key in seen_messages:
                    raise ValidationError(
                        "conflict: actor {} message id {} cannot be canonically "
                        "digested".format(actor_id, candidate_id)
                    )
                seen_messages[key] = None
            notices.append(
                "excluded comment {} whose body is not valid UTF-8 scalar text{}".format(
                    comment_id, id_reservation_notice(candidate_id)
                )
            )
            continue

        if digest != created_body_digest:
            raise ValidationError(
                "trusted comment {} body differs from its authenticated creation "
                "receipt digest; edited source material fails closed".format(comment_id)
            )

        try:
            header, _ = parse_comment(body)
        except ValidationError as error:
            if authenticated_open_table_candidate:
                output_shape = (
                    sorted(reducer_output_shapes)[0]
                    if reducer_output_shapes
                    else "open-table"
                )
                raise ValidationError(
                    "invalid authenticated {} comment {}: {}".format(
                        output_shape, comment_id, error
                    )
                ) from error
            if unauthorized_reducer_shape:
                notices.append(
                    unauthorized_reducer_output_notice(
                        reducer_output_shapes, comment_id, actor_id
                    )
                )
                continue
            candidate_id = recover_message_id(body)
            if candidate_id is not None:
                key = (actor_id, candidate_id)
                if key in seen_messages and seen_messages[key] != digest:
                    raise ValidationError(
                        "conflict: actor {} message id {} has a different digest; "
                        "it is not a duplicate".format(actor_id, candidate_id)
                    )
                # Section 7.2 deliberately reserves a syntactically recoverable
                # actor/id key even when the earliest envelope is invalid.
                seen_messages.setdefault(key, digest)
            if OPENING_RE.match(body):
                notices.append(
                    "excluded invalid open-table comment {}: {}{}".format(
                        comment_id, error, id_reservation_notice(candidate_id)
                    )
                )
            else:
                notices.append(
                    "excluded non-protocol comment {}; treated as prose".format(
                        comment_id
                    )
                )
            continue

        if unauthorized_reducer_shape:
            notices.append(
                unauthorized_reducer_output_notice(
                    reducer_output_shapes, comment_id, actor_id
                )
            )
            continue

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
            continue
        else:
            seen_messages[key] = digest

        try:
            validate_event_local(header, created_at)
        except ValidationError as error:
            if authenticated_open_table_candidate:
                output_shape = (
                    sorted(reducer_output_shapes)[0]
                    if reducer_output_shapes
                    else "open-table"
                )
                raise ValidationError(
                    "invalid authenticated {} comment {}: {}".format(
                        output_shape, comment_id, error
                    )
                ) from error
            notices.append(
                "excluded invalid open-table comment {}: {}{}".format(
                    comment_id, error, id_reservation_notice(header["id"])
                )
            )
            continue

        record = {
            "actor_id": actor_id,
            "comment_id": comment_id,
            "created_at": created_at,
            "header": header,
            "digest": digest,
            "order": order,
        }
        parsed.append(record)
        by_comment_id[comment_id] = record

    ruled_sources = {}
    for record in parsed:
        header = record["header"]
        if header["message"] != "ruling":
            continue
        source_comment_id = int(header["source-comment-id"])
        if source_comment_id in ruled_sources:
            raise ValidationError(
                "duplicate ruling {} for source comment {}; first ruling was {}".format(
                    header["id"], source_comment_id,
                    ruled_sources[source_comment_id]["header"]["id"]
                )
            )
        source = by_comment_id.get(source_comment_id)
        if source is None:
            raise ValidationError(
                "ruling source comment {} is deleted or missing; fail closed".format(
                    source_comment_id
                )
            )
        if source["order"] >= record["order"]:
            raise ValidationError("ruling must be appended after its bound source")
        if source["actor_id"] != int(header["target-actor-id"]):
            raise ValidationError("ruling target actor does not match trusted source actor")
        if source["header"]["id"] != header["message-id"]:
            raise ValidationError("ruling message id does not match its bound source")
        if source["digest"] != header["source-digest"]:
            raise ValidationError(
                "ruling source digest mismatch; source was edited or binding is invalid; "
                "fail closed"
            )
        source_message = source["header"]["message"]
        if source_message not in RULING_REQUIRED_MESSAGES:
            raise ValidationError(
                "ruling targets {} source comment {}, which does not accept rulings".format(
                    source_message, source_comment_id
                )
            )
        if source_message == "claim":
            allowed_decisions = (
                {"rejected"}
                if authority_policy["profile"] == "deliberation-only"
                else {"awarded", "rejected"}
            )
        else:
            allowed_decisions = {"authorized", "unauthorized"}
        allowed_decisions.add("invalidated")
        if header["decision"] not in allowed_decisions:
            raise ValidationError(
                "ruling decision {} is not legal for {} source comment {}".format(
                    header["decision"], source_message, source_comment_id
                )
            )
        ruled_sources[source_comment_id] = record

    for record in parsed:
        if (
            record["header"]["message"] in RULING_REQUIRED_MESSAGES
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
    def refresh_fixture_receipt(event):
        try:
            event["created_body_digest"] = canonical_digest(event.get("body"))
        except (AttributeError, UnicodeEncodeError):
            event["created_body_digest"] = "sha256:" + "0" * 64

    def validate_fixture_bundle(bundle):
        """Attach authenticated creation receipts to an integrity fixture."""
        for event in bundle.get("ordered_events", []):
            if "created_body_digest" not in event:
                refresh_fixture_receipt(event)
        return validate_integrity_bundle(bundle)

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

    generic_artefact = make_fixture(
        "result",
        [
            ("claim", "implementation"),
            ("result-id", "result-1"),
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
        "four-space opening fence": (
            "    ```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0007\nclaim: work\n```\n\nRelease."
        ),
        "indented duplicate block": (
            "```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0008\nclaim: work\n```\n\nFirst block.\n"
            "   ```open-table\nopen-table: 0\nmessage: release\n"
            "id: malformed-0009\nclaim: work\n   ```\n\nSecond block."
        ),
        "generic artefact with backslash": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://example.com\\artifact#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with invalid percent escape": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://example.com/%GG#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with bracket in path": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://example.com/a[b]#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with malformed IP literal": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://[not-ip]/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with duplicate at-sign": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://user@@example.com/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with nonnumeric port": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://example.com:no/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with raw tab": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://exam\tple.com/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with scoped IPv6": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
                ("outcome", "completed"),
                ("artefact", "https://[fe80::1%eth0]/a#sha256=" + "a" * 64),
            ],
        ),
        "generic artefact with non-ASCII port": make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
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
    notices = validate_fixture_bundle(duplicate_bundle)
    assert len(notices) == 1 and notices[0].startswith("exact duplicate:")
    print("integrity fixture (exact duplicate): accepted")

    edited_bundle = json.loads(json.dumps(duplicate_bundle))
    edited_bundle["ordered_events"][0]["last_edited_at"] = (
        "2026-08-01T00:00:00Z"
    )
    try:
        validate_fixture_bundle(edited_bundle)
    except ValidationError as error:
        assert "was edited" in str(error) and "fail closed" in str(error)
        print("integrity fixture (edited trusted comment): rejected: {}".format(error))
    else:
        raise AssertionError("an edited trusted comment was accepted")

    missing_update_bundle = json.loads(json.dumps(duplicate_bundle))
    del missing_update_bundle["ordered_events"][0]["updated_at"]
    try:
        validate_fixture_bundle(missing_update_bundle)
    except ValidationError as error:
        assert "must contain" in str(error) and "updated_at" in str(error)
        print("integrity fixture (missing trusted updated_at): rejected")
    else:
        raise AssertionError("an event without trusted updated_at was accepted")

    missing_edit_marker_bundle = json.loads(json.dumps(duplicate_bundle))
    del missing_edit_marker_bundle["ordered_events"][0]["last_edited_at"]
    try:
        validate_fixture_bundle(missing_edit_marker_bundle)
    except ValidationError as error:
        assert "must contain" in str(error) and "last_edited_at" in str(error)
        print("integrity fixture (missing trusted last_edited_at): rejected")
    else:
        raise AssertionError("an event without trusted last_edited_at was accepted")

    missing_creation_receipt_bundle = json.loads(json.dumps(duplicate_bundle))
    del missing_creation_receipt_bundle["ordered_events"][0]["created_body_digest"]
    try:
        validate_integrity_bundle(missing_creation_receipt_bundle)
    except ValidationError as error:
        assert "must contain" in str(error) and "created_body_digest" in str(error)
        print("integrity fixture (missing authenticated creation digest): rejected")
    else:
        raise AssertionError("an event without a creation receipt digest was accepted")

    creation_digest_mismatch_bundle = json.loads(json.dumps(duplicate_bundle))
    creation_digest_mismatch_bundle["ordered_events"][0]["created_body_digest"] = (
        "sha256:" + "0" * 64
    )
    try:
        validate_fixture_bundle(creation_digest_mismatch_bundle)
    except ValidationError as error:
        assert "creation receipt digest" in str(error) and "fails closed" in str(error)
        print("integrity fixture (creation receipt digest mismatch): rejected")
    else:
        raise AssertionError("a creation receipt digest mismatch was accepted")

    edited_retry_bundle = json.loads(json.dumps(duplicate_bundle))
    edited_retry_bundle["ordered_events"][1]["created_body_digest"] = (
        "sha256:" + "0" * 64
    )
    try:
        validate_fixture_bundle(edited_retry_bundle)
    except ValidationError as error:
        assert "creation receipt digest" in str(error)
        assert "exact duplicate" not in str(error)
        print("integrity fixture (edited exact retry): rejected before deduplication")
    else:
        raise AssertionError("an edited exact retry bypassed its creation receipt")

    conflict_bundle = json.loads(json.dumps(duplicate_bundle))
    conflict_bundle["ordered_events"][1]["body"] += "\nChanged prose."
    refresh_fixture_receipt(conflict_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(conflict_bundle)
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
        validate_fixture_bundle(mismatch_bundle)
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
    refresh_fixture_receipt(illegal_claim_decision_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(illegal_claim_decision_bundle)
    except ValidationError as error:
        assert "decision authorized is not legal for claim" in str(error)
        print("integrity fixture (illegal claim ruling decision): rejected")
    else:
        raise AssertionError("an authorized decision was accepted for a claim")

    deliberation_award_bundle = json.loads(json.dumps(mismatch_bundle))
    deliberation_award_bundle["authority_policy"]["profile"] = "deliberation-only"
    deliberation_award_bundle["ordered_events"][1]["body"] = valid_ruling
    refresh_fixture_receipt(deliberation_award_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(deliberation_award_bundle)
    except ValidationError as error:
        assert "decision awarded is not legal for claim" in str(error)
        print("integrity fixture (deliberation-only claim award): rejected")
    else:
        raise AssertionError("deliberation-only accepted an awarded claim ruling")

    invalidated_claim_bundle = json.loads(json.dumps(mismatch_bundle))
    invalidated_claim_bundle["ordered_events"][1]["body"] = valid_ruling.replace(
        "decision: awarded", "decision: invalidated"
    )
    refresh_fixture_receipt(invalidated_claim_bundle["ordered_events"][1])
    assert validate_fixture_bundle(invalidated_claim_bundle) == []
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
        validate_fixture_bundle(non_rulable_source_bundle)
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
    notices = validate_fixture_bundle(late_duplicate_bundle)
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
        validate_fixture_bundle(duplicate_ruling_bundle)
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
    notices = validate_fixture_bundle(unauthorized_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; treated as prose"
    ]
    print("integrity fixture (unauthorized ruling author): excluded as prose")

    empty_bundle = {
        "authority_policy": unauthorized_bundle["authority_policy"],
        "ordered_events": [],
    }
    assert validate_fixture_bundle(empty_bundle) == []
    print("integrity fixture (empty event stream): accepted")

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
            validate_fixture_bundle(fixture)
        except ValidationError as error:
            assert "at most 20 digits" in str(error)
            print("integrity fixture (oversized {} id): rejected".format(label))
        else:
            raise AssertionError("oversized {} id was accepted".format(label))

    invalid_claim = (
        "```open-table\nopen-table: 0\nmessage: claim\n"
        "id: invalid-claim-0001\nclaim: work\n```\n\nMissing expiry."
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
    notices = validate_fixture_bundle(public_input_bundle)
    assert notices[0].startswith("excluded non-protocol comment 8")
    assert notices[1].startswith("excluded invalid open-table comment 9")
    print("integrity fixture (ordinary and malformed public input): excluded")

    invalid_lease_body = make_fixture(
        "claim",
        [("claim", "implementation"), ("expires-at", "2026-08-20T00:00:00Z")],
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
    notices = validate_fixture_bundle(invalid_lease_bundle)
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
    notices = validate_fixture_bundle(malformed_unauthorized_bundle)
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
    refresh_fixture_receipt(truncated_unauthorized_bundle["ordered_events"][1])
    notices = validate_fixture_bundle(truncated_unauthorized_bundle)
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
        validate_fixture_bundle(truncated_authenticated_bundle)
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
    refresh_fixture_receipt(malformed_discriminator_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(malformed_discriminator_bundle)
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
        refresh_fixture_receipt(malformed_delimiter_bundle["ordered_events"][1])
        try:
            validate_fixture_bundle(malformed_delimiter_bundle)
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
    refresh_fixture_receipt(missing_discriminator_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(missing_discriminator_bundle)
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
    refresh_fixture_receipt(four_space_authenticated_bundle["ordered_events"][1])
    try:
        validate_fixture_bundle(four_space_authenticated_bundle)
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
    notices = validate_fixture_bundle(forged_id_conflict_bundle)
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
    notices = validate_fixture_bundle(valid_forged_id_conflict_bundle)
    assert notices == [
        "excluded ruling-shaped comment 7 from unauthorized actor 888; "
        "treated as prose"
    ]
    print("integrity fixture (valid unauthorized id reuse): accepted")

    expiration_body = make_fixture(
        "expiration",
        [("claim", "implementation"), ("expired-at", "2026-08-01T12:00:00Z")],
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
    notices = validate_fixture_bundle(unauthorized_expiration_bundle)
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
    notices = validate_fixture_bundle(surrogate_public_bundle)
    assert len(notices) == 1 and "not valid UTF-8 scalar text" in notices[0]
    print("integrity fixture (lone-surrogate public text): excluded")

    surrogate_expiration_bundle = json.loads(
        json.dumps(unauthorized_expiration_bundle)
    )
    surrogate_expiration_bundle["ordered_events"][0]["actor_id"] = 999
    surrogate_expiration_bundle["ordered_events"][0]["body"] += "\ud800"
    try:
        validate_fixture_bundle(surrogate_expiration_bundle)
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
    notices = validate_fixture_bundle(duplicate_source_bundle)
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
    notices = validate_fixture_bundle(duplicate_ruling_retry_bundle)
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
        validate_fixture_bundle(preemptive_ruling_bundle)
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
        validate_fixture_bundle(early_expiration_bundle)
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

    for oversized_artefact in (
        "github:{}:pull:45:head:{}".format("1" * 21, "a" * 40),
        "github:123:pull:{}:head:{}".format("1" * 21, "a" * 40),
    ):
        oversized_artefact_message = make_fixture(
            "result",
            [
                ("claim", "implementation"),
                ("result-id", "result-1"),
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
        [("claim", "implementation"), ("expired-at", "2026-02-31T12:00:00Z")],
    )
    try:
        parse_comment(impossible_timestamp)
    except ValidationError as error:
        assert "not a real UTC date" in str(error)
        print("integrity fixture (impossible timestamp): rejected: {}".format(error))
    else:
        raise AssertionError("an impossible timestamp was accepted")

    corrected_invalid_claim = invalid_claim.replace(
        "claim: work\n", "claim: work\nexpires-at: 2026-08-02T00:00:00Z\n"
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
        validate_fixture_bundle(reserved_id_bundle)
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
    refresh_fixture_receipt(repeated_id_bundle["ordered_events"][0])
    try:
        validate_fixture_bundle(repeated_id_bundle)
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
    notices = validate_fixture_bundle(ambiguous_id_bundle)
    assert len(notices) == 1 and "no unambiguous message id reserved" in notices[0]
    print("integrity fixture (ambiguous invalid ids): no id reserved")

    ambiguous_surrogate_bundle = json.loads(json.dumps(ambiguous_id_bundle))
    ambiguous_surrogate_bundle["ordered_events"][0]["body"] += "\ud800"
    notices = validate_fixture_bundle(ambiguous_surrogate_bundle)
    assert len(notices) == 1 and "no unambiguous message id reserved" in notices[0]
    print("integrity fixture (ambiguous surrogate ids): no id reserved")

    print(
        "self-test: 14 valid families, 19 malformed fixtures, and 53 integrity "
        "rules passed"
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
