# tg-cli

`tg-cli` is a safety-first local CLI for the Telegram group-chat game. It reuses the local Telethon session and keeps all write operations behind a whitelist, pause switch, confirmation, and audit log.

## Local Setup

Use environment variables for credentials so secrets are not committed:

```sh
export TG_API_ID=12345
export TG_API_HASH='<your-api-hash>'
export TG_CLI_ALLOWED_CHATS=5217114569
```

The default session path is `./printer.session`. Override it when needed:

```sh
export TG_CLI_SESSION=/absolute/path/to/printer.session
```

Optional local config can live in `tg_cli/.tg-cli.json`. That file is ignored by git. Start from `tg_cli/tg-cli.example.json`.

## Commands

```sh
tg-cli me
tg-cli groups
tg-cli history 5217114569 --limit 20
tg-cli send 5217114569 "tg-cli 测试消息"
tg-cli send 5217114569 "tg-cli 测试消息" --yes
tg-cli send 5217114569 "tg-cli 测试消息" --dry-run --yes
tg-cli pause
tg-cli resume
tg-cli status
tg-cli game observe 5217114569
tg-cli game suggest 5217114569 --limit 20 --json
tg-cli game round 5217114569 --duration 60 --max-replies 8
```

`game suggest` does not call an LLM in v0.1. It prints a Codex-ready context bundle. Codex decides the reply, then sends through `tg-cli send`.

`game round` is the bounded live game loop. It listens for new messages, prints recent context, asks the current Codex operator for a reply, sends through the safety layer, and exits when `--duration` or `--max-replies` is reached.

## Safety Rules

- Write operations require `TG_CLI_ALLOWED_CHATS` or `allowed_chats` in config.
- `pause` blocks all sends until `resume`.
- `send` asks for confirmation unless `--yes` is passed.
- `--dry-run` resolves and audits without sending.
- Audit logs store message hashes and lengths, not raw message text.
