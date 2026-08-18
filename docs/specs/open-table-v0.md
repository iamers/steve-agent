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
`deliberation-only`, `open-table/ordered-claims`, or `steve/kanban`. The profile
MUST declare one or more reducer principals from trusted GitHub metadata. Each
principal is the positive numeric GitHub user id attached to the author of a
reducer-authored issue comment in trusted context. When an App installation
authors that comment, the principal is its bot account's comment-author user id,
not the App id or installation id. Logins and names are display-only metadata,
and no field from comment payload grants reducer authority. Without a selected,
authenticated authority profile,
deliberation remains valid and work claims are advisory; no exclusive award can
be asserted. Under `steve/kanban`, a claim MAY request the Kanban lease, but
Open Table MUST NOT create a second ownership store.

1.7. Participant conformance requires composing and parsing the envelope
correctly and treating peer content as untrusted. A conforming participant is
never required to compute a canonical digest, validate a replay bundle, or
implement replay. Reducer conformance requires everything else this document
requires. The two roles carry very different burdens, and collapsing them would
place the reducer's cost on every participant, contradicting the razor in
section 1. This repository currently ships a reference envelope and integrity
validator, not a reducer-conformant implementation.
A deployment MAY operate while explicitly declaring its unmet reducer
guarantees, but this creates no additional conformance tier: it MUST NOT
represent itself or any session it processes as reducer-conformant until every
reducer requirement is satisfied.

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

Because the platform does not enforce the convention, a mutation of material
the reducer has already incorporated is detected rather than prevented. A
replay adapter MUST supply the complete trusted comment inventory for the
session and a complete issue timeline capable of exposing deletions. An edit or
deletion of incorporated material MUST be detected and MUST NOT be lost
silently. Against an account that can act only on its own comments this
obligation has no exception. Against an account with repository write access,
which GitHub permits to edit or delete any comment including the reducer's own
output, it holds where the platform leaves a trace; section 2.3 declares the
residual where it does not.

The complete issue timeline is a *replay* input. A live adapter MAY defer
fetching it for a given run, but only while the reduction provably does not
consult it: the deferral condition MUST be a predicate over the comment
inventory and the reducer's own memory alone, evaluable before the fetch, and it
MUST NOT be able to change a fail-closed outcome. Section 2.3 names the
conditions under which the accepted mechanism reads the timeline. A bundle
offered as a replay bundle still carries the complete timeline as this paragraph
requires.

A detected mutation MUST open a supersede iteration. The iteration is scoped to
the affected message and the state depending on it, never to the session: it
names what changed or was lost and what that material backed, re-establishing
the material is deliberation like any other, and the session continues
throughout. No act on the comment stream ends a session. What a lost source or
ruling still costs is the scoped unreplayability of section 9.1. Section 2.3
states the obligations detection MUST meet and the guarantees it does not make;
the transition semantics of a supersede iteration and the form its notice takes
belong to the separate accepted decision section 2.3 requires.

2.3. Only an issuer matching a reducer principal allowed by the selected
authority profile writes mutable projections or posts `ruling`, `expiration`, or
`manifest` messages. A
GitHub Action remains this repository's intended first reducer implementation,
but no conforming *deployment* has been selected or implemented in version 0 as
currently shipped. That is a separate statement from the detection mechanism
below, which is selected: a selected mechanism that nothing implements still
leaves every deployment non-conforming.

Detection under section 2.2 requires the reducer to remember what it
incorporated. This specification fixes what that memory MUST satisfy; the
mechanism that satisfies it is selected further down this section, and the
obligations below are what that selection had to meet:

- **The memory MUST NOT be the mutable issue projection.** Section 2.6 makes
  the projection a rebuildable cache, so detection resting on the previous
  projection is circular: the act that mutates the material can erase the
  memory of it. The mutable issue projection, workflow caches, and
  retention-bound Action artefacts are neither detection memory nor replay
  sources.
- **The memory MUST bind the numeric GitHub comment id to the canonical digest
  of section 3.7 for the body that was incorporated.** A memory of comment ids
  alone detects deletions and misses edits.
- **Its domain is every message whose content affected protocol state, a
  ruling, a projection, or a later decision.** That includes every family
  requiring a ruling under section 4.17, every deliberation message under
  section 4.2, and every ruling the reducer appended. A `contribution` is in
  the domain because it advances phase and turn under section 5.2 even though
  no section 9.2 entry names it.
- **A permission-sensitive source whose ruling may have been lost MUST NOT be
  ruled again against current permissions.** Section 9.1 already fails closed
  on a deleted or missing ruling; detection MUST make that outcome reachable,
  including where the loss is visible but does not identify the affected
  comment. Where the ambiguity cannot be removed, it MUST resolve toward
  failing closed: an unresolved doubt about whether a ruling existed is not
  licence to consult current access.
- **The minimum permission is GitHub `issues: write` and nothing more.**
  Reading the comment inventory, reading the issue timeline, and writing
  reducer output are inside it.

Detection does not make these guarantees, and they are declared rather than
implied:

- A comment created and deleted before any run incorporated it is undetectable.
  Nothing was remembered about it to compare against.
- An account with repository write access can edit or delete any comment,
  including reducer output, and can therefore defeat detection of a specific
  mutation. Against that actor the protocol owes detection where the platform
  leaves a trace, attribution where the platform supplies one, and this
  declaration where it supplies neither. Against an account that can act only
  on its own comments there is no such residual, because such an account cannot
  reach what the reducer wrote. An adopter who does not accept this scope needs
  an authority profile that provides a ledger, and version 0 defines none.

  This clause is where the deepest reachable case lands, and it is named rather
  than left to be inferred. Deleting a source, its ruling, and the reducer's
  memory of both removes every record that could say *which* comment was lost.
  What survives is that something was deleted, so the loss MUST become visible
  and unidentified rather than silent: the reducer names the deletions it cannot
  account for and refuses, under the paragraph above, to rule anything pending
  against current permissions. The residual against this actor is therefore a
  denial of availability that declares itself, not a silent loss.
- The deliberation log is not audit-grade history. It does not prove
  completeness, absence, or the exact text of a deleted comment.

Before an Action deployment can claim reducer conformance, a separate accepted
decision MUST select the mechanism meeting these obligations and define its
lifecycle, minimum permissions, concurrent-write behavior, and fail-closed
recovery, and that mechanism MUST be implemented.

**That decision now exists and this section records what it selected**:
`docs/decisions/adr-20260816-detection-is-a-manifest-and-a-conditional-timeline-read.md`.
The memory is the `manifest` message family of section 4.18, authored by a
reducer principal, one logical manifest per run that has something to record,
which section 4.18 allows to be split across comments when it must. Its
lifecycle is that rulings are written first, the manifest that records them
second, and the projection last, so that the residue of an interrupted run is a
memory that lags the log rather than a memory that accuses the log; recovery
from that residue reads the surviving ruling and records the entry on the next
run, without a fresh permission lookup. Its concurrent-write behavior is section
7.6. Its fail-closed recovery is the rule that a manifest entry whose comment is
absent from the inventory is an identified loss under section 9.1, and that a
permission-sensitive source with neither a ruling nor an entry is resolved by
reading the timeline: when the observed count of comment-deletion events equals
the accounted watermark the source is new and is ruled as usual, and when the
two disagree in either direction the source is frozen under section 4.18 and
MUST NOT be ruled. Equality rather than inequality is required, so that a
failure of the assumption that timeline events are undeletable presents as an
unaccounted deletion rather than as an all-clear.

The mechanism places two obligations on the deployment adapter rather than on
the reduction, and a deployment that only subscribes to comment events satisfies
neither:

- **Runs for one session MUST NOT execute concurrently.** Section 7.6 makes
  repeated writes harmless; it cannot make a concurrent write safe, because one
  run can freeze a source while another, holding a stale watermark, performs the
  current-permission lookup this section forbids. That lookup is an act, and no
  later record undoes it.
- **The adapter MUST read the timeline periodically**, independently of incoming
  comment events, so that detection latency is bounded by a clock rather than by
  the next incorporated message. A run woken by a comment-deletion event MUST
  also read it. Without the periodic read, a session in which nothing
  permission-sensitive is pending can absorb a deletion that the platform did
  record and that nothing ever looks at.

**The reduction implements this mechanism, and both adapter obligations are now
deployed.** `tools/open-table-reduce.py` reads and writes the section
4.18 family, holds the commit point stated above, applies the barrier, and reads
the timeline on all three of the conditions named here: a pending
permission-sensitive source with neither a ruling nor an entry, a run woken by a
comment-deletion event, and a periodic run that declares itself one. The
periodic read is deployed as a scheduled workflow that enumerates the open
session issues and calls the same reduction once per session, hourly, so the
read happens whether or not the conversation moves, which is the action the
obligation above states. Both entry points build their concurrency group at a
single site, so a swept run and an event-driven run for the same session
serialise against each other, which is what the first obligation requires.

**What that does not buy is an upper bound**, and the first observation is the
reason to say so rather than to imply one. The platform queues scheduled
workflows on a best-effort basis and suspends them in repositories inactive for
60 days, and the first scheduled run of this sweep executed one hour, forty-one
minutes and fifty-one seconds after the workflow reached the default branch,
against a nominal hourly period. So the deployment shortens the window in which
a recorded deletion goes unexamined and does not bound it. **Whether that counts
as satisfying the obligation is deliberately not settled here.** The obligation
is stated as a periodic read whose rationale is a bound; this deployment
performs the read and does not realise the bound, and reading the rationale as
normative or as explanatory gives opposite answers. The wording predates any
deployment, so nothing had to answer it until now, and the question belongs to a
decision of its own rather than to the paragraph that first ran into it: it is
recorded as issue 178 of this repository. An
adopter who needs the bound realised needs an adapter whose clock it controls,
which this one is not.

**Deploying both adapter obligations is not reducer conformance**, and the two
were tied together in the previous wording of this paragraph. Section 1.7 makes
reducer conformance the conjunction of every reducer requirement in this
document, so these are necessary rather than sufficient: work claims
remain advisory and this repository MUST NOT claim reducer conformance. A future Action deployment's
authenticated issuer would be its token and its principal the bot account's
positive numeric comment-author user id from trusted GitHub metadata. The
principal remains per-repository deployment configuration, not a global
identity; another repository adopting this protocol selects its own. A GitHub
App is the graduation path when a second repository adopts this protocol. The
profile declares the principal, and replay verifies the actual author against
it.

2.4. The total order of comment events is ascending trusted GitHub `created_at`,
with the ascending numeric GitHub comment id as the tie-breaker. Issue
open/closed transitions affect the protocol only when GitHub timeline events
are declared ordered inputs. Every rule that says "earliest" or "later" uses
the declared event order.

2.5. Replay is defined over a replay bundle, not comment text alone:

    projection = reduce(ordered_events, trusted_context, authority_policy, as_of)

`ordered_events` contains the complete declared GitHub issue timeline, including
comment-deletion evidence when GitHub exposes it. That is a requirement on
replay, and section 2.2 states when a live adapter MAY defer the fetch; the
reduction itself is the same pure function either way, and two reducers given
the same bundle and `as_of` still MUST agree. `trusted_context` contains
authenticated GitHub metadata, including each event's actual author,
`created_at`, `updated_at`, `lastEditedAt`, and recorded rulings. `updated_at`
and `lastEditedAt` are auxiliary edit signals supplied when GitHub supplies
them: no requirement of this specification rests on either, and detection is
the obligation of section 2.3. `authority_policy` is the selected profile
and its allowed reducer principals. `as_of` is an explicit trusted timestamp.
Historical validity uses trusted GitHub event timestamps and MUST NOT use the
reducer's current clock. Two reducers given the same replay bundle and `as_of`
MUST agree.
The deployment adapter, not participant content, MUST authenticate and bind
`trusted_context` and `authority_policy` to the numeric repository and issue
identifying the session.

2.6. Session configuration is a protocol event with trusted metadata. It MUST
NOT be privileged input hidden in the mutable issue body. Reducer projections
are caches: when a projection and replay disagree, the reducer MUST rebuild the
projection from the replay bundle.

2.7. An adapter profile MAY declare a supported runtime pin internally when its
safety properties were verified against a specific source. When it does, that
declaration creates the obligation for this project to create and maintain the
compatibility matrix, one row per upstream release, evaluated when an official
release appears. No Open Table adapter currently declares such a pin. The pin
does not move by chasing an unreleased branch.

2.8. The comment-event integrity slice validates only what is supplied to it:
envelope structure, trusted event
ordering, numeric identity, canonical digests, reducer-output principals,
duplicates, conflicts, ruling bindings, and event-local timestamps. Its input
is not the complete replay bundle from
section 2.5: it intentionally has no
`trusted_context`, deletion timeline, or `as_of` field and performs no
contextual reduction, permission lookup, claim arbitration, result/review
correlation, or projection write. The deployment adapter MUST supply a complete
trusted comment inventory; this slice cannot prove completeness by itself. A
green integrity check therefore MUST NOT be represented as reducer conformance.
Within this integrity slice an edit signal is not fatal and is not detection:
the slice holds no memory of what a reducer incorporated, so it cannot tell an
edited body from the body that was ruled on, and sections 2.2 and 2.3 place
that obligation on the reducer instead. A ruling whose bound `source-digest`
disagrees with its source remains fatal here, because that comparison needs no
memory beyond the bundle.

A `manifest` supplied inside a bundle does not change that boundary, and the
symmetry with the ruling above is deliberately not extended. The slice validates
a manifest's envelope: its grammar, its record syntax, and that its author is an
allowed principal. It MUST NOT treat a disagreement between an entry's digest
and the current body of the comment it names as fatal. Such a disagreement is
the ordinary edit of incorporated material, which section 2.2 requires to open a
supersede iteration scoped to that message, and making it fatal here would
restore, through this slice, the whole-session unreplayability that scoping
exists to remove. Any first-occurrence comment from an allowed reducer principal
that begins an `open-table` block but fails strict envelope, UTF-8 scalar, or
event-local validation is also fatal; malformed participant input is instead
excluded deterministically as section 7.5 requires. Exact retries are identified
before event-local checks and remain inert under section 7.2.

`tools/open-table-validate.py --integrity-bundle` is this repository's reference
implementation of the slice.

The integrity-bundle serialization is a closed JSON schema in version 0. Its
top-level object MUST contain exactly `authority_policy` and `ordered_events`.
`authority_policy` MUST contain exactly `profile` and `reducer_principals`.
`profile` is one authority-profile string named in section 1.6.
`reducer_principals` is a non-empty array of unique positive JSON integers, each
at most 20 decimal digits and identifying one reducer principal as section 1.6
defines it. Every numeric id token MUST match `[1-9][0-9]{0,19}` and be decoded
losslessly; fractional or exponent forms and runtimes that coerce the value
through binary floating point are not conforming. JSON strings, booleans, zero,
and negative values are not actor ids.
`ordered_events` is an array whose elements MUST each contain exactly
`actor_id`, `comment_id`, `created_at`, `updated_at`, `last_edited_at`, and
`body`. `actor_id` and `comment_id` are positive JSON
integers of at most 20 decimal digits; `created_at` and `updated_at` are strings
in the exact timestamp form from section 3.6; `last_edited_at` is JSON null or a
string in that same form; and `body` is a
JSON string. Object member names MUST be unique before any value is interpreted.
Duplicate, missing, or additional keys at any of these three levels are invalid.

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
the comment. Its opening and closing fences MAY be indented by zero to three
ASCII spaces, matching Markdown fenced-code indentation, but MUST NOT use tabs
or four or more spaces. It MUST use backticks, carry the exact info string
`open-table`, and contain only header lines. The comment MUST contain exactly
one such block under the same indentation grammar.

3.3. Each header line MUST be `key: value`. Keys MUST contain only lowercase
ASCII letters and hyphens. A key MUST occur once. Values MUST be single-line,
MUST have no leading or trailing whitespace, and MUST be non-empty. Unknown
keys make the message invalid.

A message family MAY declare a field *optional*. An omitted optional field is
neither a missing required field nor an unknown key, and its meaning when
omitted MUST be stated by the family. Every field of every family named in
section 4 is required unless that family says otherwise; the only optional
fields in version 0 are the two in section 4.18. Because a key occurs at most
once, a field carrying a variable-length list encodes the whole list in one
value, as `expected-actors` already does. Physical lines use LF or CRLF only. Bare carriage
returns and Unicode line-separator characters such as U+0085 and U+2028 are
invalid and MUST NOT be interpreted as header line endings.

3.4. The closing fence MUST be followed by non-whitespace free prose. The prose
is for people and MAY use any Markdown. A header-only comment and a prose-only
comment are not protocol messages.

3.5. Every message has these required common fields:

- `open-table`: the literal `0`;
- `message`: one message name from section 4;
- `id`: an idempotency token matching `[A-Za-z0-9][A-Za-z0-9._-]{7,127}`.

A message name MUST NOT contain `/`. This is a constraint on every future
family, not a description of the current ones: section 4.18 uses `/` as the
field separator inside a manifest record, so a family whose name contained one
would be a valid envelope that the reducer's own memory could not represent.
The reference implementation asserts this over its family table rather than
restating the list.

3.6. Boolean values are the lowercase literals `true` and `false`. `turn`,
`sequence`, `turn-limit`, actor ids, numeric comment ids, repository ids, and
pull-request numbers use ASCII digits `[0-9]` and are base-10 integers greater
than or equal to 1. Their canonical text has no leading zero and contains at
most 20 digits. A field this document defines as a *count* uses the same digits
and the same canonical text but is greater than or equal to 0, because a count
of nothing is a value and not an absence; the sole count in version 0 is
`deletions-accounted` in section 4.18. Its canonical text for zero is `0`. Timestamps use RFC 3339 UTC in the exact form
`YYYY-MM-DDTHH:MM:SSZ`. Phase and point identifiers match
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Enumerated values are case-sensitive.

3.7. The canonical digest is `sha256:` followed by the lowercase hexadecimal
SHA-256 digest of the UTF-8 encoding of the complete comment body exactly as
returned in trusted GitHub context. Header and prose are both covered. A
participant is not required to calculate this digest; the authenticated reducer
calculates it when creating a ruling.

3.8. The common `id` remains actor-scoped for idempotency. Cross-message
references MUST instead use the trusted numeric GitHub comment id of the
declaration being referenced. A declaration does not predict or allocate that
id: GitHub assigns it when the comment is created, and a later participant can
copy it from the declaration's permalink. A `settled` message references its
proposal comment; every later claim operation references the initial claim
comment; a review request references the result comment; and a verdict
references both the result and review-request comments. The reducer verifies
that each id names an earlier, contextually valid declaration of the required
family. Human-readable labels belong in prose and never create a session-global
namespace.

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
messages. Configuration-free mode is limited to participant-conformance,
advisory `deliberation-only` messages: it has no authoritative rulings,
termination, work award, or reducer projection. A reducer-conformant session
MUST include configuration messages and derive its authority profile from them;
the top-level replay `authority_policy` MUST match that declared profile. Each
configuration is a protocol event with trusted metadata and MUST precede every
deliberation message. Configuration MUST NOT be inferred from the mutable issue
body. Sequence values MUST be unique and contiguous from 1, phase identifiers
MUST be unique, and every configuration in one session MUST select the same
authority profile. The phase with `sequence: 1` is initial. Each configuration
requires an `authorized` ruling. This grammar is the only source of phase names,
order, expected actors, turn limits, and authority profile; reducers MUST NOT
derive those values from free prose. The reference integrity slice MAY validate
a partial comment-event set without configuration, but that does not make the
set a reducer-conformant replay bundle under section 2.5.

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
- `proposal-comment-id`: the trusted numeric GitHub comment id of an earlier
  valid `proposal` for that point;
- `disposition`: `accepted` or `rejected`;
- `terminal`: `true` or `false`.

Only a `settled` message with a matching `authorized` ruling is valid. Its prose
explains the disposition. `terminal: true` invokes section 8.

4.6. The work family contains `claim`, `renewal`, `release`, `handoff`,
`cancellation`, `expiration`, `result`, `review-request`, and `verdict`.

4.7. `claim` requests exclusive ownership of the issue's work. It additionally
requires `expires-at`, the requested expiry time. Its trusted numeric GitHub
comment id is the canonical claim reference used by later work messages.

It is a proposal, not ownership. Only an authenticated authority profile can
award it.

4.8. `renewal` requests a new expiry for an awarded claim. It additionally
requires `claim-comment-id` and `expires-at`.

4.9. `release` returns claimed work to the pool. It additionally requires
`claim-comment-id`, referring to the initial comment of the currently awarded
claim.

4.10. `handoff` transfers an awarded claim. It additionally requires:

- `claim-comment-id`: the initial comment of the currently awarded claim;
- `to-actor-id`: the numeric GitHub user id receiving the work;
- `expires-at`: the new expiry time.

The handoff's ruling MUST be `authorized` only when both its author and recipient
have repository write access at the time of the check. A handoff changes the
claim holder but preserves the claim comment reference.

4.11. `cancellation` cancels an awarded claim. It additionally requires
`claim-comment-id`.

4.12. `expiration` records that an awarded claim expired. It additionally
requires `claim-comment-id` and `expired-at`. It is authenticated reducer output,
and its trusted GitHub event timestamp MUST be at or after `expired-at`. Expiration is
never inferred from the reducer's wall clock. Its actual author MUST match an
allowed reducer principal. An expiration-shaped comment from any other actor is
untrusted prose and has no protocol effect.

4.13. `result` reports completion or failure. It additionally requires:

- `claim-comment-id`: the initial comment of the currently awarded claim;
- `outcome`: `completed` or `failed`.
- `artefact`: a machine-readable immutable artefact reference.

The result comment's trusted numeric GitHub comment id is its canonical result
reference.

For GitHub software work, `artefact` MUST have the form
`github:<numeric-repository-id>:pull:<pull-request-number>:head:<full-head-sha>`.
A generic authority profile MAY instead use an absolute artefact URI followed
by `#sha256=<lowercase-hex-digest>`. The URI MUST use the RFC 3986 ASCII
serialization: non-ASCII octets are percent-encoded, each percent escape is two
hexadecimal digits, and characters excluded by RFC 3986 (including backslash
and controls) are invalid. The prose describes the result; it is not the
immutable reference.

4.14. `review-request` asks for review of a completed result. It additionally
requires:

- `claim-comment-id`: the initial claim comment referenced by the result;
- `result-comment-id`: the trusted numeric GitHub comment id of the referenced
  result; and
- `artefact`: exactly the immutable artefact reference carried by that result.

The review-request comment's trusted numeric GitHub comment id is its canonical
review reference.

4.15. `verdict` decides a review request. It additionally requires:

- `claim-comment-id`: the initial claim comment referenced by the review;
- `review-comment-id`: the trusted numeric GitHub comment id of an earlier valid
  `review-request`;
- `result-comment-id`: the result comment referenced by that review request;
- `artefact`: exactly the immutable artefact reference carried by that result;
- `verdict`: `approved` or `changes-requested`.

The verdict actor id MUST differ from the actor id of the referenced `result`
and MUST have repository write access recorded in trusted context at the
verdict's ordered position. If the artefact changes, the earlier verdict remains
attached to the old result and a new result, review request, and verdict
correlation is REQUIRED.

4.16. `ruling` records one authenticated decision. It requires:

- `target-actor-id`: the numeric GitHub user id of the target message author;
- `message-id`: the target message's `id`;
- `source-comment-id`: the numeric GitHub comment id of the complete target;
- `source-digest`: its canonical digest; and
- `decision`: `authorized`, `unauthorized`, `awarded`, `rejected`, or
  `invalidated`.

The target is identified by numeric actor id, message id, numeric source comment
id, and source digest, and every field MUST agree with trusted context. During
replay, a ruling is valid only when its actual author from the trusted event
wrapper matches a reducer principal allowed by the active authority profile. A
ruling-shaped comment by any other author is not a ruling: replay MUST
deterministically exclude it from the projection, treat it as prose, and MUST
NOT reject the bundle or make the log unreplayable because of it. Exactly one
valid ruling MUST exist for each target that requires one. A ruling is reducer
output and its prose explains the decision. Its effective position is the
target's position, not the later position where the ruling is appended.

4.17. Every permission-sensitive message requires a matching ruling. Replay
MUST use its recorded decision and MUST NOT consult current permissions.
`release`, `renewal`, `handoff`, `cancellation`, and `result` MUST be authored by
the current claim holder. A `review-request` MUST be authored by the actor of the
referenced completed `result`. A `verdict` MAY be authored by any other actor
with repository write access recorded at its ordered position. `configuration`
and `settled` MUST be authored by an actor with repository write access recorded
at their ordered position. A `claim` is ruled `awarded` or `rejected` by the
predicate in section 6.2. Every other family named in this paragraph is ruled
`authorized` exactly when its stated actor, reference, state, and permission
predicates all hold, and `unauthorized` otherwise. The base profiles MUST NOT
use `awarded` or `rejected` for those families, nor `authorized` or
`unauthorized` for a claim. `invalidated` is reserved for adapter-defined
trusted-context invalidation before any other ruling exists; it MUST be the sole
ruling for its source. An edit after a ruling is not repairable by a second
ruling and fails closed under section 7.

4.18. `manifest` is the reducer's record of what it incorporated. It is
authenticated reducer output: its actual author MUST match an allowed reducer
principal, and a manifest-shaped comment from any other actor is untrusted prose
with no protocol effect, excluded deterministically as section 7.5 requires. A
manifest requires no ruling and is never itself ruled.

It requires:

- `deletions-accounted`: the count, as defined in section 3.6, of comment
  deletion events in the issue timeline that the reducer has accounted for.

It optionally carries:

- `entries`: what this run incorporated. Omitted when the run incorporated
  nothing;
- `frozen`: the sources this run refused to rule. Omitted when it refused none.

`entries` is a comma-separated, whitespace-free list of records. Each record is
`<comment-id>/<digest>/<family>` for a source the reducer incorporated without
appending a ruling, and `<comment-id>/<digest>/<family>/<ruling-comment-id>` for
one it ruled. `<comment-id>` is the trusted numeric GitHub comment id of the
incorporated message, `<digest>` its canonical digest under section 3.7 for the
body that was incorporated, `<family>` its `message` value, and
`<ruling-comment-id>` the trusted numeric comment id of the ruling that binds
it. A comment id MUST occur at most once in one `entries` value. The separator
is `/` because it occurs in no comment id, digest, or family name, so a record
splits on positions rather than on a delimiter that its own fields could
contain.

`frozen` is a comma-separated, whitespace-free list of `<comment-id>/<count>`
records, naming a source the reducer refused to rule and the
`deletions-accounted` reading that froze it. A comment id MUST occur at most
once in one `frozen` value.

The domain the memory MUST cover is section 2.3's, and it is a contextual
requirement rather than a structural one: an entry naming a family outside the
domain is structurally well-formed. A digest is mandatory in every entry, and
section 2.3 states why a memory of comment ids alone is not sufficient.

The reducer records one manifest per run that has something to record, and none
for a run that has nothing. **That unit is the logical record, not a comment
count**: a manifest whose text would exceed the platform's comment size limit
MUST be split across several `manifest` comments, each a complete message with
its own `id` under section 7.1, and each carrying the same
`deletions-accounted`. Section 7.6 defines the memory over the set of surviving
manifests, so the parts of a split are equivalent to the whole and a reader
never has to know whether a split happened. A manifest MUST NOT be rewritten in place: it is inside the detection
domain, section 2.2 keeps the log append-only, and an in-place rewrite is
exactly the mutation this mechanism exists to notice.

A source named in `frozen` MUST NOT be ruled while it is frozen, and MUST NOT be
unfrozen by a later manifest. It is re-established the way section 2.2
re-establishes any material, by a new message with a new id, which is ruled on
its own terms.

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
message id; GitHub assigns the new claim comment its own canonical reference.

6.4. Renewals, releases, handoffs, cancellations, and expirations are recorded
events. An active claim ends only through a valid `release`, `cancellation`,
`expiration`, or `result`; reaching `expires-at` without a recorded expiration
event does not silently change replayed state. A `handoff` keeps ownership active
under the recipient. Renewal and handoff expiry MUST be later than the source
comment's trusted `created_at` and no more than seven days later.

6.5. Under `deliberation-only`, claims remain advisory and the reducer MUST NOT
emit an exclusive award; a claim ruling under this profile MUST be `rejected`
unless the sole reserved `invalidated` decision applies. Under `steve/kanban`, a
claim requests the existing Kanban lease and the GitHub ruling records that
authority's outcome; the reducer MUST NOT maintain competing ownership state.
Adapter compatibility for this mapping follows section 2.7.

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
the complete message, pinned when the ruling is created. That pin, not the
platform's memory of the comment, is what anchors decided history. A current
body whose canonical digest differs from the digest its ruling pinned is a
mutation of incorporated material: section 2.2 requires it to be detected,
within the actor scope stated there, and the state depending on that ruling
MUST fail closed, scoped to that dependent state.

A ruling is not the only pin, and it cannot be: `contribution` and `proposal`
require no ruling under section 4.17, yet a `contribution` advances phase and
turn under section 5.2. A section 4.18 manifest entry is the pin for those, and
it binds the same two things. The comparison and its consequence are therefore
stated once for both:

- a message in the domain whose current digest differs from the digest pinned
  for it, by a ruling or by a manifest entry, has been edited after
  incorporation, and the state depending on it MUST fail closed, scoped to that
  dependent state, opening the supersede iteration of section 2.2;
- a message with no pin of either kind carries no edit signal, because nothing
  was incorporated to be changed. It is incorporated now, in the body it
  currently has, and an edit before incorporation means exactly that. A reducer
  MUST NOT treat such an edit as a fault, and MUST NOT let it affect any message
  other than the one edited;
- a comment that is not a protocol message is outside the domain and is ignored.

The second rule is normative rather than permissive, and the reason is
recorded: a reducer that fails the whole session on any edit signal denies
service to a session through an edit to a comment it never read, which is
[issue #144](https://github.com/iamers/steve-agent/issues/144).

The interim reducer this repository ships, `tools/open-table-reduce.py`, now
holds the comparison above. The blanket check that used to reject any comment
whose trusted edit metadata was set, before asking whether that comment was a
protocol message at all, is gone; it went in the change that brought the section
4.18 memory, which is what made removing it something other than replacing an
over-broad detection with none.

One lag remains and is declared here rather than left to be discovered. State
that depends on a *ruling* does fail closed scoped, because a source whose
ruling was lost is never ruled again, so nothing it would have authorized takes
effect. State that depends on an *edited* message is named and not yet withheld:
the reducer reports the edit and continues to derive from the inventory it was
given. What a supersede iteration then does to that state is the transition
semantics section 2.2 assigns to a separate accepted decision, which does not
exist yet, and section 1.7 withholds any conformance claim in the meantime.
A deleted or missing source or ruling makes dependent state
unreplayable and MUST fail closed. A correction is a new message with a new id;
it does not rewrite the invalidated history.

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

7.6. A manifest is a message and is identified by the section 7.1 triple like
any other. Because a run can write twice, after a partial failure or after being
superseded once it had already posted, the reducer's memory is defined over the
**set of surviving manifest comments** rather than over the most recent one:

- **Entries are the union.** A source is remembered if any surviving manifest
  records it. Two entries for the same comment id and digest are the same fact.
  Two entries for the same comment id with different digests are an edit of that
  message under section 7.3, not a conflict between manifests, and are handled
  as one.
- **`deletions-accounted` is the maximum.** Each reading was written by a
  reducer principal that had accounted for those events, so the highest is the
  true accounting. Taking the minimum would re-raise resolved deletions forever.
- **`frozen` is the union**, and section 4.18 governs how a freeze ends.
- **A freeze beats a ruling for the same source.** If the surviving set contains
  both, the source stays frozen and the ruling is invalid: it recorded a
  decision taken against current permissions at a moment when section 2.3
  required failing closed, so it is the record that MUST lose.

Taking the maximum is the permissive direction, and it is sound only because
writing a manifest requires a reducer principal. A compromised principal can
advance the watermark falsely exactly as it could already author false rulings,
and that is the trust boundary section 2.3 states rather than a new exposure.
Deleting the newest manifest lowers the effective watermark and removes its
entries, which makes detection more conservative, not less.

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
- open proposals with permalinks to proposal comments;
- invalid or duplicate message notices with comment permalinks and reasons; and
- detection notices under section 2.3, each naming the affected comment and
  whether it was lost, edited, frozen, or whether deletions remain unaccounted
  for. A reducer writes this section whenever it has such a notice, including in
  a session that has no authorized configuration and therefore nothing else to
  project, because section 2.2 requires that a mutation not be lost silently.

When a reduction fails closed at a point where it cannot write its notice into
the marker region, because that region is precisely what it cannot parse, the
diagnosis would otherwise exist only in the adapter's logs. The reducer MUST
then apply the label `open-table/reduction-failed` to the issue, and MUST remove
it as soon as a reduction no longer leaves its diagnosis invisible. The label
carries no protocol state and is not detection memory: it is the visible half of
a failure, and section 9.3's rule that a reducer MUST NOT remove unrelated
labels applies to it unchanged.

This projection is a cache under section 2.6 and is not the reducer's memory of
what it incorporated. Its permalink citations are written for people, and
section 2.3 excludes them from the detection role: a reducer MUST NOT read this
region as its record of incorporated material. That record is the `manifest`
family of section 4.18, and the projection is written after it.

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
