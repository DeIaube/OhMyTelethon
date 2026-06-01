import argparse
import asyncio
import json
import sys

from . import __version__
from .config import ConfigError, load_config
from . import safety
from .safety import SafetyError
from .telegram_ops import (
    TelegramCliError, codex_context, dumps_json, get_me, history,
    interactive_round, list_dialogs, observe, send_text,
)


def _print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _run(coro):
    return asyncio.run(coro)


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

    suggest = game_sub.add_parser('suggest', help='Print a Codex-ready reply context bundle.')
    suggest.add_argument('chat')
    suggest.add_argument('--limit', '-n', type=int, default=20)
    suggest.add_argument('--json', action='store_true')

    round_cmd = game_sub.add_parser('round', help='Run a bounded interactive Codex-operated chat round.')
    round_cmd.add_argument('chat')
    round_cmd.add_argument('--duration', type=float, default=60)
    round_cmd.add_argument('--limit', '-n', type=int, default=12)
    round_cmd.add_argument('--max-replies', type=int, default=8)
    round_cmd.add_argument('--include-self', action='store_true')
    round_cmd.add_argument(
        '--quiet-context', action='store_true',
        help='Only print each incoming message and compact Codex instruction, not the repeated recent-context block.')
    round_cmd.add_argument(
        '--min-reply-interval', type=float, default=2.0,
        help='Minimum seconds between game round sends.')
    round_cmd.add_argument(
        '--end-buffer', type=float, default=5.0,
        help='Stop prompting when less than this many seconds remain.')
    round_cmd.add_argument(
        '--reply-probability', type=float, default=1.0,
        help='Probability of prompting for a reply to each inbound message or merged batch.')
    round_cmd.add_argument(
        '--mention-reply-probability', type=float,
        help='Override reply probability when inbound text appears to mention the logged-in account.')
    round_cmd.add_argument(
        '--random-delay-min', type=float, default=0.0,
        help='Minimum human-like delay before sending a typed round reply.')
    round_cmd.add_argument(
        '--random-delay-max', type=float, default=0.0,
        help='Maximum human-like delay before sending a typed round reply.')
    round_cmd.add_argument(
        '--skip-short-ack', action='store_true',
        help='Skip low-information acknowledgements such as 嗯, 哈哈, or 真的假的.')
    round_cmd.add_argument(
        '--merge-window', type=float, default=0.0,
        help='Seconds to collect rapid consecutive inbound messages before one prompt.')

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
        data = await codex_context(config, args.chat, args.limit)
        if args.json:
            print(dumps_json(data))
        else:
            print('Chat: {title} (id={id})'.format(**data['chat']))
            print('Profile: {}'.format(data['profile']))
            print('Recent messages:')
            for item in data['messages']:
                print('- [{id}] {sender}: {text}'.format(**item))
            print('\nCodex instruction:')
            print(data['instruction'])
        return
    if args.game_command == 'round':
        await interactive_round(
            config, args.chat, duration=args.duration, limit=args.limit,
            max_replies=args.max_replies, include_self=args.include_self,
            quiet_context=args.quiet_context,
            min_reply_interval=args.min_reply_interval,
            end_buffer=args.end_buffer,
            reply_probability=args.reply_probability,
            mention_reply_probability=args.mention_reply_probability,
            random_delay_min=args.random_delay_min,
            random_delay_max=args.random_delay_max,
            skip_short_ack=args.skip_short_ack,
            merge_window=args.merge_window)
        return
    raise AssertionError(args.game_command)


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
    require_credentials = args.command in telegram_commands

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
        else:
            parser.error('unknown command {}'.format(args.command))
        return 0
    except (ConfigError, SafetyError, TelegramCliError) as exc:
        print('error: {}'.format(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
