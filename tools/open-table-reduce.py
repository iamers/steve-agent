#!/usr/bin/env python3
"""Reduce an Open Table v0 session using the deliberation-only profile.

The pure ``reduce_session`` entry point maps a replay bundle and an explicit
``as_of`` timestamp to a JSON-serializable plan of issue writes. The GitHub
adapter builds that bundle from authenticated API responses and applies the
plan. This deployment deliberately has no creation receipts or deletion
history and therefore never claims reducer conformance.

Replay bundle shape (this is not the section 2.8 integrity-bundle schema):

- ``repository``: ``owner/name``
- ``issue``: number, body, state, html_url, and labels
- ``authority_policy``: profile and reducer_principals
- ``ordered_events``: current comment inventory with trusted GitHub metadata;
  each event carries actor_id, actor_login, comment_id, created_at, updated_at,
  last_edited_at, body, html_url, and optional permission for a new ruling
- optional ``unreplayable_reason`` supplied by an adapter-observed deletion
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


START_MARKER = "<!-- open-table:start -->"
END_MARKER = "<!-- open-table:end -->"
PROFILE = "deliberation-only"
VALIDATOR = Path(__file__).with_name("open-table-validate.py")
VALIDATOR_PREFLIGHT_BODY = "\n".join([
    "```open-table",
    "open-table: 0",
    "message: contribution",
    "id: validator-preflight-0001",
    "phase: preflight",
    "turn: 1",
    "```",
    "",
    "Reducer validator toolchain preflight.",
])
_VALIDATOR_PREFLIGHT_SIGNATURE = None
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
OPEN_TABLE_RE = re.compile(r"\A(?:[ \t]*\r?\n)* {0,3}```open-table[ \t]*\r?\n")
CLOSING_RE = re.compile(r"^ {0,3}```[ \t]*(?:\r\n|\n)", re.MULTILINE)
RULING_REQUIRED = {
    "configuration", "settled", "claim", "renewal", "release", "handoff",
    "cancellation", "result", "review-request", "verdict",
}
DELIBERATION_MESSAGES = {"contribution", "proposal", "settled"}
# Section 2.3: only a reducer principal may author these. This deployment does
# not yet write a manifest, but a manifest-shaped comment from a participant is
# already reducer-shaped prose and section 7.5 requires excluding it.
REDUCER_OUTPUT_MESSAGES = {"ruling", "expiration", "manifest"}
WRITE_PERMISSIONS = {"admin", "maintain", "write"}


class ReductionError(ValueError):
    """A fail-closed replay or adapter failure."""


def canonical_digest(body):
    """Return the section 3.7 digest for a complete comment body."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def parse_timestamp(value, field):
    """Parse the protocol's exact UTC timestamp form."""
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise ReductionError("{} must use the exact RFC 3339 UTC form".format(field))
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ReductionError("{} is not a real UTC date and time".format(field)) from error


def validate_comment(body):
    """Use the reference validator's single-comment stdin mode."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        input=body.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReductionError(detail or "single-comment validation failed")


def verify_validator_toolchain():
    """Prove the deployed validator can accept a known-valid envelope once."""
    global _VALIDATOR_PREFLIGHT_SIGNATURE
    signature = (sys.executable, str(VALIDATOR))
    if _VALIDATOR_PREFLIGHT_SIGNATURE == signature:
        return
    try:
        validate_comment(VALIDATOR_PREFLIGHT_BODY)
    except (OSError, ReductionError) as error:
        raise ReductionError(
            "validator toolchain preflight failed: {}".format(error)
        ) from error
    _VALIDATOR_PREFLIGHT_SIGNATURE = signature


def extract_header(body):
    """Extract an already validated envelope header without participant prose."""
    opening = OPEN_TABLE_RE.match(body)
    if opening is None:
        raise ReductionError("validated comment has no Open Table opening fence")
    closing = CLOSING_RE.search(body, opening.end())
    if closing is None:
        raise ReductionError("validated comment has no closing fence")
    header = {}
    header_text = body[opening.end():closing.start()].replace("\r\n", "\n")
    for line in header_text.rstrip("\n").split("\n"):
        key, value = line.split(": ", 1)
        header[key] = value
    return header


def is_open_table_candidate(body):
    return isinstance(body, str) and OPEN_TABLE_RE.match(body) is not None


def recover_message_id(body):
    """Return one unambiguous valid id value from a malformed leading block."""
    opening = OPEN_TABLE_RE.match(body)
    if opening is None:
        return None
    closing = CLOSING_RE.search(body, opening.end())
    header_end = closing.start() if closing else len(body)
    candidates = {
        line[4:]
        for line in body[opening.end():header_end].replace("\r\n", "\n").split("\n")
        if line.startswith("id: ") and ID_RE.fullmatch(line[4:])
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def is_write_permission(permission):
    return permission in WRITE_PERMISSIONS


def event_order(event):
    return (event["created_at"], event["comment_id"])


def permalink(event):
    return event["html_url"]


def ruling_body(source, decision, reason):
    """Build a deterministic ruling containing only protocol data and rationale."""
    header = source["header"]
    digest = source["digest"]
    ruling_id = "ruling-{}-{}".format(source["comment_id"], digest.split(":", 1)[1][:16])
    return "\n".join([
        "```open-table",
        "open-table: 0",
        "message: ruling",
        "id: {}".format(ruling_id),
        "target-actor-id: {}".format(source["actor_id"]),
        "message-id: {}".format(header["id"]),
        "source-comment-id: {}".format(source["comment_id"]),
        "source-digest: {}".format(digest),
        "decision: {}".format(decision),
        "```",
        "",
        reason,
    ])


def replace_projection(issue_body, projection):
    """Replace only the section 9.2 marker region, preserving all other bytes."""
    body = issue_body or ""
    start_count = body.count(START_MARKER)
    end_count = body.count(END_MARKER)
    replacement = START_MARKER + "\n" + projection + "\n" + END_MARKER
    if start_count == 0 and end_count == 0:
        separator = "" if not body or body.endswith("\n") else "\n"
        return body + separator + replacement
    if start_count != 1 or end_count != 1:
        raise ReductionError("projection markers are missing, duplicated, or unbalanced")
    start = body.index(START_MARKER)
    end = body.index(END_MARKER)
    if end < start:
        raise ReductionError("projection end marker precedes its start marker")
    return body[:start] + replacement + body[end + len(END_MARKER):]


def render_projection(status, phase, turn, settled, proposals, notices):
    """Render identifiers, dispositions, and permalinks without participant prose."""
    lines = [
        "## Open Table projection",
        "",
        "**Not reducer-conformant.** This deployment has no authenticated creation "
        "receipts and no deletion evidence, so this session is not fully replayable.",
        "",
        "- Protocol version: `0`",
        "- Session status: `{}`".format(status),
        "- Current phase: `{}`".format(phase),
        "- Current turn: `{}`".format(turn),
        "",
        "### Settled points",
    ]
    if settled:
        for point in sorted(settled):
            item = settled[point]
            lines.append("- `{}`: `{}` ([comment]({}))".format(
                point, item["disposition"], item["permalink"]
            ))
    else:
        lines.append("- None")
    lines.extend(["", "### Open proposals"])
    open_points = [point for point in sorted(proposals) if point not in settled]
    if open_points:
        for point in open_points:
            lines.append("- `{}` ([comment]({}))".format(point, proposals[point]))
    else:
        lines.append("- None")
    lines.extend(["", "### Invalid or duplicate messages"])
    if notices:
        for notice in notices:
            lines.append("- [Comment {}]({}): {}".format(
                notice["comment_id"], notice["permalink"], notice["reason"]
            ))
    else:
        lines.append("- None")
    return "\n".join(lines)


def render_unreplayable_projection(reason):
    return "\n".join([
        "## Open Table projection",
        "",
        "**Session unreplayable.** {}".format(reason),
        "",
        "**Not reducer-conformant.** This deployment has no authenticated creation "
        "receipts and no deletion evidence.",
    ])


def fail_plan(bundle, reason, comments=None):
    """Plan the visible fail-closed projection before making the Action fail."""
    issue = bundle.get("issue", {})
    writes = []
    try:
        body = replace_projection(issue.get("body", ""), render_unreplayable_projection(reason))
        if body != issue.get("body", ""):
            writes.append({"operation": "update_issue_body", "body": body})
    except ReductionError:
        pass
    return {
        "profile": PROFILE,
        "as_of": bundle.get("as_of"),
        "unreplayable": True,
        "reason": reason,
        "writes": writes,
        "notices": comments or [],
    }


def validate_bundle_shape(bundle, as_of):
    if not isinstance(bundle, dict):
        raise ReductionError("replay bundle must be a JSON object")
    parse_timestamp(as_of, "as_of")
    issue = bundle.get("issue")
    policy = bundle.get("authority_policy")
    events = bundle.get("ordered_events")
    if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
        raise ReductionError("bundle issue must contain a numeric issue number")
    if not isinstance(issue.get("body", ""), str):
        raise ReductionError("bundle issue body must be a string")
    if issue.get("state") not in {"open", "closed"}:
        raise ReductionError("bundle issue state must be open or closed")
    if not isinstance(policy, dict) or policy.get("profile") != PROFILE:
        raise ReductionError("authority policy must select deliberation-only")
    principals = policy.get("reducer_principals")
    if not isinstance(principals, list) or not principals or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in principals
    ):
        raise ReductionError("authority policy needs positive numeric reducer principals")
    if len(principals) != len(set(principals)):
        raise ReductionError("authority policy reducer principals must be unique")
    if not isinstance(events, list):
        raise ReductionError("ordered_events must be a list")


def normalize_events(bundle):
    """Validate trusted metadata, edit signals, ordering, envelopes, and retries."""
    principals = set(bundle["authority_policy"]["reducer_principals"])
    parsed = []
    notices = []
    seen_comment_ids = set()
    seen_keys = {}
    previous = None
    required = {
        "actor_id", "actor_login", "comment_id", "created_at", "updated_at",
        "last_edited_at", "body", "html_url",
    }
    for index, event in enumerate(bundle["ordered_events"], 1):
        if not isinstance(event, dict) or not required.issubset(event):
            raise ReductionError("event {} is missing trusted comment metadata".format(index))
        if any(
            isinstance(event[name], bool) or not isinstance(event[name], int) or event[name] < 1
            for name in ("actor_id", "comment_id")
        ):
            raise ReductionError("event {} has an invalid numeric GitHub id".format(index))
        if event["comment_id"] in seen_comment_ids:
            raise ReductionError("duplicate trusted comment id {}".format(event["comment_id"]))
        seen_comment_ids.add(event["comment_id"])
        parse_timestamp(event["created_at"], "created_at")
        parse_timestamp(event["updated_at"], "updated_at")
        if event["updated_at"] != event["created_at"]:
            raise ReductionError(
                "trusted comment {} was edited: updated_at differs from created_at".format(
                    event["comment_id"]
                )
            )
        if event["last_edited_at"] is not None:
            raise ReductionError(
                "trusted comment {} was edited: lastEditedAt is non-null".format(
                    event["comment_id"]
                )
            )
        order = event_order(event)
        if previous is not None and order < previous:
            raise ReductionError("ordered_events are not in trusted GitHub order")
        previous = order
        body = event["body"]
        if not isinstance(body, str):
            raise ReductionError("comment {} body is not text".format(event["comment_id"]))
        if not is_open_table_candidate(body):
            continue
        try:
            validate_comment(body)
            header = extract_header(body)
            digest = canonical_digest(body)
        except (ReductionError, UnicodeEncodeError) as error:
            if event["actor_id"] in principals:
                raise ReductionError(
                    "invalid authenticated reducer comment {}: {}".format(
                        event["comment_id"], error
                    )
                ) from error
            candidate_id = recover_message_id(body)
            if candidate_id is not None:
                key = (event["actor_id"], candidate_id)
                try:
                    invalid_digest = canonical_digest(body)
                except UnicodeEncodeError:
                    invalid_digest = None
                if key in seen_keys and (
                    invalid_digest is None or seen_keys[key] != invalid_digest
                ):
                    raise ReductionError(
                        "actor {} reused message id {} with a different digest".format(*key)
                    )
                seen_keys.setdefault(key, invalid_digest)
            notices.append({
                "comment_id": event["comment_id"],
                "permalink": permalink(event),
                "reason": "invalid Open Table envelope",
            })
            continue
        if header["message"] in REDUCER_OUTPUT_MESSAGES and event["actor_id"] not in principals:
            notices.append({
                "comment_id": event["comment_id"],
                "permalink": permalink(event),
                "reason": "unauthorized reducer-shaped message excluded as prose",
            })
            continue
        key = (event["actor_id"], header["id"])
        if key in seen_keys:
            if seen_keys[key] != digest:
                raise ReductionError(
                    "actor {} reused message id {} with a different digest".format(*key)
                )
            notices.append({
                "comment_id": event["comment_id"],
                "permalink": permalink(event),
                "reason": "exact duplicate",
            })
            continue
        seen_keys[key] = digest
        record = dict(event)
        record.update({"header": header, "digest": digest, "order": order})
        parsed.append(record)
    return parsed, notices


def collect_rulings(records, principals):
    """Bind authenticated rulings to present sources and reject duplicates."""
    sources = {record["comment_id"]: record for record in records}
    rulings = {}
    for record in records:
        header = record["header"]
        if header["message"] != "ruling":
            continue
        if record["actor_id"] not in principals:
            continue
        source_id = int(header["source-comment-id"])
        if source_id in rulings:
            raise ReductionError("multiple rulings exist for source comment {}".format(source_id))
        source = sources.get(source_id)
        if source is None:
            raise ReductionError(
                "ruling source comment {} is deleted or missing".format(source_id)
            )
        if source["order"] >= record["order"]:
            raise ReductionError("ruling precedes its source comment {}".format(source_id))
        if (
            int(header["target-actor-id"]) != source["actor_id"]
            or header["message-id"] != source["header"]["id"]
            or header["source-digest"] != source["digest"]
        ):
            raise ReductionError("ruling binding does not match source comment {}".format(source_id))
        if source["header"]["message"] not in RULING_REQUIRED:
            raise ReductionError("ruling targets a message family that does not accept rulings")
        source_message = source["header"]["message"]
        decision = header["decision"]
        allowed = (
            {"rejected", "invalidated"}
            if source_message == "claim"
            else {"authorized", "unauthorized", "invalidated"}
        )
        if decision not in allowed:
            raise ReductionError(
                "ruling decision is invalid for source comment {}".format(source_id)
            )
        rulings[source_id] = decision
    return rulings


def configuration_context(records, rulings):
    configurations = []
    deliberation_orders = [
        record["order"] for record in records
        if record["header"]["message"] in DELIBERATION_MESSAGES
    ]
    first_deliberation = min(deliberation_orders) if deliberation_orders else None
    for record in records:
        if record["header"]["message"] != "configuration":
            continue
        if rulings.get(record["comment_id"]) == "authorized":
            if first_deliberation is not None and record["order"] >= first_deliberation:
                raise ReductionError(
                    "authorized configuration follows a deliberation message"
                )
            configurations.append(record)
    configurations.sort(key=lambda record: int(record["header"]["sequence"]))
    if not configurations:
        return None
    sequences = [int(record["header"]["sequence"]) for record in configurations]
    phases = [record["header"]["phase"] for record in configurations]
    if sequences != list(range(1, len(configurations) + 1)) or len(phases) != len(set(phases)):
        raise ReductionError("authorized configurations are not unique and contiguous")
    if any(record["header"]["authority-profile"] != PROFILE for record in configurations):
        raise ReductionError("authorized configuration selects a different authority profile")
    return {
        record["header"]["phase"]: {
            "sequence": int(record["header"]["sequence"]),
            "expected_actors": {
                int(value) for value in record["header"]["expected-actors"].split(",")
            },
            "turn_limit": int(record["header"]["turn-limit"]),
        }
        for record in configurations
    }


def configuration_declarations_valid(records):
    """Check immutable configuration grammar before creating any ruling."""
    configurations = [
        record for record in records
        if record["header"]["message"] == "configuration"
    ]
    if not configurations:
        return True
    deliberation_orders = [
        record["order"] for record in records
        if record["header"]["message"] in DELIBERATION_MESSAGES
    ]
    first_deliberation = min(deliberation_orders) if deliberation_orders else None
    if first_deliberation is not None and any(
        record["order"] >= first_deliberation for record in configurations
    ):
        return False
    sequences = [int(record["header"]["sequence"]) for record in configurations]
    phases = [record["header"]["phase"] for record in configurations]
    return (
        sorted(sequences) == list(range(1, len(configurations) + 1))
        and len(sequences) == len(set(sequences))
        and len(phases) == len(set(phases))
        and all(
            record["header"]["authority-profile"] == PROFILE
            for record in configurations
        )
    )


def transition_is_valid(state, record, configuration):
    """Check one deliberation event without mutating the replay state."""
    header = record["header"]
    phase = header["phase"]
    turn = int(header["turn"])
    if configuration is not None:
        phase_config = configuration.get(phase)
        if (
            phase_config is None
            or record["actor_id"] not in phase_config["expected_actors"]
            or turn > phase_config["turn_limit"]
        ):
            return False, None
        sequence = phase_config["sequence"]
    else:
        sequence = None
    if state["phase"] is None:
        valid = sequence in {None, 1}
    elif phase == state["phase"]:
        valid = turn in {state["turn"], state["turn"] + 1}
    else:
        valid = turn == 1 and (
            configuration is None or sequence == state["sequence"] + 1
        )
    return valid, sequence


def scan_deliberation(records, rulings, configuration, stop_order=None, notices=None):
    """Replay valid deliberation events up to an optional ordered position."""
    state = {
        "phase": None,
        "turn": None,
        "sequence": None,
        "terminated": False,
        "proposals_by_comment": {},
        "proposals_by_point": {},
        "settled": {},
    }
    for record in records:
        if stop_order is not None and record["order"] >= stop_order:
            break
        header = record["header"]
        message = header["message"]
        if message not in DELIBERATION_MESSAGES:
            continue
        if state["terminated"]:
            if notices is not None:
                notices.append({
                    "comment_id": record["comment_id"],
                    "permalink": permalink(record),
                    "reason": "deliberation message follows terminal settlement",
                })
            continue
        if message == "settled":
            proposal = state["proposals_by_comment"].get(
                int(header["proposal-comment-id"])
            )
            if rulings.get(record["comment_id"]) != "authorized":
                if notices is not None:
                    notices.append({
                        "comment_id": record["comment_id"],
                        "permalink": permalink(record),
                        "reason": "settlement lacks an authorized ruling",
                    })
                continue
            if proposal is None or proposal["header"]["point"] != header["point"]:
                if notices is not None:
                    notices.append({
                        "comment_id": record["comment_id"],
                        "permalink": permalink(record),
                        "reason": "settlement proposal reference is invalid",
                    })
                continue
        valid_transition, sequence = transition_is_valid(state, record, configuration)
        if not valid_transition:
            if notices is not None:
                notices.append({
                    "comment_id": record["comment_id"],
                    "permalink": permalink(record),
                    "reason": "message violates configured context or phase/turn transition",
                })
            continue
        state["phase"] = header["phase"]
        state["turn"] = int(header["turn"])
        state["sequence"] = sequence
        if message == "proposal":
            state["proposals_by_comment"][record["comment_id"]] = record
            state["proposals_by_point"].setdefault(
                header["point"], permalink(record)
            )
        elif message == "settled":
            state["settled"].setdefault(header["point"], {
                "disposition": header["disposition"],
                "permalink": permalink(record),
            })
            if header["terminal"] == "true":
                state["terminated"] = True
    return state


def decision_for(record, records, rulings, configuration, configurations_valid):
    """Return a new ruling decision and public, non-sensitive rationale."""
    header = record["header"]
    message = header["message"]
    permission = record.get("permission")
    if message == "claim":
        return "rejected", (
            "Rejected because claims are advisory under the deliberation-only profile; "
            "no exclusive work right was awarded. Recorded permission: {}.".format(
                permission or "not-required"
            )
        )
    if message == "configuration":
        allowed = (
            is_write_permission(permission)
            and configurations_valid
        )
        return (
            "authorized" if allowed else "unauthorized",
            "Repository write access at first ruling: {}; authority profile: {} "
            "(permission: {}).".format(
                "confirmed" if is_write_permission(permission) else "not confirmed",
                "valid" if configurations_valid else "invalid",
                permission or "none",
            ),
        )
    if message == "settled":
        if configuration is None:
            return "unauthorized", (
                "Configuration-free mode has no authoritative settlement rulings."
            )
        state = scan_deliberation(
            records, rulings, configuration, stop_order=record["order"]
        )
        proposal_id = int(header["proposal-comment-id"])
        proposal = state["proposals_by_comment"].get(proposal_id)
        references_valid = (
            proposal is not None
            and proposal["header"]["point"] == header["point"]
            and proposal["order"] < record["order"]
        )
        transition_valid, _ = transition_is_valid(state, record, configuration)
        context_valid = not state["terminated"] and transition_valid
        allowed = (
            is_write_permission(permission) and references_valid and context_valid
        )
        return (
            "authorized" if allowed else "unauthorized",
            "Repository write access at first ruling: {}; proposal reference: {}; "
            "contextual predicate: {} (permission: {}).".format(
                "confirmed" if is_write_permission(permission) else "not confirmed",
                "valid" if references_valid else "invalid",
                "valid" if context_valid else "invalid",
                permission or "none",
            ),
        )
    return "unauthorized", (
        "The deliberation-only profile does not authorize this exclusive work operation. "
        "Recorded permission: {}.".format(permission or "not-required")
    )


def derive_deliberation(records, rulings, configuration, notices):
    """Derive section 9.2 values from valid deliberation messages."""
    state = scan_deliberation(records, rulings, configuration, notices=notices)
    current_phase = state["phase"]
    if current_phase is None:
        current_phase = "initial" if configuration is None else next(
            phase
            for phase, values in configuration.items()
            if values["sequence"] == 1
        )
    current_turn = state["turn"] or 1
    return (
        "terminated" if state["terminated"] else "open",
        current_phase,
        current_turn,
        state["settled"],
        state["proposals_by_point"],
    )


def reduce_session(bundle, as_of):
    """Purely map one replay bundle and explicit clock value to planned writes."""
    verify_validator_toolchain()
    bundle = json.loads(json.dumps(bundle))
    bundle["as_of"] = as_of
    try:
        validate_bundle_shape(bundle, as_of)
        if bundle.get("unreplayable_reason"):
            raise ReductionError(str(bundle["unreplayable_reason"]))
        records, notices = normalize_events(bundle)
        principals = set(bundle["authority_policy"]["reducer_principals"])
        rulings = collect_rulings(records, principals)

        active_configuration = configuration_context(records, rulings)
        configurations_valid = configuration_declarations_valid(records)
        ruling_writes = []
        for record in records:
            message = record["header"]["message"]
            if message not in RULING_REQUIRED or record["comment_id"] in rulings:
                continue
            if message != "configuration" and active_configuration is None:
                continue
            decision, reason = decision_for(
                record, records, rulings, active_configuration, configurations_valid
            )
            rulings[record["comment_id"]] = decision
            ruling_writes.append({
                "operation": "post_comment",
                "source_comment_id": record["comment_id"],
                "body": ruling_body(record, decision, reason),
            })
            if message == "configuration":
                active_configuration = configuration_context(records, rulings)

        configuration = configuration_context(records, rulings)
        if configuration is None:
            return {
                "profile": PROFILE,
                "as_of": as_of,
                "unreplayable": False,
                "writes": ruling_writes,
                "notices": notices,
            }
        status, phase, turn, settled, open_proposals = derive_deliberation(
            records, rulings, configuration, notices
        )
        projection = render_projection(
            status, phase, turn, settled, open_proposals, notices
        )
        new_body = replace_projection(bundle["issue"].get("body", ""), projection)
        writes = ruling_writes
        if new_body != bundle["issue"].get("body", ""):
            writes.append({"operation": "update_issue_body", "body": new_body})
        return {
            "profile": PROFILE,
            "as_of": as_of,
            "unreplayable": False,
            "writes": writes,
            "notices": notices,
        }
    except ReductionError as error:
        return fail_plan(bundle, str(error))


def github_request(url, token, method="GET", data=None):
    """Call GitHub's JSON API without external dependencies."""
    encoded = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", "Bearer {}".format(token))
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if encoded is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ReductionError("GitHub API {} {} failed: {} {}".format(
            method, url, error.code, detail
        )) from error


def paginated_rest(url, token):
    values = []
    page = 1
    while True:
        separator = "&" if "?" in url else "?"
        batch = github_request("{}{}per_page=100&page={}".format(url, separator, page), token)
        values.extend(batch)
        if len(batch) < 100:
            return values
        page += 1


def graphql_edit_metadata(repository, issue_number, token):
    owner, name = repository.split("/", 1)
    cursor = None
    result = {}
    while True:
        query = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      comments(first:100,after:$cursor) {
        nodes { databaseId lastEditedAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
        payload = github_request(
            "https://api.github.com/graphql", token, "POST",
            {"query": query, "variables": {
                "owner": owner, "name": name, "number": issue_number, "cursor": cursor,
            }},
        )
        if payload.get("errors"):
            raise ReductionError("GitHub GraphQL edit-metadata query failed")
        comments = payload["data"]["repository"]["issue"]["comments"]
        for node in comments["nodes"]:
            result[node["databaseId"]] = node["lastEditedAt"]
        if not comments["pageInfo"]["hasNextPage"]:
            return result
        cursor = comments["pageInfo"]["endCursor"]


def permission_for(repository, login, token):
    quoted = urllib.parse.quote(login, safe="")
    data = github_request(
        "https://api.github.com/repos/{}/collaborators/{}/permission".format(
            repository, quoted
        ), token,
    )
    return data.get("permission")


def trusted_last_edited_at(edits, comment_id):
    """Return authenticated edit metadata while rejecting inventory races."""
    if comment_id not in edits:
        raise ReductionError(
            "trusted lastEditedAt metadata is missing for comment {}".format(comment_id)
        )
    return edits[comment_id]


def load_event_context():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReductionError("cannot read GITHUB_EVENT_PATH: {}".format(error)) from error


def build_github_bundle(repository, issue_number, token, principal):
    """Read current issue state and trusted edit metadata from GitHub."""
    verify_validator_toolchain()
    base = "https://api.github.com/repos/{}".format(repository)
    issue = github_request("{}/issues/{}".format(base, issue_number), token)
    labels = [label["name"] for label in issue.get("labels", [])]
    if "open-table/session" not in labels:
        raise ReductionError("issue does not carry open-table/session")
    comments = paginated_rest("{}/issues/{}/comments".format(base, issue_number), token)
    edits = graphql_edit_metadata(repository, issue_number, token)
    event_context = load_event_context()
    unreplayable_reason = None
    if event_context.get("action") == "deleted":
        deleted = event_context.get("comment", {}).get("id")
        unreplayable_reason = "source comment {} was deleted or is missing".format(deleted)
    events = []
    for comment in comments:
        event = {
            "actor_id": comment["user"]["id"],
            "actor_login": comment["user"]["login"],
            "comment_id": comment["id"],
            "created_at": comment["created_at"],
            "updated_at": comment["updated_at"],
            "last_edited_at": trusted_last_edited_at(edits, comment["id"]),
            "body": comment.get("body") or "",
            "html_url": comment["html_url"],
        }
        events.append(event)
    events.sort(key=event_order)

    existing_ruling_sources = set()
    for event in events:
        if event["actor_id"] != principal or not is_open_table_candidate(event["body"]):
            continue
        try:
            validate_comment(event["body"])
            header = extract_header(event["body"])
        except ReductionError:
            continue
        if header.get("message") == "ruling":
            existing_ruling_sources.add(int(header["source-comment-id"]))
    for event in events:
        if event["comment_id"] in existing_ruling_sources:
            continue
        if not is_open_table_candidate(event["body"]):
            continue
        try:
            validate_comment(event["body"])
            header = extract_header(event["body"])
        except ReductionError:
            continue
        if header.get("message") in RULING_REQUIRED:
            event["permission"] = permission_for(repository, event["actor_login"], token)

    bundle = {
        "repository": repository,
        "issue": {
            "number": issue_number,
            "body": issue.get("body") or "",
            "state": issue["state"],
            "html_url": issue["html_url"],
            "labels": labels,
        },
        "authority_policy": {
            "profile": PROFILE,
            "reducer_principals": [principal],
        },
        "ordered_events": events,
    }
    if unreplayable_reason:
        bundle["unreplayable_reason"] = unreplayable_reason
    return bundle


def apply_plan(plan, repository, issue_number, token):
    base = "https://api.github.com/repos/{}/issues/{}".format(repository, issue_number)
    for write in plan["writes"]:
        if write["operation"] == "post_comment":
            github_request(base + "/comments", token, "POST", {"body": write["body"]})
        elif write["operation"] == "update_issue_body":
            github_request(base, token, "PATCH", {"body": write["body"]})
        else:
            raise ReductionError("unknown planned write operation")
    if plan["unreplayable"]:
        raise ReductionError(plan["reason"])


def fixture_bundle():
    """Return the offline fixture used by the self-test."""
    contribution = "\n".join([
        "```open-table", "open-table: 0", "message: contribution",
        "id: contribution-0001", "phase: initial", "turn: 1", "```", "",
        "Participant prose is deliberately absent from the projection.",
    ])
    proposal = "\n".join([
        "```open-table", "open-table: 0", "message: proposal",
        "id: proposal-scope-0001", "phase: initial", "turn: 1", "point: scope",
        "```", "", "A proposal containing private participant prose.",
    ])
    claim = "\n".join([
        "```open-table", "open-table: 0", "message: claim",
        "id: advisory-claim-0001", "expires-at: 2026-08-05T00:00:00Z", "```", "",
        "An advisory claim.",
    ])
    bodies = [contribution, proposal, claim]
    events = []
    for index, body in enumerate(bodies, 1):
        timestamp = "2026-08-04T00:00:0{}Z".format(index)
        events.append({
            "actor_id": 100 + index,
            "actor_login": "participant{}".format(index),
            "comment_id": 200 + index,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_edited_at": None,
            "body": body,
            "html_url": "https://example.invalid/issues/7#issuecomment-{}".format(200 + index),
            "permission": "read",
        })
    return {
        "repository": "example/project",
        "issue": {
            "number": 7,
            "body": "Human preface\n\nHuman suffix",
            "state": "open",
            "html_url": "https://example.invalid/issues/7",
            "labels": ["open-table/session", "unrelated"],
        },
        "authority_policy": {"profile": PROFILE, "reducer_principals": [41898282]},
        "ordered_events": events,
    }


def run_self_test():
    import shutil
    import tempfile

    global VALIDATOR
    bundle = fixture_bundle()
    as_of = "2026-08-04T01:00:00Z"
    verify_validator_toolchain()
    print("validator toolchain preflight: known-valid envelope accepted")

    invalid_participant = json.loads(json.dumps(bundle))
    invalid_participant["ordered_events"] = invalid_participant["ordered_events"][:1]
    invalid_participant["ordered_events"][0]["body"] = (
        invalid_participant["ordered_events"][0]["body"].replace(
            "open-table: 0", "open-table: 1"
        )
    )
    invalid_plan = reduce_session(invalid_participant, as_of)
    assert not invalid_plan["unreplayable"] and invalid_plan["writes"] == []
    assert len(invalid_plan["notices"]) == 1
    assert invalid_plan["notices"][0]["reason"] == "invalid Open Table envelope"
    print("invalid participant envelope: nonfatal notice retained")

    original_validator = VALIDATOR
    with tempfile.TemporaryDirectory() as directory:
        isolated_validator = Path(directory) / VALIDATOR.name
        shutil.copyfile(VALIDATOR, isolated_validator)
        try:
            VALIDATOR = isolated_validator
            reduce_session(bundle, as_of)
        except ReductionError as error:
            assert "validator toolchain preflight failed" in str(error)
            assert "open_table_core" in str(error)
        else:
            raise AssertionError("a missing validator dependency was accepted")
        finally:
            VALIDATOR = original_validator
    print("missing validator dependency: fatal before reduction or planned writes")

    first = reduce_session(bundle, as_of)
    second = reduce_session(bundle, as_of)
    assert first == second and not first["unreplayable"]
    assert first["writes"] == []
    print("configuration-free session: no rulings or reducer projection")

    edited_bundle = json.loads(json.dumps(bundle))
    edited_bundle["ordered_events"][0]["last_edited_at"] = "2026-08-04T00:30:00Z"
    failed = reduce_session(edited_bundle, as_of)
    assert failed["unreplayable"] and "edited" in failed["reason"]
    assert failed["writes"] and "Session unreplayable" in failed["writes"][0]["body"]
    print("edit signal fail-closed projection: ok")

    malformed_repost = json.loads(json.dumps(bundle))
    malformed_repost["ordered_events"] = malformed_repost["ordered_events"][:2]
    malformed_repost["ordered_events"][0]["body"] = "\n".join([
        "```open-table", "open-table: 0", "message: proposal",
        "id: reserved-message-0001", "phase: initial", "turn: 1",
        "point: decision", "```",
    ])
    malformed_repost["ordered_events"][1]["actor_id"] = (
        malformed_repost["ordered_events"][0]["actor_id"]
    )
    malformed_repost["ordered_events"][1]["body"] = (
        malformed_repost["ordered_events"][0]["body"] + "\n\nLater valid repost."
    )
    repost = reduce_session(malformed_repost, as_of)
    assert repost["unreplayable"] and "reused message id" in repost["reason"]
    print("invalid earliest envelope reserves its recoverable actor/message-id key")

    participant_manifest = json.loads(json.dumps(bundle))
    participant_manifest["ordered_events"] = participant_manifest["ordered_events"][:1]
    participant_manifest["ordered_events"][0]["body"] = "\n".join([
        "```open-table", "open-table: 0", "message: manifest",
        "id: forged-manifest-0001", "deletions-accounted: 99",
        "entries: 201/sha256:{}/contribution".format("a" * 64), "```", "",
        "A participant claiming to be the reducer's memory.",
    ])
    forged = reduce_session(participant_manifest, as_of)
    assert not forged["unreplayable"] and forged["writes"] == []
    assert len(forged["notices"]) == 1
    assert forged["notices"][0]["reason"] == (
        "unauthorized reducer-shaped message excluded as prose"
    )
    print("participant-authored manifest: excluded as prose, not read as memory")

    assert trusted_last_edited_at({201: None}, 201) is None
    try:
        trusted_last_edited_at({}, 201)
    except ReductionError as error:
        assert "metadata is missing" in str(error)
    else:
        raise AssertionError("missing GraphQL edit metadata was accepted")
    print("GraphQL edit metadata: authenticated null accepted, absent entry rejected")

    configured = fixture_bundle()
    configured["ordered_events"] = []
    configured_prefix = "Configured preface bytes.\n\n"
    configured_suffix = "\n\nConfigured suffix bytes."
    configured_prose = "Distinctive configured participant prose."
    configured["issue"]["body"] = (
        configured_prefix + START_MARKER + "\nStale projection bytes.\n"
        + END_MARKER + configured_suffix
    )
    configured_bodies = [
        "\n".join([
            "```open-table", "open-table: 0", "message: configuration",
            "id: configuration-observation-0001", "phase: observation", "sequence: 1",
            "expected-actors: 101", "authority-profile: deliberation-only",
            "turn-limit: 2", "```", "", "Configuration.",
        ]),
        "\n".join([
            "```open-table", "open-table: 0", "message: configuration",
            "id: configuration-synthesis-0001", "phase: synthesis", "sequence: 2",
            "expected-actors: 101", "authority-profile: deliberation-only",
            "turn-limit: 2", "```", "", "Configuration.",
        ]),
        "\n".join([
            "```open-table", "open-table: 0", "message: contribution",
            "id: observation-contribution-0001", "phase: observation", "turn: 1",
            "```", "", "Observation.",
        ]),
        "\n".join([
            "```open-table", "open-table: 0", "message: proposal",
            "id: configured-proposal-0001", "phase: synthesis", "turn: 1",
            "point: decision", "```", "", configured_prose,
        ]),
        "\n".join([
            "```open-table", "open-table: 0", "message: claim",
            "id: configured-claim-0001", "expires-at: 2026-08-05T00:00:00Z",
            "```", "", "Configured advisory claim.",
        ]),
        "\n".join([
            "```open-table", "open-table: 0", "message: settled",
            "id: configured-settled-0001", "phase: synthesis", "turn: 1",
            "point: decision", "proposal-comment-id: 304",
            "disposition: accepted", "terminal: true", "```", "", "Settlement.",
        ]),
    ]
    for offset, body in enumerate(configured_bodies, 1):
        timestamp = "2026-08-04T00:10:0{}Z".format(offset)
        configured["ordered_events"].append({
            "actor_id": 101,
            "actor_login": "writer",
            "comment_id": 300 + offset,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_edited_at": None,
            "body": body,
            "html_url": "https://example.invalid/issues/7#issuecomment-{}".format(
                300 + offset
            ),
            "permission": "write",
        })

    configured_waiting = json.loads(json.dumps(configured))
    configured_waiting["ordered_events"] = configured_waiting["ordered_events"][:2]
    waiting_plan = reduce_session(configured_waiting, as_of)
    waiting_projection = [
        write["body"] for write in waiting_plan["writes"]
        if write["operation"] == "update_issue_body"
    ][0]
    assert "Session status: `open`" in waiting_projection
    assert "Current phase: `observation`" in waiting_projection
    assert "Current turn: `1`" in waiting_projection
    print("configured session before deliberation: first configured phase, turn 1")

    configured_plan = reduce_session(configured, as_of)
    configured_comments = [
        write["body"] for write in configured_plan["writes"]
        if write["operation"] == "post_comment"
    ]
    configured_authorized = [
        write["body"] for write in configured_plan["writes"]
        if write.get("source_comment_id") in {301, 302, 306}
    ]
    claim_rulings = [
        write["body"] for write in configured_plan["writes"]
        if write.get("source_comment_id") == 305
    ]
    assert len(configured_comments) == 4
    assert len(configured_authorized) == 3
    assert all("decision: authorized" in body for body in configured_authorized)
    assert all("permission: write" in body for body in configured_authorized)
    assert len(claim_rulings) == 1
    assert "decision: rejected" in claim_rulings[0]
    assert "claims are advisory" in claim_rulings[0]
    print("configured advisory claim ruling: rejected and recorded as advisory")
    configured_projection = [
        write["body"] for write in configured_plan["writes"]
        if write["operation"] == "update_issue_body"
    ][0]
    assert "Session status: `terminated`" in configured_projection
    assert "Current phase: `synthesis`" in configured_projection
    assert "Current turn: `1`" in configured_projection
    assert "`decision`: `accepted`" in configured_projection
    assert (
        any(configured_prose in event["body"] for event in configured["ordered_events"])
        and configured_prose not in configured_projection
    )
    print("configured projection participant prose exclusion: ok")
    print("configured phase transition and terminal settlement: ok")
    projection_prefix, _, after_start = configured_projection.partition(START_MARKER)
    _, _, projection_suffix = after_start.partition(END_MARKER)
    assert projection_prefix == configured_prefix and projection_suffix == configured_suffix
    print("configured projection marker preservation: exact surrounding bytes retained")
    print("configuration and settlement write-access rulings: recorded and authorized")

    no_configuration = json.loads(json.dumps(configured))
    no_configuration["ordered_events"] = no_configuration["ordered_events"][2:]
    no_configuration_plan = reduce_session(no_configuration, as_of)
    assert not no_configuration_plan["unreplayable"]
    assert no_configuration_plan["writes"] == []
    configuration_free_state = derive_deliberation([], {}, None, [])
    assert configuration_free_state[:3] == ("open", "initial", 1)
    print("configuration-free settlement: no ruling, termination, or projection")
    print("configuration-free initial state: phase initial, turn 1")

    ruled_bundle = json.loads(json.dumps(configured))
    for offset, ruling in enumerate(configured_comments, 7):
        timestamp = "2026-08-04T00:10:{:02d}Z".format(offset)
        ruled_bundle["ordered_events"].append({
            "actor_id": 41898282,
            "actor_login": "github-actions[bot]",
            "comment_id": 300 + offset,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_edited_at": None,
            "body": ruling,
            "html_url": "https://example.invalid/issues/7#issuecomment-{}".format(
                300 + offset
            ),
        })
    replay = reduce_session(ruled_bundle, as_of)
    assert not any(write["operation"] == "post_comment" for write in replay["writes"])
    print("existing ruling search: duplicate append suppressed")

    missing_bundle = json.loads(json.dumps(ruled_bundle))
    missing_bundle["ordered_events"] = [
        event for event in missing_bundle["ordered_events"]
        if event["comment_id"] != 306
    ]
    missing = reduce_session(missing_bundle, as_of)
    assert missing["unreplayable"] and "deleted or missing" in missing["reason"]
    print("missing ruling source fails closed: ok")

    invalid_proposal = json.loads(json.dumps(configured))
    invalid_proposal["ordered_events"][3]["body"] = (
        invalid_proposal["ordered_events"][3]["body"].replace("turn: 1", "turn: 3")
    )
    invalid_plan = reduce_session(invalid_proposal, as_of)
    invalid_rulings = [
        write["body"] for write in invalid_plan["writes"]
        if write["operation"] == "post_comment"
    ]
    assert "decision: unauthorized" in invalid_rulings[-1]
    invalid_projection = [
        write["body"] for write in invalid_plan["writes"]
        if write["operation"] == "update_issue_body"
    ][0]
    assert "Session status: `open`" in invalid_projection
    assert "`decision`: `accepted`" not in invalid_projection
    print("contextually invalid proposal cannot authorize settlement: ok")

    late_configuration = json.loads(json.dumps(configured))
    late_configuration["ordered_events"] = [
        late_configuration["ordered_events"][3],
        late_configuration["ordered_events"][0],
    ]
    late_configuration["ordered_events"][0]["created_at"] = "2026-08-04T00:10:01Z"
    late_configuration["ordered_events"][0]["updated_at"] = "2026-08-04T00:10:01Z"
    late_configuration["ordered_events"][1]["created_at"] = "2026-08-04T00:10:02Z"
    late_configuration["ordered_events"][1]["updated_at"] = "2026-08-04T00:10:02Z"
    late_plan = reduce_session(late_configuration, as_of)
    late_rulings = [
        write["body"] for write in late_plan["writes"]
        if write["operation"] == "post_comment"
    ]
    assert len(late_rulings) == 1 and "decision: unauthorized" in late_rulings[0]
    print("configuration after deliberation cannot govern retroactively: ok")
    print("self-test: configured projection, idempotency, metadata, and fail-closed paths passed")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run offline assertions")
    parser.add_argument("--dry-run", action="store_true", help="print a write plan")
    parser.add_argument("--bundle", help="replay bundle JSON path")
    parser.add_argument("--as-of", help="explicit RFC 3339 UTC reduction timestamp")
    parser.add_argument("--github", action="store_true", help="read and write through GitHub APIs")
    parser.add_argument("--repository", help="GitHub owner/repository")
    parser.add_argument("--issue", type=int, help="GitHub issue number")
    parser.add_argument("--principal", type=int, help="numeric reducer principal")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        if any((args.dry_run, args.bundle, args.github)):
            print("error: --self-test does not accept another mode", file=sys.stderr)
            return 2
        run_self_test()
        return 0
    if args.dry_run:
        if not args.bundle or args.github:
            print("error: --dry-run requires --bundle and excludes --github", file=sys.stderr)
            return 2
        try:
            bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
            as_of = args.as_of or bundle.get("as_of")
            if not as_of:
                raise ReductionError("dry-run requires --as-of or bundle as_of")
            plan = reduce_session(bundle, as_of)
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 1 if plan["unreplayable"] else 0
        except (OSError, json.JSONDecodeError, ReductionError) as error:
            print("error: {}".format(error), file=sys.stderr)
            return 2
    if args.github:
        repository = args.repository or os.environ.get("GITHUB_REPOSITORY")
        token = os.environ.get("GITHUB_TOKEN")
        principal = args.principal
        event = load_event_context()
        issue_number = args.issue or event.get("issue", {}).get("number")
        if not repository or not token or not issue_number or not principal:
            print("error: GitHub mode needs repository, issue, token, and principal", file=sys.stderr)
            return 2
        try:
            as_of = args.as_of or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            bundle = build_github_bundle(repository, issue_number, token, principal)
            plan = reduce_session(bundle, as_of)
            apply_plan(plan, repository, issue_number, token)
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0
        except ReductionError as error:
            print("error: {}".format(error), file=sys.stderr)
            return 1
    print("error: choose --self-test, --dry-run, or --github", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
