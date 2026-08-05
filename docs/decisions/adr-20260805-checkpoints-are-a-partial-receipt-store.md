---
status: superseded
date: 2026-08-05
superseded-by: adr-20260805-platform-memory-is-the-receipt-store.md
---

# Reducer-authored checkpoints are a partial receipt store and point I stays open

## Context

Section 2.3 of the Open Table v0 specification requires a separate accepted
decision before any Action deployment can claim reducer conformance. That
decision must define the durable, authenticated, non-circular GitHub-resident
store for creation receipts and deletion evidence, together with its minimum
permissions, retention, concurrent-write behavior, and fail-closed recovery. It
is open point I of issue #130.

This record does not close that point. It decides everything about the store
that can be decided without an anchor, states in one place why the anchor
cannot come from the comment stream, and leaves point I open with a narrower
question than it started with. The reason for publishing a partial answer
rather than a complete-looking one is given at the end of the decision, and it
is the same reason the 2026-08-04 record refused to write a first-observation
digest into `created_body_digest`.

Four homes are already excluded, and each exclusion was measured rather than
assumed. The issue body is a rebuildable cache under section 2.6, so drawing
replay authority from it is circular. The repository would require
`contents: write`; the workflow token carries `issues: write` and nothing else,
and on a public repository whose workflow any commenter can start, widening it
to push rights is the one change that turns a noisy session into a
supply-chain problem. Action caches and artefacts are retention-bound, and a
store that expires is not durable protocol authority. And GitHub exposes no
signal for a deleted comment, which #152 re-measured against a schema that had
changed since the first probe: `CommentDeletedEvent` is now a member of the
`IssueTimelineItems` union, its fields are `actor`, `createdAt`, `databaseId`,
`deletedCommentAuthor` and `id` so it names no comment, and it does not fire.
A comment was created and deleted on a service issue; the timeline went to
`totalCount: 0`, an explicit `itemTypes:[COMMENT_DELETED_EVENT]` filter
returned zero, and the REST timeline was empty. A deletion is an absence, not
an event, so deletion evidence has to come from remembering what existed.

That a removal is unobservable does not mean that nothing is durable, and #153
measured the difference rather than inferring it. A `LabeledEvent` survives
removing the label from the issue and survives deleting the label from the
repository: after every probe label had been deleted, the issue timeline still
returned the labeling records with their actor and with `label.name` resolving
to a label that no longer existed. No mutation among the 258 in the schema
addresses a timeline event; the actor is populated server-side and the API
rejects one supplied by the caller; repeated applications produce distinct
records rather than collapsing. A `RenamedTitleEvent` behaves the same way and
carries a payload of arbitrary length, while a label name is capped at 50
characters and cannot hold a hex SHA-256. This record does not build on that
measurement, and the decision says why. It is stated here because the
alternative was to assert that nothing outside the comment stream endures,
which would have been false.

The first live session, #143, measured three properties of the runtime that
decide the shape of any answer.

Reducer output cannot wake the reducer. Comments authored with the workflow's
own `GITHUB_TOKEN` create no workflow runs, and across the session's runs not
one came from a reducer comment. A store that needs a periodic write needs a
trigger of its own and cannot obtain one by commenting.

Recovery is entirely event-driven. A run cancelled after its source comment
existed and before any write left the projection stale with nothing in the
issue saying so, and the next event rebuilt everything in one pass. A session
whose last event dies therefore stays stale indefinitely, because nothing
polls. That is an argument for a periodic pass rather than a detail of one.

Runs serialise per issue, but GitHub's queue holds exactly one pending run per
group, so a third event in flight cancels the pending one. Full replay is what
makes that harmless, and it stops being harmless the moment any part of the
reducer becomes incremental. A store that accumulates state across runs is
exactly such a part, and this is the constraint that narrows the design most.

Issue #144 then changed what the point is for. Without receipts the reducer
cannot tell whether an edited comment used to be a protocol message, so it
checks every comment in the inventory for edit signals, including comments
carrying no `open-table` block. Editing any of them ends the session with no
recovery. On a public repository that costs one comment by any account GitHub
permits to comment, and it is reachable by accident by a participant fixing a
typo. Point I is therefore an availability problem and not only a conformance
obligation, and a design that closes the conformance half while leaving a live
session killable by a stranger has closed the smaller half.

## Decision

The receipt store is the reducer's own append-only `checkpoint` comments in the
session issue. It uses the same `issues: write` token, the same comment stream,
and the same trusted GitHub metadata that already makes an edit detectable.
Nothing else is added, and no new permission is bought.

**What a receipt is.** A receipt binds a numeric comment id to three values
taken from trusted GitHub context at the observing run: the canonical digest of
the complete comment body as section 3.7 defines it, the trusted `created_at`,
and the numeric author actor id.

**Which of section 2.2's fields are persisted, and the reading of section 2.2
that this rests on.** Section 2.2 requires a replay adapter to "capture an
authenticated GitHub comment-creation event receipt containing the original
complete-body canonical digest, plus trusted `created_at`, `updated_at`, and
GitHub GraphQL `lastEditedAt` metadata". That sentence carries two readings and
this decision does not get to pick one silently. On the wider one the receipt
itself contains all four values. On the narrower one the adapter captures a
receipt containing the digest and captures the three metadata fields alongside
it, which is what the next requirement then uses when it says replay must match
the body to the receipt digest while `lastEditedAt` is null and `updated_at`
equals `created_at`, a test that means nothing except against a live comment.

**This decision adopts the narrower reading, records that it is a reading
rather than a settled fact, and sends the ambiguity to the specification
revision it authorises.** Under it the digest, the trusted `created_at` and the
author id are persisted in the receipt, while `updated_at` and `lastEditedAt`
are read live from trusted context at every replay.

The reason is that the two unpersisted fields would record constants. The
admissibility rule below records a receipt only when `lastEditedAt` is null and
`updated_at` equals `created_at`, so their stored values are fixed by
construction and say nothing an auditor could not derive from the receipt
existing at all. Their live form is the edit detector: a comment still present
whose digest matches but whose `lastEditedAt` is now set was edited and
reverted, and that is fatal under section 2.2 exactly as a mismatch is.

If the revision settles on the wider reading instead, a receipt carries two
more fields whose values are `created_at` and null, and the cost is encoding
size rather than correctness. Nothing else here changes. What is not available
is leaving the record asserting that the current text already permits the
split, which is what an earlier draft did.

That is what makes the division sufficient once the source is unavailable. When
a receipted comment is absent from the inventory there is no live metadata to
compare against and no repair: the session fails closed on the absence itself.
What the store must supply at that moment is not a comparison but an
identification, and a comment id, its author and its creation time are what the
failure report needs to say which message vanished and whose it was.

The id of the run that observed a comment is deliberately not persisted. It
would point into workflow logs, which are retention-bound, and section 2.3
excludes retention-bound stores from being evidence. A pointer into one is no
more durable than the thing it points at. An earlier draft of this record
carried it; it is dropped here on that ground rather than silently.

**A receipt is admissible only when the comment is provably unedited at
observation.** The reducer records a receipt only when GraphQL `lastEditedAt`
is null and trusted `updated_at` equals `created_at` at the observing run. This
is what makes an observation receipt a creation receipt in substance rather
than in name: any change between creation and observation would have set
exactly the fields the admissibility rule tests, so a digest admitted under it
is the body as created. The authority is GitHub's trusted metadata, not the
reducer's word, and a later auditor re-checks the same two fields against the
same comment. This does not reverse the refusal recorded on 2026-08-04 to write
a first-observation digest into the section 2.8 `created_body_digest` field: it
supplies the metadata proof whose absence made that value a bare claim.

**Every protocol comment is receipted, including the reducer's own.** A comment
is receipted when it carries an `open-table` fenced block at first observation.
That is the whole of section 4, not the participant half of it. The families
requiring a ruling are `configuration`, `settled`, `claim`, `renewal`,
`release`, `handoff`, `cancellation`, `result`, `review-request` and `verdict`;
the reducer's `RULING_REQUIRED` set enumerates exactly those ten. Everything
else in section 4 receives no ruling at all: `contribution` and `proposal`,
for which section 4.17 states no permission predicate; `expiration`, which
section 4.12 defines as authenticated reducer output; `ruling` itself; and the
`checkpoint` family this decision adds. An earlier draft named only the first
two as the coverage gap. That was wrong by four families, and the two it missed
are both reducer output, which is the half where a gap is worst.

Prose-only and header-only comments are not protocol messages under section
3.4 and are never receipted. That is what keeps an ordinary human conversation
in a session issue free, which is the property #143 measured.

**A ruling is a receipt for its source and is not evidence of itself.** This
correction matters enough to state at length, because an earlier draft claimed
the opposite and built on it.

While a ruling is present it does bind its source: section 4.16 requires
`source-comment-id` and `source-digest`, and section 9.1 makes a missing source
or a digest mismatch fail closed. What section 9.1 does not do is make a
*missing ruling* detectable, and the implementation shows why. `collect_rulings`
raises only when a ruling that is present points to a source that is gone. A
ruling that is itself deleted is not among the records at all, so its source is
absent from the set of already-ruled sources the bundle builder assembles, and
the builder then calls the live collaborator-permission endpoint for that
source's author and the reducer emits a replacement ruling through
`decision_for`.

The result is worse than a lost record. Section 9.1 says replay reads recorded
permission outcomes and must not consult current permissions, and deleting a
ruling makes the reducer do exactly that: the historical outcome is recomputed
from whatever access that account has today. A ruling therefore cannot be its
own deletion evidence, and rulings are receipted in checkpoints like every
other protocol comment. The absence of a previously receipted ruling is fatal,
which is the section 9.1 outcome the current implementation cannot reach on its
own.

**Every run receipts what it observes before it acts on anything.** A run plans
its checkpoint and applies it ahead of any ruling, expiration or projection
write. The invariant this buys is the one the availability half rests on: a
protocol message that any run acted on was receipted by a run before it was
acted on. A crash after the checkpoint and before the rulings is harmless,
because the receipt exists and rulings are already idempotent under the
existing-ruling search of section 9.1.

The reducer's own output is covered by the same rule one run later. Run *n*
writes rulings; run *n+1* observes them and receipts them in its opening
checkpoint, before it reads them as rulings. So no run acts on a reducer
comment it has not first receipted, and the rule needs no exception for the
principal's own writes.

**Therefore a comment absent from the store was acted on by no run, and an edit
to it is not fatal.** Replay excludes it as prose and records a notice, exactly
as section 4.16 already requires for a ruling-shaped comment by a non-principal,
which it excludes while forbidding the bundle to be rejected because of it.
This is the narrowing that section 3.4 always licensed and that #144 could not
reach, and it is not narrowing by a comment's current shape: the store records
what the comment was at first observation, so an attacker who edits an
`open-table` block out of a genuine message is caught by the receipt rather
than believed.

**An edit or deletion of a receipted comment stays fatal.** That is section 2.2
working as designed, not a defect this decision should soften. What changes is
only which events count as tampering with protocol history.

**Deletion evidence is the set difference.** A receipted comment id absent from
the current inventory is a deletion, and the projection can name which comment,
by whom and from when rather than reporting an unexplained failure. The
workflow already triggers on `issue_comment: deleted`; today that wakes a
reducer with nothing to compare against, and the store is the missing memory
rather than a missing trigger.

**The chain protects every checkpoint except the most recent one, and that
exception is structural.** Each checkpoint names every checkpoint comment id
and digest it observed that no earlier checkpoint already names, so a deleted
or edited checkpoint breaks a link and fails closed instead of shrinking the
store silently.

The newest checkpoint is not covered, and it cannot be made covered from
inside the stream. Sealing it requires appending another checkpoint, which is
then itself the newest and uncovered; the operation that closes the gap
recreates it, so no number of repetitions converges. The same holds one level
down for ordinary receipts: the reducer comments a run writes are receipted by
the next run, so between a run's last write and the next run's opening
checkpoint they are unreceipted, and a session's final writes are never
receipted at all because no run follows them.

This is one property with two faces, not a residual and an edge case. A store
that lives in the stream it protects can never cover its own most recent
write. Deleting inside that window rolls the store back by whatever only it
recorded, and the comments it alone receipted become indistinguishable from
comments no run observed, which turns the exclusion rule above from a
protection into a hole. Whatever closes it has to come from outside the comment
stream, and that is where what remains of point I now sits.

Nor does the permission boundary contain it, which an earlier draft claimed it
did. Deleting an issue comment is within `issues: write`, which is the token
the workflow already holds and the access every maintainer already has. The
window is narrow and the actor able to exploit it is not the anonymous
commenter this decision exists to stop, but "narrow and privileged" is a
description of exposure, not a fail-closed property, and section 2.3 asks for
the property.

**What this decision buys, separated by who is attacking.** An account with no
repository access, which is every account GitHub permits to comment on a public
repository, is the attacker #144 reported. For that attacker the store closes
the case as reported: editing a comment that carries no `open-table` block no
longer ends a session, because that comment is in no receipt and influenced
nothing. An account with `issues: write` is a different attacker, and against
that one the store narrows rather than closes. It makes every deletion outside
the newest window detectable, including deletion of a ruling, which today is not
merely undetected but silently re-decided against current permissions. It leaves
the newest window open.

**The five obligations of section 2.3, and the one that is not met.**

*Minimum permissions*: `issues: write`, unchanged from the current deployment.
The store deliberately buys no new scope, and this is the property that
excludes every alternative home.

*Retention*: the lifetime of the issue. Checkpoints are never pruned, edited or
deleted by the reducer, and the store is as durable as the deliberation record
it attests to, which is the sense in which it is not retention-bound.

*Concurrent-write behavior*: checkpoints are additive assertions by a single
principal, so two concurrent checkpoints are both true and the store is their
union. Two checkpoints naming the same parent are a fork, not a conflict, and
the next checkpoint closes it by naming both. Two different digests for one
comment id is tamper evidence and fails closed. No run reads state from another
run except by replaying comments, so the reducer stays a pure function of the
inventory and the single-pending-run cancellation stays harmless.

*Non-circularity*: the store is a set of append-only comments whose authority
rests on GitHub's trusted metadata for those comments. It is never derived from
the projection, and the issue body remains a rebuildable cache with no
evidentiary role.

*Fail-closed recovery*: **not met.** A broken chain link, a digest conflict, a
receipted comment missing from the inventory, and an edit to a receipted
comment each make the session unreplayable and are reported naming the comment
involved. That is the whole of the store except its newest window, and inside
that window a deletion is not detected rather than being detected and refused.
Fail-closed is not a property that holds in most of the range: a hole an actor
can aim at is the case the property exists for.

**So section 2.3 is not satisfied and point I stays open.** This deployment
still must not represent itself or any session as reducer-conformant, which is
section 1.7's standing rule for a deployment operating with declared unmet
guarantees, and it is unchanged by this record.

What has changed is the kind of question that is left. Point I began as "find a
durable, authenticated, non-circular GitHub-resident store", and the part that
looked hardest was whether an anchor could exist at all. It can, and #153
measured it. So what remains is a design rather than a search, and it is
deliberately not done here: choosing the record class, deciding whether it
carries a count or a digest and in what encoding, fixing when it is written
relative to the comment it seals, and answering section 2.3's five obligations
for the anchor itself is a second decision of the same size as this one. It
also rests on a precondition that is documented rather than measured, that a
token holding only `issues: write` can apply a label, and measuring that is the
first step of that work rather than a detail of it.

Everything else point I asked for is decided above and does not need revisiting
when the anchor is chosen. That is the argument for publishing this half now
rather than holding it back: the anchor decision inherits a settled receipt
shape, a settled domain and a settled ordering rule, and has one question left
to answer.

Publishing this as a closed point was available and is refused. The store would
have looked complete, the newest-window gap would have been a footnote, and
every later piece of work would have inherited a conformance claim the store
cannot support. That is the failure mode the 2026-08-04 record already declined
once when it refused to write a first-observation digest into
`created_body_digest`, and a decision record with an overstated conclusion
passes its own review forever.

**A scheduled trigger is added and it runs daily.** Events already receipt what
they observe. The schedule exists for the case #143 measured, a session whose
last event died and which therefore stays stale forever, and it is the trigger
of its own that reducer output cannot provide. Daily is a target cadence rather
than a guarantee: GitHub delays or drops scheduled workflows under load and
disables them in inactive public repositories, so the pass shortens the window
in which a session's newest writes are unreceipted without bounding it. A
scheduled run has no issue context, so it selects sessions by the
`open-table/session` label; the concurrency group must then be keyed on the
issue it selected, because today's expression reads `github.event.issue.number`
and would evaluate to empty on a scheduled run, collapsing every session into a
single group.

**A session with a receipt gap is processed and is not conformant.** Refusing to
process it would hand anyone able to create a gap the denial of service this
decision exists to remove, which would reintroduce the defect through the door
marked safety. The gap is stated in the projection, so an incomplete session is
visibly incomplete rather than quietly treated as whole.

**The checkpoint carries no digest for the prose comments it observed.** It
would restore the per-comment noise this design avoids, and the exclusion rule
does not need it: a comment carrying no `open-table` block at first observation
influenced no ruling and no projection, so its absence from the store is already
the right answer rather than a missing record.

**The envelope grammar batches scalars and has never batched tuples.** Section
3.3 requires header values to be single-line and non-empty and requires each
key to occur once, and section 3.8 makes every cross-message reference a single
numeric comment id. That is not a prohibition on sets: section 4.1 already
defines `expected-actors` as a comma-separated, whitespace-free list of unique
numeric GitHub user ids packed into one single-line value, and the reducer
parses it by splitting on the comma. A checkpoint carrying many comment ids in
one value is therefore inside the grammar's existing idiom and needs no
amendment.

What has no precedent is that a receipt here is a triple: a comment id bound to
a digest, a timestamp and an author id. Packing tuples into one value needs a
second delimiter that no field uses today, and spreading them across
positionally aligned fields makes correctness depend on an ordering the grammar
never asks a reader to trust. This decision does not settle the encoding,
because it belongs with the specification revision it authorises, and the
choice has no bearing on anything decided above. It records that one receipt
per comment needs no new syntax and is the ruling's own shape, at the cost of
one reducer comment per protocol message; and that any batched shape has to
answer the tuple question first.

The receipts cannot move into the prose either: section 3.1 puts the protocol
surface in the header block and leaves the prose for people, and where the
specification has had to say so outright, as section 4.1 does for the
configuration values, it forbids reducers to derive them from free prose.

## Consequences

Reducer conformance does not become reachable, and this record is the second
in a row to say so. The 2026-08-04 record declared the reducer deliberation-only
and not conformant; this one removes most of what stood between the deployment
and conformance and leaves exactly one of section 2.3's five obligations unmet.
That obligation is **fail-closed recovery**, unmet because a deletion inside the
newest unreceipted window is not detected rather than being detected and
refused, and it is the same one named in the decision above. Sessions that
predate the store do not become conformant retroactively in any case, which
section 2.2 already forbids.

The denial of service in #144 closes for the case it was reported for and for
the attacker it was reported against: a prose-only comment, edited by any
account permitted to comment, no longer ends a session. It does not close
entirely. An account that posts a well-formed `contribution` or `proposal`,
neither of which requires repository write access under section 4.17, waits for
it to be receipted, and then edits or deletes it, still ends the session,
because that is section 2.2 applied to genuine protocol history. Whether
fail-closed should be scoped to the affected message rather than the session,
which section 2.2's own wording appears to allow, is a narrower question and is
left open here rather than settled in passing.

A message edited before any run receipted it is excluded with a notice instead
of being admitted. A participant who edits their own protocol message within
seconds of posting it therefore loses that message rather than the session.
That is a liveness cost paid deliberately in exchange for the availability
gain, and it is visible in the projection rather than silent.

Noise rises for protocol-heavy sessions and does not rise at all for
conversation. Only comments carrying an `open-table` block are receipted, so the
property #143 measured, that humans can discuss a session in its own issue at no
protocol cost, is preserved. How far it rises is not yet fixed, because it
follows from the unresolved encoding question above, and the receipt domain
decided here makes the unbatched ceiling higher than the earlier draft's: every
protocol comment, not only the unruled ones, and the reducer's own output
counts. Against the measured baseline, #143 produced three rulings for nine
participant comments.

The trust boundary is unchanged and is worth stating plainly: a compromised
workflow token can author a false checkpoint, exactly as it can author a false
ruling. The store does not defend against the principal; it defends the
session's history against everyone else, and only outside its newest window.

This decision records no implementation. The work it authorises is a
specification revision adding the reducer-authored `checkpoint` family, and the
reducer and workflow changes that follow it. Three constraints bound that
revision and are worth carrying into it rather than rediscovering. The
`checkpoint` must be its own comment, because section 3.2 requires exactly one
`open-table` fenced block per comment, so it cannot be folded into a ruling.
The revision must choose how a checkpoint encodes a set of receipts, which is
the tuple question above. And it must settle section 2.2's wording on whether
the three metadata fields belong inside the receipt or alongside it, because
this decision reads that sentence narrowly and a reading is not a rule.

The anchor is a separate decision and this one is a prerequisite for it rather
than a substitute. It starts from a measured set of candidate record classes
rather than from an open search, and from a settled receipt shape, domain and
ordering rule.

## Alternatives considered

The issue body: rejected because section 2.6 makes it a rebuildable cache, so
using it as replay authority is circular, which section 2.3 names explicitly.

A file in the repository: rejected because it requires `contents: write` on a
public repository whose workflow any commenter can start, and because every
checkpoint would become a commit on the default branch.

Action cache or artefacts: rejected because they are retention-bound rather
than durable, and because an auditor cannot read them, so evidence that only
the deployment can see is not evidence.

A GitHub App with its own database: rejected because it leaves the standing
non-goal of no App, no hosting and no service, and because the graduation path
to an App is already recorded as beginning when a second repository adopts the
protocol.

Receipting every comment rather than only protocol messages: rejected because
it costs one reducer comment per human comment and destroys the measured
property that conversation in a session issue is free, while buying nothing.
A comment that carried no `open-table` block at first observation influenced no
ruling and no projection, so its absence from the store is already the right
answer.

Narrowing the edit check by a comment's current shape, with no store at all:
rejected for the reason #144 gives. An attacker would edit the `open-table`
block out of a genuine message and the reducer, seeing prose, would accept the
session as intact.

Declaring the store complete and the newest-window gap a residual: rejected.
It is the shape of the answer that would let this record be titled as closing
point I, and it is false in the way that costs most, because a conformance
claim is inherited by everything built on it.

Deciding nothing until an anchor exists: rejected because the receipt shape,
the receipt domain and the ordering rule are decidable now, are needed by the
anchor decision rather than dependent on it, and are what makes the remaining
question a single one.

Deciding the anchor in this record and closing point I: rejected, though it was
the closest call here. #153 makes it look reachable, and a reviewer asked for
it conditionally on it being possible. It is a second decision of the same size
as this one, with its own record class to choose, its own encoding question,
its own place in a run's write order and its own five obligations under section
2.3, and it rests on a precondition nobody has measured yet. Folding it in
would attach an unmeasured claim to a settled one and make the reviewed part
hostage to the unreviewed part.

Doing nothing until a second repository forces an App: rejected because it
leaves a live session killable by a stranger for as long as that takes, which
is the half of point I that #144 added.

## Open questions

*What anchors the newest window, and how?* This is what remains of point I, and
it is the only thing standing between this store and section 2.3. The comment
stream cannot answer it, for the structural reason given in the decision, and
GitHub's deletion signal cannot either, since #152 measured that a deleted
comment leaves no trace at all. The answer is a record of a different class,
and #153 measured that the class exists: a labeling event and a title-rename
event each survive every removal the schema offers, carry an actor the caller
cannot supply, and accumulate rather than collapse. What is undecided is which
of them; whether it carries a count or a digest; how that is encoded, given
that a label name is capped at 50 characters while a hex SHA-256 is 64 and only
the title channel takes an arbitrary payload; and where the anchor write sits
in a run's order relative to the checkpoint it seals. Undecided too, and first,
is whether a token holding only `issues: write` can apply a label at all. That
is documented and was not measured, and the whole anchor rests on it.

*How does a checkpoint encode a set of receipts?* Batching many values into one
single-line field is already precedented by `expected-actors` in section 4.1, so
the question is not whether a checkpoint may carry more than one receipt. It is
that a receipt is a triple and the precedent is a flat list of scalars. Whether
to accept one receipt per comment, introduce a second delimiter, or split the
triple across positionally aligned fields belongs with the specification
revision this decision authorises, and it changes cost rather than correctness.

*Should fail-closed be scoped to the affected message rather than the session?*
Section 2.2's own wording scopes it to "the affected protocol history", so the
narrower reading may already be the correct one. It is not settled here because
it changes the behaviour of the existing reducer for every session, not only for
sessions with a store, and it deserves its own record rather than a sentence in
this one.
