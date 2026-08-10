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
transition. Those four are closed.

The corrected mechanism then failed its own review
([review 4892719334](https://github.com/iamers/steve-agent/pull/155#pullrequestreview-4892719334)
and its
[disposition comment](https://github.com/iamers/steve-agent/pull/155#issuecomment-5234189395)),
on three findings inside the mechanism rather than in the requirement. Reading
them together makes the pattern visible, and it is not a pattern of missing
machinery. Two of the three are reachable only by an insider with write
access: a ruling and its manifest entry deleted together, and a manifest record
edited or its newest entry left unbound. This record already conceded that
actor in plain words, calling insider detection a deliberate security
downgrade, while property 2 promised, without qualifying the actor, that
nothing incorporated is ever silently lost. Every review round has found a case
where the unqualified promise fails against the actor the qualified paragraph
had already given up on. The fix is not a fourth mechanism: it is to say which
actor property 2 speaks about, which is what this revision does below. The
third finding, that the dependency closure and the section 8.3 exception
contradict each other, is a defect at any threat model and is carried as an
obligation.

**This record therefore decides the requirement and does not decide the
mechanism.** The reviewer offered the split and it is taken: the comment-log
manifest, its lifecycle, and the supersede algorithm return as a separate
implementation decision. That record still precedes the implementation it
authorises, as `docs/decisions/README.md` requires; what it does not precede is
the evidence. Four mechanisms were designed on this branch and every one died
against a measurement or a reading of the deployed reducer, so the next one is
decided after a spike that answers its open lifecycle questions against the
running code, not from a blank page and a specification.

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
partial, not guarantees a design builds on. What the requirement below may
lean on is this project's own contract, tested by its own fixtures: the
canonical digests the reducer already computes under section 3.7, and records
the reducer itself writes into the comment log, of which rulings are today's
instance. Git is rationale, as said above, and the mutable projection is
excluded by the requirement itself. The REST `created_at`/`updated_at` pair is
auxiliary at best, and its blind spot is measured in the table rather than
assumed away. Which of these a mechanism actually uses is the implementation
record's to decide.

## Decision

**The deliberation log owes three properties, and audit-grade history is not
one of them.**

1. **Contributions are detected, considered, and incorporated.** Unchanged;
   this is what the reducer is.
2. **A participant's mutation of incorporated material is noticed, never
   silently lost, and opens a supersede iteration. An insider's mutation is
   detected where the platform allows it and declared where it does not.** An
   edit or deletion that in practice means a feature changed or work should
   stop produces a named notice and an orderly re-establishment, never a killed
   session.

   The actor scoping is the correction this round makes, and it narrows the
   promise rather than moving it. "Participant" is any account that can act
   only on its own comments; "insider" is an account with repository write
   access, which can edit or delete anyone's comment, including the reducer's
   own output. Against a participant the protocol owes detection with no
   escape: that case is fully inside this project's control, because a
   participant cannot touch the records the reducer writes. Against an insider
   it owes detection where the platform leaves a trace, attribution where the
   platform provides one, and a declaration where it provides neither. The
   record said as much about insiders three paragraphs on from an unqualified
   property 2, and three review rounds spent their findings in the gap between
   the two sentences. An insider is the team, in a tool the team runs; the
   protocol that resists them is the audit profile, named and not designed
   here.
3. **What was decided stays anchored.** Rulings keep pinning digests at ruling
   time under sections 4.16 and 9.1, replay keeps reading recorded permission
   outcomes and never consults current permissions, and the projection stays a
   deterministic function of the log. Determinism stays because it is cheap
   engineering, no second store and free crash recovery, not because it proves
   anything. The weld between determinism and tamper evidence is dropped.

### What detection must satisfy

This record fixes the obligations detection has to meet and leaves the
mechanism to the implementation decision named below. The obligations are
stated as constraints because each one was paid for by a design that failed
against it.

- **Detection may not rest on the mutable issue projection.** Section 2.6
  calls the projection a rebuildable cache, and the deployed
  `replace_projection` appends a fresh one when both markers are absent, so an
  ordinary body edit erases whatever memory lives there. A design that detects
  mutations by comparing against the previous projection is the circular
  dependency section 2.3 prohibits, wearing a different name. This was the
  first corrected mechanism, and it is recorded in the alternatives.
- **Whatever the mechanism remembers, it binds a numeric comment id to the
  canonical digest of the body that was incorporated**, under section 3.7. A
  memory that records ids without digests detects deletions and misses edits;
  this is an obligation, not a candidate.
- **The domain is every message whose content affected protocol state, a
  ruling, a projection, or a later decision.** Under the deployed reducer that
  is every family in `RULING_REQUIRED`, every family in
  `DELIBERATION_MESSAGES`, and every ruling the reducer appended.
  `contribution` is the case the projection citations missed:
  `scan_deliberation` advances phase and turn on a valid contribution while no
  section 9.2 entry names it.
- **A permission-sensitive source whose ruling may have been lost is never
  re-ruled against current permissions.** Section 9.1 already says a deleted or
  missing ruling makes dependent state unreplayable and fails closed; the
  deployed `build_github_bundle` cannot reach that branch, because it rebuilds
  `existing_ruling_sources` from the live inventory, finds the source unruled,
  and calls `permission_for`. Whatever the mechanism is, it must make that
  branch reachable, including when the loss is visible but unidentified. This
  is the one integrity asset the record keeps, so ambiguity resolves toward
  fail-closed and never toward a fresh lookup.
- **The floor is `issues: write` and nothing else.** Reading the comment
  inventory and the issue timeline, and writing reducer output, are inside it;
  a design that needs more permission than that is answering a question this
  requirement did not ask.

Two properties follow from the actor scoping and are stated here so the
implementation record inherits them rather than rediscovering them. Against a
participant these obligations are met with no residual, because a participant
cannot delete or edit what the reducer wrote. Against an insider they are met
where the platform leaves a trace and declared where it does not, which is what
the non-guarantees below say in full.

### The supersede iteration, and what the implementation record owes it

A supersede iteration is a protocol event, not an apology. The affected
material degrades, scoped to the affected message and what depends on it, never
the session; the notice names what was lost or changed and what it backed;
re-establishing the material is deliberation like any other, and the session
continues throughout. That is the requirement.

Its transition semantics were drafted here and did not survive review, so they
move to the implementation record with the defect already found. The
implementation record owes: the event family; the dependency closure; the state
effect; an idempotency key; the completion conditions; and the interaction with
section 8.3, which is where the draft broke. The closure pulled in a settlement
whose `proposal-comment-id` named a superseded proposal, while the termination
rule reopened the session only when the terminal settlement or its ruling was
mutated directly. For a mutation of the proposal behind a terminal settlement
those two rules disagree: the point is open and the session is terminated, and
section 8.3 then invalidates the very message the completion condition
requires. The correction is recorded as an obligation rather than left to be
rediscovered: **reopen whenever the computed closure invalidates or contains
the terminal settlement, not only when the terminal record was mutated
directly**, and give the closure deterministic rules for every family in the
domain above, not only points, proposals, settlements and notices.

### What sits on top, and what stays fail-closed

**Best-effort layers sit on top of detection, and nothing durable rests on
them.**

- *Tombstones from the deletion payload.* The deployed guard that reads a
  deleted comment from its trigger payload writes a tombstone comment first,
  recording the deleted comment's numeric id, numeric author id, trusted
  `created_at`, the canonical digest of the deleted body, and whether it
  carried an `open-table` block. Evidence when the run survives; detection
  covers the material it remembers when it does not.
- *Original-body recovery via `userContentEdits`.* When an edit is noticed and
  the platform cooperates, the reducer recovers and quotes the pre-edit body.
  When it does not, the notice stands without it. The review's first finding
  is answered by this demotion: the field's non-contractual semantics stop
  being load-bearing because nothing durable reads it.
- *Attribution via `CommentDeletedEvent` and `deletedCommentAuthor`.* Where
  readable, notices name the actor. Attribution is not detection: detection
  established that the mutation happened before attribution is attempted.

**Fail-closed survives only where rulings are.** Section 9.1 is unchanged in
its words: a deleted or missing source or ruling, a digest mismatch, or
conflicting reuse of an actor/message-id pair still makes dependent state
unreplayable and fails closed, scoped to that dependent state. Rulings pin
their digests at ruling time, so decided history never depends on the
platform's memory. What this record adds is the obligation that makes the
clause reachable. The deployed reducer cannot distinguish a ruling that was
deleted from one that was never emitted, and it resolves the ambiguity in the
one direction section 9.1 forbids, by consulting current permissions and
ruling again. The mechanism must remove that ambiguity, and where it cannot
remove it, it must resolve it toward fail-closed: an unresolved doubt about
whether a ruling existed is not a licence to look up current access.

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
  guard's memory is one run (#154), and nothing was ever remembered about it
  to compare against. This is a retraction of unincorporated input by its own
  author, and it is declared rather than rounded away.
- **An insider can defeat detection of a specific mutation, and property 2 is
  scoped accordingly.** Whatever the mechanism remembers, an account with write
  access can delete or edit it, because it is a comment like any other. What
  survives is the deletion event, public and unauthenticated (#154), so an
  insider deletion is visible without being identifiable; an insider edit of
  reducer output leaves whatever the platform's edit metadata leaves, which the
  table above measures as non-contractual. Against that actor the protocol owes
  a declaration, and this is it. Against a participant there is no such
  residual: a participant cannot touch what the reducer wrote.
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
candidate stores failed. Section 1.7's standing rule is untouched, and the
split lengthens rather than shortens the road to it: the deployment claims no
reducer conformance until the implementation decision below, the specification
revision, and the implementation itself all exist.

### What this record does not decide

The mechanism, deliberately, and the obligations it inherits are named here so
that nothing is dropped by being moved:

- **Where the reducer's memory of what it incorporated lives, and how it is
  written.** The requirement excludes the mutable projection and fixes the
  binding and the domain; everything else, including whether the memory is a
  message family of its own or an extension of existing reducer output, belongs
  to the implementation decision.
- **The lifecycle that makes "incorporated" true.** The commit point after
  which material counts as incorporated, whether a source may affect state, a
  ruling, a projection or a later decision before its binding is durable, and
  how the reducer's own output enters that lifecycle. The deployed order is the
  opposite of what a naive reading assumes, since a ruling has no comment id
  until after it is written, and the #143 cancellation window makes the
  ordering load-bearing.
- **How the newest record of that memory is protected, or the exact residual
  if it cannot be.** This is the unsealable tip that ended the checkpoint
  chain, met again in another shape; the implementation decision either solves
  it or declares it in the same plain words used above.
- **The supersede transition**, with the closure and termination correction
  already recorded as an obligation.
- **Whether an ambiguity barrier is the right shape for the fail-closed
  obligation.** The reviewer's proposal, treating every otherwise-unruled
  permission-sensitive source ordered before an unmatched deletion event as
  potentially having lost its ruling, satisfies the obligation. It also
  freezes, apparently permanently, sources that were in flight when an ordinary
  housekeeping deletion happened, since the event stays in the timeline and no
  resolution path is defined. Availability is the asset this whole revision was
  bought with, so the implementation decision weighs that cost explicitly
  instead of inheriting the shape.

### The specification revision this record authorises

One revision of `docs/specs/open-table-v0.md`, scoped to the requirement. The
sections that encode a mechanism wait for the implementation decision, and the
revision may be done in two passes rather than held hostage to it:

- **Section 2.2**: append-only stays a protocol convention and correction
  stays a new message, unchanged. The creation-receipt machinery (authenticated
  receipt capture, digest match, `lastEditedAt` null, edit-equals-unreplayable)
  is replaced by detect-and-supersede: mutations of incorporated material are
  detected and flagged, never silently lost against a participant, and open a
  supersede iteration; no participant act on the comment stream ends a session.
- **Section 2.3**: the store paragraph is replaced by the detection
  obligations of this record, stated as obligations rather than as a design:
  the excluded surface, the `(comment id, canonical digest)` binding, the
  domain, the fail-closed resolution of ruling ambiguity, the `issues: write`
  minimum permission, and the declared non-guarantees with their actor scope.
  The conformance gate becomes the implementation of those obligations, which
  the implementation decision selects.
- **Sections 4.16 / 9.1**: unchanged. Ruling pinning and fail-closed on
  ruling-dependent state stay exactly as written.
- **Section 9.2**: the projection keeps its permalink citations and its section
  2.6 role as a cache, and the revision says explicitly that it is not the
  reducer's memory of what it incorporated, because a version of this record
  made exactly that mistake.
- **Deferred to the implementation decision, and named so the spec does not
  half-encode them**: the memory's wire encoding, the `superseded` notice
  family with its closure and completion rules, the section 8.3 termination
  exception, and the tombstone encoding under the section 3.2 one-block
  constraint and the `invalidated` sole-ruling constraint.
- **Audit profile**: named as a future authority-profile extension for
  adopters who need a ledger (external witness repository, the Certificate
  Transparency shape, or both prior designs revived). It is also where an
  adopter who does not accept the insider scoping of property 2 is sent.
  Named, not designed; nothing in this record forecloses it.
- **Issue #130**: point I recorded as dissolved by this revision; point 2
  updated to the detect-and-supersede reading.

### Implementation and test obligations

The implementation decision comes after a spike and before the implementation
it authorises: the spike measures the lifecycle questions above against the
deployed reducer, the record decides on that evidence, and only then is the
mechanism built, which is the order `docs/decisions/README.md` already asks
for. Its tests are a fixture per row of the threat-model table plus one live drill:
a deletion of incorporated material mid-session, with the criterion that no
contribution is lost and no session is killed. Four fixtures are named now,
because they are the cases three review rounds paid for and no mechanism may
quietly fail: a deleted ruling must fail closed and must never trigger a fresh
permission lookup; an edited contribution that already advanced phase and turn
must be noticed; a projection wiped from the issue body must change nothing
about detection; and a supersede of the proposal behind a terminal settlement
must be able to complete its iteration. Platform contract probes follow use: a
field the implementation reads (for recovery or attribution) gets a probe in
that implementation's CI; a field nothing reads gets none. The scheduled daily
pass survives with its #143 stale-session rationale unchanged, and is what
bounds detection latency when event-driven runs are cancelled.

## Consequences

The #144 denial of service closes completely. No act by a participant on the
participant's own comment, and no act by an insider on anyone's comment, ends
a session. The strongest remaining consequence in the comment stream is scoped
unreplayability of ruling-dependent state under section 9.1, which protects
the one asset that kept fail-closed semantics.

What the design defends changed shape honestly. Before: prove the log intact
or refuse to run. After: never lose a participant's incorporated material
silently, keep decided history pinned, keep the session alive. The cost is
named in the non-guarantees: no proof of absence, no ledger, insider acts
detected where the platform allows rather than prevented. For a team tool that
distils what it decides into git, that trade buys availability and simplicity
with assets that were never this log's to protect.

The happy path is probably no longer free, and the record does not pretend to
know the bill. Any memory that participants cannot rewrite is something the
reducer writes, so it costs reducer output; how much depends on the mechanism,
which is why the number is the implementation decision's to state and not this
one's. What is decided is the direction: this record chose a cost it cannot yet
size over a detection floor that an ordinary body edit could erase.

The platform-dependency profile inverts. The failed design leaned on
non-contractual platform memory and needed a probe suite as a standing
obligation; what this requirement permits is comment ids, bodies the reducer
digests itself, and its own prior output, with every richer platform surface
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

**The section 9.2 citations as the detection manifest** (this record's own
first mechanism): rejected on review. The citations live in the mutable issue
body, which the issue author and any account with write access can rewrite,
and the deployed `replace_projection` silently re-creates the region when its
markers are gone. Detection resting there is the circular dependency section
2.3 prohibits, wearing a different name. It survives above as a requirement,
the excluded surface, rather than as a design.

**Deciding the comment-log mechanism in this record** (its second mechanism):
rejected on review, and the split taken instead. The mechanism was sound
enough to close the four findings before it, and its remaining gaps were the
lifecycle ones no argument can settle without evidence: the commit point, the
protection of the newest record, the shape of the ambiguity barrier and its
availability cost. Keeping it here would have bought a fourth round of
reasoning about questions a spike against the deployed reducer answers in an
afternoon. The material is not lost: its obligations are listed above and the
working design is kept with the branch's notes.

**Keeping property 2 unqualified and building the mechanism the insider case
implies**: rejected, and this is the change of substance in this round. It is
the audit-grade requirement returning through a side door, since resisting an
account with write access to the comment stream is precisely what a ledger is
for. The record already conceded that actor; qualifying the property is the
honest form of a concession that was already made, and it is declared here
rather than left to be discovered by the next review. An adopter who needs the
unqualified promise needs the audit profile.

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

The mechanism questions are not open questions here: they are the subject of
the implementation decision, listed under what this record does not decide.
What remains open at the requirement layer is smaller.

*Does a `settled` ruling additionally pin the digest of the proposal it
settles?* It aligns with anchoring decided history and costs one field, and it
is the one place where a mechanism choice would strengthen property 3 rather
than property 2. The implementation decision decides it, under the section 3.2
and `invalidated` constraints.

*What notice class is a moderator deletion of a participant's comment?*
Detection treats it like any other deletion of remembered material; whether the
notice distinguishes insider action when attribution is readable is left open,
and it is presentation rather than protection.

*Does the actor scoping of property 2 survive contact with a second adopter?*
It rests on the insider being the team that runs the tool. A repository where
write access is broader than the deliberating group would want the audit
profile, and would say so when the specification moves out of this repository
under section 11.2.
