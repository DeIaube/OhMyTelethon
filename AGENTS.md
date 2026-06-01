# Agent Notes

This repository is primarily the Telethon source tree. Keep Telethon library changes separate from local automation tooling.

The local Telegram game CLI lives in `tg_cli/`. It provides the `tg-cli` command for account inspection, group discovery, safe message sending, bounded observation, and Codex/Claude-assisted game rounds.

Do not commit local Telegram credentials or session artifacts:

- `*.session`
- `.tg-cli.json`
- `.tg-cli-state.json`
- `tg-cli.audit.log`

When working on CLI behavior, read `tg_cli/AGENTS.md` and keep CLI code, tests, docs, and examples inside `tg_cli/` unless a repository-level packaging hook is required.

If the CLI behavior, commands, safety rules, config, or file layout changes, update the relevant CLI documentation in `tg_cli/` in the same change.
