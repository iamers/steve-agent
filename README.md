# Steve Agent

Dev-coordination AI agent for small development teams collaborating through a Telegram forum group.

Steve Agent handles the non-coding side of team work (task backlog, assignment, ideas, member interaction) and optionally integrates in-chat development assistance per feature topic, so a team can run planning, vibe coding, and review in the same channel.

## Status

Early design stage. No shipped artifact yet. Design in progress.

## First use case

Steve Agent is being designed to coordinate development of [rene-agent](https://github.com/iamers/rene-agent), a community-management agent for Telegram. Rene-agent and Steve Agent are part of a potential suite of AI agents built on Telegram plus open agent frameworks; running Steve in the rene-agent dev group is itself the first dogfooding exercise for the suite.

Steve Agent is designed to be reusable for any small dev team, not tied to rene-agent.

## Planned building blocks

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) for coordination and in-chat development assistance (two profiles: main and admin)
- [OpenClaw](https://github.com/openclaw) for optional dogfooding of the product under development, running as a separate bot restricted to dedicated test topics
- Shared VPS devbox with per-feature git worktrees, accessible via SSH by contributors who prefer working with Claude Code on their own machines

See sibling project [rene-agent](https://github.com/iamers/rene-agent) for conventions and a more mature repo structure.

## License

TBD.
