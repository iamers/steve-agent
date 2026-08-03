#!/usr/bin/env python3
"""Reusable runtime-neutral Open Table v0 parsing and integrity core."""

import datetime
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass


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
REPLAY_CARRIER_FIELDS = {
    "open_table", "repository_id", "issue_number", "as_of",
    "comments_complete_through", "timeline_complete_through",
    "authority_policy", "ordered_events",
}
COMMENT_EVENT_FIELDS = {
    "kind", "actor_id", "comment_id", "created_at", "updated_at",
    "last_edited_at", "created_body_digest", "body",
}
ISSUE_STATE_EVENT_FIELDS = {"kind", "event_id", "created_at", "state"}
COMMENT_DELETION_EVENT_FIELDS = {
    "kind", "event_id", "created_at", "comment_id"
}
DECISION_REQUEST_FIELDS = {
    "open_table", "replay", "source_comment_id", "permission_observation",
    "profile_outcome",
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


def fail_validation(code, rule, detail, **location):
    """Raise one fatal structured validation failure."""
    diagnostic = Diagnostic(
        severity="fatal",
        code=code,
        rule=rule,
        detail=detail,
        **location
    )
    raise ValidationError(detail, diagnostic)


def canonical_json_bytes(value):
    """Serialize one normalized value as deterministic UTF-8 JSON plus LF."""
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (text + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        fail_validation(
            "invalid_bundle",
            "2.5",
            "value cannot be represented as canonical UTF-8 JSON: {}".format(error),
        )


def normalize_carrier_timestamp(value, field, code="invalid_bundle", rule="2.5"):
    """Return one exact real UTC carrier timestamp and its parsed value."""
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        fail_validation(
            code,
            rule,
            "{} must use the exact RFC 3339 UTC form".format(field),
            field=field,
        )
    try:
        parsed = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        fail_validation(
            code,
            rule,
            "{} is not a real UTC date and time".format(field),
            field=field,
        )
    return value, parsed


def normalize_replay_event(event, index, as_of_value):
    """Validate and copy one closed replay-carrier event fact."""
    field = "ordered_events"
    if not isinstance(event, dict):
        fail_validation(
            "invalid_event", "2.4, 2.5",
            "ordered event {} must be an object".format(index), field=field
        )
    kind = event.get("kind")
    if not isinstance(kind, str):
        fail_validation(
            "invalid_event", "2.4, 2.5",
            "ordered event {} kind must be text".format(index), field=field
        )
    expected_fields = {
        "comment": COMMENT_EVENT_FIELDS,
        "issue_state": ISSUE_STATE_EVENT_FIELDS,
        "comment_deletion": COMMENT_DELETION_EVENT_FIELDS,
    }.get(kind)
    if expected_fields is None or set(event) != expected_fields:
        fail_validation(
            "invalid_event", "2.4, 2.5",
            "ordered event {} must use one closed event shape".format(index),
            field=field,
        )

    created_at, created = normalize_carrier_timestamp(
        event["created_at"], "created_at", "invalid_event", "2.4, 2.5"
    )
    if created > as_of_value:
        fail_validation(
            "invalid_event", "2.4, 2.5",
            "ordered event {} occurs after as_of".format(index), field=field
        )

    if kind == "comment":
        for name in ("actor_id", "comment_id"):
            if not is_positive_protocol_integer(event[name]):
                fail_validation(
                    "invalid_event", "2.4, 2.5",
                    "comment {} must be a positive protocol integer".format(name),
                    field=name,
                )
        updated_at, _ = normalize_carrier_timestamp(
            event["updated_at"], "updated_at", "invalid_event", "2.5"
        )
        last_edited_at = event["last_edited_at"]
        if last_edited_at is not None:
            last_edited_at, _ = normalize_carrier_timestamp(
                last_edited_at, "last_edited_at", "invalid_event", "2.5"
            )
        if not isinstance(event["created_body_digest"], str) or not DIGEST_RE.fullmatch(
            event["created_body_digest"]
        ):
            fail_validation(
                "invalid_event", "2.2, 2.5",
                "created_body_digest must be a canonical sha256 digest",
                field="created_body_digest",
            )
        if not isinstance(event["body"], str):
            fail_validation(
                "invalid_event", "2.5", "comment body must be text", field="body"
            )
        try:
            event["body"].encode("utf-8")
        except UnicodeEncodeError:
            fail_validation(
                "invalid_event", "2.5", "comment body must be UTF-8 scalar text",
                field="body",
            )
        normalized = {
            "kind": kind,
            "actor_id": event["actor_id"],
            "comment_id": event["comment_id"],
            "created_at": created_at,
            "updated_at": updated_at,
            "last_edited_at": last_edited_at,
            "created_body_digest": event["created_body_digest"],
            "body": event["body"],
        }
    else:
        event_id = event["event_id"]
        if not isinstance(event_id, str) or not TOKEN_RE.fullmatch(event_id):
            fail_validation(
                "invalid_event", "2.4, 2.5",
                "event_id must be a bounded ASCII token", field="event_id"
            )
        normalized = {
            "kind": kind,
            "event_id": event_id,
            "created_at": created_at,
        }
        if kind == "issue_state":
            if not isinstance(event["state"], str) or event["state"] not in {
                "open", "closed"
            }:
                fail_validation(
                    "invalid_event", "2.4, 2.5",
                    "issue state must be open or closed", field="state"
                )
            normalized["state"] = event["state"]
        else:
            if not is_positive_protocol_integer(event["comment_id"]):
                fail_validation(
                    "invalid_event", "2.2, 2.5",
                    "deleted comment_id must be a positive protocol integer",
                    field="comment_id",
                )
            normalized["comment_id"] = event["comment_id"]
    return normalized, created


def normalize_replay_carrier(carrier):
    """Validate and copy the closed runtime-neutral replay carrier."""
    if not isinstance(carrier, dict) or set(carrier) != REPLAY_CARRIER_FIELDS:
        fail_validation(
            "invalid_bundle", "2.5",
            "replay carrier must contain exactly the approved top-level fields"
        )
    if carrier["open_table"] != 0 or isinstance(carrier["open_table"], bool):
        fail_validation(
            "unsupported_version", "11.1",
            "replay carrier open_table must be the integer 0", field="open_table"
        )
    for name in ("repository_id", "issue_number"):
        if not is_positive_protocol_integer(carrier[name]):
            fail_validation(
                "invalid_bundle", "2.5",
                "{} must be a positive protocol integer".format(name), field=name
            )

    as_of, as_of_value = normalize_carrier_timestamp(
        carrier["as_of"], "as_of", "invalid_as_of", "2.5"
    )
    horizons = {}
    for name in ("comments_complete_through", "timeline_complete_through"):
        value, parsed = normalize_carrier_timestamp(carrier[name], name)
        if parsed < as_of_value:
            fail_validation(
                "incomplete_trusted_context", "2.2, 2.5",
                "{} must be at or after as_of".format(name), field=name
            )
        horizons[name] = value

    policy = carrier["authority_policy"]
    if not isinstance(policy, dict) or set(policy) != {
        "profile", "reducer_principals"
    }:
        fail_validation(
            "invalid_bundle", "1.6, 2.5",
            "authority_policy must contain only profile and reducer_principals",
            field="authority_policy",
        )
    if (
        not isinstance(policy["profile"], str)
        or policy["profile"] not in AUTHORITY_PROFILES
    ):
        fail_validation(
            "invalid_bundle", "1.6, 2.5",
            "authority profile is not supported", field="authority_policy"
        )
    principals = policy["reducer_principals"]
    if (
        not isinstance(principals, list)
        or not principals
        or any(not is_positive_protocol_integer(value) for value in principals)
        or len(principals) != len(set(principals))
    ):
        fail_validation(
            "invalid_bundle", "1.6, 2.5",
            "reducer_principals must be non-empty unique positive integers",
            field="authority_policy",
        )

    events = carrier["ordered_events"]
    if not isinstance(events, list):
        fail_validation(
            "invalid_bundle", "2.4, 2.5", "ordered_events must be a list",
            field="ordered_events",
        )
    normalized_events = []
    previous_created = None
    previous_comment_key = None
    for index, event in enumerate(events):
        normalized, created = normalize_replay_event(event, index, as_of_value)
        if previous_created is not None and created < previous_created:
            fail_validation(
                "event_order_invalid", "2.4",
                "ordered event {} precedes the prior event timestamp".format(index),
                field="ordered_events",
            )
        previous_created = created
        if normalized["kind"] == "comment":
            comment_key = (created, normalized["comment_id"])
            if previous_comment_key is not None and comment_key < previous_comment_key:
                fail_validation(
                    "event_order_invalid", "2.4",
                    "comment events are not in created_at/comment_id order",
                    comment_id=normalized["comment_id"],
                )
            previous_comment_key = comment_key
        normalized_events.append(normalized)

    return {
        "open_table": 0,
        "repository_id": carrier["repository_id"],
        "issue_number": carrier["issue_number"],
        "as_of": as_of,
        "comments_complete_through": horizons["comments_complete_through"],
        "timeline_complete_through": horizons["timeline_complete_through"],
        "authority_policy": {
            "profile": policy["profile"],
            "reducer_principals": list(principals),
        },
        "ordered_events": normalized_events,
    }


def serialize_replay_carrier(carrier):
    """Return canonical bytes for one validated replay carrier."""
    return canonical_json_bytes(normalize_replay_carrier(carrier))


def normalize_decision_request(request):
    """Validate B1 decision-request syntax without making a decision."""
    if not isinstance(request, dict) or set(request) != DECISION_REQUEST_FIELDS:
        fail_validation(
            "invalid_bundle", "2.5, 9.1",
            "decision request must contain exactly the approved fields"
        )
    if request["open_table"] != 0 or isinstance(request["open_table"], bool):
        fail_validation(
            "unsupported_version", "11.1",
            "decision request open_table must be the integer 0", field="open_table"
        )
    replay = normalize_replay_carrier(request["replay"])
    source_comment_id = request["source_comment_id"]
    if not is_positive_protocol_integer(source_comment_id):
        fail_validation(
            "invalid_bundle", "2.5, 9.1",
            "source_comment_id must be a positive protocol integer",
            field="source_comment_id",
        )
    sources = {
        event["comment_id"]: event
        for event in replay["ordered_events"]
        if event["kind"] == "comment"
    }
    source = sources.get(source_comment_id)
    if source is None:
        fail_validation(
            "invalid_bundle", "2.5, 9.1",
            "source_comment_id must name a replay comment",
            field="source_comment_id",
        )

    permission = request["permission_observation"]
    if permission is not None:
        if not isinstance(permission, dict) or set(permission) != {
            "actor_id", "observed_at", "allowed"
        }:
            fail_validation(
                "invalid_bundle", "1.4, 1.5, 2.5",
                "permission_observation must use the closed approved shape",
                field="permission_observation",
            )
        observed_at, observed = normalize_carrier_timestamp(
            permission["observed_at"], "observed_at", "invalid_bundle", "1.5, 2.5"
        )
        _, as_of_value = normalize_carrier_timestamp(
            replay["as_of"], "as_of", "invalid_as_of", "2.5"
        )
        if (
            not is_positive_protocol_integer(permission["actor_id"])
            or permission["actor_id"] != source["actor_id"]
            or isinstance(permission["allowed"], bool) is False
            or observed > as_of_value
        ):
            fail_validation(
                "invalid_bundle", "1.4, 1.5, 2.5",
                "permission observation must bind the source actor before as_of",
                field="permission_observation",
            )
        permission = {
            "actor_id": permission["actor_id"],
            "observed_at": observed_at,
            "allowed": permission["allowed"],
        }

    outcome = request["profile_outcome"]
    if outcome is not None:
        if not isinstance(outcome, dict) or set(outcome) != {"profile", "decision"}:
            fail_validation(
                "invalid_bundle", "1.6, 2.5",
                "profile_outcome must use the closed approved shape",
                field="profile_outcome",
            )
        if (
            not isinstance(outcome["profile"], str)
            or outcome["profile"] != replay["authority_policy"]["profile"]
            or not isinstance(outcome["decision"], str)
            or outcome["decision"] not in RULING_DECISIONS
        ):
            fail_validation(
                "invalid_bundle", "1.6, 2.5",
                "profile outcome must bind the authority profile and a ruling decision",
                field="profile_outcome",
            )
        outcome = {
            "profile": outcome["profile"],
            "decision": outcome["decision"],
        }

    return {
        "open_table": 0,
        "replay": replay,
        "source_comment_id": source_comment_id,
        "permission_observation": permission,
        "profile_outcome": outcome,
    }


def serialize_decision_request(request):
    """Return canonical bytes for one syntax-valid B1 decision request."""
    return canonical_json_bytes(normalize_decision_request(request))


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
            actor_id in allowed_reducer_principals and bool(OPENING_RE.match(body))
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

        if unauthorized_reducer_shape:
            message_shape = sorted(reducer_output_shapes)[0]
            notices.append(
                "excluded {}-shaped comment {} from unauthorized actor {}; "
                "treated as prose".format(message_shape, comment_id, actor_id)
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
