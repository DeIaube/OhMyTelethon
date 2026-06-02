# tg-cli Profile Config

`tg_cli/.tg-cli.json` is optional and ignored by git. Missing fields are filled with defaults in `tg_cli.config`, so older configs continue to work.

The current game profile has four layers:

- `profile`: basic tone, language, length, and local safety terms.
- `persona`: 像谁. A generic or fictional voice for the account, not a real-person binding.
- `reply_policy`: 怎么接话. When to reply, when to skip, and how to avoid over-answering.
- `initiative`: 怎么主动开口. Whether the account may start a topic, how often, and under which bounded triggers.
- `character`: elizaOS-inspired voice, action, example, topic, and evaluator hints.
- `memory`: optional local SQLite room/user notes for Codex task context.

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
    "claim_ttl": 300,
    "max_pending": 20,
    "max_task_context": 8,
    "min_reply_interval": 6,
    "max_messages_per_hour": 20,
    "max_consecutive_replies": 2
  },
  "quota": {
    "state_path": ".tg-cli-quota-state.json"
  },
  "memory": {
    "enabled": false,
    "path": ".tg-cli-memory.sqlite3",
    "max_task_memories": 8
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
  "character": {
    "name": "小林",
    "bio": ["普通群友", "外向但不刷屏"],
    "lore": ["不声称真实身份或线下经历", "不编造事实"],
    "style": {
      "all": ["中文短句", "自然接话"],
      "chat": ["别像客服", "少解释"]
    },
    "topics": ["游戏", "日常闲聊", "周末安排"],
    "adjectives": ["社交", "轻松", "会接梗"],
    "message_examples": [],
    "actions": ["reply", "ask_open_question", "light_joke", "skip"],
    "evaluators": ["not_everything", "cooldown", "skip_short_ack", "no_identity_claims"]
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
    "min_starts": 0,
    "min_start_after": 60,
    "avoid_when_active": true,
    "active_threshold": 6,
    "recent_window": 300,
    "topic_sources": ["recent_messages", "preset_topics"],
    "topics": ["最近有啥好玩的", "这个有人试过吗"],
    "allow_topic_shift": false,
    "topic_shift_when": [],
    "topic_shift_style": "",
    "fallback_topics": [],
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
- `character.name`: Short character name used in operator prompts. This is a voice label, not permission to impersonate a real person.
- `character.bio`: Short background/voice notes for the character.
- `character.lore`: Behavioral constraints and safety boundaries such as no fabricated offline experience.
- `character.style.all`: General style rules.
- `character.style.chat`: Chat-specific style rules.
- `character.topics`: Safe topic seeds.
- `character.adjectives`: Voice adjectives used as prompt hints.
- `character.message_examples`: Optional elizaOS-like examples. Keep these credential-free and non-private.
- `character.actions`: Allowed action hints such as `reply`, `ask_open_question`, `light_joke`, and `skip`.
- `character.evaluators`: Deterministic/local evaluator hints such as `not_everything`, `cooldown`, `skip_short_ack`, and `no_identity_claims`.
- `reply_policy.group_type`: Context label such as `chat`, `friends`, `interest`, or `public_large_group`.
- `reply_policy.reply_threshold`: Guidance threshold from `0` to `1`; lower is more willing to reply.
- `reply_policy.prefer_reply_when`: Situations where replying is natural.
- `reply_policy.skip_when`: Situations where skipping is preferred.
- `reply_policy.style_rules`: Reply-shape rules, usually short strings.
- `reply_policy.conversation_rules`: Conversation-level rules such as anti-spam or anti-fabrication.
- `initiative.enabled`: Whether bounded proactive prompts are allowed during `game round` and `daemon run`.
- `initiative.idle_after`: Seconds of group idleness before a proactive prompt can appear.
- `initiative.cooldown`: Seconds between proactive starts.
- `initiative.max_starts`: Maximum proactive starts in one bounded run.
- `initiative.min_starts`: Minimum proactive task floor for the selected run, capped by `max_starts`. Use `0` for no floor.
- `initiative.min_start_after`: Seconds after run start when the floor can trigger, even if the group is active.
- `initiative.avoid_when_active`: Skip proactive starts if the group is already active.
- `initiative.active_threshold`: Number of recent inbound messages that counts as active.
- `initiative.recent_window`: Window in seconds used with `active_threshold`.
- `initiative.topic_sources`: Context sources used when deciding proactive prompts.
- `initiative.topics`: Optional low-risk topic seeds.
- `initiative.allow_topic_shift`: Whether a proactive prompt may start a new safe topic when recent context is unsafe or unjoinable.
- `initiative.topic_shift_when`: Situation labels where topic shifting is preferred over engaging the latest context.
- `initiative.topic_shift_style`: Natural-language guidance for how to change topics.
- `initiative.fallback_topics`: Safe topic seeds used when shifting away from ads, spam, grey-area, or unclear context.
- Inbound ads, traffic redirection, and adult-service solicitations are skip-only signals. They should make the agent ignore that message, not enter a risk cooldown.
- `initiative.allowed_intents`: Allowed proactive intent labels.
- `initiative.forbidden_topics`: Topic labels the operator should avoid.
- `daemon.queue_path`: Local JSON queue file for pending daemon tasks. This should stay ignored by git.
- `daemon.lock_path`: Local single-instance lock file used by `daemon run`. This should stay ignored by git.
- `daemon.status_path`: Local status file for daemon state and heartbeat. This should stay ignored by git.
- `daemon.poll_interval`: Seconds between daemon polling/status ticks.
- `daemon.task_ttl`: Seconds before a pending or queued reply task is considered stale.
- `daemon.claim_ttl`: Seconds before a `daemon next` task claim can be reclaimed by another operator.
- `daemon.max_pending`: Maximum queued pending tasks before new prompts are skipped or delayed.
- `daemon.max_task_context`: Maximum recent messages included in each queued task.
- `daemon.min_reply_interval`: Minimum seconds between successful daemon replies.
- `daemon.max_messages_per_hour`: Per-daemon hourly outbound message cap.
- `daemon.max_consecutive_replies`: Maximum consecutive account replies before another inbound message is required.
- `quota.state_path`: Local JSON state file for the active quota run. The default is `.tg-cli-quota-state.json` under `tg_cli/`; keep it, its lock file, and atomic-write temp files ignored by git.
- `memory.enabled`: Whether `game suggest`, `daemon`, and `quota` include local memory snippets. Default: `false`.
- `memory.path`: Local SQLite database for room/user memories. Default: `.tg-cli-memory.sqlite3` under `tg_cli/`; keep it and SQLite sidecar files ignored by git.
- `memory.max_task_memories`: Maximum memory snippets included in one operator task.

Unknown extra keys are preserved in `game suggest --json`, so operator-specific hints can be added without breaking older versions.

## Presets

Top-level `presets` can overlay any of these objects:

- `profile`
- `persona`
- `reply_policy`
- `initiative`
- `round`
- `daemon` non-path rate/queue controls
- `character`

Only one preset is selected per command. If you want to combine a persona with a social initiative setting, copy both into one named preset. `quota start --preset NAME` uses the same resolved `profile`, `persona`, `reply_policy`, `initiative`, and `character` guidance when creating quota tasks. Preset-level `daemon` may tune non-path controls such as `min_reply_interval`, `max_messages_per_hour`, and `max_consecutive_replies`; keep `queue_path`, `lock_path`, and `status_path` at the top level.

Common starter presets:

- `chat_normal`: ordinary group-chat behavior, low-frequency initiative.
- `chat_social`: more active social behavior, willing to reply to concrete harmless openings and, when enabled, casually shift to safe fallback topics if the latest context is ads, spam, grey-area, or unjoinable. It is still bounded by caps.
- `friends_normal`: friend group behavior, casual but privacy-aware.
- `interest_social`: topic-centered interest group behavior.
- `public_group_safe`: conservative public-group behavior with initiative disabled.

Select a preset with:

```sh
tg-cli game suggest 5217114569 --preset chat_social --operator codex --json
tg-cli game round 5217114569 --duration 300 --preset chat_social
tg-cli quota start --chat 111111111:120 --chat 222222222:300 --preset chat_social
```

Merge order is deterministic:

- Built-in defaults.
- Top-level objects from config.
- `presets.NAME.*` overlays.
- Explicit `game round` command flags, such as `--duration` or `--max-replies`.

Unknown preset names fail before the command starts with a message listing available presets.

## Daemon Config

Daemon path config is top-level. Presets may overlay non-path daemon rate and queue controls, but `queue_path`, `lock_path`, and `status_path` stay top-level so `daemon next`, `daemon reply`, `daemon skip`, and `daemon status` operate on the same local files.

The expected v0.4 daemon commands are:

```sh
tg-cli daemon run 5217114569 --preset chat_social --duration 3600 --dry-run
tg-cli daemon next
tg-cli daemon next --peek
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

Codex/Claude operate the queue with `daemon next`, `daemon reply`, and `daemon skip`. `daemon next` claims a task lease by default so another operator does not receive the same task; use `daemon next --peek` only for read-only inspection. A queued task should contain enough bounded context for the external operator to decide whether to reply naturally. `daemon reply --dry-run` validates and audits without consuming the task. `daemon reply` without dry-run validates and queues the reply; the foreground `daemon run` process sends queued replies from the active Telethon session. When `round.split_long_replies` is enabled, one natural reply can be split into short Telegram messages only when each part adds content. This avoids opening Telegram from a second process while the daemon owns the session.

Default local daemon files:

- `.tg-cli-daemon-queue.json`
- `.tg-cli-daemon-queue.json.lock`
- `.tg-cli-daemon-status.json`
- `.tg-cli-daemon.lock`

These files are state, not source. Keep them ignored, do not commit them, and do not treat queue content as a durable database.

v0.4 non-goals:

- Multi-group hosting.
- Automatic model API calls.
- Background launchd/system service setup.
- Web UI.
- Unlimited or unaudited sending.

## Quota Config

Quota mode is for Codex-automation-triggered target runs. `tg-cli` does not schedule the daily start time; Codex automation, cron, launchd, or another external scheduler starts the run, and `tg-cli quota` manages local task selection, Telegram sending, counting, and stop behavior.

Minimal local config:

```json
{
  "allowed_chats": [111111111, 222222222],
  "quota": {
    "state_path": ".tg-cli-quota-state.json"
  }
}
```

Typical daily trigger command:

```sh
tg-cli quota start --chat 111111111:120 --chat 222222222:300 --preset chat_social
```

Operator commands:

```sh
tg-cli quota status --json
tg-cli quota next --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --dry-run --json
tg-cli quota reply <task_id> "这把先看看队友怎么说" --json
tg-cli quota stop
```

`quota.state_path` stores local runtime state for one active quota run: run id, run status, per-chat targets, sent counts, task ids, and sent Telegram message ids. It may include bounded recent context in tasks. Keep `.tg-cli-quota-state.json`, its lock file, and atomic-write temp files ignored, do not commit them, and do not put credentials in them.

Quota counting rules:

- Count only successful Telegram sends.
- Count split replies by actual sent Telegram message parts.
- Do not increment counts for `--dry-run`.
- Apply `daemon.min_reply_interval`, `daemon.max_messages_per_hour`, and `daemon.max_consecutive_replies` to quota replies.
- Mark a target `done` when `sent_count` reaches `target_count`.
- Mark the run `done` when all targets are done.
- Mark the run `stopped` when `quota stop` is requested. In-flight sends that already passed the final safety gate may still be counted if Telegram accepted them.

Quota safety is the same outbound safety stance as the rest of the CLI: target chats must be in `allowed_chats`, `pause` blocks `quota reply`, forbidden terms are checked before `client.send_message`, daemon pacing limits apply, and audit logging records hashes and lengths instead of raw message text.

## Memory Config

Memory is local and opt-in. It is meant for short, stable notes that help Codex avoid asking the same thing repeatedly or missing recurring group context. It should not be used as a raw chat archive.

```json
{
  "memory": {
    "enabled": true,
    "path": ".tg-cli-memory.sqlite3",
    "max_task_memories": 8
  }
}
```

Operator-authored notes:

```sh
tg-cli memory remember 5217114569 --scope room --kind summary --text "这个群最近在聊晚上开黑。"
tg-cli memory remember 5217114569 --scope user --sender-id 123456 --sender-name "阿强" --kind preference --text "阿强常接游戏话题。"
tg-cli memory list 5217114569 --json
```

Store summaries, preferences, recurring topics, and explicitly provided stable facts. Do not store private raw messages, credentials, phone numbers, or sensitive personal details.

## Prompt Behavior

`tg-cli game context <chat> --limit 200 --preset NAME --operator codex --json` returns a larger entry warmup summary before daemon or longer live tests. It includes resolved `profile`, `persona`, `reply_policy`, `initiative`, active speakers, local keyword/topic signals, notice/bot messages, recent questions, guidance, and a bounded message tail. The CLI does not call an LLM or generate a reply.

`tg-cli game suggest <chat>` returns `profile`, `persona`, `reply_policy`, `initiative`, selected `preset`, and recent messages. The CLI does not call an LLM or generate a reply.

`tg-cli game round <chat>` prints the resolved guidance once at startup. For each inbound message or merged batch it prints the incoming text, optionally recent context, and a compact instruction. Empty input skips the message. `/quit` stops the round.

`tg-cli quota next --json` returns one quota task with bounded context and the resolved guidance selected at `quota start`. The CLI still does not generate a reply; the external operator writes the reply and sends it with `quota reply`.

When `initiative.enabled` is true, `game round` may prompt the operator after the group has been idle long enough. The operator still types the proactive message, and empty input skips it. This is not daemon mode and does not authorize automatic writes.

When `initiative.allow_topic_shift` is true, proactive prompts should not engage unsafe recent context directly. Instead, the operator may start one short neutral fallback topic from `initiative.fallback_topics` and avoid explaining the subject change. This is intended for social presets that should not go silent just because the latest messages are ads, spam, or otherwise unjoinable.

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

Daemon guidance also does not bypass safety. `daemon reply` must pass whitelist, `pause`, forbidden-term checks, and queue audit before a reply can be queued. The running daemon enforces daemon-specific `min_reply_interval`, `max_messages_per_hour`, `max_consecutive_replies`, stale queued-reply expiration, held rate-limit retry state, split-part checks, and final send audit before any reply part reaches Telegram.

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

In addition to prompt guidance, `tg-cli` applies deterministic inbound skips before asking the operator for a reply. Messages containing AI/robot accusations, anti-spam or ban warnings, adult-service solicitations, non-consensual recording, underage or age-risk language, ads, or grey-area account/black-market topics are skipped locally.

When `round.split_long_replies` is enabled, splitting prefers punctuation boundaries, falls back to character length, and caps parts with `round.split_max_parts`. Splitting is for naturally separate thoughts, not for raising message count. Each part still goes through forbidden-term checks and audit logging; `game round` also applies end-buffer checks.
