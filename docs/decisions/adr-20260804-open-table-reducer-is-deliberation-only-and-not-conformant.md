---
status: accepted
date: 2026-08-04
---

# The first Open Table reducer runs deliberation-only and is not reducer-conformant

## Context

Settled point 12 of issue #130 no longer says the first reducer is a GitHub
Action. Section 2.3 of the specification says an Action remains this
repository's *intended* first reducer implementation and that no conforming
deployment has been selected or implemented. Before any Action deployment can
claim reducer conformance, a separate accepted decision must define the durable,
authenticated, non-circular GitHub-resident store for creation receipts and
deletion evidence, with its minimum permissions, retention, concurrent-write
behavior, and fail-closed recovery. That decision does not exist; it is open
point I of issue #130 and this project owns the follow-up.

Section 1.7 defines the space that leaves. A deployment may operate while
explicitly declaring its unmet reducer guarantees, but this creates no
additional conformance tier: it must not represent itself, or any session it
processes, as reducer-conformant until every reducer requirement is satisfied.
So the choice is to wait for the receipt decision or to run inside that
declaration, and this decision takes the second.

Nothing has run so far. Issue #130 is maintained by hand and, under section 1.6,
claims without an authenticated authority profile remain advisory.

Three properties of this deployment make the scope load-bearing rather than
clerical.

The repository is public, so an `issue_comment` trigger means any account GitHub
permits to comment can start a workflow run that holds a writable token. That is
section 1.5 applied to infrastructure rather than a defect, but it sets the
standard the scope has to meet.

The reducer cannot satisfy section 2.2. A stateless Action observes a comment
body at trigger time and has nowhere authenticated and durable to keep the
creation receipt between runs; the three obvious homes are each excluded, the
issue projection because section 2.6 makes it a rebuildable cache and using it
would be circular, the repository because it widens the token beyond
`issues: write`, and Action caches and artefacts because they are
retention-bound rather than durable protocol authority.

And GitHub exposes no signal at all for a deleted comment. This was verified on
a service issue rather than assumed: a comment was created and deleted, and
neither the REST timeline nor GraphQL `timelineItems` recorded the deletion. A
deletion is not merely an absence. Section 5.2 derives phase and turn from the
sequence of valid messages, so removing one turn makes the messages after it
invalid, which rewrites downstream state silently.

## Decision

The reducer declares itself not reducer-conformant, in the projection it writes
and in its own documentation, naming the guarantee it does not meet: it has no
authenticated creation receipts and no deletion evidence, so its sessions are
not replayable in the sense section 2.5 requires. It claims no conformance tier
of its own, because section 1.7 says there is not one to claim. It processes and
projects; it does not certify.

The first reducer implements the `deliberation-only` profile only. It emits
`authorized`, `unauthorized` and `rejected` rulings and writes the deliberation
projection between the markers of section 9.2. It writes no
`open-table/available`, `claimed`, `review` or `done` label and no assignee,
because section 9.4 forbids exclusive work projections under this profile. The
whole assignee surface, the most fragile write in the specification, is out of
scope until `open-table/ordered-claims` is implemented.

An issue is served only when it carries the label `open-table/session`. Adding
that label requires write access, so entry into the protocol is governed by the
permission GitHub already enforces, and revocation is immediate.

Two rules this deployment implements rather than decides, recorded here because
the earlier draft of this decision claimed them as ours and a reader of the
record should not inherit that mistake. Section 4.17 requires repository write
access for `configuration` and `settled`; where a configuration exists, section
5.4 restricts `settled` to that phase's expected actors, and the two conditions
apply together. Section 6.5 requires that a claim under `deliberation-only`
receive a `rejected` ruling, which is what keeps one comment from a stranger
from leaving a public session permanently unreplayable. Both were reached
independently here before the specification settled them; the specification is
the authority for both.

The reducer does not construct a section 2.8 integrity bundle. That schema
requires an authenticated `created_body_digest` for every event, and the digest
this deployment can compute is a first-observation digest, not a creation
receipt. Writing one into that field would misrepresent the very guarantee this
decision declares unmet. Envelope validation uses the validator's
single-comment mode, which is the participant slice and requires no receipts;
contextual reduction is the reducer's own.

What the reducer can still check for tampering, it checks, and fails closed on:
trusted `updated_at` must equal `created_at` and GraphQL `lastEditedAt` must be
null, per section 7.3. This was verified in both directions on a service issue,
an intact comment reporting null and a one-character edit populating
`lastEditedAt`, `editor` and `updated_at`. It detects edits to comments that
still exist. It detects nothing about a comment that was deleted, and the
projection says so rather than implying coverage it does not have.

The reducer's own clock decides only when to emit a message. What changes state
is the trusted `created_at` of the emitted comment. Under `deliberation-only`
the question is inert, because there are no exclusive claims and no expirations;
the rule is recorded now so that `ordered-claims` inherits it rather than
rediscovering it.

The token carries `issues: write` and nothing else. The reducer does not push,
does not merge, and writes no repository file.

The projection carries only protocol-derived values: identifiers, dispositions
and permalinks. It never copies participant prose into the issue body, which
applies section 7.5 to the one surface where untrusted text could otherwise
appear under the bot's signature.

The reducer is a pure function from a replay bundle and an `as_of` to a plan of
writes; the Action performs the input and output. This makes the determinism
required by section 2.5 testable offline, in the same shape as the validator's
self-test, and yields a dry run at no extra cost.

Two defences against duplicate rulings apply together: a per-issue `concurrency`
group, and the search for an existing ruling that section 9.1 already requires.
The group serialises runs but does not order them, so neither is sufficient
alone.

The principal is `github-actions[bot]`, actor id 41898282, verified against the
API. It stays declared deployment configuration rather than a value carved into
the reducer, per section 1.6.

The first live session is a new issue. Issue #130 remains the contract record,
maintained by hand.

## Consequences

Open Table becomes live for deliberation while work claims stay advisory, which
is the state section 1.6 already describes; nothing is promised that the profile
cannot keep. The narrowest useful surface is exercised end to end, including
parsing, digests, rulings, idempotency and projection writing, without any write
that can grant a right to anyone.

Nothing this reducer produces may be cited as evidence of conformance, by this
project or by a later reader of one of its sessions. That includes a green
validator run: section 2.8 says an integrity check is not reducer conformance,
and this deployment does not even supply that bundle. If the receipt decision
lands and this reducer is upgraded, its earlier sessions do not become
conformant retroactively; section 2.2 forbids exactly that.

The sessions it runs are the measurements the checkpoint follow-up needs. Half
of what that design must answer is operational rather than textual: how
concurrent runs interleave, what happens when a run dies between observation and
append, how the reducer avoids reacting to its own checkpoint, what interval
keeps the noise tolerable on an issue that people read. Running first means that
design arrives with measurements instead of assumptions, and the interim reducer
is input to it rather than work to be discarded.

This rests on one property of the platform that is a dependency rather than a
choice: GitHub does not start new workflow runs for events generated by the
`GITHUB_TOKEN`, which is what keeps rulings from re-triggering the reducer. It
is recorded here because it stops holding the day the reducer authenticates as
an App, and a loop would then be real rather than theoretical. It is to be
confirmed on the first live run rather than assumed.

Deferring the assignee projection defers the unsolved part with it: the protocol
identifies actors by numeric id, the assignee API takes logins, and GitHub
silently ignores an assignee without write access, so that projection can fail
without an error. It is a problem for `ordered-claims` to solve.

## Alternatives considered

Waiting for the receipt decision before building anything: rejected because half
of what that decision must settle is operational, and a design written without
a running reducer answers those questions with assumptions. The cost of the
alternative is bounded by the declaration this decision makes.

Supplying a first-observation digest as `created_body_digest` so the section 2.8
bundle validates: rejected because it puts an unauthenticated value in a field
whose whole meaning is authentication, and a green check would then read as the
guarantee this deployment does not have.

Implementing `open-table/ordered-claims` in the same round: rejected because it
makes the first thing that runs also the first thing that can grant exclusive
ownership, and it drags in the assignee surface described above.

Serving every issue in the repository: rejected as the widest possible surface
with no barrier and no gain.

A scheduled run to record expirations: rejected as premature under a profile
that has no expirations.
