# Steve Agent

Run a software team from your chat. Steve Agent turns a messaging group into a
development pipeline: backlog, AI workers, adversarial review, and merges, all
driven from the conversation where your team already works. Vibecoding, for
teams.

## How it works

You message in the team group. Steve writes a brief, opens a kanban task, and a
worker agent picks it up in an isolated git worktree. The worker ships a pull
request. A separate reviewer agent re-runs the brief's verification commands and
reports. A human authorizes every merge: the deterministic GitHub App gate merges
eligible `safe` pull requests, while a human merges higher-risk tiers on GitHub.

Optionally, the product under development runs as a separate bot in dedicated
test topics, so the team can dogfood in the same group without polluting the
coordination flow.

## Built on top of Hermes

Steve Agent layers a coordination discipline on
[Hermes Agent](https://github.com/nousresearch/hermes-agent):

- **Role agents with separate GitHub identities.** A worker commits code, a
  reviewer audits it, and no agent ever merges. Each role is its own account.
- **The `.steve/` convention.** Review tiers, the brief template, and the PR
  lifecycle live in version control, so the coordination process is itself
  reviewed.
- **A deterministic brief compiler as the gate.** `tools/pr-brief.py` derives a
  review tier from the files a PR touches, not from an LLM's opinion.
- **CI plus a main-guard.** No bot pushes to main, and merges require an
  approved review from a different account.
- **A privacy guard on commits.** `scripts/check_privacy.sh` blocks commits that
  leak strings from a local denylist.
- **An instance blueprint as config-as-code.** Install, smoke test, drift-check,
  worker provisioning, and backup are all versioned under `instance/`.
- **An end-to-end injector with a real user account.** Spikes and tests post
  messages as a genuine human, exercising allowlists and mention gating exactly
  like a real member.
- **A SOUL persona per agent.** Each role carries its own disciplined identity,
  not a generic assistant prompt.

## Platform reach

Telegram first. Forum topics map cleanly to a backlog room, an admin room, and
per-feature rooms, which is why Steve Agent ships there today. The Hermes base
also speaks Discord, Slack, Teams, and Matrix, so coordination can follow your
team wherever it chats. WhatsApp support is on the roadmap, not shipping today.

## Proof

This repository is developed by its own factory. Tasks raised in chat land as
reviewed pull requests here, in the open.

## Open Table v0 contract

The accepted runtime-neutral protocol lives in
[`docs/specs/open-table-v0.md`](docs/specs/open-table-v0.md). Its reusable
standard-library core is `tools/open_table_core.py`; the compatible offline CLI
remains `tools/open-table-validate.py`. The CLI self-test runs the external,
versioned integrity, reason-code, comment, and bundle fixtures under
`docs/specs/open-table-v0/fixtures/`.

This contract validates envelopes and the closed integrity bundle, including
canonical body digests, immutable artefacts, duplicate/conflict behavior,
reducer-principal checks over caller-supplied trusted metadata, ruling bindings,
and stable diagnostics. Its supported Python API is the module's `__all__`
surface; fatal validation raises `ValidationError` with a structured diagnostic,
while the structured integrity entry point returns nonfatal diagnostics on
success. Human-readable detail text is not contractual.

The core does not authenticate or gather GitHub evidence, prove input
completeness, detect deletions that GitHub no longer exposes, perform contextual
reduction, write projections, mutate GitHub, or integrate a runtime, and it does
not claim reducer conformance.

The separate interim `deliberation-only` reducer is
`tools/open-table-reduce.py`, with its GitHub Action in
`.github/workflows/open-table.yml`. It uses the validator's single-comment mode,
implements contextual reduction outside this core, and now implements the
detection mechanism sections 2.2 and 2.3 require, with both of the obligations
that mechanism places on the deployment adapter now deployed: runs for a session
serialise, and the periodic timeline read section 2.3 requires runs as an hourly
scheduled sweep, whose period is a target rather than an upper bound. Whether a
period that is not an upper bound counts as satisfying that obligation is left
open by section 2.3 and recorded as issue 178. It explicitly remains
non-conformant either way, because section 1.7 makes reducer conformance the
conjunction of every reducer requirement, and these two are necessary rather
than sufficient. The mechanism is the `manifest` family of section
4.18, selected in
`docs/decisions/adr-20260816-detection-is-a-manifest-and-a-conditional-timeline-read.md`.
The accepted deployment boundary is recorded in
`docs/decisions/adr-20260804-open-table-reducer-is-deliberation-only-and-not-conformant.md`.

## Built on Hermes Agent

Steve Agent is built on [Hermes Agent](https://github.com/nousresearch/hermes-agent)
(MIT) by [Nous Research](https://nousresearch.com).

## Status and roadmap

A working factory today: tasks flow from chat to reviewed PRs, with an instance blueprint, CI, a main-guard, and deterministic `safe`-tier merges through a GitHub App all in place. Future roadmap: a WhatsApp layout, idea round-tables with multi-role subagents, and multi-project support.

## Community

- [CONTRIBUTING.md](CONTRIBUTING.md) - how to contribute: branching, pull requests, review tiers, and the merge flow.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) - the community standards we expect from contributors.
- [SECURITY.md](SECURITY.md) - how to report a vulnerability responsibly.

## License

Source-available under the Business Source License (BUSL) 1.1. Free for
noncommercial use, including personal, research, education, nonprofit, and
evaluation. Production and commercial use require a commercial license. Each
release converts to Apache 2.0 after four years. For commercial licensing, open
an issue.

Developed by the [IAmers](https://github.com/iamers) community.
