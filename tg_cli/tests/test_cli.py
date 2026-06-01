import json
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


def test_game_round_parser_defaults():
    parser = cli.build_parser()

    args = parser.parse_args(['game', 'round', '5217114569'])

    assert args.command == 'game'
    assert args.game_command == 'round'
    assert args.chat == '5217114569'
    assert args.duration == 60
    assert args.limit == 12
    assert args.max_replies == 8
    assert args.include_self is False
