import asyncio
import copy
from types import SimpleNamespace

from tg_cli.config import AppConfig
from tg_cli import daemon
from tg_cli import safety
from tg_cli import telegram_ops
import pytest


def make_config(tmp_path, profile=None, presets=None):
    return AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        profile=profile,
        presets=presets,
        daemon_config={
            'queue_path': str(tmp_path / 'queue.json'),
            'lock_path': str(tmp_path / 'daemon.lock'),
            'status_path': str(tmp_path / 'status.json'),
            'min_reply_interval': 1.0,
            'max_messages_per_hour': 20,
            'max_consecutive_replies': 20,
        },
        quota_config={
            'state_path': str(tmp_path / 'quota.json'),
        },
    )


class FakeQuotaStore:
    def __init__(self, status, task=None):
        self.status_payload = copy.deepcopy(status)
        self.task = copy.deepcopy(task) if task is not None else None
        self.created_tasks = []
        self.completed = []

    def get_status(self, path):
        return copy.deepcopy(self.status_payload)

    def next_target(self, path):
        for target in self.status_payload.get('targets') or []:
            if target.get('status') == 'active':
                target_count = int(target.get('target_count') or 0)
                sent_count = int(target.get('sent_count') or 0)
                if sent_count < target_count:
                    return copy.deepcopy(target)
        return None

    def create_task(self, path, chat_id, context=None):
        task = {
            'id': 'quota-task-1',
            'status': 'pending',
            'chat_id': int(chat_id),
            'context': copy.deepcopy(context or {}),
        }
        self.task = copy.deepcopy(task)
        self.created_tasks.append(copy.deepcopy(task))
        return copy.deepcopy(task)

    def get_task(self, path, task_id):
        if self.task and self.task.get('id') == task_id:
            return copy.deepcopy(self.task)
        return None

    def begin_task(self, path, task_id, expected_message_count=1):
        if self.task and self.task.get('id') == task_id:
            if self.task.get('status') != 'pending':
                return None
            self.task['status'] = 'sending'
            self.task['expected_message_count'] = int(expected_message_count)
            return copy.deepcopy(self.task)
        return None

    def complete_task(self, path, task_id, message_ids, dry_run=False):
        self.completed.append({
            'task_id': task_id,
            'message_ids': list(message_ids),
            'dry_run': bool(dry_run),
        })
        if self.task and self.task.get('id') == task_id:
            self.task['status'] = 'completed'
            self.task['message_ids'] = list(message_ids)
        for target in self.status_payload.get('targets') or []:
            if self.task and int(target.get('chat_id')) == int(self.task.get('chat_id')):
                target['sent_count'] = int(target.get('sent_count') or 0) + len(message_ids)
                if int(target.get('sent_count')) >= int(target.get('target_count')):
                    target['status'] = 'done'
        return copy.deepcopy(self.task)


class FakeTelegramClient:
    def __init__(self):
        self.sent_texts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_message(self, entity, text):
        self.sent_texts.append((entity, text))
        return SimpleNamespace(id=100 + len(self.sent_texts))


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


def test_group_context_summarizes_recent_history(monkeypatch, tmp_path):
    async def fake_history(config, chat, limit):
        assert chat == '5217114569'
        assert limit == 200
        return {'id': 5217114569, 'title': 'test chat'}, [
            {
                'id': 1,
                'date': '2026-06-01T00:00:00+00:00',
                'sender_id': 2,
                'sender': 'alice',
                'out': False,
                'text': '今晚开黑吗？',
            },
            {
                'id': 2,
                'date': '2026-06-01T00:00:02+00:00',
                'sender_id': 3,
                'sender': 'bot',
                'out': False,
                'text': 'alice joined the group',
            },
            {
                'id': 3,
                'date': '2026-06-01T00:00:05+00:00',
                'sender_id': 4,
                'sender': 'bob',
                'out': False,
                'text': '开黑开黑，我打野',
            },
            {
                'id': 4,
                'date': '2026-06-01T00:00:09+00:00',
                'sender_id': 2,
                'sender': 'alice',
                'out': False,
                'text': '那先等三分钟',
            },
        ]

    monkeypatch.setattr(telegram_ops, 'history', fake_history)
    config = make_config(tmp_path, profile={'style': 'brief'})
    config.persona = {'identity': '普通群友'}
    config.reply_policy = {'prefer_reply_when': ['direct question']}
    config.initiative = {'enabled': False}

    data = asyncio.run(telegram_ops.group_context(
        config, '5217114569', 200, operator='codex', preset='chat_social'))

    assert data['operator'] == 'codex'
    assert data['preset'] == 'chat_social'
    assert data['message_count'] == 4
    assert data['active_speakers'][0] == {
        'sender': 'alice',
        'sender_id': 2,
        'count': 2,
    }
    assert '开黑' in data['recent_topics']
    assert data['keywords'][0]['text'] == '开黑'
    assert data['recent_questions'][0]['id'] == 1
    assert data['bot_or_notice_messages']['count'] == 1
    assert len(data['messages_tail']) == 4
    assert '最近 4 条消息' in data['summary']
    assert 'Codex/Claude' not in data['summary']
    assert data['guidance']


def test_task_context_summary_drops_raw_message_tail(tmp_path):
    config = make_config(tmp_path)
    context = telegram_ops.summarize_group_context(
        config,
        {'id': 5217114569, 'title': 'test chat'},
        [{
            'id': 1,
            'date': '2026-06-01T00:00:00+00:00',
            'sender_id': 2,
            'sender': 'alice',
            'out': False,
            'text': '今晚开黑吗？',
        }],
        operator='daemon',
        preset='public_group_safe')

    task_summary = telegram_ops._task_context_summary(context)

    assert task_summary['message_count'] == 1
    assert task_summary['recent_topics']
    assert task_summary['recent_questions'][0]['id'] == 1
    assert 'messages_tail' not in task_summary
    assert 'profile' not in task_summary


def test_quota_next_context_creates_task_with_recent_context(
        tmp_path, monkeypatch):
    config = make_config(
        tmp_path,
        presets={
            'chat_social': {
                'profile': {
                    'style': 'preset style',
                    'forbidden_terms': ['blocked'],
                },
                'round': {
                    'split_long_replies': True,
                    'split_max_chars': 4,
                },
                'persona': {'identity': 'preset persona'},
            },
        })
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'preset': 'chat_social',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 3,
            'sent_count': 1,
            'status': 'active',
        }],
    })
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        assert client is fake_client
        assert int(chat) == 5217114569
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    async def fake_recent_context(client, entity, limit):
        assert client is fake_client
        assert entity == 'entity'
        assert limit == 2
        return [
            {'id': 1, 'sender': 'alice', 'out': False, 'text': '今晚开黑吗？'},
            {'id': 2, 'sender': 'bob', 'out': False, 'text': '开黑开黑'},
        ]

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)
    monkeypatch.setattr(
        telegram_ops, '_recent_context_lines', fake_recent_context)

    data = asyncio.run(telegram_ops.quota_next_context(
        config, limit=2, operator='codex'))

    assert data['task']['id'] == 'quota-task-1'
    assert data['context']['chat']['title'] == 'quota chat'
    assert data['context']['operator'] == 'codex'
    assert data['context']['preset'] == 'chat_social'
    assert data['context']['profile']['style'] == 'preset style'
    assert data['context']['profile']['forbidden_terms'] == ['blocked']
    assert data['context']['persona']['identity'] == 'preset persona'
    assert data['context']['round']['split_long_replies'] is True
    assert data['context']['quota']['remaining'] == 2
    assert data['context']['messages'][-1]['text'] == '开黑开黑'
    assert 'prompt' in data['context']
    assert quota.created_tasks[0]['context']['context_summary']['message_count'] == 2


def test_quota_reply_dry_run_validates_without_completing_or_sending(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    config.round['split_long_replies'] = True
    config.round['split_max_chars'] = 4
    config.round['split_max_parts'] = 3
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 5,
            'sent_count': 0,
            'status': 'active',
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)

    result = asyncio.run(telegram_ops.quota_reply(
        config, 'quota-task-1', '一二三四五六七八', dry_run=True))

    assert result['dry_run'] is True
    assert result['sent'] is False
    assert result['message_ids'] == []
    assert result['parts'] == ['一二三四', '五六七八']
    assert fake_client.sent_texts == []
    assert quota.completed == []
    assert quota.get_task(config.quota['state_path'], 'quota-task-1')['status'] == 'pending'


def test_quota_reply_dry_run_uses_task_context_profile_without_credentials(
        tmp_path, monkeypatch):
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota.json')},
    )
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'context': {
            'profile': {'forbidden_terms': ['禁词']},
            'round': {
                'split_long_replies': True,
                'split_max_chars': 4,
                'split_max_parts': 3,
            },
        },
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 5,
            'sent_count': 0,
            'status': 'active',
        }],
    }, task=task)

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)

    with pytest.raises(safety.SafetyError, match='禁词'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '这里有禁词', dry_run=True))

    result = asyncio.run(telegram_ops.quota_reply(
        config, 'quota-task-1', '一二三四五六七八', dry_run=True))
    assert result['parts'] == ['一二三四', '五六七八']
    assert quota.completed == []


def test_quota_reply_sends_split_parts_and_counts_actual_message_ids(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    config.round['split_long_replies'] = True
    config.round['split_max_chars'] = 4
    config.round['split_max_parts'] = 3
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 2,
            'sent_count': 0,
            'status': 'active',
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)

    result = asyncio.run(telegram_ops.quota_reply(
        config, 'quota-task-1', '一二三四五六七八'))

    assert result['sent'] is True
    assert result['message_ids'] == [101, 102]
    assert fake_client.sent_texts == [
        ('entity', '一二三四'),
        ('entity', '五六七八'),
    ]
    assert quota.completed == [{
        'task_id': 'quota-task-1',
        'message_ids': [101, 102],
        'dry_run': False,
    }]
    target = quota.get_status(config.quota['state_path'])['targets'][0]
    assert target['sent_count'] == 2
    assert target['status'] == 'done'


def test_quota_reply_blocks_hourly_limit_without_sending(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    config.daemon['max_messages_per_hour'] = 1
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 3,
            'sent_count': 1,
            'status': 'active',
        }],
        'tasks': [{
            'id': 'completed-task',
            'status': 'completed',
            'chat_id': 5217114569,
            'updated_at': telegram_ops._dt.datetime.now(
                telegram_ops._dt.timezone.utc).isoformat(),
            'message_ids': [99],
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)

    with pytest.raises(telegram_ops.TelegramCliError, match='hourly'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '再来一句'))

    assert fake_client.sent_texts == []
    assert quota.completed == []


def test_quota_reply_uses_preset_daemon_rate_limits(tmp_path, monkeypatch):
    config = make_config(
        tmp_path,
        presets={
            'chat_social': {
                'daemon': {'max_messages_per_hour': 1},
            },
        })
    config.daemon['max_messages_per_hour'] = 20
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'preset': 'chat_social',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 3,
            'sent_count': 1,
            'status': 'active',
        }],
        'tasks': [{
            'id': 'completed-task',
            'status': 'completed',
            'chat_id': 5217114569,
            'updated_at': telegram_ops._dt.datetime.now(
                telegram_ops._dt.timezone.utc).isoformat(),
            'message_ids': [99],
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)

    with pytest.raises(telegram_ops.TelegramCliError, match='hourly'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '再来一句'))

    assert fake_client.sent_texts == []
    assert quota.completed == []


def test_quota_reply_rechecks_run_after_begin_task(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }

    class StoppingQuotaStore(FakeQuotaStore):
        def begin_task(self, path, task_id, expected_message_count=1):
            begun = super().begin_task(
                path, task_id,
                expected_message_count=expected_message_count)
            self.status_payload['status'] = 'stopped'
            return begun

    quota = StoppingQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 3,
            'sent_count': 0,
            'status': 'active',
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    async def fake_resolve_chat(client, chat):
        return 'entity', {'id': 5217114569, 'title': 'quota chat'}

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)

    with pytest.raises(telegram_ops.TelegramCliError, match='stopped'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '再来一句'))

    assert fake_client.sent_texts == []
    assert quota.completed == []


def test_quota_reply_blocks_completed_target_without_sending(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'active',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 2,
            'sent_count': 2,
            'status': 'done',
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)

    with pytest.raises(telegram_ops.TelegramCliError, match='done'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '还有一句'))

    assert fake_client.sent_texts == []
    assert quota.completed == []


def test_quota_reply_blocks_stopped_run_without_sending(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    task = {
        'id': 'quota-task-1',
        'status': 'pending',
        'chat_id': 5217114569,
        'profile': {},
    }
    quota = FakeQuotaStore({
        'run_id': 'quota-1',
        'status': 'stopped',
        'targets': [{
            'chat_id': 5217114569,
            'target_count': 2,
            'sent_count': 0,
            'status': 'active',
        }],
    }, task=task)
    fake_client = FakeTelegramClient()

    monkeypatch.setattr(telegram_ops, 'quota_store', quota)
    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: fake_client)

    with pytest.raises(telegram_ops.TelegramCliError, match='stopped'):
        asyncio.run(telegram_ops.quota_reply(
            config, 'quota-task-1', '还有一句'))

    assert fake_client.sent_texts == []
    assert quota.completed == []


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


def test_initiative_instruction_explains_topic_shift_fallback():
    prompt = telegram_ops._initiative_instruction(
        profile={'language': '中文', 'style': 'social', 'max_chars': 80},
        persona={'identity': 'regular member'},
        reply_policy={'skip_when': ['ads', 'grey area']},
        initiative={
            'enabled': True,
            'allow_topic_shift': True,
            'topic_shift_when': ['ads', 'grey area'],
            'topic_shift_style': 'casual pivot',
            'fallback_topics': ['晚上有人开黑吗'],
            'topics': ['刚才聊到哪了'],
        },
        preset='chat_social',
        idle_seconds=42,
        recent_messages=[
            {'id': 1, 'sender': 'spam', 'text': '广告'},
        ],
    )

    assert 'allow_topic_shift=True' in prompt
    assert 'fallback_topics=晚上有人开黑吗' in prompt
    assert 'start one neutral fallback topic' in prompt
    assert 'Do not explain the subject change' in prompt


def test_initiative_min_start_uses_round_start_instead_of_activity():
    initiative = {
        'enabled': True,
        'idle_after': 30,
        'cooldown': 75,
        'max_starts': 2,
        'min_starts': 1,
        'min_start_after': 45,
    }

    assert telegram_ops._initiative_wait_seconds(
        initiative,
        now=1040,
        started_at=1000,
        last_activity_at=1039,
        last_initiative_at=None,
        initiative_starts=0) == 5.0
    assert telegram_ops._initiative_wait_seconds(
        initiative,
        now=1045,
        started_at=1000,
        last_activity_at=1044,
        last_initiative_at=None,
        initiative_starts=0) == 0.0


def test_initiative_min_start_bypasses_active_gate_until_floor_met():
    initiative = {
        'enabled': True,
        'max_starts': 2,
        'min_starts': 1,
    }

    assert telegram_ops._initiative_allows_active_bypass(
        initiative, initiative_starts=0) is True
    assert telegram_ops._initiative_allows_active_bypass(
        initiative, initiative_starts=1) is False


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


def test_daemon_reply_counts_hourly_ignores_pending_breaks(tmp_path):
    queue_path = tmp_path / 'queue.json'
    completed = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    pending = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:30+00:00')
    daemon.append_task(queue_path, completed)
    daemon.complete_task(queue_path, completed['id'], message_id=1)
    daemon.append_task(queue_path, pending)

    assert telegram_ops._daemon_reply_counts(
        queue_path,
        5217114569,
        now=telegram_ops._daemon_parse_time('2026-06-01T00:01:00+00:00')) == (
            1, 0)


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


def test_daemon_send_reply_holds_task_when_hourly_limit_reached(tmp_path):
    config = make_config(tmp_path)
    config.daemon['max_messages_per_hour'] = 1
    completed = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    pending = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:01+00:00')
    daemon.append_task(config.daemon['queue_path'], completed)
    daemon.complete_task(config.daemon['queue_path'], completed['id'], message_id=1)
    daemon.append_task(config.daemon['queue_path'], pending)
    queued = daemon.queue_reply_task(
        config.daemon['queue_path'], pending['id'], '来了')
    sent_texts = []

    class FakeClient:
        async def send_message(self, entity, text):
            sent_texts.append((entity, text))
            return SimpleNamespace(id=77)

    async def run():
        return await telegram_ops._daemon_send_reply_task(
            FakeClient(),
            entity='entity',
            config=config,
            row={'id': 5217114569, 'title': 'chat'},
            task=queued,
            last_sent_at=None,
            dry_run=False,
            emit=lambda text='': None)

    assert asyncio.run(run()) is None
    assert sent_texts == []
    saved = daemon.get_task(config.daemon['queue_path'], pending['id'])
    assert saved['status'] == 'held_rate_limit'
    assert saved['rate_limit_reason'] == 'hourly_limit'
    assert 'retry_after' in saved


def test_daemon_send_reply_splits_long_reply_and_counts_parts(tmp_path):
    config = make_config(tmp_path)
    config.daemon['min_reply_interval'] = 0
    config.daemon['max_messages_per_hour'] = 10
    config.daemon['max_consecutive_replies'] = 10
    config.round['split_long_replies'] = True
    config.round['split_max_chars'] = 4
    config.round['split_max_parts'] = 3
    config.round['split_delay_min'] = 0
    config.round['split_delay_max'] = 0
    task = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    daemon.append_task(config.daemon['queue_path'], task)
    queued = daemon.queue_reply_task(
        config.daemon['queue_path'], task['id'], '一二三四五六七八')
    sent_texts = []

    class FakeClient:
        async def send_message(self, entity, text):
            sent_texts.append(text)
            return SimpleNamespace(id=100 + len(sent_texts))

    async def run():
        return await telegram_ops._daemon_send_reply_task(
            FakeClient(),
            entity='entity',
            config=config,
            row={'id': 5217114569, 'title': 'chat'},
            task=queued,
            last_sent_at=None,
            dry_run=False,
            emit=lambda text='': None)

    assert asyncio.run(run()) is not None
    assert sent_texts == ['一二三四', '五六七八']
    saved = daemon.get_task(config.daemon['queue_path'], task['id'])
    assert saved['status'] == 'completed'
    assert saved['message_id'] == 101
    assert saved['message_ids'] == [101, 102]
    assert telegram_ops._daemon_reply_counts(
        config.daemon['queue_path'],
        5217114569,
        now=telegram_ops._daemon_parse_time('2026-06-01T00:01:00+00:00')) == (
            2, 2)


def test_daemon_send_reply_holds_when_split_parts_exceed_consecutive_limit(
        tmp_path):
    config = make_config(tmp_path)
    config.daemon['min_reply_interval'] = 0
    config.daemon['max_messages_per_hour'] = 10
    config.daemon['max_consecutive_replies'] = 1
    config.round['split_long_replies'] = True
    config.round['split_max_chars'] = 4
    config.round['split_max_parts'] = 3
    config.round['split_delay_min'] = 0
    config.round['split_delay_max'] = 0
    task = daemon.create_task(
        chat={'id': 5217114569, 'title': 'chat'},
        messages=[],
        profile={},
        persona={},
        reply_policy={},
        initiative={},
        now='2026-06-01T00:00:00+00:00')
    daemon.append_task(config.daemon['queue_path'], task)
    queued = daemon.queue_reply_task(
        config.daemon['queue_path'], task['id'], '一二三四五六七八')
    sent_texts = []

    class FakeClient:
        async def send_message(self, entity, text):
            sent_texts.append(text)
            return SimpleNamespace(id=77)

    async def run():
        return await telegram_ops._daemon_send_reply_task(
            FakeClient(),
            entity='entity',
            config=config,
            row={'id': 5217114569, 'title': 'chat'},
            task=queued,
            last_sent_at=None,
            dry_run=False,
            emit=lambda text='': None)

    assert asyncio.run(run()) is None
    assert sent_texts == []
    saved = daemon.get_task(config.daemon['queue_path'], task['id'])
    assert saved['status'] == 'held_rate_limit'
    assert saved['rate_limit_reason'] == 'consecutive_limit'


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

        async def iter_messages(self, entity, limit=None):
            if False:
                yield None

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


def test_daemon_run_does_not_queue_slow_initiative_after_duration(
        tmp_path, monkeypatch):
    config = make_config(tmp_path)
    config.initiative = {
        'enabled': True,
        'idle_after': 0,
        'cooldown': 0,
        'max_starts': 1,
        'min_starts': 1,
        'min_start_after': 0,
        'avoid_when_active': False,
        'active_threshold': 0,
        'recent_window': 1,
        'topics': [],
        'allowed_intents': [],
        'forbidden_topics': [],
    }
    outputs = []
    recent_calls = {'count': 0}

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

    async def fake_recent_context(client, entity, limit):
        recent_calls['count'] += 1
        if recent_calls['count'] == 1:
            return []
        await asyncio.sleep(0.02)
        return [{'id': 1, 'sender': 'p1', 'text': 'hello', 'out': False}]

    monkeypatch.setattr(telegram_ops, '_client', lambda cfg: FakeClient())
    monkeypatch.setattr(telegram_ops, 'resolve_chat', fake_resolve_chat)
    monkeypatch.setattr(
        telegram_ops, '_recent_context_lines', fake_recent_context)

    asyncio.run(telegram_ops.daemon_run(
        config, '5217114569', duration=0.01,
        output_func=lambda text='': outputs.append(text)))

    assert recent_calls['count'] >= 2
    assert not any('Queued daemon task' in item for item in outputs)
    assert daemon.queue_counts(config.daemon['queue_path']) == {}
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
