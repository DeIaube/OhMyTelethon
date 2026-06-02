# Scenario Runs

Scenario runs are operator handoffs for long quota tests. They are intended for a known account, a known authorized group, a known persona or preset, and an explicit message target such as 150 successful Telegram message parts.

Use scenarios only in groups where participants and operators are authorized and informed about the test. A scenario is not permission to bypass Telegram/platform risk controls, hide automation, evade detection, impersonate a real person, or ignore CLI safety gates. All sends still pass `allowed_chats`, global `pause`, forbidden terms, daemon pacing, quota skip, stale preflight, audit logging, and bad-case guidance.

## Config Fields

Keep scenario config local and credential-free. Recommended fields:

```json
{
  "name": "authorized-chat-social-150",
  "account": "local-session-label",
  "chat_id": 2400000996,
  "persona": "ordinary group member voice; no real-person impersonation",
  "preset": "chat_social",
  "target_messages": 150,
  "dry_run_first": true,
  "max_runtime_minutes": 240,
  "stop_on": [
    "target_reached",
    "manual_stop",
    "moderation_warning",
    "spam_complaint",
    "too_many_stale_context",
    "hourly_limit",
    "unsafe_context_ratio"
  ]
}
```

Field notes:

- `name`: Human-readable run label for handoff and reports.
- `account`: Local account/session label. Do not store phone numbers, API hashes, session bytes, or credentials here.
- `chat_id`: The authorized test group id. It must already be in `allowed_chats`.
- `persona`: Operator-facing voice guidance. It must not bind the account to a real person or request deceptive behavior.
- `preset`: Existing profile preset, usually `chat_normal` or `chat_social`.
- `target_messages`: Successful sent Telegram message parts for the run. The common long test target is `150`.
- `dry_run_first`: Require the first suitable quota reply to use `--dry-run --json` before any live send.
- `max_runtime_minutes`: Wall-clock safety cap owned by the operator or scheduler.
- `stop_on`: Stop conditions the operator must monitor.

## Operator Loop

Recommended long-run loop:

```sh
tg-cli scenario start authorized-chat-social-150 --json

tg-cli quota status --json
tg-cli quota next --json
tg-cli quota reply <task_id> "自然、相关、不过度的一句回复" --dry-run --json
tg-cli quota reply <task_id> "自然、相关、不过度的一句回复" --json
tg-cli quota skip <task_id> --reason "unsafe_or_stale_context" --json
tg-cli quota status --json
```

Repeat `quota status`, `quota next`, and either `quota reply` or `quota skip` until the target is reached, a stop condition fires, or the operator manually stops the run. At target reached, stop claiming new tasks and record the final report from `quota status --json`; use `tg-cli quota stop` only when the run must be stopped before completion.

## Stop Conditions

Use these `stop_on` labels in handoffs and reports:

- `target_reached`: `sent_count` reached `target_messages`; stop automatically and report.
- `manual_stop`: The operator, owner, or scheduler requested stop.
- `moderation_warning`: A warning names, replies to, or clearly mentions the logged-in account.
- `spam_complaint`: A participant complains about the account's messages as spam or unwanted volume.
- `too_many_stale_context`: Repeated `stale_context` skips show the operator cannot keep up with the group safely.
- `hourly_limit`: `daemon.max_messages_per_hour` or equivalent pacing cap blocks more sends.
- `unsafe_context_ratio`: Too many tasks are unsafe, unclear, spammy, or otherwise unsuitable compared with natural reply opportunities.

## Handoff Rules

Every agent taking over a scenario must:

- Read `tg_cli/AGENTS.md` before acting.
- Verify the scenario is for an authorized, informed test group and an allowed chat.
- Run a dry-run quota reply before the first live reply in a new scenario, group, or preset.
- Use `quota skip` for unsafe, stale, unclear, low-value, self-heavy, or unnatural contexts.
- Never send filler just to reach `150` or any other target.
- Stop automatically when `target_messages` is reached and include final `quota status --json` counts in the handoff report.
- Keep all normal safety gates intact: allowlist, `pause`, forbidden terms, daemon pacing, quota skip, stale preflight, audit logs, and bad-case constraints.
