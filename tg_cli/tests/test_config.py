import json

import pytest

from tg_cli.config import ConfigError, load_config, normalize_chat_id, parse_chat_ids


def test_normalize_chat_id_accepts_telegram_peer_forms():
    assert normalize_chat_id('5217114569') == 5217114569
    assert normalize_chat_id('-5217114569') == 5217114569
    assert normalize_chat_id('-1001937176825') == 1937176825


def test_parse_chat_ids_accepts_string_or_list():
    assert parse_chat_ids('5217114569,-1001937176825') == [5217114569, 1937176825]
    assert parse_chat_ids([5217114569, '-1937176825']) == [5217114569, 1937176825]


def test_load_config_prefers_environment_over_file(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'api_id': 111,
        'api_hash': 'file-hash',
        'session_path': 'file.session',
        'allowed_chats': [1],
        'state_path': 'file-state.json',
        'audit_log_path': 'file-audit.log',
    }), encoding='utf-8')

    env = {
        'TG_API_ID': '222',
        'TG_API_HASH': 'env-hash',
        'TG_CLI_SESSION': str(tmp_path / 'env.session'),
        'TG_CLI_ALLOWED_CHATS': '5217114569,-1001937176825',
        'TG_CLI_STATE': str(tmp_path / 'env-state.json'),
        'TG_CLI_AUDIT_LOG': str(tmp_path / 'env-audit.log'),
    }

    config = load_config(config_path, env=env, cwd=tmp_path, require_credentials=True)

    assert config.api_id == 222
    assert config.api_hash == 'env-hash'
    assert config.session_path == (tmp_path / 'env.session').resolve()
    assert config.allowed_chats == (5217114569, 1937176825)
    assert config.state_path == (tmp_path / 'env-state.json').resolve()
    assert config.audit_log_path == (tmp_path / 'env-audit.log').resolve()


def test_load_config_requires_credentials_when_requested(tmp_path):
    with pytest.raises(ConfigError):
        load_config(env={}, cwd=tmp_path, require_credentials=True)
