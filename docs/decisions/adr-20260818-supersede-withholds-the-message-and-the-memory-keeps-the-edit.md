---
status: accepted
date: 2026-08-18
amends:
  - adr-20260807-mutations-are-detected-and-superseded.md
---

# A supersede withholds the mutated message, and the memory keeps the edit

## Context

### What this record is, and the order it followed

[The requirement record](adr-20260807-mutations-are-detected-and-superseded.md)
decided that a detected mutation opens a supersede iteration and deliberately
did not decide what that iteration does. It named six things the implementation
record owes: the event family, the dependency closure, the state effect, an
idempotency key, the completion conditions, and the interaction with section
8.3, with a correction already recorded as an obligation rather than left to be
rediscovered.

[The detection record](adr-20260816-detection-is-a-manifest-and-a-conditional-timeline-read.md)
selected the memory and the triggers, listed those same six in full under *What
this record does not decide* "so that nothing is dropped by being left", and
said why they could not be decided there: the first spike measured detection and
lifecycle and measured nothing about what the reducer can do once material is
gone, so deciding the transition would have been "reasoning from a blank page
about questions a second spike answers".

That second spike is done and is the evidence this record decides on:
`.local/design/supersede-transition-spike.md`, run against
`tools/open-table-reduce.py` as installed at `e88657c`, self-test green before
any measurement, no file in the repository modified. Every claim in it is the
literal output of the tool's own `--dry-run --bundle` CLI, the literal return
value of an installed function imported unmodified, or a file:line citation.
Its fixtures descend from the shipped self-test's own `terminal_bundle`, which
is a session an earlier run terminated: a configuration, a proposal, a terminal
settlement, their rulings, and the manifest recording all three.

### What the spike measured

Eight findings, each a fact about installed code.

| Question | Measured result | Where |
|---|---|---|
| What decides the state effect of a mutation today? | Not what depends on the message. Whether the message carried a **ruling**: an edit to a ruled message unbinds it and removes it from derivation, an edit to an unruled one is silently derived from in its new body | spike Q1, `tools/open-table-reduce.py:467-514` |
| Does a detected mutation leave a record? | No. One write, `update_issue_body`, into the cache section 2.6 defines | spike Q1, finding 2 |
| Does a session reopen when the material behind its terminal settlement is superseded? | On a **deletion** yes, silently, as a side effect of a reference check failing. On an **edit** not at all: the point stays projected as `accepted` on text that changed | spike Q2 |
| Can the iteration complete? | Only where the mutation was severe enough to reopen the session. After an edit, section 8.3 discards every re-establishing message | spike Q3 |
| Can anything end an iteration? | No. A fully re-established, re-terminated session still carries the notice, and no record retires one | spike Q4 |
| What identifies superseded material? | `(comment id, digest)`. The section 7.1 triple does **not** survive: a manifest entry carries no actor id and no message id | spike Q5 |
| Is the closure computable? | Yes, by withholding the message and re-deriving with the existing pure `scan_deliberation`. But withholding is **not monotone**: withholding a `configuration` grants effect to messages it excluded | spike Q6 |
| Does the reader already support durable edit evidence? | Yes. Fed two digests for one comment id, `detect_mutations` reports the edit **even with the body restored to the first**. Nothing produces that state today because the writer skips edited comments | spike Q7B, `tools/open-table-reduce.py:1208` |

Two of those shape the whole decision and are worth stating before it.

**A purely derived notice cannot meet the obligation.** Section 2.2 says an
edit of incorporated material MUST NOT be lost silently, and says that against
an account acting only on its own comments this obligation *has no exception*.
Such an account can edit an incorporated message, let a run derive from the
degraded state, and edit it back. If detection is derived from a single pinned
digest and reported only into the projection, the revert erases the report with
the next projection write, and the mutation leaves no trace anywhere. That is
the actor class the protocol promises the most about, and the cheapest design
fails exactly there.

**And the recovery path that every other family has does not exist for
`configuration`.** Section 4.1 requires every configuration to precede every
deliberation message, so a replacement posted after deliberation has begun is
ruled `unauthorized` (measured), and the hand-authored authorized variant makes
the whole session unreplayable (measured, and marked in the spike as
constructed rather than reachable). A superseded configuration cannot be
re-established inside its own session.

### The obligation this transition has to meet

Section 2.2: the iteration is scoped to the affected message and the state
depending on it, never the session; it names what changed or was lost and what
that material backed; re-establishing the material is deliberation like any
other; no act on the comment stream ends a session.

Section 7.3: a message in the domain whose current digest differs from the
digest pinned for it, by a ruling **or by a manifest entry**, has been edited
after incorporation, and the state depending on it MUST fail closed, scoped to
that dependent state. That section also declares the lag this record removes:
*"State that depends on an edited message is named and not yet withheld."*

Section 9.1: a deleted or missing source or ruling makes dependent state
unreplayable and MUST fail closed, scoped to that dependent state.

### What this record amends

One clause of the requirement record, named here rather than left to the front
matter. That record listed "the section 8.3 termination exception" among the
things an implementation record owes; this one finds that no exception is
needed, for the reason decision 7 gives, and meets the obligation without one.
It also reads "the `superseded` notice family" as section 9.2's kind of notice
rather than as a new message family, which is a reading of an ambiguous phrase
and is argued rather than assumed. Nothing else in either earlier record is
reversed: the six items were deferred and not decided, and deciding them is what
this record was asked to do.

## Decision

### 1. A supersede is a withholding, and it is the same withholding for an edit and for a deletion

A message in the domain is **superseded** when it is absent from the comment
inventory, or when its current body's canonical digest differs from a digest
pinned for it by a ruling or by a manifest entry. A superseded message is
**withheld from the derivation**: it contributes nothing to phase, turn,
settled points, open proposals, or to the context of any ruling the reducer
computes afterwards. It is not re-incorporated in its new body.

This is section 7.3's fail-closed, made real for the half of the domain where
it was declared and not applied. It replaces four measured cases with one rule:
today an edit is equivalent to a withholding for a ruled message, a no-op for an
unruled one, and a deletion is a withholding for both. Four cases, three
behaviours, one obligation.

Section 7.3's other rule is untouched and the boundary between them is the pin:
a message with **no** pin of either kind carries no edit signal, is incorporated
now in the body it currently has, and an edit before incorporation means exactly
that. This record withholds only what was pinned, which is why it does not
reintroduce [#144](https://github.com/iamers/steve-agent/issues/144).

The scope of a withholding is not chosen; it is measured. Where another message
occupies the same turn, withholding one changes nothing at all. Where the
withheld message was the only one at its turn, section 5.2's transition rule
breaks the chain and later messages become invalid (spike Q8). The cost is
proportional to how load-bearing the material was, which is what "scoped to the
affected message and what depends on it" has to mean if it is to mean anything.

### 2. The dependency closure is computed, not enumerated

The closure of a superseded message is the difference between the derivation
over incorporated material and the derivation over the same material with that
message withheld. It is deterministic because the derivation is a pure function
of the replay bundle under section 2.5, and it is defined for every family at
once, without a per-family table.

That generality is the point. The requirement record asks for "deterministic
rules for every family in the domain, not only points, proposals, settlements
and notices". A hand-written table would answer that on the day it was written
and would then drift away from the derivation it describes, silently, because
nothing compares the two. Withhold-and-re-derive cannot drift: it *is* the
derivation. The spike computed it against the shipped fixture with no new
machinery, and it costs one extra pure scan over records already in memory,
with no network read.

For a **deleted** message the second term is what the reducer already computes
and the first is not computable, because the body is gone. The closure of a
deletion is therefore not a comparison but a discovery: whatever the derivation
cannot resolve because the message is absent, which is what the reducer already
surfaces today as invalid-message notices for the references that no longer
bind.

### 3. `configuration` is the exception, and its cost is declared rather than argued away

Withholding is not monotone. Measured: adding one proposal from an actor the
configuration does not expect, and then withholding the configuration, does not
subtract that proposal, it **grants it effect**, because
`configuration_context` returns `None`, section 5.4's constraints stop applying,
and the derivation degrades to configuration-free mode.

So for `configuration` the rule of decision 1 is wrong in the dangerous
direction, and a different one applies:

- **A superseded `configuration` withholds the whole deliberation plane of its
  session.** No settled point is derived, no termination is derived, no
  deliberation message is ruled, and the projection says why.
- **A session that lost its configuration is not a configuration-free session.**
  Configuration-free mode under section 4.1 is a session that never had one and
  therefore has no authoritative rulings, termination, work award, or
  projection. A session that had one and lost it has authoritative rulings in
  its log already. The reducer MUST NOT silently treat the second as the first,
  which is what it does today: `t8` projects a *terminated* deliberation with no
  configuration behind it.
- **The material cannot be re-established, and this is the availability
  residual of this record.** Section 4.1's ordering rule makes a replacement
  configuration `unauthorized`. The session is not ended, participants may keep
  posting, and nothing more can be settled in it. Its forward path is a new
  session.

That residual is stated plainly because the alternative is worse in a way this
project has already paid for. Relaxing section 4.1 to admit a late replacement
would let an account with write access rewrite the phase grammar mid-session,
retroactively validating and invalidating past messages. The ordering rule
exists to prevent exactly that, and a recovery path that opens it would buy
availability with the property the rule was protecting.

### 4. The memory records the mutation, as a second manifest entry

On first observing that a message in the domain no longer matches its pin, the
reducer records an additional section 4.18 entry for that comment id, carrying
the digest it now reads.

Nothing else changes. Section 7.6 already says two entries for the same comment
id with different digests are an edit of that message under section 7.3, not a
conflict between manifests. `manifest_memory` already accumulates the digests
into a set and `detect_mutations` already compares the current body against the
whole set. The reader half exists, is specified, and was measured working with
the body restored to the first digest. **The only gap is the writer**, which
skips any comment it has just flagged as edited, so the clause in 7.6 has never
had an input.

This is what makes the withholding durable and revert-proof, and it is the
minimum that does. With one pinned digest, an edit that is reverted becomes
indistinguishable from an edit that never happened, and the obligation section
2.2 states without exception fails against the actor it names. With two, the
memory says the message was superseded at a digest, and no later body restores
it.

Three consequences follow, and they are decided here rather than left:

- **A deletion gets no second entry.** There is no body to digest, GitHub never
  reuses a comment id, and the original entry already binds the loss
  permanently. Recording something for it would be state that answers no
  question.
- **Exactly one additional entry, ever, per comment id.** The reducer records
  the observed digest only while the memory holds a single digest for that
  comment. A message that is already withheld stays withheld whatever happens
  to its body next, so further mutations record nothing. This caps the cost at
  one entry per superseded message and denies an edit loop the ability to
  inflate reducer output.
- **The second entry carries the family the first one carried**, not the family
  the current header claims. An edit can change the `message` value, and a
  memory that followed it would disagree with itself about what was
  incorporated. The family is a property of what the reducer read, and the
  current header may not even parse: an edit that breaks the envelope excludes
  the comment from the records under section 7.5 while leaving its body
  perfectly digestible.

**That second digest is the only new state this transition introduces.**
Everything else decided in this record is derivation over records that already
exist.

One corner is declared rather than solved. Where the current body has no
computable canonical digest under section 3.7, there is nothing to bind and no
entry is written. The message is withheld for as long as the body stays
unreadable, because a body that cannot be digested cannot match the pin, and a
revert from that state is the one case this record's evidence does not cover.
It is named here because an implementation will meet it in
`body_digest` and should not invent an answer.

**No new message family.** The requirement record's deferral names "the
`superseded` notice family with its closure and completion rules", and this
record reads *notice family* as section 9.2 does, a family of notices in the
projection, not a new `open-table` message family. A message family was
considered and rejected: it would be a second reducer-authored comment inside
the detection domain, so it would add another unsealable tip to the one the
detection record already declared, it would multiply reducer output on exactly
the sessions already in trouble, and it would carry a fact the log already
determines. What the log does *not* determine after a revert is the digest that
was observed, and that is one field on a record that already exists.

### 5. An iteration is identified by the comment id and the digest that was incorporated

The idempotency key is `(comment id, incorporated digest)`. It is the only pair
the memory preserves across the whole domain: a manifest entry carries no actor
id and no message id, so for a `contribution` or a `proposal` the section 7.1
triple does not survive its own supersede (measured). Where a ruling exists the
triple survives inside it, and keying on the ruled half only would be a rule
with two cases and no reason for them.

A second mutation of an already-superseded message is **the same iteration**,
not a new one. The message is already withheld, the evidence is already
durable, and there is nothing a second key would let the reducer do.

Notices keep the identity the implementation already gives them, `(code,
comment id)`, merging facts about one comment into one notice
(`tools/open-table-reduce.py:968-978`). That merge is why a deleted source
reported both by the entry that remembered it and by the ruling left pointing at
it is one notice and not two.

### 6. Completion is the restoration of state, and no notice retires

An iteration's **effect** ends when new material re-establishes what the closure
withheld. That is ordinary deliberation: a new message, with a new id, ruled on
its own terms, exactly as section 2.2 already says material is re-established
and exactly as section 4.18 already says a freeze ends.

Its **notice** does not end. The manifest is append-only by section 2.2 and
unrewritable in place by section 4.18, so the record of the mutation is
permanent, and the notice derived from it is permanent with it.

That is a decision and not an omission, and the measurement is why. `t9` is the
iteration completing in full: the deleted proposal re-posted, the point
re-settled terminally, the session terminated again on new material, with the
notice still standing and **nothing blocked by it**. The reducer never waits for
completion, never gates on it, and never needs to compute it. A completion
condition would be state whose only reader is a projection line.

What it costs is that a long-lived session accumulates one detection notice per
mutation for its life. The bound is the number of mutations, not the number of
runs, and mutations are rare by construction. Whether the projection eventually
wants to fold or summarise them is left open under *What this record does not
decide*, alongside the same question
the detection record left open for manifests.

### 7. Section 8.3 needs no exception, and the reopen must be announced

The requirement record's correction is: reopen whenever the computed closure
invalidates or contains the terminal settlement, not only when the terminal
record was mutated directly. Under decision 2 those two words are one predicate,
and the record says so rather than carrying both: **a session reopens when the
terminal settlement's derived validity or effect differs under the closure.**
The two words were written before the closure had a definition; with the
definition they name the same set, because the only thing a change to a validity
can be is a flip.

Nothing else is needed, and this is the part where the measurement contradicts
the expectation the deferral was written with. Section 8.3 makes later
deliberation messages invalid after termination, and termination is *derived*,
not stored. A terminal settlement whose closure is superseded stops
terminating, and section 8.3 then applies to whatever the derivation says is
terminal. `t4` measures the whole path: with the settlement failing, a
deliberation message posted after it is consumed normally and advances the
turn. **There is no temporal exception to write**, no "messages after the
reopen", and no ordering rule to invent, and a determinism problem is avoided
by not creating one: the reduction stays a pure function of its bundle, with no
notion of when a reopen happened.

Two things this record does add:

- **The reopen is announced.** Today it is silent: the session status simply
  reads differently than it did on the previous run, and the projection's only
  subject is the mutated comment. The projection MUST carry a notice whose
  subject is the termination being withdrawn, naming the terminal settlement and
  the superseded message that withdrew it. A decision leaving the log unremarked
  is the shape of defect this project keeps paying for.
- **Decision 4 is what makes the reopen safe**, and this is the second reason it
  is load-bearing. Section 8.1 makes the *earliest* contextually valid terminal
  settlement the one that ends the deliberation. If a superseded message could
  become un-superseded by having its body restored, the original settlement
  would become valid again, and being earliest it would terminate the session
  retroactively, invalidating under section 8.3 every message the recovery
  deliberation had posted. A durable withholding closes that path: the
  settlement behind superseded material never becomes valid again, and the
  re-established decision stands.

There is one dependence no derivation can see, and it is declared rather than
implied: a terminal settlement whose prose summarises a point whose proposal was
edited is affected in a way no closure computes, because the dependence is in
the prose and not in the references. Section 2.3 disclaims the exact text of a
deleted comment and says nothing either way about the prose of one that
survives, so this is a residual this record adds rather than one it inherits.

### Minimum permissions, unchanged, and no probe is owed

`issues: write` and nothing more. This transition reads nothing the reducer does
not already read: the comment inventory, the manifests it wrote, and the rulings
it appended. The requirement record's probe rule is that a field the
implementation reads gets a probe in that implementation's CI, and the
contrapositive is why this record owes none, stated explicitly so that its
absence reads as a conclusion rather than as an oversight. The three probes the
detection record owes are unaffected and remain owed.

### What is now withheld, and what is not

| Case | Before (measured) | After |
|---|---|---|
| Proposal behind a terminal settlement edited | Nothing withheld: the point stays projected `accepted` on text that changed | Withheld; the settlement stops terminating; the session reopens and says so |
| Proposal behind a terminal settlement deleted | Session reopens silently, as a side effect | Same reopen, announced, with the settlement named |
| Terminal settlement or its ruling edited or deleted | Session reopens silently | Same reopen, announced |
| An edit reverted before anyone read the projection | Every trace gone with the next projection write | The second entry keeps it, and the message stays withheld |
| Re-establishing material after an edit | Impossible: section 8.3 discards every new message | Ordinary deliberation, because the settlement no longer terminates |
| `configuration` edited or deleted | Session keeps projecting a terminated deliberation under no configuration | Deliberation plane withheld, declared unrecoverable in that session |
| A withheld message whose turn had another message | n/a | Nothing changes: the scope is measured, not assumed |
| Notice after full re-establishment | Permanent, undecided | Permanent, decided |
| Work-plane families | Unmeasurable under `deliberation-only` | Rule stated, unimplemented, declared in the consequences |

## Consequences

**The declared lag in section 7.3 closes.** That section named the transition
semantics as belonging to "a separate accepted decision, which does not exist
yet". It exists now. Reducer conformance remains withheld all the same, because
section 1.7 makes it the conjunction of every reducer requirement and this is
one of them.

**One class of availability cost is new and is not hidden.** Before this record,
an edit to an incorporated proposal cost nothing and left the session running on
mutated text. After it, the same edit withholds the message, and where that
message was the only one at its turn, later messages become invalid until new
material re-establishes the chain. That is the price of section 7.3's promise
being kept rather than declared, and it is paid in exactly the sessions where
someone edited material that had already been read.

**Reducer output grows by at most one manifest entry per superseded message.**
The detection record sized its own bill as one comment per run with new
material; this adds an entry, not a comment, and caps it at one per comment id
for the life of the session.

**The reduction stays pure and section 2.5 is untouched.** Nothing here reads
the timeline, consults a clock, or depends on which run first observed
anything. The one piece of new state is a digest the reducer read from the
bundle it was given.

**The trust boundary is unchanged.** A compromised principal can write a false
second entry and withhold material that was never mutated, exactly as it could
already author false rulings and advance the watermark falsely. That is the
boundary section 2.3 states, not a new exposure.

**The work plane is decided in rule and not in evidence, and that is said
plainly.** `PROFILE` is `deliberation-only`
(`tools/open-table-reduce.py:44`), so `claim`, `renewal`, `release`, `handoff`,
`cancellation`, `result`, `review-request` and `verdict` drive no projection
under section 9.3 and their closure could not be measured on this deployment.
Decision 1 and decision 2 are stated over the whole domain and apply to them
unchanged, by construction rather than by measurement: withholding a work
message removes it from the derivation the same way, and its closure is what the
same re-derivation reports. What this record does **not** claim is that the
outcome has been observed. The first authority profile that awards exclusive
work owes a measurement, and section 6.4's rule that an active claim ends only
through a recorded event is where the surprise would be if there is one.

### The specification revision this record authorises

Scoped to the transition.

- **Section 2.2**: the transition semantics of a supersede iteration now exist;
  the sentence deferring them names this record.
- **Section 4.1**: a session that lost its configuration is not a
  configuration-free session, and a reducer MUST NOT derive one as the other.
- **Section 4.18**: the writer obligation of decision 4, one additional entry
  carrying the observed digest, at most one per comment id, none for a deletion.
- **Section 7.3**: the declared lag paragraph is replaced by the withholding of
  decision 1, and the boundary with the no-pin rule is kept in the same words.
- **Section 7.6**: unchanged in its words. What changes is that the two-digest
  clause becomes reachable.
- **Section 8.1 and 8.3**: unchanged in their words. The revision states that
  termination is derived, that a terminal settlement whose closure is superseded
  stops terminating, and that no temporal exception exists.
- **Section 9.2**: the detection notices list gains the withdrawn-termination
  notice.
- **Issue [#130](https://github.com/iamers/steve-agent/issues/130)**: the
  supersede-transition point updated from deferred to this record.

### Implementation and test obligations

The implementation comes after this record, per `docs/decisions/README.md`.

**The missing fixture is unblocked.** The requirement record named four
fixtures, and the fourth is *"a supersede of the proposal behind a terminal
settlement must be able to complete its iteration"*. Of the twelve the detection
record counted, it is the one that could not be written, because completing an
iteration was undefined until now; the other eleven are in the self-test. It is `t3` of the spike, which today fails: the
re-establishing message is discarded with `deliberation message follows terminal
settlement`.

Seven more correspond to the numbered decisions of this record. **Six of them
must fail before the implementation and pass after. The seventh, number 6, is a
different kind of test and is stated separately below**, because a list that
promises every item is red makes its one green item read as a failure:

1. an edited `proposal` behind a terminal settlement is withheld, the session
   reopens, and the projection carries a notice whose subject is the withdrawn
   termination;
2. the same session then accepts a re-establishing message and re-terminates on
   it, which is the requirement record's fourth fixture and the missing one;
3. an edit that is **reverted** to the exact incorporated body leaves the
   message withheld and the notice standing, which is the fixture for decision
   4 and the one an implementation that stores a single digest would pass every
   other test while failing;
4. a superseded `configuration` withholds the deliberation plane, derives no
   termination and no settled point, and a replacement configuration does not
   restore it;
5. withholding a message whose turn carries another message changes no derived
   value, which is the guard against a withholding that over-reaches;
6. a message with **no** pin that is edited is incorporated in its current body
   and affects no other message, which is #144's regression guard restated
   against the new rule;
7. a second mutation of an already-withheld message records no further entry
   and changes no derived value.

**Number 6 is a regression guard and it is green today.** Measured against the
reducer as installed: an in-domain `contribution` carrying no ruling and no
manifest entry, edited after it was posted, produces no detection notice, is
incorporated at the digest its current body now carries, advances the turn, and
leaves the session replayable. Section 7.3's no-pin rule is already implemented,
and the shipped self-test already asserts it as `edit signal on an unpinned
message: incorporated as it now reads, not fatal`. It belongs in this list
because decision 1 is the change most likely to break it: withholding a *pinned*
edited message is one line away from withholding an *unpinned* one, and the
fixture that would notice is one that was already passing before anyone touched
anything.

Number 3 and number 6 are the two worth attending to first, for opposite
reasons. Number 3 is the red one where a cheaper implementation looks complete;
number 6 is the green one this record's own change would turn red.

The live drill the requirement record asked for stands unchanged: a deletion of
incorporated material mid-session, with the criterion that no contribution is
lost and no session is killed.

### What this record does not decide

- **How detection notices are presented once there are many.** The detection
  record left the same question open for manifest comments and this record does
  not close it for either. Folding, summarising, or moving them are all
  compatible with everything decided here.
- **The audit profile.** Named, not designed, unchanged.
- **Marker corruption diagnosability.** Out of scope by the detection record,
  still owed its own issue.
- **Whether a `settled` ruling additionally pins the digest of the proposal it
  settles.** Inherited open from both earlier records. It is cheaper again after
  decision 4, and still not needed: the withholding already reaches the
  settlement through the closure.

## Alternatives considered

**Leave the state effect as measured** (an edit withholds a ruled message and
does nothing to an unruled one): rejected, and it is the option that costs
nothing. It is section 7.3's promise applying to half a domain that the same
paragraph defines as one, with the half it skips being precisely the two
families that have no ruling to pin them, `contribution` and `proposal`, which
are the ones the detection record built the manifest for.

**A `superseded` message family authored by the reducer**: rejected. It is what
the requirement record's wording suggests and it buys nothing the second entry
does not. It adds a reducer-authored comment inside the detection domain, so it
adds an unsealable tip; it grows reducer output on the sessions already
degraded; and the fact it would carry is already carried by a record the reducer
writes anyway. Reading "notice family" as section 9.2's kind of notice is what
this record does instead, and it is a reading rather than a reversal.

**Derive the supersede entirely, with no new state**: rejected, and this is the
one that was measured wrong rather than argued down. It is strictly simpler and
it fails against the actor class section 2.2 admits no exception for: an edit
made, derived from, and reverted leaves nothing behind, because the only report
lived in a cache. The revert case is what a second spike is for.

**Record every observed digest, not just the first mutation**: rejected on cost
and on purpose. The message is withheld after the first, so further digests
change no outcome, and an edit loop would otherwise grow the manifest once per
run.

**An enumerated per-family closure table**: rejected. It answers the
requirement record's "every family in the domain" on the day it is written and
drifts afterwards with nothing comparing it against the derivation it claims to
describe. This is the same defect as any hand-maintained copy of a list the
system already has, and the derivation is the list.

**Withhold a superseded `configuration` like anything else**: rejected on
measurement. Withholding is not monotone there: it grants effect to material
the configuration excluded, so the mutation would *add* valid messages to the
session. The cheapest correct rule was to treat the whole deliberation plane as
dependent, which is what decision 3 does.

**Let a replacement `configuration` re-establish a superseded one**: rejected on
what it opens. It would give an account with write access a way to rewrite the
phase grammar mid-session and so retroactively validate or invalidate past
messages, which is the thing section 4.1's ordering rule exists to prevent. The
unrecoverable session is the smaller loss and it is declared rather than
disguised.

**A completion record that retires a notice**: rejected. Nothing reads it. The
measurement is that a fully re-established session already behaves correctly
with the notice standing, so the record would exist to make a projection line
disappear, and it would be one more reducer-authored comment for an insider to
delete.

## Open questions

*Should the withdrawn-termination notice name what the settlement had settled?*
The point identifier and disposition are available from the settlement's own
header and would make the notice readable without following a permalink. It is
left to the implementation, which has the rendering constraints in front of it.

*Does a long-lived session want its detection notices folded?* Left open here
and in the detection record, deliberately in the same shape, because the two
would want the same answer and neither has a session long enough to have
measured the problem.

*What does a work-plane supersede actually do?* The rule is stated and untested,
for the reason the consequences give. The first authority profile that awards
exclusive work should measure it before trusting it, and section 6.4 is the
place to look first.
