---
status: accepted
date: 2026-08-23
---

# Deployments pin official releases by commit

## Context

Steve Agent has no release identity. At `426008e`, the repository had no Git
tags, no GitHub Releases, and no changelog. Two deployments can therefore run
different snapshots of `main` without a human-readable way to distinguish
them.

The mirror policy already exists for the runtime this project consumes:
[`adr-20260802-runtime-pin-follows-official-releases.md`](adr-20260802-runtime-pin-follows-official-releases.md)
waits for an official release rather than chasing an upstream default branch.
The installation guide also establishes a separate machine constraint: a tag
does not compose safely with its existing fast-forward installation behavior,
while a full commit hash does.

The accepted hub/contributor split remains intentionally incomplete. Its
bounded concern-separation audit has not happened, and issue
[#163](https://github.com/iamers/steve-agent/issues/163) has not chosen the
versioned home or alignment mechanism for deployment-owned configuration.
Waiting for either would leave a second deployment without a release boundary,
but publishing the current layout as stable would make a promise the project
already knows it cannot keep.

## Decision

### Release identity and numbering

An official Steve Agent release is a published, non-draft, non-prerelease
GitHub Release whose tag has the exact form `v0.x.y`. The corresponding version
follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) as
`0.x.y`; the leading `v` belongs only to the Git tag and release name. The
release commit is reachable from `main`. There are no moving aliases such as
`v0` or `v0.x`. Major zero carries the pre-stable signal; GitHub's prerelease
flag is reserved for candidates that are not official releases.

The `0` major version declares the product pre-stable. During `v0`, the public
compatibility surface is the documented configuration, scripts, operator
workflow, and installation layout. A minor release may change that surface and
may require operator action; a patch release is reserved for compatible fixes
that require no migration. The changelog must call out every exception before
publication. In particular, the hub/contributor layout remains provisional
throughout `v0` and a minor release may reorganize it.

Published releases are immutable. A release tag is never moved, reused, or
deleted to replace its contents; a correction receives a new version. GitHub
[release immutability](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
must be enabled before the first release so this rule is enforced by the
hosting platform for future releases, not only by convention.

### Human selection and machine pin

A human selects a named official release after reading its deployment and
operator impact. The deployment records both that release name and the full
40-character commit SHA to which its tag resolves. The name is the
human-readable identity; the full SHA is the authoritative machine pin. A
deployment must refuse the selection if the two do not resolve to the same
commit.

Issue [#163](https://github.com/iamers/steve-agent/issues/163) decides where that
deployment-owned record lives and how it stays aligned with this repository. It
may not replace the full SHA with a tag or a branch.

The development instance that dogfoods this repository is the sole exception:
it may continue to track `main` so merged changes become live on the cadence the
factory already verifies. It is then running an unreleased development snapshot
and reports its full commit SHA, not an official release version. Every other
deployment selects an official release.

### Cadence and changelog

Releases are readiness-driven, not scheduled and not cut for every merge. A
maintainer publishes one when `main` contains a coherent deployment candidate,
the release gate below is green, and a non-dogfooding rollout needs a new
version. Urgent fixes still receive a new release; they do not justify moving a
tag.

`CHANGELOG.md` is the human source for release impact. Every pull request that
changes installation, configuration, runtime behavior, operator work, security
posture, or compatibility updates its `Unreleased` section. At release time,
the release owner moves those entries under the version and date, preserves an
explicit `Deployment and operator impact` section even when its value is
`None`, records the release's full commit SHA, and uses that section as the
basis of the GitHub Release notes.

### Rollback

Rollback means selecting an earlier official release, changing the deployment's
authoritative pin to that release's full SHA, and redeploying that exact commit.
It never means moving a release tag backward. A code rollback does not itself
reverse configuration, credentials, persisted state, or external side effects.
Each release's deployment-impact notes must say when downgrade requires a
backup, manual state repair, or is unsupported.

### First-release gate

This decision does not publish `v0.1.0`. Before the first release:

1. issue [#187](https://github.com/iamers/steve-agent/issues/187) is resolved so
   every documented scheduled job has an owned, reproducible wrapper rather
   than inheriting clone freshness from another job;
2. issue [#189](https://github.com/iamers/steve-agent/issues/189) is resolved so
   a pinned deployment has guarded scheduled-run semantics instead of a wrapper
   that only accepts `main` and `origin/main`;
3. GitHub release immutability is enabled;
4. the candidate is on `main`, its required `checks` result is green, and the
   release changelog, installation procedure, links, formatting, and privacy
   checks pass on that exact commit.

The concern-separation audit and issue #163 are not first-release prerequisites.
Their uncertainty is carried honestly by the `v0` compatibility policy. Issue
#163 chooses companion alignment after this release identity and #189's pinned
execution behavior are known.

## Consequences

`main` remains the integration and dogfooding line, not a release channel for
ordinary deployments. There is no LTS branch during `v0`; support targets the
latest official release, and fixes become available to pinned deployments only
when a new release is published.

The first release is deliberately blocked on two small operational gaps rather
than on the larger provisional layout. This prevents publishing a version whose
documented scheduled jobs either run stale code or refuse to run, while avoiding
an indefinite dependency on the hub/contributor separation work.

The initial release process is manual. Automation may later enforce changelog,
tag, and release-note consistency, but adding such automation is not required to
establish the identity and pinning contract.

This decision does not interpret or change the Business Source License. The
publication and version terms in `LICENSE` remain authoritative.

## Alternatives considered

**Documenting commit hashes without releases.** Rejected because a hash is an
adequate machine pin but not a human-readable version or an operator-impact
record.

**Using the tag itself as the deployment pin.** Rejected because the existing
installation path already demonstrates that tags and fast-forward updates do
not compose safely, and because a full SHA makes the machine boundary explicit
even when tag protection is misconfigured.

**Publishing a moving `v0` tag.** Rejected because it would give different code
the same identity and defeat rollback and auditability.

**Waiting for the hub/contributor layout to stabilize.** Rejected because `v0`
exists to carry that instability, while the second deployment needs a release
boundary now. The provisional layout is disclosed instead of treated as
stable.

**Releasing on a fixed calendar or after every merge.** Rejected because neither
is evidence that a coherent, operable deployment candidate exists.
