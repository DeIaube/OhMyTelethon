# elizaOS-Inspired Runtime

`tg-cli` keeps Telegram IO and safety local. Codex, Claude, or another external agent remains the operator. The runtime adds elizaOS-inspired character, room memory, actions, evaluators, and prompt assembly so group-chat behavior is easier to tune without adding model-provider coupling.

## Concepts

- Character: voice and behavior hints, similar to a small elizaOS character file.
- Room: one Telegram group or channel. Quota mode can select across rooms; daemon mode remains one room per foreground daemon.
- Memory: concise local summaries and facts. It does not store a raw message archive by default.
- Bad cases: local lessons from blocked/skipped behavior, stored without raw Telegram text and injected into future same-room tasks.
- Action: the kind of response Codex should consider, such as `reply`, `ask_open_question`, `light_joke`, or `skip`.
- Evaluator: deterministic local checks that decide whether to create an operator task, such as cooldown, short-ack skipping, and no-identity-claim guidance.

## Runtime Loop

```text
Telegram messages
  -> tg-cli context / daemon / quota
  -> local evaluators choose skip or task
  -> task includes profile, persona, reply_policy, initiative, character, memory, bad_cases
  -> Codex writes a reply, skips, or stores memory
  -> safety checks, pacing, audit
  -> Telethon sends, if allowed
```

`tg-cli` still does not call Codex, Claude, OpenAI, Anthropic, or any model provider. It prepares task context and enforces local IO safety.

## First Run

```sh
tg-cli game context CHAT_ID --preset chat_social --operator codex --json
tg-cli memory remember CHAT_ID --scope room --kind summary --text "这个群最近在聊晚上开黑。"
tg-cli quota start --chat CHAT_ID:5 --preset chat_social
tg-cli quota next --json
tg-cli quota reply TASK_ID "这话题可以，晚上看有没有人开。" --dry-run --json
tg-cli quota skip TASK_ID --reason "unsafe_or_stale_context" --json
```

Enable memory only in local ignored config:

```json
{
  "memory": {
    "enabled": true,
    "path": ".tg-cli-memory.sqlite3",
    "max_task_memories": 8
  }
}
```

## Character

`character` is prompt/task guidance:

```json
{
  "character": {
    "name": "小林",
    "bio": ["普通群友", "外向但不刷屏"],
    "lore": ["不声称真实身份或线下经历", "不编造事实"],
    "style": {
      "all": ["中文短句", "自然接话"],
      "chat": ["别像客服", "少解释"]
    },
    "topics": ["游戏", "日常闲聊"],
    "actions": ["reply", "ask_open_question", "light_joke", "skip"],
    "evaluators": ["not_everything", "cooldown", "skip_short_ack", "no_identity_claims"]
  }
}
```

The character name is a voice label, not permission to impersonate a real person.

## Safety

All sends still require allowed chats, pause state, forbidden-term checks, pacing limits, and audit records. Character config, actions, evaluators, and memory snippets do not grant extra send permission.

Memory notes should be short summaries, preferences, recurring topics, or explicit stable facts. Do not store raw private messages, credentials, phone numbers, or sensitive personal details.
