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
- `tg-cli game suggest <chat>`: print a Codex-ready context bundle, including the resolved profile, without sending.
- `tg-cli game round <chat> --duration 60 --max-replies 8`: run a bounded interactive chat round where Codex supplies replies and the CLI sends them through the safety layer.
- `tg-cli game round <chat> --quiet-context --min-reply-interval 2 --end-buffer 5`: run the compact one-minute operator loop with repeated context reduced, send spacing, and an end-of-round buffer.
- `tg-cli game round <chat> --reply-probability 0.7 --random-delay-min 1 --random-delay-max 4 --skip-short-ack --merge-window 2`: make the bounded operator loop less mechanical without entering daemon/auto mode.
- `tg-cli game round <chat> --split-long-replies`: split long typed replies into several safe, audited Telegram messages.

Profile config:

- `profile.style`, `profile.language`, `profile.max_chars`, `profile.emoji_level`, `profile.avoid_topics`, `profile.forbidden_terms`, and `profile.reply_policy` have safe defaults in `tg_cli.config`.
- `round.*` has defaults in `tg_cli.config`; command flags should override config values only when explicitly passed.
- `game suggest` must include the full resolved profile.
- `game round` must show profile guidance before asking the operator for a reply.

Safety rules:

- Never bypass `tg_cli.safety.require_can_write` for write operations.
- Never bypass outbound forbidden-term checks before `client.send_message`.
- Never send to chats outside `allowed_chats`.
- Keep `pause` as a global write stop.
- Keep `game round` rate-limit and end-buffer checks local and testable.
- Keep `game round` human-likeness gates local and testable: probability skip, short-ack skip, merge-window, mention probability, and random delay must not bypass safety checks.
- Long reply splitting must keep every message part inside the same write safety checks and audit behavior.
- Audit logs must not store raw message text, API hash, phone number, or session bytes.
- Keep auto/daemon behavior out of v0.2; use bounded `game round` for live tests.
- If CLI behavior, commands, safety rules, config, or file layout changes, update this file and the relevant `tg_cli/` documentation in the same change.

Local test command:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q
```
