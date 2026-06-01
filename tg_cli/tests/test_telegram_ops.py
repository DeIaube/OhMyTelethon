import asyncio

from tg_cli.config import AppConfig
from tg_cli import telegram_ops


def make_config(tmp_path, profile=None):
    return AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        profile=profile,
    )


def test_remember_inbound_message_rejects_duplicate_ids():
    seen = set()

    assert telegram_ops._remember_inbound_message(seen, 10) is True
    assert telegram_ops._remember_inbound_message(seen, 10) is False
    assert telegram_ops._remember_inbound_message(seen, 11) is True
    assert seen == {10, 11}


def test_codex_context_includes_full_profile(monkeypatch, tmp_path):
    async def fake_history(config, chat, limit):
        return {'id': 5217114569, 'title': 'test chat'}, [{
            'id': 1,
            'date': '2026-06-01T00:00:00+00:00',
            'sender_id': 2,
            'sender': 'player',
            'out': False,
            'text': 'hello',
        }]

    monkeypatch.setattr(telegram_ops, 'history', fake_history)
    config = make_config(tmp_path, profile={
        'style': 'brief',
        'avoid_topics': ['spoilers'],
        'forbidden_terms': ['classified'],
    })

    data = asyncio.run(telegram_ops.codex_context(config, '5217114569', 20))

    assert data['profile']['style'] == 'brief'
    assert data['profile']['language'] == '中文'
    assert data['profile']['max_chars'] == 80
    assert data['profile']['emoji_level'] == 'low'
    assert data['profile']['avoid_topics'] == ['spoilers']
    assert data['profile']['forbidden_terms'] == ['classified']
    assert 'reply_policy' in data['profile']
    assert data['messages'][0]['text'] == 'hello'
