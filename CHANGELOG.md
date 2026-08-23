# Changelog

This file records human-readable changes to Steve Agent releases. No official
release has been published yet.

## Unreleased

### Deployment and operator impact

- No deployment action is required. This change defines the release policy but
  does not publish a release, move a tag, or change a running instance.
- The first official release remains blocked on issues
  [#187](https://github.com/iamers/steve-agent/issues/187) and
  [#189](https://github.com/iamers/steve-agent/issues/189), current green
  verification, and GitHub release immutability.

### Added

- The accepted `v0.x.y` release identity, full-commit deployment pin, dogfooding
  exception, rollback meaning, and first-release gate.

## Release entry requirements

At release time, move the entries into a heading of the form
`## [v0.x.y] - YYYY-MM-DD`, record the full 40-character release commit SHA,
and leave a fresh `Unreleased` section above it. Every release keeps a
`Deployment and operator impact` section; write `None` when no action,
migration, or downgrade constraint exists.
