# docs/

Public architecture documentation for Steve Agent.

- [`ARCHITECTURE.md`](ARCHITECTURE.md) - the system architecture (arc42-light): goals,
  constraints, context, building-block/runtime/deployment views, cross-cutting concepts,
  decisions (ADR-light), and risks.

The document describes the system as it is today (a working factory) and cites the
repository's versioned artifacts (`instance/`, `.steve/`, `tools/`, `.github/`) and the pull
request history as evidence. Identifiers specific to a deployment (chat id, user id, host)
do not appear here: they live only in an instance's server-side `.env`.
