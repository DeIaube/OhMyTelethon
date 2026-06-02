# Multi-Agent Account Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable two external agents to safely operate two different Telegram accounts through `tg-cli`, with isolated session/state/queue files, explicit account identity, and a preflight check that catches accidental shared runtime paths.

**Architecture:** Keep the runtime model as isolated single-account CLI instances, not a centralized multi-account scheduler. Add an optional top-level `account_name`, resolve explicit config-relative paths predictably, expose `tg-cli config inspect/doctor`, and carry account metadata into status, audit, daemon tasks, and quota state/tasks. Templates and docs teach the two-agent workflow and make unsafe shared files visible before either agent starts.

**Tech Stack:** Python stdlib (`argparse`, `json`, `pathlib`), existing `tg_cli.config`, `tg_cli.cli`, `tg_cli.daemon`, `tg_cli.quota`, `tg_cli.safety`, pytest.

---

## File Structure

- Modify `tg_cli/config.py`: add `account_name`, config-relative path resolution, and tests for path behavior.
- Create `tg_cli/account_isolation.py`: inspect one config and compare multiple configs for shared runtime files.
- Modify `tg_cli/cli.py`: add `config inspect` and `config doctor` subcommands; surface account metadata in `status` and daemon status.
- Modify `tg_cli/safety.py`: add account metadata to audit records.
- Modify `tg_cli/daemon.py`: add optional account metadata to daemon task payloads.
- Modify `tg_cli/quota.py`: add optional account metadata to quota run state and quota tasks.
- Modify `tg_cli/telegram_ops.py`: pass `account_name` when creating daemon/quota tasks.
- Modify `tg_cli/tests/test_config.py`: test `account_name` loading and config-relative paths.
- Create `tg_cli/tests/test_account_isolation.py`: unit-test inspect/doctor behavior.
- Modify `tg_cli/tests/test_cli.py`: parser and command tests for `config inspect/doctor`.
- Modify `tg_cli/tests/test_safety.py`, `tg_cli/tests/test_daemon.py`, and `tg_cli/tests/test_quota.py`: test account metadata propagation.
- Modify `.gitignore`: ignore real account configs and runtime files under `tg_cli/accounts/`, while allowing examples.
- Create `tg_cli/accounts/account-a.example.json` and `tg_cli/accounts/account-b.example.json`: safe tracked templates without real credentials.
- Modify `tg_cli/AGENTS.md`, `tg_cli/docs/agent-operator.md`, `tg_cli/docs/profile-config.md`, and `tg_cli/docs/local-profile-template.json`: document two-agent operation, config-relative paths, and doctor usage.

---

### Task 1: Config Account Identity And Config-Relative Paths

**Files:**
- Modify: `tg_cli/config.py`
- Test: `tg_cli/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add these tests near the existing `load_config` tests in `tg_cli/tests/test_config.py`:

```python
def test_load_config_accepts_account_name_from_file_and_env(tmp_path):
    config_path = tmp_path / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': 'file-account',
        'session_path': 'file.session',
        'allowed_chats': [1],
    }), encoding='utf-8')

    file_config = load_config(config_path, env={}, cwd=tmp_path)
    env_config = load_config(
        config_path, env={'TG_CLI_ACCOUNT': 'env-account'}, cwd=tmp_path)

    assert file_config.account_name == 'file-account'
    assert env_config.account_name == 'env-account'


def test_load_config_rejects_blank_account_name(tmp_path):
    config_path = tmp_path / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': '   ',
        'session_path': 'file.session',
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='account_name must not be blank'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_explicit_config_relative_paths_resolve_against_config_directory(tmp_path):
    config_dir = tmp_path / 'tg_cli' / 'accounts'
    config_dir.mkdir(parents=True)
    config_path = config_dir / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': 'account-a',
        'session_path': 'account-a.session',
        'state_path': 'account-a.state.json',
        'audit_log_path': 'account-a.audit.log',
        'allowed_chats': [5217114569],
        'daemon': {
            'queue_path': 'account-a.daemon-queue.json',
            'lock_path': 'account-a.daemon.lock',
            'status_path': 'account-a.daemon-status.json'
        },
        'quota': {'state_path': 'account-a.quota-state.json'},
        'memory': {'path': 'account-a.memory.sqlite3'},
        'bad_cases': {'path': 'account-a.bad-cases.jsonl'},
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.session_path == (config_dir / 'account-a.session').resolve()
    assert config.state_path == (config_dir / 'account-a.state.json').resolve()
    assert config.audit_log_path == (config_dir / 'account-a.audit.log').resolve()
    assert config.daemon['queue_path'] == (
        config_dir / 'account-a.daemon-queue.json').resolve()
    assert config.daemon['lock_path'] == (
        config_dir / 'account-a.daemon.lock').resolve()
    assert config.daemon['status_path'] == (
        config_dir / 'account-a.daemon-status.json').resolve()
    assert config.quota['state_path'] == (
        config_dir / 'account-a.quota-state.json').resolve()
    assert config.memory['path'] == (
        config_dir / 'account-a.memory.sqlite3').resolve()
    assert config.bad_cases['path'] == (
        config_dir / 'account-a.bad-cases.jsonl').resolve()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_config.py -q
```

Expected: the new tests fail because `AppConfig` has no `account_name`, `TG_CLI_ACCOUNT` is ignored, and explicit relative paths resolve against `cwd`.

- [ ] **Step 3: Implement account name and config-relative path resolution**

In `tg_cli/config.py`, add helpers above `class AppConfig`:

```python
def normalize_account_name(value=None):
    if value in (None, ''):
        return ''
    if not isinstance(value, str):
        raise ConfigError('account_name must be a string.')
    normalized = value.strip()
    if not normalized:
        raise ConfigError('account_name must not be blank.')
    return normalized


def _resolve_path_value(value, path_base):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(path_base) / path
    return str(path)
```

Update `AppConfig.__init__` to accept and store `account_name`:

```python
def __init__(
        self, api_id=None, api_hash=None, session_path=None,
        allowed_chats=None, state_path=None, audit_log_path=None,
        profile=None, round_config=None, presets=None, config_path=None,
        reply_policy=None, initiative=None, persona=None,
        daemon_config=None, quota_config=None, character=None,
        memory_config=None, bad_cases_config=None, account_name=None):
    self.account_name = normalize_account_name(account_name)
    self.api_id = api_id
```

In `load_config`, compute path bases after reading the config:

```python
config_path = _find_config_path(path, base)
data = _read_json(config_path)
path_base = Path(config_path).expanduser().parent if config_path else base
```

Resolve every configured path through `path_base`:

```python
session_path = _resolve_path_value(
    env.get('TG_CLI_SESSION')
    or env.get('TG_SESSION_PATH')
    or data.get('session_path')
    or str(base / 'printer.session'),
    path_base)

state_path = _resolve_path_value(
    env.get('TG_CLI_STATE')
    or data.get('state_path')
    or str(base / 'tg_cli' / '.tg-cli-state.json'),
    path_base)
audit_log_path = _resolve_path_value(
    env.get('TG_CLI_AUDIT_LOG')
    or data.get('audit_log_path')
    or str(base / 'tg_cli' / 'tg-cli.audit.log'),
    path_base)
```

Resolve nested paths when present:

```python
for field_name in ('queue_path', 'lock_path', 'status_path'):
    if daemon_config.get(field_name) not in (None, ''):
        daemon_config[field_name] = _resolve_path_value(
            daemon_config[field_name], path_base)

if quota_config.get('state_path') not in (None, ''):
    quota_config['state_path'] = _resolve_path_value(
        quota_config['state_path'], path_base)
if memory_config.get('path') not in (None, ''):
    memory_config['path'] = _resolve_path_value(
        memory_config['path'], path_base)
if bad_cases_config.get('path') not in (None, ''):
    bad_cases_config['path'] = _resolve_path_value(
        bad_cases_config['path'], path_base)
```

Pass account name into `AppConfig`:

```python
account_name=env.get('TG_CLI_ACCOUNT') or data.get('account_name'),
```

- [ ] **Step 4: Run config tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_config.py -q
```

Expected: all config tests pass after updating any assertions whose expected relative path intentionally changed to config-directory resolution.

- [ ] **Step 5: Commit config changes**

```bash
git add tg_cli/config.py tg_cli/tests/test_config.py
git commit -m "feat(tg-cli): add account identity to config"
```

---

### Task 2: Runtime Path Inspection And Doctor Module

**Files:**
- Create: `tg_cli/account_isolation.py`
- Test: `tg_cli/tests/test_account_isolation.py`

- [ ] **Step 1: Write failing isolation tests**

Create `tg_cli/tests/test_account_isolation.py`:

```python
from pathlib import Path

from tg_cli.account_isolation import doctor_configs, inspect_config
from tg_cli.config import AppConfig


def make_config(tmp_path, name, suffix):
    return AppConfig(
        account_name=name,
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / '{}.session'.format(suffix),
        allowed_chats=(5217114569,),
        state_path=tmp_path / '{}.state.json'.format(suffix),
        audit_log_path=tmp_path / '{}.audit.log'.format(suffix),
        daemon_config={
            'queue_path': str(tmp_path / '{}.daemon-queue.json'.format(suffix)),
            'lock_path': str(tmp_path / '{}.daemon.lock'.format(suffix)),
            'status_path': str(tmp_path / '{}.daemon-status.json'.format(suffix)),
        },
        quota_config={'state_path': str(tmp_path / '{}.quota-state.json'.format(suffix))},
        memory_config={'path': str(tmp_path / '{}.memory.sqlite3'.format(suffix))},
        bad_cases_config={'path': str(tmp_path / '{}.bad-cases.jsonl'.format(suffix))},
    )


def test_inspect_config_lists_runtime_paths(tmp_path):
    config = make_config(tmp_path, 'account-a', 'a')

    payload = inspect_config(config)

    assert payload['account_name'] == 'account-a'
    assert payload['allowed_chats'] == [5217114569]
    assert payload['runtime_paths']['session_path'].endswith('a.session')
    assert payload['runtime_paths']['daemon.queue_path'].endswith(
        'a.daemon-queue.json')
    assert payload['runtime_paths']['bad_cases.path'].endswith(
        'a.bad-cases.jsonl')


def test_doctor_configs_passes_when_paths_are_distinct(tmp_path):
    account_a = make_config(tmp_path, 'account-a', 'a')
    account_b = make_config(tmp_path, 'account-b', 'b')

    result = doctor_configs(account_a, [account_b])

    assert result['ok'] is True
    assert result['findings'] == []


def test_doctor_configs_reports_shared_paths_and_duplicate_names(tmp_path):
    account_a = make_config(tmp_path, 'same-name', 'a')
    account_b = make_config(tmp_path, 'same-name', 'b')
    account_b.session_path = Path(account_a.session_path)
    account_b.daemon['queue_path'] = Path(account_a.daemon['queue_path'])

    result = doctor_configs(account_a, [account_b])

    assert result['ok'] is False
    messages = [finding['message'] for finding in result['findings']]
    assert 'Duplicate account_name "same-name" appears in 2 configs.' in messages
    assert any('session_path' in message for message in messages)
    assert any('daemon.queue_path' in message for message in messages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_account_isolation.py -q
```

Expected: import fails because `tg_cli.account_isolation` does not exist.

- [ ] **Step 3: Implement inspection module**

Create `tg_cli/account_isolation.py`:

```python
from pathlib import Path


RUNTIME_PATH_FIELDS = (
    ('session_path', lambda config: config.session_path),
    ('state_path', lambda config: config.state_path),
    ('audit_log_path', lambda config: config.audit_log_path),
    ('daemon.queue_path', lambda config: config.daemon.get('queue_path')),
    ('daemon.lock_path', lambda config: config.daemon.get('lock_path')),
    ('daemon.status_path', lambda config: config.daemon.get('status_path')),
    ('quota.state_path', lambda config: config.quota.get('state_path')),
    ('memory.path', lambda config: config.memory.get('path')),
    ('bad_cases.path', lambda config: config.bad_cases.get('path')),
)


def _path_text(value):
    if value in (None, ''):
        return ''
    return str(Path(value).expanduser().resolve())


def inspect_config(config):
    runtime_paths = {}
    for field_name, getter in RUNTIME_PATH_FIELDS:
        path = _path_text(getter(config))
        if path:
            runtime_paths[field_name] = path
    return {
        'account_name': getattr(config, 'account_name', '') or '',
        'config_path': str(getattr(config, 'config_path', '') or ''),
        'allowed_chats': list(getattr(config, 'allowed_chats', ()) or ()),
        'runtime_paths': runtime_paths,
    }


def _finding(severity, code, message, configs=None, path=None):
    payload = {
        'severity': severity,
        'code': code,
        'message': message,
    }
    if configs is not None:
        payload['configs'] = list(configs)
    if path is not None:
        payload['path'] = path
    return payload


def doctor_configs(primary_config, other_configs):
    inspections = [
        inspect_config(primary_config),
    ] + [inspect_config(config) for config in other_configs]
    findings = []

    names = {}
    for item in inspections:
        name = item.get('account_name') or ''
        label = item.get('config_path') or name or '<in-memory>'
        if not name:
            findings.append(_finding(
                'warning', 'missing_account_name',
                'Config {} has no account_name.'.format(label),
                configs=[label]))
            continue
        names.setdefault(name, []).append(label)
    for name, labels in sorted(names.items()):
        if len(labels) > 1:
            findings.append(_finding(
                'error', 'duplicate_account_name',
                'Duplicate account_name "{}" appears in {} configs.'.format(
                    name, len(labels)),
                configs=labels))

    paths = {}
    for item in inspections:
        label = item.get('config_path') or item.get('account_name') or '<in-memory>'
        for field_name, path in sorted(item.get('runtime_paths', {}).items()):
            paths.setdefault(path, []).append((label, field_name))

    for path, owners in sorted(paths.items()):
        labels = sorted({label for label, _field in owners})
        if len(labels) < 2:
            continue
        fields = sorted({field for _label, field in owners})
        findings.append(_finding(
            'error', 'shared_runtime_path',
            'Runtime path is shared by multiple configs: {} -> {}.'.format(
                path, ', '.join(fields)),
            configs=labels,
            path=path))

    return {
        'ok': not any(finding['severity'] == 'error' for finding in findings),
        'configs': inspections,
        'findings': findings,
    }
```

- [ ] **Step 4: Run isolation tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_account_isolation.py -q
```

Expected: all isolation tests pass.

- [ ] **Step 5: Commit inspection module**

```bash
git add tg_cli/account_isolation.py tg_cli/tests/test_account_isolation.py
git commit -m "feat(tg-cli): add account isolation doctor"
```

---

### Task 3: CLI Config Inspect And Doctor Commands

**Files:**
- Modify: `tg_cli/cli.py`
- Test: `tg_cli/tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add imports at the top of `tg_cli/tests/test_cli.py`:

```python
from pathlib import Path
```

Add these tests near the parser tests:

```python
def test_config_parser_accepts_inspect_and_doctor():
    parser = cli.build_parser()

    inspect_args = parser.parse_args(['config', 'inspect', '--json'])
    doctor_args = parser.parse_args([
        '--config', 'account-a.json',
        'config', 'doctor',
        '--other-config', 'account-b.json',
        '--json',
    ])

    assert inspect_args.command == 'config'
    assert inspect_args.config_command == 'inspect'
    assert inspect_args.json is True
    assert doctor_args.command == 'config'
    assert doctor_args.config_command == 'doctor'
    assert doctor_args.other_config == ['account-b.json']
    assert doctor_args.json is True


def test_config_inspect_json_outputs_account_and_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': 'account-a',
        'session_path': 'account-a.session',
        'state_path': 'account-a.state.json',
        'audit_log_path': 'account-a.audit.log',
        'allowed_chats': [5217114569],
    }), encoding='utf-8')

    code = cli.main(['--config', str(config_path), 'config', 'inspect', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['account_name'] == 'account-a'
    assert data['allowed_chats'] == [5217114569]
    assert data['runtime_paths']['session_path'].endswith('account-a.session')


def test_config_doctor_json_reports_shared_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    a_path = tmp_path / 'account-a.json'
    b_path = tmp_path / 'account-b.json'
    shared_session = str(tmp_path / 'shared.session')
    a_path.write_text(json.dumps({
        'account_name': 'account-a',
        'session_path': shared_session,
        'state_path': 'a.state.json',
        'audit_log_path': 'a.audit.log',
    }), encoding='utf-8')
    b_path.write_text(json.dumps({
        'account_name': 'account-b',
        'session_path': shared_session,
        'state_path': 'b.state.json',
        'audit_log_path': 'b.audit.log',
    }), encoding='utf-8')

    code = cli.main([
        '--config', str(a_path),
        'config', 'doctor',
        '--other-config', str(b_path),
        '--json',
    ])

    assert code == 1
    data = json.loads(capsys.readouterr().out)
    assert data['ok'] is False
    assert any(
        finding['code'] == 'shared_runtime_path'
        for finding in data['findings'])
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_cli.py -q
```

Expected: parser tests fail because `config` subcommands are not registered.

- [ ] **Step 3: Implement CLI subcommands**

In `tg_cli/cli.py`, add imports:

```python
from . import account_isolation
```

In `build_parser`, add the config command before existing runtime commands:

```python
    config_cmd = sub.add_parser(
        'config', help='Inspect and validate tg-cli configuration.')
    config_sub = config_cmd.add_subparsers(
        dest='config_command', required=True)

    config_inspect = config_sub.add_parser(
        'inspect', help='Show resolved config paths and account metadata.')
    config_inspect.add_argument('--json', action='store_true')

    config_doctor = config_sub.add_parser(
        'doctor', help='Check this config against other account configs.')
    config_doctor.add_argument(
        '--other-config', action='append', default=[], required=True,
        help='Another account config to compare. Repeat for more accounts.')
    config_doctor.add_argument('--json', action='store_true')
```

Add a command helper near `_status_payload`:

```python
def _print_config_inspect(payload):
    print('account_name={}'.format(payload.get('account_name') or '-'))
    print('config_path={}'.format(payload.get('config_path') or '-'))
    print('allowed_chats={}'.format(
        ','.join(str(x) for x in payload.get('allowed_chats') or []) or 'none'))
    for field_name, path in sorted(payload.get('runtime_paths', {}).items()):
        print('{}={}'.format(field_name, path))


def _print_config_doctor(payload):
    print('ok={}'.format(str(bool(payload.get('ok'))).lower()))
    for finding in payload.get('findings') or []:
        print('[{}] {}: {}'.format(
            finding.get('severity'), finding.get('code'),
            finding.get('message')))


def _cmd_config(args, config):
    if args.config_command == 'inspect':
        payload = account_isolation.inspect_config(config)
        if args.json:
            _print_json(payload)
        else:
            _print_config_inspect(payload)
        return 0
    if args.config_command == 'doctor':
        other_configs = [
            load_config(path, require_credentials=False)
            for path in args.other_config
        ]
        payload = account_isolation.doctor_configs(config, other_configs)
        if args.json:
            _print_json(payload)
        else:
            _print_config_doctor(payload)
        return 0 if payload['ok'] else 1
    raise AssertionError(args.config_command)
```

Dispatch in `main` after loading config:

```python
        if args.command == 'config':
            return _cmd_config(args, config)
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests/test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit CLI commands**

```bash
git add tg_cli/cli.py tg_cli/tests/test_cli.py
git commit -m "feat(tg-cli): expose config inspect and doctor"
```

---

### Task 4: Account Metadata In Status, Audit, Daemon, And Quota

**Files:**
- Modify: `tg_cli/cli.py`
- Modify: `tg_cli/safety.py`
- Modify: `tg_cli/daemon.py`
- Modify: `tg_cli/quota.py`
- Modify: `tg_cli/telegram_ops.py`
- Test: `tg_cli/tests/test_cli.py`
- Test: `tg_cli/tests/test_safety.py`
- Test: `tg_cli/tests/test_daemon.py`
- Test: `tg_cli/tests/test_quota.py`
- Test: `tg_cli/tests/test_telegram_ops.py`

- [ ] **Step 1: Write failing metadata tests**

In `tg_cli/tests/test_cli.py`, add:

```python
def test_status_json_includes_account_name(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': 'account-a',
        'session_path': 'account-a.session',
    }), encoding='utf-8')

    code = cli.main(['--config', str(config_path), 'status', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['account_name'] == 'account-a'
```

In `tg_cli/tests/test_safety.py`, add:

```python
def test_audit_record_includes_account_name(tmp_path):
    config = make_config(tmp_path)
    config.account_name = 'account-a'

    safety.audit_record(
        config, 'send', 5217114569,
        chat_title='test chat', text='tg-cli 测试消息',
        message_id=123, dry_run=False)

    line = config.audit_log_path.read_text(encoding='utf-8').strip()
    data = json.loads(line)
    assert data['account_name'] == 'account-a'
```

In `tg_cli/tests/test_daemon.py`, add:

```python
def test_create_task_can_include_account_name():
    task = daemon.create_task(
        chat={'id': 1, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        account_name='account-a',
        now='2026-06-01T00:00:00+00:00')

    assert task['account_name'] == 'account-a'
```

In `tg_cli/tests/test_quota.py`, add:

```python
def test_create_run_and_task_store_account_name(tmp_path):
    state_path = tmp_path / 'quota.json'

    state = quota.create_run(
        state_path, [{'chat_id': 111, 'target_count': 1}],
        preset='chat_social', account_name='account-a', now=NOW)
    task = quota.create_task(state_path, 111, now=NOW)

    assert state['account_name'] == 'account-a'
    assert task['account_name'] == 'account-a'
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tg_cli/tests/test_cli.py::test_status_json_includes_account_name \
  tg_cli/tests/test_safety.py::test_audit_record_includes_account_name \
  tg_cli/tests/test_daemon.py::test_create_task_can_include_account_name \
  tg_cli/tests/test_quota.py::test_create_run_and_task_store_account_name -q
```

Expected: the tests fail because account metadata is not emitted.

- [ ] **Step 3: Implement metadata propagation**

In `tg_cli/cli.py`, update `_status_payload`:

```python
        'account_name': getattr(config, 'account_name', '') or '',
```

Update `_daemon_status_payload`:

```python
        'account_name': getattr(config, 'account_name', '') or '',
```

In `tg_cli/safety.py`, update `audit_record` payload:

```python
        'account_name': getattr(config, 'account_name', '') or '',
```

In `tg_cli/daemon.py`, add `account_name=None` to `create_task` and store it only when present:

```python
def create_task(chat, messages, profile, persona, reply_policy, initiative,
                preset=None, kind='message', prompt=None, now=None,
                context_summary=None, character=None, actions=None,
                evaluators=None, memory=None, bad_cases=None, action=None,
                account_name=None):
```

```python
    if account_name not in (None, ''):
        task['account_name'] = str(account_name)
```

In `tg_cli/quota.py`, add `account_name=None` to `create_run` and store it:

```python
def create_run(path, targets, preset=None, scenario=None, account_name=None,
               now=None):
```

```python
        'account_name': str(account_name or ''),
```

In `quota.create_task`, copy it from state:

```python
            'account_name': state.get('account_name') or '',
```

In `tg_cli/cli.py`, pass account name when starting quota:

```python
        payload = store.create_run(
            state_path, args.chat, preset=args.preset,
            scenario=scenario_payload,
            account_name=getattr(config, 'account_name', '') or '')
```

In `tg_cli/telegram_ops.py`, pass account name when daemon tasks are created:

```python
                account_name=getattr(config, 'account_name', '') or '')
```

Also include account name in quota task context:

```python
        'account_name': getattr(config, 'account_name', '') or '',
```

- [ ] **Step 4: Run metadata tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tg_cli/tests/test_cli.py \
  tg_cli/tests/test_safety.py \
  tg_cli/tests/test_daemon.py \
  tg_cli/tests/test_quota.py \
  tg_cli/tests/test_telegram_ops.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit metadata propagation**

```bash
git add tg_cli/cli.py tg_cli/safety.py tg_cli/daemon.py tg_cli/quota.py tg_cli/telegram_ops.py tg_cli/tests/test_cli.py tg_cli/tests/test_safety.py tg_cli/tests/test_daemon.py tg_cli/tests/test_quota.py tg_cli/tests/test_telegram_ops.py
git commit -m "feat(tg-cli): tag runtime payloads with account name"
```

---

### Task 5: Account Templates, Ignore Rules, And Documentation

**Files:**
- Modify: `.gitignore`
- Create: `tg_cli/accounts/account-a.example.json`
- Create: `tg_cli/accounts/account-b.example.json`
- Modify: `tg_cli/AGENTS.md`
- Modify: `tg_cli/docs/agent-operator.md`
- Modify: `tg_cli/docs/profile-config.md`
- Modify: `tg_cli/docs/local-profile-template.json`

- [ ] **Step 1: Update ignore rules**

Add this block under the existing local tg-cli state section in `.gitignore`:

```gitignore
# Local per-account tg-cli configs and runtime files
/tg_cli/accounts/*.json
!/tg_cli/accounts/*.example.json
/tg_cli/accounts/*.session
/tg_cli/accounts/*.session-journal
/tg_cli/accounts/*.state.json
/tg_cli/accounts/*.audit.log
/tg_cli/accounts/*.daemon-queue.json
/tg_cli/accounts/*.daemon-queue.json.lock
/tg_cli/accounts/*.daemon-status.json
/tg_cli/accounts/*.daemon.lock
/tg_cli/accounts/*.quota-state.json
/tg_cli/accounts/*.quota-state.json.lock
/tg_cli/accounts/*.memory.sqlite3
/tg_cli/accounts/*.memory.sqlite3-*
/tg_cli/accounts/*.bad-cases.jsonl
/tg_cli/accounts/*.bad-cases.jsonl.*
```

- [ ] **Step 2: Create account templates**

Create `tg_cli/accounts/account-a.example.json`:

```json
{
  "account_name": "account-a",
  "api_id": 12345,
  "api_hash": "set-with-TG_API_HASH",
  "session_path": "account-a.session",
  "allowed_chats": [
    1234567890
  ],
  "state_path": "account-a.state.json",
  "audit_log_path": "account-a.audit.log",
  "daemon": {
    "queue_path": "account-a.daemon-queue.json",
    "lock_path": "account-a.daemon.lock",
    "status_path": "account-a.daemon-status.json",
    "poll_interval": 1,
    "task_ttl": 900,
    "claim_ttl": 300,
    "max_pending": 20,
    "max_task_context": 8,
    "min_reply_interval": 6,
    "max_messages_per_hour": 20
  },
  "quota": {
    "state_path": "account-a.quota-state.json"
  },
  "memory": {
    "enabled": false,
    "path": "account-a.memory.sqlite3",
    "max_task_memories": 8
  },
  "bad_cases": {
    "enabled": true,
    "path": "account-a.bad-cases.jsonl",
    "max_records": 1000,
    "max_task_bad_cases": 3,
    "recent_days": 14
  },
  "profile": {
    "style": "账号 A：自然、简短、像普通群聊，不要长篇解释。",
    "language": "中文",
    "max_chars": 80,
    "emoji_level": "low",
    "avoid_topics": ["隐私", "账号信息", "借钱"],
    "forbidden_terms": [],
    "reply_policy": "只在有明确可接话的内容时回复；不确定时跳过；不要编造事实或冒充他人。"
  }
}
```

Create `tg_cli/accounts/account-b.example.json` with the same structure and these string changes:

```json
{
  "account_name": "account-b",
  "api_id": 12345,
  "api_hash": "set-with-TG_API_HASH",
  "session_path": "account-b.session",
  "allowed_chats": [
    1234567890
  ],
  "state_path": "account-b.state.json",
  "audit_log_path": "account-b.audit.log",
  "daemon": {
    "queue_path": "account-b.daemon-queue.json",
    "lock_path": "account-b.daemon.lock",
    "status_path": "account-b.daemon-status.json",
    "poll_interval": 1,
    "task_ttl": 900,
    "claim_ttl": 300,
    "max_pending": 20,
    "max_task_context": 8,
    "min_reply_interval": 6,
    "max_messages_per_hour": 20
  },
  "quota": {
    "state_path": "account-b.quota-state.json"
  },
  "memory": {
    "enabled": false,
    "path": "account-b.memory.sqlite3",
    "max_task_memories": 8
  },
  "bad_cases": {
    "enabled": true,
    "path": "account-b.bad-cases.jsonl",
    "max_records": 1000,
    "max_task_bad_cases": 3,
    "recent_days": 14
  },
  "profile": {
    "style": "账号 B：自然、简短、像普通群聊，不要长篇解释。",
    "language": "中文",
    "max_chars": 80,
    "emoji_level": "low",
    "avoid_topics": ["隐私", "账号信息", "借钱"],
    "forbidden_terms": [],
    "reply_policy": "只在有明确可接话的内容时回复；不确定时跳过；不要编造事实或冒充他人。"
  }
}
```

- [ ] **Step 3: Update docs with the two-agent workflow**

In `tg_cli/AGENTS.md`, add under profile config:

```markdown
- For two-agent/two-account operation, use one config file per account and keep every runtime path unique: `session_path`, `state_path`, `audit_log_path`, `daemon.queue_path`, `daemon.lock_path`, `daemon.status_path`, `quota.state_path`, `memory.path`, and `bad_cases.path`.
- Run `tg-cli --config <account-a.json> config doctor --other-config <account-b.json>` before starting concurrent agents.
- Explicit config-relative paths resolve relative to the config file directory. Default paths without an explicit config still resolve under the repository-local `tg_cli/` runtime files.
```

In `tg_cli/docs/agent-operator.md`, add a section before "Daemon Task Queue":

```markdown
## Two-Agent / Two-Account Operation

Use one config per Telegram account. Each external agent must keep using its own `--config` for every command, including daemon queue commands:

```sh
tg-cli --config tg_cli/accounts/account-a.json config inspect --json
tg-cli --config tg_cli/accounts/account-b.json config inspect --json
tg-cli --config tg_cli/accounts/account-a.json config doctor --other-config tg_cli/accounts/account-b.json

tg-cli --config tg_cli/accounts/account-a.json daemon run 111111111 --preset chat_social
tg-cli --config tg_cli/accounts/account-b.json daemon run 222222222 --preset chat_social

tg-cli --config tg_cli/accounts/account-a.json daemon next --json
tg-cli --config tg_cli/accounts/account-a.json daemon reply TASK_ID "这把先看看队友怎么说" --dry-run --json

tg-cli --config tg_cli/accounts/account-b.json daemon next --json
tg-cli --config tg_cli/accounts/account-b.json daemon reply TASK_ID "这把先等等信息" --dry-run --json
```

Do not share a Telethon `session_path` across agents. Do not share daemon queue/lock/status files across account configs. Different accounts may run in parallel only when their runtime files are distinct.
```

In `tg_cli/docs/profile-config.md`, add a "Path Resolution" subsection:

```markdown
## Path Resolution

When `--config path/to/account.json` is provided, relative paths inside that file are resolved relative to `path/to/`. This applies to `session_path`, `state_path`, `audit_log_path`, `daemon.*_path`, `quota.state_path`, `memory.path`, and `bad_cases.path`.

When no explicit config is loaded, defaults still use repository-local paths under `tg_cli/`.
```

Update `tg_cli/docs/local-profile-template.json` by adding:

```json
  "account_name": "local-account",
```

- [ ] **Step 4: Validate JSON templates and docs snippets**

Run:

```bash
python -m json.tool tg_cli/accounts/account-a.example.json >/tmp/account-a.json
python -m json.tool tg_cli/accounts/account-b.example.json >/tmp/account-b.json
python -m json.tool tg_cli/docs/local-profile-template.json >/tmp/local-profile-template.json
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit templates and docs**

```bash
git add .gitignore tg_cli/accounts/account-a.example.json tg_cli/accounts/account-b.example.json tg_cli/AGENTS.md tg_cli/docs/agent-operator.md tg_cli/docs/profile-config.md tg_cli/docs/local-profile-template.json
git commit -m "docs(tg-cli): document isolated two-account operation"
```

---

### Task 6: End-To-End Verification

**Files:**
- No new files.
- Verify: all touched tests and JSON templates.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tg_cli/tests/test_config.py \
  tg_cli/tests/test_account_isolation.py \
  tg_cli/tests/test_cli.py \
  tg_cli/tests/test_safety.py \
  tg_cli/tests/test_daemon.py \
  tg_cli/tests/test_quota.py \
  tg_cli/tests/test_telegram_ops.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run template inspection smoke tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m tg_cli.cli --config tg_cli/accounts/account-a.example.json config inspect --json
PYTHONPATH=. .venv/bin/python -m tg_cli.cli --config tg_cli/accounts/account-a.example.json config doctor --other-config tg_cli/accounts/account-b.example.json --json
```

Expected: `inspect` exits 0 and shows `account_name` as `account-a`; `doctor` exits 0 with `"ok": true`.

- [ ] **Step 3: Run shared-session negative smoke test**

Create temporary configs:

```bash
tmpdir="$(mktemp -d)"
cp tg_cli/accounts/account-a.example.json "$tmpdir/a.json"
cp tg_cli/accounts/account-b.example.json "$tmpdir/b.json"
python - "$tmpdir/a.json" "$tmpdir/b.json" <<'PY'
import json
import sys
from pathlib import Path

a_path = Path(sys.argv[1])
b_path = Path(sys.argv[2])
a = json.loads(a_path.read_text(encoding='utf-8'))
b = json.loads(b_path.read_text(encoding='utf-8'))
a['session_path'] = 'shared.session'
b['session_path'] = 'shared.session'
a_path.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding='utf-8')
b_path.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding='utf-8')
PY
PYTHONPATH=. .venv/bin/python -m tg_cli.cli --config "$tmpdir/a.json" config doctor --other-config "$tmpdir/b.json" --json
```

Expected: command exits 1 and prints a `shared_runtime_path` finding for `session_path`.

- [ ] **Step 4: Run full tg_cli tests if focused tests pass**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tg_cli/tests -q
```

Expected: all `tg_cli` tests pass.

- [ ] **Step 5: Commit verification fixes if needed**

If any test exposed a small fix, commit the fix:

```bash
git add tg_cli .gitignore
git commit -m "test(tg-cli): verify account isolation workflow"
```

If no files changed after verification, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Two agents, one account each: covered by config-per-account templates and docs in Task 5.
- Full runtime isolation: covered by config-relative paths in Task 1 and doctor checks in Task 2.
- CLI usability: covered by `config inspect` and `config doctor` in Task 3.
- Account visibility: covered by status, audit, daemon tasks, and quota state/tasks in Task 4.
- Documentation and examples inside `tg_cli/`: covered by Task 5.
- Safety constraints: no bypass is introduced; all sends continue to use existing whitelist, pause, forbidden-term, rate-limit, and audit paths.

Placeholder scan:

- The plan contains no "TBD", "implement later", or undefined task references.
- Every code step includes concrete code or exact command lines.

Type consistency:

- `account_name` is a string stored on `AppConfig`.
- Inspection payload uses `runtime_paths` consistently.
- Doctor output uses `ok`, `configs`, and `findings`.
- CLI subcommand names are `config inspect` and `config doctor`.
