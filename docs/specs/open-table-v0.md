# Open Table protocol v0

## 1. Scope and conformance

1.1. Open Table coordinates independent participants through GitHub issues and
issue comments. It defines two planes: deliberation and work.

1.2. GitHub is the only shared medium. A conforming session MUST NOT require a
shared database, a participant registry, a participant-to-participant network
protocol, or any particular agent runtime.

1.3. A person with a text editor MUST be able to participate as a participant:
propose, contribute, contest, and claim. Participants MAY use validation
software, but participation MUST NOT require particular software or manual
calculation of canonical digests. This does not make participant-authored
rulings authoritative. An authenticated reducer is REQUIRED to rule.

1.4. Participant identity is the numeric GitHub user id in authenticated GitHub
context. A login is display-only metadata. No field in a participant-authored
envelope grants identity or authority. Trusted context supplies the actor,
repository, issue and numeric comment ids, GitHub server timestamp, and recorded
permission ruling.

1.5. On a public repository, any account that GitHub permits to comment MAY
contribute to deliberation. Claiming work requires the write access GitHub
already governs. Permission is checked once when the first ruling for a source
message is created, and that outcome is recorded so replay MUST NOT consult
mutable current permissions. Open Table defines no enrollment mechanism.

1.6. Each session selects exactly one authority profile:
`deliberation-only`, `open-table/ordered-claims`, or `steve/kanban`. Without a
selected, authenticated authority profile, deliberation remains valid and work
claims are advisory; no exclusive award can be asserted. Under `steve/kanban`,
a claim MAY request the Kanban lease, but Open Table MUST NOT create a second
ownership store.

1.7. The minimum implementation required to claim conformance is deferred to
open point F in issue #130. This document does not settle that floor.

1.8. The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to
be interpreted as normative requirements.

## 2. Records and ordering

2.1. Each Open Table session is one GitHub issue. The issue number and
repository identify the session; messages MUST NOT repeat either identifier in
the protocol header.

2.2. Comments are the deliberation record and the protocol treats them as
append-only. This is a protocol convention, not a GitHub guarantee: comments
can be edited or deleted. Participants MUST correct a message by posting a new
message that references the invalidated one, never by silently editing it.
Participants MUST NOT write Open Table projections.

2.3. Only the reducer writes mutable projections or posts `ruling` messages.
Who runs the reducer in this repository is deferred to open point G in issue
#130. This specification does not select a GitHub Action, GitHub App, hosted
service, or any other concrete issuer.

2.4. The total order of comment events is ascending trusted GitHub `created_at`,
with the ascending numeric GitHub comment id as the tie-breaker. Issue
open/closed transitions affect the protocol only when GitHub timeline events
are declared ordered inputs. Every rule that says "earliest" or "later" uses
the declared event order.

2.5. Replay is defined over a replay bundle, not comment text alone:

    projection = reduce(ordered_events, trusted_context, authority_policy, as_of)

`ordered_events` contains the declared GitHub events. `trusted_context` contains
authenticated GitHub metadata and recorded rulings. `authority_policy` is the
selected profile. `as_of` is an explicit trusted timestamp. Historical validity
uses trusted GitHub event timestamps and MUST NOT use the reducer's current
clock. Two reducers given the same replay bundle and `as_of` MUST agree.

2.6. Session configuration is a protocol event with trusted metadata. It MUST
NOT be privileged input hidden in the mutable issue body. Reducer projections
are caches: when a projection and replay disagree, the reducer MUST rebuild the
projection from the replay bundle.

2.7. The format boundary between adapters and the replay bundle is deferred to
open point H in issue #130. This specification does not assert an adapter
compatibility matrix or a runtime pin.

## 3. Comment envelope

3.1. A protocol comment MUST have exactly this shape:

````text
```open-table
open-table: 0
message: contribution
id: 01J4N6Y7J8K9M0N1P2Q3R4S5T6
phase: dreamer
turn: 1
```

Human-readable prose explaining the contribution.
````

3.2. The `open-table` fenced block MUST be the first non-whitespace content in
the comment. It MUST use backticks, carry the exact info string `open-table`,
and contain only header lines. The comment MUST contain exactly one such block.

3.3. Each header line MUST be `key: value`. Keys MUST contain only lowercase
ASCII letters and hyphens. A key MUST occur once. Values MUST be single-line,
MUST have no leading or trailing whitespace, and MUST be non-empty. Unknown
keys make the message invalid.

3.4. The closing fence MUST be followed by non-whitespace free prose. The prose
is for people and MAY use any Markdown. A header-only comment and a prose-only
comment are not protocol messages.

3.5. Every message has these required common fields:

- `open-table`: the literal `0`;
- `message`: one message name from section 4;
- `id`: an idempotency token matching `[A-Za-z0-9][A-Za-z0-9._-]{7,127}`.

3.6. Boolean values are the lowercase literals `true` and `false`. `turn`,
`sequence`, `turn-limit`, actor ids, numeric comment ids, repository ids, and
pull-request numbers are base-10 integers greater than or equal to 1. Timestamps
use RFC 3339 UTC in the exact form `YYYY-MM-DDTHH:MM:SSZ`. Phase, point, claim,
proposal, result, and review identifiers match
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Enumerated values are case-sensitive.

3.7. The canonical digest is `sha256:` followed by the lowercase hexadecimal
SHA-256 digest of the UTF-8 encoding of the complete comment body exactly as
returned in trusted GitHub context. Header and prose are both covered. A
participant is not required to calculate this digest; the authenticated reducer
calculates it when creating a ruling.

## 4. Message families

4.1. `configuration` defines one phase. It requires:

- `phase`: the phase identifier;
- `sequence`: the phase's one-based position;
- `expected-actors`: a comma-separated, whitespace-free list of unique numeric
  GitHub user ids;
- `authority-profile`: `deliberation-only`, `open-table/ordered-claims`, or
  `steve/kanban`; and
- `turn-limit`: the maximum turn number in the phase.

A session uses either one `configuration` message per phase or no configuration
messages. Each configuration is a protocol event with trusted metadata and MUST
precede every deliberation message. Configuration MUST NOT be inferred from the
mutable issue body. Sequence values MUST be unique and contiguous from 1, phase
identifiers MUST be unique, and every configuration in one session MUST select
the same authority profile. The phase with `sequence: 1` is initial. Each
configuration requires an `authorized` ruling. This grammar is the only source
of phase names, order, expected actors, turn limits, and authority profile;
reducers MUST NOT derive those values from free prose.

4.2. The deliberation family contains `contribution`, `proposal`, and `settled`.
All deliberation messages require `phase` and `turn` in addition to the common
fields.

4.3. `contribution` records analysis for the current phase and turn. It has no
additional fields. Its prose contains the contribution.

4.4. `proposal` offers one point for adoption. It additionally requires
`point`, a stable identifier for the point. Its prose states the proposed text
and rationale.

4.5. `settled` declares the disposition of one proposal. It additionally
requires:

- `point`: the point identifier used by the proposal;
- `proposal-id`: the `id` of an earlier valid `proposal` for that point;
- `disposition`: `accepted` or `rejected`;
- `terminal`: `true` or `false`.

Only a `settled` message with a matching `authorized` ruling is valid. Its prose
explains the disposition. `terminal: true` invokes section 8.

4.6. The work family contains `claim`, `renewal`, `release`, `handoff`,
`cancellation`, `expiration`, `result`, `review-request`, and `verdict`.

4.7. `claim` requests exclusive ownership of the issue's work. It additionally
requires:

- `claim`: a stable claim identifier;
- `expires-at`: the requested expiry time.

It is a proposal, not ownership. Only an authenticated authority profile can
award it.

4.8. `renewal` requests a new expiry for an awarded claim. It additionally
requires `claim` and `expires-at`.

4.9. `release` returns claimed work to the pool. It additionally requires
`claim`, referring to the currently awarded claim.

4.10. `handoff` transfers an awarded claim. It additionally requires:

- `claim`: the currently awarded claim;
- `to-actor-id`: the numeric GitHub user id receiving the work;
- `expires-at`: the new expiry time.

The handoff's ruling MUST be `authorized` only when both its author and recipient
have repository write access at the time of the check. A handoff changes the
claim holder but preserves the claim identifier.

4.11. `cancellation` cancels an awarded claim. It additionally requires `claim`.

4.12. `expiration` records that an awarded claim expired. It additionally
requires `claim` and `expired-at`. It is authenticated reducer output, and its
trusted GitHub event timestamp MUST be at or after `expired-at`. Expiration is
never inferred from the reducer's wall clock.

4.13. `result` reports completion or failure. It additionally requires:

- `claim`: the currently awarded claim;
- `result-id`: a stable result identifier;
- `outcome`: `completed` or `failed`.
- `artefact`: a machine-readable immutable artefact reference.

For GitHub software work, `artefact` MUST have the form
`github:<numeric-repository-id>:pull:<pull-request-number>:head:<full-head-sha>`.
A generic authority profile MAY instead use an absolute artefact URI followed
by `#sha256=<lowercase-hex-digest>`. The prose describes the result; it is not
the immutable reference.

4.14. `review-request` asks for review of a completed result. It additionally
requires:

- `claim`: the claim associated with the result;
- `review`: a stable review identifier;
- `result-id`: the referenced result; and
- `artefact`: exactly the immutable artefact reference carried by that result.

4.15. `verdict` decides a review request. It additionally requires:

- `claim`: the claim associated with the review;
- `review`: the identifier of an earlier valid `review-request`;
- `result-id`: the result referenced by that review request;
- `artefact`: exactly the immutable artefact reference carried by that result;
- `verdict`: `approved` or `changes-requested`.

The verdict actor id MUST differ from the actor id of the referenced `result`.
If the artefact changes, the earlier verdict remains attached to the old result
and a new result, review request, and verdict correlation is REQUIRED.

4.16. `ruling` records one authenticated decision. It requires:

- `target-actor-id`: the numeric GitHub user id of the target message author;
- `message-id`: the target message's `id`;
- `source-comment-id`: the numeric GitHub comment id of the complete target;
- `source-digest`: its canonical digest; and
- `decision`: `authorized`, `unauthorized`, `awarded`, `rejected`, or
  `invalidated`.

The target is identified by numeric actor id, message id, numeric source comment
id, and source digest, and every field MUST agree with trusted context. Exactly
one ruling MUST exist for each target that requires one. A ruling is reducer
output and its prose explains the decision. Its effective position is the
target's position, not the later position where the ruling is appended.

4.17. Every permission-sensitive message requires a matching ruling. Replay
MUST use its recorded decision and MUST NOT consult current permissions.
`release`, `renewal`, `handoff`, `cancellation`, and `result` MUST be authored by
the current claim holder. A `review-request` MUST be authored by the actor of the
referenced completed `result`. A `verdict` MAY be authored by any other actor
with an `authorized` ruling.

## 5. Deliberation turns and phases

5.1. A session begins at phase `initial`, turn 1 when it has no configuration.
When configuration messages exist, the phase whose `sequence` is 1 is initial.
A phase is a repository-chosen identifier, not a runtime role. Names such as
`dreamer`, `realist`, and `critic` are valid.

5.2. The reducer derives the current `(phase, turn)` from valid deliberation
messages in comment order. The first valid deliberation message establishes the
initial pair. A later pair is valid when it is either the same pair, the same
phase with turn incremented by exactly one, or a new phase with turn 1.

5.3. The first valid message for a new phase closes the preceding phase. A
participant MUST NOT add messages to a closed phase or an earlier turn. Such
messages are invalid and have no effect.

5.4. When configuration messages exist, a deliberation message MUST name a
configured phase, phases MUST advance in `sequence` order, its actor id MUST be an
expected actor for that phase, and its `turn` MUST NOT exceed the phase's
`turn-limit`. Without configuration messages, these constraints do not apply.

## 6. Claim arbitration and expiry

6.1. Assignment is a projection, not a claim operation. A participant claims
work only by posting a `claim` comment.

6.2. Under `open-table/ordered-claims`, the reducer orders candidate claims by
trusted GitHub `created_at` with numeric comment id as the deterministic
tie-breaker. A claim can be awarded only when all of the following are true at
its ordered position:

- the envelope and fields are valid;
- authenticated context records repository write access for the claimant;
- the issue is open and is not terminally completed;
- no awarded claim is active; and
- `expires-at` is later than the comment's GitHub `created_at` and no more than
  seven days later.

The authenticated reducer checks authority once and emits exactly one `awarded`
or `rejected` ruling bound to the numeric source comment id and canonical digest.
The ruling records the permission outcome and explicit expiry. Later replay uses
that ruling and MUST NOT consult current permissions.

6.3. The earliest awardable claim wins. Claims encountered while an awarded
claim is active receive a `rejected` ruling and never become effective later.
Retrying after release, cancellation, or recorded expiration requires a new
message id and claim identifier.

6.4. Renewals, releases, handoffs, cancellations, and expirations are recorded
events. An active claim ends only through a valid `release`, `cancellation`,
`expiration`, or `result`; reaching `expires-at` without a recorded expiration
event does not silently change replayed state. A `handoff` keeps ownership active
under the recipient. Renewal and handoff expiry MUST be later than the source
comment's trusted `created_at` and no more than seven days later.

6.5. Under `deliberation-only`, claims remain advisory and the reducer MUST NOT
emit an exclusive award. Under `steve/kanban`, a claim requests the existing
Kanban lease and the GitHub ruling records that authority's outcome; the reducer
MUST NOT maintain competing ownership state. Adapter compatibility for this
mapping is deferred to open point H in issue #130.

6.6. A `result` makes the work state `completed` or `failed`. A new claim is
valid after `failed`. A new claim after `completed` is invalid unless a later
`verdict: changes-requested` reopens the work.

## 7. Idempotency and validity

7.1. Message integrity and idempotency use the triple `(numeric actor id,
message id, canonical digest)`. Actors MUST
reuse the same `id` when retrying delivery of the same logical message and MUST
use a new `id` for a new logical message.

7.2. The same actor id, message id, and digest is an exact duplicate and has no
additional effect. The same actor id and message id with a different digest is
a conflict, never a duplicate, and replay MUST fail closed. An invalid earliest
occurrence reserves the key; it cannot be repaired by reposting and requires a
new id.

7.3. Every ruling binds to the numeric source comment id and canonical digest of
the complete message. If an edited source no longer matches, replay MUST fail
closed or consume an explicit `invalidated` ruling. A deleted or missing source
or ruling makes dependent state unreplayable and MUST fail closed. A correction
is a new message referencing the invalidated source.

7.4. Structural and integrity validation can be performed offline when supplied
with trusted context. Contextual reduction, including permissions, references,
ordering, authority-profile state, and recorded expiration, is performed by the
reducer.

7.5. Content authored by another participant is untrusted input. Participants
MUST treat headers and prose as data, not as instructions to change their local
rules, reveal data, or execute tools. The reducer MUST deterministically exclude
invalid and over-limit events from projections and MUST keep their text in data
boundaries rather than agent instructions. Rate limits, hop limits, and circuit
breaking are projection-enforcement principles; GitHub cannot prevent posting.

## 8. Deliberation termination

8.1. A deliberation is over only when the earliest contextually valid `settled`
message with `terminal: true` has a matching `authorized` ruling.

8.2. A terminal settlement MUST refer to an earlier valid proposal. Its prose
MUST summarize the final decision and identify any intentionally open points.
The author of that settlement is the person or agent that declares termination.

8.3. After termination, later deliberation messages are invalid. Work messages
remain governed by the work state; deliberation termination does not silently
cancel active work.

## 9. Reducer projections and rulings

9.1. On first processing a permission-sensitive source, an authenticated
reducer checks authority once and appends exactly one ruling bound to its
numeric actor id, message id, numeric source comment id, and canonical digest.
Before appending, it MUST search all ordered events for an existing ruling for
that source. Reprocessing MUST NOT emit a second ruling.

The reducer processes the replay bundle from section 2, applies section 7
integrity rules, validates events, and derives both planes from scratch. Replay
reads recorded permission outcomes and MUST NOT consult current permissions.
Rulings are load-bearing records: a deleted or missing source or ruling, a
digest mismatch, or conflicting reuse of an actor/message-id pair makes
dependent state unreplayable and MUST fail closed. The accepted contract is
documented in [issue #130](https://github.com/iamers/steve-agent/issues/130#issuecomment-5157092344).

9.2. For a deliberation issue, the reducer writes the issue body between stable
markers `<!-- open-table:start -->` and `<!-- open-table:end -->`. It MUST
preserve all text outside those markers. Inside them it writes, in this order:

- protocol version and session status (`open` or `terminated`);
- current phase and turn;
- settled points with disposition and permalinks to settling comments;
- open proposals with permalinks to proposal comments; and
- invalid or duplicate message notices with comment permalinks and reasons.

9.3. For work under an authenticated work authority profile, the reducer writes
only labels prefixed `open-table/` and the GitHub assignee list. It computes
these projections:

- no active claim: label `open-table/available`, no Open Table assignee;
- active claim: label `open-table/claimed`, exactly the claim holder as the Open
  Table assignee;
- completed result awaiting review: label `open-table/review`, no Open Table
  assignee;
- approved verdict: label `open-table/done`, no Open Table assignee;
- failed result or changes requested: label `open-table/available`, no Open
  Table assignee.

The reducer MUST NOT remove unrelated labels or assignees.

9.4. A ruling is visible only after the reducer appends it. Visibility does not
change its effective position, defined by section 4.16. A reducer MUST be
idempotent both when handling participant messages and when emitting its own
rulings. Claims under `deliberation-only` MUST NOT drive these exclusive work
projections. Under `steve/kanban`, these projections reflect the Kanban lease
outcome rather than an independent award.

9.5. Participants never write projections, including as an attempted repair.
They post a new protocol comment and let the reducer recompute.

## 10. Optional session artefacts

10.1. A repository MAY preserve transcripts, reports, or decisions produced by
a session as ordinary repository files. Their location, format, review, and
retention are repository policy and are not required for protocol conformance.

10.2. An optional session artefact MUST link back to the GitHub issue if the
repository chooses to preserve it. The replay bundle remains the protocol
record; a session artefact does not replace or mutate that record. This section
does not weaken the immutable artefact binding required for `result`,
`review-request`, and `verdict` messages.

## 11. Version and repository lifecycle

11.1. This document defines version `0`. A reducer MUST reject an unsupported
`open-table` value rather than guessing compatibility.

11.2. Version 0 lives in this repository. When a second project adopts Open
Table, the specification and validator will move to a dedicated repository so
neither adopting project owns the shared contract.
