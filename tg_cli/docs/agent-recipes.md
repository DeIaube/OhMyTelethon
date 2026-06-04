# tg-cli Agent Recipes

This is the short operator runbook for agents using `tg-cli`. The CLI owns
Telegram IO, local safety checks, queue/quota state, and audit logging. The
agent decides what to say or skip.

Use placeholder values in examples until you have confirmed the local config:

```sh
CHAT_ID=-1001234567890
OTHER_CHAT_ID=-1009876543210
TASK_ID=task_000000
USER_QUERY='public_username_or_display_name'
INLINE_BOT='@inline_bot_placeholder'
```

Never paste API hashes, phone numbers, 2FA passwords, bot tokens, session
bytes, raw Telegram objects, access hashes, or real private chat names into
commands, docs, logs, or handoffs.

## Startup Safety Checks

Run these before operating a live account:

```sh
sed -n '1,220p' AGENTS.md
sed -n '1,260p' tg_cli/AGENTS.md
git status --short
tg-cli capabilities --json
tg-cli doctor agent --json
tg-cli config inspect --json
tg-cli auth status --json
tg-cli me --json
tg-cli status --json
```

If two agents or two accounts are active, use one config per account and verify
the runtime files do not overlap:

```sh
tg-cli --config tg_cli/accounts/account-a.json config doctor --other-config tg_cli/accounts/account-b.json --json
```

Safety notes:

- Live writes are only allowed to chats in `allowed_chats`.
- `tg-cli pause` is the global emergency stop; `tg-cli resume` re-enables writes.
- Avoid concurrent Telegram-using commands on the same Telethon session file.
- Do not commit local runtime files such as `*.session`, `.tg-cli*.json`,
  `.tg-cli*.lock`, quota state, daemon state, bad-case files, audit logs, or
  `tg_cli/downloads/`.

## Discover Capabilities

Start with help and existing docs instead of guessing command shape:

```sh
tg-cli capabilities --json
tg-cli doctor agent --json
tg-cli --help
tg-cli messages --help
tg-cli quota --help
tg-cli daemon --help
tg-cli admin --help
tg-cli bot --help
```

Useful local references:

```sh
sed -n '1,280p' tg_cli/README.md
sed -n '1,260p' tg_cli/docs/agent-operator.md
sed -n '1,220p' tg_cli/docs/profile-config.md
```

Safety notes:

- `capabilities --json` is the machine-readable command catalog for agents.
- `doctor agent --json` is a credential-free local preflight; it does not
  connect to Telegram.
- `tg-cli` wraps Telethon high-level methods; do not add or rely on raw TL
  request passthrough.
- JSON rows must stay sanitized: no phone numbers, access hashes, raw TL
  dictionaries, session data, downloaded bytes, or base64 content.

## Inspect Chats And Context

Use read-only commands to resolve the target and understand the room before any
reply:

```sh
tg-cli groups --kind supergroup --json
tg-cli dialogs --limit 50 --json
tg-cli entity resolve "$CHAT_ID" --json
tg-cli members list "$CHAT_ID" --filter admins --limit 50 --json
tg-cli members search "$CHAT_ID" "$USER_QUERY" --json
tg-cli profile show "$USER_QUERY" --chat "$CHAT_ID" --json
tg-cli messages history "$CHAT_ID" --limit 50 --json
tg-cli messages search "recent topic" --chat "$CHAT_ID" --limit 20 --json
tg-cli game context "$CHAT_ID" --limit 200 --preset public_group_safe --operator codex --json
tg-cli game suggest "$CHAT_ID" --preset chat_social --operator codex --json
tg-cli memory list "$CHAT_ID" --json
tg-cli badcase list --chat "$CHAT_ID" --json
```

Safety notes:

- `game context` and `game suggest` do not call a model provider.
- Treat `persona`, `reply_policy`, `initiative`, `character`, `memory`, and
  `bad_cases` as guidance only. They do not grant send permission.
- Skip instead of replying when context is unsafe, stale, too unclear, spammy,
  self-heavy, or not natural to join.

## Safe Send Flow

Always dry-run first, review the output, then perform one explicit live send
only if the target, text, and timing are still correct:

```sh
tg-cli messages send "$CHAT_ID" "Short natural reply from the operator." --dry-run --json
tg-cli messages history "$CHAT_ID" --limit 5 --json
tg-cli messages send "$CHAT_ID" "Short natural reply from the operator." --yes --json
```

Legacy form:

```sh
tg-cli send "$CHAT_ID" "Short natural reply from the operator." --dry-run --json
tg-cli send "$CHAT_ID" "Short natural reply from the operator." --yes --json
```

Reply, schedule, media, and management examples:

```sh
tg-cli messages send "$CHAT_ID" "Replying to this exact message." --reply-to 12345 --parse-mode none --dry-run --json
tg-cli messages send-file "$CHAT_ID" ./local-image.png --caption "Image caption." --dry-run --json
tg-cli messages edit "$CHAT_ID" 12345 "Corrected text." --dry-run --json
tg-cli messages delete "$CHAT_ID" 12345 --dry-run --json
tg-cli messages pin "$CHAT_ID" 12345 --dry-run --json
tg-cli messages action "$CHAT_ID" typing --duration 2 --dry-run --json
```

Safety notes:

- Live writes require allowlist, unpaused state, forbidden-term checks,
  confirmation or `--yes`, and audit logging.
- Only operate on explicit message ids. Do not use broad deletion, unpin-all, or
  hidden bulk mutation patterns.
- A dry-run validates and audits without mutating Telegram.

## Quota Step Flow

Quota mode is a local target-count flow for authorized, informed test groups.
It does not schedule time windows and does not generate reply text.

Start from a named scenario when available:

```sh
tg-cli scenario list --json
tg-cli scenario show authorized-chat-social-150 --json
tg-cli scenario start authorized-chat-social-150 --json
```

For an ad hoc run:

```sh
tg-cli quota start --chat "$CHAT_ID:50" --chat "$OTHER_CHAT_ID:50" --preset chat_social --json
```

Operator loop:

```sh
tg-cli quota status --json
tg-cli quota step --json
tg-cli quota step --reply "Operator-written reply after reading the task." --json
tg-cli quota step --reply "Operator-written reply after reading the task." --send --json
tg-cli quota step --skip-reason "unsafe_or_stale_context" --json
tg-cli quota watch --interval 5 --count 12 --json
tg-cli quota status --json
```

Primitive form when you want explicit task ids:

```sh
tg-cli quota next --json
tg-cli quota reply "$TASK_ID" "Operator-written reply after reading the task." --dry-run --json
tg-cli quota reply "$TASK_ID" "Operator-written reply after reading the task." --json
tg-cli quota skip "$TASK_ID" --reason "unsafe_or_stale_context" --json
```

Stop early when needed:

```sh
tg-cli quota stop --json
```

Safety notes:

- `quota step --reply` defaults to dry-run and never increments counts.
- `quota step --reply ... --send` dry-runs first, then performs the explicit
  live send through stale-context, allowlist, pause, forbidden-term, pacing, and
  audit checks.
- Count only successful Telegram message parts. Split replies count by actual
  sent parts. Dry-runs do not count.
- Treat target counts as caps, not a reason to send filler. Use `quota skip`
  when the natural action is to wait or skip.
- Stop claiming tasks when a target is reached, when all targets are done, or
  when stop conditions such as direct moderation warning, spam complaint,
  repeated stale context, hourly limit, or unsafe-context ratio fire.

## Daemon Task Flow

Daemon mode is one foreground daemon for one whitelisted chat. It writes local
tasks; the external agent claims tasks and decides reply or skip. The daemon
does not call a model provider and is not a background service.

Start the daemon in a dedicated terminal:

```sh
tg-cli daemon run "$CHAT_ID" --preset chat_social --duration 3600 --dry-run
```

Work the queue from another operator shell:

```sh
tg-cli daemon status --json
tg-cli daemon next --peek --json
tg-cli daemon next --json
tg-cli daemon reply "$TASK_ID" "Operator-written reply after reading the task." --dry-run --json
tg-cli daemon reply "$TASK_ID" "Operator-written reply after reading the task." --json
tg-cli daemon skip "$TASK_ID" --reason "unclear_context" --json
tg-cli daemon status --json
tg-cli daemon stop
```

Safety notes:

- `daemon next` claims a lease. Use `--peek` only for read-only inspection.
- `daemon reply --dry-run` validates and audits without queueing a live send.
- The foreground daemon owns Telegram IO while running; queue commands should
  not open Telegram directly.
- Replies still pass allowlist, pause, forbidden terms, daemon pacing,
  stale queued-reply expiration, minimum reply length, final send audit, and
  single-instance lock checks.
- Use `daemon skip` for spam, private data, conflict, stale context, low value,
  self-heavy context, or anything unnatural.

## Downloads

Downloads write bytes to local files but command output must only contain paths
and shallow metadata.

```sh
tg-cli messages history "$CHAT_ID" --media-only --limit 20 --json
tg-cli downloads media "$CHAT_ID" 12345 --output-dir tg_cli/downloads --json
tg-cli profile photos "$USER_QUERY" --limit 5 --json
tg-cli downloads profile-photo "$USER_QUERY" --output-dir tg_cli/downloads --json
```

Safety notes:

- Download only explicit media or profile-photo targets.
- Do not print, serialize, or commit downloaded bytes or base64 content.
- Keep `tg_cli/downloads/` local and ignored.

## Admin Read And Write

Read admin state first:

```sh
tg-cli admin log "$CHAT_ID" --limit 20 --json
tg-cli admin permissions show "$CHAT_ID" --json
tg-cli admin permissions show "$CHAT_ID" --user "$USER_QUERY" --json
tg-cli admin stats "$CHAT_ID" --json
```

Dry-run before any moderation mutation:

```sh
tg-cli admin permissions set "$CHAT_ID" --user "$USER_QUERY" --disable send_messages --dry-run --json
tg-cli admin permissions set "$CHAT_ID" --user "$USER_QUERY" --disable send_messages --yes --json
tg-cli admin kick "$CHAT_ID" "$USER_QUERY" --dry-run --json
tg-cli admin ban "$CHAT_ID" "$USER_QUERY" --dry-run --json
tg-cli admin unban "$CHAT_ID" "$USER_QUERY" --dry-run --json
tg-cli admin promote "$CHAT_ID" "$USER_QUERY" --enable delete_messages --dry-run --json
tg-cli admin demote "$CHAT_ID" "$USER_QUERY" --dry-run --json
```

Safety notes:

- Admin writes are explicit, high-impact operations. Require a clear operator
  reason, exact chat, exact user, dry-run review, and live confirmation.
- Do not add mass moderation, raw permission passthrough, or range operations.

## Drafts

Draft commands use the same write safety gates before mutating or sending:

```sh
tg-cli drafts list "$CHAT_ID" --json
tg-cli drafts set "$CHAT_ID" "Draft text for later review." --dry-run --json
tg-cli drafts set "$CHAT_ID" "Draft text for later review." --yes --json
tg-cli drafts send "$CHAT_ID" --dry-run --json
tg-cli drafts send "$CHAT_ID" --yes --json
tg-cli drafts delete "$CHAT_ID" --dry-run --json
```

Safety notes:

- Listing is read-only; setting, sending, and deleting drafts are writes.
- Review the current chat tail before sending an old draft.

## Inline Bot

Inspect inline results first, then dry-run the selected result:

```sh
tg-cli bot inline-query "$INLINE_BOT" "Example inline query" --chat "$CHAT_ID" --json
tg-cli bot inline-send "$INLINE_BOT" "Example inline query" "$CHAT_ID" --index 0 --dry-run --json
tg-cli bot inline-send "$INLINE_BOT" "Example inline query" "$CHAT_ID" --index 0 --yes --json
```

Safety notes:

- `inline-query` is read-only; `inline-send` is a write.
- Confirm the selected `--index` still matches the intended result before live
  send.
- Inline sends still require allowlist, pause, forbidden-term checks where
  applicable, confirmation or `--yes`, and audit logging.

## Badcase Review

Bad cases are local lessons from blocked or skipped behavior. Review them before
replying, especially for daemon and quota tasks:

```sh
tg-cli badcase list --chat "$CHAT_ID" --json
tg-cli badcase list --chat "$CHAT_ID" --reason stale_context --json
tg-cli badcase export --chat "$CHAT_ID" --json
```

Safety notes:

- Bad-case records store hashes, lengths, reasons, and lessons, not raw Telegram
  text or chat titles.
- Treat bad cases as constraints for future operators, not permission to bypass
  safety gates.
- Use the CLI/runtime bad-case helpers for new automated captures; do not hand
  edit ignored JSONL state as source.

## Documentation Update Rule

When CLI behavior, commands, safety rules, config, prompt/task payloads, runtime
file layout, or ignored local state changes, update documentation in the same
change:

```sh
sed -n '1,260p' tg_cli/AGENTS.md
sed -n '1,280p' tg_cli/README.md
sed -n '1,260p' tg_cli/docs/agent-operator.md
sed -n '1,260p' tg_cli/docs/agent-recipes.md
```

Update `tg_cli/AGENTS.md` for agent rules and safety invariants, `tg_cli/README.md`
for command reference, `tg_cli/agent_discovery.py` when command metadata or
safety classification changes, and the relevant `tg_cli/docs/` page for
operator flow. If a recipe changes, update this file too. Keep Telethon library
changes separate from `tg_cli/` local automation changes.
