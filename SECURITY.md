# Security Policy

Steve Agent coordinates automated pull requests and self-hosted infrastructure, and
manages bot credentials (fine-grained PATs, and a future GitHub App). We take reports of
security issues seriously and appreciate responsible disclosure.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's [private vulnerability reporting](https://github.com/iamers/steve-agent/security/advisories/new)
(the repository's **Security → Report a vulnerability**). Include:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- affected files, configuration, or versions.

This is a community-maintained, source-available project: we respond on a best-effort
basis and will keep you updated on triage and any fix.

## Scope

In scope: this repository — the instance blueprint (`instance/`), the coordination
governance (`.steve/`), the review/e2e tooling (`tools/`), the privacy guard
(`scripts/`), and CI (`.github/`).

Out of scope: the underlying runtime, [Hermes Agent](https://github.com/nousresearch/hermes-agent),
which has its own project and security process — report runtime issues there. Findings
that require an operator to first misconfigure their own deployment (for example,
committing real secrets, or weakening the documented allowlist posture) are configuration
guidance, not vulnerabilities in this project.

## Handling of secrets and identifiers

By design, no secrets and no deployment-specific identifiers (tokens, chat/user ids, host
names) belong in version control. A local denylist plus a pre-commit hook and CI secret
scanning guard against leaks. If you find such a value committed anywhere in this
repository or its history, please report it privately as above.

## Supported versions

Active development happens on `main`. Fixes land on `main`; there is no separate
long-term-support branch. Under the Business Source License (BUSL) 1.1, each release
converts to Apache 2.0 four years after publication.
