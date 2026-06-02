from pathlib import Path

from tg_cli.account_isolation import doctor_configs, inspect_config
from tg_cli.config import AppConfig


def make_config(tmp_path, name, suffix):
    config = AppConfig(
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
        quota_config={
            'state_path': str(
                tmp_path / '{}.quota-state.json'.format(suffix)),
        },
        memory_config={
            'path': str(tmp_path / '{}.memory.sqlite3'.format(suffix)),
        },
        bad_cases_config={
            'path': str(tmp_path / '{}.bad-cases.jsonl'.format(suffix)),
        },
    )
    config.account_name = name
    return config


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
