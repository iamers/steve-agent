---
status: accepted
date: 2026-08-02
---

# The runtime pin follows official releases

## Context

The instance pins the agent runtime to a released tag. A feature we wanted,
per-card model and provider selection, exists only on the upstream default
branch and in no release. At the time of this decision, that branch was several
hundred commits ahead of the newest tag, with no release notes and no version
boundary.

A second, unrelated need briefly pointed at the same branch and then dissolved
when a contributor decoupled protocol conformance from any exact runtime
commit.

## Decision

The pin is evaluated when an official release appears, and never by chasing an
unreleased branch. A feature that exists only on the default branch is waited
for. Moving the pin outside that cadence requires a declared emergency, not a
desirable feature.

## Consequences

Capability gaps are accepted for the length of a release cycle, and designs
must not assume an unreleased feature. Every "should we update" question becomes
a check of whether a newer release exists, not a diff against the default
branch.

The adapter compatibility matrix inherits this cadence, one row per release, as
recorded in
`adr-20260802-open-table-conformance-and-reducer.md`.

## Alternatives considered

Pinning to the default branch to get the feature immediately: rejected because
the factory runs on this runtime, and a few hundred unreleased commits without
release notes is an unbounded change to a production dependency.

Vendoring or patching the runtime: rejected because this project deliberately
does not fork it.
