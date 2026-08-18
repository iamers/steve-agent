---
status: accepted
date: 2026-08-18
amends: adr-20260816-detection-is-a-manifest-and-a-conditional-timeline-read.md
---

# A bounded detection window is a claim an adapter makes with its conditions, not a promise the base contract makes for it

## Context

Section 2.3 stated the second adapter obligation as:

> **The adapter MUST read the timeline periodically**, independently of incoming
> comment events, so that detection latency is bounded by a clock rather than by
> the next incorporated message.

The requirement is an act; the `so that` clause promised a **bound**. Those two
halves could be read as one rule or as a rule plus an explanation, and nothing
had to choose while no deployment existed to be measured against either reading.

The wording arrived in `0e38ad2` on 2026-08-16. [#176](https://github.com/iamers/steve-agent/pull/176)
deployed the periodic read on 2026-08-18 and the question became live in the
same hour: [#177](https://github.com/iamers/steve-agent/pull/177) declined to
answer it in the paragraph that first ran into it, and recorded it as
[#178](https://github.com/iamers/steve-agent/issues/178).

### What the deployment measured

The deployed sweep runs on a hosted scheduler that queues on a best-effort
basis. Six scheduled runs on 2026-08-18, against a cron of minute 17 and a
nominal hourly period:

| run created | minute | gap from previous |
|---|---|---|
| 03:07:37Z | 07 | — |
| 03:55:42Z | 55 | 48 min |
| 04:49:44Z | 49 | 54 min |
| 05:43:44Z | 43 | 54 min |
| 07:01:46Z | 01 | 78 min |
| 07:51:30Z | 51 | 50 min |

**The declared minute was not honoured once**, and the interval ranged from 48
to 78 minutes around a nominal 60. The same platform suspends scheduled
workflows in repositories inactive for 60 days. So this adapter does not control
its clock, in a way that is measured rather than suspected.

### The argument this record does not make, and why

An earlier draft argued that **no** adapter can deliver the bound, because
punctuality belongs to whatever clock it runs on and the protocol cannot reach
it. Review found the hole, and it is worth keeping: the same draft told an
adopter who needs a bound to use *an adapter whose clock it controls*. If such an
adapter exists — a daemon, a self-hosted runner, a scheduler with a documented
delivery guarantee — then the bound is deliverable by someone, the claim of
platform-independence was false, and the draft was a hosted deployment excusing
itself in the base contract.

What is actually true is narrower. **Whether the bound holds is a property of
the adapter's clock, which varies by deployment, so the base contract cannot
assume it of every adapter.** That is a reason to stop deriving the bound from
the act, not a reason to declare it undeliverable.

## Decision

**The obligation is the act; a bounded window is an additional claim, available
to any adapter that can support it and conditioned on saying what supports it.**

1. **The MUST is unchanged**: read the timeline periodically, independently of
   incoming comment events. Its rationale is restated as a purpose, *so that
   detection stops depending on the next incorporated message arriving*, which
   is what a periodic read delivers on any clock.
2. **Every adapter MUST state the period it runs on.** A backstop whose period is
   unstated is a backstop whose value is unstated, and a reader can only weigh
   what a deployment tells them.
3. **An adapter MAY claim a bounded detection window, and one that does MUST
   state the bound and the failure model under which it holds** — what the bound
   rests on, and what suspends or exceeds it. The claim is conforming when it
   carries those conditions and not otherwise.
4. **An adapter that does not control its clock MUST NOT present its period as a
   bound.** It still owes point 2.

An adopter who needs a bounded window therefore has a conforming path, which the
previous wording obscured by promising the bound on everyone's behalf and
delivering it for no one.

## What this amends in the prior record

`adr-20260816-detection-is-a-manifest-and-a-conditional-timeline-read.md` remains
accepted: it selects the detection mechanism, and nothing here touches the
manifest, the barrier, the three triggers or the serialisation prerequisite. Two
of its clauses are reversed and are marked in that record:

- decision 4 point 3, *"A sweep bounds detection latency by a clock instead of by
  the next incorporated message"* — a sweep bounds it only where the clock is
  controlled, which that record did not distinguish;
- its open-questions answer on the sweep interval, which asked the implementation
  to state *"the latency it therefore promises"* — an implementation states the
  period it runs on, and promises a latency only under point 3 above.

Both were written before any deployment existed, which is why neither had to
separate the period from the promise.

## Consequences

- **The obligation is satisfiable, and this deployment satisfies it.** It reads
  periodically and states its period; it makes no bounded-window claim, because
  it cannot support one.
- **This deployment's declaration had to change with the contract, and did.**
  `.github/workflows/open-table-sweep.yml` described its interval as *the latency
  it promises*; under point 4 that is exactly what a deployment on a clock it
  does not control must not say. The measured spread above is now stated there
  instead.
- **The specification promises less and offers more.** It stops asserting a bound
  on every adapter's behalf, and it gives an adapter that can provide one a
  defined way to say so.
- **Nothing changes about detection.** The three triggers, the barrier, the
  manifest and the serialisation prerequisite are untouched. This record changes
  what the specification claims about latency, not what any code does.
- **Reducer conformance is unaffected.** Section 1.7 makes it the conjunction of
  every reducer requirement; this narrows one of them and adds a conditional
  claim, rather than removing a requirement.
- **Nothing in continuous integration checks points 2 to 4.** They are duties on
  prose, checkable by a reader and by review, and the contradiction that review
  found in this repository's own workflow header is the evidence that they can be
  violated silently. Stated here rather than left to be discovered.

## Alternatives considered

**Keep the bound in the base contract and declare a best-effort scheduler
non-satisfying.** States a stricter truth, buys no detection, and permanently
routes every hosted-runner adopter into the declared-gap path of section 1.7.
Rejected because the strictness costs every such deployment and catches nothing
that the period statement does not already expose. Note that this record does
not need that alternative to be wrong in order to stand: point 3 gives the
strict adopter the same guarantee, stated by whoever can actually keep it.

**Remove the bound from the contract with no replacement**, which is what the
first draft of this record did. Rejected in review: it generalised a hosted
deployment's limitation into a claim about every adapter, and it left an adopter
who needs a bound with nothing conforming to point at.

**A MUST for the periodic read and a SHOULD for a bounded period.** The SHOULD is
decoration: nothing measures it and no deployment can be held to it. Point 3
captures what it was reaching for in a form a reader can check, because a claim
that must carry its failure model can be read and disputed.

## What this record does not decide

Whether an authority profile should *require* a bounded window, and what it would
demand of an adapter's clock. Point 3 makes the claim possible and conditioned;
requiring it is a profile question, and version 0 defines no such profile.
