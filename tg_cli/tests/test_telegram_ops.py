import asyncio
from types import SimpleNamespace

from tg_cli.config import AppConfig
from tg_cli import telegram_ops
import pytest


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


def test_short_ack_detection_handles_low_information_messages():
    assert telegram_ops._is_short_ack('嗯') is True
    assert telegram_ops._is_short_ack('哈哈哈') is True
    assert telegram_ops._is_short_ack('真的假的') is True
    assert telegram_ops._is_short_ack('今天下午可能下雨') is False


def test_should_prompt_can_skip_short_ack():
    assert telegram_ops._should_prompt_for_text(
        '哈哈', skip_short_ack=True, reply_probability=1.0) == (
            False, 'short_ack')


def test_should_prompt_uses_probability_gate():
    assert telegram_ops._should_prompt_for_text(
        '正常消息', reply_probability=0.3, random_value=0.2) == (
            True, 'prompt')
    assert telegram_ops._should_prompt_for_text(
        '正常消息', reply_probability=0.3, random_value=0.8) == (
            False, 'probability')


def test_should_prompt_uses_mention_probability_override():
    assert telegram_ops._should_prompt_for_text(
        'lu 你看看',
        reply_probability=0.0,
        mention_reply_probability=1.0,
        mentions_me=True,
        random_value=0.5) == (True, 'prompt')


def test_mentions_me_uses_account_names():
    me = SimpleNamespace(username='test_user', first_name='Lu', last_name=None)
    names = telegram_ops._mention_names(me)

    assert telegram_ops._mentions_me('@test_user 在吗', names) is True
    assert telegram_ops._mentions_me('Lu 看下', names) is True
    assert telegram_ops._mentions_me('别人看下', names) is False


def test_random_reply_delay_validates_range():
    assert telegram_ops._random_reply_delay(0, 0) == 0.0
    assert telegram_ops._random_reply_delay(1, 3, random_func=lambda a, b: 2.5) == 2.5
    with pytest.raises(telegram_ops.TelegramCliError):
        telegram_ops._random_reply_delay(4, 1)


def test_probability_validation_rejects_invalid_values():
    with pytest.raises(telegram_ops.TelegramCliError):
        telegram_ops._should_prompt_for_text('x', reply_probability=1.5)


def test_collect_merged_events_collects_until_window_expires():
    async def run():
        queue = asyncio.Queue()
        first = SimpleNamespace(message=SimpleNamespace(id=1))
        await queue.put(SimpleNamespace(message=SimpleNamespace(id=2)))
        loop = asyncio.get_running_loop()
        events = await telegram_ops._collect_merged_events(
            queue, first, merge_window=0.01, end_at=loop.time() + 1, loop=loop)
        return [event.message.id for event in events]

    assert asyncio.run(run()) == [1, 2]
