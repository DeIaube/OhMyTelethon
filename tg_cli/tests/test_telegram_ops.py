import asyncio
from types import SimpleNamespace

from tg_cli.config import AppConfig
from tg_cli import daemon
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
        daemon_config={
            'queue_path': str(tmp_path / 'queue.json'),
            'lock_path': str(tmp_path / 'daemon.lock'),
            'status_path': str(tmp_path / 'status.json'),
            'min_reply_interval': 1.0,
            'max_messages_per_hour': 20,
            'max_consecutive_replies': 20,
        },
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


def test_daemon_reply_counts_ignore_current_reply_pending_task(tmp_path):
    queue_path = tmp_path / 'queue.json'
    first = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    second = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:01+00:00')
    third = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:02+00:00')
    daemon.append_task(queue_path, first)
    daemon.complete_task(queue_path, first['id'], message_id=1)
    daemon.append_task(queue_path, second)
    daemon.complete_task(queue_path, second['id'], message_id=2)
    daemon.append_task(queue_path, third)
    daemon.queue_reply_task(queue_path, third['id'], '来了')

    assert telegram_ops._daemon_reply_counts(
        queue_path,
        5217114569,
        now=telegram_ops._daemon_parse_time('2026-06-01T00:01:00+00:00')) == (
            2, 2)


def test_daemon_send_reply_rechecks_stop_after_rate_limit_sleep(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    task = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    daemon.append_task(config.daemon['queue_path'], task)
    queued = daemon.queue_reply_task(config.daemon['queue_path'], task['id'], '来了')
    sent_texts = []

    class FakeClient:
        async def send_message(self, entity, text):
            sent_texts.append((entity, text))
            return SimpleNamespace(id=77)

    async def fake_sleep(delay):
        daemon.request_stop(config.daemon['status_path'])

    monkeypatch.setattr(telegram_ops.asyncio, 'sleep', fake_sleep)

    async def run():
        loop = asyncio.get_running_loop()
        return await telegram_ops._daemon_send_reply_task(
            FakeClient(),
            entity='entity',
            config=config,
            row={'id': 5217114569, 'title': 'chat'},
            task=queued,
            last_sent_at=loop.time(),
            dry_run=False,
            emit=lambda text='': None)

    assert asyncio.run(run()) is not None
    assert sent_texts == []
    saved = daemon.get_task(config.daemon['queue_path'], task['id'])
    assert saved['status'] == 'reply_pending'


def test_daemon_run_releases_lock_when_client_start_fails(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    disconnected = []

    class FailingClient:
        async def start(self):
            raise RuntimeError('start failed')

        async def disconnect(self):
            disconnected.append(True)

    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: FailingClient())

    with pytest.raises(RuntimeError, match='start failed'):
        asyncio.run(telegram_ops.daemon_run(
            config, '5217114569', duration=1,
            output_func=lambda text='': None))

    assert disconnected == [True]
    assert config.daemon['lock_path'].exists() is False


def test_daemon_run_refreshes_lock_on_status_updates(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    refresh_owners = []
    original_refresh_lock = daemon.refresh_lock

    class FakeClient:
        async def start(self):
            return None

        async def get_me(self):
            return SimpleNamespace(
                id=999, username='agent', first_name='Agent', last_name=None)

        def on(self, event):
            def decorator(handler):
                return handler
            return decorator

        async def disconnect(self):
            return None

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'chat'}

    def wrapped_refresh_lock(path, owner=None, now=None):
        refresh_owners.append(owner)
        return original_refresh_lock(path, owner=owner, now=now)

    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: FakeClient())
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)
    monkeypatch.setattr(
        telegram_ops.daemon_store, 'refresh_lock', wrapped_refresh_lock)

    asyncio.run(telegram_ops.daemon_run(
        config, '5217114569', duration=0,
        output_func=lambda text='': None))

    assert len(refresh_owners) >= 2
    assert all(owner and owner.startswith('tg-cli-daemon:') for owner in refresh_owners)
    assert config.daemon['lock_path'].exists() is False


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
