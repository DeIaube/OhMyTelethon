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
Round behavior can also live in `tg_cli/.tg-cli.json`, so day-to-day runs can be as short as `tg-cli game round 5217114569`. Multiple named presets can live under `presets`, then selected with `--preset NAME` for `game suggest`, `game round`, `daemon run`, or `quota start`. Keep initiative disabled or low-frequency by default; use explicit presets such as `chat_normal` or `chat_social` for bounded tests. `chat_social` can set an `initiative.min_starts` floor so a five-minute run produces bounded, content-aware proactive opportunities even if the group keeps moving, and `initiative.allow_topic_shift` lets it start a safe fallback topic instead of engaging ads, spam, or grey-area context.

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
tg-cli game context 5217114569 --limit 200 --preset public_group_safe --operator codex --json
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
tg-cli daemon next --peek
tg-cli daemon next --json
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --dry-run
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --json
tg-cli daemon skip <task_id> --reason "unclear context"
tg-cli daemon status
tg-cli daemon status --json
tg-cli daemon stop
tg-cli quota start --chat 111111111:120 --chat 222222222:300 --preset chat_social
tg-cli quota status --json
tg-cli quota next --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --dry-run --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --json
tg-cli quota stop
```

`game context` does not call an LLM. It reads a larger recent-history window and prints an agent-ready warmup summary: active speakers, local keyword/topic signals, notice/bot messages, recent questions, a compact summary, guidance, and a small message tail. Use it before daemon or longer live tests so the external agent knows what the group has recently been discussing without copying hundreds of raw messages into each task.

`game suggest` does not call an LLM. It prints an agent-ready reply context bundle with the selected `preset` name plus resolved `profile`, `persona`, `reply_policy`, and `initiative`. Codex, Claude, or another external agent decides the reply, then sends through `tg-cli send`.

`game round` is the bounded live game loop. It listens for new messages, prints recent context plus a compact agent instruction, asks the current operator for a reply, sends through the safety layer, and exits when `--duration` or `--max-replies` is reached. `--max-replies` is enforced as an outbound Telegram message cap, so a split reply will not exceed the cap. Use empty input to skip the current message and `/quit` to stop the round. At the end it prints a structured round report with elapsed time, received message counts, prompt count, sent reply count, sent message ids, skip reasons, average reply length, and initiative counts.

`daemon` is the v0.4 long-running operator mode. It still does not call an LLM or model provider. `tg-cli daemon run <chat>` owns Telegram IO for one whitelisted chat, writes local pending tasks when the account may naturally reply or open a light topic, and keeps local status/lock files. Codex, Claude, or another external agent claims the next pending item with `daemon next`, then either queues a reply with `daemon reply <task_id> "..."` or skips it with `daemon skip <task_id>`. The foreground daemon sends queued replies from the same Telethon session, so queue commands do not open Telegram while the daemon is running. Every send still goes through whitelist, `pause`, forbidden-term checks, daemon rate limits, dry-run behavior where applicable, and audit logging. More active presets can use `initiative.min_starts`, `initiative.min_start_after`, reply splitting, and preset-level daemon rate caps, but splitting is for natural separate thoughts rather than increasing message count.

Suggested first Social Policy test:

```sh
tg-cli game round 5217114569 --duration 300 --preset chat_social
```

See `tg_cli/docs/agent-operator.md` for the Codex/Claude operation flow.

Round operator flags:

- `--preset NAME`: apply `presets.NAME.profile`, `presets.NAME.persona`, `presets.NAME.reply_policy`, `presets.NAME.initiative`, `presets.NAME.round`, and non-path `presets.NAME.daemon` over the top-level defaults before command flags.
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
- `daemon next [--json]`: claim the next pending local task for Codex/Claude, including bounded recent context and resolved Social Policy guidance. The claim lease expires after `daemon.claim_ttl`.
- `daemon next --peek [--json]`: inspect the next pending task without claiming it.
- `daemon reply <task_id> "..." [--dry-run] [--json]`: validate and queue one claimed or pending reply for the running daemon to send. If `round.split_long_replies` is enabled, the running daemon can split a natural longer reply into several audited Telegram messages. With `--dry-run`, validate/audit without changing task state.
- `daemon skip <task_id> [--reason TEXT] [--json]`: mark a task skipped without sending.
- `daemon status [--json]`: show daemon lock, queue, pause, and rate-limit status.
- `daemon stop`: request the foreground daemon to stop cleanly.

Daemon config lives under top-level `daemon` in `tg_cli/.tg-cli.json`. The default local files are ignored by git: `.tg-cli-daemon-queue.json`, `.tg-cli-daemon-queue.json.lock`, `.tg-cli-daemon-status.json`, and `.tg-cli-daemon.lock`.

v0.4 daemon scope is intentionally narrow: one chat per daemon, local task queue only, no model API calls, no launchd/system service, no web UI, and no multi-group hosting. Multi-group and long-term background service behavior should be added only after the single-chat queue has proven stable.

## Quota Runs

Use quota mode when Codex automation owns the wall-clock trigger and `tg-cli` only needs to manage target counts across one or more whitelisted chats. For example, a Codex automation can wake the thread every day at 14:00, then start a local quota run for two groups:

```sh
tg-cli quota start --chat 111111111:120 --chat 222222222:300 --preset chat_social
```

`quota start` creates or replaces the local quota run state with one target per `--chat CHAT_ID:COUNT`. The default state file is `tg_cli/.tg-cli-quota-state.json`, configurable as `quota.state_path` in `tg_cli/.tg-cli.json`. This file, its lock file, and atomic-write temp files are ignored by git and are local runtime state, not source. The state tracks the run id, status, target counts, sent counts, task ids, and sent Telegram message ids; it may also contain bounded task context, so do not commit or share it.

Codex, Claude, or another operator then works the quota run:

```sh
tg-cli quota status --json
tg-cli quota next --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --dry-run --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --json
tg-cli quota stop
```

`quota next --json` selects the next active target chat, creates or claims one task, and returns bounded context plus resolved `profile`, `persona`, `reply_policy`, `initiative`, `round`, and `preset` guidance. `quota reply` sends one operator-written reply for that task. Use `--dry-run` for new groups or changed presets: it validates whitelist, pause, forbidden terms, split/remaining-count behavior, and audit behavior without sending, consuming the task, or incrementing counts.

Counting rules are deliberately strict:

- Only successful Telegram sends increment `sent_count`.
- If a natural reply is split into several Telegram messages, each successful part counts as one message.
- Dry-run replies never increment counts.
- `quota reply` also honors `daemon.min_reply_interval`, `daemon.max_messages_per_hour`, and `daemon.max_consecutive_replies` so automation loops cannot send faster than the configured safety limits.
- When one chat reaches its target, that target becomes `done` and receives no more quota replies for the active run.
- When every target is done, the run becomes `done`.
- `quota stop` marks the run `stopped` and blocks new quota tasks and replies without deleting audit history. In-flight sends that already passed the final safety gate may still be counted if Telegram accepted them.

Quota mode is not a scheduler and does not call a model provider. It is the send/count state machine that a Codex automation can trigger daily. Keep one live quota operator flow per Telethon session so concurrent commands do not fight over the same local session file.

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
- `daemon next` claims tasks with a lease, so another operator does not receive the same task until the lease expires.
- `daemon reply` must keep enforcing `allowed_chats`, `pause`, forbidden terms, and audit logging before a reply enters the send queue; `daemon run` enforces minimum reply interval, per-hour message limit, consecutive reply limit, stale queued-reply expiration, and final send audit.
- `quota reply` must keep enforcing `allowed_chats`, `pause`, forbidden terms, dry-run semantics, and audit logging before any quota progress is counted.
- Quota target counts are caps for the active run, not permission to spam. Keep presets, rate limits, and operator judgment conservative.
- Long round replies can be split into several messages only when that is natural, with each part still passing forbidden-term checks and audit logging.
- Audit logs store message hashes and lengths, not raw message text.
- Use one live Telegram-writing `tg-cli` flow per Telethon session file. If another command runs while `game round`, `daemon run`, or a quota reply flow owns the same session, the CLI reports a readable session-lock error instead of a raw SQLite traceback.
