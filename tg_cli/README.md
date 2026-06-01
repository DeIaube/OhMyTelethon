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

Profile fields are optional and default to safe game-round guidance. See `tg_cli/docs/profile-config.md` for the full profile schema, prompt behavior, and local safety filtering rules.
For a profile-only starter that contains no credentials, copy `tg_cli/docs/local-profile-template.json` into your local `tg_cli/.tg-cli.json` and add credentials through environment variables.

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
tg-cli game round 5217114569 --duration 60 --quiet-context --min-reply-interval 2 --end-buffer 5
tg-cli game round 5217114569 --duration 120 --quiet-context \
  --reply-probability 0.75 --mention-reply-probability 1 \
  --random-delay-min 1 --random-delay-max 4 \
  --skip-short-ack --merge-window 2
```

`game suggest` does not call an LLM. It prints a Codex-ready context bundle with the full resolved profile. Codex decides the reply, then sends through `tg-cli send`.

`game round` is the bounded live game loop. It listens for new messages, prints recent context plus a compact Codex instruction, asks the current Codex operator for a reply, sends through the safety layer, and exits when `--duration` or `--max-replies` is reached. Use empty input to skip the current message and `/quit` to stop the round.

Round operator flags:

- `--quiet-context`: print only each incoming message and compact Codex instruction, not the repeated recent-context block.
- `--min-reply-interval SECONDS`: keep at least this much time between round sends. Default: `2`.
- `--end-buffer SECONDS`: stop prompting when less than this much time remains. Default: `5`.
- `--reply-probability 0..1`: probabilistically skip prompts so the account does not answer every message.
- `--mention-reply-probability 0..1`: use a higher prompt probability when the inbound text appears to mention the logged-in account.
- `--random-delay-min/--random-delay-max SECONDS`: wait a random human-like delay before sending a typed reply.
- `--skip-short-ack`: skip low-information acknowledgements such as `嗯`, `哈哈`, or `真的假的`.
- `--merge-window SECONDS`: collect rapid consecutive inbound messages before prompting once.

## Safety Rules

- Write operations require `TG_CLI_ALLOWED_CHATS` or `allowed_chats` in config.
- `pause` blocks all sends until `resume`.
- `send` asks for confirmation unless `--yes` is passed.
- `--dry-run` resolves and audits without sending.
- `profile.forbidden_terms` and `profile.avoid_topics` block outbound text before `client.send_message`.
- `game round` rate-limits sends and stops prompting near the end of a bounded round.
- `game round` can skip low-information messages, skip by probability, merge rapid messages, and delay sends without becoming a daemon or auto mode.
- Audit logs store message hashes and lengths, not raw message text.
