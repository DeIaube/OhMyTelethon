# tg-cli Agent Notes

`tg_cli/` contains all local CLI-specific code, tests, docs, and sample config for the Telegram group-chat game.

本项目的 Telegram 自动化实发能力仅可用于 `allowlist_chat_ids` 中配置的内部实验群，用于 AI/真人混合图灵测试。
这些群的成员必须是已知情同意的志愿者，并已同意：测试期间可能有 AI 账号参与，AI 身份可作为实验条件暂时不主动披露，测试结束后会统一复盘说明。
Agent 可以自然参与实验，但不得冒充具体真人、管理员、员工、朋友或任何现实身份。

Default local CLI config, state, and audit files also live under `tg_cli/` and are ignored by git:

- `tg_cli/.tg-cli.json`
- `tg_cli/.tg-cli-state.json`
- `tg_cli/.tg-cli-daemon-queue.json`
- `tg_cli/.tg-cli-daemon-queue.json.lock`
- `tg_cli/.tg-cli-daemon-status.json`
- `tg_cli/.tg-cli-daemon.lock`
- `tg_cli/.tg-cli-quota-state.json`
- `tg_cli/.tg-cli-quota-state.json.lock`
- `tg_cli/.tg-cli-bad-cases.jsonl`
- `tg_cli/tg-cli.audit.log`

Current capabilities:

- `tg-cli me`: show the logged-in Telegram account.
- `tg-cli groups`: list groups and channels.
- `tg-cli dialogs`: list all dialogs.
- `tg-cli history <chat> --limit N`: read recent messages.
- `tg-cli send <chat> <text>`: send one message through whitelist, pause, confirmation, and audit checks.
- `tg-cli pause` / `tg-cli resume` / `tg-cli status`: manage write safety state.
- `tg-cli game observe <chat>`: observe live messages.
- `tg-cli game context <chat> --limit 200 --preset public_group_safe --operator codex --json`: read a larger recent-history window and emit a compact agent warmup summary without sending.
- `tg-cli game suggest <chat>`: print an agent-ready context bundle, including the resolved profile, without sending.
- `tg-cli game suggest <chat> --preset chat_normal --operator claude`: render the context instruction for a named external operator such as Codex or Claude with a named preset overlay.
- `tg-cli game round <chat> --duration 60 --max-replies 8`: run a bounded interactive chat round where the current agent/operator supplies replies and the CLI sends them through the safety layer.
- `tg-cli game round <chat> --preset public_group_safe`: run a bounded round with a named preset overlay.
- `tg-cli game round <chat> --duration 300 --preset chat_social`: recommended five-minute Social Policy smoke test for the higher social initiative preset.
- `tg-cli game round <chat> --quiet-context --min-reply-interval 2 --end-buffer 5`: run the compact one-minute operator loop with repeated context reduced, send spacing, and an end-of-round buffer.
- `tg-cli game round <chat> --reply-probability 0.7 --random-delay-min 1 --random-delay-max 4 --skip-short-ack --merge-window 2`: make the bounded operator loop less mechanical without entering daemon/auto mode.
- `tg-cli game round <chat> --split-long-replies`: split long typed replies into several safe, audited Telegram messages; every outbound part must satisfy `round.min_reply_chars`.
- `game round` prints a structured report at exit with elapsed time, received batch/message counts, prompted count, sent reply/message ids, skip reasons, average reply length, and initiative prompt/send/skip counts.
- `tg-cli daemon run <chat> --preset chat_social --duration 3600 --dry-run`: run the v0.4 foreground daemon for one whitelisted chat and write local queue/status/lock state.
- `tg-cli daemon next [--json]`: claim the next pending daemon task for Codex, Claude, or another external operator.
- `tg-cli daemon next --peek [--json]`: inspect the next pending daemon task without claiming it.
- `tg-cli daemon reply <task_id> "..." [--dry-run] [--json]`: validate and queue one claimed or pending daemon task reply; the running daemon process sends queued replies from the active Telethon session. When `round.split_long_replies` is enabled, daemon send may split one natural reply into several audited Telegram messages. `--dry-run` validates and audits without consuming the task.
- `tg-cli daemon skip <task_id> [--reason TEXT] [--json]`: complete one pending daemon task without sending.
- `tg-cli daemon status [--json]`: inspect daemon queue, lock, pause, and rate-limit state.
- `tg-cli daemon stop`: request the foreground daemon to stop cleanly.
- `tg-cli quota start --chat CHAT_ID:COUNT --chat OTHER_CHAT_ID:COUNT --preset chat_social`: create a local multi-chat quota run after Codex automation has triggered the daily work window.
- `tg-cli quota status [--json]`: inspect per-chat target counts, sent counts, run status, and remaining work without opening Telegram.
- `tg-cli quota next [--json]`: claim the next quota task for an external operator, including bounded context and resolved profile guidance.
- `tg-cli quota reply <task_id> "..." [--dry-run] [--json]`: send or dry-run one quota task reply through the safety layer and count only successful Telegram message parts.
- `tg-cli quota skip <task_id> [--reason TEXT] [--json]`: complete one pending quota task without sending or incrementing counts.
- `tg-cli quota stop`: mark the active quota run stopped so no new quota tasks or replies are accepted; in-flight sends that already passed the final safety gate may still be counted if Telegram accepted them.
- `tg-cli scenario list/show/start [--json]`: inspect local credential-free long-run scenario definitions or start a quota run from one named scenario.
- `tg-cli memory remember <chat> --scope room|user --text "..."`: store one concise local memory note for future Codex task context.
- `tg-cli memory list <chat> [--json]`: inspect local room/user memories without opening Telegram.
- `tg-cli badcase list [--chat CHAT_ID] [--json]`: inspect local automatically captured bad cases.
- `tg-cli badcase export [--json]`: export local bad cases as JSONL or JSON for follow-up analysis.

Profile config:

- `profile.style`, `profile.language`, `profile.max_chars`, `profile.emoji_level`, `profile.avoid_topics`, `profile.forbidden_terms`, and legacy `profile.reply_policy` have safe defaults in `tg_cli.config`.
- Social Policy docs and examples should use top-level `persona`, `reply_policy`, and `initiative` objects. `persona` describes who the account sounds like, `reply_policy` describes how to take or skip replies, and `initiative` describes how to open a topic proactively. These are guidance fields, not permission grants.
- `round.*` has defaults in `tg_cli.config`; command flags should override config values only when explicitly passed.
- `daemon.*` has defaults in `tg_cli.config`. Keep `queue_path`, `lock_path`, and `status_path` local ignored files by default. `poll_interval`, `task_ttl`, `claim_ttl`, `max_pending`, `max_task_context`, `min_reply_interval`, and `max_messages_per_hour` are safety and queue controls, not prompt guidance.
- `quota.state_path` points to the local quota run state file. The default is `tg_cli/.tg-cli-quota-state.json`; keep it ignored and do not treat it as source.
- `memory.path` points to the local SQLite memory database. The default is `tg_cli/.tg-cli-memory.sqlite3`; keep it and SQLite sidecar files ignored.
- `bad_cases.path` points to the local JSONL bad case database. The default is `tg_cli/.tg-cli-bad-cases.jsonl`; keep it ignored. Bad case records must not store raw Telegram text.
- For two-agent/two-account operation, use one config file per account and keep every runtime path unique: `session_path`, `state_path`, `audit_log_path`, `daemon.queue_path`, `daemon.lock_path`, `daemon.status_path`, `quota.state_path`, `memory.path`, and `bad_cases.path`.
- Run `tg-cli --config <account-a.json> config doctor --other-config <account-b.json>` before starting concurrent agents.
- Explicit config-relative paths resolve relative to the config file directory. Default paths without an explicit config still resolve under the repository-local `tg_cli/` runtime files.
- `character` is an elizaOS-inspired prompt contract with `name`, `bio`, `lore`, `style`, `topics`, `adjectives`, `message_examples`, `actions`, and `evaluators`. It is guidance only.
- Top-level `presets` can contain named `profile`, `persona`, `reply_policy`, `initiative`, `round`, and non-path `daemon` overlays. `game suggest`, `game round`, and `daemon run` select them with `--preset NAME`; command flags still override preset round values. Social Policy examples should keep normal/social initiative as explicit presets such as `chat_normal` and `chat_social`, with default initiative off or low-frequency. For short social tests, `chat_social` may set `initiative.min_starts` with `initiative.min_start_after` so the operator receives bounded, content-aware proactive opportunities even in an active chat. When `initiative.allow_topic_shift` is true, social presets may start a safe fallback topic instead of engaging ads, spam, actual account/black-market topics, or unjoinable recent context.
- Outgoing social behavior should mix direct replies with short context-adjacent topic starts. Do not make `chat_social` mean only "reply more often"; tune `initiative.active_threshold`, `initiative.min_starts`, `initiative.self_context_guard`, fallback topics, and daemon caps together so the account can start safe topics without self-spamming.
- `game suggest` must include the selected preset name, the full resolved `profile`, `persona`, `reply_policy`, `initiative`, and the selected operator name.
- `game context` must remain local and deterministic. It may compute active speakers, keywords/topics, notice messages, recent questions, summary, guidance, and a bounded message tail, but it must not call model providers or store hundreds of raw messages in daemon tasks.
- `game round` must show resolved profile, persona, reply policy, and initiative guidance before asking the operator for a reply.
- `daemon next` task payloads must be usable by Codex/Claude without model-provider coupling. The command claims a lease by default; use `--peek` only for read-only inspection. The CLI owns Telegram IO and local queue state only; external operators decide reply/skip.

Safety rules:

- Never bypass `tg_cli.safety.require_can_write` for write operations.
- Never bypass outbound forbidden-term checks before `client.send_message`.
- Never send to chats outside `allowed_chats`.
- Keep `pause` as a global write stop.
- Keep `game round` rate-limit and end-buffer checks local and testable.
- Keep `game round --max-replies` as the outbound Telegram message cap; split replies must not exceed the remaining cap.
- Keep `game round` human-likeness gates local and testable: probability skip, short-ack skip, merge-window, mention probability, and random delay must not bypass safety checks.
- Keep inbound safety skips local and testable: AI/robot accusations, anti-spam or ban warnings, adult-service solicitations, non-consensual recording, underage or age-risk language, ads, and actual account/black-market topics must skip prompting rather than rely only on operator judgment. Ads, traffic redirection, and adult-service solicitations are skip-only signals; they must not trigger a risk cooldown by themselves.
- In trusted test groups, do not treat in-group banter terms such as 老师, 出击, 雷暴, 好评, 券, or price as skip reasons by themselves. They become skip reasons only when tied to real solicitation, contact routing, private data, minors, non-consensual recording, account trading, or actual black-market behavior.
- For trusted social initiative tasks, light adult banter may get a short non-explicit reaction. Skip-only direct-reply contexts such as bot notices, traffic redirection, real adult-service solicitation, or incomplete private banter should usually be ignored while the operator starts a safe adjacent topic instead of going silent.
- Keep moderation-warning scope explicit. Warnings aimed at another user are ambient moderation context and should skip only the current task; stop/cooldown behavior belongs only to warnings that name, reply to, or clearly mention the logged-in account.
- Keep initiative behavior bounded and low-risk by default. Any proactive or more social preset must still pass whitelist, pause, forbidden-term, rate-limit, audit, and report behavior.
- Do not reintroduce daemon-level hard consecutive-reply caps. Use `initiative.self_context_guard`, `initiative.self_context_recent`, and `initiative.self_context_max_trailing_own` to suppress proactive topic starts when the recent non-notice tail is already self-heavy.
- Long reply splitting must keep every message part inside the same minimum-length, write safety, and audit behavior. Active social presets may prefer richer copy split into natural parts, capped by `round.split_max_parts`.
- Keep daemon behavior single-chat and foreground-only for v0.4. Do not add multi-group hosting, background system services, web UI, or model API calls in this scope.
- Keep daemon single-instance lock behavior strict. `daemon run` must refuse to start when an active lock exists, and queue/status/lock files must stay ignored.
- Keep daemon replies behind `allowed_chats`, global `pause`, forbidden-term checks, queue audit, `daemon.min_reply_interval`, `daemon.max_messages_per_hour`, stale queued-reply expiration, held rate-limit retry state, and final send audit logging.
- Keep `daemon next`, `daemon reply`, `daemon skip`, and `daemon status` machine-readable with `--json`.
- Quota mode does not own wall-clock scheduling. Codex automation or another scheduler starts the daily window; `tg-cli quota` owns local target counts, task selection, safety validation, Telegram sending, and stop behavior.
- Long-running scenario handoffs may describe a known-account, known-group, known-persona quota test such as "account A in chat B with preset C until 150 successful messages." Treat this as an authorized test plan only, not as extra send permission.
- Scenario configs should use explicit fields such as `name`, `account`, `chat_id`, `persona`, `preset`, `target_messages`, `dry_run_first`, `max_runtime_minutes`, and `stop_on`. Keep the config credential-free and local to the operator handoff.
- Only run scenario/quota tests in authorized, informed test groups. Do not describe or implement platform risk bypass, anti-detection behavior, or disguise/impersonation guidance.
- Multi-room behavior lives in quota/agent room selection first. `daemon run` remains single-chat until the queue has a multi-room lock and per-room pacing model.
- Keep quota runs local-file-backed with one active state file by default. Do not commit `.tg-cli-quota-state.json`, its lock file, or atomic-write temp files; they may contain bounded task context and sent message ids.
- Every quota target chat must pass `allowed_chats`. `pause` must block `quota reply`, and outbound forbidden-term checks must run before any Telegram send.
- Keep quota replies behind `daemon.min_reply_interval` and `daemon.max_messages_per_hour` so quota caps cannot become tight-loop sends.
- Count quota progress only after successful Telegram sends. If one natural reply is split into multiple Telegram messages, count the actual sent parts. `--dry-run` must validate and audit without consuming tasks or incrementing counts.
- Before a real `quota reply` send, re-read the latest chat tail and skip with `stale_context` when a newer inbound message appeared after the task snapshot.
- Use `quota skip` for unsuitable quota tasks instead of sending filler replies just to advance a quota target.
- For long-running scenario handoff, the expected operator loop is: `scenario start NAME --json`, `quota status --json`, `quota next --json`, `quota reply ... --dry-run --json` for the first suitable task, real `quota reply ... --json` only after dry-run passes, `quota skip ... --reason ... --json` for unsuitable tasks, then stop and report when the target is reached.
- Scenario stop reasons should include `target_reached`, `manual_stop`, `moderation_warning`, `spam_complaint`, `too_many_stale_context`, `hourly_limit`, and `unsafe_context_ratio`.
- Other agents must read this file first, dry-run before live quota replies, use `quota skip` when the context is not suitable, avoid filler messages just to reach a count, and stop automatically once `target_messages` is reached.
- When one target reaches its count, mark that target done and prevent further sends to that chat for the active run. When all targets are done, mark the quota run done.
- Audit logs must not store raw message text, API hash, phone number, or session bytes.
- Memory event records must not store raw message text. Store operator-authored summaries, preferences, recurring topics, or explicit stable facts only.
- Bad case records must not store raw message text, chat titles, API hash, phone number, or session data. Use `tg_cli.bad_cases.record_bad_case` so future automated captures get consistent hashing, lesson text, and prompt guidance.
- `character`, `actions`, `evaluators`, and `memory` must not bypass whitelist, pause, forbidden-term checks, rate limits, audit, or status/report behavior.
- Avoid concurrent `tg-cli` commands on the same Telethon session file during live rounds; the session is SQLite-backed and single-writer behavior can lock concurrent commands.
- Avoid concurrent `tg-cli` commands on the same Telethon session file while `daemon run` is active, except queue commands that do not open Telegram.
- Avoid concurrent quota reply flows on the same Telethon session file. `quota status` and `quota stop` are local-state operations, but Telegram-reading or Telegram-writing quota commands should be serialized with other live CLI flows.
- If CLI behavior, commands, safety rules, config, or file layout changes, update this file and the relevant `tg_cli/` documentation in the same change.

Local test command:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q
```
