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


def test_emit_requests_flush_when_output_func_supports_it():
    calls = []

    def output(text, flush=False):
        calls.append((text, flush))

    telegram_ops._emit(output, 'hello')

    assert calls == [('hello', True)]


def test_emit_falls_back_for_simple_output_func():
    calls = []

    def output(text):
        calls.append(text)

    telegram_ops._emit(output, 'hello')

    assert calls == ['hello']


def test_codex_context_includes_full_profile_and_operator(monkeypatch, tmp_path):
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

    data = asyncio.run(telegram_ops.codex_context(
        config, '5217114569', 20, operator='Claude', preset='casual'))

    assert data['operator'] == 'Claude'
    assert data['preset'] == 'casual'
    assert data['profile']['style'] == 'brief'
    assert data['profile']['language'] == '中文'
    assert data['profile']['max_chars'] == 80
    assert data['profile']['emoji_level'] == 'low'
    assert data['profile']['avoid_topics'] == ['spoilers']
    assert data['profile']['forbidden_terms'] == ['classified']
    assert 'reply_policy' in data['profile']
    assert data['messages'][0]['text'] == 'hello'
    assert '你是 Claude' in data['instruction']


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


def test_split_reply_text_prefers_punctuation_boundaries():
    assert telegram_ops._split_reply_text(
        '先这样吧，我一会儿再看。你先别急。', max_chars=12, max_parts=3) == [
            '先这样吧，',
            '我一会儿再看。',
            '你先别急。',
        ]


def test_split_reply_text_caps_parts_by_merging_tail():
    assert telegram_ops._split_reply_text(
        '一二三四五六七八九十十一十二', max_chars=4, max_parts=2) == [
            '一二三四',
            '五六七八九十十一十二',
        ]


def test_round_reply_parts_respects_config(tmp_path):
    config = make_config(tmp_path)
    config.round['split_long_replies'] = False
    assert telegram_ops._round_reply_parts(config, '一二三四五六') == ['一二三四五六']

    config.round['split_long_replies'] = True
    config.round['split_max_chars'] = 3
    config.round['split_max_parts'] = 3
    assert telegram_ops._round_reply_parts(config, '一二三四五六') == [
        '一二三',
        '四五六',
    ]


def test_remaining_message_budget_counts_split_message_ids():
    report = telegram_ops.RoundReport(duration=60)
    report.record_sent_message(101)
    report.record_sent_message(102)

    assert telegram_ops._remaining_message_budget(report, 3) == 1
    assert telegram_ops._remaining_message_budget(report, 2) == 0


def test_initiative_forbidden_topics_match_outbound_text():
    assert telegram_ops._terms_in_text(['交易', '隐私'], '这个交易别聊了') == ('交易',)
    assert telegram_ops._terms_in_text(['交易', '交易'], '交易') == ('交易',)
    assert telegram_ops._terms_in_text(['隐私'], '普通聊天') == ()


def test_new_inbound_ids_ignores_self_messages():
    previous = [
        {'id': 1, 'out': False, 'text': 'old'},
        {'id': 2, 'out': True, 'text': 'me'},
    ]
    latest = previous + [
        {'id': 3, 'out': False, 'text': 'new'},
        {'id': 4, 'out': True, 'text': 'my new message'},
    ]

    assert telegram_ops._new_inbound_ids(previous, latest) == {3}


def test_format_persona_guidance_renders_style_notes_cleanly():
    guidance = telegram_ops._format_persona_guidance({
        'identity': '普通群友',
        'traits': ['短句'],
        'style_notes': ['像随手回一句'],
    })

    assert 'style_notes=像随手回一句' in guidance
    assert "['像随手回一句']" not in guidance


def test_round_report_tracks_and_formats_summary():
    report = telegram_ops.RoundReport(duration=60)

    report.record_batch(2)
    report.record_batch(1)
    report.record_prompt()
    report.record_prompt()
    report.record_skip('probability')
    report.record_skip('probability')
    report.record_skip('empty_input')
    report.record_sent_message(101)
    report.record_sent_message(102)
    report.record_sent_reply('短回复')
    report.record_initiative_prompt()
    report.record_initiative_skip('empty_input')
    report.record_initiative_sent([201])
    report.finish(12.345)

    assert report.as_dict() == {
        'duration': 60.0,
        'elapsed': 12.345,
        'received_batches': 2,
        'received_messages': 3,
        'prompted': 2,
        'sent_replies': 1,
        'sent_message_ids': [101, 102],
        'skip_reasons': {
            'probability': 2,
            'empty_input': 1,
        },
        'avg_reply_chars': 3.0,
        'initiative_prompts': 1,
        'initiative_sent': 1,
        'initiative_skipped': 1,
        'initiative_skip_reasons': {
            'empty_input': 1,
        },
        'initiative_sent_message_ids': [201],
    }
    assert telegram_ops._format_round_report(report) == [
        'Round report:',
        'duration=60.0s',
        'elapsed=12.3s',
        'received_batches=2',
        'received_messages=3',
        'prompted=2',
        'sent_replies=1',
        'sent_message_ids=101,102',
        'skip_reasons={"empty_input": 1, "probability": 2}',
        'avg_reply_chars=3.0',
        'initiative_prompts=1',
        'initiative_sent=1',
        'initiative_skipped=1',
        'initiative_sent_message_ids=201',
        'initiative_skip_reasons={"empty_input": 1}',
    ]
