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

Profile fields are optional and default to safe game-round guidance. Social Policy is split into three layers: `persona` says "像谁", `reply_policy` says "怎么接话", and `initiative` says "怎么主动开口". See `tg_cli/docs/profile-config.md` for the full profile schema, preset behavior, prompt behavior, and local safety filtering rules.
For a profile-only starter that contains no credentials, copy `tg_cli/docs/local-profile-template.json` into your local `tg_cli/.tg-cli.json` and add credentials through environment variables.
Round behavior can also live in `tg_cli/.tg-cli.json`, so day-to-day runs can be as short as `tg-cli game round 5217114569`. Multiple named presets can live under `presets`, then selected with `--preset NAME` for `game suggest` or `game round`. Keep initiative disabled or low-frequency by default; use explicit presets such as `chat_normal` or `chat_social` for bounded tests.

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
tg-cli game suggest 5217114569 --preset chat_normal --operator codex --json
tg-cli game suggest 5217114569 --preset chat_social --operator codex --json
tg-cli game suggest 5217114569 --operator claude --limit 20 --json
tg-cli game round 5217114569 --duration 60 --max-replies 8
tg-cli game round 5217114569 --preset public_group_safe
tg-cli game round 5217114569 --duration 300 --preset chat_social
tg-cli game round 5217114569 --duration 60 --quiet-context --min-reply-interval 2 --end-buffer 5
tg-cli game round 5217114569 --duration 120 --quiet-context \
  --reply-probability 0.75 --mention-reply-probability 1 \
  --random-delay-min 1 --random-delay-max 4 \
  --skip-short-ack --merge-window 2
tg-cli game round 5217114569 --split-long-replies
tg-cli daemon run 5217114569 --preset chat_social --duration 3600 --dry-run
tg-cli daemon next
tg-cli daemon next --json
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --dry-run
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --json
tg-cli daemon skip <task_id> --reason "unclear context"
tg-cli daemon status
tg-cli daemon status --json
tg-cli daemon stop
```

`game suggest` does not call an LLM. It prints an agent-ready context bundle with the selected `preset` name plus resolved `profile`, `persona`, `reply_policy`, and `initiative`. Codex, Claude, or another external agent decides the reply, then sends through `tg-cli send`.

`game round` is the bounded live game loop. It listens for new messages, prints recent context plus a compact agent instruction, asks the current operator for a reply, sends through the safety layer, and exits when `--duration` or `--max-replies` is reached. `--max-replies` is enforced as an outbound Telegram message cap, so a split reply will not exceed the cap. Use empty input to skip the current message and `/quit` to stop the round. At the end it prints a structured round report with elapsed time, received message counts, prompt count, sent reply count, sent message ids, skip reasons, average reply length, and initiative counts.

`daemon` is the v0.4 long-running operator mode. It still does not call an LLM or model provider. `tg-cli daemon run <chat>` owns Telegram IO for one whitelisted chat, writes local pending tasks when the account may naturally reply or open a light topic, and keeps local status/lock files. Codex, Claude, or another external agent reads the next pending item with `daemon next`, then either queues a reply with `daemon reply <task_id> "..."` or skips it with `daemon skip <task_id>`. The foreground daemon sends queued replies from the same Telethon session, so queue commands do not open Telegram while the daemon is running. Every send still goes through whitelist, `pause`, forbidden-term checks, daemon rate limits, dry-run behavior where applicable, and audit logging.

Suggested first Social Policy test:

```sh
tg-cli game round 5217114569 --duration 300 --preset chat_social
```

See `tg_cli/docs/agent-operator.md` for the Codex/Claude operation flow.

Round operator flags:

- `--preset NAME`: apply `presets.NAME.profile`, `presets.NAME.persona`, `presets.NAME.reply_policy`, `presets.NAME.initiative`, and `presets.NAME.round` over the top-level defaults before command flags.
- `--quiet-context`: print only each incoming message and compact agent instruction, not the repeated recent-context block.
- `--min-reply-interval SECONDS`: keep at least this much time between round sends. Default: `2`.
- `--end-buffer SECONDS`: stop prompting when less than this much time remains. Default: `5`.
- `--reply-probability 0..1`: probabilistically skip prompts so the account does not answer every message.
- `--mention-reply-probability 0..1`: use a higher prompt probability when the inbound text appears to mention the logged-in account.
- `--random-delay-min/--random-delay-max SECONDS`: wait a random human-like delay before sending a typed reply.
- `--skip-short-ack`: skip low-information acknowledgements such as `嗯`, `哈哈`, or `真的假的`.
- `--merge-window SECONDS`: collect rapid consecutive inbound messages before prompting once.
- `--split-long-replies`: split long typed replies into multiple Telegram messages using `round.split_*` config.

Daemon task queue commands:

- `daemon run <chat> --preset NAME --duration SECONDS --dry-run`: start one foreground daemon for one whitelisted chat. `--dry-run` lets the queue flow be tested without sending replies.
- `daemon next [--json]`: print the next pending local task for Codex/Claude, including bounded recent context and resolved Social Policy guidance.
- `daemon reply <task_id> "..." [--dry-run] [--json]`: validate and queue one reply for the running daemon to send. With `--dry-run`, validate/audit and mark the task complete without sending.
- `daemon skip <task_id> [--reason TEXT] [--json]`: mark a task skipped without sending.
- `daemon status [--json]`: show daemon lock, queue, pause, and rate-limit status.
- `daemon stop`: request the foreground daemon to stop cleanly.

Daemon config lives under top-level `daemon` in `tg_cli/.tg-cli.json`. The default local files are ignored by git: `.tg-cli-daemon-queue.json`, `.tg-cli-daemon-status.json`, and `.tg-cli-daemon.lock`.

v0.4 daemon scope is intentionally narrow: one chat per daemon, local task queue only, no model API calls, no launchd/system service, no web UI, and no multi-group hosting. Multi-group and long-term background service behavior should be added only after the single-chat queue has proven stable.

## Safety Rules

- Write operations require `TG_CLI_ALLOWED_CHATS` or `allowed_chats` in config.
- `pause` blocks all sends until `resume`.
- `send` asks for confirmation unless `--yes` is passed.
- `--dry-run` resolves and audits without sending.
- `profile.forbidden_terms` and `profile.avoid_topics` block outbound text before `client.send_message`.
- `persona`, `reply_policy`, and `initiative` are prompt guidance only. They do not authorize sending to non-whitelisted chats, bypass `pause`, bypass forbidden terms, skip rate limits, hide audit records, or suppress the round report.
- `game round` rate-limits sends and stops prompting near the end of a bounded round.
- `game round` can skip low-information messages, skip by probability, merge rapid messages, and delay sends without becoming a daemon or auto mode.
- `daemon run` uses a single-instance lock so two daemons do not write the same queue/session at the same time.
- `daemon reply` must keep enforcing `allowed_chats`, `pause`, forbidden terms, and audit logging before a reply enters the send queue; `daemon run` enforces minimum reply interval, per-hour message limit, consecutive reply limit, and final send audit.
- Long round replies can be split into several messages, with each part still passing forbidden-term checks and audit logging.
- Audit logs store message hashes and lengths, not raw message text.
- Use one long-running `tg-cli` process per Telethon session file. If another command runs while `game round` or `daemon run` owns the same session, the CLI reports a readable session-lock error instead of a raw SQLite traceback.
