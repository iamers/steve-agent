---
status: accepted
date: 2026-07-27
---

# Instance-local preferences are not blueprint defaults

## Context

A confirmation prompt in chat offered an "always" option. Choosing it caused the
gateway to persist a setting in the live configuration. The canonical
configuration under `instance/` is not a snapshot of this deployment: it is the
blueprint used to build a future instance.

The distinction had not mattered before because operators deliberately applied
each configuration change to both places. A control that a person can change
from a chat message has a different source of change, and the drift check had no
category for it.

## Decision

A preference that belongs to one deployment rather than to the product stays out
of the canonical configuration. The drift check knows each such key, verifies
its shape, and reports drift if the key ever appears in the canonical
configuration.

## Consequences

The blueprint retains the safe default for future adopters. The drift check no
longer reports a legitimate local choice as drift, without being taught to look
away. Each new key in this category must be added deliberately to a short,
reviewed list.

## Alternatives considered

Copying the key into the canonical configuration: rejected, because it would
decide for every future adopter based on one administrator's convenience.
Reverting the setting on the instance: rejected, because it would override a
deliberate choice and restore friction for commands used in testing. Ignoring the
key in the comparator: rejected, because a mute exception would hide both the
legitimate local difference and the opposite defect of committing a local
preference to the blueprint.
