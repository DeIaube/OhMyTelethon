# Telethon CLI Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Expand `tg-cli` so every practical Telethon high-level client method has a safe CLI wrapper, while keeping raw Telegram credentials, access hashes, media bytes, and unsafe write behavior out of command output.

**Architecture:** Keep Telegram IO in `tg_cli.telegram_ops`, argument parsing and presentation in `tg_cli.cli`, and all write authorization in `tg_cli.safety`. Add narrow wrapper functions around Telethon high-level public methods instead of exposing arbitrary raw TL request passthrough. Shared serializers must emit sanitized rows only.

**Tech Stack:** Python, argparse, Telethon, pytest.

---

### Task 1: Coverage Inventory And Safety Contract

**Files:**
- Modify: `tg_cli/docs/superpowers/plans/2026-06-04-telethon-cli-coverage.md`
- Modify: `tg_cli/AGENTS.md`
- Modify: `tg_cli/README.md`

- [x] Capture the command families to add: `auth`, `dialog manage`, `drafts`, `messages get/replies/scheduled/copy/action/download`, expanded `send-file`, `downloads`, `members list`, `admin log/permissions/stats/kick/ban/unban/promote/demote/default-permissions`, `bot inline-query/inline-send`.
- [x] Keep these exclusions explicit: no arbitrary raw TL passthrough, no access hashes or phone numbers in JSON, no session bytes, no downloaded media bytes/base64, no broad range deletion, and no unpin-all.
- [x] Update user-facing docs after implementation lands.

### Task 2: Shared Serializers And Helpers

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Test: `tg_cli/tests/test_telegram_ops.py`

- [x] Add shallow sanitized serializers for drafts, admin log events, permissions, stats, inline results, auth status, and download results.
- [x] Add small parser helpers for message filters, participant filters, datetime, output paths, boolean permission flags, and JSON button markup.
- [x] Keep existing `_entity_row`, `_message_row`, and `_media_row` backward compatible.

### Task 3: Read-Only Coverage

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_telegram_ops.py`
- Test: `tg_cli/tests/test_cli.py`

- [x] Implement `auth status`.
- [x] Implement `messages get`, `messages replies`, `messages scheduled`, and filter-aware history/global search.
- [x] Implement `members list`, `admin log`, `admin permissions show`, and `admin stats`.
- [x] Implement `drafts list` and `bot inline-query`.

### Task 4: Download And Export Coverage

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_telegram_ops.py`
- Test: `tg_cli/tests/test_cli.py`

- [x] Implement `downloads media` for explicit message ids only.
- [x] Implement `downloads profile-photo`.
- [x] Ensure JSON returns file paths and metadata only, never file bytes.
- [x] Keep default output under a local ignored runtime directory.

### Task 5: Safe Write Coverage

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_telegram_ops.py`
- Test: `tg_cli/tests/test_cli.py`

- [x] Expand `messages send` and `messages send-file` options for Telethon high-level parameters that are safe to expose.
- [x] Implement `messages copy`, `messages edit-media`, `messages action`, and `bot inline-send`.
- [x] Implement `drafts set/send/delete`, `dialog archive/unarchive/delete`.
- [x] Require allowlist, pause check, confirmation or `--yes`, dry-run, and audit for every live write.

### Task 6: Admin Write Coverage

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_telegram_ops.py`
- Test: `tg_cli/tests/test_cli.py`

- [x] Implement `admin kick`, `admin ban`, `admin unban`, `admin promote`, `admin demote`, and `admin default-permissions`.
- [x] Keep all admin writes explicit-target only; do not add broad destructive ranges.
- [x] Require allowlist, pause check, confirmation or `--yes`, dry-run, and audit.

### Task 7: Account Session Coverage

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_cli.py`

- [x] Implement `auth login`, `auth qr-login`, `auth logout`, and `auth edit-2fa` with interactive secret prompts where needed.
- [x] Do not audit or print passwords, codes, API hash, phone number, or session paths beyond existing sanitized config inspection.

### Task 8: Documentation And Verification

**Files:**
- Modify: `tg_cli/README.md`
- Modify: `tg_cli/AGENTS.md`
- Test: `tg_cli/tests`

- [x] Document every new command family with examples.
- [x] Document retained exclusions and safety behavior.
- [x] Run `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q`.
- [x] Fix regressions in existing game, daemon, quota, memory, and badcase flows.
