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
must attach to several hubs.

"Contributor" here is the **administrative trust boundary that owns the credentials and the
configuration**, not necessarily one human. A single developer and an entire company with shared
credentials are both contributors under that definition, which is why the cardinality is one agent
per boundary rather than one per person. Stating it that way is what makes the count meaningful: it
is not a headcount, it is a count of who administers the deployment.

The deployment is not per project. **Each attachment to a hub may be**, and that is a different
statement. The agent's model credentials and its configuration belong to the contributor, but a
GitHub identity acting on a project is governed by that project: the worker identity uses a
fine-grained token scoped to target repositories, and the accepted decision on role-separated
identities makes concrete account names per-instance. So an agent attached to several hubs carries
per-attachment state for identity selection, authorisation, revocation and isolation, whatever
mechanism ends up providing it.

The false conclusion was a chain broken only at its last step: credentials are personal, so an
instance is per contributor; a contributor works on several projects, so that instance attaches to
several hubs; and because the agent was also the hub, the hub had to serve several repositories.
Breaking the third premise leaves multi-hub as a property of the agent and the hub as one per
repository.

**The hub is per repository because the deployment boundary already is the repository**, and
because a project must have exactly one ownership authority. What each part of that rests on is
stated separately, because the two are not equally strong:

- section 1.6 of `docs/specs/open-table-v0.md` requires that a project have **one** ownership
  store, since under `steve/kanban` a claim may request the Kanban lease and Open Table must not
  create a second one. That fixes the store, not the number of hubs: two hubs sharing one store
  could still award exclusively, so the clause does not by itself establish this cardinality;
- what does hold today is measured and is a property of the deployment rather than of the
  protocol: the deterministic merge gate accepts one repository per invocation and one configured
  reviewer identity, the `pr-watch` and `merge-gate-scan` schedules each watch one repository, and
  GitHub Actions are repository-scoped.

One hub per project is therefore the arrangement that guarantees the single ownership authority
most simply, on a boundary the deployment already has. It is decided here as policy, and the
argument that it is structurally forced is **not** made, because the evidence does not support it.

**A candidate mapping the specification already suggests, and it is a candidate rather than a
finding.** Open Table section 1.3 requires that a person with a text editor be able to participate
while an authenticated reducer is required to rule, and section 1.7 defines participant and reducer
as two conformance tiers carrying very different burdens. That is the same asymmetry this record
draws, one authenticated deciding role against many unprivileged participating ones, which makes
the protocol a plausible home for the hub-agent boundary and is a use nobody had considered for it.

The mapping is not an identity, and the two places it fails are worth naming: section 1.5 lets any
account that may comment participate, so a participant can be a person with no agent at all; and
the hub does more than rule, since the gate, the schedules, the Actions and the project group are
outside anything the specification defines. Whether the boundary is actually carried by this
protocol is left to the open question below.

## Decision

**Steve is two roles, and everything written about Steve declares which of them it governs, `hub`,
`contributor-agent`, or `shared`.**

1. **One hub per project.** The hub is provided by the repository owner and is not multi-tenant.
   The earlier decision recorded on 2026-07-23 is preserved here in full, scoped to this role.
2. **One agent per contributor, attaching to many hubs**, where "contributor" is the
   administrative boundary that owns the credentials and configuration. **The deployment is not
   per project; each hub attachment may be.** The model credentials and the deployment belong to
   the contributor. Of the two GitHub identities the factory separates by role, the **worker**
   identity belongs to the contributor side, because it acts for whoever is doing the work and
   GitHub's own per-repository access already governs what it may do there; the **reviewer**
   identity belongs to the **hub**, because author-is-not-approver is a guarantee the project owes
   and the gate checks a reviewer identity configured on the hub. That division is decided here
   and is new; the mechanism by which an agent selects an identity per attachment is not.
3. **A single deployment may perform both roles**, which is what this repository does today while
   developing itself. This is permitted as a deployment arrangement and forbidden as a conceptual
   one. Concretely, and because an absolute version of this rule cannot classify a combined
   deployment:
   - the declared scopes are **`hub`**, **`contributor-agent`** and **`shared`**, and `shared` is a
     real answer rather than a failure to choose: a combined deployment has runtime state that
     genuinely belongs to both;
   - a declaration attaches to an **artifact, a section, or a configuration namespace**, not to
     every sentence. Requiring it per sentence is unsatisfiable and was the first form of this
     rule;
   - what is a defect is an artifact whose scope is **undeclared where the reader cannot infer
     it**, not prose that omits the word.

   This rule is not retroactively satisfied. The canonical architecture document still states one
   unqualified instance per project, and the blueprint configuration mixes model, chat, board and
   repository-gate concerns in one namespace. Both are named in the obligations below as a bounded
   audit rather than left to be discovered by the first reader who takes rule 3 literally.

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

**The bounded audit rule 3 owes, named so it is scheduled rather than discovered.** Landing this
record makes existing canonical material non-compliant on the day it merges, and the material is
enumerable rather than open-ended:

- `docs/ARCHITECTURE.md`, which states one unqualified instance per project in its overview and
  again in its fixed decisions, and describes the two GitHub identities without saying which side
  owns them;
- the accepted decision records that speak of "the instance" without qualifying it, of which the
  superseded one is only the clearest case;
- `instance/config.yaml` and its profiles, where model, chat, board and repository-gate settings
  share one namespace, so no namespace can carry a scope until they are separated.

The audit assigns a scope to each of these and changes nothing else. It is bounded by that list,
and the blueprint separation it may reveal is the open question already recorded below, not part of
the audit itself.

## Alternatives considered

**Making the hub multi-repository.** Rejected, and on the ground the evidence supports rather than
on a stronger one. It is the conclusion the false premise produced, and nothing in it is needed
once the agent carries the multi-hub property. Against it: every deployment surface the hub owns
today is repository-scoped, and a hub spanning repositories would have to keep one ownership
authority per project without ever letting two of them award the same work. That is not shown to
be impossible; it is shown to be unnecessary, and this record declines to buy it.

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
