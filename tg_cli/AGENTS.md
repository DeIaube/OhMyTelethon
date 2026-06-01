# tg-cli Agent Notes

`tg_cli/` contains all local CLI-specific code, tests, docs, and sample config for the Telegram group-chat game.

Default local CLI config, state, and audit files also live under `tg_cli/` and are ignored by git:

- `tg_cli/.tg-cli.json`
- `tg_cli/.tg-cli-state.json`
- `tg_cli/tg-cli.audit.log`

Current capabilities:

- `tg-cli me`: show the logged-in Telegram account.
- `tg-cli groups`: list groups and channels.
- `tg-cli dialogs`: list all dialogs.
- `tg-cli history <chat> --limit N`: read recent messages.
- `tg-cli send <chat> <text>`: send one message through whitelist, pause, confirmation, and audit checks.
- `tg-cli pause` / `tg-cli resume` / `tg-cli status`: manage write safety state.
- `tg-cli game observe <chat>`: observe live messages.
- `tg-cli game suggest <chat>`: print a Codex-ready context bundle without sending.
- `tg-cli game round <chat> --duration 60 --max-replies 8`: run a bounded interactive chat round where Codex supplies replies and the CLI sends them through the safety layer.

Safety rules:

- Never bypass `tg_cli.safety.require_can_write` for write operations.
- Never send to chats outside `allowed_chats`.
- Keep `pause` as a global write stop.
- Audit logs must not store raw message text, API hash, phone number, or session bytes.
- Keep auto/daemon behavior out of v0.1; use bounded `game round` for live tests.
- If CLI behavior, commands, safety rules, config, or file layout changes, update this file and the relevant `tg_cli/` documentation in the same change.

Local test command:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q
```
