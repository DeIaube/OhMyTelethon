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

For a local starter file without credentials, see `tg_cli/docs/local-profile-template.json`.

## Fields

- `style`: Natural-language tone guidance for the external agent operator.
- `language`: Preferred reply language.
- `max_chars`: Suggested maximum reply length. This is prompt guidance, not a hard length rejection.
- `emoji_level`: Suggested emoji usage, such as `none`, `low`, `medium`, or `high`.
- `avoid_topics`: Sensitive topics to avoid. The CLI also treats these strings as outbound block terms.
- `forbidden_terms`: Exact sensitive terms that must not appear in outbound text.
- `reply_policy`: Guidance for when to reply, skip, or stay uncertain.

Extra profile keys are preserved in `game suggest --json` for operator-specific hints, but only the fields above are rendered in the compact round instruction.

## Prompt Behavior

`tg-cli game suggest <chat>` returns the full resolved `profile` in its JSON bundle and references it in the agent instruction. The CLI does not call an LLM or generate a reply.

`tg-cli game round <chat>` prints the resolved profile once at the start. For each inbound message it prints:

- The incoming message.
- Recent context, unless `--quiet-context` is set.
- A compact agent instruction containing the profile guidance.

The current operator still types the reply manually. Empty input skips the message. `/quit` stops the round.

## Local Safety Filtering

Before any outbound text reaches `client.send_message`, the CLI checks `profile.forbidden_terms` and `profile.avoid_topics` with case-insensitive substring matching. If a match is found:

- `send` exits with a safety error and writes an audit record with the text hash and `blocked_forbidden_terms`.
- `game round` skips the reply, prints the matched profile term names, and writes the same style of audit record.

Audit records continue to store text hashes and lengths, not raw message text.

## Round Safety Options

`game round` adds local timing controls. These can be passed as command flags or configured under `round` in `tg_cli/.tg-cli.json`.

```sh
tg-cli game round 5217114569 --duration 60 --max-replies 8 \
  --min-reply-interval 2 --end-buffer 5 --quiet-context
```

- `--min-reply-interval`: Minimum seconds between successful round sends.
- `--end-buffer`: Stop prompting, or skip a typed reply, if sending would happen too close to the round end.
- `--quiet-context`: Suppress repeated recent-context output for a compact one-minute operator loop.

## Human-Likeness Options

These options keep `game round` semi-automatic. The CLI still does not generate replies; it only decides whether to prompt the external operator and when to send the operator's typed reply.

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

- `--reply-probability`: Probability from `0` to `1` that a normal inbound message will prompt for a reply.
- `--mention-reply-probability`: Optional probability override when inbound text appears to mention the logged-in account by username or display name.
- `--random-delay-min` / `--random-delay-max`: Random delay range before sending the operator's typed reply.
- `--skip-short-ack`: Skip low-information messages such as `嗯`, `哈哈`, `真的假的`, and one-character acknowledgements.
- `--merge-window`: Wait for additional inbound messages for this many seconds, then prompt once for the merged batch.

Suggested first real-game settings:

```sh
tg-cli game round 5217114569 --duration 120 --max-replies 8 \
  --quiet-context --min-reply-interval 5 --end-buffer 8 \
  --reply-probability 0.7 --mention-reply-probability 1 \
  --random-delay-min 1 --random-delay-max 4 \
  --skip-short-ack --merge-window 2
```

Equivalent local config:

```json
{
  "round": {
    "duration": 120,
    "max_replies": 8,
    "quiet_context": true,
    "min_reply_interval": 5,
    "end_buffer": 8,
    "reply_probability": 0.75,
    "mention_reply_probability": 1,
    "random_delay_min": 1,
    "random_delay_max": 4,
    "skip_short_ack": true,
    "merge_window": 2,
    "split_long_replies": true,
    "split_max_chars": 28,
    "split_delay_min": 1,
    "split_delay_max": 2.5,
    "split_max_parts": 3
  }
}
```

With this config, the normal command can be shortened:

```sh
tg-cli game round 5217114569
```

## Splitting Long Replies

When `round.split_long_replies` is enabled, the external operator can type one longer reply and the CLI will split it into several Telegram messages. Splitting prefers punctuation boundaries, falls back to character length, and caps the number of parts with `round.split_max_parts`.

Each split part still goes through:

- `profile.forbidden_terms` / `profile.avoid_topics` filtering.
- `end_buffer` checks before sending.
- Audit logging with text hash and length only.

Split timing:

- `round.random_delay_min` / `round.random_delay_max` applies before the first sent part.
- `round.split_delay_min` / `round.split_delay_max` applies between later parts.
