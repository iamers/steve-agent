#!/usr/bin/env python3
"""Reusable runtime-neutral Open Table v0 parsing and integrity core.

The names in ``__all__`` are the supported import surface.
``validate_integrity_bundle_diagnostics`` returns nonfatal diagnostics and raises
``ValidationError`` for fatal outcomes; when present, ``ValidationError.diagnostic``
carries the same stable code, rule, severity, and location fields. Human-readable
``detail`` text is not contractual.

The caller supplies already-authenticated GitHub metadata and complete replay
inputs. This module validates those inputs but does not authenticate or gather
them, establish completeness, reduce contextual state, or perform I/O.
"""

import datetime
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass


__all__ = (
    "Diagnostic",
    "MAX_PROTOCOL_INTEGER",
    "REASON_CATALOG",
    "ValidationError",
    "canonical_digest",
    "make_diagnostic",
    "parse_comment",
    "parse_integrity_bundle_json",
    "render_diagnostics",
    "validate_integrity_bundle",
    "validate_integrity_bundle_diagnostics",
)


COMMON_FIELDS = {"open-table", "message", "id"}
MESSAGE_FIELDS = {
    "configuration": {
        "phase", "sequence", "expected-actors", "authority-profile", "turn-limit"
    },
    "contribution": {"phase", "turn"},
    "proposal": {"phase", "turn", "point"},
    "settled": {
        "phase", "turn", "point", "proposal-comment-id", "disposition", "terminal"
    },
    "claim": {"expires-at"},
    "renewal": {"claim-comment-id", "expires-at"},
    "release": {"claim-comment-id"},
    "handoff": {"claim-comment-id", "to-actor-id", "expires-at"},
    "cancellation": {"claim-comment-id"},
    "expiration": {"claim-comment-id", "expired-at"},
    "result": {"claim-comment-id", "outcome", "artefact"},
    "review-request": {"claim-comment-id", "result-comment-id", "artefact"},
    "verdict": {
        "claim-comment-id", "review-comment-id", "result-comment-id", "artefact",
        "verdict"
    },
    "ruling": {
        "target-actor-id", "message-id", "source-comment-id", "source-digest",
        "decision"
    },
}
TOKEN_FIELDS = {"phase", "point"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
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
AUTHORITY_PROFILES = {
    "deliberation-only", "open-table/ordered-claims", "steve/kanban"
}
RULING_DECISIONS = {
    "authorized", "unauthorized", "awarded", "rejected", "invalidated"
}
REASON_CATALOG = {
    "invalid_bundle": {"rule": "2.8"},
    "event_order_invalid": {"rule": "2.4"},
    "source_edited": {"rule": "2.2, 7.3"},
    "non_protocol_comment": {"rule": "2.8, 7.5"},
    "invalid_envelope": {"rule": "3.1-3.5"},
    "invalid_field": {"rule": "3.3-3.6, 4"},
    "invalid_artefact": {"rule": "4.13"},
    "exact_duplicate": {"rule": "7.2"},
    "message_id_conflict": {"rule": "7.2"},
    "unauthorized_reducer_output": {"rule": "2.3, 4.12, 4.16"},
    "ruling_missing": {"rule": "4.16, 9.1"},
    "ruling_duplicate": {"rule": "4.16, 9.1"},
    "ruling_binding_invalid": {"rule": "4.16, 7.3"},
    "ruling_decision_invalid": {"rule": "4.17"},
}


@dataclass(frozen=True)
class Diagnostic:
    """Stable machine-readable validation outcome with non-contractual detail."""

    severity: str
    code: str
    rule: str
    detail: str
    comment_id: int = None
    related_comment_id: int = None
    field: str = None

    def to_dict(self):
        result = {
            "severity": self.severity,
            "code": self.code,
            "rule": self.rule,
            "detail": self.detail,
        }
        for name in ("comment_id", "related_comment_id", "field"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        return result


class ValidationError(ValueError):
    """A readable validation failure, optionally carrying a stable diagnostic."""

    def __init__(self, detail, diagnostic=None):
        super().__init__(detail)
        self.diagnostic = diagnostic


def fail_validation(code, detail, **location):
    """Raise one fatal structured validation failure."""
    rule = REASON_CATALOG[code]["rule"]
    diagnostic = Diagnostic(
        severity="fatal",
        code=code,
        rule=rule,
        detail=detail,
        **location
    )
    raise ValidationError(detail, diagnostic)


def make_diagnostic(severity, code, detail, **location):
    """Return one stable structured diagnostic."""
    return Diagnostic(
        severity=severity,
        code=code,
        rule=REASON_CATALOG[code]["rule"],
        detail=detail,
        **location
    )


def contextualize_diagnostic(
    error, severity, detail, comment_id, fallback_code
):
    """Rebase one child validation diagnostic onto trusted comment context."""
    source = error.diagnostic or make_diagnostic(
        severity, fallback_code, str(error), comment_id=comment_id
    )
    return Diagnostic(
        severity=severity,
        code=source.code,
        rule=source.rule,
        detail=detail,
        comment_id=comment_id,
        related_comment_id=source.related_comment_id,
        field=source.field,
    )


def fail_invalid_envelope(detail, **location):
    """Raise one stable envelope-shape failure."""
    fail_validation("invalid_envelope", detail, **location)


def fail_invalid_field(detail, **location):
    """Raise one stable protocol-field failure."""
    fail_validation("invalid_field", detail, **location)


def canonical_digest(body):
    """Return the canonical digest of one complete GitHub comment body."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def reject_duplicate_json_members(pairs):
    """Reject duplicate JSON object member names before interpretation."""
    result = {}
    for key, value in pairs:
        if key in result:
            fail_validation(
                "invalid_bundle",
                "duplicate JSON object member: {}".format(key),
                field=key,
            )
        result[key] = value
    return result


def parse_integrity_bundle_json(raw):
    """Decode one integrity bundle while preserving the closed JSON contract."""
    try:
        return json.loads(raw, object_pairs_hook=reject_duplicate_json_members)
    except json.JSONDecodeError as error:
        fail_validation(
            "invalid_bundle",
            "integrity bundle is not valid JSON: {} at line {} column {}".format(
                error.msg, error.lineno, error.colno
            ),
            field="bundle",
        )


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


def unauthorized_reducer_output_diagnostic(shapes, comment_id, actor_id):
    """Return the stable exclusion for reducer-shaped prose by another actor."""
    return make_diagnostic(
        "excluded",
        "unauthorized_reducer_output",
        "excluded {}-shaped comment {} from unauthorized actor {}; treated as "
        "prose".format(sorted(shapes)[0], comment_id, actor_id),
        comment_id=comment_id,
    )


def legal_ruling_decisions(source_message, authority_profile):
    """Return event-local decisions allowed by sections 4.16, 4.17, 6.2, and 6.5.

    This preserves the final-A integrity check. It does not decide whether a
    legal ruling matches contextual state, which belongs to reduction.
    """
    if source_message == "claim":
        decisions = (
            {"rejected"}
            if authority_profile == "deliberation-only"
            else {"awarded", "rejected"}
        )
    else:
        decisions = {"authorized", "unauthorized"}
    return decisions | {"invalidated"}


def parse_utc_timestamp(value, field):
    """Parse one already shape-checked protocol timestamp."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        fail_invalid_field(
            "{} is not a real UTC date and time".format(field), field=field
        )


def validate_event_local(header, created_at):
    """Validate constraints that need only one trusted comment event."""
    message = header["message"]
    created = parse_utc_timestamp(created_at, "created_at")
    if message in {"claim", "renewal", "handoff"}:
        expires = parse_utc_timestamp(header["expires-at"], "expires-at")
        if expires <= created or expires - created > datetime.timedelta(days=7):
            fail_invalid_field(
                "{} expires-at must be later than created_at and no more than "
                "seven days later".format(message), field="expires-at"
            )
    if message == "expiration":
        expired = parse_utc_timestamp(header["expired-at"], "expired-at")
        if created < expired:
            fail_invalid_field(
                "expiration trusted created_at must be at or after expired-at",
                field="expired-at",
            )


def parse_comment(body):
    """Return the validated header and human prose from a comment body."""
    opening = OPENING_RE.match(body)
    if not opening:
        fail_invalid_envelope(
            "comment must begin with a fenced block whose info string is open-table"
        )

    closing = CLOSING_RE.search(body, opening.end())
    if not closing:
        fail_invalid_envelope("open-table fenced block is not closed")

    header_text = body[opening.end():closing.start()]
    prose = body[closing.end():]

    if BLOCK_OPENING_RE.search(prose):
        fail_invalid_envelope("comment must contain exactly one open-table fenced block")
    if not prose.strip():
        fail_invalid_envelope("comment must contain human-readable prose after the header")

    header = parse_header(header_text)
    validate_header(header)
    return header, prose


def parse_header(header_text):
    """Parse strict single-line key/value pairs from an envelope header."""
    header = {}
    if UNSUPPORTED_LINE_SEPARATOR_RE.search(header_text):
        fail_invalid_envelope("header contains an unsupported Unicode line separator")
    lines = split_physical_lines(header_text)
    if any("\r" in line for line in lines):
        fail_invalid_envelope("header contains a bare carriage return")
    if not lines:
        fail_invalid_envelope("open-table header is empty")

    for number, line in enumerate(lines, 1):
        if not line:
            fail_invalid_envelope("header line {} is empty".format(number))
        if ": " not in line:
            fail_invalid_envelope(
                "header line {} must have the form key: value".format(number)
            )
        key, value = line.split(": ", 1)
        if not KEY_RE.fullmatch(key):
            fail_invalid_envelope("invalid header key on line {}".format(number))
        if not value or value != value.strip():
            fail_invalid_envelope(
                "header value for {} must be non-empty and unpadded".format(key),
                field=key,
            )
        if key in header:
            fail_invalid_envelope("duplicate header key: {}".format(key), field=key)
        header[key] = value
    return header


def validate_header(header):
    """Validate common fields and the exact field set for one message family."""
    if header.get("open-table") != "0":
        fail_invalid_field("open-table must be the literal 0", field="open-table")

    message = header.get("message")
    if message not in MESSAGE_FIELDS:
        fail_invalid_field(
            "unknown or missing message type: {}".format(message), field="message"
        )

    expected = COMMON_FIELDS | MESSAGE_FIELDS[message]
    missing = sorted(expected - set(header))
    unknown = sorted(set(header) - expected)
    if missing:
        fail_invalid_field("missing required field(s): {}".format(", ".join(missing)))
    if unknown:
        fail_invalid_field("unknown field(s): {}".format(", ".join(unknown)))

    if not ID_RE.fullmatch(header["id"]):
        fail_invalid_field("id does not match the Open Table token syntax", field="id")

    for field in TOKEN_FIELDS & set(header):
        if not TOKEN_RE.fullmatch(header[field]):
            fail_invalid_field(
                "{} does not match the token syntax".format(field), field=field
            )

    if "turn" in header:
        if not is_positive_ascii_integer(header["turn"]):
            fail_invalid_field(
                "turn must be a base-10 integer of at least 1", field="turn"
            )

    for field in ("sequence", "turn-limit"):
        if field in header:
            if not is_positive_ascii_integer(header[field]):
                fail_invalid_field(
                    "{} must be a base-10 integer of at least 1".format(field),
                    field=field,
                )

    for field in ("expires-at", "expired-at"):
        if field in header:
            timestamp = header[field]
            if not TIMESTAMP_RE.fullmatch(timestamp):
                fail_invalid_field(
                    "{} must use the exact RFC 3339 UTC form".format(field),
                    field=field,
                )
            parse_utc_timestamp(timestamp, field)

    for field in (
        "target-actor-id", "to-actor-id", "source-comment-id",
        "proposal-comment-id", "claim-comment-id", "result-comment-id",
        "review-comment-id"
    ):
        if field in header:
            if not is_positive_ascii_integer(header[field]):
                fail_invalid_field(
                    "{} must be a positive numeric GitHub id".format(field),
                    field=field,
                )

    if "message-id" in header and not ID_RE.fullmatch(header["message-id"]):
        fail_invalid_field(
            "message-id does not match the Open Table token syntax", field="message-id"
        )

    if "expected-actors" in header:
        actors = header["expected-actors"].split(",")
        if (
            any(not is_positive_ascii_integer(actor) for actor in actors)
            or len(actors) != len(set(actors))
        ):
            fail_invalid_field(
                "expected-actors must be unique numeric GitHub ids separated by commas",
                field="expected-actors",
            )

    if "source-digest" in header and not DIGEST_RE.fullmatch(header["source-digest"]):
        fail_invalid_field(
            "source-digest must be a canonical sha256 digest", field="source-digest"
        )

    if "artefact" in header and not (
        GITHUB_ARTEFACT_RE.fullmatch(header["artefact"])
        or is_generic_artefact(header["artefact"])
    ):
        fail_validation(
            "invalid_artefact",
            "artefact must be an immutable GitHub or generic reference",
            field="artefact",
        )

    enumerations = {
        "disposition": {"accepted", "rejected"},
        "terminal": {"true", "false"},
        "outcome": {"completed", "failed"},
        "verdict": {"approved", "changes-requested"},
        "decision": RULING_DECISIONS,
        "authority-profile": AUTHORITY_PROFILES,
    }
    for field, allowed in enumerations.items():
        if field in header and header[field] not in allowed:
            fail_invalid_field(
                "{} must be one of: {}".format(field, ", ".join(sorted(allowed))),
                field=field,
            )


def validate_integrity_bundle_diagnostics(bundle):
    """Validate supplied trusted events and existing rulings.

    This integrity slice does not gather or authenticate GitHub evidence, choose
    rulings, reduce contextual state, or mutate a projection.
    """
    required_bundle_fields = {"authority_policy", "ordered_events"}
    if not isinstance(bundle, dict) or set(bundle) != required_bundle_fields:
        fail_validation(
            "invalid_bundle",
            "integrity bundle must contain only authority_policy and ordered_events",
            field="bundle",
        )
    authority_policy = bundle["authority_policy"]
    if not isinstance(authority_policy, dict) or set(authority_policy) != {
        "profile", "reducer_principals"
    }:
        fail_validation(
            "invalid_bundle",
            "authority_policy must contain only profile and reducer_principals"
        )
    authority_profile = authority_policy["profile"]
    if (
        not isinstance(authority_profile, str)
        or authority_profile not in AUTHORITY_PROFILES
    ):
        fail_validation(
            "invalid_bundle", "authority_policy profile is not supported",
            field="authority_policy",
        )
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
        fail_validation(
            "invalid_bundle",
            "authority_policy reducer_principals must be unique positive numeric "
            "GitHub actor ids of at most 20 digits", field="authority_policy"
        )
    allowed_reducer_principals = set(reducer_principals)
    events = bundle["ordered_events"]
    if not isinstance(events, list):
        fail_validation(
            "invalid_bundle", "ordered_events must be a list",
            field="ordered_events",
        )

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
            fail_validation(
                "invalid_bundle",
                "event {} must contain actor_id, comment_id, created_at, updated_at, "
                "last_edited_at, created_body_digest, and body".format(index),
                field="ordered_events",
            )
        actor_id = event["actor_id"]
        comment_id = event["comment_id"]
        created_at = event["created_at"]
        updated_at = event["updated_at"]
        last_edited_at = event["last_edited_at"]
        created_body_digest = event["created_body_digest"]
        body = event["body"]
        if not is_positive_protocol_integer(actor_id):
            fail_validation(
                "invalid_bundle",
                "event {} actor_id must be a positive integer of at most 20 "
                "digits".format(index), field="actor_id"
            )
        if not is_positive_protocol_integer(comment_id):
            fail_validation(
                "invalid_bundle",
                "event {} comment_id must be a positive integer of at most 20 "
                "digits".format(index), field="comment_id"
            )
        if comment_id in seen_comment_ids:
            fail_validation(
                "invalid_bundle",
                "duplicate trusted comment id: {}".format(comment_id),
                comment_id=comment_id,
            )
        seen_comment_ids.add(comment_id)
        for timestamp_field, timestamp_value in (
            ("created_at", created_at),
            ("updated_at", updated_at),
        ):
            if (
                not isinstance(timestamp_value, str)
                or not TIMESTAMP_RE.fullmatch(timestamp_value)
            ):
                fail_validation(
                    "invalid_bundle",
                    "event {} {} must use the exact RFC 3339 UTC form".format(
                        index, timestamp_field
                    ), field=timestamp_field
                )
            try:
                datetime.datetime.strptime(timestamp_value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                fail_validation(
                    "invalid_bundle",
                    "event {} {} is not a real UTC date and time".format(
                        index, timestamp_field
                    ), field=timestamp_field
                )
        if updated_at != created_at:
            fail_validation(
                "source_edited",
                "trusted comment {} was edited: updated_at differs from created_at; "
                "fail closed".format(comment_id), comment_id=comment_id
            )
        if last_edited_at is not None:
            fail_validation(
                "source_edited",
                "trusted comment {} was edited: GitHub last_edited_at is non-null; "
                "fail closed".format(comment_id), comment_id=comment_id
            )
        if (
            not isinstance(created_body_digest, str)
            or not DIGEST_RE.fullmatch(created_body_digest)
        ):
            fail_validation(
                "invalid_bundle",
                "event {} created_body_digest must be a canonical sha256 digest".format(
                    index
                ), comment_id=comment_id, field="created_body_digest"
            )
        if not isinstance(body, str):
            fail_validation(
                "invalid_bundle", "event {} body must be a string".format(index),
                comment_id=comment_id, field="body",
            )

        order = (created_at, comment_id)
        if previous_order is not None and order < previous_order:
            fail_validation(
                "event_order_invalid",
                "ordered_events are not in trusted GitHub order",
                comment_id=comment_id,
            )
        previous_order = order

        reducer_output_shapes = identify_reducer_output_shapes(body)
        authenticated_open_table_candidate = (
            actor_id in allowed_reducer_principals and bool(OPEN_TABLE_CANDIDATE_RE.match(body))
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
                fail_validation(
                    "invalid_envelope",
                    "invalid authenticated {} comment {}: body is not valid UTF-8 "
                    "scalar text".format(
                        output_shape, comment_id
                    ), comment_id=comment_id
                )
            if unauthorized_reducer_shape:
                notices.append(unauthorized_reducer_output_diagnostic(
                    reducer_output_shapes, comment_id, actor_id
                ))
                continue
            candidate_id = recover_message_id(body)
            if candidate_id is not None:
                key = (actor_id, candidate_id)
                if key in seen_messages:
                    fail_validation(
                        "message_id_conflict",
                        "conflict: actor {} message id {} cannot be canonically "
                        "digested".format(actor_id, candidate_id),
                        comment_id=comment_id,
                    )
                seen_messages[key] = None
            notices.append(make_diagnostic(
                "excluded", "invalid_envelope",
                "excluded comment {} whose body is not valid UTF-8 scalar text{}".format(
                    comment_id, id_reservation_notice(candidate_id)
                ), comment_id=comment_id
                )
            )
            continue

        if digest != created_body_digest:
            fail_validation(
                "source_edited",
                "trusted comment {} body differs from its authenticated creation "
                "receipt digest; edited source material fails closed".format(comment_id),
                comment_id=comment_id,
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
                detail = "invalid authenticated {} comment {}: {}".format(
                    output_shape, comment_id, error
                )
                raise ValidationError(
                    detail,
                    contextualize_diagnostic(
                        error, "fatal", detail, comment_id, "invalid_envelope"
                    ),
                ) from error
            if unauthorized_reducer_shape:
                notices.append(unauthorized_reducer_output_diagnostic(
                    reducer_output_shapes, comment_id, actor_id
                ))
                continue
            candidate_id = recover_message_id(body)
            if candidate_id is not None:
                key = (actor_id, candidate_id)
                if key in seen_messages and seen_messages[key] != digest:
                    fail_validation(
                        "message_id_conflict",
                        "conflict: actor {} message id {} has a different digest; "
                        "it is not a duplicate".format(actor_id, candidate_id),
                        comment_id=comment_id,
                    )
                # Section 7.2 deliberately reserves a syntactically recoverable
                # actor/id key even when the earliest envelope is invalid.
                seen_messages.setdefault(key, digest)
            if OPENING_RE.match(body):
                detail = "excluded invalid open-table comment {}: {}{}".format(
                    comment_id, error, id_reservation_notice(candidate_id)
                )
                notices.append(contextualize_diagnostic(
                    error, "excluded", detail, comment_id, "invalid_envelope"
                ))
            else:
                notices.append(make_diagnostic(
                    "excluded", "non_protocol_comment",
                    "excluded non-protocol comment {}; treated as prose".format(
                        comment_id
                    ), comment_id=comment_id
                    )
                )
            continue

        if unauthorized_reducer_shape:
            notices.append(unauthorized_reducer_output_diagnostic(
                reducer_output_shapes, comment_id, actor_id
            ))
            continue

        key = (actor_id, header["id"])
        if key in seen_messages:
            previous_digest = seen_messages[key]
            if digest != previous_digest:
                fail_validation(
                    "message_id_conflict",
                    "conflict: actor {} message id {} has a different digest; "
                    "it is not a duplicate".format(actor_id, header["id"]),
                    comment_id=comment_id,
                )
            notices.append(make_diagnostic(
                "notice", "exact_duplicate",
                "exact duplicate: actor {} message id {} digest {}".format(
                    actor_id, header["id"], digest
                ), comment_id=comment_id
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
                detail = "invalid authenticated {} comment {}: {}".format(
                    output_shape, comment_id, error
                )
                raise ValidationError(
                    detail,
                    contextualize_diagnostic(
                        error, "fatal", detail, comment_id, "invalid_field"
                    ),
                ) from error
            detail = "excluded invalid open-table comment {}: {}{}".format(
                comment_id, error, id_reservation_notice(header["id"])
            )
            notices.append(contextualize_diagnostic(
                error, "excluded", detail, comment_id, "invalid_field"
            ))
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
            fail_validation(
                "ruling_duplicate",
                "duplicate ruling {} for source comment {}; first ruling was {}".format(
                    header["id"], source_comment_id,
                    ruled_sources[source_comment_id]["header"]["id"]
                ), comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
            )
        source = by_comment_id.get(source_comment_id)
        if source is None:
            fail_validation(
                "ruling_binding_invalid",
                "ruling source comment {} is deleted or missing; fail closed".format(
                    source_comment_id
                ), comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
            )
        if source["order"] >= record["order"]:
            fail_validation(
                "ruling_binding_invalid",
                "ruling must be appended after its bound source",
                comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
            )
        if source["actor_id"] != int(header["target-actor-id"]):
            fail_validation(
                "ruling_binding_invalid",
                "ruling target actor does not match trusted source actor",
                comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
                field="target-actor-id",
            )
        if source["header"]["id"] != header["message-id"]:
            fail_validation(
                "ruling_binding_invalid",
                "ruling message id does not match its bound source",
                comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
                field="message-id",
            )
        if source["digest"] != header["source-digest"]:
            fail_validation(
                "ruling_binding_invalid",
                "ruling source digest mismatch; source was edited or binding is invalid; "
                "fail closed", comment_id=record["comment_id"],
                related_comment_id=source_comment_id, field="source-digest"
            )
        source_message = source["header"]["message"]
        if source_message not in RULING_REQUIRED_MESSAGES:
            fail_validation(
                "ruling_binding_invalid",
                "ruling targets {} source comment {}, which does not accept rulings".format(
                    source_message, source_comment_id
                ), comment_id=record["comment_id"],
                related_comment_id=source_comment_id,
            )
        allowed_decisions = legal_ruling_decisions(
            source_message, authority_policy["profile"]
        )
        if header["decision"] not in allowed_decisions:
            fail_validation(
                "ruling_decision_invalid",
                "ruling decision {} is not legal for {} source comment {}".format(
                    header["decision"], source_message, source_comment_id
                ), comment_id=record["comment_id"],
                related_comment_id=source_comment_id, field="decision"
            )
        ruled_sources[source_comment_id] = record

    for record in parsed:
        if (
            record["header"]["message"] in RULING_REQUIRED_MESSAGES
            and record["comment_id"] not in ruled_sources
        ):
            fail_validation(
                "ruling_missing",
                "required ruling for source comment {} is deleted or missing; "
                "fail closed".format(record["comment_id"]),
                comment_id=record["comment_id"],
            )

    return notices


def validate_integrity_bundle(bundle):
    """Preserve the A API by rendering structured notices as English text."""
    return render_diagnostics(validate_integrity_bundle_diagnostics(bundle))


def render_diagnostics(diagnostics):
    """Render non-contractual detail text for compatible human-facing output."""
    return [diagnostic.detail for diagnostic in diagnostics]
