---
status: accepted
date: 2026-08-12
supersedes: adr-20260723-one-instance-serves-one-project.md
---

# Steve is a project hub and a contributor agent, and only the hub is per project

## Context

One name covered two products, and the confusion produced a false conclusion that blocked a
design question for a day.

The **hub** is the coordination point of one repository. Whoever owns the repository provides it
and makes it reachable by every contributor. It answers about state, assigns work, and holds the
platform integrations.

The **contributor agent** is the instance a contributor installs. It holds that contributor's own
model credentials and configuration, and one person contributes to more than one project, so it
must attach to several hubs. A single developer or an entire company with shared credentials may
sit behind one agent; that is a choice of whoever installs it, not a property of the product.

The false conclusion was a chain broken only at its last step: credentials are personal, so an
instance is per contributor; a contributor works on several projects, so that instance attaches to
several hubs; and because the agent was also the hub, the hub had to serve several repositories.
Breaking the third premise leaves multi-hub as a property of the agent and the hub as one per
repository.

**The hub is per repository because that is where atomicity lives**, which is a structural reason
and not a convenience:

- assignment is the Kanban lease, and section 1.6 of `docs/specs/open-table-v0.md` requires that
  lease to remain the sole ownership authority; two hubs over one repository cannot assign
  exclusively;
- the deterministic merge gate is bound to one repository and to a configured reviewer identity;
- the `pr-watch` and `merge-gate-scan` schedules watch one repository;
- GitHub Actions belong to the repository.

**The split is already written in this repository's own specification, under other names.** Open
Table section 1.3 requires that a person with a text editor be able to participate while an
authenticated reducer is required to rule, and section 1.7 defines two conformance tiers,
participant and reducer, stating that the two roles carry very different burdens. Participant and
reducer are the agent and the hub. That protocol is therefore a candidate for the boundary between
them, which is a use nobody had considered for it.

## Decision

**Steve is two roles, and every decision about Steve declares which of the two it speaks about.**

1. **One hub per project.** The hub is provided by the repository owner and is not multi-tenant.
   The earlier decision recorded on 2026-07-23 is preserved here in full, scoped to this role.
2. **One agent per contributor, attaching to many hubs.** The agent holds its own credentials and
   configuration. Nothing about it is per project.
3. **A single deployment may perform both roles**, which is what this repository does today while
   developing itself. This is permitted as a deployment arrangement and forbidden as a conceptual
   one: documents, records and configuration state which role they govern, and a sentence that
   does not say is a defect to correct rather than a shorthand to interpret.

This record supersedes rather than amends because the register has no amending status. The
substance is a scoping: the superseded decision was right about the hub, silent about the agent,
and its unqualified form is what allowed the false conclusion.

## Consequences

Rule 3 is the one that costs something, and it is deliberate. This project has already paid four
review rounds for a promise that did not say which actor it held against, and the correction that
closed it was to say so. The same correction is applied here before the cost is paid twice.

What is hub-scoped in what exists today: the merge gate, the two schedules, the merge App, the
project Telegram group and its per-topic prompts. What is agent-scoped: model credentials. What is
not yet separated, and is the hardest part: the `instance/` blueprint with its drift check, and the
Kanban board, since assignment belongs to the hub while a contributor has private work to queue.
Those are named here as unseparated rather than left to be discovered.

The superseded decision recorded no context, no consequences and no alternatives, so **it is not
known what "not multi-tenancy" was decided against**. This record narrows rather than reverses it,
which limits but does not remove the risk that the original reason is being reintroduced. Stating
the ignorance is the only honest handling available.

Naming carries a cost that is recorded rather than solved: this repository is named `steve-agent`,
so using "agent" for the contributor half makes the repository share a name with one of the two
roles. The names used here are `hub` and `contributor agent`.

## Alternatives considered

**Making the hub multi-repository.** Rejected: it is the conclusion the false premise produced, and
it breaks atomic assignment, which no amount of engineering restores once two hubs can award the
same work.

**One agent per contributor per project.** Rejected: it multiplies instances along two dimensions
and forces a contributor to maintain one installation per project they touch.

**Leaving the 2026-07-23 decision unqualified and treating the split as understood.** Rejected.
The unqualified form is exactly what produced the impasse, and an understanding that lives in a
conversation does not reach the next session.

## Open questions

The role names are recorded as `hub` and `contributor agent` and may not survive contact with the
repository's own name.

Whether the agent speaks to hubs over Open Table or over a channel of its own is not decided here.
The specification was written for independent participants sharing only GitHub, which fits, but the
fit is to be verified against the real case rather than inherited from the shape.

How the board and the `instance/` blueprint separate between the two roles is not decided here.
