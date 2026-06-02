# Scenario Quota Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repeated "account + group + persona + 150-message target" tests declarative, resumable, and safe through quota scenario runs.

**Architecture:** Add a local scenario config model that validates non-secret scenario definitions, then expose a CLI entry point that starts a quota run from a named scenario. Keep message generation and sending in the existing `quota next/reply/skip` loop so allowlist, pause, pacing, stale preflight, audit, and bad-case behavior remain enforced.

**Tech Stack:** Python stdlib JSON/pathlib, existing `tg_cli` quota/CLI/config patterns, pytest.

---

### Task 1: Scenario Model

**Files:**
- Create: `tg_cli/scenarios.py`
- Create: `tg_cli/tests/test_scenarios.py`

- [x] **Step 1: Implement scenario loading and validation**

Support local ignored config at `tg_cli/.tg-cli-scenarios.json`, validate `name`, `account`, `chat_id`, `persona`, `preset`, `target_messages`, `dry_run_first`, `max_runtime_minutes`, and `stop_on`.

- [x] **Step 2: Test model behavior**

Cover defaults, invalid values, named lookup, and a 150-message target.

### Task 2: Quota Metadata

**Files:**
- Modify: `tg_cli/quota.py`
- Modify: `tg_cli/tests/test_quota.py`

- [x] **Step 1: Store scenario metadata on quota runs**

Allow `create_run(..., scenario=...)` to persist non-secret scenario metadata in state.

- [x] **Step 2: Test metadata preservation**

Ensure the scenario metadata is visible in `quota status` and does not change counting semantics.

### Task 3: CLI Integration

**Files:**
- Modify: `tg_cli/cli.py`
- Modify: `tg_cli/tests/test_cli.py`

- [x] **Step 1: Add parser for `scenario list/show/start`**

Support `--path` and `--json`; `start` creates a quota run for the scenario target.

- [x] **Step 2: Enforce safety gates**

Require target chat to be allowed and preset to resolve before creating the quota run.

- [x] **Step 3: Test CLI behavior without credentials**

Use fake scenario and quota stores to verify start/list/show output and metadata.

### Task 4: Documentation And Verification

**Files:**
- Modify: `tg_cli/AGENTS.md`
- Modify: `tg_cli/README.md`
- Modify: `tg_cli/docs/agent-operator.md`
- Modify: `tg_cli/docs/profile-config.md`

- [x] **Step 1: Document scenario workflow**

Explain scenario fields, safe operator loop, skip behavior, stale preflight, and stop conditions.

- [x] **Step 2: Run tests**

Run `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q`, JSON validation, and `git diff --check`.
