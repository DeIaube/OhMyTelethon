import argparse
import asyncio
import copy
import importlib
import inspect
import json
import os
import sqlite3
import sys

from . import __version__
from . import account_isolation
from .config import (
    ConfigError, load_config, normalize_chat_id, normalize_daemon,
    normalize_round,
)
from . import daemon as daemon_store
from . import bad_cases as bad_case_store
from . import scenarios as scenario_store
from .agent_memory import MemoryStore
from .agent_report import summarize_agent_run
from .agent_rooms import select_next_room
from . import safety
from .safety import SafetyError
from .telegram_ops import (
    TelegramCliError, codex_context, daemon_run, dumps_json, get_me,
    group_context, history, interactive_round, list_dialogs, observe, send_text,
    validate_agent_reply_parts,
)


quota_store = None


def _rewrite_quota_chat_args(args):
    if args is None:
        args = sys.argv[1:]
    args = list(args)
    rewritten = []
    index = 0
    while index < len(args):
        value = args[index]
        if (
                value == '--chat'
                and index + 1 < len(args)
                and str(args[index + 1]).startswith('-')
                and ':' in str(args[index + 1])):
            rewritten.append('--chat={}'.format(args[index + 1]))
            index += 2
            continue
        rewritten.append(value)
        index += 1
    return rewritten


class TgArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        return super().parse_args(_rewrite_quota_chat_args(args), namespace)

    def parse_known_args(self, args=None, namespace=None):
        return super().parse_known_args(
            _rewrite_quota_chat_args(args), namespace)


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


def _resolve_character(config, preset_name=None):
    if hasattr(config, 'resolve_character'):
        return config.resolve_character(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return dict(getattr(config, 'character', {}) or {})


def _resolve_daemon(config, preset_name=None):
    if hasattr(config, 'resolve_daemon'):
        return config.resolve_daemon(preset_name)
    if preset_name not in (None, ''):
        raise ConfigError('Presets are not supported by this config object.')
    return normalize_daemon(getattr(config, 'daemon', {}) or {})


def _copy_config_with_game_settings(
        config, profile, round_config=None, reply_policy=None,
        initiative=None, persona=None, character=None, daemon_config=None,
        preset_name=None):
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
    if character is not None:
        game_config.character = character
    if daemon_config is not None:
        game_config.daemon = daemon_config
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


def _quota_module():
    global quota_store
    if quota_store is None:
        try:
            quota_store = importlib.import_module('.quota', __package__)
        except ImportError as exc:
            raise TelegramCliError(
                'Quota state support is not available yet; expected tg_cli.quota.'
            ) from exc
    return quota_store


def _quota_state_path(config):
    quota_config = getattr(config, 'quota', {}) or {}
    state_path = quota_config.get('state_path')
    if state_path in (None, ''):
        raise ConfigError('quota.state_path is not configured.')
    return state_path


def _parse_quota_chat(value):
    text = str(value or '').strip()
    if ':' not in text:
        raise argparse.ArgumentTypeError(
            '--chat must use CHAT_ID:COUNT, for example 5217114569:120.')
    chat_text, count_text = text.rsplit(':', 1)
    chat_text = chat_text.strip()
    count_text = count_text.strip()
    if not chat_text:
        raise argparse.ArgumentTypeError('quota chat id must not be empty.')
    try:
        chat_id = int(normalize_chat_id(chat_text))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            'quota chat id must be an integer.') from exc
    try:
        target_count = int(count_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            'quota target count must be an integer.') from exc
    if target_count < 1:
        raise argparse.ArgumentTypeError(
            'quota target count must be greater than 0.')
    return {'chat_id': chat_id, 'target_count': target_count}


def _quota_targets(chat_specs):
    targets = []
    seen = set()
    for spec in chat_specs or []:
        target = dict(spec)
        chat_id = int(target['chat_id'])
        if chat_id in seen:
            raise ConfigError(
                'Duplicate quota target chat id: {}.'.format(chat_id))
        seen.add(chat_id)
        targets.append({
            'chat_id': chat_id,
            'target_count': int(target['target_count']),
        })
    if not targets:
        raise ConfigError('At least one --chat CHAT_ID:COUNT target is required.')
    return targets


def _quota_status(config):
    store = _quota_module()
    helper = getattr(store, 'status', None) or getattr(store, 'get_status', None)
    if helper is None:
        raise TelegramCliError(
            'Quota state module must expose status(path) or get_status(path).')
    return helper(_quota_state_path(config))


def _create_quota_run(store, path, targets, preset=None, scenario=None,
                      account_name=''):
    kwargs = {'preset': preset}
    if scenario is not None:
        kwargs['scenario'] = scenario
    if account_name:
        kwargs['account_name'] = account_name
    try:
        return store.create_run(path, targets, **kwargs)
    except TypeError as exc:
        if 'account_name' not in str(exc):
            raise
        kwargs.pop('account_name', None)
        return store.create_run(path, targets, **kwargs)


def _quota_target_remaining(target):
    return max(0, int(target.get('target_count') or 0) -
               int(target.get('sent_count') or 0))


def _select_quota_target(state):
    rooms = []
    for target in (state or {}).get('targets') or []:
        remaining = _quota_target_remaining(target)
        rooms.append({
            'chat_id': target.get('chat_id'),
            'status': target.get('status', 'active'),
            'remaining_count': remaining,
            'last_sent_at': target.get('last_sent_at') or '',
            'target': target,
        })
    selected = select_next_room(rooms)
    if selected is None:
        return None
    return selected['target']


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _quota_task_context(config, target, preset=None):
    telegram_ops = importlib.import_module('.telegram_ops', __package__)
    helper = (
        getattr(telegram_ops, 'quota_task_context', None)
        or getattr(telegram_ops, 'quota_context', None)
    )
    if helper is None:
        return None
    config.require_credentials()
    return await _maybe_await(
        helper(config, int(target['chat_id']), preset=preset))


async def _quota_next_context_payload(config):
    telegram_ops = importlib.import_module('.telegram_ops', __package__)
    helper = getattr(telegram_ops, 'quota_next_context', None)
    if helper is None:
        return None
    config.require_credentials()
    return await _maybe_await(helper(config))


def _quota_task_chat_id(task):
    chat = (task or {}).get('chat') or {}
    chat_id = chat.get('id') if isinstance(chat, dict) else None
    if chat_id is None:
        context = (task or {}).get('context') or {}
        chat = context.get('chat') if isinstance(context, dict) else {}
        chat_id = chat.get('id') if isinstance(chat, dict) else None
    if chat_id is None:
        chat_id = (task or {}).get('chat_id')
    if chat_id is None:
        raise TelegramCliError(
            'Quota task is missing chat id: {}'.format(
                (task or {}).get('id') or 'unknown'))
    return int(normalize_chat_id(chat_id))


def _config_for_quota_task(config, task):
    task_config = copy.copy(config)
    context = (task or {}).get('context') or {}
    for field_name in ('profile', 'persona', 'reply_policy', 'initiative'):
        value = task.get(field_name)
        if value is None and isinstance(context, dict):
            value = context.get(field_name)
        if value is not None:
            setattr(task_config, field_name, value)
    return task_config


def _validate_quota_reply(config, task, text):
    task_config = _config_for_quota_task(config, task)
    chat_id = _quota_task_chat_id(task)
    safety.require_can_write(task_config, chat_id)
    matches = safety.find_forbidden_terms(task_config, text)
    if matches:
        chat = task.get('chat') or {}
        safety.audit_record(
            task_config, 'quota_reply', chat_id,
            chat_title=chat.get('title'), text=text,
            status='blocked_forbidden_terms')
        raise safety.SafetyError(
            'Message contains forbidden/sensitive profile term(s): {}.'.format(
                ', '.join(matches)))
    validate_agent_reply_parts(task_config, text)
    return task_config


async def _quota_send_reply(config, task_id, task, text, dry_run=False):
    telegram_ops = importlib.import_module('.telegram_ops', __package__)
    quota_reply = getattr(telegram_ops, 'quota_reply', None)
    if quota_reply is not None:
        if getattr(telegram_ops, 'quota_store', None) is None:
            telegram_ops.quota_store = _quota_module()
        result = quota_reply(config, task_id, text, dry_run=dry_run)
        result = await _maybe_await(result)
        return (result if result is not None else {}), False

    helper = getattr(telegram_ops, 'send_quota_reply', None)
    if helper is None:
        raise TelegramCliError(
            'Quota reply sending is not available yet; expected '
            'tg_cli.telegram_ops.send_quota_reply or quota_reply.')
    config.require_credentials()
    result = helper(config, task, text, dry_run=dry_run)
    result = await _maybe_await(result)
    return (result if result is not None else {}), True


def _quota_message_ids(send_result, dry_run=False):
    if dry_run:
        return []
    if isinstance(send_result, (list, tuple)):
        return list(send_result)
    if not isinstance(send_result, dict):
        raise TelegramCliError('Quota reply helper returned an invalid result.')
    if send_result.get('message_ids') is not None:
        return list(send_result.get('message_ids') or [])
    if send_result.get('message_id') is not None:
        return [send_result['message_id']]
    raise TelegramCliError('Quota reply helper did not return message ids.')


def build_parser():
    parser = TgArgumentParser(prog='tg-cli')
    parser.add_argument('--version', action='version', version='tg-cli {}'.format(__version__))
    parser.add_argument('--config', help='Path to JSON config. Defaults to ./.tg-cli.json then ~/.config/tg-cli/config.json.')
    sub = parser.add_subparsers(dest='command', required=True)

    config_cmd = sub.add_parser(
        'config', help='Inspect and validate tg-cli configuration.')
    config_sub = config_cmd.add_subparsers(
        dest='config_command', required=True)

    config_inspect = config_sub.add_parser(
        'inspect', help='Show resolved config paths and account metadata.')
    config_inspect.add_argument('--json', action='store_true')

    config_doctor = config_sub.add_parser(
        'doctor', help='Check this config against other account configs.')
    config_doctor.add_argument(
        '--other-config', action='append', default=[], required=True,
        help='Another account config to compare. Repeat for more accounts.')
    config_doctor.add_argument('--json', action='store_true')

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

    context = game_sub.add_parser(
        'context',
        help='Read recent history and print an agent-ready group warmup summary.')
    context.add_argument('chat')
    context.add_argument('--limit', '-n', type=int, default=200)
    context.add_argument('--preset', help='Named profile/round preset from config.presets.')
    context.add_argument(
        '--operator', default='codex',
        help='Operator name to include in the generated context, such as codex or claude.')
    context.add_argument('--json', action='store_true')

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

    quota = sub.add_parser(
        'quota', help='Manage multi-chat quota runs for external agents.')
    quota_sub = quota.add_subparsers(dest='quota_command', required=True)

    quota_start = quota_sub.add_parser(
        'start', help='Start a quota run with one or more chat targets.')
    quota_start.add_argument(
        '--chat', action='append', type=_parse_quota_chat, required=True,
        help='Target chat and successful-send count as CHAT_ID:COUNT.')
    quota_start.add_argument('--preset', help='Named preset from config.presets.')
    quota_start.add_argument('--json', action='store_true')

    quota_status = quota_sub.add_parser(
        'status', help='Show quota run state.')
    quota_status.add_argument('--json', action='store_true')

    quota_stop = quota_sub.add_parser(
        'stop', help='Stop the current quota run.')
    quota_stop.add_argument('--json', action='store_true')

    quota_next = quota_sub.add_parser(
        'next', help='Create the next quota task for an external operator.')
    quota_next.add_argument('--json', action='store_true')

    quota_reply = quota_sub.add_parser(
        'reply', help='Send or validate a reply for one quota task.')
    quota_reply.add_argument('task_id')
    quota_reply.add_argument('text')
    quota_reply.add_argument(
        '--dry-run', action='store_true',
        help='Validate without sending or incrementing quota counts.')
    quota_reply.add_argument('--json', action='store_true')

    quota_skip = quota_sub.add_parser(
        'skip', help='Skip one pending quota task without sending.')
    quota_skip.add_argument('task_id')
    quota_skip.add_argument(
        '--reason', default='skipped',
        help='Reason stored on the skipped quota task.')
    quota_skip.add_argument('--json', action='store_true')

    scenario = sub.add_parser(
        'scenario', help='Manage local long-run quota scenarios.')
    scenario_sub = scenario.add_subparsers(
        dest='scenario_command', required=True)

    scenario_list = scenario_sub.add_parser(
        'list', help='List configured long-run scenarios.')
    scenario_list.add_argument(
        '--path', default=str(scenario_store.DEFAULT_SCENARIOS_PATH),
        help='Path to local scenario JSON config.')
    scenario_list.add_argument('--json', action='store_true')

    scenario_show = scenario_sub.add_parser(
        'show', help='Show one configured long-run scenario.')
    scenario_show.add_argument('name')
    scenario_show.add_argument(
        '--path', default=str(scenario_store.DEFAULT_SCENARIOS_PATH),
        help='Path to local scenario JSON config.')
    scenario_show.add_argument('--json', action='store_true')

    scenario_start = scenario_sub.add_parser(
        'start', help='Start a quota run from one configured scenario.')
    scenario_start.add_argument('name')
    scenario_start.add_argument(
        '--path', default=str(scenario_store.DEFAULT_SCENARIOS_PATH),
        help='Path to local scenario JSON config.')
    scenario_start.add_argument('--json', action='store_true')

    memory = sub.add_parser('memory', help='Manage local agent memory.')
    memory_sub = memory.add_subparsers(dest='memory_command', required=True)

    memory_remember = memory_sub.add_parser(
        'remember', help='Store one memory note.')
    memory_remember.add_argument('chat')
    memory_remember.add_argument(
        '--scope', choices=('room', 'user'), required=True)
    memory_remember.add_argument('--sender-id', type=int)
    memory_remember.add_argument('--sender-name')
    memory_remember.add_argument('--kind', default='note')
    memory_remember.add_argument('--text', required=True)
    memory_remember.add_argument('--source-task-id')
    memory_remember.add_argument('--confidence', type=float, default=1.0)
    memory_remember.add_argument('--json', action='store_true')

    memory_list = memory_sub.add_parser(
        'list', help='List relevant memories for a chat.')
    memory_list.add_argument('chat')
    memory_list.add_argument('--sender-id', type=int)
    memory_list.add_argument('--limit', type=int, default=20)
    memory_list.add_argument('--json', action='store_true')

    badcase = sub.add_parser('badcase', help='Inspect local bad case records.')
    badcase_sub = badcase.add_subparsers(dest='badcase_command', required=True)

    badcase_list = badcase_sub.add_parser(
        'list', help='List recent local bad cases.')
    badcase_list.add_argument('--chat', type=normalize_chat_id)
    badcase_list.add_argument('--type')
    badcase_list.add_argument('--reason')
    badcase_list.add_argument('--limit', type=int, default=20)
    badcase_list.add_argument('--json', action='store_true')

    badcase_export = badcase_sub.add_parser(
        'export', help='Export local bad cases as JSONL or JSON.')
    badcase_export.add_argument('--chat', type=normalize_chat_id)
    badcase_export.add_argument('--type')
    badcase_export.add_argument('--reason')
    badcase_export.add_argument('--limit', type=int)
    badcase_export.add_argument('--json', action='store_true')

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
        character = _resolve_character(config, args.preset)
        game_config = _copy_config_with_game_settings(
            config, profile, reply_policy=reply_policy,
            initiative=initiative, persona=persona, character=character,
            preset_name=args.preset)
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
            print('Character: {}'.format(data.get('character') or {}))
            print('Reply policy: {}'.format(data['reply_policy']))
            print('Initiative: {}'.format(data['initiative']))
            print('Recent messages:')
            for item in data['messages']:
                print('- [{id}] {sender}: {text}'.format(**item))
            print('\nAgent instruction:')
            print(data['instruction'])
        return
    if args.game_command == 'context':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        character = _resolve_character(config, args.preset)
        game_config = _copy_config_with_game_settings(
            config, profile, reply_policy=reply_policy,
            initiative=initiative, persona=persona, character=character,
            preset_name=args.preset)
        data = await group_context(
            game_config, args.chat, args.limit,
            operator=args.operator, preset=args.preset)
        if args.json:
            print(dumps_json(data))
        else:
            print('Chat: {title} (id={id})'.format(**data['chat']))
            print('Operator: {}'.format(data['operator']))
            print('Preset: {}'.format(data['preset'] or 'default'))
            print('Messages analyzed: {}'.format(data['message_count']))
            print('Summary: {}'.format(data['summary']))
            print('Active speakers:')
            for item in data['active_speakers']:
                print('- {sender}: {count}'.format(**item))
            print('Recent topics: {}'.format(
                ', '.join(data['recent_topics']) or 'none'))
            print('Recent questions:')
            for item in data['recent_questions']:
                print('- [{id}] {sender}: {text}'.format(**item))
            print('Guidance:')
            for item in data['guidance']:
                print('- {}'.format(item))
        return
    if args.game_command == 'round':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        character = _resolve_character(config, args.preset)
        round_config = _round_with_cli_overrides(
            _resolve_round(config, args.preset), args)
        game_config = _copy_config_with_game_settings(
            config, profile, round_config, reply_policy=reply_policy,
            initiative=initiative, persona=persona, character=character,
            preset_name=args.preset)
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
    task_config.character = (
        task.get('character') or getattr(config, 'character', {}))
    return task_config


def _daemon_status_payload(config):
    status = daemon_store.read_status(_daemon_path(config, 'status'))
    counts = daemon_store.queue_counts(_daemon_path(config, 'queue'))
    lock_path = _daemon_path(config, 'lock')
    return {
        'account_name': getattr(config, 'account_name', '') or '',
        'paused': bool(safety.load_state(config).get('paused')),
        'running': bool(status.get('running')),
        'stop_requested': bool(status.get('stop_requested')),
        'status': status,
        'queue_counts': counts,
        'queue_path': str(_daemon_path(config, 'queue')),
        'lock_path': str(lock_path),
        'status_path': str(_daemon_path(config, 'status')),
        'locked': lock_path.is_file(),
        'agent_report': summarize_agent_run(status.get('agent_events') or []),
    }


async def _cmd_daemon(args, config):
    queue_path = _daemon_path(config, 'queue')
    status_path = _daemon_path(config, 'status')

    if args.daemon_command == 'run':
        profile = _resolve_profile(config, args.preset)
        reply_policy = _resolve_reply_policy(config, args.preset)
        initiative = _resolve_initiative(config, args.preset)
        persona = _resolve_persona(config, args.preset)
        character = _resolve_character(config, args.preset)
        round_config = _resolve_round(config, args.preset)
        resolved_daemon = _resolve_daemon(config, args.preset)
        daemon_config = _copy_config_with_game_settings(
            config, profile, round_config, reply_policy=reply_policy,
            initiative=initiative, persona=persona, character=character,
            daemon_config=resolved_daemon, preset_name=args.preset)
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
        validate_agent_reply_parts(task_config, text)
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


async def _cmd_quota(args, config):
    state_path = _quota_state_path(config)
    store = _quota_module()

    if args.quota_command == 'start':
        targets = _quota_targets(args.chat)
        if args.preset:
            _resolve_profile(config, args.preset)
        for target in targets:
            safety.require_allowed_chat(config, target['chat_id'])
        payload = _create_quota_run(
            store, state_path, targets, preset=args.preset,
            account_name=getattr(config, 'account_name', '') or '')
        if args.json:
            print(dumps_json(payload))
        else:
            print('Started quota run {} with {} target(s).'.format(
                payload.get('run_id', 'unknown'), len(targets)))
        return

    if args.quota_command == 'status':
        payload = _quota_status(config)
        payload.setdefault(
            'agent_report',
            summarize_agent_run(payload.get('tasks') or []))
        if args.json:
            print(dumps_json(payload))
        else:
            print('status={}'.format(payload.get('status') or 'none'))
            for target in payload.get('targets') or []:
                print('chat={} sent={}/{} status={}'.format(
                    target.get('chat_id'),
                    int(target.get('sent_count') or 0),
                    int(target.get('target_count') or 0),
                    target.get('status') or 'unknown'))
        return

    if args.quota_command == 'stop':
        payload = store.stop_run(state_path)
        if args.json:
            print(dumps_json(payload))
        else:
            print('Stopped quota run {}.'.format(
                payload.get('run_id', 'unknown')))
        return

    if args.quota_command == 'next':
        context_payload = await _quota_next_context_payload(config)
        if context_payload is not None:
            if args.json:
                print(dumps_json(context_payload))
            else:
                task = context_payload.get('task')
                if task is None:
                    print('No active quota target.')
                else:
                    print('Task: {} chat={}'.format(
                        task.get('id'),
                        task.get('chat_id')
                        or ((task.get('context') or {}).get('chat') or {}).get('id')))
                    context = context_payload.get('context') or {}
                    prompt = context.get('prompt') or task.get('prompt') or ''
                    if prompt:
                        print('Prompt:')
                        print(prompt)
            return

        state = _quota_status(config)
        target = _select_quota_target(state)
        if target is None:
            payload = {'task': None, 'reason': 'no_active_quota_target'}
            if args.json:
                print(dumps_json(payload))
            else:
                print('No active quota target.')
            return
        context = await _quota_task_context(
            config, target, preset=state.get('preset'))
        task = store.create_task(
            state_path, int(target['chat_id']), context=context)
        if args.json:
            print(dumps_json(task))
        else:
            print('Task: {} chat={} remaining={}'.format(
                task.get('id'), target.get('chat_id'),
                _quota_target_remaining(target)))
            prompt = task.get('prompt') or ''
            if prompt:
                print('Prompt:')
                print(prompt)
        return

    if args.quota_command == 'reply':
        text = (args.text or '').strip()
        if not text:
            raise TelegramCliError('Reply text must not be empty.')
        task = store.get_task(state_path, args.task_id)
        if task is None:
            raise TelegramCliError(
                'Quota task not found: {}'.format(args.task_id))
        _validate_quota_reply(config, task, text)
        send_result, complete_in_cli = await _quota_send_reply(
            config, args.task_id, task, text, dry_run=args.dry_run)
        message_ids = _quota_message_ids(send_result, dry_run=args.dry_run)
        if complete_in_cli:
            completed = store.complete_task(
                state_path, args.task_id, message_ids, dry_run=False)
        elif args.dry_run:
            completed = task
        else:
            completed = send_result.get('task') if isinstance(send_result, dict) else None
        payload = {
            'sent': not args.dry_run,
            'dry_run': bool(args.dry_run),
            'message_ids': message_ids,
            'send_result': send_result,
            'task': completed,
        }
        if args.json:
            print(dumps_json(payload))
        elif args.dry_run:
            print('DRY-RUN quota reply accepted for task {}.'.format(
                args.task_id))
        else:
            print('Sent quota reply for task {} ({} message id(s)).'.format(
                args.task_id, len(message_ids)))
        return

    if args.quota_command == 'skip':
        skip_task = getattr(store, 'skip_task', None)
        if skip_task is None:
            raise TelegramCliError('Quota module does not expose skip_task.')
        skipped = skip_task(
            state_path, args.task_id, reason=args.reason or 'skipped')
        if skipped is None:
            raise TelegramCliError(
                'Quota task is not pending or was not found: {}'.format(
                    args.task_id))
        payload = {'skipped': True, 'task': skipped}
        if args.json:
            print(dumps_json(payload))
        else:
            print('Skipped quota task {}.'.format(args.task_id))
        return

    raise AssertionError(args.quota_command)


async def _cmd_scenario(args, config):
    path = args.path

    if args.scenario_command == 'list':
        items = scenario_store.load_scenarios(path)
        payload = {
            'path': str(path),
            'scenarios': items,
        }
        if args.json:
            print(dumps_json(payload))
        else:
            for item in items:
                print('{} chat={} account={} persona={} target={} preset={}'.format(
                    item['name'], item['chat_id'], item['account'],
                    item['persona'], item['target_messages'], item['preset']))
        return

    if args.scenario_command == 'show':
        scenario = scenario_store.get_scenario(path, args.name)
        payload = {
            'path': str(path),
            'scenario': scenario,
        }
        if args.json:
            print(dumps_json(payload))
        else:
            print(dumps_json(scenario))
        return

    if args.scenario_command == 'start':
        scenario = scenario_store.get_scenario(path, args.name)
        _resolve_profile(config, scenario['preset'])
        chat_id = int(normalize_chat_id(scenario['chat_id']))
        scenario = dict(scenario)
        scenario['chat_id'] = chat_id
        safety.require_allowed_chat(config, chat_id)
        targets = [{
            'chat_id': chat_id,
            'target_count': int(scenario['target_messages']),
        }]
        store = _quota_module()
        payload = _create_quota_run(
            store,
            _quota_state_path(config), targets,
            preset=scenario['preset'], scenario=scenario,
            account_name=getattr(config, 'account_name', '') or '')
        result = {
            'path': str(path),
            'scenario': scenario,
            'quota': payload,
        }
        if args.json:
            print(dumps_json(result))
        else:
            print('Started scenario {} as quota run {}.'.format(
                scenario['name'], payload.get('run_id', 'unknown')))
        return

    raise AssertionError(args.scenario_command)


async def _cmd_memory(args, config):
    memory_config = getattr(config, 'memory', {}) or {}
    memory_path = memory_config.get('path')
    if memory_path in (None, ''):
        raise ConfigError('memory.path is not configured.')
    store = MemoryStore(memory_path)
    chat_id = normalize_chat_id(args.chat)

    if args.memory_command == 'remember':
        try:
            memory_id = store.remember(
                chat_id=chat_id,
                scope=args.scope,
                sender_id=args.sender_id,
                sender_name=args.sender_name,
                kind=args.kind,
                content=args.text,
                confidence=args.confidence,
                source_task_id=args.source_task_id)
        except ValueError as exc:
            raise TelegramCliError(str(exc)) from exc
        payload = {
            'remembered': True,
            'id': memory_id,
            'chat_id': chat_id,
            'scope': args.scope,
        }
        if args.json:
            print(dumps_json(payload))
        else:
            print('Stored memory id={} chat={} scope={}.'.format(
                memory_id, chat_id, args.scope))
        return

    if args.memory_command == 'list':
        memories = store.relevant_memories(
            chat_id=chat_id, sender_id=args.sender_id, limit=args.limit)
        payload = {
            'chat_id': chat_id,
            'sender_id': args.sender_id,
            'memories': memories,
        }
        if args.json:
            print(dumps_json(payload))
        else:
            for item in memories:
                print('[{id}] {scope} {kind}: {content}'.format(**item))
        return

    raise AssertionError(args.memory_command)


async def _cmd_badcase(args, config):
    records = bad_case_store.list_bad_cases(
        config,
        chat_id=getattr(args, 'chat', None),
        case_type=getattr(args, 'type', None),
        reason=getattr(args, 'reason', None),
        limit=getattr(args, 'limit', 20))
    payload = {
        'records': records,
        'path': str((getattr(config, 'bad_cases', {}) or {}).get('path') or ''),
    }

    if args.badcase_command == 'list':
        if args.json:
            print(dumps_json(payload))
        else:
            for item in records:
                print('[{id}] chat={chat_id} {case_type}/{reason} source={source}: {lesson}'.format(
                    id=item.get('id'),
                    chat_id=item.get('chat_id') or 'none',
                    case_type=item.get('case_type') or 'bad_case',
                    reason=item.get('reason') or 'unknown',
                    source=item.get('source') or 'unknown',
                    lesson=item.get('lesson') or '',
                ))
        return

    if args.badcase_command == 'export':
        if args.json:
            print(dumps_json(payload))
        else:
            text = bad_case_store.dumps_jsonl(records)
            if text:
                print(text)
        return

    raise AssertionError(args.badcase_command)


def _status_payload(config):
    state = safety.load_state(config)
    return {
        'account_name': getattr(config, 'account_name', '') or '',
        'paused': bool(state.get('paused')),
        'allowed_chats': list(config.allowed_chats),
        'session_path': str(config.session_path),
        'state_path': str(config.state_path),
        'audit_log_path': str(config.audit_log_path),
    }


def _print_config_inspect(payload):
    print('account_name={}'.format(payload.get('account_name') or '-'))
    print('config_path={}'.format(payload.get('config_path') or '-'))
    print('allowed_chats={}'.format(
        ','.join(str(x) for x in payload.get('allowed_chats') or []) or 'none'))
    for field_name, path in sorted(payload.get('runtime_paths', {}).items()):
        print('{}={}'.format(field_name, path))


def _print_config_doctor(payload):
    print('ok={}'.format(str(bool(payload.get('ok'))).lower()))
    for finding in payload.get('findings') or []:
        print('[{}] {}: {}'.format(
            finding.get('severity'), finding.get('code'),
            finding.get('message')))


def _cmd_config(args, config):
    if args.config_command == 'inspect':
        payload = account_isolation.inspect_config(config)
        if args.json:
            _print_json(payload)
        else:
            _print_config_inspect(payload)
        return 0
    if args.config_command == 'doctor':
        other_configs = [
            load_config(path, require_credentials=False)
            for path in args.other_config
        ]
        payload = account_isolation.doctor_configs(config, other_configs)
        if args.json:
            _print_json(payload)
        else:
            _print_config_doctor(payload)
        return 0 if payload['ok'] else 1
    raise AssertionError(args.config_command)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    telegram_commands = {'me', 'groups', 'dialogs', 'history', 'send', 'game'}
    require_credentials = (
        args.command in telegram_commands
        or (args.command == 'daemon' and args.daemon_command == 'run')
        or (
            args.command == 'quota'
            and args.quota_command == 'reply'
            and not args.dry_run))

    try:
        config = load_config(args.config, require_credentials=require_credentials)
        if args.command == 'config':
            return _cmd_config(args, config)
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
        elif args.command == 'quota':
            _run(_cmd_quota(args, config))
        elif args.command == 'scenario':
            _run(_cmd_scenario(args, config))
        elif args.command == 'memory':
            _run(_cmd_memory(args, config))
        elif args.command == 'badcase':
            _run(_cmd_badcase(args, config))
        else:
            parser.error('unknown command {}'.format(args.command))
        return 0
    except (
            ConfigError, SafetyError, TelegramCliError,
            scenario_store.ScenarioConfigError,
            daemon_store.DaemonLockError) as exc:
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
