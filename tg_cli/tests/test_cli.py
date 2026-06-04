import json
import sqlite3
from types import SimpleNamespace

import pytest

from tg_cli import bad_cases as bad_case_store
from tg_cli import cli
from tg_cli.config import AppConfig


def test_status_json_does_not_require_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(['status', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['account_name'] == ''
    assert data['paused'] is False
    assert data['allowed_chats'] == []
    assert data['session_path'].endswith('printer.session')
    assert data['state_path'].endswith('tg_cli/.tg-cli-state.json')
    assert data['audit_log_path'].endswith('tg_cli/tg-cli.audit.log')


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


def test_main_reports_json_error_for_json_command(
        monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TG_API_ID', '1')
    monkeypatch.setenv('TG_API_HASH', 'hash')

    async def fake_get_me(config):
        raise cli.TelegramCliError('synthetic failure')

    monkeypatch.setattr(cli, 'get_me', fake_get_me)

    code = cli.main(['me', '--json'])

    captured = capsys.readouterr()
    assert code == 2
    data = json.loads(captured.err)
    assert data == {
        'ok': False,
        'error': {
            'code': 'telegram_cli_error',
            'message': 'synthetic failure',
            'type': 'TelegramCliError',
        },
    }


def test_main_reports_session_database_lock_json(
        monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TG_API_ID', '1')
    monkeypatch.setenv('TG_API_HASH', 'hash')

    async def fake_get_me(config):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(cli, 'get_me', fake_get_me)

    code = cli.main(['me', '--json'])

    captured = capsys.readouterr()
    assert code == 2
    data = json.loads(captured.err)
    assert data['ok'] is False
    assert data['error']['code'] == 'session_database_locked'
    assert 'same session' in data['error']['message']
    assert data['error']['hint'].startswith('Serialize live tg-cli commands')


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


def test_agent_discovery_parser_accepts_capabilities_and_doctor():
    parser = cli.build_parser()

    capabilities_args = parser.parse_args(['capabilities', '--json'])
    doctor_args = parser.parse_args(['doctor', 'agent', '--json'])

    assert capabilities_args.command == 'capabilities'
    assert capabilities_args.json is True
    assert doctor_args.command == 'doctor'
    assert doctor_args.doctor_command == 'agent'
    assert doctor_args.json is True


def test_capabilities_json_outputs_command_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(['capabilities', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['schema_version'] == 1
    assert data['generated_from'] == 'argparse'
    commands = {item['command']: item for item in data['commands']}
    assert 'tg-cli capabilities' in commands
    assert commands['tg-cli capabilities']['risk'] == 'local'
    assert 'tg-cli doctor agent' in commands
    assert commands['tg-cli doctor agent']['credential_mode'] == 'not_required'
    assert 'tg-cli messages send' in commands
    assert commands['tg-cli messages send']['supports_dry_run'] is True
    assert commands['tg-cli messages send']['risk'] == 'write'
    assert data['agent_entrypoints']['preflight'] == 'tg-cli doctor agent --json'
    assert data['json_error_schema']['ok'] is False


def test_capabilities_json_ignores_invalid_local_config(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'broken.json'
    config_path.write_text('[]', encoding='utf-8')

    code = cli.main([
        '--config', str(config_path), 'capabilities', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['schema_version'] == 1
    assert any(
        item['command'] == 'tg-cli capabilities'
        for item in data['commands'])


def test_agent_doctor_json_does_not_require_credentials(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'agent.json'
    config_path.write_text(json.dumps({
        'account_name': 'agent-a',
        'session_path': 'agent-a.session',
        'allowed_chats': [5217114569],
    }), encoding='utf-8')

    code = cli.main([
        '--config', str(config_path), 'doctor', 'agent', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['schema_version'] == 1
    assert data['account_name'] == 'agent-a'
    assert data['allowed_chats'] == [5217114569]
    assert data['readiness']['local_inspection'] is True
    assert data['readiness']['telegram_io'] is False
    assert data['runtime_paths']['session_path'].endswith('agent-a.session')
    assert any(
        finding['code'] == 'missing_credentials'
        for finding in data['findings'])
    assert any(
        item['path'].endswith('tg_cli/docs/agent-recipes.md')
        for item in data['docs'])


def test_config_inspect_json_outputs_account_and_paths(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'account-a.json'
    config_path.write_text(json.dumps({
        'account_name': 'account-a',
        'session_path': 'account-a.session',
        'state_path': 'account-a.state.json',
        'audit_log_path': 'account-a.audit.log',
        'allowed_chats': [5217114569],
    }), encoding='utf-8')

    code = cli.main([
        '--config', str(config_path), 'config', 'inspect', '--json'])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['account_name'] == 'account-a'
    assert data['allowed_chats'] == [5217114569]
    assert data['runtime_paths']['session_path'].endswith('account-a.session')


def test_config_doctor_json_reports_shared_paths(
        tmp_path, monkeypatch, capsys):
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


def test_scenario_parser_accepts_commands():
    parser = cli.build_parser()

    list_args = parser.parse_args([
        'scenario', 'list', '--path', 'scenarios.json', '--json'])
    show_args = parser.parse_args([
        'scenario', 'show', 'newmei-afuan-150',
        '--path', 'scenarios.json', '--json'])
    start_args = parser.parse_args([
        'scenario', 'start', 'newmei-afuan-150',
        '--path', 'scenarios.json', '--json'])

    assert list_args.command == 'scenario'
    assert list_args.scenario_command == 'list'
    assert list_args.path == 'scenarios.json'
    assert list_args.json is True
    assert show_args.scenario_command == 'show'
    assert show_args.name == 'newmei-afuan-150'
    assert start_args.scenario_command == 'start'
    assert start_args.name == 'newmei-afuan-150'


def test_memory_parser_accepts_memory_commands():
    parser = cli.build_parser()

    remember_args = parser.parse_args([
        'memory', 'remember', '123', '--scope', 'room',
        '--kind', 'preference', '--text', '这个群喜欢晚上开黑。',
        '--source-task-id', 'task-1', '--confidence', '0.7', '--json',
    ])
    list_args = parser.parse_args(['memory', 'list', '123', '--json'])

    assert remember_args.command == 'memory'
    assert remember_args.memory_command == 'remember'
    assert remember_args.chat == '123'
    assert remember_args.scope == 'room'
    assert remember_args.kind == 'preference'
    assert remember_args.text == '这个群喜欢晚上开黑。'
    assert remember_args.source_task_id == 'task-1'
    assert remember_args.confidence == 0.7
    assert remember_args.json is True
    assert list_args.command == 'memory'
    assert list_args.memory_command == 'list'
    assert list_args.chat == '123'
    assert list_args.json is True


def test_badcase_parser_accepts_list_and_export_commands():
    parser = cli.build_parser()

    list_args = parser.parse_args([
        'badcase', 'list', '--chat', '-1001937176825',
        '--type', 'self_flood', '--reason', 'self_context_wait',
        '--limit', '5', '--json',
    ])
    export_args = parser.parse_args(['badcase', 'export', '--json'])

    assert list_args.command == 'badcase'
    assert list_args.badcase_command == 'list'
    assert list_args.chat == 1937176825
    assert list_args.type == 'self_flood'
    assert list_args.reason == 'self_context_wait'
    assert list_args.limit == 5
    assert list_args.json is True
    assert export_args.badcase_command == 'export'
    assert export_args.json is True


def test_entity_and_messages_parser_accepts_new_commands():
    parser = cli.build_parser()

    entity_args = parser.parse_args([
        'entity', 'resolve', '@group', '--json'])
    members_args = parser.parse_args([
        'members', 'search', '长沙修车大堆群', '薇薇',
        '--limit', '5', '--json'])
    profile_args = parser.parse_args([
        'profile', 'show', '薇薇',
        '--chat', '长沙修车大堆群',
        '--limit', '5',
        '--json',
    ])
    history_args = parser.parse_args([
        'messages', 'history', '5217114569',
        '--limit', '50',
        '--search', '开黑',
        '--from-user', '@alice',
        '--min-id', '10',
        '--max-id', '100',
        '--offset-id', '90',
        '--offset-date', '2026-06-04T12:00:00+08:00',
        '--reverse',
        '--media-only',
        '--json',
    ])
    send_args = parser.parse_args([
        'messages', 'send', '5217114569', '来了兄弟们下午好',
        '--reply-to', '7',
        '--parse-mode', 'html',
        '--no-link-preview',
        '--silent',
        '--dry-run',
        '--json',
    ])
    file_args = parser.parse_args([
        'messages', 'send-file', '5217114569', 'a.jpg', 'b.jpg',
        '--caption', '两张图',
        '--force-document',
        '--reply-to', '8',
        '--dry-run',
        '--json',
    ])
    delete_args = parser.parse_args([
        'messages', 'delete', '5217114569', '1', '2',
        '--revoke', '--dry-run', '--json'])
    forward_args = parser.parse_args([
        'messages', 'forward', 'from-chat', '5217114569', '3', '4',
        '--silent', '--dry-run', '--json'])
    read_args = parser.parse_args([
        'messages', 'read', '5217114569', '5',
        '--clear-mentions', '--dry-run', '--json'])
    pin_args = parser.parse_args([
        'messages', 'pin', '5217114569', '6', '--notify', '--dry-run'])
    unpin_args = parser.parse_args([
        'messages', 'unpin', '5217114569', '6', '--dry-run'])

    assert entity_args.command == 'entity'
    assert entity_args.entity_command == 'resolve'
    assert members_args.command == 'members'
    assert members_args.members_command == 'search'
    assert members_args.chat == '长沙修车大堆群'
    assert members_args.query == '薇薇'
    assert members_args.limit == 5
    assert profile_args.command == 'profile'
    assert profile_args.profile_command == 'show'
    assert profile_args.query == '薇薇'
    assert profile_args.chat == '长沙修车大堆群'
    assert history_args.messages_command == 'history'
    assert history_args.limit == 50
    assert history_args.search == '开黑'
    assert history_args.from_user == '@alice'
    assert history_args.reverse is True
    assert history_args.media_only is True
    assert send_args.messages_command == 'send'
    assert send_args.reply_to == 7
    assert send_args.parse_mode == 'html'
    assert send_args.link_preview is False
    assert send_args.silent is True
    assert file_args.messages_command == 'send-file'
    assert file_args.files == ['a.jpg', 'b.jpg']
    assert file_args.force_document is True
    assert delete_args.message_ids == ['1', '2']
    assert delete_args.revoke is True
    assert forward_args.from_chat == 'from-chat'
    assert forward_args.to_chat == '5217114569'
    assert forward_args.silent is True
    assert read_args.clear_mentions is True
    assert pin_args.notify is True
    assert unpin_args.messages_command == 'unpin'


def test_telethon_coverage_parser_accepts_new_command_families():
    parser = cli.build_parser()

    auth_args = parser.parse_args(['auth', 'status', '--json'])
    dialog_args = parser.parse_args([
        'dialog', 'archive', '5217114569', '--dry-run', '--json'])
    members_args = parser.parse_args([
        'members', 'list', '5217114569',
        '--filter', 'admins', '--limit', '10', '--json'])
    profile_args = parser.parse_args([
        'profile', 'photos', '5217114569', '--limit', '3', '--json'])
    get_args = parser.parse_args([
        'messages', 'get', '5217114569', '10', '11', '--json'])
    search_args = parser.parse_args([
        'messages', 'search', '开黑', '--global',
        '--filter', 'photos', '--json'])
    copy_args = parser.parse_args([
        'messages', 'copy', 'source', '5217114569', '12',
        '--dry-run', '--json'])
    action_args = parser.parse_args([
        'messages', 'action', '5217114569', 'typing',
        '--duration', '1', '--dry-run', '--json'])
    drafts_args = parser.parse_args([
        'drafts', 'set', '5217114569', '草稿',
        '--dry-run', '--json'])
    downloads_args = parser.parse_args([
        'downloads', 'media', '5217114569', '10', '--json'])
    admin_args = parser.parse_args([
        'admin', 'permissions', 'set', '5217114569',
        '--user', 'alice', '--disable', 'send_messages',
        '--dry-run', '--json'])
    bot_args = parser.parse_args([
        'bot', 'inline-send', '@like', 'hello', '5217114569',
        '--index', '1', '--dry-run', '--json'])

    assert auth_args.command == 'auth'
    assert auth_args.auth_command == 'status'
    assert dialog_args.dialog_command == 'archive'
    assert members_args.members_command == 'list'
    assert members_args.filter == 'admins'
    assert profile_args.profile_command == 'photos'
    assert get_args.messages_command == 'get'
    assert get_args.message_ids == ['10', '11']
    assert search_args.global_search is True
    assert search_args.filter == 'photos'
    assert copy_args.messages_command == 'copy'
    assert action_args.duration == 1.0
    assert drafts_args.drafts_command == 'set'
    assert downloads_args.downloads_command == 'media'
    assert downloads_args.message_id == 10
    assert admin_args.permissions_command == 'set'
    assert admin_args.disable == ['send_messages']
    assert bot_args.bot_command == 'inline-send'
    assert bot_args.index == 1


def test_cmd_downloads_media_json(monkeypatch, tmp_path, capsys):
    captured = {}

    async def fake_download_media(config, chat, message_id, **kwargs):
        captured['chat'] = chat
        captured['message_id'] = message_id
        captured.update(kwargs)
        return {
            'kind': 'media',
            'path': str(tmp_path / 'downloads' / 'media.bin'),
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'message_id': message_id,
        }

    monkeypatch.setattr(cli, 'download_media', fake_download_media)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'downloads', 'media', '5217114569', '10',
        '--output-dir', str(tmp_path / 'downloads'),
        '--json',
    ])

    cli._run(cli._cmd_downloads(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['path'].endswith('media.bin')
    assert captured['chat'] == '5217114569'
    assert captured['message_id'] == 10
    assert captured['output_dir'] == str(tmp_path / 'downloads')


def test_cmd_admin_permissions_set_json(monkeypatch, tmp_path, capsys):
    captured = {}

    async def fake_admin_permissions_set(config, chat, **kwargs):
        captured['chat'] = chat
        captured.update(kwargs)
        return {
            'updated': False,
            'dry_run': True,
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'permissions': {'send_messages': False},
        }

    monkeypatch.setattr(cli, 'admin_permissions_set', fake_admin_permissions_set)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'admin', 'permissions', 'set', '5217114569',
        '--user', 'alice',
        '--disable', 'send_messages',
        '--dry-run',
        '--json',
    ])

    cli._run(cli._cmd_admin(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['dry_run'] is True
    assert captured['chat'] == '5217114569'
    assert captured['user'] == 'alice'
    assert captured['disabled_permissions'] == ['send_messages']


def test_cmd_entity_resolve_json(monkeypatch, tmp_path, capsys):
    async def fake_resolve_entity(config, query, allow_users=True):
        return {
            'id': 5217114569,
            'peer_id': -1005217114569,
            'title': 'test chat',
            'kind': 'supergroup',
            'username': 'test_chat',
        }

    monkeypatch.setattr(cli, 'resolve_entity', fake_resolve_entity)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'entity', 'resolve', '@test_chat', '--json'])

    cli._run(cli._cmd_entity(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['kind'] == 'supergroup'
    assert payload['peer_id'] == -1005217114569


def test_cmd_members_search_json(monkeypatch, tmp_path, capsys):
    async def fake_search_members(config, chat, query, limit=20):
        return {
            'chat': {'id': 5217114569, 'title': chat},
            'query': query,
            'members': [{
                'id': 88,
                'peer_id': 88,
                'title': '薇薇',
                'kind': 'user',
                'username': 'vv_user',
                'participants_count': None,
            }],
        }

    monkeypatch.setattr(cli, 'search_members', fake_search_members)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'members', 'search', '长沙修车大堆群', '薇薇', '--json'])

    cli._run(cli._cmd_members(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['chat']['title'] == '长沙修车大堆群'
    assert payload['members'][0]['title'] == '薇薇'


def test_cmd_profile_show_json(monkeypatch, tmp_path, capsys):
    async def fake_show_profile(config, query, chat=None, limit=20):
        return {
            'source': 'chat_member',
            'chat': {'id': 5217114569, 'title': chat},
            'profile': {
                'id': 88,
                'peer_id': 88,
                'title': query,
                'kind': 'user',
                'username': 'vv_user',
                'display_name': query,
                'about': '公开简介',
                'has_profile_photo': True,
                'verified': False,
                'premium': False,
                'restricted': False,
                'scam': False,
                'fake': False,
            },
        }

    monkeypatch.setattr(cli, 'show_profile', fake_show_profile)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'profile', 'show', '薇薇',
        '--chat', '长沙修车大堆群',
        '--json'])

    cli._run(cli._cmd_profile(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['source'] == 'chat_member'
    assert payload['profile']['display_name'] == '薇薇'
    assert payload['profile']['about'] == '公开简介'


def test_cmd_messages_send_file_json(monkeypatch, tmp_path, capsys):
    captured = {}

    async def fake_send_media(config, chat, files, **kwargs):
        captured['chat'] = chat
        captured['files'] = files
        captured.update(kwargs)
        return {
            'sent': False,
            'dry_run': True,
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'message_ids': [],
            'files': files,
        }

    monkeypatch.setattr(cli, 'send_media', fake_send_media)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'messages', 'send-file', '5217114569', 'a.jpg',
        '--caption', '看图',
        '--force-document',
        '--dry-run',
        '--json',
    ])

    cli._run(cli._cmd_messages(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['dry_run'] is True
    assert captured['chat'] == '5217114569'
    assert captured['files'] == ['a.jpg']
    assert captured['caption'] == '看图'
    assert captured['force_document'] is True


def test_cmd_messages_delete_json(monkeypatch, tmp_path, capsys):
    captured = {}

    async def fake_delete_messages(config, chat, message_ids, **kwargs):
        captured['chat'] = chat
        captured['message_ids'] = message_ids
        captured.update(kwargs)
        return {
            'deleted': False,
            'dry_run': True,
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'message_ids': message_ids,
        }

    monkeypatch.setattr(cli, 'delete_messages', fake_delete_messages)
    config = AppConfig(
        api_id=1,
        api_hash='hash',
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
    )
    args = cli.build_parser().parse_args([
        'messages', 'delete', '5217114569', '10', '11',
        '--revoke', '--dry-run', '--json'])

    cli._run(cli._cmd_messages(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['message_ids'] == [10, 11]
    assert captured['revoke'] is True
    assert captured['dry_run'] is True


def test_badcase_list_json_does_not_require_credentials(tmp_path, capsys):
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        bad_cases_config={
            'enabled': True,
            'path': str(tmp_path / 'bad-cases.jsonl'),
            'max_records': 20,
            'max_task_bad_cases': 3,
        })
    bad_case_store.record_bad_case(
        config, source='daemon', reason='self_context_wait',
        chat_id=5217114569)

    args = cli.build_parser().parse_args([
        'badcase', 'list', '--chat', '5217114569', '--json'])
    cli._run(cli._cmd_badcase(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['records'][0]['case_type'] == 'self_flood'
    assert payload['records'][0]['reason'] == 'self_context_wait'


def test_memory_remember_validation_error_is_reported_without_traceback(
        tmp_path, monkeypatch, capsys):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'memory': {
            'enabled': True,
            'path': str(tmp_path / 'memory.sqlite3'),
        },
    }), encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    code = cli.main([
        '--config', str(config_path),
        'memory', 'remember', '123',
        '--scope', 'room',
        '--text', 'note',
        '--confidence', '2.0',
        '--json',
    ])

    captured = capsys.readouterr()
    assert code == 2
    assert 'confidence must be between 0 and 1' in captured.err
    assert 'Traceback' not in captured.err


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
        def get_status(self, path):
            return {
                'run_id': 'quota-test',
                'status': 'active',
                'targets': [{
                    'chat_id': 5217114569,
                    'target_count': 1,
                    'sent_count': 0,
                    'status': 'active',
                }],
            }

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
        'quota', 'reply', 'task-1', '来了兄弟们下午好', '--dry-run', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['sent'] is False
    assert payload['dry_run'] is True
    assert payload['message_ids'] == []
    assert payload['task']['status'] == 'pending'
    assert captured['get_path'] == config.quota['state_path']
    assert 'complete_path' not in captured


def test_quota_skip_marks_task_without_credentials(
        tmp_path, monkeypatch, capsys):
    captured = {}

    class FakeQuotaStore:
        def skip_task(self, path, task_id, reason='skipped'):
            captured['path'] = path
            captured['task_id'] = task_id
            captured['reason'] = reason
            return {
                'id': task_id,
                'status': 'skipped',
                'reason': reason,
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
        'quota', 'skip', 'task-1', '--reason', 'stale_context', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['skipped'] is True
    assert payload['task']['status'] == 'skipped'
    assert payload['task']['reason'] == 'stale_context'
    assert captured == {
        'path': config.quota['state_path'],
        'task_id': 'task-1',
        'reason': 'stale_context',
    }


def test_quota_step_without_reply_creates_task_and_reports_progress(
        tmp_path, monkeypatch, capsys):
    async def fake_next_context_payload(config):
        return {
            'task': {
                'id': 'task-1',
                'status': 'pending',
                'chat_id': 5217114569,
            },
            'context': {'prompt': 'Reply if useful.'},
            'status': {
                'run_id': 'quota-test',
                'status': 'active',
                'targets': [{
                    'chat_id': 5217114569,
                    'target_count': 140,
                    'sent_count': 1,
                    'status': 'active',
                }],
                'tasks': [],
            },
        }

    monkeypatch.setattr(
        cli, '_quota_next_context_payload', fake_next_context_payload)
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota-state.json')},
    )

    args = cli.build_parser().parse_args(['quota', 'step', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['action'] == 'next'
    assert payload['task']['id'] == 'task-1'
    assert payload['progress']['sent_count'] == 1
    assert payload['progress']['target_count'] == 140
    assert payload['progress']['remaining_count'] == 139
    assert payload['next_action'] == 'reply_or_skip'


def test_quota_step_reply_defaults_to_dry_run(
        tmp_path, monkeypatch, capsys):
    captured = []

    async def fake_next_context_payload(config):
        return {
            'task': {
                'id': 'task-1',
                'status': 'pending',
                'chat_id': 5217114569,
            },
            'context': {'prompt': 'Reply if useful.'},
            'status': {
                'run_id': 'quota-test',
                'status': 'active',
                'targets': [{
                    'chat_id': 5217114569,
                    'target_count': 2,
                    'sent_count': 0,
                    'status': 'active',
                }],
                'tasks': [],
            },
        }

    class FakeQuotaStore:
        def get_task(self, path, task_id):
            return {
                'id': task_id,
                'status': 'pending',
                'chat': {'id': 5217114569, 'title': 'test chat'},
                'profile': {'style': 'brief', 'forbidden_terms': []},
            }

    async def fake_send_reply(config, task_id, task, text, dry_run=False):
        captured.append({
            'task_id': task_id,
            'text': text,
            'dry_run': dry_run,
        })
        return ({
            'sent': False,
            'dry_run': dry_run,
            'task_id': task_id,
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'message_ids': [],
            'parts': [text],
        }, False)

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())
    monkeypatch.setattr(
        cli, '_quota_next_context_payload', fake_next_context_payload)
    monkeypatch.setattr(cli, '_quota_send_reply', fake_send_reply)
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
        'quota', 'step', '--reply', '西瓜现在甜不甜呀', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['action'] == 'dry_run'
    assert payload['dry_run']['sent'] is False
    assert payload['dry_run']['dry_run'] is True
    assert 'send' not in payload
    assert captured == [{
        'task_id': 'task-1',
        'text': '西瓜现在甜不甜呀',
        'dry_run': True,
    }]


def test_quota_step_reply_send_runs_dry_run_before_send(
        tmp_path, monkeypatch, capsys):
    captured = []

    async def fake_next_context_payload(config):
        return {
            'task': {
                'id': 'task-1',
                'status': 'pending',
                'chat_id': 5217114569,
            },
            'context': {'prompt': 'Reply if useful.'},
            'status': {
                'run_id': 'quota-test',
                'status': 'active',
                'targets': [{
                    'chat_id': 5217114569,
                    'target_count': 2,
                    'sent_count': 0,
                    'status': 'active',
                }],
                'tasks': [],
            },
        }

    class FakeQuotaStore:
        def get_task(self, path, task_id):
            return {
                'id': task_id,
                'status': 'pending',
                'chat': {'id': 5217114569, 'title': 'test chat'},
                'profile': {'style': 'brief', 'forbidden_terms': []},
            }

    async def fake_send_reply(config, task_id, task, text, dry_run=False):
        captured.append(dry_run)
        message_ids = [] if dry_run else [42]
        return ({
            'sent': not dry_run,
            'dry_run': dry_run,
            'task_id': task_id,
            'chat': {'id': 5217114569, 'title': 'test chat'},
            'message_ids': message_ids,
            'parts': [text],
            'task': {
                'id': task_id,
                'status': 'completed' if not dry_run else 'pending',
                'message_ids': message_ids,
            },
        }, False)

    monkeypatch.setattr(cli, 'quota_store', FakeQuotaStore())
    monkeypatch.setattr(
        cli, '_quota_next_context_payload', fake_next_context_payload)
    monkeypatch.setattr(cli, '_quota_send_reply', fake_send_reply)
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
        'quota', 'step', '--reply', '西瓜现在甜不甜呀', '--send', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['action'] == 'send'
    assert payload['dry_run']['dry_run'] is True
    assert payload['send']['sent'] is True
    assert payload['send']['message_ids'] == [42]
    assert captured == [True, False]


def test_quota_watch_reads_progress_without_credentials(
        tmp_path, monkeypatch, capsys):
    class FakeQuotaStore:
        def status(self, path):
            return {
                'run_id': 'quota-test',
                'status': 'active',
                'targets': [{
                    'chat_id': 5217114569,
                    'target_count': 140,
                    'sent_count': 12,
                    'status': 'active',
                }],
                'tasks': [],
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
        'quota', 'watch', '--interval', '0', '--count', '2', '--json'])
    cli._run(cli._cmd_quota(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert len(payload['snapshots']) == 2
    assert payload['snapshots'][0]['progress']['sent_count'] == 12
    assert payload['snapshots'][0]['progress']['remaining_count'] == 128


def test_scenario_list_and_show_do_not_require_credentials(
        tmp_path, capsys):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps({
        'scenarios': [{
            'name': 'newmei-afuan-150',
            'account': 'lu',
            'chat_id': 5217114569,
            'persona': 'afuan_social',
            'preset': 'chat_social',
            'target_messages': 150,
        }],
    }), encoding='utf-8')
    config = AppConfig(
        api_id=None,
        api_hash=None,
        session_path=tmp_path / 'printer.session',
        allowed_chats=[5217114569],
        state_path=tmp_path / '.tg-cli-state.json',
        audit_log_path=tmp_path / 'tg-cli.audit.log',
        quota_config={'state_path': str(tmp_path / 'quota-state.json')},
    )

    list_args = cli.build_parser().parse_args([
        'scenario', 'list', '--path', str(path), '--json'])
    cli._run(cli._cmd_scenario(list_args, config))
    listed = json.loads(capsys.readouterr().out)

    show_args = cli.build_parser().parse_args([
        'scenario', 'show', 'newmei-afuan-150',
        '--path', str(path), '--json'])
    cli._run(cli._cmd_scenario(show_args, config))
    shown = json.loads(capsys.readouterr().out)

    assert listed['path'] == str(path)
    assert listed['scenarios'][0]['target_messages'] == 150
    assert shown['scenario']['name'] == 'newmei-afuan-150'
    assert shown['scenario']['dry_run_first'] is True


def test_scenario_start_creates_quota_run_with_metadata(
        tmp_path, monkeypatch, capsys):
    captured = {}
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps([{
        'name': 'newmei-afuan-150',
        'account': 'lu',
        'chat_id': 5217114569,
        'persona': 'afuan_social',
        'preset': 'chat_social',
        'target_messages': 150,
        'max_runtime_minutes': 240,
    }]), encoding='utf-8')

    class FakeQuotaStore:
        def create_run(self, state_path, targets, preset=None, scenario=None):
            captured['state_path'] = state_path
            captured['targets'] = targets
            captured['preset'] = preset
            captured['scenario'] = scenario
            return {
                'run_id': 'quota-test',
                'status': 'active',
                'preset': preset,
                'scenario': scenario,
                'targets': [{
                    'chat_id': targets[0]['chat_id'],
                    'target_count': targets[0]['target_count'],
                    'sent_count': 0,
                    'status': 'active',
                }],
                'tasks': [],
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
        presets={'chat_social': {'profile': {'style': 'social'}}},
    )

    args = cli.build_parser().parse_args([
        'scenario', 'start', 'newmei-afuan-150',
        '--path', str(path), '--json'])
    cli._run(cli._cmd_scenario(args, config))

    payload = json.loads(capsys.readouterr().out)
    assert payload['scenario']['name'] == 'newmei-afuan-150'
    assert payload['quota']['targets'][0]['target_count'] == 150
    assert captured['state_path'] == config.quota['state_path']
    assert captured['targets'] == [{
        'chat_id': 5217114569,
        'target_count': 150,
    }]
    assert captured['preset'] == 'chat_social'
    assert captured['scenario']['account'] == 'lu'
    assert captured['scenario']['persona'] == 'afuan_social'


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
        'daemon', 'reply', task['id'], '来了兄弟们下午好', '--json'])
    cli._run(cli._cmd_daemon(reply_args, config))
    reply_payload = json.loads(capsys.readouterr().out)
    assert reply_payload['queued'] is True
    assert reply_payload['task']['status'] == 'reply_pending'
    assert reply_payload['task']['reply_text'] == '来了兄弟们下午好'

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
    assert 'max_consecutive_replies' not in captured['daemon']


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
        'daemon', 'reply', task['id'], '来了兄弟们下午好', '--dry-run', '--json'])
    cli._run(cli._cmd_daemon(reply_args, config))

    reply_payload = json.loads(capsys.readouterr().out)
    assert reply_payload['queued'] is False
    assert reply_payload['dry_run'] is True
    assert reply_payload['task']['dry_run_checked'] is True
    saved = cli.daemon_store.get_task(config.daemon['queue_path'], task['id'])
    assert saved['status'] == 'pending'
