---
status: accepted
date: 2026-08-07
supersedes: adr-20260805-checkpoints-are-a-partial-receipt-store.md
---

# Mutations of incorporated material are detected and superseded, and point I dissolves

## Context

### This is a requirement revision, and it follows a lost review

This branch previously carried a different record, "Platform memory is the
receipt store", which accepted GitHub's own memory of the comment stream as the
durable receipt store section 2.3 demands. It was reviewed and failed on three
findings
([review 4869573236](https://github.com/iamers/steve-agent/pull/155#pullrequestreview-4869573236)),
each correct against the specification as written: `userContentEdits.diff` is
documented as "a summary of the changes for this edit" with no ordering
contract, so treating observed complete bodies as a durable receipt promoted
observed behavior to authority; the design's minimum-permission answer depended
on a GraphQL read the workflow token had never been shown to perform; and
"unruled" is not "unacted-on", because `scan_deliberation` projects proposals
immediately, so the declared self-deletion residual was wider than the record
admitted.

The response is not a repaired store. On 2026-08-06 the project owner reviewed
the requirement the store was meant to satisfy, and revised it
([the reframe comment](https://github.com/iamers/steve-agent/pull/155#issuecomment-5207954411)
records the decision and its reasons; this record is the decision itself). Said
plainly rather than left to be inferred: this moves the goalposts after a lost
review. The review was lost fairly, and the revised requirement passes through
review like everything else. The failed record was never merged; it is replaced
on this branch, not superseded, and its measurements are inherited below. The
record this one supersedes is the checkpoint store, accepted and merged on
2026-08-05.

### The product rationale

Steve runs collaboration and development from chat, with GitHub as the
synchronization hub. Activity is continuous: the reducer acts within about a
minute of a comment (#143 runtime measurements, inherited from the superseded
record), and what a deliberation produces is distilled into the repository
through the normal flow, in decisions, commits and pull requests that cite the
issue and the specific comments behind them. That distillate lives in git,
which is already an append-only, content-addressed, distributed, signed store.

The deliberation issue is working memory. Nobody re-reads a session issue
months later as the authoritative record; they read what it produced. The
window in which a comment body exists only in the platform's memory is minutes,
not months, and the scenario that makes an audit-grade comment log necessary,
replaying an old session whose original text survives nowhere else, is not one
this product has. Section 2.3's demand for a durable, authenticated,
non-circular receipt store was calibrated for that scenario. Two designs tried
to meet it: the checkpoint chain could not seal its own tip, and platform
memory rests on non-contractual semantics. The demand itself was the
miscalibration.

### The threat model, unchanged

The actor table from the failed record stands: it describes the platform, not
a design.

| Actor | Can do | Evidence the platform keeps (measured) |
|---|---|---|
| Any account (the #144 attacker) | edit or delete **its own** comments only | edit: revision bodies in `userContentEdits`, non-contractual (#153). Self-delete: nothing (#152) |
| Participant | same as above | same as above |
| Insider with write access | edit or delete **any** comment; delete a revision | delete of another's comment: `CommentDeletedEvent` with actor, and deleted author in GraphQL (#154). Revision delete: `deletedAt`/`deletedBy` (#153) |
| The principal itself (compromised token) | all of the above, plus authoring false rulings | out of scope: the trust boundary recorded in the superseded record |
| The platform | anything | trusted by assumption of the entire design |

What this revision changes is not who can do what. It is what the protocol
owes when they do it: detection and an orderly supersede, not proof.

### Every platform property, with its measurement

The measured-sentence table survives both prior designs because it is the
instrument that caught them. Updated with the review's probes:

| Assumed property | Measured sentence | Date | Probe |
|---|---|---|---|
| Self-deletion leaves no trace | A comment created and deleted by its author left timeline `totalCount: 0`, an explicit `COMMENT_DELETED_EVENT` filter returned zero, and the REST timeline was empty | 2026-08-05 | #152 |
| Moderator deletion leaves an event | Admin deletion of a principal-authored comment recorded `CommentDeletedEvent` with actor and `deletedCommentAuthor`, in GraphQL and REST | 2026-08-05 | #154, comment 5197354178 |
| Timeline events are undeletable | After every probe label was deleted from the repository, the timeline still returned the labeling records; no mutation among 258 in the schema addresses a timeline event | 2026-08-05 | #153 |
| The platform remembers edited bodies | Each `userContentEdits` node's `diff` carried the complete body of that revision, including the pre-edit original, with editor and timestamp | 2026-08-05 | #153 |
| That memory is contractual | It is not: the public schema defines `diff` only as "A summary of the changes for this edit", the connection documents no ordering argument or guarantee, and two #153 revisions carry identical `editedAt` values, so timestamps cannot always order them ([UserContentEdit](https://docs.github.com/en/graphql/reference/users#usercontentedit), [IssueComment](https://docs.github.com/en/graphql/reference/issues#issuecomment)) | 2026-08-05 | review 4869573236, independent query |
| Revision deletion destroys but attributes | The deleted revision's node survives with `deletedAt`/`deletedBy` populated and `diff` reduced to the literal `deleted` | 2026-08-05 | #153, comment 5198090574 |
| The deletion event is public, the actor is not | An unauthenticated REST read returns the event with its timestamp and the organization as `actor`; `deletedCommentAuthor` is GraphQL-only; unauthenticated GraphQL returns 403 | 2026-08-05 | #154, comment 5198298566 |
| GH Archive is not a witness for this repo | One event archived of the sixteen the live per-repo feed serves across two measured hours; the deleted ruling in neither hourly file nor the live feed | 2026-08-05 | #154, comment 5198298566 |
| Deleting another's comment requires write access | Documented ("Managing disruptive comments"), not independently measured; consistent with the anonymous-actor masking above | docs | none available without a no-access account |
| The deployed guard's memory is one run | The deletion-triggered run failed closed naming the comment; the next run re-emitted the ruling against current permissions | 2026-08-05 | #154, comment 5197354178 |
| REST `updated_at` reflects edits, above the second | An edit five seconds after creation moved `updated_at` from `07:11:14Z` to `07:11:19Z` while `created_at` stayed; an edit within the creation second left the pair equal while `lastEditedAt` was populated; a revision deletion did not move `updated_at` | 2026-08-07 | #153, comment 5213750179 |
| The workflow token can read `userContentEdits` and `deletedCommentAuthor` | **Not measured, and no longer load-bearing.** Both fields serve best-effort recovery and attribution below; a probe is owed if and when an implementation reads them | — | deferred to that implementation's CI |

After this revision the table's role changes. No durability claim rests on any
row: the rows are the reasons recovery is best-effort and attribution is
partial, not guarantees a design builds on. The design's load-bearing
dependencies are git as the archive, the canonical digests the reducer already
computes, and the projection citations section 9.2 already requires, which are
this project's own contract, tested by its own fixtures. The REST
`created_at`/`updated_at` pair is auxiliary, and its blind spot is measured in
the table rather than assumed away.

## Decision

**The deliberation log owes three properties, and audit-grade history is not
one of them.**

1. **Contributions are detected, considered, and incorporated.** Unchanged;
   this is what the reducer is.
2. **Mutations of incorporated material are noticed, never silently lost, and
   open a supersede iteration.** An edit or deletion that in practice means a
   feature changed or work should stop produces a named notice and an orderly
   re-establishment, never a killed session.
3. **What was decided stays anchored.** Rulings keep pinning digests at ruling
   time under sections 4.16 and 9.1, replay keeps reading recorded permission
   outcomes and never consults current permissions, and the projection stays a
   deterministic function of the log. Determinism stays because it is cheap
   engineering, no second store and free crash recovery, not because it proves
   anything. The weld between determinism and tamper evidence is dropped.

### The detection mechanism

**Primary detection is a comparison between the previous projection and the
current inventory.** Section 9.2 already requires the projection to cite
permalinks for what it incorporated: settling comments, proposal comments,
notice sources. Those citations are the detection manifest. On every run the
reducer compares the comment ids the previous projection cited against the
comment inventory it just read:

- a cited id absent from the inventory is a detected deletion: the reducer
  emits a supersede notice naming the id and the settled point, proposal, or
  notice it backed, and opens a supersede iteration for that material;
- a cited comment whose current body no longer digests to what the previous
  projection recorded beside the citation is a detected edit, noticed the same
  way. The reducer already computes canonical digests under section 3.7, so
  this comparison adds no machinery and trusts no platform metadata. The REST
  `created_at`/`updated_at` pair serves as a cheap auxiliary signal with a
  measured blind spot: a later-second edit moves `updated_at`, a same-second
  edit does not (#153, comment 5213750179).

This floor needs `issues: write` and nothing else, which answers the
minimum-permission question the failed design left to an unproved GraphQL
read. The projection stays a rebuildable cache with no evidentiary role: state
is still derived from the log alone, and the comparison only emits notices.
The review's third finding is the requirement this mechanism exists to meet:
an author who self-deletes a proposal after a successful run, inside the #143
cancellation window that erases the payload guard's one-run memory, is caught
because the previous projection cited that proposal.

**A supersede iteration is a protocol event, not an apology.** The affected
material degrades, scoped to the affected message and what depends on it,
never the session. The notice names what was lost or changed and what it
backed; re-establishing the material (a re-post, a re-settle, a decision to
drop it) is deliberation like any other. The session continues throughout.

**Best-effort layers sit on top of detection, and nothing durable rests on
them.**

- *Tombstones from the deletion payload.* The deployed guard that reads a
  deleted comment from its trigger payload writes a tombstone comment first,
  recording the deleted comment's numeric id, numeric author id, trusted
  `created_at`, the canonical digest of the deleted body, and whether it
  carried an `open-table` block. Evidence when the run survives; the
  comparison above covers projected material when it does not.
- *Original-body recovery via `userContentEdits`.* When an edit is noticed and
  the platform cooperates, the reducer recovers and quotes the pre-edit body.
  When it does not, the notice stands without it. The review's first finding
  is answered by this demotion: the field's non-contractual semantics stop
  being load-bearing because nothing durable reads it.
- *Attribution via `CommentDeletedEvent` and `deletedCommentAuthor`.* Where
  readable, notices name the actor. Attribution is not detection: the
  comparison already established that the mutation happened.

**Fail-closed survives only where rulings are.** Section 9.1 is unchanged: a
deleted or missing source or ruling, a digest mismatch, or conflicting reuse
of an actor/message-id pair still makes dependent state unreplayable and fails
closed, scoped to that dependent state. Rulings pin their digests at ruling
time, so decided history never depends on the platform's memory.

**An insider mutation is a detected event that opens an iteration, not
session-fatal tampering.** In a team tool the admin who deletes a comment is
usually doing housekeeping. The prior designs treated insider deletion of
principal output as session death; this record downgrades it to the same
notice-and-supersede path as every other mutation, with attribution where the
platform provides it. This is a security downgrade, made deliberately for a
team tool, and written down as one: the log detects and names insider
mutations where the platform allows, and it does not prove them.

### The non-guarantees, declared

- **A comment created and deleted before any run projected it is
  undetectable: a self-deleted, never-projected message can disappear without
  trace.** Self-deletion leaves no platform trace (#152), the payload guard's
  memory is one run (#154), and no citation exists to compare against. This is
  a retraction of unincorporated input by its own author, and it is declared
  rather than rounded away.
- **The deliberation log is not audit-grade history.** It does not prove
  completeness, absence, or the exact text of what a deleted comment said
  beyond a best-effort tombstone. An adopter who needs a ledger needs the
  audit profile below, which this record names and does not design.

### Point I dissolves

Section 2.3 required a separate accepted decision defining a durable,
authenticated, non-circular receipt store before any deployment claims reducer
conformance. This revision removes that requirement, so there is no store to
select: point I closes with the clause that created it rather than being
answered. The two prior records remain the measured account of why both
candidate stores failed. Section 1.7's standing rule is untouched: the
deployment claims no reducer conformance until the specification revision
below and the implementation exist.

### The specification revision this record authorises

One revision of `docs/specs/open-table-v0.md`, plus the issue housekeeping
that follows:

- **Section 2.2**: append-only stays a protocol convention and correction
  stays a new message, unchanged. The creation-receipt machinery (authenticated
  receipt capture, digest match, `lastEditedAt` null, edit-equals-unreplayable)
  is replaced by detect-and-supersede: mutations of incorporated material are
  detected and flagged, never silently lost, and open a supersede iteration;
  no participant act on the comment stream ends a session.
- **Section 2.3**: the store paragraph is replaced by the detection
  obligations of this record: the citation-comparison floor, its
  `issues: write` minimum permission, notice duties, the best-effort layers,
  and the declared non-guarantees. The conformance gate becomes the
  implementation of those obligations.
- **Sections 4.16 / 9.1**: unchanged. Ruling pinning and fail-closed on
  ruling-dependent state stay exactly as written.
- **Section 9.2**: extended with what detection needs the projection to
  record beside each citation, decided in the revision (at minimum, citations
  remain mandatory; the per-citation canonical digest above is the candidate
  mechanism).
- **Tombstone encoding**: either a minimal reducer-output family or a reuse of
  the `invalidated` ruling, decided in the revision under the two constraints
  already recorded: section 3.2 permits one `open-table` block per comment,
  and `invalidated` must be the sole ruling for its source.
- **Audit profile**: named as a future authority-profile extension for
  adopters who need a ledger (external witness repository, the Certificate
  Transparency shape, or both prior designs revived). Named, not designed;
  nothing in this record forecloses it.
- **Issue #130**: point I recorded as dissolved by this revision; point 2
  updated to the detect-and-supersede reading.

### Implementation and test obligations

The implementation this record authorises is the comparison and its notices,
the scoped supersede path, the tombstone write, the insider notice, and the
best-effort recovery reads. Its tests are a fixture per row of the
threat-model table plus one live drill: a deletion of incorporated material
mid-session, with the criterion that no contribution is lost and no session
is killed. Platform contract probes follow use: a field the implementation
reads (for recovery or attribution) gets a probe in that implementation's CI;
a field nothing reads gets none. The scheduled daily pass survives with its
#143 stale-session rationale unchanged, and is what bounds detection latency
when event-driven runs are cancelled.

## Consequences

The #144 denial of service closes completely. No act by a participant on the
participant's own comment, and no act by an insider on anyone's comment, ends
a session. The strongest remaining consequence in the comment stream is scoped
unreplayability of ruling-dependent state under section 9.1, which protects
the one asset that kept fail-closed semantics.

What the design defends changed shape honestly. Before: prove the log intact
or refuse to run. After: never lose incorporated material silently, keep
decided history pinned, keep the session alive. The cost is named in the
non-guarantees: no proof of absence, no ledger, insider acts detected rather
than prevented. For a team tool whose durable record is git, that trade buys
availability and simplicity with assets that were never this log's to
protect.

Noise stays zero on the happy path. The reducer writes nothing extra while
nobody tampers: one tombstone per deletion it witnesses, one notice per
detected mutation, no per-message receipts. The #143 property that
conversation in a session issue is free is preserved exactly.

The platform-dependency profile inverts. The failed design leaned on
non-contractual platform memory and needed a probe suite as a standing
obligation; this design's floor reads only comment ids and the
`created_at`/`updated_at` pair, and treats every richer platform surface as
optional. Probes shrink from an obligation of the design to a property of
whatever the implementation actually reads.

The trust boundary is unchanged: a compromised principal token can author
false tombstones, false notices, and false rulings exactly as it always
could. The insider, previously the actor the checkpoint chain could not stop
and the platform-memory design failed closed against, is now met where the
product lives: detected, named where possible, superseded in the open.

## Alternatives considered

**The checkpoint chain** (the superseded record): rejected on measurement,
inherited. Its central deletion premise is false for the only actor able to
delete other people's comments, its machinery defends against the insider it
concedes it cannot stop, and its tip cannot be sealed from inside the stream.
Its excluded homes, runtime measurements, and the #144 reframing carry over.

**Platform memory as the durable store** (the record this branch previously
carried): rejected on review. Non-contractual field semantics cannot anchor a
durability claim, the minimum-permission answer depended on an unproved read,
and the declared residual was wider than admitted. Its measurements, scoping,
tombstone, and pinning survive here in demoted roles.

**Keep the audit-grade requirement and build the independent receipt store it
implies**: rejected for this product by the owner's requirement review. The
deliberation log is working memory; git is the archive; the store would
protect a scenario the product does not have, at the availability and
complexity costs both prior designs measured. Available later as the audit
profile.

**Fail-open with notices only, everywhere**: rejected. What a settled point
settled and what text a ruling ruled on are real assets; section 9.1 protects
them at zero availability cost, and this record keeps it.

**GH Archive as witness or recovery channel**: rejected on measurement,
inherited: one event in sixteen archived for this repository in the hours
probed.

## Open questions

*How does the projection encode what it last saw?* The revision owns the
encoding that makes edit detection precise and idempotent; the per-citation
canonical digest is the candidate, with the REST pair as the auxiliary signal.

*Does a `settled` ruling additionally pin the digest of the proposal it
settles?* It aligns with anchoring decided history and costs one field; the
revision decides, under the same section 3.2 and `invalidated` constraints as
the tombstone encoding.

*What notice class is a moderator deletion of a participant's comment?* The
comparison detects it like any other deletion of cited material; whether the
notice distinguishes insider action when attribution is readable is the
revision's to decide.

*Does anything widen the citation manifest?* Detection covers what the
projection cites. If a class of incorporated material turns out not to be
cited under section 9.2, the revision widens the citations, not the trust
model.
