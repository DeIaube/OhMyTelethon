import json
import sqlite3
from types import SimpleNamespace

import pytest

from tg_cli import cli
from tg_cli.config import AppConfig


def test_status_json_does_not_require_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(['status', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['paused'] is False
    assert data['allowed_chats'] == []
    assert data['session_path'].endswith('printer.session')
    assert data['state_path'].endswith('tg_cli/.tg-cli-state.json')
    assert data['audit_log_path'].endswith('tg_cli/tg-cli.audit.log')


def test_pause_and_resume_update_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli.main(['pause']) == 0
    assert 'Paused.' in capsys.readouterr().out

    assert cli.main(['status', '--json']) == 0
    paused = json.loads(capsys.readouterr().out)
    assert paused['paused'] is True

    assert cli.main(['resume']) == 0
    assert 'Resumed.' in capsys.readouterr().out

    assert cli.main(['status', '--json']) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed['paused'] is False


def test_groups_text_output_formats_username(monkeypatch, capsys):
    async def fake_list_dialogs(config, groups_only=False):
        return [{
            'id': 5217114569,
            'title': 'lu 和 王哥',
            'kind': 'chat',
            'username': None,
            'participants_count': 2,
        }]

    monkeypatch.setattr(cli, 'list_dialogs', fake_list_dialogs)

    cli._run(cli._cmd_groups(SimpleNamespace(json=False), config=None, groups_only=True))

    assert '[chat] lu 和 王哥 | id=5217114569 | username=- | members=2' in capsys.readouterr().out


def test_main_reports_session_database_lock(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TG_API_ID', '1')
    monkeypatch.setenv('TG_API_HASH', 'hash')

    async def fake_get_me(config):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(cli, 'get_me', fake_get_me)

    code = cli.main(['me'])

    captured = capsys.readouterr()
    assert code == 2
    assert 'Telegram session database is locked' in captured.err
    assert 'same session' in captured.err


def test_game_round_parser_defaults():
    parser = cli.build_parser()

    args = parser.parse_args(['game', 'round', '5217114569'])

    assert args.command == 'game'
    assert args.game_command == 'round'
    assert args.chat == '5217114569'
    assert args.duration is None
    assert args.limit is None
    assert args.max_replies is None
    assert args.include_self is False
    assert args.preset is None
    assert args.reply_probability is None
    assert args.mention_reply_probability is None
    assert args.random_delay_min is None
    assert args.random_delay_max is None
    assert args.skip_short_ack is None
    assert args.merge_window is None
    assert args.quiet_context is None
    assert args.split_long_replies is None


def test_daemon_parser_accepts_queue_commands():
    parser = cli.build_parser()

    run_args = parser.parse_args([
        'daemon', 'run', '5217114569',
        '--preset', 'chat_social',
        '--duration', '30',
        '--dry-run',
    ])
    next_args = parser.parse_args(['daemon', 'next', '--json'])
    reply_args = parser.parse_args([
        'daemon', 'reply', 'task-1', '短回复', '--dry-run', '--json'])
    skip_args = parser.parse_args([
        'daemon', 'skip', 'task-1', '--reason', 'unclear', '--json'])

    assert run_args.command == 'daemon'
    assert run_args.daemon_command == 'run'
    assert run_args.chat == '5217114569'
    assert run_args.preset == 'chat_social'
    assert run_args.duration == 30.0
    assert run_args.dry_run is True
    assert next_args.daemon_command == 'next'
    assert next_args.json is True
    assert reply_args.daemon_command == 'reply'
    assert reply_args.task_id == 'task-1'
    assert reply_args.text == '短回复'
    assert reply_args.dry_run is True
    assert reply_args.json is True
    assert skip_args.daemon_command == 'skip'
    assert skip_args.reason == 'unclear'


def test_quota_parser_accepts_run_commands():
    parser = cli.build_parser()

    start_args = parser.parse_args([
        'quota', 'start',
        '--chat', '-1001937176825:120',
        '--chat', '5217114569:300',
        '--preset', 'chat_social',
        '--json',
    ])
    status_args = parser.parse_args(['quota', 'status', '--json'])
    stop_args = parser.parse_args(['quota', 'stop', '--json'])
    next_args = parser.parse_args(['quota', 'next', '--json'])
    reply_args = parser.parse_args([
        'quota', 'reply', 'task-1', '短回复', '--dry-run', '--json'])

    assert start_args.command == 'quota'
    assert start_args.quota_command == 'start'
    assert start_args.chat == [
        {'chat_id': 1937176825, 'target_count': 120},
        {'chat_id': 5217114569, 'target_count': 300},
    ]
    assert start_args.preset == 'chat_social'
    assert start_args.json is True
    assert status_args.quota_command == 'status'
    assert status_args.json is True
    assert stop_args.quota_command == 'stop'
    assert stop_args.json is True
    assert next_args.quota_command == 'next'
    assert next_args.json is True
    assert reply_args.quota_command == 'reply'
    assert reply_args.task_id == 'task-1'
    assert reply_args.text == '短回复'
    assert reply_args.dry_run is True
    assert reply_args.json is True


def test_quota_parser_rejects_invalid_chat_targets(capsys):
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(['quota', 'start', '--chat', '5217114569'])
    with pytest.raises(SystemExit):
        parser.parse_args(['quota', 'start', '--chat', '5217114569:0'])

    captured = capsys.readouterr()
    assert 'CHAT_ID:COUNT' in captured.err or 'greater than 0' in captured.err


def test_game_suggest_parser_accepts_operator():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'suggest', '5217114569',
        '--preset', 'casual',
        '--operator', 'claude',
        '--json',
    ])

    assert args.command == 'game'
    assert args.game_command == 'suggest'
    assert args.chat == '5217114569'
    assert args.preset == 'casual'
    assert args.operator == 'claude'
    assert args.json is True


def test_game_context_parser_defaults_to_codex_operator():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'context', '5217114569',
        '--limit', '200',
        '--preset', 'chat_social',
        '--json',
    ])

    assert args.command == 'game'
    assert args.game_command == 'context'
    assert args.chat == '5217114569'
    assert args.limit == 200
    assert args.preset == 'chat_social'
    assert args.operator == 'codex'
    assert args.json is True


def test_game_round_parser_humanization_flags():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'round', '5217114569',
        '--preset', 'casual',
        '--reply-probability', '0.4',
        '--mention-reply-probability', '0.9',
        '--random-delay-min', '1.5',
        '--random-delay-max', '4',
        '--skip-short-ack',
        '--merge-window', '2',
    ])

    assert args.preset == 'casual'
    assert args.reply_probability == 0.4
    assert args.mention_reply_probability == 0.9
    assert args.random_delay_min == 1.5
    assert args.random_delay_max == 4.0
    assert args.skip_short_ack is True
    assert args.merge_window == 2.0
    assert args.quiet_context is None
    assert args.min_reply_interval is None
    assert args.end_buffer is None


def test_game_round_parser_accepts_operator_safety_flags():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'round', '5217114569',
        '--quiet-context',
        '--min-reply-interval', '1.5',
        '--end-buffer', '4',
    ])

    assert args.quiet_context is True
    assert args.min_reply_interval == 1.5
    assert args.end_buffer == 4.0


def test_game_round_uses_config_defaults_when_flags_are_omitted(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(['game', 'round', '5217114569'])
    seen = {}

    async def fake_interactive_round(config, chat, **kwargs):
        seen['config'] = config
        seen['chat'] = chat
        seen.update(kwargs)

    monkeypatch.setattr(cli, 'interactive_round', fake_interactive_round)
    config = SimpleNamespace(round={
        'duration': 120.0,
        'limit': 9,
        'max_replies': 4,
        'quiet_context': True,
        'min_reply_interval': 6.0,
        'end_buffer': 10.0,
        'reply_probability': 0.8,
        'mention_reply_probability': 1.0,
        'random_delay_min': 1.0,
        'random_delay_max': 3.0,
        'skip_short_ack': True,
        'merge_window': 2.0,
        'split_long_replies': True,
    })

    cli._run(cli._cmd_game(args, config))

    assert seen['chat'] == '5217114569'
    assert seen['duration'] == 120.0
    assert seen['limit'] == 9
    assert seen['max_replies'] == 4
    assert seen['quiet_context'] is True
    assert seen['min_reply_interval'] == 6.0
    assert seen['end_buffer'] == 10.0
    assert seen['reply_probability'] == 0.8
    assert seen['mention_reply_probability'] == 1.0
    assert seen['random_delay_min'] == 1.0
    assert seen['random_delay_max'] == 3.0
    assert seen['skip_short_ack'] is True
    assert seen['merge_window'] == 2.0
    assert seen['split_long_replies'] is True


def test_game_round_applies_preset_then_cli_flags(monkeypatch, tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args([
        'game', 'round', '5217114569',
        '--preset', 'casual',
        '--duration', '15',
        '--max-replies', '2',
    ])
    seen = {}

    async def fake_interactive_round(config, chat, **kwargs):
        seen['config'] = config
        seen['chat'] = chat
        seen.update(kwargs)

    monkeypatch.setattr(cli, 'interactive_round', fake_interactive_round)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        profile={'style': 'global style'},
        round_config={'duration': 120, 'max_replies': 8},
        presets={
            'casual': {
                'profile': {'style': 'casual style', 'max_chars': 42},
                'round': {'duration': 60, 'reply_probability': 0.25},
            },
        })

    cli._run(cli._cmd_game(args, config))

    assert seen['chat'] == '5217114569'
    assert seen['duration'] == 15.0
    assert seen['max_replies'] == 2
    assert seen['reply_probability'] == 0.25
    assert seen['config'].profile['style'] == 'casual style'
    assert seen['config'].profile['max_chars'] == 42
    assert seen['config'].round['duration'] == 15.0
    assert config.profile['style'] == 'global style'
    assert config.round['duration'] == 120.0


def test_game_suggest_json_applies_preset(monkeypatch, tmp_path, capsys):
    parser = cli.build_parser()
    args = parser.parse_args([
        'game', 'suggest', '5217114569',
        '--preset', 'casual',
        '--operator', 'codex',
        '--json',
    ])

    async def fake_codex_context(config, chat, limit, operator='agent', preset=None):
        return {
            'chat': {'id': int(chat), 'title': 'test chat'},
            'operator': operator,
            'preset': preset,
            'profile': dict(config.profile),
            'messages': [],
            'instruction': 'instruction',
        }

    monkeypatch.setattr(cli, 'codex_context', fake_codex_context)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        profile={'style': 'global style'},
        presets={
            'casual': {
                'profile': {'style': 'casual style'},
            },
        })

    cli._run(cli._cmd_game(args, config))

    data = json.loads(capsys.readouterr().out)
    assert data['operator'] == 'codex'
    assert data['preset'] == 'casual'
    assert data['profile']['style'] == 'casual style'


def test_game_context_json_applies_preset(monkeypatch, tmp_path, capsys):
    parser = cli.build_parser()
    args = parser.parse_args([
        'game', 'context', '5217114569',
        '--preset', 'casual',
        '--operator', 'claude',
        '--json',
    ])

    async def fake_group_context(config, chat, limit, operator='agent', preset=None):
        return {
            'chat': {'id': int(chat), 'title': 'test chat'},
            'operator': operator,
            'preset': preset,
            'profile': dict(config.profile),
            'persona': dict(config.persona),
            'reply_policy': dict(config.reply_policy),
            'initiative': dict(config.initiative),
            'message_count': 0,
            'active_speakers': [],
            'recent_topics': [],
            'keywords': [],
            'bot_or_notice_messages': {'count': 0, 'messages': []},
            'recent_questions': [],
            'summary': 'empty',
            'guidance': [],
            'messages_tail': [],
        }

    monkeypatch.setattr(cli, 'group_context', fake_group_context)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        profile={'style': 'global style'},
        persona={'identity': 'global persona'},
        presets={
            'casual': {
                'profile': {'style': 'casual style'},
                'persona': {'identity': 'casual persona'},
            },
        })

    cli._run(cli._cmd_game(args, config))

    data = json.loads(capsys.readouterr().out)
    assert data['operator'] == 'claude'
    assert data['preset'] == 'casual'
    assert data['profile']['style'] == 'casual style'
    assert data['persona']['identity'] == 'casual persona'


def test_daemon_status_json_does_not_require_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(['daemon', 'status', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['paused'] is False
    assert data['running'] is False
    assert data['queue_counts'] == {}
    assert data['queue_path'].endswith('tg_cli/.tg-cli-daemon-queue.json')
    assert data['lock_path'].endswith('tg_cli/.tg-cli-daemon.lock')


def test_quota_status_and_stop_do_not_require_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    class FakeQuotaStore:
        def status(self, path):
            return {
                'status': 'active',
                'state_path': str(path),
                'targets': [],
            }

        def stop_run(self, path):
            return {
                'run_id': 'quota-test',
                'status': 'stopped',
                'state_path': str(path),
            }

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())

    assert cli.main(['quota', 'status', '--json']) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload['status'] == 'active'
    assert status_payload['state_path'].endswith(
        'tg_cli/.tg-cli-quota-state.json')

    assert cli.main(['quota', 'stop', '--json']) == 0
    stop_payload = json.loads(capsys.readouterr().out)
    assert stop_payload['status'] == 'stopped'
    assert stop_payload['state_path'].endswith(
        'tg_cli/.tg-cli-quota-state.json')


def test_quota_start_enforces_allowed_chats_without_credentials(
        tmp_path, monkeypatch, capsys):
    captured = {}

    class FakeQuotaStore:
        def create_run(self, path, targets, preset=None):
            captured['path'] = path
            captured['targets'] = targets
            captured['preset'] = preset
            return {
                'run_id': 'quota-test',
                'status': 'active',
                'preset': preset,
                'targets': targets,
            }

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569, 1937176825],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota-state.json')},
        presets={'chat_social': {'profile': {'max_chars': 42}}},
    )

    args = cli.build_parser().parse_args([
        'quota', 'start',
        '--chat', '5217114569:120',
        '--chat', '-1001937176825:300',
        '--preset', 'chat_social',
        '--json',
    ])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['status'] == 'active'
    assert captured['path'] == config.quota['state_path']
    assert captured['targets'] == [
        {'chat_id': 5217114569, 'target_count': 120},
        {'chat_id': 1937176825, 'target_count': 300},
    ]
    assert captured['preset'] == 'chat_social'

    blocked_args = cli.build_parser().parse_args([
        'quota', 'start', '--chat', '999:1'])
    with pytest.raises(cli.SafetyError, match='not whitelisted'):
        cli._run(cli._cmd_quota(blocked_args, config))


def test_quota_next_creates_task_for_largest_remaining_target(
        tmp_path, monkeypatch, capsys):
    captured = {}

    async def no_context_payload(config):
        return None

    class FakeQuotaStore:
        def status(self, path):
            return {
                'run_id': 'quota-test',
                'status': 'active',
                'preset': 'chat_social',
                'targets': [
                    {
                        'chat_id': 1,
                        'target_count': 120,
                        'sent_count': 119,
                        'status': 'active',
                    },
                    {
                        'chat_id': 2,
                        'target_count': 300,
                        'sent_count': 10,
                        'status': 'active',
                    },
                ],
            }

        def create_task(self, path, chat_id, context=None):
            captured['path'] = path
            captured['chat_id'] = chat_id
            captured['context'] = context
            return {
                'id': 'task-2',
                'status': 'pending',
                'chat_id': chat_id,
            }

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())
    monkeypatch.setattr(cli, '_quota_next_context_payload', no_context_payload)
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[1, 2],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota-state.json')},
    )

    args = cli.build_parser().parse_args(['quota', 'next', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['id'] == 'task-2'
    assert captured['path'] == config.quota['state_path']
    assert captured['chat_id'] == 2
    assert captured['context'] is None


def test_quota_reply_dry_run_validates_without_completing_or_credentials(
        tmp_path, monkeypatch, capsys):
    captured = {}

    class FakeQuotaStore:
        def get_task(self, path, task_id):
            captured['get_path'] = path
            captured['task_id'] = task_id
            return {
                'id': task_id,
                'status': 'pending',
                'chat': {'id': 5217114569, 'title': 'test chat'},
                'profile': {'style': 'brief', 'forbidden_terms': []},
            }

        def complete_task(self, path, task_id, message_ids, dry_run=False):
            captured['complete_path'] = path
            captured['complete_task_id'] = task_id
            captured['message_ids'] = message_ids
            captured['dry_run'] = dry_run
            return {
                'id': task_id,
                'status': 'pending',
                'dry_run_checked': dry_run,
            }

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota-state.json')},
    )

    args = cli.build_parser().parse_args([
        'quota', 'reply', 'task-1', '来了', '--dry-run', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['sent'] is False
    assert payload['dry_run'] is True
    assert payload['message_ids'] == []
    assert payload['task']['status'] == 'pending'
    assert captured['get_path'] == config.quota['state_path']
    assert 'complete_path' not in captured


def test_daemon_next_skip_and_reply_queue_lifecycle(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        daemon_config={
            'queue_path': str(tmp_path / 'queue.json'),
            'lock_path': str(tmp_path / 'daemon.lock'),
            'status_path': str(tmp_path / 'status.json'),
            'task_ttl': 3600,
        })
    task = cli.daemon_store.create_task(
        chat={'id': 5217114569, 'title': 'test chat'},
        messages=[{'id': 1, 'sender': 'p1', 'text': '在吗'}],
        profile={'style': 'brief'},
        persona={},
        reply_policy={},
        initiative={},
        preset='chat_social',
        prompt='Reply if useful.')
    cli.daemon_store.append_task(config.daemon['queue_path'], task)

    next_args = cli.build_parser().parse_args(['daemon', 'next', '--json'])
    cli._run(cli._cmd_daemon(next_args, config))
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload['id'] == task['id']
    assert next_payload['status'] == 'claimed'
    assert 'claim_expires_at' in next_payload

    reply_args = cli.build_parser().parse_args([
        'daemon', 'reply', task['id'], '来了', '--json'])
    cli._run(cli._cmd_daemon(reply_args, config))
    reply_payload = json.loads(capsys.readouterr().out)
    assert reply_payload['queued'] is True
    assert reply_payload['task']['status'] == 'reply_pending'
    assert reply_payload['task']['reply_text'] == '来了'

    skip_args = cli.build_parser().parse_args([
        'daemon', 'skip', task['id'], '--reason', 'changed', '--json'])
    cli._run(cli._cmd_daemon(skip_args, config))
    skip_payload = json.loads(capsys.readouterr().out)
    assert skip_payload['skipped'] is True
    assert skip_payload['task']['status'] == 'skipped'
    assert skip_payload['task']['reason'] == 'changed'


def test_daemon_run_applies_preset_daemon_overlay(tmp_path, monkeypatch):
    captured = {}

    async def fake_daemon_run(
            config, chat, preset=None, duration=3600.0, dry_run=False,
            output_func=print):
        captured['chat'] = chat
        captured['preset'] = preset
        captured['duration'] = duration
        captured['dry_run'] = dry_run
        captured['daemon'] = dict(config.daemon)

    monkeypatch.setattr(cli, 'daemon_run', fake_daemon_run)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        daemon_config={
            'queue_path': str(tmp_path / 'queue.json'),
            'lock_path': str(tmp_path / 'daemon.lock'),
            'status_path': str(tmp_path / 'status.json'),
            'min_reply_interval': 6,
            'max_messages_per_hour': 20,
        },
        presets={
            'chat_social': {
                'daemon': {
                    'min_reply_interval': 2,
                    'max_messages_per_hour': 240,
                    'max_consecutive_replies': 4,
                },
            },
        })

    args = cli.build_parser().parse_args([
        'daemon', 'run', '5217114569',
        '--preset', 'chat_social',
        '--duration', '60',
        '--dry-run',
    ])
    cli._run(cli._cmd_daemon(args, config))

    assert captured['chat'] == '5217114569'
    assert captured['preset'] == 'chat_social'
    assert captured['duration'] == 60
    assert captured['dry_run'] is True
    assert captured['daemon']['min_reply_interval'] == 2.0
    assert captured['daemon']['max_messages_per_hour'] == 240
    assert captured['daemon']['max_consecutive_replies'] == 4


def test_daemon_reply_dry_run_does_not_consume_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        daemon_config={
            'queue_path': str(tmp_path / 'queue.json'),
            'lock_path': str(tmp_path / 'daemon.lock'),
            'status_path': str(tmp_path / 'status.json'),
            'task_ttl': 3600,
        })
    task = cli.daemon_store.create_task(
        chat={'id': 5217114569, 'title': 'test chat'},
        messages=[{'id': 1, 'sender': 'p1', 'text': '在吗'}],
        profile={'style': 'brief'},
        persona={},
        reply_policy={},
        initiative={},
        preset='chat_social',
        prompt='Reply if useful.')
    cli.daemon_store.append_task(config.daemon['queue_path'], task)

    reply_args = cli.build_parser().parse_args([
        'daemon', 'reply', task['id'], '来了', '--dry-run', '--json'])
    cli._run(cli._cmd_daemon(reply_args, config))

    reply_payload = json.loads(capsys.readouterr().out)
    assert reply_payload['queued'] is False
    assert reply_payload['dry_run'] is True
    assert reply_payload['task']['dry_run_checked'] is True
    saved = cli.daemon_store.get_task(config.daemon['queue_path'], task['id'])
    assert saved['status'] == 'pending'
