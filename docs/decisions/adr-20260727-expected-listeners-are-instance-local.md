---
status: accepted
date: 2026-07-27
---

# Expected listeners are instance-local

## Context

The listener smoke check fails when the instance user owns a non-loopback
listener. This fail-closed default is correct for new installations, but an
operator can deliberately expose an optional authenticated service such as the
Hermes dashboard. A permanently failing check would stop distinguishing that
known exposure from a new, unintended listener.

The endpoint belongs to one deployment. Recording it in the blueprint would
make that deployment's network choice a default for every adopter and could
publish an instance-specific identifier.

## Decision

Expected non-loopback listeners are recorded only on the live instance in
`~/.hermes/private/allowed-listeners.txt`. Each active line is one exact local
endpoint in the form printed by the local-address field of `ss`; blank lines and
`#` comments are ignored. The smoke check reads the file over its existing SSH
path and permits only literal, exact matches.

The administrative environment may select another remote path with
`STEVE_ALLOWED_LISTENERS_FILE`. An absent file means that no non-loopback
listener is expected. A file that exists but cannot be read makes the inspection
untrustworthy and fails closed.

## Consequences

Fresh installations retain the strict default without carrying another
instance's network choices. An operator who intentionally exposes the dashboard
must create and maintain the private file on that instance. If its address or
port changes, the check fails until a person reviews the change and updates the
exact endpoint.

The blueprint, pull requests, and reviews contain neither the live endpoint nor
any deployment-specific host information. The allowlist is operational state
and is not drifted into canonical configuration.

## Alternatives considered

Adding the dashboard endpoint to the blueprint: rejected because it would turn
one installation's preference into a shared default and could disclose local
network details. Matching only the port or an address prefix: rejected because
it would also permit endpoints that were never reviewed. Ignoring all listeners
owned by the instance user: rejected because it would remove the protection the
check provides. Treating an unreadable file as empty: rejected because the
inspection could report a misleading result when its declared policy was not
available.
