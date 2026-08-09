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

The revised requirement then passed through review as promised, and its first
mechanism failed there
([review 4881577752](https://github.com/iamers/steve-agent/pull/155#pullrequestreview-4881577752)).
The product reframing held; the floor did not. Four findings, each checked
against the deployed reducer before being accepted: rulings were outside the
detection manifest, so a deleted ruling was silently replaceable against
current permissions; the manifest lived in the mutable projection, which made
detection circular; the manifest did not cover contributions and bound no
digest; and the supersede iteration was named without being a state
transition. The mechanism below is the corrected one, and the sections it
replaced are recorded in the alternatives rather than quietly dropped.

### The product rationale

Steve runs collaboration and development from chat, with GitHub as the
synchronization hub. Activity is continuous: the reducer acts within about a
minute of a comment (#143 runtime measurements, inherited from the superseded
record), and what a deliberation produces is distilled into the repository
through the normal flow, in decisions, commits and pull requests that cite the
issue and the specific comments behind them. That distillate lives in git,
which is already an append-only, content-addressed, distributed, signed store.

This is rationale, not protocol authority. Nothing in this record requires a
terminal decision or an incorporated contribution to reach git before the
weaker retention applies, and a commit that only cites a comment preserves a
link that can die rather than the substance behind it. Whether a session's
output is distilled into the repository is repository practice under section
10.1, and section 10.1 already says session artefacts are not required for
conformance. Making the handoff a protocol obligation was considered and
rejected below; git is why the audit-grade demand was miscalibrated for this
product, and it carries no load in the mechanism.

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
dependencies are two, and both are this project's own contract, tested by its
own fixtures: the canonical digests the reducer already computes under section
3.7, and the reducer's own output records in the comment log, of which rulings
are today's instance. Git is rationale, as said above. The mutable projection
is not among them, which is what the detection mechanism below had to be
rewritten to achieve. The REST `created_at`/`updated_at` pair is auxiliary, and
its blind spot is measured in the table rather than assumed away.

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

**The detection manifest is reducer output in the comment log, and it is not
the projection.** A first version of this record made the section 9.2 citations
the manifest. That was circular in the way section 2.3 prohibits: the issue
body is mutable by any account with write access and by the issue author, the
deployed `replace_projection` appends a fresh projection when both markers are
absent, and so an accidental body edit or an insider removing the manifest and
the incorporated comment together leaves the next run rebuilding from the
reduced inventory with nothing to compare against. The projection is a
rebuildable cache under section 2.6, and a cache cannot be the memory that
detection rests on.

The manifest therefore lives where participants cannot write: in comments
authored by the reducer principal, which is where rulings already live.

*Domain, exact.* The manifest binds **every message whose content affected
protocol state, a ruling, a projection, or a later decision.** Under the
deployed reducer that is, at minimum: every message in `RULING_REQUIRED`
(`configuration`, `settled`, `claim`, `renewal`, `release`, `handoff`,
`cancellation`, `result`, `review-request`, `verdict`), every message in
`DELIBERATION_MESSAGES` (`contribution`, `proposal`, `settled`), and every
ruling the reducer itself appended. `contribution` is the case the citation
manifest missed: `scan_deliberation` advances phase and turn on a valid
contribution, and no section 9.2 entry names it, so an edit or a later
self-deletion could change already-processed input invisibly.

*Binding, mandatory.* Each manifest entry binds the numeric comment id to the
canonical digest of the complete body the reducer incorporated, computed under
section 3.7. This is an obligation of this decision, not a candidate for the
specification revision; only the wire encoding is deferred, under the section
3.2 constraint of one `open-table` block per comment.

*Rulings are in the manifest, and a missing ruling fails closed.* A ruling
entry binds the ruling's own comment id alongside the source id and source
digest it already carries under section 4.16. This closes the gap #154
measured end to end: the deployed `build_github_bundle` derives
`existing_ruling_sources` from the live inventory, so a deleted ruling makes
its source look unruled, `permission_for` is called against current
permissions, and a replacement ruling is emitted for a decision that had
already been decided. When the manifest records a ruling the inventory no
longer contains, the reducer MUST NOT rule again and MUST NOT consult current
permissions: the dependent state is unreplayable and fails closed under
section 9.1, scoped to that state, and the notice names the lost ruling. This
is section 9.1 becoming reachable rather than a new rule; today nothing lets
the reducer know the ruling ever existed.

*The comparison.* On every run the reducer reads its own manifest entries from
the log and compares them against the comment inventory it just read:

- a manifest id absent from the inventory is a detected deletion: the reducer
  emits a supersede notice naming the id and the material it backed, and opens
  the supersede iteration defined below;
- a manifest id whose current body no longer digests to the bound digest is a
  detected edit, noticed the same way. The REST `created_at`/`updated_at` pair
  serves as a cheap auxiliary signal with a measured blind spot: a later-second
  edit moves `updated_at`, a same-second edit does not (#153, comment
  5213750179). The digest comparison is what decides; the pair only cheapens
  the scan.

The floor needs `issues: write` and nothing else, which answers the
minimum-permission question the failed design left to an unproved GraphQL
read. State stays derived from the log alone: the manifest is in the log, the
comparison only emits notices, and the projection keeps its section 2.6 role
of a cache with no evidentiary value. The review's third finding on the failed
record is what this mechanism exists to meet: an author who self-deletes a
proposal after a successful run, inside the #143 cancellation window that
erases the payload guard's one-run memory, is caught because the manifest
bound that proposal.

*What it costs.* The happy path is no longer silent. The reducer already posts
one ruling per permission-sensitive message; the manifest adds a record for
what has no ruling, proposals and contributions, batched as one reducer
comment per run that incorporates new material. The #143 property that
conversation in a session issue is free does not survive intact, and the
record does not pretend otherwise: this is the price of moving the manifest
off a surface participants can rewrite.

*What still defeats it, declared.* Reducer output is a comment, so an insider
with write access can delete a manifest entry, and the material it bound
becomes invisible to the comparison again. One measured fact bounds that case
rather than closing it: an admin deletion of a principal-authored comment
recorded a `CommentDeletedEvent`, and that event is readable without
authentication (#154). So the reducer reads the issue timeline as well as the
comment inventory, one extra read inside the same permission, and any deletion
event it cannot match to a manifest entry becomes an unidentified-loss notice.
Detection degrades from naming what changed to recording that something was
removed; it does not degrade to silence, and it is not proof. Whether a
workflow token sees the acting user in that event is not measured, and is
attribution rather than detection. A participant without write access does not
reach this case at all, on the documented rather than measured row of the
table above: deleting another account's comment requires write access, and the
manifest is not the participant's to delete.

### The supersede iteration, as a state transition

A supersede iteration is a protocol event, not an apology, and this record owes
its semantics rather than the phrase. The affected material degrades, scoped to
the affected message and what depends on it, never the session, and the session
continues throughout. Deterministically:

- **Event family.** One reducer-output notice, `superseded`, naming the
  manifest id, the mutation observed (absent, or digest mismatch), and the
  material it backed. It is reducer output like a ruling, so participants never
  write it and section 9.5 is unchanged. The header encoding is the
  specification revision's, under the same section 3.2 one-block constraint as
  the tombstone.
- **Dependency closure, computed not judged.** The closure of a superseded id
  is: the settled point, open proposal, or notice the manifest bound it to;
  plus any settlement whose `proposal-comment-id` names a superseded proposal;
  plus, transitively, whatever those settlements settled. Nothing outside that
  closure degrades. Rulings whose sources are untouched keep their pinned
  digests, so decided history outside the closure is unaffected.
- **State effect.** Each point in the closure returns to open and is shown as
  superseded in the projection with the notice that opened it. A superseded
  point is not settled and does not satisfy a later reference to its
  settlement.
- **Idempotency.** One notice per `(comment id, bound digest)` pair. A run that
  re-derives the same pair finds its notice already in the log and emits
  nothing, exactly as section 9.1 forbids a second ruling for a source. A
  second mutation of the same comment binds a new pair and earns a new notice.
- **Completion.** The iteration closes when a new valid proposal and its
  settlement re-establish the point, or when a settlement with an explicit drop
  disposition disposes of it. Re-establishment and drop are ordinary
  deliberation under ordinary authority: a settlement still requires its
  authorized ruling, so no new privilege appears here. Until one of the two
  happens the point stays open and superseded, which is a visible state and not
  a stall the projection hides.
- **Termination.** Section 8.3 gains exactly one exception. When the superseded
  material is the terminal settlement itself or the ruling that authorized it,
  the session returns to `open` with that point reopened, and the iteration
  proceeds as above. A supersede of any other material after termination emits
  its notice and does not reopen the session: digests pinned at ruling time
  keep what was decided anchored, which is property 3, and reopening for
  material a terminal decision no longer depends on would be a wider door than
  the requirement asks for.

**Best-effort layers sit on top of detection, and nothing durable rests on
them.**

- *Tombstones from the deletion payload.* The deployed guard that reads a
  deleted comment from its trigger payload writes a tombstone comment first,
  recording the deleted comment's numeric id, numeric author id, trusted
  `created_at`, the canonical digest of the deleted body, and whether it
  carried an `open-table` block. Evidence when the run survives; the
  comparison above covers material the manifest binds when it does not.
- *Original-body recovery via `userContentEdits`.* When an edit is noticed and
  the platform cooperates, the reducer recovers and quotes the pre-edit body.
  When it does not, the notice stands without it. The review's first finding
  is answered by this demotion: the field's non-contractual semantics stop
  being load-bearing because nothing durable reads it.
- *Attribution via `CommentDeletedEvent` and `deletedCommentAuthor`.* Where
  readable, notices name the actor. Attribution is not detection: the
  comparison already established that the mutation happened.

**Fail-closed survives only where rulings are.** Section 9.1 is unchanged in
its words: a deleted or missing source or ruling, a digest mismatch, or
conflicting reuse of an actor/message-id pair still makes dependent state
unreplayable and fails closed, scoped to that dependent state. Rulings pin
their digests at ruling time, so decided history never depends on the
platform's memory. What changes is that "missing ruling" becomes observable.
Without the manifest the deployed reducer cannot distinguish a ruling that was
deleted from one that was never emitted, and it resolves the ambiguity in the
one direction section 9.1 forbids, by consulting current permissions and
ruling again. With the manifest the ambiguity is gone, so the clause applies
where it always claimed to.

**An insider mutation is a detected event that opens an iteration, not
session-fatal tampering.** In a team tool the admin who deletes a comment is
usually doing housekeeping. The prior designs treated insider deletion of
principal output as session death; this record downgrades it to the same
notice-and-supersede path as every other mutation, with attribution where the
platform provides it. This is a security downgrade, made deliberately for a
team tool, and written down as one: the log detects and names insider
mutations where the platform allows, and it does not prove them.

### The non-guarantees, declared

- **A comment created and deleted before any run incorporated it is
  undetectable: a self-deleted, never-incorporated message can disappear
  without trace.** Self-deletion leaves no platform trace (#152), the payload
  guard's memory is one run (#154), and no manifest entry exists to compare
  against. This is a retraction of unincorporated input by its own author, and
  it is declared rather than rounded away.
- **An insider can delete the manifest entry along with what it bound, and the
  comparison then sees nothing.** What survives is the deletion event itself,
  public and unauthenticated (#154), so the loss is visible without being
  identifiable. Detection degrades from "this comment changed" to "reducer
  output was deleted here"; it does not degrade to silence, and it is not
  proof.
- **Nothing requires the substance of a decision to reach git.** Git is why
  audit-grade history is not this log's job, and it is not a protocol gate: a
  session whose output is never distilled keeps only permalinks, which can die.
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
  obligations of this record: the reducer-output manifest and its comparison,
  its `issues: write` minimum permission, notice duties, the best-effort
  layers, and the declared non-guarantees. The conformance gate becomes the
  implementation of those obligations.
- **The manifest**: a new obligation, whose domain and binding this record
  fixes (every message whose content affected state, a ruling, a projection,
  or a later decision; each entry binding numeric comment id to canonical
  digest, rulings included). The revision owns only the wire encoding, under
  the section 3.2 one-block constraint, and whether the manifest is a message
  family of its own or an extension of the existing reducer output.
- **The `superseded` notice**: the event family, the closure rule, the
  idempotency key, and the completion conditions decided above, encoded.
- **Section 8.3**: gains the single termination exception decided above, and
  nothing else: a superseded terminal settlement or its ruling reopens the
  session for that point; every other post-termination supersede notices
  without reopening.
- **Sections 4.16 / 9.1**: unchanged. Ruling pinning and fail-closed on
  ruling-dependent state stay exactly as written; the manifest is what makes
  the missing-ruling branch of 9.1 reachable.
- **Section 9.2**: the projection keeps its permalink citations and its section
  2.6 role as a cache. It is explicitly not the detection manifest, and the
  revision says so, because a first version of this record made that mistake.
  The projection additionally shows superseded points and the notices that
  opened them.
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

The implementation this record authorises is the manifest write, the
comparison and its notices, the scoped supersede path, the tombstone write,
the insider notice, and the best-effort recovery reads. Its tests are a
fixture per row of the threat-model table plus one live drill: a deletion of
incorporated material mid-session, with the criterion that no contribution is
lost and no session is killed. Three fixtures are named because they are the
cases this record was corrected to cover: a deleted ruling must fail closed
and must never trigger a fresh permission lookup; an edited contribution that
already advanced phase and turn must be noticed; and a projection wiped from
the issue body must change nothing about detection. Platform contract probes follow use: a field the implementation
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
than prevented. For a team tool that distils what it decides into git, that
trade buys availability and simplicity with assets that were never this log's
to protect.

The happy path is no longer free, and that is the price of a manifest
participants cannot rewrite. The reducer already posted a ruling per
permission-sensitive message; it now also records what it incorporated without
one, batched per run. The #143 property that conversation in a session issue
costs nothing survives only in the weaker form: a run that incorporates
nothing new still writes nothing. This record chose that cost over a detection
floor that an ordinary body edit could erase.

The platform-dependency profile inverts. The failed design leaned on
non-contractual platform memory and needed a probe suite as a standing
obligation; this design's floor reads comment ids, bodies it digests itself,
its own prior output, and the timeline's deletion events, and treats every
richer platform surface as optional. Probes shrink from an obligation of the design to a property of
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

**The section 9.2 citations as the detection manifest** (this record's own
first version): rejected on review. The citations live in the mutable issue
body, which the issue author and any account with write access can rewrite,
and the deployed `replace_projection` silently re-creates the region when its
markers are gone. Detection resting there is the circular dependency section
2.3 prohibits, wearing a different name. The manifest moved into reducer
output; the citations stay as the human-readable projection they were.

**Requiring an archival handoff into git**: rejected. Making a terminal
decision provisional until its substance lands in an immutable artifact would
turn repository practice into a protocol gate, against section 10.1, which
keeps session artefacts outside conformance. The alternative taken is honesty:
git is rationale, the handoff is not guaranteed, and the missing guarantee is
declared above rather than implied by calling git the archive.

**Fail-open with notices only, everywhere**: rejected. What a settled point
settled and what text a ruling ruled on are real assets; section 9.1 protects
them at zero availability cost, and this record keeps it.

**GH Archive as witness or recovery channel**: rejected on measurement,
inherited: one event in sixteen archived for this repository in the hours
probed.

## Open questions

*How is a manifest entry encoded on the wire?* The domain and the binding are
decided above; the revision owns the encoding, including whether a manifest
entry is a message family of its own or an extension of existing reducer
output, under the section 3.2 one-block constraint.

*Does a `settled` ruling additionally pin the digest of the proposal it
settles?* It aligns with anchoring decided history and costs one field; the
revision decides, under the same section 3.2 and `invalidated` constraints as
the tombstone encoding.

*What notice class is a moderator deletion of a participant's comment?* The
comparison detects it like any other deletion of manifest-bound material;
whether the notice distinguishes insider action when attribution is readable
is the revision's to decide.
