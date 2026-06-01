import json

import pytest

from tg_cli.config import AppConfig
from tg_cli import safety


def make_config(tmp_path, allowed=(5217114569,)):
    return AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=allowed,
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )


def test_require_can_write_allows_whitelisted_chat(tmp_path):
    config = make_config(tmp_path)
    safety.require_can_write(config, 5217114569)


def test_require_can_write_rejects_non_whitelisted_chat(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(safety.SafetyError):
        safety.require_can_write(config, 1937176825)


def test_pause_blocks_write_operations(tmp_path):
    config = make_config(tmp_path)
    safety.set_paused(config, True)

    with pytest.raises(safety.SafetyError):
        safety.require_can_write(config, 5217114569)

    safety.set_paused(config, False)
    safety.require_can_write(config, 5217114569)


def test_confirm_send_defaults_to_no():
    seen = []
    result = safety.confirm_send(
        'chat', 1, 'hello',
        input_func=lambda prompt: '',
        output_func=seen.append,
    )

    assert result is False
    assert any('Target:' in line for line in seen)


def test_audit_record_hashes_text_without_storing_raw_message(tmp_path):
    config = make_config(tmp_path)
    safety.audit_record(
        config, 'send', 5217114569,
        chat_title='lu 和 王哥',
        text='tg-cli 测试消息',
        message_id=123,
        status='sent',
    )

    line = config.audit_log_path.read_text(encoding='utf-8').strip()
    data = json.loads(line)

    assert data['text_length'] == len('tg-cli 测试消息')
    assert 'text_sha256' in data
    assert 'tg-cli 测试消息' not in line
    assert data['message_id'] == 123
