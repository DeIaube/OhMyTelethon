import argparse
import asyncio
import copy
import json
import os
import sqlite3
import sys

from . import __version__
from .config import ConfigError, load_config, normalize_round
from . import daemon as daemon_store
from . import safety
from .safety import SafetyError
from .telegram_ops import (
    TelegramCliError, codex_context, daemon_run, dumps_json, get_me, history,
    interactive_round, list_dialogs, observe, send_text,
)


def _print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _run(coro):
    return asyncio.run(coro)


def _resolve_profile(config, preset_name=None):
    if hasattr(config, 'resolve_profile'):
        return config.resolve_profile(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return dict(getattr(config, 'profile', {}) or {})


def _resolve_round(config, preset_name=None):
    if hasattr(config, 'resolve_round'):
        return config.resolve_round(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return normalize_round(getattr(config, 'round', {}) or {})


def _resolve_reply_policy(config, preset_name=None):
    if hasattr(config, 'resolve_reply_policy'):
        return config.resolve_reply_policy(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return dict(getattr(config, 'reply_policy', {}) or {})


def _resolve_initiative(config, preset_name=None):
    if hasattr(config, 'resolve_initiative'):
        return config.resolve_initiative(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return dict(getattr(config, 'initiative', {}) or {})


def _resolve_persona(config, preset_name=None):
    if hasattr(config, 'resolve_persona'):
        return config.resolve_persona(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return dict(getattr(config, 'persona', {}) or {})


def _copy_config_with_game_settings(
        config, profile, round_config=None, reply_policy=None,
        initiative=None, persona=None, preset_name=None):
    game_config = copy.copy(config)
    game_config.profile = profile
    if round_config is not None:
        game_config.round = round_config
    if reply_policy is not None:
        game_config.reply_policy = reply_policy
    if initiative is not None:
        game_config.initiative = initiative
    if persona is not None:
        game_config.persona = persona
    game_config.preset_name = preset_name
    return game_config


def _round_with_cli_overrides(round_config, args):
    effective = dict(round_config)
    for name in (
            'duration', 'limit', 'max_replies', 'quiet_context',
            'min_reply_interval', 'end_buffer', 'reply_probability',
            'mention_reply_probability', 'random_delay_min',
            'random_delay_max', 'skip_short_ack', 'merge_window',
            'split_long_replies'):
        value = getattr(args, name)
        if value is not None:
            effective[name] = value
    return normalize_round(effective)


def build_parser():
    parser = argparse.ArgumentParser(prog='tg-cli')
    parser.add_argument('--version', action='version', version='tg-cli {}'.format(__version__))
    parser.add_argument('--config', help='Path to JSON config. Defaults to ./.tg-cli.json then ~/.config/tg-cli/config.json.')
    sub = parser.add_subparsers(dest='command', required=True)

    me = sub.add_parser('me', help='Show the logged-in Telegram account.')
    me.add_argument('--json', action='store_true')

    groups = sub.add_parser('groups', help='List groups and channels.')
    groups.add_argument('--json', action='store_true')

    dialogs = sub.add_parser('dialogs', help='List all dialogs.')
    dialogs.add_argument('--json', action='store_true')

    hist = sub.add_parser('history', help='Print recent messages from a chat.')
    hist.add_argument('chat')
    hist.add_argument('--limit', '-n', type=int, default=20)
    hist.add_argument('--json', action='store_true')

    send = sub.add_parser('send', help='Send one message through the safety layer.')
    send.add_argument('chat')
    send.add_argument('text')
    send.add_argument('--yes', action='store_true', help='Skip interactive confirmation.')
    send.add_argument('--dry-run', action='store_true', help='Resolve and audit without sending.')
    send.add_argument('--json', action='store_true')

    sub.add_parser('pause', help='Pause all write operations.')
    sub.add_parser('resume', help='Resume write operations.')

    status = sub.add_parser('status', help='Show safety state.')
    status.add_argument('--json', action='store_true')

    game = sub.add_parser('game', help='Game-oriented commands.')
    game_sub = game.add_subparsers(dest='game_command', required=True)
    observe_cmd = game_sub.add_parser('observe', help='Observe live messages in one chat.')
    observe_cmd.add_argument('chat')
    observe_cmd.add_argument('--include-self', action='store_true')
    observe_cmd.add_argument('--timeout', type=float, help='Stop after this many seconds.')

    suggest = game_sub.add_parser('suggest', help='Print an agent-ready reply context bundle.')
    suggest.add_argument('chat')
    suggest.add_argument('--limit', '-n', type=int, default=20)
    suggest.add_argument('--preset', help='Named profile/round preset from config.presets.')
    suggest.add_argument(
        '--operator', default='agent',
        help='Operator name to include in the generated instruction, such as codex or claude.')
    suggest.add_argument('--json', action='store_true')

    round_cmd = game_sub.add_parser('round', help='Run a bounded interactive agent-operated chat round.')
    round_cmd.add_argument('chat')
    round_cmd.add_argument('--preset', help='Named profile/round preset from config.presets.')
    round_cmd.add_argument('--duration', type=float)
    round_cmd.add_argument('--limit', '-n', type=int)
    round_cmd.add_argument('--max-replies', type=int)
    round_cmd.add_argument('--include-self', action='store_true')
    round_cmd.add_argument(
        '--quiet-context', action='store_true', default=None,
        help='Only print each incoming message and compact agent instruction, not the repeated recent-context block.')
    round_cmd.add_argument(
        '--min-reply-interval', type=float,
        help='Minimum seconds between game round sends.')
    round_cmd.add_argument(
        '--end-buffer', type=float,
        help='Stop prompting when less than this many seconds remain.')
    round_cmd.add_argument(
        '--reply-probability', type=float,
        help='Probability of prompting for a reply to each inbound message or merged batch.')
    round_cmd.add_argument(
        '--mention-reply-probability', type=float,
        help='Override reply probability when inbound text appears to mention the logged-in account.')
    round_cmd.add_argument(
        '--random-delay-min', type=float,
        help='Minimum human-like delay before sending a typed round reply.')
    round_cmd.add_argument(
        '--random-delay-max', type=float,
        help='Maximum human-like delay before sending a typed round reply.')
    round_cmd.add_argument(
        '--skip-short-ack', action='store_true', default=None,
        help='Skip low-information acknowledgements such as 嗯, 哈哈, or 真的假的.')
    round_cmd.add_argument(
        '--merge-window', type=float,
        help='Seconds to collect rapid consecutive inbound messages before one prompt.')
    round_cmd.add_argument(
        '--split-long-replies', action='store_true', default=None,
        help='Split long typed replies into multiple Telegram messages using round config.')

    daemon = sub.add_parser('daemon', help='Long-running local task queue commands.')
    daemon_sub = daemon.add_subparsers(dest='daemon_command', required=True)

    daemon_run_cmd = daemon_sub.add_parser(
        'run', help='Run one foreground daemon for one chat.')
    daemon_run_cmd.add_argument('chat')
    daemon_run_cmd.add_argument('--preset', help='Named preset from config.presets.')
    daemon_run_cmd.add_argument(
        '--duration', type=float, default=3600.0,
        help='Stop after this many seconds. Default: 3600.')
    daemon_run_cmd.add_argument(
        '--dry-run', action='store_true',
        help='Create local tasks but do not send queued replies.')

    daemon_next = daemon_sub.add_parser(
        'next', help='Print the next pending daemon task.')
    daemon_next.add_argument(
        '--peek', action='store_true',
        help='Read without claiming a task lease.')
    daemon_next.add_argument('--json', action='store_true')

    daemon_reply = daemon_sub.add_parser(
        'reply', help='Queue a reply for the running daemon to send.')
    daemon_reply.add_argument('task_id')
    daemon_reply.add_argument('text')
    daemon_reply.add_argument(
        '--dry-run', action='store_true',
        help='Validate and audit without queueing a real send.')
    daemon_reply.add_argument('--json', action='store_true')

    daemon_skip = daemon_sub.add_parser(
        'skip', help='Skip a pending daemon task.')
    daemon_skip.add_argument('task_id')
    daemon_skip.add_argument('--reason', default='skipped')
    daemon_skip.add_argument('--json', action='store_true')

    daemon_status = daemon_sub.add_parser(
        'status', help='Show daemon queue and lock status.')
    daemon_status.add_argument('--json', action='store_true')

    daemon_sub.add_parser('stop', help='Ask the foreground daemon to stop.')

    return parser


async def _cmd_me(args, config):
    data = await get_me(config)
    if args.json:
        _print_json(data)
    else:
        print('{display_name} | id={id} | username={username} | bot={bot}'.format(**data))


async def _cmd_groups(args, config, groups_only=True):
    rows = await list_dialogs(config, groups_only=groups_only)
    if args.json:
        _print_json(rows)
        return
    for row in rows:
        display = dict(row)
        display['username'] = '@{}'.format(row['username']) if row.get('username') else '-'
        display['count'] = row['participants_count'] if row['participants_count'] is not None else '-'
        print('[{kind}] {title} | id={id} | username={username} | members={count}'.format(**display))


async def _cmd_history(args, config):
    row, messages = await history(config, args.chat, args.limit)
    if args.json:
        _print_json({'chat': row, 'messages': messages})
        return
    print('History: {} (id={})'.format(row['title'], row['id']))
    for item in messages:
        print('[{id}] {sender}: {text}'.format(**item))


async def _cmd_send(args, config):
    result = await send_text(
        config, args.chat, args.text, assume_yes=args.yes,
        dry_run=args.dry_run)
    if args.json:
        _print_json(result)
        return
    if result['dry_run']:
        print('DRY-RUN allowed for {} (id={})'.format(
            result['chat']['title'], result['chat']['id']))
    elif result['sent']:
        print('SENT title={!r} id={} message_id={}'.format(
            result['chat']['title'], result['chat']['id'], result['message_id']))
    else:
        print('Cancelled.')


async def _cmd_game(args, config):
    if args.game_command == 'observe':
        await observe(config, args.chat, include_self=args.include_self, timeout=args.timeout)
        return
    if args.game_command == 'suggest':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        game_config = _copy_config_with_game_settings(
            config, profile, reply_policy=reply_policy,
            initiative=initiative, persona=persona, preset_name=args.preset)
        data = await codex_context(
            game_config, args.chat, args.limit,
            operator=args.operator, preset=args.preset)
        if args.json:
            print(dumps_json(data))
        else:
            print('Chat: {title} (id={id})'.format(**data['chat']))
            print('Operator: {}'.format(data['operator']))
            print('Preset: {}'.format(data['preset'] or 'default'))
            print('Profile: {}'.format(data['profile']))
            print('Persona: {}'.format(data['persona']))
            print('Reply policy: {}'.format(data['reply_policy']))
            print('Initiative: {}'.format(data['initiative']))
            print('Recent messages:')
            for item in data['messages']:
                print('- [{id}] {sender}: {text}'.format(**item))
            print('\nAgent instruction:')
            print(data['instruction'])
        return
    if args.game_command == 'round':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        round_config = _round_with_cli_overrides(
            _resolve_round(config, args.preset), args)
        game_config = _copy_config_with_game_settings(
            config, profile, round_config, reply_policy=reply_policy,
            initiative=initiative, persona=persona, preset_name=args.preset)
        await interactive_round(
            game_config, args.chat,
            duration=round_config['duration'],
            limit=round_config['limit'],
            max_replies=round_config['max_replies'],
            include_self=args.include_self,
            quiet_context=round_config['quiet_context'],
            min_reply_interval=round_config['min_reply_interval'],
            end_buffer=round_config['end_buffer'],
            reply_probability=round_config['reply_probability'],
            mention_reply_probability=round_config['mention_reply_probability'],
            random_delay_min=round_config['random_delay_min'],
            random_delay_max=round_config['random_delay_max'],
            skip_short_ack=round_config['skip_short_ack'],
            merge_window=round_config['merge_window'],
            split_long_replies=round_config['split_long_replies'])
        return
    raise AssertionError(args.game_command)


def _daemon_path(config, name):
    return config.daemon['{}_path'.format(name)]


def _find_task(config, task_id):
    queue = daemon_store.load_queue(_daemon_path(config, 'queue'))
    for task in queue.get('tasks', []):
        if task.get('id') == task_id:
            return task
    return None


def _config_for_task(config, task):
    task_config = copy.copy(config)
    task_config.profile = task.get('profile') or getattr(config, 'profile', {})
    task_config.persona = task.get('persona') or getattr(config, 'persona', {})
    task_config.reply_policy = (
        task.get('reply_policy') or getattr(config, 'reply_policy', {}))
    task_config.initiative = (
        task.get('initiative') or getattr(config, 'initiative', {}))
    return task_config


def _daemon_status_payload(config):
    status = daemon_store.read_status(_daemon_path(config, 'status'))
    counts = daemon_store.queue_counts(_daemon_path(config, 'queue'))
    lock_path = _daemon_path(config, 'lock')
    return {
        'paused': bool(safety.load_state(config).get('paused')),
        'running': bool(status.get('running')),
        'stop_requested': bool(status.get('stop_requested')),
        'status': status,
        'queue_counts': counts,
        'queue_path': str(_daemon_path(config, 'queue')),
        'lock_path': str(lock_path),
        'status_path': str(_daemon_path(config, 'status')),
        'locked': lock_path.is_file(),
    }


async def _cmd_daemon(args, config):
    queue_path = _daemon_path(config, 'queue')
    status_path = _daemon_path(config, 'status')

    if args.daemon_command == 'run':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        round_config = _resolve_round(config, args.preset)
        daemon_config = _copy_config_with_game_settings(
            config, profile, round_config, reply_policy=reply_policy,
            initiative=initiative, persona=persona, preset_name=args.preset)
        await daemon_run(
            daemon_config, args.chat, preset=args.preset,
            duration=args.duration, dry_run=args.dry_run)
        return

    if args.daemon_command == 'next':
        if args.peek:
            task = daemon_store.next_pending_task(
                queue_path,
                task_ttl=config.daemon['task_ttl'])
        else:
            task = daemon_store.claim_next_task(
                queue_path,
                task_ttl=config.daemon['task_ttl'],
                claim_ttl=config.daemon['claim_ttl'],
                owner='tg-cli:{}'.format(os.getpid()))
        if args.json:
            print(dumps_json(task))
        elif task is None:
            print('No pending daemon task.')
        else:
            print('Task: {id} kind={kind} chat={title} preset={preset}'.format(
                id=task['id'],
                kind=task.get('kind'),
                title=(task.get('chat') or {}).get('title'),
                preset=task.get('preset') or 'default'))
            print('Prompt:')
            print(task.get('prompt') or '')
            print('Messages:')
            for item in task.get('messages') or []:
                print('- [{id}] {sender}: {text}'.format(**item))
        return

    if args.daemon_command == 'reply':
        task = _find_task(config, args.task_id)
        if task is None:
            raise TelegramCliError('Daemon task not found: {}'.format(args.task_id))
        if task.get('status') not in ('pending', 'claimed'):
            raise TelegramCliError(
                'Daemon task {} is not pending or claimed; status={}.'.format(
                    args.task_id, task.get('status')))
        text = (args.text or '').strip()
        if not text:
            raise TelegramCliError('Reply text must not be empty.')
        task_config = _config_for_task(config, task)
        chat = task.get('chat') or {}
        chat_id = chat.get('id')
        safety.require_can_write(task_config, chat_id)
        matches = safety.find_forbidden_terms(task_config, text)
        if matches:
            safety.audit_record(
                task_config, 'daemon_reply', chat_id,
                chat_title=chat.get('title'), text=text,
                dry_run=args.dry_run, status='blocked_forbidden_terms')
            raise safety.SafetyError(
                'Message contains forbidden/sensitive profile term(s): {}.'.format(
                    ', '.join(matches)))
        if args.dry_run:
            safety.audit_record(
                task_config, 'daemon_reply', chat_id,
                chat_title=chat.get('title'), text=text,
                dry_run=True, status='dry_run')
            result = copy.deepcopy(task)
            result['dry_run_checked'] = True
            payload = {'queued': False, 'dry_run': True, 'task': result}
        else:
            safety.audit_record(
                task_config, 'daemon_reply', chat_id,
                chat_title=chat.get('title'), text=text,
                status='queued')
            result = daemon_store.queue_reply_task(queue_path, args.task_id, text)
            payload = {'queued': True, 'dry_run': False, 'task': result}
        if args.json:
            print(dumps_json(payload))
        elif payload['queued']:
            print('Queued daemon reply for task {}.'.format(args.task_id))
        else:
            print('DRY-RUN daemon reply accepted for task {}.'.format(args.task_id))
        return

    if args.daemon_command == 'skip':
        task = daemon_store.skip_task(queue_path, args.task_id, reason=args.reason)
        if task is None:
            raise TelegramCliError(
                'Daemon task not found or not skippable: {}'.format(args.task_id))
        if args.json:
            print(dumps_json({'skipped': True, 'task': task}))
        else:
            print('Skipped daemon task {}.'.format(args.task_id))
        return

    if args.daemon_command == 'status':
        data = _daemon_status_payload(config)
        if args.json:
            print(dumps_json(data))
        else:
            print('running={}'.format(str(data['running']).lower()))
            print('locked={}'.format(str(data['locked']).lower()))
            print('paused={}'.format(str(data['paused']).lower()))
            print('stop_requested={}'.format(
                str(data['stop_requested']).lower()))
            print('queue_counts={}'.format(
                json.dumps(data['queue_counts'], sort_keys=True)))
        return

    if args.daemon_command == 'stop':
        daemon_store.request_stop(status_path)
        print('Stop requested.')
        return

    raise AssertionError(args.daemon_command)


def _status_payload(config):
    state = safety.load_state(config)
    return {
        'paused': bool(state.get('paused')),
        'allowed_chats': list(config.allowed_chats),
        'session_path': str(config.session_path),
        'state_path': str(config.state_path),
        'audit_log_path': str(config.audit_log_path),
    }


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    telegram_commands = {'me', 'groups', 'dialogs', 'history', 'send', 'game'}
    require_credentials = (
        args.command in telegram_commands
        or (args.command == 'daemon' and args.daemon_command == 'run'))

    try:
        config = load_config(args.config, require_credentials=require_credentials)
        if args.command == 'pause':
            safety.set_paused(config, True)
            print('Paused.')
            return 0
        if args.command == 'resume':
            safety.set_paused(config, False)
            print('Resumed.')
            return 0
        if args.command == 'status':
            data = _status_payload(config)
            if args.json:
                _print_json(data)
            else:
                print('paused={}'.format(str(data['paused']).lower()))
                print('allowed_chats={}'.format(','.join(str(x) for x in data['allowed_chats']) or 'none'))
                print('session_path={}'.format(data['session_path']))
            return 0

        if args.command == 'me':
            _run(_cmd_me(args, config))
        elif args.command == 'groups':
            _run(_cmd_groups(args, config, groups_only=True))
        elif args.command == 'dialogs':
            _run(_cmd_groups(args, config, groups_only=False))
        elif args.command == 'history':
            _run(_cmd_history(args, config))
        elif args.command == 'send':
            _run(_cmd_send(args, config))
        elif args.command == 'game':
            _run(_cmd_game(args, config))
        elif args.command == 'daemon':
            _run(_cmd_daemon(args, config))
        else:
            parser.error('unknown command {}'.format(args.command))
        return 0
    except (ConfigError, SafetyError, TelegramCliError, daemon_store.DaemonLockError) as exc:
        print('error: {}'.format(exc), file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        if 'database is locked' in str(exc).lower():
            print(
                'error: Telegram session database is locked. Another tg-cli process may be using the same session. '
                'Wait for it to finish, or use TG_CLI_SESSION with a separate session file.',
                file=sys.stderr)
        else:
            print('error: sqlite operation failed: {}'.format(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
