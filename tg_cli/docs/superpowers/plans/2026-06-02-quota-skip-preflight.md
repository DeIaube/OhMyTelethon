# Quota Skip And Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe way for quota operators to skip unsuitable tasks and prevent stale quota replies from sending after newer human activity.

**Architecture:** Reuse the existing quota state machine's `skip_task` transition and expose it through the CLI. Add a Telegram send preflight in `quota_reply` that re-reads the latest tail before reserving/sending; if the task snapshot is stale because a newer inbound message exists, skip the task and raise a clear error.

**Tech Stack:** Python stdlib, existing `tg_cli` quota/CLI/telegram_ops modules, pytest.

---

### Task 1: Expose Quota Skip

**Files:**
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_cli.py`
- Docs: `tg_cli/README.md`, `tg_cli/docs/agent-operator.md`, `tg_cli/docs/profile-config.md`, `tg_cli/AGENTS.md`

- [x] **Step 1: Add a CLI test for `quota skip`**

Verify `tg-cli quota skip <task_id> --reason stale_context --json` calls `skip_task`, prints `skipped: true`, and does not require credentials.

- [x] **Step 2: Add parser and command handling**

Add `quota skip` beside `quota reply`, with `task_id`, optional `--reason`, and `--json`.

- [x] **Step 3: Update docs**

Show `quota skip` in quota loops and explain it is the correct action when a task is unsuitable.

### Task 2: Add Quota Reply Stale Preflight

**Files:**
- Modify: `tg_cli/telegram_ops.py`
- Test: `tg_cli/tests/test_telegram_ops.py`
- Docs: `tg_cli/README.md`, `tg_cli/docs/agent-operator.md`, `tg_cli/docs/profile-config.md`, `tg_cli/AGENTS.md`

- [x] **Step 1: Add a failing preflight test**

Create a quota task with snapshot message id `10`; make latest tail contain inbound id `11`; assert `quota_reply` raises `stale context`, skips the task with reason `stale_context`, and sends nothing.

- [x] **Step 2: Implement helper functions**

Add helpers to extract snapshot message ids, detect newer inbound messages, and skip stale tasks through the quota store wrapper.

- [x] **Step 3: Call preflight before `begin_task`**

In the real-send branch of `quota_reply`, after validation/rate-limit checks and before `begin_task`, re-read the latest tail and reject stale tasks.

- [x] **Step 4: Run focused and full tests**

Run quota, CLI, Telegram ops tests, then the full `tg_cli/tests` suite.
