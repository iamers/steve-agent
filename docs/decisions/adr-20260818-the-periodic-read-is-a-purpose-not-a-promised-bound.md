---
status: accepted
date: 2026-08-18
---

# The periodic read's rationale states a purpose, not a bound the protocol can enforce

## Context

Section 2.3 states the second adapter obligation as:

> **The adapter MUST read the timeline periodically**, independently of incoming
> comment events, so that detection latency is bounded by a clock rather than by
> the next incorporated message.

The requirement is an action. The `so that` clause is its rationale, and the
rationale promises a **bound**. Those two halves can be read as one requirement
or as a requirement plus an explanation, and the difference was invisible for as
long as no deployment existed to be measured against either reading.

The wording arrived in `0e38ad2` on 2026-08-16, before any deployment. #176
deployed the periodic read on 2026-08-18, and the question became live in the
same hour.

### What the deployment measured

The sweep runs on a hosted scheduler that queues on a best-effort basis. The
workflow reached the default branch at `2026-08-18T01:25:47Z` and the first
scheduled execution was created at `03:07:37Z`: **one hour, forty-one minutes
and fifty-one seconds**, against a nominal hourly period. The same platform
suspends scheduled workflows in repositories inactive for 60 days.

So the deployment performs the periodic read and does not realise a bound, and
the two readings of the clause give opposite answers to whether it satisfies the
obligation. #177 declined to answer in the paragraph that first ran into the
question, and recorded it as issue 178 instead.

### Why this is not a deployment defect

No adapter can promise the bound by being written better. Punctuality is a
property of whatever clock the adapter runs on, and the protocol has no reach
into it: it can require an act and observe a record, and it cannot require a
scheduler to be on time. A requirement whose satisfaction is decided entirely
outside the protocol's reach is not a requirement the protocol can hold anyone
to. That is the whole of the argument, and it does not depend on which
platform this repository happens to use.

## Decision

**The rationale of the periodic-read obligation states a purpose rather than a
guarantee, and section 2.3 is reworded to say so.** The clause becomes:

> so that detection stops depending on the next incorporated message arriving

The MUST is unchanged: read the timeline periodically, independently of incoming
comment events. What changes is that the specification stops promising an upper
bound on detection latency, which it never had a mechanism to enforce.

**A deployment MUST state the period it runs on**, because a backstop whose
period is unstated is a backstop whose value is unstated, and readers can only
weigh what a deployment tells them. It MUST NOT present that period as an upper
bound unless it controls the clock that produces it.

**An adopter who needs a bounded window needs an adapter whose clock it
controls.** Section 2.3 says this rather than leaving it to be discovered, and it
is the honest form of what the previous wording implied it was already
delivering.

## Consequences

- **Section 2.3's second adapter obligation is satisfiable, and this deployment
  satisfies it.** The question #177 left open is closed by narrowing the claim
  rather than by asserting the deployment achieved something it did not, and
  section 2.3 stops carrying a deliberate non-answer.
- **The specification promises less than it did, and the difference was never
  real.** No conforming deployment ever had the bound; the previous wording
  described an intention as though it were a guarantee.
- **The measured figure stays in section 2.3.** A reader deciding whether this
  deployment is good enough needs the observation, not only the rule, and the
  one observation available is a delay of over an hour and forty minutes on a
  nominal hourly period.
- **Nothing changes about detection itself.** The three triggers, the barrier,
  the manifest and the serialisation prerequisite are untouched. This record
  changes what the specification claims about latency, not what any code does.
- **Reducer conformance is unaffected.** Section 1.7 makes it the conjunction of
  every reducer requirement, and this record removes an unenforceable promise
  from one of them rather than removing the requirement.

## Alternatives considered

**Keep the bound as normative and declare a best-effort scheduler
non-satisfying.** This states the stricter truth, and it converts a working
deployment into a declared non-conformance without changing anything it does.
It also puts the specification in the position of requiring something no adopter
on a hosted runner can provide, which pushes every such adopter into the
declared-gap path of section 1.7 permanently. Rejected because the strictness
buys no detection and costs every hosted deployment.

**Split the obligation into a MUST for the periodic read and a SHOULD for a
bounded period.** More faithful to the intent, and the SHOULD is decoration:
nothing measures it, no deployment can be held to it, and a recommendation that
cannot fail is a sentence rather than a rule. Rejected for that reason, and the
"state your period" duty above captures what the SHOULD was reaching for in a
form a reader can check.

**Leave the ambiguity and let each adopter read the clause as it prefers.**
Rejected: the ambiguity already produced a specification that contradicted
itself across two paragraphs and a public summary that contradicted the
specification, and it did so within hours of the first deployment.

## What this record does not decide

Whether an authority profile that requires a bounded detection window should
exist, and what it would demand of an adapter's clock. That is a profile
question and version 0 defines no such profile.
