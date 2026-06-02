# Bad Case Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a local, privacy-conscious bad case capture loop so future Telegram operators can learn from blocked/skipped cases without repeating them.

**Architecture:** Add a small JSONL-backed `bad_cases` store under `tg_cli/`, normalize a top-level `bad_cases` config block, and inject recent relevant records into daemon/quota/suggest prompts. Runtime code records structured, non-raw-text records when known failure signals fire, while CLI commands expose list/export for humans and future agents.

**Tech Stack:** Python stdlib JSON/Pathlib/hashlib, existing `tg_cli` config/daemon/quota/prompt/test patterns, pytest.

---

### Task 1: Local Bad Case Store

**Files:**
- Create: `tg_cli/bad_cases.py`
- Test: `tg_cli/tests/test_bad_cases.py`

- [x] **Step 1: Write tests for append, list, filtering, and no raw message text**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_bad_cases.py -q`

Expected first run before implementation: import failure for `tg_cli.bad_cases`.

- [x] **Step 2: Implement JSONL store**

Implement helpers to append bounded records, hash message text, list newest records, filter by chat/type, and format concise prompt guidance.

- [x] **Step 3: Verify store tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_bad_cases.py -q`

Expected: pass.

### Task 2: Config and Ignore Rules

**Files:**
- Modify: `tg_cli/config.py`
- Modify: `.gitignore`
- Modify: `tg_cli/AGENTS.md`
- Modify: `tg_cli/tg-cli.example.json`
- Modify: `tg_cli/docs/local-profile-template.json`
- Test: `tg_cli/tests/test_config.py`

- [x] **Step 1: Add `bad_cases` config defaults**

Fields: `enabled`, `path`, `max_records`, `max_task_bad_cases`, `recent_days`.

- [x] **Step 2: Resolve default path**

Default path: `tg_cli/.tg-cli-bad-cases.jsonl`. Keep it ignored by git.

- [x] **Step 3: Verify config tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_config.py -q`

Expected: pass.

### Task 3: Prompt Injection and Runtime Capture

**Files:**
- Modify: `tg_cli/agent_prompt.py`
- Modify: `tg_cli/telegram_ops.py`
- Test: `tg_cli/tests/test_agent_prompt.py`
- Test: `tg_cli/tests/test_telegram_ops.py`

- [x] **Step 1: Add bad case prompt section**

`build_operator_prompt` and initiative prompts should accept `bad_cases` and show concise lessons.

- [x] **Step 2: Inject recent bad cases into `game suggest`, daemon tasks, and quota tasks**

Use same-chat recent records first, capped by `bad_cases.max_task_bad_cases`.

- [x] **Step 3: Record automatic bad cases**

Record known failure signals such as `self_context_wait`, `stale_context`, `min_reply_chars`, `max_replies`, forbidden terms, and daemon/quota skip reasons without raw message text.

- [x] **Step 4: Verify behavior tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_agent_prompt.py tg_cli/tests/test_telegram_ops.py -q`

Expected: pass.

### Task 4: CLI and Docs

**Files:**
- Modify: `tg_cli/cli.py`
- Modify: `tg_cli/README.md`
- Modify: `tg_cli/docs/profile-config.md`
- Modify: `tg_cli/docs/agent-operator.md`
- Test: `tg_cli/tests/test_cli.py`

- [x] **Step 1: Add `tg-cli badcase list/export`**

Both commands should support `--json`; `list` should print concise records, and `export` should print JSONL-safe records.

- [x] **Step 2: Document extension workflow**

Explain how future bad case types can be recorded by adding one mapping and one call site.

- [x] **Step 3: Run full verification**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q`

Expected: pass.
