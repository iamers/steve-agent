---
status: accepted
date: 2026-08-16
---

# Detection memory is a run manifest, and the ambiguity barrier reads the timeline only when a ruling is missing

## Context

### What this record is, and the order it follows

[The requirement record](adr-20260807-mutations-are-detected-and-superseded.md)
decided what the deliberation log owes and deliberately did not decide the
mechanism. It named this record, listed the obligations it inherits so that
nothing would be dropped by being moved, and required that it come after a
spike rather than from a blank page: four mechanisms were designed on that
branch and every one died against a measurement or a reading of the deployed
reducer.

The spike is done and is the evidence this record decides on:
`.local/design/rm-spike-measurements.md`, run against
`tools/open-table-reduce.py` as installed at `eb4e12a`, unchanged in `main` at
the time of writing. Every claim in it is either a command run against the real
`reduce_session` or `replace_projection` through the tool's own
`--dry-run --bundle` CLI, with its literal output, or a file:line citation. No
reducer behaviour was reimplemented and no file in the repository was modified
by it.

Section 2.3 of `docs/specs/open-table-v0.md` already says what this record must
produce: a separate accepted decision that selects the mechanism meeting the
detection obligations and defines its **lifecycle, minimum permissions,
concurrent-write behavior, and fail-closed recovery**. Those four are the
skeleton of the decision below, and the record is answerable against them.

### What the spike measured

Four findings, each a fact about installed code rather than a reading of the
specification.

| Question | Measured result | Where |
|---|---|---|
| Is there a commit point for "incorporated"? | **No.** A ruling is written into an in-memory dict inside one call, before it has any GitHub comment id, and phase, turn and the projection all read that dict downstream | `tools/open-table-reduce.py:716` |
| What stands in for "was this already processed"? | A blanket edit-signal check that runs for **every** event before the code knows whether the comment is a protocol message at all. A comment reading `thanks for the update!`, edited once, makes the whole session unreplayable | `tools/open-table-reduce.py:321-332`, spike Q1 measurements A and B |
| Is the most recent ruling protected? | **No.** Deleting a ruling while its source stays byte-identical produces a fresh, byte-plausible replacement ruling, `unreplayable: false`, zero notices. Deleting the source and its ruling together leaves **zero** trace. The one case that does fail closed is a positional accident of `configuration_context` running before the ruling loop, and its message (`authorized configurations are not unique and contiguous`) names no ruling, deletion or comment id | spike Q2 |
| Does the reducer read the issue timeline? | **Never.** `grep -c -i timeline tools/open-table-reduce.py` returns `0`, against `70` for `ruling` in the same file. The only deletion evidence it ever sees is the single webhook payload that woke this run, read from local disk | `tools/open-table-reduce.py:839-846`, `:861-863` |

Two consequences of those four are worth stating before the decision, because
the decision is shaped by them.

The reducer's *asymmetry* is structural, not accidental: the edit check runs
over the raw event list before any protocol interpretation, and **nothing
analogous runs over the absence of an event**. Editing a ruling is caught by an
unscoped check that kills the session; deleting the same ruling is not caught
at all. Both halves are wrong in opposite directions.

And the cost baseline is already three unconditional network read-groups per
run, plus zero to N collaborator-permission lookups bounded by how much new
permission-sensitive material arrived: one issue read, one paginated comments
read, one paginated GraphQL edit-metadata read
(`tools/open-table-reduce.py:853`, `:857`, `:858`, `:901`). Any per-run cost
this record adds is priced against that three, not against zero.

### The obligation this mechanism has to meet

Section 2.3 fixes five constraints, and this record is measured against them
rather than against its own taste: the memory is not the mutable projection; it
binds the numeric comment id to the section 3.7 canonical digest of the
incorporated body; its domain is every family requiring a ruling under section
4.17, every deliberation message under section 4.2, and every ruling the
reducer appended; a permission-sensitive source whose ruling may have been lost
is never ruled again against current permissions, **including where the loss is
visible but does not identify the affected comment**; and the permission floor
is `issues: write`.

That fourth constraint is the one that decides the shape of everything below,
and its final clause is the reason the cheapest available design does not
qualify.

### The one thing the requirement record left genuinely open

The requirement record declined to inherit the reviewer's ambiguity barrier,
which treats every otherwise-unruled permission-sensitive source ordered before
an unmatched deletion event as potentially having lost its ruling. It satisfies
the obligation and it freezes, apparently permanently, sources that were in
flight when an ordinary housekeeping deletion happened, since the event stays
in the timeline and no resolution path was defined. Availability is the asset
the whole revision was bought with, so the cost was left to be weighed here
explicitly instead of inherited.

The spike priced the looking and not the unfreezing, because no unfreeze path
existed to measure. So the barrier's trigger and its exit are decided below on
argument, and they are the two places where this record is most exposed to
being wrong.

## Decision

### 1. The memory is a `manifest` message the reducer posts, one per run that has something to record

A new `open-table` message family, `manifest`, authored by a reducer principal
like a `ruling`. It is not an extension of ruling headers and it is not one
comment per incorporated message.

Not ruling headers, because rulings do not exist for the two families that most
need remembering: `contribution` and `proposal` require no ruling under section
4.17, and a `contribution` is in the domain precisely because it advances phase
and turn under section 5.2 while no section 9.2 entry names it. A memory that
rides inside rulings cannot cover the domain section 2.3 fixes.

One comment per run rather than one per message, because the run is already the
unit at which the reducer writes and because per-message manifests multiply
reducer output by the size of the deliberation. Batching concentrates the blast
radius of a single deletion, and section 4 below is where that is paid for: a
deleted manifest comment is what the timeline read exists to make visible. That
this is visible at all is measured rather than assumed. An account with write
access deleting a principal-authored comment records a `CommentDeletedEvent`
with actor and `deletedCommentAuthor`, in GraphQL and REST (2026-08-05, probe
#154); the actor that could delete a manifest without leaving that event is the
principal itself, deleting its own comment (2026-08-05, probe #152), and a
compromised principal is outside the trust boundary the requirement record
kept.

### 2. What an entry binds, and what a manifest carries besides entries

Each entry binds, for one message in the domain:

- the numeric GitHub comment id;
- the section 3.7 canonical digest of the body that was incorporated;
- the message family;
- for a source that was ruled, the numeric comment id of its ruling.

A manifest comment carries, in addition to its entries:

- `deletions-accounted`: the number of comment-deletion events in the issue
  timeline that the reducer has already accounted for. This is the watermark
  section 4 uses, and it is the only field of this mechanism that is not a
  binding;
- `frozen`: the numeric comment ids of sources the barrier refused to rule,
  each with the watermark reading that froze it.

The exact wire encoding under the section 3.2 one-block constraint is the
specification revision's, not this record's; what is decided here is the set of
things an entry must bind, and that the digest is mandatory rather than
optional. A memory of comment ids alone detects deletions and misses edits, and
that is an obligation and not a preference.

### 3. The commit point: rulings first, manifest second, projection last

**Manifest membership is not a precondition for affecting in-run state, and
this is stated rather than left to be inferred.** A ruling computed inside
`reduce_session` keeps driving phase, turn and the projection within the same
call, exactly as it does today at `tools/open-table-reduce.py:716`. What the
manifest records is what a *completed* run incorporated.

The write order in `apply_plan` is: ruling comments, then the manifest comment
that records them, then the projection.

The order is the opposite of the naive one, and the reason is the recovery
rule. A manifest written first cannot bind the ruling comment ids, because a
ruling has no id until it is posted. Worse, a crash between the manifest and
the rulings would leave manifest entries whose rulings are absent, which is
exactly the signature of a deleted ruling: **a crash would be indistinguishable
from tampering, and the recovery path would be a false accusation.**

With rulings first, the crash residual is a manifest that lags the log. The
next run finds the source already carrying a ruling in the inventory, uses it,
consults no current permission, and records the entry then. The residual is
under-detection inside one window, never a false alarm, and it is bounded by
the next successful run. For permission-sensitive sources the window is
narrower than it looks, because section 7.3 already makes every ruling bind its
source's comment id and digest: inside that window the ruling is itself the
digest binding, and only `contribution` and `proposal` are left with no binding
at all until the manifest lands.

That residual is not left uncovered. A source ruled in the crashed run whose
ruling is then deleted has neither ruling nor manifest entry, which is precisely
the state section 4's timeline read exists to resolve.

### 4. The ambiguity barrier reads the timeline only when a permission-sensitive lookup is pending

This is the decision the requirement record deferred, and it is taken in the
narrow form. It is the residual case, so the general rule comes first.

**A manifest entry whose comment is absent from the inventory is an identified
loss**, for every family in the domain and whatever the message was: the entry
names the comment id, the digest, and the ruling if it had one, so the notice
can say what was lost and what it backed, and a scoped supersede iteration
opens. That rule needs no timeline, covers deliberation messages that never had
a ruling, and is where most of this mechanism's detection actually happens.

The barrier below is the one case that rule cannot reach: a permission-sensitive
source with **no ruling and no entry**, where the absence of the entry is
exactly what makes the loss unidentifiable. So, when the reduction reaches a
source in a section 4.17 family that has no ruling in the inventory:

1. **A surviving manifest entry records a ruling for it.** The ruling was lost.
   Section 9.1 applies unchanged: dependent state is unreplayable and fails
   closed, scoped to that state, a notice names the source and the ruling that
   backed it, and **no permission lookup happens**. The timeline is not read:
   the loss is already identified.
2. **No surviving manifest entry records it.** The source is either genuinely
   new or its manifest entry was removed with its ruling. These two states are
   indistinguishable from the inventory, which is the ambiguity, so the
   timeline is read here and only here.
   - **Observed comment-deletion count equals `deletions-accounted`.** No loss
     is visible. The source is new: it is ruled, one permission lookup happens
     as today, and the entry is recorded.
   - **The two disagree, in either direction.** A loss is visible and
     unidentified. The source is frozen: no ruling, no permission lookup,
     recorded as `frozen`, and a notice names the unaccounted deletions and
     every source frozen by them.

The comparison is equality and not "observed is at least accounted", and the
reason is that the assumption underneath it is measured rather than
contractual. The requirement record's table records timeline events as
undeletable (2026-08-05, probe #153: after every probe label was deleted the
timeline still returned the labeling records, and no mutation among 258 in the
schema addresses a timeline event) and also records that no durability claim
rests on any row of that table. If that property ever fails, an observed count
*below* the watermark is the shape it takes, and equality makes that read as
unaccounted rather than as all-clear. **A broken assumption fails toward the
barrier, not past it.**

The trigger is stated as a predicate over the inventory and the manifest alone,
with no reference to the timeline, and that is deliberate: a live adapter can
evaluate it before deciding whether to fetch the timeline, and when it is false
the reduction provably does not consult the timeline at all, so omitting it
cannot change the result. Section 2.5's determinism is untouched, and a replay
bundle still carries the complete timeline as section 2.2 requires.

### 5. What the barrier does when it fires, and how the freeze ends

The freeze is scoped, durable, and has a defined exit. All three are answers to
the objection the requirement record raised.

**Scoped**: only the permission-sensitive sources that were pending a ruling
when the unaccounted deletion was observed are frozen. Material already ruled
is untouched, deliberation continues, and the session is not terminated.

**Durable**: a frozen source is recorded as frozen in the manifest, so a later
run does not quietly rule it once the watermark has moved on. Without this the
freeze would last exactly one run and the fresh permission lookup section 9.1
forbids would happen on the next one.

**Exited by deliberation, never by a lookup**: the frozen source is not
re-ruled. It is re-established the way the requirement record already says
material is re-established, by a new message, which is an ordinary supersede
iteration. The participant posts again and the new comment gets an honest
ruling of its own.

**And the watermark advances in the same manifest write.** The notice is the
accounting: once the reducer has named the unaccounted deletions and the
sources they froze, those events are accounted for, and material arriving
afterwards is not frozen by them. This is what stops a single housekeeping
deletion from freezing the session permanently, which was the concrete
objection to the barrier's original shape. What it costs is that the same
deletion event cannot freeze anything twice, which is correct: it has been
adjudicated once, in the open.

### 6. Concurrent writes: union the entries, take the highest watermark

Two runs can overlap in the #143 debounce and cancellation window, so the
mechanism is defined over the set of surviving manifest comments rather than
over the latest one.

- **Entries are the union.** A source is remembered if any surviving manifest
  comment records it. Duplicate entries for the same `(comment id, digest)` are
  the same fact and merge; two entries for the same comment id with different
  digests are an edit and are handled as one, not as a conflict between
  manifests.
- **`deletions-accounted` is the maximum.** Each watermark was written by a
  reducer principal that had actually accounted for those events, so the
  highest one is the true accounting. The minimum would re-raise resolved
  events forever, which is the permanent freeze again wearing a different hat.
- **`frozen` is the union**, and a frozen source is unfrozen only by the
  supersede iteration of section 5, never by a later manifest.

The maximum is the permissive direction, and it is safe only because writing a
manifest requires a reducer principal, whose compromise is out of scope under
the trust boundary the requirement record kept. That dependency is named here
rather than buried: if the principal is compromised the watermark can be
advanced falsely, exactly as false rulings could already be authored.

Deleting the newest manifest comment therefore lowers the effective watermark
and removes its entries, which makes the barrier **more** conservative, not
less. Both regressions fail toward detection.

### 7. The blanket edit trip-wire is replaced by scoped detection

The check at `tools/open-table-reduce.py:321-332` is removed, and detection of
an edit becomes a digest comparison against the manifest:

- a comment in the domain whose current digest differs from its manifest entry
  has been edited: a scoped supersede iteration opens for that message and what
  depends on it;
- a comment with no manifest entry carries no edit signal worth acting on,
  because nothing was incorporated to be changed. It is incorporated now, in
  the body it currently has, which is what an edit before incorporation means;
- a comment that is not a protocol message at all is not in the domain and is
  ignored.

This is what closes [#144](https://github.com/iamers/steve-agent/issues/144) in
code. The requirement record closed it in the requirement; the denial of
service is a live line of Python until this lands, and the spike's measurements
A and B are the reproduction: a never-incorporated `contribution` and a comment
whose body is `thanks for the update!` each take down an entire session's
replay when edited once.

`updated_at` and `lastEditedAt` keep the role section 2.5 already gives them,
auxiliary signals that nothing rests on. They may cheapen the digest comparison
by narrowing which bodies are worth hashing; they may not be the thing that
decides.

### Minimum permissions, unchanged

`issues: write` and nothing more. Reading the comment inventory, reading the
issue timeline, and writing reducer output are inside the floor, and section 2.3
already says so. The timeline read is a REST `/issues/{n}/timeline` or GraphQL
`timelineItems` read of the same issue the reducer is already reading, so no new
scope is requested.

**A probe is owed all the same, and this record does not get to skip it.** The
requirement record's rule is that a field the implementation reads gets a probe
in that implementation's CI, and this mechanism reads a surface nothing read
before. Two things need measuring rather than asserting: that the workflow
token can enumerate comment-deletion events on the session issue, which section
2.3 states as documented rather than measured, and that the count is stable
across reads of an unchanged issue, because an unstable count is a freeze that
fires on nothing. Both belong to the implementation's CI, and until they pass,
the barrier is a design and not a guarantee.

### What is now detected, and what is not

| Case | Before (measured) | After |
|---|---|---|
| Ruling deleted, source alive | Silent fresh ruling against current permissions | Identified loss, fail closed under 9.1, no lookup |
| Source and its ruling deleted together | Zero trace | Identified loss: the manifest entry survives both |
| Source, ruling and manifest entry all deleted | Zero trace | Visible and unidentified: the barrier freezes pending lookups and names the unaccounted deletion |
| Incorporated body edited | Whole session unreplayable | Scoped supersede iteration for that message |
| Never-incorporated body edited | Whole session unreplayable (#144) | Ignored, and incorporated as it now reads |
| Projection content overwritten | Silently rebuilt | Unchanged: it is a cache under 2.6 and carries no evidentiary value |
| Comment self-deleted before any run saw it | Undetectable | Undetectable, and still declared |

The third row is the residual, and it is the one the requirement record already
scoped by actor: reaching it needs repository write access, because a manifest
is a comment the reducer wrote. What that actor gets is a denial of
availability that names itself, not a silent loss.

**The second row moved, and it is worth saying so plainly.** The spike measured
a paired source-and-ruling deletion as leaving zero trace, and that is what the
decision was framed against: the paired case would stay a declared
non-guarantee. It does not, once a memory exists that neither of the two
deleted comments carries. The entry survives both, so the loss is identified,
and what stays declared is the deletion that removes the manifest record as
well. This is a stronger outcome than the brief this record was written from,
and it is stated as a correction rather than quietly banked: a record that
silently improves on the promise it was asked to make is as hard to review as
one that silently weakens it. The published non-guarantees of section 2.3 are
unaffected either way, because the insider clause already covers both the case
that moved and the one that did not.

## Consequences

**The happy path is free, and this is a narrower claim than it sounds.** A run
that brings no new permission-sensitive material pays nothing new: three read
groups, as today. A run that does bring some pays one additional paginated
timeline read, once, regardless of how many such sources it carries, and it
pays it on the same path that was already about to make N collaborator
permission lookups over the network. So the honest statement is not "only
anomalies pay". It is that the cost attaches to the branch that was already the
expensive one, and never to the ordinary comment traffic that makes up most
runs.

The cheaper trigger was available and does not qualify. Reading the timeline
only when the manifest already disagrees with the inventory would cost nothing
outside a real anomaly, and it cannot see a loss that removed the manifest
entry along with the ruling. Section 2.3 requires the fail-closed outcome to be
reachable *including where the loss is visible but does not identify the
affected comment*, and unidentified loss is by construction invisible in the
manifest. The extra read buys exactly that clause and nothing else.

**Reducer output grows by one comment per run with new material.** The
requirement record said the happy path was probably no longer free and declined
to size the bill; this is the bill. It is bounded by runs rather than by
messages, and a session that deliberates for an hour at the measured cadence of
roughly one run per minute pays tens of comments, not hundreds. Whether that
noise wants a fold, a single rewritten manifest, or a separate issue is a
presentation question and is left open below.

**Determinism is preserved and section 2.5 is not weakened.** The reduction is
still a pure function of its bundle. What is conditional is the adapter's
fetch, gated on a predicate the adapter can evaluate from what it has already
read. A replay bundle carries the complete timeline as before.

**One integrity asset changes hands.** Today the only thing resembling
detection is a trip-wire that fires on prose. After this, detection rests on
records the reducer itself wrote and digests it computed under section 3.7,
which is what the requirement record said the mechanism was permitted to lean
on. The platform surfaces it leans on are two: the comment inventory, and the
existence and count of timeline deletion events. The second is measured and not
contractual, and section 4 makes its failure fail toward the barrier.

### The specification revision this record authorises

Scoped to the mechanism, and it is the revision section 2.3 says must exist
before an Action deployment can claim reducer conformance:

- **Section 2.3**: replace "no such mechanism is selected today" with the
  selection, its lifecycle, its concurrent-write rule and its fail-closed
  recovery. The declared non-guarantees stay as written, with the third row of
  the table above folded into the insider clause that already covers it.
- **Section 2.2 and 2.5**: state that the complete timeline is a *replay*
  input, and that a live adapter may defer fetching it while the reduction
  provably does not consult it. Without this the conditional read reads as a
  violation of a MUST that was written for replay.
- **Section 4**: the `manifest` family, its fields, and the rule that only a
  reducer principal may author one, alongside the section 3.2 one-block
  constraint.
- **Section 7**: manifest idempotency under the section 7.1 triple, and the
  union and maximum rules of section 6 above.
- **Section 9.1**: unchanged in its words. What changes is that the clause
  becomes reachable.
- **Issue [#130](https://github.com/iamers/steve-agent/issues/130)**: the
  mechanism point updated from "not selected" to this record.

### Implementation and test obligations

The implementation comes after this record, per `docs/decisions/README.md`. The
four fixtures the requirement record named are inherited unchanged, and this
record adds five that correspond to the decisions above, each of which must
fail before the implementation and pass after:

1. a deleted ruling with a surviving manifest entry fails closed and makes
   **zero** permission lookups;
2. a source and its ruling deleted together, with the manifest entry
   surviving, is identified rather than silent;
3. an unaccounted deletion event freezes a pending permission-sensitive source
   and does **not** freeze material that arrives after the watermark advanced;
4. a manifest written by a crashed run, absent while its rulings exist, is
   recovered on the next run with no false accusation and no fresh lookup;
5. an edited comment that is not in the domain changes nothing, which is #144's
   regression guard.

Plus the two live probes the minimum-permissions section says are owed, which
are not fixtures because no fixture can answer them: the workflow token
enumerating comment-deletion events on a real session issue, and the same count
read twice over an unchanged issue.

Two of those five are guards against this record being implemented in the wrong
direction rather than against the platform, and they are the ones worth writing
first: number 3 is where a permanent freeze would show up, and number 4 is
where a crash would be misread as tampering.

The live drill the requirement record asked for stands: a deletion of
incorporated material mid-session, with the criterion that no contribution is
lost and no session is killed.

### What this record does not decide

- **The supersede transition.** The event family, the dependency closure, the
  state effect, the idempotency key, the completion conditions, and the
  interaction with section 8.3, with the correction the requirement record
  already recorded as an obligation: reopen whenever the computed closure
  invalidates or contains the terminal settlement, not only when the terminal
  record was mutated directly. It is listed here in full so that nothing is
  dropped by being left.

  The split is deliberate and it is the same one that produced this record. The
  spike measured detection and lifecycle, which is what four failed mechanisms
  died on; it measured nothing about what the reducer can do once material is
  gone, and `docs/decisions/README.md` asks for the evidence before the
  decision. Deciding the transition here would be reasoning from a blank page
  about questions a second spike answers, which is the exact move the
  requirement record refused.
- **The audit profile.** Named, not designed, and still where an adopter who
  does not accept the actor scoping of property 2 is sent.
- **Marker corruption diagnosability.** The spike measured that a duplicated
  projection marker produces `writes: []`, with the only external signal the
  process exit code, because `fail_plan` cannot write its notice into a body it
  cannot parse (`tools/open-table-reduce.py:257-258`). That is a real defect
  and it is not this mechanism's: the projection is outside the manifest's
  domain by section 2.6. It gets its own issue rather than being absorbed here.
- **How manifest comments are presented.** Folding, rewriting a single manifest
  in place, or moving them off the deliberation issue are all compatible with
  everything decided above, and none of them is decided.

## Alternatives considered

**Read the timeline on every run** (the reviewer's original shape): rejected on
cost and on the freeze. It raises the unconditional read groups from three to
four for every run forever, including the all-clear case where no deletion ever
occurred, and its unmatched-deletion rule freezes in-flight sources with no
defined exit. The narrow trigger buys the same clause of section 2.3 and pays
only on the branch that was already making network calls.

**Read the timeline only when the manifest already disagrees with the
inventory**: rejected, and it is the tempting one. It is strictly cheaper and
it satisfies everything except the clause that matters: a loss that removed the
manifest entry along with the ruling is invisible in the manifest by
construction, so this trigger can never reach the fail-closed branch section 2.3
requires to be reachable "including where the loss is visible but does not
identify the affected comment". It would have been the design that reads as
correct and is exactly one measured case short.

**Ride the manifest inside ruling headers**: rejected on the domain.
`contribution` and `proposal` require no ruling under section 4.17 and are in
the domain under section 2.3, and a `contribution` advances phase and turn.
The memory would have covered everything except the two families the
requirement record specifically identified as the gap.

**One manifest comment per incorporated message**: rejected on volume. It
multiplies reducer output by the size of the deliberation to reduce the blast
radius of a single deletion, and the blast radius is already covered: a deleted
manifest comment is a timeline event, which is what section 4 reads.

**Post the manifest before the rulings**: rejected on recovery, and this is the
sharpest of the alternatives. It is the intuitive order, it is what "record
before you act" suggests, and it makes a crash produce manifest entries whose
rulings are absent, which is byte-identical to a deleted ruling. The mechanism
would then accuse the process of tampering by the process's own crash. The
chosen order pays for that with a lagging manifest, whose failure direction is
under-detection inside one bounded window.

**Keep the blanket edit trip-wire alongside the manifest**: rejected. It is
the #144 denial of service, it fires on prose the protocol never read, and the
requirement record already decided that no participant act on the comment
stream ends a session. Keeping it "for defence in depth" would be keeping a
defect and calling it a layer.

**Seal the manifest tip**: rejected, and declared instead. This is the
unsealable tip that ended the checkpoint chain, met a third time. Any record
the reducer writes is a comment an account with write access can delete, so no
arrangement of comments seals its own newest entry. What is achieved instead is
that deleting the tip regresses the watermark and removes entries, and both
regressions make the barrier more conservative: the tip cannot be removed
silently, only expensively.

**Take the minimum watermark across surviving manifests**: rejected. It reads
as the safe direction and it is the permanent freeze: an event resolved by one
run would be re-raised by every later run that saw an older manifest, forever.

## Open questions

*Does the watermark want to be a count or a cursor?* A count is the simplest
thing that supports the equality comparison and rests on timeline events being
undeletable. A cursor on the newest accounted event's `createdAt` survives that
assumption failing but needs a tie-break rule for events sharing a timestamp,
which probe #153 already measured happening for `editedAt`. The count is
decided above; the cursor is the fallback if the count is ever observed to
disagree with itself, and the implementation records which it used.

*Does a `settled` ruling additionally pin the digest of the proposal it
settles?* Inherited unchanged from the requirement record, which left it to
this one. It is now cheaper than it was, because the manifest already binds the
proposal's digest and the extra field would be a second copy of a binding that
exists. Left open rather than decided, under the section 3.2 and `invalidated`
constraints.

*What does the barrier do in a session with no permission-sensitive families at
all?* A `deliberation-only` session never triggers it, so an unaccounted
deletion in such a session produces no freeze and no notice at the time it
happens. Detection of identified loss still works through the manifest, and
whether the unidentified case deserves a notice with nothing to freeze is a
presentation question this record does not settle.
