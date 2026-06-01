# tg-cli Profile Config

`profile` is optional in `tg_cli/.tg-cli.json`. Missing fields are filled with defaults, so older configs continue to work.

Example:

```json
{
  "profile": {
    "style": "自然、简短、像普通群聊，不要长篇解释。",
    "language": "中文",
    "max_chars": 80,
    "emoji_level": "low",
    "avoid_topics": ["隐私", "账号信息"],
    "forbidden_terms": ["示例禁用词"],
    "reply_policy": "只在有明确可接话的内容时回复；不确定时跳过；不要编造事实或冒充他人。"
  }
}
```

## Fields

- `style`: Natural-language tone guidance for Codex.
- `language`: Preferred reply language.
- `max_chars`: Suggested maximum reply length. This is prompt guidance, not a hard length rejection.
- `emoji_level`: Suggested emoji usage, such as `none`, `low`, `medium`, or `high`.
- `avoid_topics`: Sensitive topics to avoid. The CLI also treats these strings as outbound block terms.
- `forbidden_terms`: Exact sensitive terms that must not appear in outbound text.
- `reply_policy`: Guidance for when to reply, skip, or stay uncertain.

Extra profile keys are preserved in `game suggest --json` for operator-specific hints, but only the fields above are rendered in the compact round instruction.

## Prompt Behavior

`tg-cli game suggest <chat>` returns the full resolved `profile` in its JSON bundle and references it in the Codex instruction. The CLI does not call an LLM or generate a reply.

`tg-cli game round <chat>` prints the resolved profile once at the start. For each inbound message it prints:

- The incoming message.
- Recent context, unless `--quiet-context` is set.
- A compact Codex instruction containing the profile guidance.

The current operator still types the reply manually. Empty input skips the message. `/quit` stops the round.

## Local Safety Filtering

Before any outbound text reaches `client.send_message`, the CLI checks `profile.forbidden_terms` and `profile.avoid_topics` with case-insensitive substring matching. If a match is found:

- `send` exits with a safety error and writes an audit record with the text hash and `blocked_forbidden_terms`.
- `game round` skips the reply, prints the matched profile term names, and writes the same style of audit record.

Audit records continue to store text hashes and lengths, not raw message text.

## Round Safety Options

`game round` adds local timing controls:

```sh
tg-cli game round 5217114569 --duration 60 --max-replies 8 \
  --min-reply-interval 2 --end-buffer 5 --quiet-context
```

- `--min-reply-interval`: Minimum seconds between successful round sends.
- `--end-buffer`: Stop prompting, or skip a typed reply, if sending would happen too close to the round end.
- `--quiet-context`: Suppress repeated recent-context output for a compact one-minute operator loop.
