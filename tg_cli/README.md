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

Profile fields are optional and default to safe game-round guidance. Social Policy is split into three layers: `persona` says "像谁", `reply_policy` says "怎么接话", and `initiative` says "怎么主动开口". Social presets should not only answer the latest message: `chat_social` mixes direct replies with context-adjacent topic starts, roughly 60%接话 / 40%旁路引题. See `tg_cli/docs/profile-config.md` for the full profile schema, preset behavior, prompt behavior, and local safety filtering rules.
The agent runtime also accepts an elizaOS-inspired `character` block and optional local `memory`. `character` adds action/evaluator hints such as `reply`, `light_joke`, `skip_short_ack`, and `no_identity_claims`; `memory` stores concise room/user notes in a local SQLite file when explicitly enabled. See `tg_cli/docs/elizaos-inspired-runtime.md`.
For a profile-only starter that contains no credentials, copy `tg_cli/docs/local-profile-template.json` into your local `tg_cli/.tg-cli.json` and add credentials through environment variables.
Round behavior can also live in `tg_cli/.tg-cli.json`, so day-to-day runs can be as short as `tg-cli game round 5217114569`. Multiple named presets can live under `presets`, then selected with `--preset NAME` for `game suggest`, `game round`, `daemon run`, or `quota start`. Keep initiative disabled or low-frequency by default; use explicit presets such as `chat_normal` or `chat_social` for bounded tests. `chat_social` sets an `initiative.min_starts` floor, raises `initiative.active_threshold`, and enables `initiative.allow_topic_shift` so a short run produces bounded, content-aware proactive opportunities even if the group keeps moving. `initiative.self_context_guard` prevents proactive openings when the recent non-notice tail is already dominated by the account's own messages. Inbound ads, spam, adult-service solicitations, and actual account/black-market messages are still skipped as direct reply targets, but initiative prompts should usually ignore that context and pivot to a safe light topic instead of going silent.

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
tg-cli quota skip <task_id> --reason "unsafe_or_stale_context" --json
tg-cli quota stop
tg-cli scenario list --json
tg-cli scenario show authorized-chat-social-150 --json
tg-cli scenario start authorized-chat-social-150 --json
tg-cli memory remember 5217114569 --scope room --kind summary --text "这个群最近在聊晚上开黑。"
tg-cli memory remember 5217114569 --scope user --sender-id 123456 --sender-name "阿强" --kind preference --text "阿强常接游戏话题。"
tg-cli memory list 5217114569 --json
tg-cli badcase list --chat 5217114569 --json
tg-cli badcase export
```

`game context` does not call an LLM. It reads a larger recent-history window and prints an agent-ready warmup summary: active speakers, local keyword/topic signals, notice/bot messages, recent questions, a compact summary, guidance, and a small message tail. Use it before daemon or longer live tests so the external agent knows what the group has recently been discussing without copying hundreds of raw messages into each task.

`game suggest` does not call an LLM. It prints an agent-ready reply context bundle with the selected `preset` name plus resolved `profile`, `persona`, `reply_policy`, `initiative`, `character`, and relevant `memory` snippets. Codex, Claude, or another external agent decides the reply, then sends through `tg-cli send`.

`game round` is the bounded live game loop. It listens for new messages, prints recent context plus a compact agent instruction, asks the current operator for a reply, sends through the safety layer, and exits when `--duration` or `--max-replies` is reached. `--max-replies` is enforced as an outbound Telegram message cap, so a split reply will not exceed the cap. Use empty input to skip the current message and `/quit` to stop the round. At the end it prints a structured round report with elapsed time, received message counts, prompt count, sent reply count, sent message ids, skip reasons, average reply length, and initiative counts.

`daemon` is the v0.4 long-running operator mode. It still does not call an LLM or model provider. `tg-cli daemon run <chat>` owns Telegram IO for one whitelisted chat, writes local pending tasks when the account may naturally reply or open a light topic, and keeps local status/lock files. Codex, Claude, or another external agent claims the next pending item with `daemon next`, then either queues a reply with `daemon reply <task_id> "..."` or skips it with `daemon skip <task_id>`. The foreground daemon sends queued replies from the same Telethon session, so queue commands do not open Telegram while the daemon is running. Every send still goes through whitelist, `pause`, forbidden-term checks, daemon rate limits, dry-run behavior where applicable, minimum reply length, and audit logging. More active presets can use `initiative.min_starts`, `initiative.min_start_after`, `initiative.self_context_guard`, character action/evaluator hints, longer copy with reply splitting, and preset-level daemon rate caps. Social presets may prefer richer replies split into up to five natural short messages.

`memory` manages optional local room/user notes. It is off by default and stores short operator-authored summaries, preferences, or recurring topic notes. Event records store message hashes and lengths, not raw text. Use memory to help Codex remember stable group context without building a raw Telegram archive.

`badcase` manages automatically captured local bad cases. `game round`, `daemon run`, and `quota reply` record structured cases for known failure signals such as `self_context_wait`, `stale_context`, `min_reply_chars`, `max_replies`, forbidden terms, AI/anti-spam challenges, and unsafe inbound topics. Records live in `tg_cli/.tg-cli-bad-cases.jsonl` by default, are ignored by git, and store message hashes/lengths plus reusable lessons rather than raw Telegram text. Recent same-chat bad cases are injected into `game suggest`, daemon tasks, and quota tasks so later operators see what to avoid.

Suggested first Social Policy test:

```sh
tg-cli game round 5217114569 --duration 300 --preset chat_social
```

See `tg_cli/docs/agent-operator.md` for the Codex/Claude operation flow.
See `tg_cli/docs/scenario-runs.md` for authorized long-running scenario handoffs such as one account, one informed test group, one persona/preset, and a `150` message quota target.

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
- `daemon reply <task_id> "..." [--dry-run] [--json]`: validate and queue one claimed or pending reply for the running daemon to send. If `round.split_long_replies` is enabled, the running daemon can split a natural longer reply into several audited Telegram messages, capped by `round.split_max_parts`. Each outgoing part must satisfy `round.min_reply_chars`. With `--dry-run`, validate/audit without changing task state.
- `daemon skip <task_id> [--reason TEXT] [--json]`: mark a task skipped without sending.
- `daemon status [--json]`: show daemon lock, queue, pause, and rate-limit status.
- `daemon stop`: request the foreground daemon to stop cleanly.
- `badcase list [--chat CHAT_ID] [--type TYPE] [--reason REASON] [--json]`: show recent automatically captured bad cases.
- `badcase export [--chat CHAT_ID] [--json]`: export captured bad cases as JSONL or JSON.

Daemon config lives under top-level `daemon` in `tg_cli/.tg-cli.json`. The default local files are ignored by git: `.tg-cli-daemon-queue.json`, `.tg-cli-daemon-queue.json.lock`, `.tg-cli-daemon-status.json`, and `.tg-cli-daemon.lock`.

v0.4 daemon scope is intentionally narrow: one chat per daemon, local task queue only, no model API calls, no launchd/system service, no web UI, and no multi-group hosting. Multi-group and long-term background service behavior should be added only after the single-chat queue has proven stable.

## Quota Runs

Use quota mode when Codex automation owns the wall-clock trigger and `tg-cli` only needs to manage target counts across one or more whitelisted chats. For example, a Codex automation can wake the thread every day at 14:00, then start a local quota run for two groups:

```sh
tg-cli quota start --chat 111111111:120 --chat 222222222:300 --preset chat_social
```

For long-running informed tests, an operator may describe a scenario as "account X, authorized chat Y, persona/preset Z, target 150 messages." This is only a handoff convention over quota mode. Recommended scenario fields are `name`, `account`, `chat_id`, `persona`, `preset`, `target_messages`, `dry_run_first`, `max_runtime_minutes`, and `stop_on`. Keep scenario files credential-free, and keep them limited to authorized/informed test groups.

`quota start` creates or replaces the local quota run state with one target per `--chat CHAT_ID:COUNT`. The default state file is `tg_cli/.tg-cli-quota-state.json`, configurable as `quota.state_path` in `tg_cli/.tg-cli.json`. This file, its lock file, and atomic-write temp files are ignored by git and are local runtime state, not source. The state tracks the run id, status, target counts, sent counts, task ids, and sent Telegram message ids; it may also contain bounded task context, so do not commit or share it.

Codex, Claude, or another operator then works the quota run:

```sh
tg-cli quota status --json
tg-cli quota next --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --dry-run --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --json
tg-cli quota skip <task_id> --reason "unsafe_or_stale_context" --json
tg-cli quota stop
```

Recommended scenario loop: `scenario start NAME --json`, `quota status --json`, `quota next --json`, first suitable `quota reply ... --dry-run --json`, live `quota reply ... --json` only when the dry-run passes and the context is still natural, `quota skip ... --reason ... --json` when it is not suitable, then target reached stop/report. Example `stop_on` labels are `target_reached`, `manual_stop`, `moderation_warning`, `spam_complaint`, `too_many_stale_context`, `hourly_limit`, and `unsafe_context_ratio`.

`quota next --json` selects the next active target chat, creates or claims one task, and returns bounded context plus resolved `profile`, `persona`, `reply_policy`, `initiative`, `character`, `memory`, `round`, and `preset` guidance. `quota reply` sends one operator-written reply for that task. Use `--dry-run` for new groups or changed presets: it validates whitelist, pause, forbidden terms, split/remaining-count behavior, and audit behavior without sending, consuming the task, or incrementing counts. Use `quota skip` when the task context is unsafe, stale, too unclear, or not worth replying to.

Counting rules are deliberately strict:

- Only successful Telegram sends increment `sent_count`.
- If a natural reply is split into several Telegram messages, each successful part counts as one message.
- Dry-run replies never increment counts.
- `quota reply` also honors `daemon.min_reply_interval` and `daemon.max_messages_per_hour` so automation loops cannot send faster than the configured pacing limits.
- Before a real send, `quota reply` re-reads the latest chat tail. If a newer inbound message appeared after the task snapshot, the task is skipped with `reason=stale_context` and nothing is sent.
- When one chat reaches its target, that target becomes `done` and receives no more quota replies for the active run.
- When every target is done, the run becomes `done`.
- `quota stop` marks the run `stopped` and blocks new quota tasks and replies without deleting audit history. In-flight sends that already passed the final safety gate may still be counted if Telegram accepted them.

Quota mode is not a scheduler and does not call a model provider. It is the send/count state machine that a Codex automation can trigger daily. Keep one live quota operator flow per Telethon session so concurrent commands do not fight over the same local session file. Do not describe quota/scenario runs as platform risk bypass, anti-detection behavior, or disguised automation; all sends remain behind allowlist, `pause`, forbidden terms, daemon pacing, quota skip, stale preflight, audit logs, and bad-case constraints.

## Safety Rules

- Write operations require `TG_CLI_ALLOWED_CHATS` or `allowed_chats` in config.
- `pause` blocks all sends until `resume`.
- `send` asks for confirmation unless `--yes` is passed.
- `--dry-run` resolves and audits without sending.
- `profile.forbidden_terms` and `profile.avoid_topics` block outbound text before `client.send_message`.
- `persona`, `reply_policy`, and `initiative` are prompt guidance only. They do not authorize sending to non-whitelisted chats, bypass `pause`, bypass forbidden terms, skip rate limits, hide audit records, or suppress the round report.
- `character`, `actions`, `evaluators`, and `memory` are prompt/task context only. They do not grant extra send permission or bypass any safety control.
- `bad_cases` are prompt/task guidance and local diagnostics only. They do not authorize sending, bypass safety, or store raw Telegram text.
- Inbound agent prompts are deterministically skipped when recent text contains high-risk signals such as AI/robot accusations, anti-spam or ban warnings, adult-service solicitations, non-consensual recording, underage/age-risk language, ads, or actual account/black-market topics. Ads, traffic redirection, and adult-service solicitations are skip-only signals; they must not enter a risk cooldown by themselves. Moderation warnings aimed at another user are ambient context and should skip the current task, not stop the run; only warnings that name or mention the logged-in account should be treated as direct stop/cooldown signals by the operator.
- In trusted test groups, in-group banter terms are not skip reasons by themselves. Do not skip solely because friends joke with words like 老师, 出击, 雷暴, 好评, 券, or price. Skip only when the message becomes real solicitation, contact routing, private data, minors, non-consensual recording, account trading, or other actual black-market content.
- For social initiative tasks in trusted tests, light adult banter may get a short non-explicit reaction. Skipped direct-reply contexts such as bot notices, traffic redirection, real adult-service solicitation, or incomplete private banter should usually be ignored while the operator starts a safe adjacent topic.
- Proactive initiative tasks are skipped with `self_context_wait` when the recent non-notice tail already has too many consecutive messages from the logged-in account. This is not a total reply cap; it waits for new human context before opening another topic.
- `game round` rate-limits sends and stops prompting near the end of a bounded round.
- `game round` can skip low-information messages, skip by probability, merge rapid messages, and delay sends without becoming a daemon or auto mode.
- `daemon run` uses a single-instance lock so two daemons do not write the same queue/session at the same time.
- `daemon next` claims tasks with a lease, so another operator does not receive the same task until the lease expires.
- `daemon reply` must keep enforcing `allowed_chats`, `pause`, forbidden terms, and audit logging before a reply enters the send queue; `daemon run` enforces minimum reply interval, per-hour message limit, stale queued-reply expiration, and final send audit.
- `quota reply` must keep enforcing `allowed_chats`, `pause`, forbidden terms, dry-run semantics, and audit logging before any quota progress is counted.
- Quota target counts are caps for the active run, not permission to spam. Keep presets, rate limits, and operator judgment conservative.
- Long-running scenario targets such as `150` messages are caps for authorized tests, not a reason to send filler. Other agents should read `tg_cli/AGENTS.md`, dry-run first, use `quota skip` for unsuitable context, and stop/report automatically when the target is reached.
- Long round replies can be split into several messages when that is natural, with each part still passing minimum-length, forbidden-term, and audit checks.
- Audit logs store message hashes and lengths, not raw message text.
- Bad case records also store hashes/lengths and lessons, not raw message text. To add a new automated bad case, add a reason rule in `tg_cli.bad_cases.BAD_CASE_REASON_RULES` and call `record_bad_case` at the rule trigger.
- Use one live Telegram-writing `tg-cli` flow per Telethon session file. If another command runs while `game round`, `daemon run`, or a quota reply flow owns the same session, the CLI reports a readable session-lock error instead of a raw SQLite traceback.
