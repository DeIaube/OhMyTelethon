# tg-cli Agent Notes

`tg_cli/` contains all local CLI-specific code, tests, docs, and sample config for the Telegram group-chat game.

Default local CLI config, state, and audit files also live under `tg_cli/` and are ignored by git:

- `tg_cli/.tg-cli.json`
- `tg_cli/.tg-cli-state.json`
- `tg_cli/.tg-cli-daemon-queue.json`
- `tg_cli/.tg-cli-daemon-queue.json.lock`
- `tg_cli/.tg-cli-daemon-status.json`
- `tg_cli/.tg-cli-daemon.lock`
- `tg_cli/.tg-cli-quota-state.json`
- `tg_cli/.tg-cli-quota-state.json.lock`
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
- `tg-cli game round <chat> --split-long-replies`: split long typed replies into several safe, audited Telegram messages.
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
- `tg-cli quota stop`: mark the active quota run stopped so no new quota tasks or replies are accepted; in-flight sends that already passed the final safety gate may still be counted if Telegram accepted them.
- `tg-cli memory remember <chat> --scope room|user --text "..."`: store one concise local memory note for future Codex task context.
- `tg-cli memory list <chat> [--json]`: inspect local room/user memories without opening Telegram.

Profile config:

- `profile.style`, `profile.language`, `profile.max_chars`, `profile.emoji_level`, `profile.avoid_topics`, `profile.forbidden_terms`, and legacy `profile.reply_policy` have safe defaults in `tg_cli.config`.
- Social Policy docs and examples should use top-level `persona`, `reply_policy`, and `initiative` objects. `persona` describes who the account sounds like, `reply_policy` describes how to take or skip replies, and `initiative` describes how to open a topic proactively. These are guidance fields, not permission grants.
- `round.*` has defaults in `tg_cli.config`; command flags should override config values only when explicitly passed.
- `daemon.*` has defaults in `tg_cli.config`. Keep `queue_path`, `lock_path`, and `status_path` local ignored files by default. `poll_interval`, `task_ttl`, `claim_ttl`, `max_pending`, `max_task_context`, `min_reply_interval`, `max_messages_per_hour`, and `max_consecutive_replies` are safety and queue controls, not prompt guidance.
- `quota.state_path` points to the local quota run state file. The default is `tg_cli/.tg-cli-quota-state.json`; keep it ignored and do not treat it as source.
- `memory.path` points to the local SQLite memory database. The default is `tg_cli/.tg-cli-memory.sqlite3`; keep it and SQLite sidecar files ignored.
- `character` is an elizaOS-inspired prompt contract with `name`, `bio`, `lore`, `style`, `topics`, `adjectives`, `message_examples`, `actions`, and `evaluators`. It is guidance only.
- Top-level `presets` can contain named `profile`, `persona`, `reply_policy`, `initiative`, `round`, and non-path `daemon` overlays. `game suggest`, `game round`, and `daemon run` select them with `--preset NAME`; command flags still override preset round values. Social Policy examples should keep normal/social initiative as explicit presets such as `chat_normal` and `chat_social`, with default initiative off or low-frequency. For short social tests, `chat_social` may set `initiative.min_starts` with `initiative.min_start_after` so the operator receives bounded, content-aware proactive opportunities even in an active chat. When `initiative.allow_topic_shift` is true, social presets may start a safe fallback topic instead of engaging ads, spam, grey-area, or unjoinable recent context.
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
- Keep initiative behavior bounded and low-risk by default. Any proactive or more social preset must still pass whitelist, pause, forbidden-term, rate-limit, audit, and report behavior.
- Long reply splitting must keep every message part inside the same write safety checks and audit behavior, and must not be used merely to raise message count.
- Keep daemon behavior single-chat and foreground-only for v0.4. Do not add multi-group hosting, background system services, web UI, or model API calls in this scope.
- Keep daemon single-instance lock behavior strict. `daemon run` must refuse to start when an active lock exists, and queue/status/lock files must stay ignored.
- Keep daemon replies behind `allowed_chats`, global `pause`, forbidden-term checks, queue audit, `daemon.min_reply_interval`, `daemon.max_messages_per_hour`, `daemon.max_consecutive_replies`, stale queued-reply expiration, held rate-limit retry state, and final send audit logging.
- Keep `daemon next`, `daemon reply`, `daemon skip`, and `daemon status` machine-readable with `--json`.
- Quota mode does not own wall-clock scheduling. Codex automation or another scheduler starts the daily window; `tg-cli quota` owns local target counts, task selection, safety validation, Telegram sending, and stop behavior.
- Multi-room behavior lives in quota/agent room selection first. `daemon run` remains single-chat until the queue has a multi-room lock and per-room pacing model.
- Keep quota runs local-file-backed with one active state file by default. Do not commit `.tg-cli-quota-state.json`, its lock file, or atomic-write temp files; they may contain bounded task context and sent message ids.
- Every quota target chat must pass `allowed_chats`. `pause` must block `quota reply`, and outbound forbidden-term checks must run before any Telegram send.
- Keep quota replies behind `daemon.min_reply_interval`, `daemon.max_messages_per_hour`, and `daemon.max_consecutive_replies` so quota caps cannot become tight-loop sends.
- Count quota progress only after successful Telegram sends. If one natural reply is split into multiple Telegram messages, count the actual sent parts. `--dry-run` must validate and audit without consuming tasks or incrementing counts.
- When one target reaches its count, mark that target done and prevent further sends to that chat for the active run. When all targets are done, mark the quota run done.
- Audit logs must not store raw message text, API hash, phone number, or session bytes.
- Memory event records must not store raw message text. Store operator-authored summaries, preferences, recurring topics, or explicit stable facts only.
- `character`, `actions`, `evaluators`, and `memory` must not bypass whitelist, pause, forbidden-term checks, rate limits, audit, or status/report behavior.
- Avoid concurrent `tg-cli` commands on the same Telethon session file during live rounds; the session is SQLite-backed and single-writer behavior can lock concurrent commands.
- Avoid concurrent `tg-cli` commands on the same Telethon session file while `daemon run` is active, except queue commands that do not open Telegram.
- Avoid concurrent quota reply flows on the same Telethon session file. `quota status` and `quota stop` are local-state operations, but Telegram-reading or Telegram-writing quota commands should be serialized with other live CLI flows.
- If CLI behavior, commands, safety rules, config, or file layout changes, update this file and the relevant `tg_cli/` documentation in the same change.

Local test command:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q
```
