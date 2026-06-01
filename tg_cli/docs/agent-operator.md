# Agent Operator Flow

`tg-cli` does not call a model provider. Codex, Claude, or another external agent is the operator. The CLI handles Telegram IO, safety checks, local config, rate limits, reply splitting, and audit logging.

## One-Shot Reply

Use this when the agent wants to inspect recent context, write one reply, and send it explicitly.

```sh
tg-cli game suggest 2400000996 --operator codex --limit 20 --json
tg-cli game suggest 2400000996 --preset chat_normal --operator codex --limit 20 --json
tg-cli game suggest 2400000996 --preset chat_social --operator codex --limit 20 --json
```

The JSON output includes:

- `chat`: resolved chat metadata.
- `operator`: the operator name used in the instruction.
- `preset`: selected preset name, or `null` when no preset was selected.
- `profile`: local tone, length, and sensitive-topic config.
- `persona`: generic account voice guidance.
- `reply_policy`: reply/skip guidance.
- `initiative`: bounded proactive-opening guidance.
- `messages`: recent Telegram messages in chronological order.
- `instruction`: a ready-to-use prompt for the external agent.

Social Policy has three layers:

- `persona`: 像谁. Use it as a generic example voice, not a real-person binding.
- `reply_policy`: 怎么接话. Use it to decide whether to answer, skip, ask briefly, or stay uncertain.
- `initiative`: 怎么主动开口. Use it only as bounded operator guidance for low-frequency proactive openings.

After choosing a reply, send it through the safety layer:

```sh
tg-cli send 2400000996 "这把感觉能打，先看看队友怎么说" --dry-run --json
tg-cli send 2400000996 "这把感觉能打，先看看队友怎么说" --yes --json
```

## Live Round

Use this when the agent should operate a short bounded chat session.

```sh
tg-cli game round 2400000996
tg-cli game round 2400000996 --preset public_group_safe
tg-cli game round 2400000996 --duration 300 --preset chat_social
```

The command reads `round.*` defaults from `tg_cli/.tg-cli.json`. When `--preset NAME` is present, it first overlays `presets.NAME.profile`, `presets.NAME.persona`, `presets.NAME.reply_policy`, `presets.NAME.initiative`, and `presets.NAME.round`; explicit command flags still win last. In each prompt:

- Empty input skips the current message.
- `/quit` stops the round.
- A typed reply is checked against pause, whitelist, forbidden terms, rate limits, end buffer, and optional long-reply splitting before sending.
- `--max-replies` is enforced as an outbound Telegram message cap; a split reply is skipped if it would exceed the remaining cap.

At the end of the round, read the structured report before deciding whether to start another round. It includes `duration`, `elapsed`, `received_batches`, `received_messages`, `prompted`, `sent_replies`, `sent_message_ids`, `skip_reasons`, `avg_reply_chars`, `initiative_prompts`, `initiative_sent`, `initiative_skipped`, `initiative_sent_message_ids`, and `initiative_skip_reasons`.

Recommended Social Policy smoke test:

```sh
tg-cli game round 2400000996 --duration 300 --preset chat_social
```

## Safety Expectations

- Keep target groups in `allowed_chats`.
- Start a new public-group test with `send --dry-run`.
- Keep `pause` available as the emergency stop.
- Do not run another `tg-cli` command with the same Telethon session while a live round is active.
- Do not reply to spam, gambling, private-data requests, money requests, or conflict escalation.
- Keep default initiative off or low-frequency. More active presets such as `chat_social` still go through whitelist, `pause`, forbidden-term checks, rate limits, audit logging, and the round report.
- Prefer short replies. Let `round.split_long_replies` split only when a longer response is natural.
