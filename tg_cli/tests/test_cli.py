import json
import sqlite3
from types import SimpleNamespace

from tg_cli import cli


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
    assert args.reply_probability is None
    assert args.mention_reply_probability is None
    assert args.random_delay_min is None
    assert args.random_delay_max is None
    assert args.skip_short_ack is None
    assert args.merge_window is None
    assert args.quiet_context is None
    assert args.split_long_replies is None


def test_game_suggest_parser_accepts_operator():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'suggest', '5217114569',
        '--operator', 'claude',
        '--json',
    ])

    assert args.command == 'game'
    assert args.game_command == 'suggest'
    assert args.chat == '5217114569'
    assert args.operator == 'claude'
    assert args.json is True


def test_game_round_parser_humanization_flags():
    parser = cli.build_parser()

    args = parser.parse_args([
        'game', 'round', '5217114569',
        '--reply-probability', '0.4',
        '--mention-reply-probability', '0.9',
        '--random-delay-min', '1.5',
        '--random-delay-max', '4',
        '--skip-short-ack',
        '--merge-window', '2',
    ])

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
