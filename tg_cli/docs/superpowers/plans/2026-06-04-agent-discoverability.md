# Agent Discoverability

## Goal

Make `tg-cli` easier for Codex, Claude, and other external agents to inspect safely before operating:

- [x] Add a machine-readable `tg-cli capabilities --json` command.
- [x] Add a credential-free local `tg-cli doctor agent --json` preflight.
- [x] Return standard JSON error objects when `--json` commands fail.
- [x] Add agent-facing recipes and keep docs updated with CLI behavior changes.
- [x] Cover the new behavior with tests.
- [x] Run the full `tg_cli` test suite and review the worktree.

## Constraints

- Keep CLI code, tests, and docs inside `tg_cli/`.
- Do not connect to Telegram or require credentials for capabilities or agent doctor.
- Do not expose session data, API hashes, access hashes, raw TL objects, message text archives, or downloaded bytes.
- Preserve existing human-readable errors for non-JSON commands.
