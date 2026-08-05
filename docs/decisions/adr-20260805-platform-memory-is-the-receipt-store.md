---
status: accepted
date: 2026-08-05
supersedes: adr-20260805-checkpoints-are-a-partial-receipt-store.md
---

# Platform memory is the receipt store and the checkpoint family is withdrawn

## Context

The record this one supersedes was approved and merged on 2026-08-05 at 19:51Z.
The same evening, before any of it was implemented, its premises were challenged
and probed instead of defended, and two of them fell. The announcement of the
measurements and of this superseding record is
[on #151](https://github.com/iamers/steve-agent/pull/151#issuecomment-5197601275).
Superseding an accepted record within hours needs a better reason than second
thoughts, so this context is measurements, not argument. The approval of the
superseded record does not carry over: this one is reviewed from zero.

**The first premise that fell: "A deletion is an absence, not an event."** The
superseded record states it as measured, and it is true only for the case #152
measured, an author deleting their own comment. Sacrificial session #154
measured the other case: the reducer ruled a configuration as the workflow
principal, a repository admin deleted that ruling through the REST API, and the
timeline recorded a `CommentDeletedEvent` with `createdAt: 2026-08-05T20:58:10Z`,
the deleting account as `actor` in both GraphQL and REST, and the principal as
`deletedCommentAuthor` in GraphQL, the only surface that carries that field
([result](https://github.com/iamers/steve-agent/issues/154#issuecomment-5197354178)).
Timeline events are the record class #153 measured as undeletable: no mutation
among the 258 in the GraphQL schema addresses one. The event does not name which
comment died, and for reducer output it does not need to: the principal never
deletes its own comments by contract, so any such event naming it as deleted
author is tamper evidence by itself.

**The second premise that fell was never written down, which is how it
survived: an edit destroys the creation-time body, so the reducer must remember
everything in advance.** Measured on #153 the same evening: GraphQL
`userContentEdits` on an edited comment returns one node per revision, and each
node's `diff` field carries the complete body of that revision, including the
original pre-edit body, with editor and timestamp. The entire receipt line since
2026-08-04 rested on the platform forgetting something it remembers.

**What bounds the platform's memory was then probed rather than assumed.**
Deleting a revision from the UI is the one act that destroys an edited body, and
it attributes itself: measured on #153, the revision node survives with
`deletedAt` and `deletedBy` populated and its `diff` reduced to a literal
`deleted` ([result](https://github.com/iamers/steve-agent/issues/153#issuecomment-5198090574)).
And the deletion event's audience is narrower than its existence: an anonymous
reader of the #154 timeline receives the `comment_deleted` event with its
timestamp, but with `actor` replaced by the organization account; the deleting
user's login is served only to authenticated readers with sufficient access, and
`deletedCommentAuthor` exists only in GraphQL, which refuses unauthenticated
requests outright
([result](https://github.com/iamers/steve-agent/issues/154#issuecomment-5198298566)).

**The external witness was measured and shrank.** GH Archive, pencilled in as a
passive witness of everything public, captured one of the sixteen public events
the platform itself still serves for this repository across the two hours
measured, and the deleted ruling appears in neither hourly file nor in the live
per-repo events feed read afterwards
([result](https://github.com/iamers/steve-agent/issues/154#issuecomment-5198298566)).
Nothing in this decision may depend on it.

### The threat model, explicit this time

The superseded record analysed attackers in prose and sized its machinery
wrong. The table the analysis should have started from:

| Actor | Can do | Evidence the platform keeps (measured) |
|---|---|---|
| Any account (the #144 attacker) | edit or delete **its own** comments only | edit: every revision body in `userContentEdits` (#153). Self-delete: nothing (#152) |
| Participant | same as above | same as above |
| Insider with write access | edit or delete **any** comment; delete a revision | delete of another's comment: `CommentDeletedEvent` with actor and deleted author (#154). Revision delete: `deletedAt`/`deletedBy` (#153) |
| The principal itself (compromised token) | all of the above, plus authoring false rulings | out of scope: the trust boundary already recorded in the superseded record |
| The platform | anything | trusted by assumption of the entire design |

The mismatch this exposes in the superseded design: the reported attack, #144,
is by an account with no access, which can only touch its own comments. The
checkpoint chain defends chiefly against the insider, the only actor able to
delete other people's comments and checkpoints, and its own tip analysis
concedes the insider defeats it. Machinery sized for the adversary it admits it
cannot stop, paid for in availability and noise against the adversary that far
less would have stopped.

### Every platform property this design rests on, with its measurement

The superseded record is the fourth in four days on this thread to carry an
unmeasured platform assumption, and it passed two reviews because the
assumption arrived labelled as already measured. The countermeasure is
mechanical: every property, its measured sentence, its date, and the probe that
repeats it. Where the columns do not agree, the design does not build.

| Assumed property | Measured sentence | Date | Probe |
|---|---|---|---|
| Self-deletion leaves no trace | A comment created and deleted by its author left timeline `totalCount: 0`, an explicit `COMMENT_DELETED_EVENT` filter returned zero, and the REST timeline was empty | 2026-08-05 | #152 |
| Moderator deletion leaves an event | Admin deletion of a principal-authored comment recorded `CommentDeletedEvent` with actor and `deletedCommentAuthor`, in GraphQL and REST | 2026-08-05 | #154, comment 5197354178 |
| Timeline events are undeletable | After every probe label was deleted from the repository, the timeline still returned the labeling records; no mutation among 258 in the schema addresses a timeline event | 2026-08-05 | #153 |
| The platform remembers edited bodies | Each `userContentEdits` node's `diff` carries the complete body of that revision, including the pre-edit original, with editor and timestamp | 2026-08-05 | #153 |
| Revision deletion destroys but attributes | The deleted revision's node survives with `deletedAt`/`deletedBy` populated and `diff` reduced to the literal `deleted` | 2026-08-05 | #153, comment 5198090574 |
| The deletion event is public, the actor is not | An unauthenticated REST read returns the event with its timestamp and the organization as `actor`; `deletedCommentAuthor` is GraphQL-only; unauthenticated GraphQL returns 403 | 2026-08-05 | #154, comment 5198298566 |
| GH Archive is not a witness for this repo | One event archived of the sixteen the live per-repo feed serves across two measured hours; the deleted ruling in neither hourly file nor the live feed | 2026-08-05 | #154, comment 5198298566 |
| Deleting another's comment requires write access | Documented ("Managing disruptive comments"), not independently measured; consistent with the anonymous-actor masking above | docs | none available without a no-access account |
| The deployed guard's memory is one run | The deletion-triggered run failed closed naming the comment; the next run re-emitted the ruling against current permissions | 2026-08-05 | #154, comment 5197354178 |
| The workflow token can read `userContentEdits` and `deletedCommentAuthor` | **Not measured.** | — | named CI probe of the implementing pull request |

The last row is the discipline applied to this record itself: one property it
needs is unmeasured, it says so, and the implementation is gated on the probe
rather than on optimism.

### What survives from the superseded record

Its context was mostly right and is inherited, not re-litigated: the four
excluded homes for a store (mutable issue body, repository files, retention-bound
artefacts, a GitHub App) and the reasons; the #143 runtime measurements, that
reducer output cannot wake the reducer, that recovery is entirely event-driven,
and that the single-pending-run queue cancels harmlessly only while replay is
total; and the #144 reframing of point I as an availability problem, not only a
conformance obligation. Its receipt admissibility analysis is replaced, not
refuted: it was the best available answer under the premise that the platform
forgets, and the premise was false.

## Decision

**The durable, authenticated, non-circular GitHub-resident store for creation
receipts and deletion evidence required by section 2.3 is the platform's own
memory of the comment stream, plus the digest pinning rulings already perform,
plus reducer-authored tombstones.** No checkpoint family, no chain, no anchor,
no store the reducer must maintain ahead of need. Five components.

**1. Replay reads creation-time bodies from platform memory.** For a comment
never edited, the creation-time body is the current body, exactly as today. For
an edited comment, it is the earliest revision body from `userContentEdits`,
whose `diff` was measured to carry complete revision bodies (#153). An edit to a
protocol message therefore stops being fatal at all: replay proceeds on the body
as created and records a notice naming the edit. This is not leniency; it is
reading the receipt the platform already holds. A protocol message whose
revision history carries a deleted revision (`deletedAt` populated) has had its
receipt destroyed by an attributable act, and that message fails closed,
naming `deletedBy`.

**2. Fail-closed is scoped to the affected message.** Section 2.2 already says
an edit or deletion "makes the affected protocol history unreplayable", and the
superseded record left the scoping question open. It is decided here: the
affected protocol history is the affected message and everything that depends on
it, not the session. The #144 class of denial of service, any account ending a
live session by touching its own comment, does not survive this sentence plus
component 1.

**3. The deletion guard writes a tombstone before failing.** The deployed guard
that already reads a deleted comment from the trigger payload
(`open-table-reduce.py`, bundle builder) currently fails and forgets: the run
after it was measured re-emitting a ruling against current permissions (#154).
Instead, the reducer first writes a tombstone comment recording the deleted
comment's numeric id, numeric author id, trusted `created_at`, and the canonical
digest of the deleted body computed from the payload, plus whether that body
carried an `open-table` block. The event payload's one-run memory becomes a
durable record in the stream. A tombstoned protocol message is a deletion with
evidence: replay fails closed on it, scoped as component 2 says, naming the
comment. Deleting the tombstone itself is possible only for an insider, and
that act fires the very event component 4 consumes.

**4. Any `CommentDeletedEvent` whose deleted author is the principal fails the
session closed.** The principal never deletes its own comments, by contract. The
event was measured firing on exactly this case, carrying `deletedCommentAuthor`
(#154), and it belongs to the undeletable record class (#153). The rule is
evaluated during replay from the timeline, which section 2.5 already declares an
ordered input, so it does not depend on the run that saw the deletion surviving:
every later run re-derives it. This is the insider detection the checkpoint
chain bought with a family, a chain, and an anchor question, supplied by one
comparison against a record the insider cannot erase.

**5. The `settled` ruling pins the proposal it references.** Rulings already
bind `source-comment-id` and `source-digest` under section 4.16, and section 9.1
already fails closed on a missing or mismatched source. The ruling emitted for a
`settled` message additionally records the digest of the referenced proposal
comment and quotes its body in the ruling prose. A participant who deletes their
own proposal after settlement is thereby detected (the ruling's reference no
longer resolves) and the deliberative content survives in the ruling. What is
ruled can no longer be silently unwritten by its author, and the record of what
was decided does not depend on the platform remembering the source.

**The checkpoint family, its chain, and its anchor question are withdrawn.**
The superseded record was documentation only; no implementation exists to
remove. The tip problem it could not close does not transfer: there is no
reducer-maintained store in the stream, so there is no newest window to seal
and no anchor decision to make. The #153 anchor measurements (labeling and
rename events survive everything, actors are server-populated, label names cap
at 50 characters) stay on the record as measurements, needed by nothing here.

### The five obligations of section 2.3

*Minimum permissions*: `issues: write`, unchanged. The design adds GraphQL
reads (`userContentEdits`, timeline events) under the same workflow token, and
whether that token sees the two fields it needs is the unmeasured row of the
method table, gated on the implementing pull request's CI probe.

*Retention*: revision history lives exactly as long as its comment, so the
receipt for a message outlives every edit but not the message's deletion, which
is the case components 3 to 5 cover with records of their own: tombstones and
rulings are comments retained for the life of the issue, and the insider
deletion event is undeletable platform history. Ruled content additionally
survives its source through the digest and quotation pinned at ruling time.

*Concurrent-write behavior*: the store's only reducer-written parts, tombstones
and rulings, are additive assertions by a single principal; platform memory is
written by the platform. Two tombstones for one deletion assert the same fact
and are idempotent by content; the single-ruling rule of section 9.1 is
unchanged. No run reads state accumulated by another run, so the reducer stays
a pure function of inventory plus trusted context and the measured
single-pending-run cancellation stays harmless.

*Non-circularity*: replay authority is GitHub's trusted metadata, the same
class section 2.5 already names: revision nodes, timeline events, trusted
timestamps and actor ids. The issue body remains a rebuildable cache with no
evidentiary role, and nothing is derived from the projection.

*Fail-closed recovery*: for every message that was ruled, referenced, or is
still present, tampering is either survivable with a notice (an edit), or
detected and refused naming the actor or the comment (a revision deletion, a
tombstoned deletion, an insider deletion of principal output, a settled
proposal withdrawn). The declared residual is one case: an author deletes their
own protocol message before any ruling or reference binds it, and the
deletion-triggered run is cancelled by the queue before writing the tombstone
(the #143 window). Self-deletion leaves no platform trace (#152), so that
message becomes indistinguishable from one never posted. This is a retraction
of unacted-on input by its own author, the lowest-value asset in the model, and
it is declared rather than rounded away.

**Point I closes with this record.** Section 2.3 asks for a separate accepted
decision defining the store and its four operational properties; this is that
decision. Two things do not follow from it and are stated so they cannot be
inferred: the deployment claims no reducer conformance until the specification
revision below and the implementation exist, section 1.7's standing rule; and
the residual above is part of the store's definition, not a defect discovered
later.

### The probe suite is an obligation, not an aspiration

The properties this design rests on are not contractual. `CommentDeletedEvent`
is absent from the superseded record's probe of 2026-08-04 and fired on
2026-08-05, which cuts both ways: the platform's behavior moved once within two
days. The implementation this record authorises includes a scheduled platform
contract probe suite that re-measures, against sacrificial fixtures: that
`userContentEdits` still returns complete revision bodies; that a moderator
deletion still fires `CommentDeletedEvent` with `deletedCommentAuthor`; that
timeline events still survive source deletion; and that the workflow token
still reads what the implementation reads. A probe that fails does not repair
anything: it fails the suite and names the property, so a platform change is a
red build instead of a silent hole. Ruled history stays safe either way,
because digests are pinned at ruling time and never depend on platform memory.

**The scheduled daily pass survives supersession, re-motivated.** Its first
reason, the #143 stale-session case, is unchanged: nothing else polls. Its
second reason changes for the better: component 4 is evaluated from the
timeline during any replay, so the scheduled pass now re-derives insider
deletion evidence that an event-driven run may have missed, instead of
narrowing a receipt window. The concurrency-group caveat recorded in the
superseded record (the group key must come from the selected issue, not from
`github.event.issue.number`, which is empty on a schedule) carries over
unchanged.

### The specification revisions this record authorises

One revision of `docs/specs/open-table-v0.md`, smaller than the one the
superseded record authorised, plus the issue housekeeping that follows:

- **Section 2.2**: fail-closed scoped to the affected message; replay defined
  over creation-time bodies read from platform memory; an edit is a recorded
  notice; a revision deletion on a protocol message is an attributed, scoped
  failure. The two-readings ambiguity about receipt fields dissolves: there is
  no receipt object to put fields inside.
- **Section 2.3**: the store is the one this record defines, with its five
  obligations as answered above and the residual as declared.
- **Tombstone encoding**: either a minimal reducer-output family or a reuse of
  the `invalidated` ruling decision, decided in the revision under two recorded
  constraints: section 3.2 permits one `open-table` block per comment, and
  `invalidated` must be the sole ruling for its source, which fits a
  never-ruled deleted comment and cannot serve an already-ruled one, whose
  missing source is already fatal under section 9.1.
- **Section 4.16 / 9.1**: the `settled` ruling's pinned proposal digest and
  quotation, as component 5.
- **Issue #130**: point I recorded as closed by this decision; point 2 updated
  to the scoped fail-closed reading.

## Consequences

The #144 denial of service closes entirely, not partially. Under the superseded
design an account that posted a well-formed protocol message, waited for its
receipt, then edited it, still ended the session; that was section 2.2 working
as then designed. Under this design the same act produces a notice and a replay
on the creation-time body. No participant act on the participant's own comment
ends a session any more; the acts that still fail things closed are a revision
deletion (attributed, scoped), a deletion of a protocol message (tombstoned,
scoped), and an insider deleting principal output (session-fatal, evidenced).

The liveness cost the superseded record paid disappears. There is no
receipt-before-act window, so a participant who edits their message seconds
after posting loses nothing; the reducer reads the body as created.

Noise falls to zero on the happy path. The superseded design cost one reducer
comment per protocol message; this one writes nothing extra while nobody
tampers, one tombstone per deletion, and some prose growth in `settled`
rulings. The property #143 measured, that conversation in a session issue is
free, is preserved exactly.

Auditability has a measured shape rather than an assumed one. Anyone can see
that a moderator-class deletion happened and when, anonymously. Naming the actor
requires access, and `deletedCommentAuthor` requires an authenticated GraphQL
read. The projection therefore quotes the evidence it acted on (event id,
timestamp, deleted author) so that an anonymous auditor reads the reducer's
finding even where the platform masks the underlying actor, and an
authenticated auditor re-derives it.

The trust boundary is unchanged: a compromised principal token can author false
tombstones and false rulings exactly as it always could. The store defends the
session's history against everyone else. External witnessing (a second
repository observing this one, the Certificate Transparency shape) remains the
extension if the insider threat ever becomes real, and nothing here forecloses
it.

The dependency profile changes shape: less machinery of our own, more reliance
on measured but non-contractual platform behavior. That trade is taken
deliberately, priced by the probe suite, and hedged by ruling-time pinning, so
the decided record never depends on the platform's memory.

This record, like its predecessor, records no implementation. It authorises the
specification revision above, then the reducer and workflow changes (creation
body replay, tombstone write, insider rule, settled pinning, scoped failure,
with a test fixture per row of the threat-model table), then the probe suite.

## Alternatives considered

The superseded checkpoint chain: rejected on three measured grounds. Its
central deletion premise is false for the only actor able to delete other
people's comments; its machinery defends against the insider it concedes it
cannot stop; and its availability cost, one lost message per pre-receipt edit
and one comment of noise per protocol message, bought protection the platform
provides natively. What it got right, the excluded homes, the runtime
measurements, the #144 reframing, is inherited by this record's context.

Both stores at once, checkpoints plus platform memory: rejected. Redundant
evidence for every covered case, the chain's unsolved tip problem retained for
no gain, and double noise.

The label-event anchor (#153): dissolved rather than rejected. It existed to
seal a store that no longer exists. The measurements stand; the 50-character
cap and the unmeasured question of whether `issues: write` applies a label
stand with them, needed by nothing current.

GH Archive as witness or recovery channel: rejected on measurement. One event
in sixteen archived for this repository in the hours probed, and the deleted
comment it would have been wanted for is exactly what it lacks.

Fail-open with notices only, no fail-closed anywhere: rejected. What a settled
point settled, and what text a ruling ruled on, are real assets; component 5
and section 9.1 protect them at zero cost to availability.

A GitHub App with its own store: unchanged graduation path when a second
repository adopts the protocol, and not before.

## Open questions

*Does the workflow token read what replay needs?* `userContentEdits` and
`deletedCommentAuthor` under `GITHUB_TOKEN` are unmeasured, the one open row in
the method table. The implementing pull request's CI carries the probe, and a
negative answer reopens the read-path design (a separate read-only token would
be a new permission decision), not the store's shape.

*What is a moderator deletion of a participant's comment?* Component 4 covers
the principal's output; a `CommentDeletedEvent` naming a participant as deleted
author is measured, durable evidence too. Whether replay treats it as a notice
or as a scoped failure when it cannot be matched to a tombstone belongs to the
specification revision, which owns fail-closed granularity.

*Tombstone family or `invalidated` ruling?* Sent to the revision with the two
constraints recorded above.

*How much of the proposal does a `settled` ruling quote?* The digest is fixed;
whether the prose quotes the body verbatim or excerpts it is a size and
readability question for the revision, not a correctness one.
