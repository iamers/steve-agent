---
status: accepted
date: 2026-08-05
---

# Creation receipts and deletion evidence live in reducer-authored comments

## Context

Section 2.3 of the Open Table v0 specification requires a separate accepted
decision before any Action deployment can claim reducer conformance. That
decision must define the durable, authenticated, non-circular GitHub-resident
store for creation receipts and deletion evidence, together with its minimum
permissions, retention, concurrent-write behavior, and fail-closed recovery. It
is open point I of issue #130, and this is it.

Four homes are already excluded, and each exclusion was measured rather than
assumed. The issue body is a rebuildable cache under section 2.6, so drawing
replay authority from it is circular. The repository would require
`contents: write`; the workflow token carries `issues: write` and nothing else,
and on a public repository whose workflow any commenter can start, widening it
to push rights is the one change that turns a noisy session into a
supply-chain problem. Action caches and artefacts are retention-bound, and a
store that expires is not durable protocol authority. And GitHub exposes no
signal for a deleted comment: a comment was created and deleted on a service
issue, and neither the REST timeline nor GraphQL `timelineItems` recorded it.

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

The store is the reducer's own append-only comments in the session issue: the
`ruling` comments it already writes, plus a new chained `checkpoint` family that
covers what rulings do not reach. Nothing else is added: the same
`issues: write` token, the same comment stream, and the same trusted GitHub
metadata that already makes an edit detectable. Naming the existing half first
matters, because it is the difference between adding a store and finishing one.

**Part of the store already exists, and this decision names it rather than
inventing a parallel one.** A `ruling` already binds `source-comment-id` to
`source-digest` under section 4.16, is authored by the reducer principal, and is
already load-bearing under section 9.1, which fails closed on a missing source
or a digest mismatch. Every permission-sensitive message therefore already
carries a durable authenticated receipt in an append-only comment. What is
missing is coverage, not a mechanism: `contribution` and `proposal` are not
permission-sensitive under section 4.17, so they receive no ruling and no
receipt. The `checkpoint` family exists to close exactly that gap, and it
inherits the ruling's binding, a comment id to a digest, instead of inventing a
second way to say the same thing. What it cannot inherit is how many bindings
fit in one comment, which the next paragraph takes up.

**What a receipt is, and for which comments.** A receipt binds a numeric comment
id to the canonical digest of the complete body of that comment, as section 3.7
already defines the digest. A receipt is recorded only for a comment that
carries an `open-table` fenced block at first observation. Prose-only and
header-only comments are not protocol messages under section 3.4 and are never
receipted, which is what keeps an ordinary human conversation in a session issue
free.

**The envelope grammar already batches, and the real constraint is narrower than
it first appears.** Section 3.3 requires header values to be single-line and
non-empty and requires each key to occur once, and section 3.8 makes every
cross-message reference a single numeric comment id. That is not a prohibition
on sets: section 4.1 already defines `expected-actors` as a comma-separated,
whitespace-free list of unique numeric GitHub user ids, packed into one
single-line value, and the reducer already parses it by splitting on the comma.
A checkpoint carrying many comment ids in one value is therefore inside the
grammar's existing idiom and needs no amendment.

What the precedent does not cover is that a receipt is a **pair**, a comment id
bound to a digest, while `expected-actors` is a flat list of scalars. Packing
pairs into one value needs a second delimiter that no field uses today, and
splitting them across two positionally aligned fields makes correctness depend
on ordering, which the grammar never asks a reader to trust. So the open
question is not whether a checkpoint may batch, which it may, but how it encodes
a set of pairs.

The receipts cannot move into the prose either: section 3.1 puts the protocol
surface in the header block and leaves the prose for people, and where the
specification has had to say so outright, as section 4.1 does for the
configuration values, it forbids reducers to derive them from free prose.

This decision does not settle the encoding, because it belongs with the
specification revision it authorises. It records that one receipt per comment is
the shape that needs no new syntax at all and is exactly the ruling's shape, at
the cost of one reducer comment per unruled protocol message; that a flat packed
list is already precedented and would remove most of that cost; and that a
pair-valued field is the only option that asks the grammar for something it has
never done.

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

**The checkpoint is written before anything else the run writes.** A run
plans its checkpoint and applies it ahead of any ruling or projection write.
The invariant this buys is the one the whole design rests on: a protocol
message that any run acted on is receipted by that run. A crash after the
checkpoint and before the rulings is harmless, because the receipt exists and
rulings are already idempotent under the existing-ruling search of section 9.1.

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
the current inventory is a deletion, and the projection can name which comment
rather than reporting an unexplained failure. The workflow already triggers on
`issue_comment: deleted`; today that wakes a reducer with nothing to compare
against, and the store is the missing memory rather than a missing trigger.

**The chain covers the checkpoint half; the ruling half is already covered.**
Rulings are not members of the chain and do not need to be: section 9.1 already
makes a deleted or missing ruling fail closed, so the half of the store that
predates this decision is protected by a rule the specification already has. The
chain exists because a `checkpoint` binds no permission decision, so nothing in
the existing rules would notice one going missing.

**The chain protects the store from the same attack it detects, except at its
tip.** Each checkpoint names every checkpoint comment id and digest it observed
that no earlier checkpoint already names. A deleted or edited checkpoint
therefore breaks a link and fails closed, instead of shrinking the store
silently, which is the deletion problem one level up. The most recent checkpoint
is the exception, because nothing references it yet. Deleting it rolls the store
back by the receipts only it carried, and the comments it alone receipted become
indistinguishable from comments no run ever observed, which is the one case
where the exclusion rule above turns from a protection into a hole. Closing it
needs an anchor outside the comment stream, which is the durable-store problem
one level up again, so this decision does not claim to close it. What bounds it
is the permission: deleting a comment requires repository write access, so the
exposure is to a maintainer rather than to the anonymous commenter whose attack
this decision exists to stop. It is named here rather than left for a reader to
find, and it is the first thing an anchor design should address.

**Conformance becomes a property of a session, not of the deployment.** A
session is receipt-complete when every protocol message in its inventory carries
an admissible receipt. Labelling a session before its first comment is what
makes completeness attainable, though not automatic: a comment edited before any
run observed it is unreceiptable and leaves the session incomplete, which is the
same event the exclusion rule handles rather than a second failure. Only a
receipt-complete session may be represented as reducer-conformant; the
deployment claims nothing on its own.

The five obligations of section 2.3 are then answered as follows.

*Minimum permissions*: `issues: write`, unchanged from the current deployment.
The store deliberately buys no new scope, and this is the property that
excludes every alternative home.

*Retention*: the lifetime of the issue. Checkpoints are never pruned, edited or
deleted, and the store is as durable as the deliberation record it attests to,
which is the sense in which it is not retention-bound.

*Concurrent-write behavior*: checkpoints are additive assertions by a single
principal, so two concurrent checkpoints are both true and the store is their
union. Two checkpoints naming the same parent are a fork, not a conflict, and
the next checkpoint closes it by naming both. Two different digests for one
comment id is tamper evidence and fails closed. No run reads state from another
run except by replaying comments, so the reducer stays a pure function of the
inventory and the single-pending-run cancellation stays harmless.

*Fail-closed recovery*: a broken chain link, a digest conflict, a receipted
comment missing from the inventory, and an edit to a receipted comment each
make the session unreplayable and are reported naming the comment involved.
There is no recovery from genuine tampering, and there should not be: the
protocol refuses to trust a history it cannot verify. What this decision
removes is the class of events that were being treated as tampering and were
not.

*Non-circularity*: the store is a set of append-only comments whose authority
rests on GitHub's trusted metadata for those comments. It is never derived from
the projection, and the issue body remains a rebuildable cache with no
evidentiary role.

**A scheduled trigger is added, it runs daily, and it is not the receipting
path.** Events already receipt what they observe. The schedule exists for the
case #143 measured, a session whose last event died and which therefore stays
stale forever, and it is the trigger of its own that reducer output cannot
provide. Daily is the cadence because the pass is a safety net rather than the
receipting path: it bounds staleness at twenty-four hours and writes nothing on
a session with nothing to record. A scheduled run has no issue context, so it
selects sessions by the `open-table/session` label; the concurrency group must
then be keyed on the issue it selected, because today's expression reads
`github.event.issue.number` and would evaluate to empty on a scheduled run,
collapsing every session into a single group.

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

## Consequences

Reducer conformance becomes reachable for this deployment for the first time,
and it becomes checkable per session against a stated criterion rather than
asserted for the deployment as a whole. Sessions that predate the store do not
become conformant retroactively, which section 2.2 already forbids.

The denial of service in #144 closes for the case it was reported for: a
prose-only comment, edited by anyone, no longer ends a session. It does not
close entirely. An account that posts a well-formed `contribution` or
`proposal`, neither of which requires repository write access under section
4.17, waits for it to be receipted, and then edits it, still ends the session,
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
follows from the unresolved encoding question above: one checkpoint per unruled
protocol message is the ceiling, while a batched shape lowers it and is already
inside the grammar's idiom for a flat list. Against the measured baseline, #143 produced
three rulings for nine participant comments, and its unruled messages are the
ones that would have carried the new cost.

The trust boundary is unchanged and is worth stating plainly: a compromised
workflow token can author a false checkpoint, exactly as it can author a false
ruling. The store does not defend against the principal; it defends the
session's history against everyone else.

This decision records no implementation. The work it authorises is a
specification revision adding the reducer-authored `checkpoint` family, and the
reducer and workflow changes that follow it. Two constraints bound that revision
and are worth carrying into it rather than rediscovering. The `checkpoint` must
be its own comment, because section 3.2 requires exactly one `open-table` fenced
block per comment, so it cannot be folded into a ruling. And the revision must
choose how a checkpoint encodes a set of receipts. Batching itself is already
precedented by `expected-actors`; what has no precedent is a list of pairs, and
that is the question the revision has to answer.

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

Doing nothing until a second repository forces an App: rejected because it
leaves a live session killable by a stranger for as long as that takes, which
is the half of point I that #144 added.

## Open questions

Three questions posed by the first draft of this record are now settled and have
moved into the decision above: the scheduled pass runs daily, a session with a
receipt gap is processed and is not conformant, and the checkpoint carries no
digest for prose comments. They are noted here because a reader of the PR
discussion will find them raised and should not go looking for them unanswered.

What stays open is smaller and sharper.

*Should fail-closed be scoped to the affected message rather than the session?*
Section 2.2's own wording scopes it to "the affected protocol history", so the
narrower reading may already be the correct one. It is not settled here because
it changes the behaviour of the existing reducer for every session, not only for
sessions with a store, and it deserves its own record rather than a sentence in
this one.

*How does a checkpoint encode a set of receipts?* Batching many values into one
single-line field is already precedented by `expected-actors` in section 4.1, so
the question is not whether a checkpoint may carry more than one receipt. It is
that a receipt is a pair and the precedent is a flat list of scalars. Whether to
accept one receipt per comment, introduce a second delimiter, or split the pair
across positionally aligned fields belongs with the specification revision this
decision authorises.

*What anchors the tip of the chain?* Deleting the most recent checkpoint is
undetectable, because nothing references it yet. The exposure is bounded to
actors with repository write access, which is not the attacker this decision
closes out, but it is the residual most worth closing next and no answer to it
is proposed here.
