# Vision

This document is the place a reader unfamiliar with Steve Agent goes to understand what
problem it addresses, what the product actually is, what it deliberately stays out of, and
what has already been settled rather than left for later. The day-to-day pitch lives in
[`README.md`](../README.md), the mechanism in [`ARCHITECTURE.md`](ARCHITECTURE.md), and the
shared vocabulary in [`GLOSSARY.md`](GLOSSARY.md); this document does not repeat them, it
gives the reasoning that sits above them.

## The problem

A team that wants a chat-driven, AI-assisted development workflow today has to wire it
together itself: a chat tool, a task tracker, a coding agent, and a review process, with the
coordination between those pieces held together by whoever is running it, not by the tools
themselves. Steve Agent addresses that coordination gap. It turns a request raised where a
team already talks into a unit of trackable work, has an AI worker execute it in isolation,
has a separate AI reviewer check the result against the same evidence a human reviewer would
demand, and stops short of merging anything without a human's authorization on record.

## What Steve Agent is

A working factory: requests raised in a chat land, through a governed pipeline, as reviewed
pull requests. This repository is built by its own instance of that pipeline, so most of its
history is evidence of the cycle rather than a claim about it: of the first 146 pull requests
merged to it, 119 were opened by the worker identity. The boundary is a count rather than a date
because the number keeps moving: anchored this way the sentence stays true however much history
is added after it. The rest were opened directly by a person or a
session, which the project also permits and does not pretend otherwise.

The pipeline, at the level a reader needs before going to `ARCHITECTURE.md` for the mechanism:
a request becomes a brief with an explicit, executable definition of done; the brief becomes a
card on a work queue; a worker agent executes it in an isolated worktree, on its own branch,
and opens a pull request; a separate reviewer agent re-runs the brief's verification commands
rather than trusting the worker's word; and a human authorizes every merge, whether that
authorization is recorded before a deterministic gate executes a low-risk merge, or given
directly on the platform for anything riskier.

## Two roles, one name used to cover both

Until a recent decision, a single name, "steve-agent", stood for two different things, and
treating them as one produced a real cost: a chain of reasoning that looked sound broke at its
last link and stalled a design question for a day. The chain ran: model credentials are
personal, so an installation is personal to whoever holds them; a person contributes to more
than one project, so that installation has to reach more than one project; and because the
same name also stood for the per-project coordination point, that coordination point was
assumed to need the same reach. The first two steps hold. The third does not, once the two
things the name covered are told apart.

Steve Agent is two roles. Everything written about it, from here on, declares the scope it
governs — `hub`, `contributor-agent`, or `shared` — wherever a reader could not otherwise infer it.

## The hub: the coordination point of one project

The hub is the coordination point of one project. Whoever owns the project's repository
provides it and makes it reachable by every contributor: it answers about state, assigns work,
and holds the platform integrations. What is hub-scoped today: the deterministic merge gate,
the schedules that watch for pull requests it has not seen and for pull requests carrying the
approval label, the identity that executes low-risk merges, and the project's chat group with its
per-topic configuration.

One hub per project is a decision, not a proof. What actually holds today, measured rather than
assumed, is that every one of those pieces is already scoped to a single repository: the merge
gate takes one repository per run, each schedule watches one repository, and the platform's own
automation is repository-scoped. The reviewer identity the gate checks is configured per hub where
it is set at all; where it is not, the gate accepts an approval from anyone who did not author the
change, which is a weaker guarantee and worth stating rather than rounding up. One hub per project is
the arrangement that gives a project a single assignment authority most simply, on a boundary
the deployment already has, and it is adopted as policy on that evidence, not because a hub
spanning several projects has been shown to be impossible. It has only been shown to be
unnecessary, once the other role below carries the need to reach several projects instead.

## The contributor agent: one per contributor, reaching many hubs

The contributor agent is the instance a contributor installs. It holds that contributor's own
model credentials and configuration. "Contributor" here is an administrative boundary, the
party that owns those credentials and that configuration, not necessarily one person: a single
developer and an entire organization sharing credentials are both contributors under that
definition, and what is being counted is who administers a deployment, not a headcount of
people.

Because credentials belong to that boundary, and because a contributor is not expected to work
on only one project, one contributor agent can attach to more than one hub, rather than being
confined to a single project. The alternative, one agent per contributor per project, was rejected: it
multiplies installations along two dimensions and forces a contributor to run one installation
per project they touch.

Of the two GitHub identities the factory already keeps separate by role, the worker belongs to
the contributor agent: it acts for whoever is doing the work, and the platform's own
per-repository access already governs what it may do on a given project. The reviewer belongs
to the hub: the guarantee that whoever approves a change is not the party that authored it is
something a project owes its own work, and the gate checks a reviewer identity where the hub
configures one. Where it does not, the gate falls back to accepting an approval from anyone who did
not author the change, and the guarantee is correspondingly weaker. What is agent-scoped today: model credentials. Reaching several hubs from one agent still needs
per-attachment state, and that mechanism is not settled yet.

## One deployment can hold both roles, as an arrangement, not as a merged concept

This repository's own instance holds both roles today, developing itself. That is permitted as
a deployment arrangement and forbidden as a conceptual one: anything written about Steve, a
document, a section, a configuration namespace, declares one of three scopes: `hub`,
`contributor-agent`, or `shared`. `shared` is a first-class answer for state that genuinely belongs
to both roles, not a way of avoiding the question, and leaving the scope undeclared where a reader
cannot infer it is a defect rather than a stylistic choice. What this
replaces is exactly the failure described above: presenting the two as one thing is what
stalled a design decision for a day, and the discipline exists so that does not happen again.

## What carries over from the earlier decision, and what does not

Steve Agent had earlier decided that one instance serves one project, not a multi-tenant one.
That decision was right about the hub, which remains bound to one project, and **silent** about the
contributor agent rather than wrong about it: it did not say which of the two it governed, which is
the whole reason this split was needed. Nobody recorded, at the time,
what "not multi-tenant" was decided against, so this narrows the earlier decision rather than
reversing it: the reason behind the original boundary might still apply to something this split
has not yet touched, and that gap is stated rather than assumed away.

## Where this shows up beyond naming

Steve Agent already runs a separate, GitHub-based protocol for questions that need to be argued
out rather than decided unilaterally
([`docs/specs/open-table-v0.md`](specs/open-table-v0.md)). That protocol independently
distinguishes a participant, anyone able to comment, from a reducer, an authenticated party
required to rule. That is the same asymmetry as the hub and the agent: many unprivileged
participants, one authenticated deciding role. It is a plausible place for the hub/agent
boundary to live when separate instances need to talk to each other, and it is recorded as a
candidate, not a finding: a participant can take part with no agent at all, and a hub does more
than rule, since the gate, the schedules, and the platform integrations it holds are outside
anything that protocol defines. Whether instances actually end up talking to each other over
this protocol, or over a channel built for the purpose, is not decided.

## What Steve Agent deliberately does not do

- It never modifies its own live runtime. The factory develops the repository under it, never
  its own configuration or installation; changes to a running instance happen only from the
  outside and are traced.
- Nothing is merged without a human's authorization on record, and no worker or reviewer
  merges its own work. A worker and a reviewer stop once a pull request is opened and reviewed.
  A low-risk change is merged by deterministic code under a dedicated identity, and only once
  that authorization exists; anything riskier is merged by whoever holds it, or by an operator
  acting on an authorization they were explicitly given. The invariant is the recorded
  authorization, not which party performs the gesture -- stating it the other way would be a
  promise this project has already broken in its own history.
- A hub is not a shared runtime across projects. It is one project's own coordination point,
  not a service other projects reach into; reaching across projects is what the contributor
  agent is for, deliberately, and the hub deliberately is not built to do it.
- Whatever product is under development does not share Steve's own coordination channel: it can
  run its own presence in its own rooms, so a team can exercise the real thing without mixing
  it into the coordination flow.

## Decided, and left open

Decided:

- The two roles exist, are named `hub` and `contributor agent`, and everything written about
  Steve declares its scope: `hub`, `contributor-agent`, or `shared`.
- One hub per project; a hub is not multi-tenant.
- One contributor agent per credential-owning administrative boundary, able to attach to more
  than one hub.
- The worker identity is scoped to the contributor agent; the reviewer identity is scoped to
  the hub.
- A single deployment may hold both roles at once. Doing so is a deployment choice; it is never
  license to treat the two concepts as one.

Left open:

- Whether `hub` and `contributor agent` are the names that stick. The repository itself is
  named `steve-agent`, so "agent" is already claimed by one of the two roles, and that
  collision is unresolved.
- Which existing canonical material still has to be re-scoped. The decision record settles that a
  bounded audit of it is owed and lists what falls in scope; carrying that out is work this
  document does not do and does not get to forget.
- How a contributor agent reaches several hubs in practice: over the same deliberation
  protocol Steve already uses for other cross-party questions, or over a channel built for
  this specifically.
- How the parts that today serve both roles come apart. Assignment belongs to the hub while a
  contributor also has private work of their own to queue, and separating the two is named as the
  hardest remaining piece rather than a solved one.

The vocabulary introduced here, `hub` and `contributor agent`, is not yet in
[`GLOSSARY.md`](GLOSSARY.md), which is where this project defines each of its terms exactly
once. Adding them there is work this document does not do.

Full detail on the decision this document distills lives in
[the accepted decision record](decisions/adr-20260812-hub-is-per-project-and-agent-is-per-contributor.md).
