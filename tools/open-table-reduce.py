#!/usr/bin/env python3
"""Reduce an Open Table v0 session using the deliberation-only profile.

The pure ``reduce_session`` entry point maps a replay bundle and an explicit
``as_of`` timestamp to a JSON-serializable plan of issue writes. The GitHub
adapter builds that bundle from authenticated API responses and applies the
plan. The detection mechanism section 2.3 selects, the `manifest` family of
section 4.18, is implemented here; the deployment obligation of a periodic
timeline read is not deployed yet, so this deployment still claims no reducer
conformance.

Replay bundle shape (this is not the section 2.8 integrity-bundle schema):

- ``repository``: ``owner/name``
- ``issue``: number, body, state, html_url, and labels
- ``authority_policy``: profile and reducer_principals
- ``ordered_events``: current comment inventory with trusted GitHub metadata;
  each event carries actor_id, actor_login, comment_id, created_at, updated_at,
  last_edited_at, body, html_url, and optional permission for a new ruling
- optional ``deletions_observed``: the count of comment-deletion events in the
  issue timeline. Present when the adapter read the timeline; a replay bundle
  always carries it. The watermark is a count rather than a cursor, which is
  the choice the mechanism's record left to this implementation
- optional ``unreplayable_reason`` declared by an adapter
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
# Section 2.3 fixes the domain the reducer's memory must cover: every family
# requiring a ruling under 4.17 and every deliberation message under 4.2. The
# rulings the reducer appended are remembered inside their source's entry.
DOMAIN_MESSAGES = RULING_REQUIRED | DELIBERATION_MESSAGES
# Section 2.3: only a reducer principal may author these. A manifest-shaped
# comment from a participant is reducer-shaped prose and section 7.5 requires
# excluding it.
REDUCER_OUTPUT_MESSAGES = {"ruling", "expiration", "manifest"}
WRITE_PERMISSIONS = {"admin", "maintain", "write"}
# Section 4.18 requires a manifest too large for one comment to be split across
# several, each complete and carrying the same deletions-accounted. GitHub's own
# comment limit is 65536 characters; the headroom is deliberate.
MANIFEST_BODY_LIMIT = 60000
# Section 3.6 caps a count at twenty decimal digits, and the watermark this
# reducer reads is a count it writes back into a manifest.
MAX_PROTOCOL_COUNT = 10 ** 20 - 1
# Issue #173: the surface that carries a fail-closed diagnosis when the reducer
# cannot write it into the issue body, because the marker region it would write
# into is the region it cannot parse.
REDUCTION_FAILED_LABEL = "open-table/reduction-failed"


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


def render_projection(status, phase, turn, settled, proposals, notices, detection):
    """Render identifiers, dispositions, and permalinks without participant prose."""
    lines = [
        "## Open Table projection",
        "",
        "**Not reducer-conformant.** The detection mechanism of section 2.3 is "
        "implemented, but this deployment does not yet read the issue timeline "
        "periodically as that section requires of an adapter.",
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
    lines.extend(["", "### Detection notices"])
    if detection:
        for notice in detection:
            if notice["comment_id"] is None:
                lines.append("- [This issue]({}): {}".format(
                    notice["permalink"], notice["detail"]
                ))
            else:
                lines.append("- [Comment {}]({}): {}".format(
                    notice["comment_id"], notice["permalink"], notice["detail"]
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
        "**Not reducer-conformant.** This deployment does not yet read the issue "
        "timeline periodically as section 2.3 requires of an adapter.",
    ])


def label_plan(bundle, diagnosis_is_invisible):
    """Keep the issue #173 label in step with whether a diagnosis reached the body.

    The label means exactly one thing: the last reduction failed somewhere its
    notice could not be written into the issue. It is applied when that happens
    and removed as soon as it stops being true, so a stale label cannot outlive
    the failure it describes.
    """
    labels = (bundle.get("issue") or {}).get("labels") or []
    if diagnosis_is_invisible and REDUCTION_FAILED_LABEL not in labels:
        return [{"operation": "add_label", "label": REDUCTION_FAILED_LABEL}]
    if not diagnosis_is_invisible and REDUCTION_FAILED_LABEL in labels:
        return [{"operation": "remove_label", "label": REDUCTION_FAILED_LABEL}]
    return []


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
    writes.extend(label_plan(bundle, diagnosis_is_invisible=not writes))
    return {
        "profile": PROFILE,
        "as_of": bundle.get("as_of"),
        "unreplayable": True,
        "reason": reason,
        "writes": writes,
        "notices": comments or [],
        "detection": [],
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
    observed = bundle.get("deletions_observed")
    # The upper bound is not decoration: the watermark is written back into a
    # manifest, and section 3.6 caps a count at twenty decimal digits. Accepting
    # a larger one would make the reducer post a comment its own reference
    # validator rejects, and the next run would then read its own output as an
    # invalid authenticated reducer comment.
    if observed is not None and (
        isinstance(observed, bool)
        or not isinstance(observed, int)
        or not 0 <= observed <= MAX_PROTOCOL_COUNT
    ):
        raise ReductionError(
            "deletions_observed must be a count of at least 0 and at most twenty digits"
        )


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
        # Section 2.5 keeps updated_at and lastEditedAt auxiliary: they are
        # validated and nothing rests on them. Detection is the digest
        # comparison against the section 4.18 manifest, and the blanket
        # trip-wire that used to stand here is issue #144.
        if event["last_edited_at"] is not None:
            parse_timestamp(event["last_edited_at"], "last_edited_at")
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
    """Bind authenticated rulings to present sources and report the ones that no longer bind.

    A ruling is a pin under section 7.3, so a ruling whose source is gone or
    whose source no longer matches the digest it pinned is evidence of a
    mutation rather than a reason to fail the whole session. Those are returned
    as unbound facts and fail closed scoped to the state that depended on them.
    """
    sources = {record["comment_id"]: record for record in records}
    rulings = {}
    unbound = []
    for record in records:
        header = record["header"]
        if header["message"] != "ruling":
            continue
        if record["actor_id"] not in principals:
            continue
        source_id = int(header["source-comment-id"])
        if source_id in rulings or any(fact[1] == source_id for fact in unbound):
            raise ReductionError("multiple rulings exist for source comment {}".format(source_id))
        source = sources.get(source_id)
        if source is None:
            unbound.append(("source_deleted", source_id, record))
            continue
        if source["order"] >= record["order"]:
            raise ReductionError("ruling precedes its source comment {}".format(source_id))
        if int(header["target-actor-id"]) != source["actor_id"]:
            raise ReductionError("ruling binding does not match source comment {}".format(source_id))
        if (
            header["message-id"] != source["header"]["id"]
            or header["source-digest"] != source["digest"]
        ):
            unbound.append(("source_edited", source_id, record))
            continue
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
    return rulings, unbound


def manifest_memory(records, principals):
    """Merge the surviving section 4.18 manifests into the reducer's memory.

    Section 7.6 defines the memory over the *set* of surviving manifests rather
    than the newest one, because a run can write twice. Entries and freezes are
    the union and the watermark is the maximum; two entries for the same comment
    with different digests are an edit of that message under section 7.3, not a
    conflict between manifests.
    """
    memory = {"entries": {}, "frozen": {}, "deletions_accounted": 0}
    for record in records:
        header = record["header"]
        if header["message"] != "manifest" or record["actor_id"] not in principals:
            continue
        memory["deletions_accounted"] = max(
            memory["deletions_accounted"], int(header["deletions-accounted"])
        )
        for token in header.get("entries", "").split(","):
            if not token:
                continue
            parts = token.split("/")
            comment_id = int(parts[0])
            entry = memory["entries"].setdefault(
                comment_id, {"digests": set(), "family": parts[2], "ruling_comment_id": None}
            )
            entry["digests"].add(parts[1])
            if len(parts) == 4:
                entry["ruling_comment_id"] = int(parts[3])
        for token in header.get("frozen", "").split(","):
            if not token:
                continue
            comment_id, watermark = token.split("/")
            comment_id, watermark = int(comment_id), int(watermark)
            previous = memory["frozen"].get(comment_id)
            memory["frozen"][comment_id] = (
                watermark if previous is None else min(previous, watermark)
            )
    return memory


def barrier_candidates(records, memory, rulings):
    """Return the sources the ambiguity barrier of the mechanism has to resolve.

    A source in a section 4.17 family with no ruling in the inventory and no
    surviving entry recording a ruling for it: the two states "genuinely new"
    and "its entry went with its ruling" are indistinguishable from the
    inventory, which is what the timeline read exists to separate. This is a
    predicate over the inventory and the manifest alone, so an adapter can
    evaluate it before deciding whether to fetch the timeline.
    """
    candidates = []
    for record in records:
        if record["header"]["message"] not in RULING_REQUIRED:
            continue
        comment_id = record["comment_id"]
        if comment_id in rulings:
            continue
        entry = memory["entries"].get(comment_id)
        if entry is not None and entry["ruling_comment_id"] is not None:
            continue
        candidates.append(comment_id)
    return candidates


def reduction_context(bundle):
    """Normalize the inputs the adapter's two predicates share with the reduction."""
    records, _ = normalize_events(bundle)
    principals = set(bundle["authority_policy"]["reducer_principals"])
    memory = manifest_memory(records, principals)
    rulings, _ = collect_rulings(records, principals)
    return records, memory, rulings


def timeline_read_required(bundle, context=None):
    """Trigger 1: whether resolving this bundle needs the issue timeline."""
    records, memory, rulings = context or reduction_context(bundle)
    return bool(barrier_candidates(records, memory, rulings))


def permission_lookup_targets(bundle, context=None):
    """Return the sources for which the adapter may consult current permissions.

    This is the single site that decides, so that "no permission lookup happens"
    is a property of the code both the adapter and the fixtures read rather than
    two rules that can drift apart. A source whose loss is identified, one the
    barrier freezes, and one already frozen by a surviving manifest are all
    excluded: section 9.1 forbids the lookup, and a lookup is an act no later
    record undoes.
    """
    records, memory, rulings = context or reduction_context(bundle)
    observed = bundle.get("deletions_observed")
    return {
        comment_id
        for comment_id in barrier_candidates(records, memory, rulings)
        if comment_id not in memory["frozen"]
        and observed is not None
        and observed == memory["deletions_accounted"]
    }


def manifest_body(part, accounted, entry_records, frozen_records):
    """Render one manifest comment, with a message id derived from its content.

    Deriving the id from the payload is what makes a retry of the same logical
    manifest an exact duplicate under section 7.2 rather than a conflict.
    """
    payload = json.dumps([part, accounted, entry_records, frozen_records], sort_keys=True)
    lines = [
        "```open-table",
        "open-table: 0",
        "message: manifest",
        "id: manifest-{}".format(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]),
        "deletions-accounted: {}".format(accounted),
    ]
    if entry_records:
        lines.append("entries: {}".format(",".join(entry_records)))
    if frozen_records:
        lines.append("frozen: {}".format(",".join(frozen_records)))
    lines.extend([
        "```",
        "",
        "Reducer memory of what this run incorporated. Section 4.18.",
    ])
    return "\n".join(lines)


def manifest_bodies(accounted, entries, frozen):
    """Render the logical manifest, split across comments when one would be too large."""
    entry_records = [
        "{}/{}/{}{}".format(
            entry["comment_id"], entry["digest"], entry["family"],
            "/{}".format(entry["ruling_comment_id"])
            if entry["ruling_comment_id"] is not None else "",
        )
        for entry in entries
    ]
    frozen_records = [
        "{}/{}".format(comment_id, watermark) for comment_id, watermark in frozen
    ]
    parts = []
    current = []
    for record in entry_records:
        candidate = current + [record]
        carried = frozen_records if not parts else []
        if current and len(manifest_body(len(parts), accounted, candidate, carried)) > (
            MANIFEST_BODY_LIMIT
        ):
            parts.append(current)
            current = [record]
        else:
            current = candidate
    parts.append(current)
    return [
        manifest_body(index, accounted, records, frozen_records if index == 0 else [])
        for index, records in enumerate(parts)
    ]


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


def detection_permalink(issue_url, comment_id):
    """Cite a comment that may no longer exist, so the notice can still name it."""
    return "{}#issuecomment-{}".format(issue_url, comment_id)


def body_digest(body):
    try:
        return canonical_digest(body)
    except UnicodeEncodeError:
        return None


def detect_mutations(inventory, records, memory, unbound, issue_url):
    """Name every mutation the memory and the section 7.3 pins expose.

    Two kinds of pin exist and they are read together: a manifest entry, which
    is the only pin `contribution` and `proposal` ever get, and a ruling, which
    binds its source's comment id and digest. A message with neither carries no
    edit signal, because nothing was incorporated to be changed.
    """
    present = {record["comment_id"]: record for record in records}
    found = {}
    edited = set()

    def report(code, comment_id, **fields):
        # One fact about one comment is one notice. A deleted source is reported
        # both by the entry that remembered it and by the ruling left pointing at
        # it, and those are the same loss seen twice, so they merge and each
        # fills in what the other could not name.
        key = (code, comment_id)
        notice = found.setdefault(key, {
            "code": code,
            "comment_id": comment_id,
            "permalink": detection_permalink(issue_url, comment_id),
        })
        for name, value in fields.items():
            if notice.get(name) is None:
                notice[name] = value

    for comment_id in sorted(memory["entries"]):
        entry = memory["entries"][comment_id]
        if comment_id not in inventory:
            report(
                "incorporated_message_deleted", comment_id, family=entry["family"],
                ruling_comment_id=None,
                detail="an incorporated {} is no longer in the inventory".format(
                    entry["family"]
                ),
            )
        else:
            # The section 7.3 comparison is scoped to the domain, and the family
            # that decides is the one the comment's own header carries when the
            # comment is still a readable protocol message. Section 4.18 keeps an
            # entry naming a family outside the domain structurally well-formed,
            # so the entry's claim alone is not enough to raise an edit; it is
            # what is left to go on when an edit broke the envelope itself.
            family = (
                present[comment_id]["header"]["message"]
                if comment_id in present else entry["family"]
            )
            if family in DOMAIN_MESSAGES and (
                len(entry["digests"] | {body_digest(inventory[comment_id])}) > 1
            ):
                edited.add(comment_id)
                report(
                    "incorporated_message_edited", comment_id, family=family,
                    ruling_comment_id=None,
                    detail="the body of this {} differs from the one "
                           "incorporated".format(family),
                )
        if entry["ruling_comment_id"] is not None and (
            entry["ruling_comment_id"] not in inventory
        ):
            report(
                "ruling_deleted", comment_id, family=entry["family"],
                ruling_comment_id=entry["ruling_comment_id"],
                detail="the ruling that decided this {} is no longer in the "
                       "inventory".format(entry["family"]),
            )

    for kind, source_id, ruling in unbound:
        family = present[source_id]["header"]["message"] if source_id in present else None
        if kind == "source_deleted":
            report(
                "incorporated_message_deleted", source_id, family=family,
                ruling_comment_id=ruling["comment_id"],
                detail="a ruled source is no longer in the inventory",
            )
        else:
            edited.add(source_id)
            report(
                "incorporated_message_edited", source_id, family=family,
                ruling_comment_id=ruling["comment_id"],
                detail="the body of this message differs from the one its ruling pinned",
            )

    order = {
        "incorporated_message_deleted": 0,
        "ruling_deleted": 1,
        "incorporated_message_edited": 2,
    }
    return [
        found[key] for key in sorted(found, key=lambda key: (order[key[0]], key[1]))
    ], edited


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
        memory = manifest_memory(records, principals)
        rulings, unbound = collect_rulings(records, principals)
        inventory = {
            event["comment_id"]: event["body"] for event in bundle["ordered_events"]
        }
        issue_url = bundle["issue"].get("html_url", "")
        detection, edited = detect_mutations(
            inventory, records, memory, unbound, issue_url
        )

        observed = bundle.get("deletions_observed")
        accounted = memory["deletions_accounted"]
        watermark = accounted if observed is None else max(accounted, observed)
        if observed is not None and observed != accounted:
            detection.append({
                "code": "unaccounted_deletions",
                "comment_id": None,
                "observed": observed,
                "accounted": accounted,
                "unaccounted": abs(observed - accounted),
                "permalink": issue_url,
                "detail": "{} comment deletions in the issue timeline are not "
                          "accounted for: {} observed against a watermark of "
                          "{}".format(abs(observed - accounted), observed, accounted),
            })

        # Computed from the same expression, over the same inputs, that the
        # adapter's two predicates read. The freeze below removes rulings, and a
        # candidate set computed after it would be a second construction site
        # that can agree with the first while both are wrong.
        candidates = set(barrier_candidates(records, memory, rulings))

        # Section 7.6: a freeze beats a ruling for the same source, because the
        # ruling recorded a decision taken against current permissions at a
        # moment when section 2.3 required failing closed.
        frozen = dict(memory["frozen"])
        present = {record["comment_id"]: record for record in records}
        for comment_id in sorted(frozen):
            rulings.pop(comment_id, None)
            family = (
                present[comment_id]["header"]["message"]
                if comment_id in present else None
            )
            # A durable freeze is re-announced every run: the projection is a
            # full recomputation, and a source nobody may rule has to stay
            # visible to the people who could re-establish it.
            detection.append({
                "code": "source_frozen",
                "comment_id": comment_id,
                "family": family,
                "watermark": frozen[comment_id],
                "permalink": detection_permalink(issue_url, comment_id),
                "detail": "still frozen at a watermark of {}: it is re-established "
                          "by a new message, never by a later ruling".format(
                              frozen[comment_id]
                          ),
            })

        existing_ruling_ids = {
            int(record["header"]["source-comment-id"]): record["comment_id"]
            for record in records
            if record["header"]["message"] == "ruling"
            and record["actor_id"] in principals
        }
        identified_loss = {
            comment_id for comment_id, entry in memory["entries"].items()
            if entry["ruling_comment_id"] is not None
            and entry["ruling_comment_id"] not in inventory
        }

        active_configuration = configuration_context(records, rulings)
        configurations_valid = configuration_declarations_valid(records)
        ruling_writes = []
        new_frozen = {}
        ruled_here = set()
        for record in records:
            message = record["header"]["message"]
            comment_id = record["comment_id"]
            # Only a candidate is ever ruled here. Everything else in a
            # ruling-required family either already carries a ruling or has an
            # entry naming one, and minting a decision for it would be a
            # decision taken without the lookup the adapter was told not to make.
            if comment_id not in candidates or comment_id in frozen:
                continue
            # The barrier. Its trigger is a predicate over the inventory and
            # the manifest alone, so it fires here whether or not this run
            # would otherwise have reached the source.
            if observed is None:
                raise ReductionError(
                    "the issue timeline is required to resolve source comment "
                    "{} and was not supplied".format(comment_id)
                )
            if observed != accounted:
                new_frozen[comment_id] = watermark
                detection.append({
                    "code": "source_frozen",
                    "comment_id": comment_id,
                    "family": message,
                    "watermark": watermark,
                    "permalink": detection_permalink(issue_url, comment_id),
                    "detail": "refused to rule this {} while {} comment "
                              "deletions are unaccounted for".format(
                                  message, abs(observed - accounted)
                              ),
                })
                continue
            if comment_id in edited:
                continue
            if message != "configuration" and active_configuration is None:
                continue
            decision, reason = decision_for(
                record, records, rulings, active_configuration, configurations_valid
            )
            rulings[comment_id] = decision
            ruled_here.add(comment_id)
            ruling_writes.append({
                "operation": "post_comment",
                "source_comment_id": comment_id,
                "body": ruling_body(record, decision, reason),
            })
            if message == "configuration":
                active_configuration = configuration_context(records, rulings)

        for comment_id, watermark_value in new_frozen.items():
            frozen[comment_id] = watermark_value

        configuration = configuration_context(records, rulings)
        # A loss must not be silent, so detection alone is enough to make this
        # run publish a projection even where a configuration-free session would
        # otherwise write nothing at all.
        renders_projection = configuration is not None or bool(detection)

        entries = []
        for record in records:
            message = record["header"]["message"]
            comment_id = record["comment_id"]
            if message not in DOMAIN_MESSAGES:
                continue
            # Only what this run actually incorporated is remembered: a message
            # the reduction never consumed was not incorporated, and a manifest
            # entry for it would be a memory of something that never happened.
            incorporated = (
                comment_id in rulings
                or (renders_projection and message in DELIBERATION_MESSAGES)
            )
            if not incorporated:
                continue
            if comment_id in edited or comment_id in frozen or comment_id in identified_loss:
                continue
            entry = memory["entries"].get(comment_id)
            known_ruling = existing_ruling_ids.get(comment_id)
            if entry is not None and (
                entry["ruling_comment_id"] is not None
                or (known_ruling is None and comment_id not in ruled_here)
            ):
                continue
            entries.append({
                "comment_id": comment_id,
                "digest": record["digest"],
                "family": message,
                "ruling_comment_id": known_ruling,
                "ruling_of_source": comment_id if comment_id in ruled_here else None,
            })

        writes = ruling_writes
        if entries or new_frozen or watermark != accounted:
            writes.append({
                "operation": "post_manifest",
                "deletions_accounted": watermark,
                "entries": entries,
                "frozen": sorted(
                    [comment_id, value] for comment_id, value in new_frozen.items()
                ),
            })

        if renders_projection:
            status, phase, turn, settled, open_proposals = derive_deliberation(
                records, rulings, configuration, notices
            )
            projection = render_projection(
                status, phase, turn, settled, open_proposals, notices, detection
            )
            new_body = replace_projection(bundle["issue"].get("body", ""), projection)
            if new_body != bundle["issue"].get("body", ""):
                writes.append({"operation": "update_issue_body", "body": new_body})
        writes.extend(label_plan(bundle, diagnosis_is_invisible=False))
        return {
            "profile": PROFILE,
            "as_of": as_of,
            "unreplayable": False,
            "writes": writes,
            "notices": notices,
            "detection": detection,
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


def deletion_event_count(repository, issue_number, token):
    """Count the comment-deletion events GitHub records in the issue timeline.

    The REST event name is `comment_deleted`, measured against the timeline of
    the probe issue where a deletion actually happened rather than read off the
    documentation. The watermark is this count; the mechanism's record leaves a
    cursor as the fallback if the count is ever observed to disagree with
    itself, and this implementation uses the count.
    """
    events = paginated_rest(
        "https://api.github.com/repos/{}/issues/{}/timeline".format(
            repository, issue_number
        ), token,
    )
    return sum(1 for event in events if event.get("event") == "comment_deleted")


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
    # Trigger 2: a run woken by a comment deletion reads the timeline and
    # reconciles the accounting, whether or not anything is pending. What used
    # to happen here instead was declaring the whole session unreplayable from
    # the one comment id in the webhook payload.
    deletion_woken = event_context.get("action") == "deleted"
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
    context = reduction_context(bundle)
    if deletion_woken or timeline_read_required(bundle, context):
        bundle["deletions_observed"] = deletion_event_count(repository, issue_number, token)
    by_comment_id = {event["comment_id"]: event for event in events}
    for comment_id in sorted(permission_lookup_targets(bundle, context)):
        event = by_comment_id[comment_id]
        event["permission"] = permission_for(repository, event["actor_login"], token)
    return bundle


def resolve_manifest_entries(entries, posted_rulings):
    """Bind each entry to the ruling comment id this run now has.

    A ruling has no comment id until it is posted, which is why the manifest is
    written after the rulings it records rather than before them.
    """
    resolved = []
    for entry in entries:
        ruling_comment_id = entry["ruling_comment_id"]
        if ruling_comment_id is None and entry["ruling_of_source"] is not None:
            ruling_comment_id = posted_rulings.get(entry["ruling_of_source"])
        resolved.append(dict(entry, ruling_comment_id=ruling_comment_id))
    return resolved


def apply_plan(plan, repository, issue_number, token):
    """Apply the plan in order: rulings, then the manifest recording them, then the projection."""
    base = "https://api.github.com/repos/{}/issues/{}".format(repository, issue_number)
    posted_rulings = {}
    for write in plan["writes"]:
        if write["operation"] == "post_comment":
            created = github_request(
                base + "/comments", token, "POST", {"body": write["body"]}
            )
            posted_rulings[write["source_comment_id"]] = created["id"]
        elif write["operation"] == "post_manifest":
            for body in manifest_bodies(
                write["deletions_accounted"],
                resolve_manifest_entries(write["entries"], posted_rulings),
                write["frozen"],
            ):
                github_request(base + "/comments", token, "POST", {"body": body})
        elif write["operation"] == "update_issue_body":
            github_request(base, token, "PATCH", {"body": write["body"]})
        elif write["operation"] == "add_label":
            github_request(base + "/labels", token, "POST", {"labels": [write["label"]]})
        elif write["operation"] == "remove_label":
            github_request(
                "{}/labels/{}".format(
                    base, urllib.parse.quote(write["label"], safe="")
                ), token, "DELETE",
            )
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
        # Section 2.2 makes the complete timeline a replay input, and this
        # session has a claim awaiting a ruling, so a bundle without it cannot
        # be resolved without consulting current permissions.
        "deletions_observed": 0,
        "ordered_events": events,
    }


DETECTION_PRINCIPAL = 41898282
DETECTION_AS_OF = "2026-08-16T01:00:00Z"
DETECTION_CONFIGURATION = "\n".join([
    "```open-table", "open-table: 0", "message: configuration",
    "id: detection-configuration-0001", "phase: observation", "sequence: 1",
    "expected-actors: 101", "authority-profile: deliberation-only",
    "turn-limit: 2", "```", "", "Configuration for the detection fixtures.",
])
DETECTION_CONTRIBUTION = "\n".join([
    "```open-table", "open-table: 0", "message: contribution",
    "id: detection-contribution-0001", "phase: observation", "turn: 1",
    "```", "", "An incorporated contribution.",
])


def detection_claim(message_id):
    return "\n".join([
        "```open-table", "open-table: 0", "message: claim",
        "id: {}".format(message_id), "expires-at: 2026-08-20T00:00:00Z",
        "```", "", "An advisory claim awaiting a ruling.",
    ])


def detection_ruling(source_comment_id, source_body, message_id, actor_id, decision):
    """Build a ruling an earlier run would have appended, bound to its source."""
    digest = canonical_digest(source_body)
    return "\n".join([
        "```open-table", "open-table: 0", "message: ruling",
        "id: ruling-{}-{}".format(source_comment_id, digest.split(":", 1)[1][:16]),
        "target-actor-id: {}".format(actor_id),
        "message-id: {}".format(message_id),
        "source-comment-id: {}".format(source_comment_id),
        "source-digest: {}".format(digest),
        "decision: {}".format(decision),
        "```", "", "Recorded by an earlier run.",
    ])


def detection_manifest(message_id, accounted, entries=None, frozen=None):
    """Build a section 4.18 manifest an earlier run would have posted."""
    lines = [
        "```open-table", "open-table: 0", "message: manifest",
        "id: {}".format(message_id),
        "deletions-accounted: {}".format(accounted),
    ]
    if entries:
        lines.append("entries: {}".format(",".join(entries)))
    if frozen:
        lines.append("frozen: {}".format(",".join(frozen)))
    lines.extend(["```", "", "Reducer memory written by an earlier run."])
    return "\n".join(lines)


def detection_comment(comment_id, actor_id, body, seconds, permission=None, edited=False):
    created = "2026-08-16T00:00:{:02d}Z".format(seconds)
    touched = "2026-08-16T00:30:00Z"
    event = {
        "actor_id": actor_id,
        "actor_login": (
            "github-actions[bot]" if actor_id == DETECTION_PRINCIPAL else "writer"
        ),
        "comment_id": comment_id,
        "created_at": created,
        "updated_at": touched if edited else created,
        "last_edited_at": touched if edited else None,
        "body": body,
        "html_url": "https://example.invalid/issues/9#issuecomment-{}".format(comment_id),
    }
    if permission is not None:
        event["permission"] = permission
    return event


def detection_bundle(deletions_observed=0):
    """A configured session whose first run left a ruling and a manifest behind.

    Comment 401 is an authorized `configuration`, 403 the ruling that authorized
    it, 402 an incorporated `contribution` that needs no ruling, and 404 the
    manifest recording both.
    """
    manifest = detection_manifest(
        "detection-manifest-0001", 0,
        entries=[
            "401/{}/configuration/403".format(canonical_digest(DETECTION_CONFIGURATION)),
            "402/{}/contribution".format(canonical_digest(DETECTION_CONTRIBUTION)),
        ],
    )
    bundle = {
        "repository": "example/project",
        "issue": {
            "number": 9,
            "body": "Human preface\n\n" + START_MARKER + "\nStale projection.\n" + END_MARKER,
            "state": "open",
            "html_url": "https://example.invalid/issues/9",
            "labels": ["open-table/session"],
        },
        "authority_policy": {
            "profile": PROFILE, "reducer_principals": [DETECTION_PRINCIPAL],
        },
        "ordered_events": [
            detection_comment(401, 101, DETECTION_CONFIGURATION, 1, permission="write"),
            detection_comment(402, 101, DETECTION_CONTRIBUTION, 2),
            detection_comment(403, DETECTION_PRINCIPAL, detection_ruling(
                401, DETECTION_CONFIGURATION, "detection-configuration-0001", 101,
                "authorized",
            ), 3),
            detection_comment(404, DETECTION_PRINCIPAL, manifest, 4),
        ],
    }
    if deletions_observed is not None:
        bundle["deletions_observed"] = deletions_observed
    return bundle


def without_comments(bundle, *comment_ids):
    copy = json.loads(json.dumps(bundle))
    copy["ordered_events"] = [
        event for event in copy["ordered_events"]
        if event["comment_id"] not in comment_ids
    ]
    return copy


def detection_notices(plan, code=None):
    found = plan.get("detection", [])
    return [notice for notice in found if code is None or notice["code"] == code]


def detection_codes(plan):
    return [notice["code"] for notice in plan.get("detection", [])]


def ruling_sources(plan):
    return [
        write["source_comment_id"] for write in plan["writes"]
        if write["operation"] == "post_comment"
    ]


def manifest_write(plan):
    writes = [write for write in plan["writes"] if write["operation"] == "post_manifest"]
    assert len(writes) <= 1, "a run plans at most one logical manifest"
    return writes[0] if writes else None


def label_writes(plan):
    return [
        write for write in plan["writes"]
        if write["operation"] in {"add_label", "remove_label"}
    ]


def detection_fixture_lost_ruling_is_identified():
    """ADR fixture 1 and the requirement record's first inherited fixture.

    A deleted ruling whose manifest entry survives is an identified loss: the
    entry names the source and the ruling that backed it, no replacement ruling
    is minted, no permission is consulted, and the timeline is not read because
    the loss is already identified.
    """
    bundle = without_comments(detection_bundle(), 403)
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    assert ruling_sources(plan) == []
    lost = detection_notices(plan, "ruling_deleted")
    assert len(lost) == 1
    assert lost[0]["comment_id"] == 401 and lost[0]["ruling_comment_id"] == 403
    assert permission_lookup_targets(bundle) == set()
    assert timeline_read_required(bundle) is False
    print("detection: deleted ruling with a surviving entry is identified, zero lookups")


def detection_fixture_paired_deletion_is_identified():
    """ADR fixture 2: a source and its ruling deleted together are not silent.

    Neither deleted comment carries the memory, so the surviving manifest entry
    is what turns a paired deletion from zero trace into a named loss.
    """
    bundle = without_comments(detection_bundle(), 401, 403)
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    deleted = detection_notices(plan, "incorporated_message_deleted")
    assert [notice["comment_id"] for notice in deleted] == [401]
    assert deleted[0]["family"] == "configuration"
    assert [
        notice["ruling_comment_id"] for notice in detection_notices(plan, "ruling_deleted")
    ] == [403]

    # The same loss seen twice: the entry that remembered the source and the
    # ruling still pointing at it are one deletion, not two.
    orphaned = reduce_session(without_comments(detection_bundle(), 401), DETECTION_AS_OF)
    lost = detection_notices(orphaned, "incorporated_message_deleted")
    assert len(lost) == 1 and lost[0]["comment_id"] == 401
    assert lost[0]["ruling_comment_id"] == 403 and lost[0]["family"] == "configuration"
    print("detection: a paired source and ruling deletion is identified, not silent")


def detection_fixture_unaccounted_deletion_freezes_only_the_pending():
    """ADR fixture 3: the barrier freezes what is pending and nothing later.

    One unaccounted deletion freezes the permission-sensitive source that was
    pending when it was observed. Once the watermark has advanced in the same
    manifest write, material arriving afterwards is ruled normally: this is what
    stops one housekeeping deletion from freezing a session permanently.
    """
    bundle = detection_bundle(deletions_observed=1)
    bundle["ordered_events"].append(
        detection_comment(405, 101, detection_claim("detection-claim-0001"), 5,
                          permission="write")
    )
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    assert ruling_sources(plan) == []
    assert permission_lookup_targets(bundle) == set()
    assert [notice["comment_id"] for notice in detection_notices(plan, "source_frozen")] == [405]
    unaccounted = detection_notices(plan, "unaccounted_deletions")
    assert len(unaccounted) == 1 and unaccounted[0]["unaccounted"] == 1
    manifest = manifest_write(plan)
    assert manifest["deletions_accounted"] == 1
    assert manifest["frozen"] == [[405, 1]]

    later = json.loads(json.dumps(bundle))
    later["ordered_events"].append(detection_comment(
        406, DETECTION_PRINCIPAL,
        detection_manifest("detection-manifest-0002", 1, frozen=["405/1"]), 6,
    ))
    later["ordered_events"].append(detection_comment(
        407, 101, detection_claim("detection-claim-0002"), 7, permission="write",
    ))
    later_plan = reduce_session(later, DETECTION_AS_OF)
    assert ruling_sources(later_plan) == [407]
    assert permission_lookup_targets(later) == {407}
    assert [
        notice["comment_id"] for notice in detection_notices(later_plan, "source_frozen")
    ] == [405]
    print("detection: an unaccounted deletion freezes the pending source and nothing after it")


def detection_fixture_crashed_run_is_recovered_without_accusation():
    """ADR fixture 4: a manifest that lags its rulings is recovered, not accused.

    The rulings of the crashed run are in the inventory and its manifest is not.
    That residue must read as under-detection inside one window rather than as
    tampering, so the next run records the entry from the surviving ruling and
    consults no current permission.
    """
    bundle = without_comments(detection_bundle(), 404)
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    assert ruling_sources(plan) == []
    assert detection_codes(plan) == []
    manifest = manifest_write(plan)
    assert manifest is not None
    entries = {entry["comment_id"]: entry for entry in manifest["entries"]}
    assert entries[401]["ruling_comment_id"] == 403
    assert entries[402]["ruling_comment_id"] is None
    assert permission_lookup_targets(bundle) == set()
    print("detection: a crashed run's missing manifest is recovered with no false accusation")


def detection_fixture_edit_outside_the_domain_changes_nothing():
    """ADR fixture 5, the regression guard for issue #144.

    A comment that is not a protocol message carries no edit signal worth acting
    on. Editing one must not change the plan at all, which is the denial of
    service the blanket trip-wire caused.
    """
    bundle = detection_bundle()
    bundle["ordered_events"].append(
        detection_comment(405, 101, "thanks for the update!", 5)
    )
    edited = json.loads(json.dumps(bundle))
    edited["ordered_events"][-1]["updated_at"] = "2026-08-16T00:30:00Z"
    edited["ordered_events"][-1]["last_edited_at"] = "2026-08-16T00:30:00Z"
    edited_plan = reduce_session(edited, DETECTION_AS_OF)
    assert not edited_plan["unreplayable"]
    assert edited_plan == reduce_session(bundle, DETECTION_AS_OF)
    assert detection_codes(edited_plan) == []
    print("detection: an edit outside the domain changes nothing (#144)")


def detection_fixture_erased_memory_still_produces_a_notice():
    """ADR fixture 6, the leg driven by a run woken by a comment deletion.

    Three comments were deleted that no surviving manifest names, and nothing
    permission-sensitive is pending, so the barrier alone would never look. The
    deletion-woken run reads the timeline anyway and names what it cannot
    account for. The sweep leg of this fixture belongs to the deployment change
    and is deferred with it.
    """
    bundle = detection_bundle(deletions_observed=3)
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    unaccounted = detection_notices(plan, "unaccounted_deletions")
    assert len(unaccounted) == 1
    assert unaccounted[0]["observed"] == 3 and unaccounted[0]["accounted"] == 0
    assert detection_notices(plan, "source_frozen") == []
    manifest = manifest_write(plan)
    assert manifest["deletions_accounted"] == 3 and manifest["frozen"] == []
    print("detection: an erased memory still produces a notice with nothing pending")


def terminal_bundle(freeze_the_settlement):
    """A session an earlier run terminated, optionally with its settlement frozen.

    The settlement carries an `authorized` ruling in the inventory and a manifest
    entry naming it. Freezing it is the only difference between the two bundles,
    so whether the session reads as terminated is exactly the question of which
    record wins.
    """
    configuration = "\n".join([
        "```open-table", "open-table: 0", "message: configuration",
        "id: terminal-configuration-0001", "phase: observation", "sequence: 1",
        "expected-actors: 101", "authority-profile: deliberation-only",
        "turn-limit: 3", "```", "", "Configuration.",
    ])
    proposal = "\n".join([
        "```open-table", "open-table: 0", "message: proposal",
        "id: terminal-proposal-0001", "phase: observation", "turn: 1",
        "point: decision", "```", "", "A proposal.",
    ])
    settled = "\n".join([
        "```open-table", "open-table: 0", "message: settled",
        "id: terminal-settled-0001", "phase: observation", "turn: 2",
        "point: decision", "proposal-comment-id: 413", "disposition: accepted",
        "terminal: true", "```", "", "A settlement.",
    ])
    manifest = detection_manifest(
        "terminal-manifest-0001", 0,
        entries=[
            "411/{}/configuration/412".format(canonical_digest(configuration)),
            "413/{}/proposal".format(canonical_digest(proposal)),
            "414/{}/settled/415".format(canonical_digest(settled)),
        ],
        frozen=["414/0"] if freeze_the_settlement else None,
    )
    return {
        "repository": "example/project",
        "issue": {
            "number": 9,
            "body": "Human preface\n",
            "state": "open",
            "html_url": "https://example.invalid/issues/9",
            "labels": ["open-table/session"],
        },
        "authority_policy": {
            "profile": PROFILE, "reducer_principals": [DETECTION_PRINCIPAL],
        },
        "deletions_observed": 0,
        "ordered_events": [
            detection_comment(411, 101, configuration, 1, permission="write"),
            detection_comment(412, DETECTION_PRINCIPAL, detection_ruling(
                411, configuration, "terminal-configuration-0001", 101, "authorized",
            ), 2),
            detection_comment(413, 101, proposal, 3),
            detection_comment(414, 101, settled, 4, permission="write"),
            detection_comment(415, DETECTION_PRINCIPAL, detection_ruling(
                414, settled, "terminal-settled-0001", 101, "authorized",
            ), 5),
            detection_comment(416, DETECTION_PRINCIPAL, manifest, 6),
        ],
    }


def detection_fixture_freeze_beats_a_ruling():
    """ADR fixture 7: the only observable consequence of the race serialisation prevents.

    A surviving manifest freezes the settlement while an authorized ruling for it
    sits in the inventory. The freeze wins, so the settlement does not terminate
    the deliberation: the ruling that crossed the freeze recorded a decision
    taken when failing closed was required, and it is the record that loses.
    """
    frozen_plan = reduce_session(terminal_bundle(True), DETECTION_AS_OF)
    assert not frozen_plan["unreplayable"]
    assert ruling_sources(frozen_plan) == []
    frozen_projection = [
        write["body"] for write in frozen_plan["writes"]
        if write["operation"] == "update_issue_body"
    ][0]
    assert "Session status: `open`" in frozen_projection
    assert [
        notice["comment_id"] for notice in detection_notices(frozen_plan, "source_frozen")
    ] == [414]

    control_plan = reduce_session(terminal_bundle(False), DETECTION_AS_OF)
    control_projection = [
        write["body"] for write in control_plan["writes"]
        if write["operation"] == "update_issue_body"
    ][0]
    assert "Session status: `terminated`" in control_projection
    assert detection_notices(control_plan, "source_frozen") == []
    print("detection: a freeze beats a ruling for the same source")


def detection_fixture_edited_contribution_is_noticed():
    """The requirement record's second inherited fixture.

    A `contribution` requires no ruling and still advances phase and turn, so
    the manifest entry is its only pin. Editing it after incorporation must be
    named rather than absorbed, and must not kill the session.
    """
    bundle = detection_bundle()
    bundle["ordered_events"][1] = detection_comment(
        402, 101,
        DETECTION_CONTRIBUTION.replace("An incorporated", "An edited"), 2, edited=True,
    )
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    edited = detection_notices(plan, "incorporated_message_edited")
    assert len(edited) == 1 and edited[0]["comment_id"] == 402
    assert edited[0]["family"] == "contribution"
    print("detection: an edited contribution that advanced phase and turn is noticed")


def detection_fixture_wiped_projection_changes_no_detection():
    """The requirement record's third inherited fixture.

    The projection is a cache under section 2.6 and carries no evidentiary
    value, so erasing it from the issue body must leave detection identical.
    The equality is asserted against a non-empty result, because two empty
    lists would agree while detecting nothing.
    """
    base = without_comments(detection_bundle(), 403)
    wiped = json.loads(json.dumps(base))
    wiped["issue"]["body"] = "Human preface\n"
    base_detection = reduce_session(base, DETECTION_AS_OF).get("detection", [])
    wiped_detection = reduce_session(wiped, DETECTION_AS_OF).get("detection", [])
    assert base_detection and base_detection == wiped_detection
    print("detection: a wiped projection changes nothing about detection")


def detection_fixture_all_clear_rules_the_new_source():
    """The barrier's positive control, which the ADR's list does not name.

    A barrier exercised only on the branch that freezes has never said yes, and
    an implementation that froze everything would pass the freeze fixture. With
    the observed count equal to the watermark the source is new: it is ruled,
    exactly one permission lookup happens, and the entry is recorded.
    """
    bundle = detection_bundle(deletions_observed=0)
    bundle["ordered_events"].append(
        detection_comment(405, 101, detection_claim("detection-claim-0003"), 5,
                          permission="write")
    )
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert ruling_sources(plan) == [405]
    manifest = manifest_write(plan)
    assert manifest is not None
    assert any(entry["comment_id"] == 405 for entry in manifest["entries"])
    assert detection_notices(plan, "source_frozen") == []
    assert permission_lookup_targets(bundle) == {405}
    print("detection: with the watermark in agreement a new source is ruled once")


def detection_fixture_corrupted_markers_become_visible():
    """Issue #173, one row per row of its measured table.

    A damaged marker region makes the reduction fail where its notice cannot
    reach the issue body. The label is the surface that carries the diagnosis,
    and it is removed as soon as a reduction succeeds again.
    """
    label = "open-table/reduction-failed"
    healthy_plan = reduce_session(detection_bundle(), DETECTION_AS_OF)
    assert not healthy_plan["unreplayable"]
    assert label_writes(healthy_plan) == []

    damaged_bodies = {
        "duplicated": "\n".join([START_MARKER, "one", END_MARKER, START_MARKER, "two", END_MARKER]),
        "reversed": "\n".join([END_MARKER, "inverted", START_MARKER]),
        "unclosed": "\n".join([START_MARKER, "no end marker follows"]),
    }
    for shape, body in sorted(damaged_bodies.items()):
        bundle = detection_bundle()
        bundle["issue"]["body"] = body
        plan = reduce_session(bundle, DETECTION_AS_OF)
        assert plan["unreplayable"], shape
        assert not any(
            write["operation"] == "update_issue_body" for write in plan["writes"]
        ), shape
        assert {"operation": "add_label", "label": label} in plan["writes"], shape

    recovered = detection_bundle()
    recovered["issue"]["labels"] = ["open-table/session", label]
    recovered_plan = reduce_session(recovered, DETECTION_AS_OF)
    assert not recovered_plan["unreplayable"]
    assert {"operation": "remove_label", "label": label} in recovered_plan["writes"]
    print("detection: a corrupted marker region is labelled, and the label is removed on recovery")


def detection_fixture_a_missing_timeline_fails_closed():
    """The barrier's guard has to be able to say the timeline is missing.

    Treating an absent count as zero would read a bundle that never looked as
    an all-clear, which is the one direction the mechanism must never fail in.
    """
    bundle = detection_bundle(deletions_observed=None)
    bundle["ordered_events"].append(
        detection_comment(405, 101, detection_claim("detection-claim-0005"), 5,
                          permission="write")
    )
    assert timeline_read_required(bundle) is True
    assert permission_lookup_targets(bundle) == set()
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert plan["unreplayable"]
    assert "timeline is required" in plan["reason"]
    print("detection: a barrier with no timeline fails closed instead of reading all-clear")


def detection_fixture_manifest_is_accepted_and_settles():
    """The reducer must not write a manifest its own reference validator rejects.

    The same check covers the commit point and idempotency: the ruling posted by
    this run is bound by the comment id it received, and once the rulings and the
    manifest are in the inventory the next run has nothing left to record.
    """
    bundle = detection_bundle(deletions_observed=0)
    bundle["ordered_events"].append(
        detection_comment(405, 101, detection_claim("detection-claim-0004"), 5,
                          permission="write")
    )
    plan = reduce_session(bundle, DETECTION_AS_OF)
    manifest = manifest_write(plan)
    posted = {
        write["source_comment_id"]: 500 + index
        for index, write in enumerate(plan["writes"])
        if write["operation"] == "post_comment"
    }
    bodies = manifest_bodies(
        manifest["deletions_accounted"],
        resolve_manifest_entries(manifest["entries"], posted),
        manifest["frozen"],
    )
    assert len(bodies) == 1
    validate_comment(bodies[0])
    assert "405/{}/claim/500".format(
        canonical_digest(detection_claim("detection-claim-0004"))
    ) in bodies[0]

    settled = json.loads(json.dumps(bundle))
    for index, write in enumerate(plan["writes"]):
        if write["operation"] == "post_comment":
            settled["ordered_events"].append(detection_comment(
                posted[write["source_comment_id"]], DETECTION_PRINCIPAL,
                write["body"], 10 + index,
            ))
    for index, body in enumerate(bodies):
        settled["ordered_events"].append(
            detection_comment(600 + index, DETECTION_PRINCIPAL, body, 20 + index)
        )
    replay = reduce_session(settled, DETECTION_AS_OF)
    assert manifest_write(replay) is None
    assert ruling_sources(replay) == []
    assert replay["detection"] == []
    print("detection: the manifest validates, binds the ruling it recorded, and settles")


def detection_fixture_a_large_manifest_is_split():
    """Section 4.18 requires a manifest too large for one comment to be split.

    Each part is a complete message with its own id and the same watermark, and
    section 7.6 defines the memory over the set, so a reader never has to know
    whether a split happened.
    """
    entries = [
        {
            "comment_id": 100000 + index,
            "digest": canonical_digest("entry-{}".format(index)),
            "family": "contribution",
            "ruling_comment_id": None,
            "ruling_of_source": None,
        }
        for index in range(900)
    ]
    bodies = manifest_bodies(7, entries, [[42, 7]])
    assert len(bodies) > 1
    assert all(len(body) <= MANIFEST_BODY_LIMIT for body in bodies)
    assert all("deletions-accounted: 7" in body for body in bodies)
    assert sum(body.count("frozen: 42/7") for body in bodies) == 1
    headers = [extract_header(body) for body in bodies]
    assert len({header["id"] for header in headers}) == len(bodies)
    recorded = [
        record for header in headers for record in header.get("entries", "").split(",")
        if record
    ]
    assert recorded == [
        "{}/{}/contribution".format(entry["comment_id"], entry["digest"])
        for entry in entries
    ]
    for body in bodies:
        validate_comment(body)
    print("detection: a manifest too large for one comment is split across complete parts")


def detection_fixture_an_oversized_watermark_is_refused():
    """Found by an adversarial pass through the CLI, not by the fixtures above.

    A watermark the reducer accepts is a watermark it writes back into a
    manifest, and section 3.6 caps a count at twenty digits. Accepting a larger
    one made the reducer plan a comment its own reference validator rejects,
    which the next run would have read as an invalid authenticated reducer
    comment and failed the whole session on.
    """
    oversized = reduce_session(
        detection_bundle(deletions_observed=MAX_PROTOCOL_COUNT + 1), DETECTION_AS_OF
    )
    assert oversized["unreplayable"] and "twenty digits" in oversized["reason"]

    accepted = reduce_session(
        detection_bundle(deletions_observed=MAX_PROTOCOL_COUNT), DETECTION_AS_OF
    )
    assert not accepted["unreplayable"]
    manifest = manifest_write(accepted)
    for body in manifest_bodies(
        manifest["deletions_accounted"],
        resolve_manifest_entries(manifest["entries"], {}),
        manifest["frozen"],
    ):
        validate_comment(body)
    print("detection: a watermark the validator would reject is refused at the boundary")


def detection_fixture_an_out_of_domain_entry_raises_no_edit():
    """Also found adversarially: an entry outside the domain is not an accusation.

    Section 4.18 keeps an entry naming a family outside the domain structurally
    well-formed, and the section 7.3 comparison is scoped to the domain. Reading
    the entry's claimed family instead of the comment's own header turned a
    manifest that named itself into a report that the manifest had been edited.
    """
    bundle = detection_bundle()
    bundle["ordered_events"][3]["body"] = detection_manifest(
        "self-naming-manifest-0001", 0,
        entries=["404/{}/manifest".format(canonical_digest("a body 404 never had"))],
    )
    plan = reduce_session(bundle, DETECTION_AS_OF)
    assert not plan["unreplayable"]
    assert detection_notices(plan, "incorporated_message_edited") == []
    print("detection: an entry outside the domain raises no edit against its comment")


def detection_fixture_every_ruling_had_an_authorised_lookup():
    """The adapter's predicate and the reduction's loop must not drift apart.

    The adapter decides which permissions to fetch before the reduction runs, so
    a source the reduction rules but the adapter was told not to look up is a
    decision recorded with nothing behind it. The two read the same expression;
    this is the check that they still agree.
    """
    scenarios = [without_comments(detection_bundle(), 403), terminal_bundle(True),
                 terminal_bundle(False)]
    for observed in (0, 1):
        bundle = detection_bundle(deletions_observed=observed)
        bundle["ordered_events"].append(detection_comment(
            405, 101, detection_claim("invariant-claim-0001"), 5, permission="write",
        ))
        scenarios.append(bundle)
    ruled_anywhere = False
    for bundle in scenarios:
        ruled = set(ruling_sources(reduce_session(bundle, DETECTION_AS_OF)))
        assert ruled <= permission_lookup_targets(bundle), ruled
        ruled_anywhere = ruled_anywhere or bool(ruled)
    assert ruled_anywhere, "an inclusion that never contained anything proves nothing"
    print("detection: every ruling this run makes was a lookup the adapter was allowed")


DETECTION_FIXTURES = (
    detection_fixture_lost_ruling_is_identified,
    detection_fixture_paired_deletion_is_identified,
    detection_fixture_unaccounted_deletion_freezes_only_the_pending,
    detection_fixture_crashed_run_is_recovered_without_accusation,
    detection_fixture_edit_outside_the_domain_changes_nothing,
    detection_fixture_erased_memory_still_produces_a_notice,
    detection_fixture_freeze_beats_a_ruling,
    detection_fixture_edited_contribution_is_noticed,
    detection_fixture_wiped_projection_changes_no_detection,
    detection_fixture_all_clear_rules_the_new_source,
    detection_fixture_corrupted_markers_become_visible,
    detection_fixture_a_missing_timeline_fails_closed,
    detection_fixture_manifest_is_accepted_and_settles,
    detection_fixture_a_large_manifest_is_split,
    detection_fixture_an_oversized_watermark_is_refused,
    detection_fixture_an_out_of_domain_entry_raises_no_edit,
    detection_fixture_every_ruling_had_an_authorised_lookup,
)


def run_detection_self_test():
    for fixture in DETECTION_FIXTURES:
        fixture()


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
    edited_bundle["ordered_events"][0]["updated_at"] = "2026-08-04T00:30:00Z"
    edited_plan = reduce_session(edited_bundle, as_of)
    assert not edited_plan["unreplayable"]
    assert edited_plan == reduce_session(bundle, as_of)
    print("edit signal on an unpinned message: incorporated as it now reads, not fatal")

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
    assert not missing["unreplayable"]
    orphaned = [
        notice for notice in missing["detection"]
        if notice["code"] == "incorporated_message_deleted"
    ]
    assert [notice["comment_id"] for notice in orphaned] == [306]
    assert orphaned[0]["ruling_comment_id"] == 310
    assert not any(
        write.get("source_comment_id") == 306 for write in missing["writes"]
    )
    print("missing ruling source fails closed scoped: named, and the session survives")

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

    run_detection_self_test()
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
