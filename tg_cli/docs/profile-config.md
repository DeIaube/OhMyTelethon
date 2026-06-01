# tg-cli Profile Config

`tg_cli/.tg-cli.json` is optional and ignored by git. Missing fields are filled with defaults in `tg_cli.config`, so older configs continue to work.

The current game profile has four layers:

- `profile`: basic tone, language, length, and local safety terms.
- `persona`: 像谁. A generic or fictional voice for the account, not a real-person binding.
- `reply_policy`: 怎么接话. When to reply, when to skip, and how to avoid over-answering.
- `initiative`: 怎么主动开口. Whether the account may start a topic, how often, and under which bounded triggers.

Default initiative should stay off or low-frequency. More active behavior belongs in explicit presets such as `chat_normal` and `chat_social`.

## Example

```json
{
  "allowed_chats": [1234567890],
  "daemon": {
    "queue_path": ".tg-cli-daemon-queue.json",
    "lock_path": ".tg-cli-daemon.lock",
    "status_path": ".tg-cli-daemon-status.json",
    "poll_interval": 1,
    "task_ttl": 900,
    "max_pending": 20,
    "max_task_context": 8,
    "min_reply_interval": 6,
    "max_messages_per_hour": 20,
    "max_consecutive_replies": 2
  },
  "profile": {
    "style": "自然、简短、像普通群聊，不要长篇解释。",
    "language": "中文",
    "max_chars": 80,
    "emoji_level": "low",
    "avoid_topics": ["隐私", "账号信息", "借钱"],
    "forbidden_terms": ["示例禁用词"],
    "reply_policy": "只在有明确可接话的内容时回复；不确定时跳过。"
  },
  "persona": {
    "identity": "普通群友，不绑定真实人。",
    "traits": ["短句", "自然", "不装懂"],
    "catchphrases": ["看情况", "先试试"],
    "avoid": ["长篇解释", "客服感"],
    "style_notes": ["像在群里随手回一句"]
  },
  "reply_policy": {
    "group_type": "chat",
    "reply_threshold": 0.6,
    "prefer_reply_when": ["direct question", "mentioned by name", "light joke"],
    "skip_when": ["ads", "spam", "conflict", "privacy", "unclear reference"],
    "style_rules": ["keep replies short", "avoid customer-service tone"],
    "conversation_rules": ["do not reply to everything", "do not fabricate facts"]
  },
  "initiative": {
    "enabled": false,
    "group_type": "chat",
    "style": "normal",
    "idle_after": 90,
    "cooldown": 180,
    "max_starts": 1,
    "avoid_when_active": true,
    "active_threshold": 6,
    "recent_window": 300,
    "topic_sources": ["recent_messages", "preset_topics"],
    "topics": ["最近有啥好玩的", "这个有人试过吗"],
    "allowed_intents": ["ask_open_question", "continue_recent_topic"],
    "forbidden_topics": ["广告", "交易", "隐私", "争吵"]
  }
}
```

For a credential-free starter file, see `tg_cli/docs/local-profile-template.json`. For the full sample with credentials placeholders and presets, see `tg_cli/tg-cli.example.json`.

## Fields

- `profile.style`: Natural-language tone guidance.
- `profile.language`: Preferred reply language.
- `profile.max_chars`: Suggested maximum reply length. This is prompt guidance, not a hard send limit.
- `profile.emoji_level`: Suggested emoji usage, such as `none`, `low`, `medium`, or `high`.
- `profile.avoid_topics`: Sensitive topics to avoid. The CLI also treats these strings as outbound block terms.
- `profile.forbidden_terms`: Exact sensitive terms that must not appear in outbound text.
- `profile.reply_policy`: Legacy compact reply guidance kept for backward compatibility.
- `persona.identity`: Generic role or voice.
- `persona.traits`: Short voice traits.
- `persona.catchphrases`: Optional common phrasing hints.
- `persona.avoid`: Voice patterns to avoid.
- `persona.style_notes`: Extra operator-facing style notes.
- `reply_policy.group_type`: Context label such as `chat`, `friends`, `interest`, or `public_large_group`.
- `reply_policy.reply_threshold`: Guidance threshold from `0` to `1`; lower is more willing to reply.
- `reply_policy.prefer_reply_when`: Situations where replying is natural.
- `reply_policy.skip_when`: Situations where skipping is preferred.
- `reply_policy.style_rules`: Reply-shape rules, usually short strings.
- `reply_policy.conversation_rules`: Conversation-level rules such as anti-spam or anti-fabrication.
- `initiative.enabled`: Whether bounded proactive prompts are allowed during `game round`.
- `initiative.idle_after`: Seconds of group idleness before a proactive prompt can appear.
- `initiative.cooldown`: Seconds between proactive starts.
- `initiative.max_starts`: Maximum proactive starts in one bounded round.
- `initiative.avoid_when_active`: Skip proactive starts if the group is already active.
- `initiative.active_threshold`: Number of recent inbound messages that counts as active.
- `initiative.recent_window`: Window in seconds used with `active_threshold`.
- `initiative.topic_sources`: Context sources used when deciding proactive prompts.
- `initiative.topics`: Optional low-risk topic seeds.
- `initiative.allowed_intents`: Allowed proactive intent labels.
- `initiative.forbidden_topics`: Topic labels the operator should avoid.
- `daemon.queue_path`: Local JSON queue file for pending daemon tasks. This should stay ignored by git.
- `daemon.lock_path`: Local single-instance lock file used by `daemon run`. This should stay ignored by git.
- `daemon.status_path`: Local status file for daemon state and heartbeat. This should stay ignored by git.
- `daemon.poll_interval`: Seconds between daemon polling/status ticks.
- `daemon.task_ttl`: Seconds before a pending task is considered stale.
- `daemon.max_pending`: Maximum queued pending tasks before new prompts are skipped or delayed.
- `daemon.max_task_context`: Maximum recent messages included in each queued task.
- `daemon.min_reply_interval`: Minimum seconds between successful daemon replies.
- `daemon.max_messages_per_hour`: Per-daemon hourly outbound message cap.
- `daemon.max_consecutive_replies`: Maximum consecutive account replies before another inbound message is required.

Unknown extra keys are preserved in `game suggest --json`, so operator-specific hints can be added without breaking older versions.

## Presets

Top-level `presets` can overlay any of these objects:

- `profile`
- `persona`
- `reply_policy`
- `initiative`
- `round`

Only one preset is selected per command. If you want to combine a persona with a social initiative setting, copy both into one named preset.

Common starter presets:

- `chat_normal`: ordinary group-chat behavior, low-frequency initiative.
- `chat_social`: more willing to reply and start light topics, still bounded.
- `friends_normal`: friend group behavior, casual but privacy-aware.
- `interest_social`: topic-centered interest group behavior.
- `public_group_safe`: conservative public-group behavior with initiative disabled.

Select a preset with:

```sh
tg-cli game suggest 5217114569 --preset chat_social --operator codex --json
tg-cli game round 5217114569 --duration 300 --preset chat_social
```

Merge order is deterministic:

- Built-in defaults.
- Top-level objects from config.
- `presets.NAME.*` overlays.
- Explicit `game round` command flags, such as `--duration` or `--max-replies`.

Unknown preset names fail before the command starts with a message listing available presets.

## Daemon Config

Daemon config is top-level and not part of `presets`. Use presets to choose `profile`, `persona`, `reply_policy`, `initiative`, and `round`; use `daemon` to control local queue files and long-running safety limits.

The expected v0.4 daemon commands are:

```sh
tg-cli daemon run 5217114569 --preset chat_social --duration 3600 --dry-run
tg-cli daemon next
tg-cli daemon next --json
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --dry-run
tg-cli daemon reply <task_id> "这把先看看队友怎么说" --json
tg-cli daemon skip <task_id> --reason "unclear context"
tg-cli daemon skip <task_id> --reason "unclear context" --json
tg-cli daemon status
tg-cli daemon status --json
tg-cli daemon stop
```

`daemon run` is a foreground single-chat process. It listens to one whitelisted chat, writes local pending tasks, updates status, and holds a single-instance lock. It does not call Codex, Claude, OpenAI, Anthropic, or any other model provider.

Codex/Claude operate the queue with `daemon next`, `daemon reply`, and `daemon skip`. A queued task should contain enough bounded context for the external operator to decide whether to reply naturally. `daemon reply` validates and queues the reply; the foreground `daemon run` process sends queued replies from the active Telethon session. This avoids opening Telegram from a second process while the daemon owns the session.

Default local daemon files:

- `.tg-cli-daemon-queue.json`
- `.tg-cli-daemon-status.json`
- `.tg-cli-daemon.lock`

These files are state, not source. Keep them ignored, do not commit them, and do not treat queue content as a durable database.

v0.4 non-goals:

- Multi-group hosting.
- Automatic model API calls.
- Background launchd/system service setup.
- Web UI.
- Unlimited or unaudited sending.

## Prompt Behavior

`tg-cli game suggest <chat>` returns `profile`, `persona`, `reply_policy`, `initiative`, selected `preset`, and recent messages. The CLI does not call an LLM or generate a reply.

`tg-cli game round <chat>` prints the resolved guidance once at startup. For each inbound message or merged batch it prints the incoming text, optionally recent context, and a compact instruction. Empty input skips the message. `/quit` stops the round.

When `initiative.enabled` is true, `game round` may prompt the operator after the group has been idle long enough. The operator still types the proactive message, and empty input skips it. This is not daemon mode and does not authorize automatic writes.

At exit, `game round` prints a report like:

```text
Round report:
duration=300.0s
elapsed=292.1s
received_batches=5
received_messages=7
prompted=3
sent_replies=2
sent_message_ids=101,102
skip_reasons={"empty_input": 1, "probability": 2}
avg_reply_chars=18.5
initiative_prompts=1
initiative_sent=1
initiative_skipped=0
initiative_sent_message_ids=103
initiative_skip_reasons={}
```

`sent_replies` counts successful operator replies. `initiative_sent` counts successful proactive starts. If long-reply splitting sends multiple Telegram messages for one typed reply, all Telegram message ids appear in `sent_message_ids`.

## Local Safety Filtering

Before any outbound text reaches `client.send_message`, the CLI checks `profile.forbidden_terms` and `profile.avoid_topics` with case-insensitive substring matching. If a match is found:

- `send` exits with a safety error and writes an audit record with the text hash and `blocked_forbidden_terms`.
- `game round` skips the reply, prints the matched profile term names, and writes the same style of audit record.

Audit records store text hashes and lengths, not raw message text.

Social Policy guidance does not bypass safety. Active or social presets still pass the same `allowed_chats` whitelist, global `pause`, forbidden-term checks, round rate limits, audit logging, and final round report.

Daemon guidance also does not bypass safety. `daemon reply` must pass whitelist, `pause`, forbidden-term checks, and queue audit before a reply can be queued. The running daemon enforces daemon-specific `min_reply_interval`, `max_messages_per_hour`, `max_consecutive_replies`, and final send audit before the reply reaches Telegram.

## Round Options

`game round` adds timing and human-likeness controls. These can be command flags or configured under `round`:

```sh
tg-cli game round 5217114569 --duration 120 --max-replies 10 \
  --quiet-context \
  --reply-probability 0.75 \
  --mention-reply-probability 1 \
  --random-delay-min 1 \
  --random-delay-max 4 \
  --skip-short-ack \
  --merge-window 2
```

- `--min-reply-interval`: Minimum seconds between successful round sends.
- `--end-buffer`: Stop prompting or skip sending near the round end.
- `--quiet-context`: Suppress repeated recent-context output.
- `--reply-probability`: Probability from `0` to `1` that a normal inbound message prompts for a reply.
- `--mention-reply-probability`: Probability override when inbound text appears to mention the logged-in account.
- `--max-replies`: Outbound Telegram message cap for the round. A split reply is skipped if all parts would exceed the remaining cap.
- `--random-delay-min` / `--random-delay-max`: Random delay before sending the first part of a typed reply.
- `--skip-short-ack`: Skip low-information messages such as `嗯`, `哈哈`, `真的假的`, and one-character acknowledgements.
- `--merge-window`: Collect rapid consecutive inbound messages before prompting once.
- `--split-long-replies`: Split long typed replies using `round.split_*`.

When `round.split_long_replies` is enabled, splitting prefers punctuation boundaries, falls back to character length, and caps parts with `round.split_max_parts`. Each part still goes through forbidden-term checks, end-buffer checks, and audit logging.
