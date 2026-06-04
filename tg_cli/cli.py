import argparse
import asyncio
import copy
import getpass
import importlib
import inspect
import json
import os
import sqlite3
import sys
import time

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
    TelegramCliError, admin_edit_admin, admin_kick, admin_log,
    admin_permissions_set, auth_edit_2fa, auth_login, auth_logout,
    auth_qr_login, auth_status, bot_inline_query, bot_inline_send,
    codex_context, copy_messages, daemon_run, delete_draft,
    delete_messages, dialog_delete, dialog_folder, download_media,
    download_profile_photo, dumps_json, edit_message, edit_message_media,
    forward_messages, get_me, get_messages_by_ids, group_context, history,
    interactive_round, list_dialogs, list_drafts, list_members,
    list_profile_photos, mark_read, message_action, observe, pin_message_op,
    resolve_entity, search_members, send_draft, send_media, send_text,
    set_draft, show_permissions, show_profile, show_stats,
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


def _parse_parse_mode(value):
    if value in (None, ''):
        return None
    value = str(value).strip().lower()
    if value == 'none':
        return None
    if value in ('md', 'markdown'):
        return 'md'
    if value == 'html':
        return 'html'
    raise TelegramCliError('parse mode must be md, html, or none.')


def _message_ids_arg(values):
    if values in (None, ''):
        return []
    if isinstance(values, str):
        values = [values]
    result = []
    for item in values:
        try:
            result.append(int(item))
        except (TypeError, ValueError) as exc:
            raise TelegramCliError(
                'message id must be an integer: {}'.format(item)) from exc
    return result


def _print_dialog_rows(rows):
    for row in rows:
        display = dict(row)
        display['username'] = '@{}'.format(row['username']) if row.get('username') else '-'
        display['count'] = row['participants_count'] if row.get('participants_count') is not None else '-'
        print('[{kind}] {title} | id={id} | username={username} | members={count}'.format(**display))


def _print_messages(row, messages):
    print('History: {} (id={})'.format(row['title'], row['id']))
    for item in messages:
        suffix = ''
        if item.get('media'):
            suffix = ' [media:{}]'.format(item['media'].get('kind'))
        print('[{id}] {sender}: {text}{suffix}'.format(
            suffix=suffix, **item))


def _run(coro):
    return asyncio.run(coro)


async def _call_async_supported(func, *args, **kwargs):
    signature = inspect.signature(func)
    has_var_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values())
    if not has_var_kwargs:
        kwargs = {
            key: value for key, value in kwargs.items()
            if key in signature.parameters
        }
    return await func(*args, **kwargs)


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


def _quota_progress_payload(state):
    targets = []
    total_target = 0
    total_sent = 0
    for target in (state or {}).get('targets') or []:
        target_count = int(target.get('target_count') or 0)
        sent_count = int(target.get('sent_count') or 0)
        remaining_count = max(0, target_count - sent_count)
        total_target += target_count
        total_sent += sent_count
        targets.append({
            'chat_id': target.get('chat_id'),
            'status': target.get('status') or 'unknown',
            'sent_count': sent_count,
            'target_count': target_count,
            'remaining_count': remaining_count,
            'last_sent_at': target.get('last_sent_at'),
        })
    return {
        'run_id': (state or {}).get('run_id'),
        'status': (state or {}).get('status') or 'empty',
        'sent_count': total_sent,
        'target_count': total_target,
        'remaining_count': max(0, total_target - total_sent),
        'targets': targets,
    }


async def _quota_step_next_payload(config, state_path, store):
    context_payload = await _quota_next_context_payload(config)
    if context_payload is not None:
        state = context_payload.get('status') or _quota_status(config)
        return {
            'task': context_payload.get('task'),
            'context': context_payload.get('context'),
            'status': state,
            'source': 'telegram_ops',
        }

    state = _quota_status(config)
    target = _select_quota_target(state)
    if target is None:
        return {
            'task': None,
            'context': None,
            'status': state,
            'source': 'quota_state',
            'reason': 'no_active_quota_target',
        }
    context = await _quota_task_context(
        config, target, preset=state.get('preset'))
    task = store.create_task(
        state_path, int(target['chat_id']), context=context)
    return {
        'task': task,
        'context': context,
        'status': _quota_status(config),
        'source': 'quota_state',
    }


async def _quota_reply_payload(config, store, state_path, task_id, text,
                               dry_run=False):
    text = (text or '').strip()
    if not text:
        raise TelegramCliError('Reply text must not be empty.')
    task = store.get_task(state_path, task_id)
    if task is None:
        raise TelegramCliError('Quota task not found: {}'.format(task_id))
    _validate_quota_reply(config, task, text)
    send_result, complete_in_cli = await _quota_send_reply(
        config, task_id, task, text, dry_run=dry_run)
    message_ids = _quota_message_ids(send_result, dry_run=dry_run)
    if complete_in_cli:
        completed = store.complete_task(
            state_path, task_id, message_ids, dry_run=False)
    elif dry_run:
        completed = task
    else:
        completed = (
            send_result.get('task') if isinstance(send_result, dict) else None)
    return {
        'sent': not dry_run,
        'dry_run': bool(dry_run),
        'message_ids': message_ids,
        'send_result': send_result,
        'task': completed,
    }


def _print_quota_step(payload):
    progress = payload.get('progress') or {}
    print('status={} sent={}/{} remaining={}'.format(
        progress.get('status') or 'empty',
        int(progress.get('sent_count') or 0),
        int(progress.get('target_count') or 0),
        int(progress.get('remaining_count') or 0)))
    task = payload.get('task')
    if task is None:
        print('No active quota task.')
        return
    print('Task: {} chat={}'.format(
        task.get('id'),
        task.get('chat_id')
        or ((task.get('context') or {}).get('chat') or {}).get('id')))
    if payload.get('dry_run'):
        print('DRY-RUN accepted.')
    if payload.get('send'):
        print('Sent {} message id(s).'.format(
            len(payload['send'].get('message_ids') or [])))
    if payload.get('skipped'):
        print('Skipped task.')
    next_action = payload.get('next_action')
    if next_action:
        print('next_action={}'.format(next_action))


def _print_quota_watch_snapshot(snapshot):
    progress = snapshot.get('progress') or {}
    print('status={} sent={}/{} remaining={} run={}'.format(
        progress.get('status') or 'empty',
        int(progress.get('sent_count') or 0),
        int(progress.get('target_count') or 0),
        int(progress.get('remaining_count') or 0),
        progress.get('run_id') or '-'))


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

    auth = sub.add_parser('auth', help='Account login/session commands.')
    auth_sub = auth.add_subparsers(dest='auth_command', required=True)
    auth_status = auth_sub.add_parser('status', help='Show authorization status.')
    auth_status.add_argument('--json', action='store_true')
    auth_login_cmd = auth_sub.add_parser('login', help='Interactive phone or bot-token login.')
    auth_login_cmd.add_argument('--phone')
    auth_login_cmd.add_argument('--bot-token')
    auth_login_cmd.add_argument('--password', action='store_true',
                                help='Prompt for 2FA password.')
    auth_login_cmd.add_argument('--json', action='store_true')
    auth_qr = auth_sub.add_parser('qr-login', help='Print a Telegram QR-login URL and wait for login.')
    auth_qr.add_argument('--password', action='store_true',
                         help='Prompt for 2FA password if needed.')
    auth_qr.add_argument('--timeout', type=float)
    auth_qr.add_argument('--json', action='store_true')
    auth_logout_cmd = auth_sub.add_parser('logout', help='Log out and delete the current session.')
    auth_logout_cmd.add_argument('--yes', action='store_true')
    auth_logout_cmd.add_argument('--dry-run', action='store_true')
    auth_logout_cmd.add_argument('--json', action='store_true')
    auth_2fa = auth_sub.add_parser('edit-2fa', help='Edit two-step verification settings.')
    auth_2fa.add_argument('--current-password', action='store_true')
    auth_2fa.add_argument('--new-password', action='store_true')
    auth_2fa.add_argument('--hint', default='')
    auth_2fa.add_argument('--email')
    auth_2fa.add_argument('--yes', action='store_true')
    auth_2fa.add_argument('--dry-run', action='store_true')
    auth_2fa.add_argument('--json', action='store_true')

    me = sub.add_parser('me', help='Show the logged-in Telegram account.')
    me.add_argument('--json', action='store_true')

    groups = sub.add_parser('groups', help='List groups and channels.')
    groups.add_argument('--limit', type=int)
    groups.add_argument('--query')
    groups.add_argument(
        '--kind', action='append',
        choices=('user', 'bot', 'chat', 'supergroup', 'channel'))
    groups.add_argument('--archived', action='store_true', default=None)
    groups.add_argument('--folder', type=int)
    groups.add_argument('--json', action='store_true')

    dialogs = sub.add_parser('dialogs', help='List all dialogs.')
    dialogs.add_argument('--limit', type=int)
    dialogs.add_argument('--query')
    dialogs.add_argument(
        '--kind', action='append',
        choices=('user', 'bot', 'chat', 'supergroup', 'channel'))
    dialogs.add_argument('--archived', action='store_true', default=None)
    dialogs.add_argument('--folder', type=int)
    dialogs.add_argument('--json', action='store_true')

    dialog = sub.add_parser('dialog', help='Manage one dialog.')
    dialog_sub = dialog.add_subparsers(dest='dialog_command', required=True)
    dialog_archive = dialog_sub.add_parser('archive', help='Archive one dialog.')
    dialog_archive.add_argument('chat')
    dialog_archive.add_argument('--yes', action='store_true')
    dialog_archive.add_argument('--dry-run', action='store_true')
    dialog_archive.add_argument('--json', action='store_true')
    dialog_unarchive = dialog_sub.add_parser('unarchive', help='Move one dialog out of archive.')
    dialog_unarchive.add_argument('chat')
    dialog_unarchive.add_argument('--yes', action='store_true')
    dialog_unarchive.add_argument('--dry-run', action='store_true')
    dialog_unarchive.add_argument('--json', action='store_true')
    dialog_delete_cmd = dialog_sub.add_parser('delete', help='Delete or leave one dialog.')
    dialog_delete_cmd.add_argument('chat')
    dialog_delete_cmd.add_argument('--revoke', action='store_true')
    dialog_delete_cmd.add_argument('--yes', action='store_true')
    dialog_delete_cmd.add_argument('--dry-run', action='store_true')
    dialog_delete_cmd.add_argument('--json', action='store_true')

    entity = sub.add_parser('entity', help='Resolve Telegram entities.')
    entity_sub = entity.add_subparsers(dest='entity_command', required=True)
    entity_resolve = entity_sub.add_parser(
        'resolve', help='Resolve one chat, channel, bot, or user.')
    entity_resolve.add_argument('query')
    entity_resolve.add_argument(
        '--no-users', action='store_true',
        help='Reject user entities and only allow chats/channels.')
    entity_resolve.add_argument('--json', action='store_true')

    members = sub.add_parser('members', help='Search group members.')
    members_sub = members.add_subparsers(
        dest='members_command', required=True)
    members_search = members_sub.add_parser(
        'search', help='Search members in one chat by display name or username.')
    members_search.add_argument('chat')
    members_search.add_argument('query')
    members_search.add_argument('--limit', type=int, default=20)
    members_search.add_argument('--json', action='store_true')
    members_list = members_sub.add_parser(
        'list', help='List members in one chat with optional participant filter.')
    members_list.add_argument('chat')
    members_list.add_argument('--limit', type=int, default=50)
    members_list.add_argument('--query', default='')
    members_list.add_argument(
        '--filter',
        choices=('admins', 'bots', 'recent', 'banned', 'restricted',
                 'kicked', 'contacts', 'search'))
    members_list.add_argument('--aggressive', action='store_true')
    members_list.add_argument('--json', action='store_true')

    profile = sub.add_parser('profile', help='Show a sanitized public profile.')
    profile_sub = profile.add_subparsers(
        dest='profile_command', required=True)
    profile_show = profile_sub.add_parser(
        'show', help='Show public profile fields for one user or bot.')
    profile_show.add_argument('query')
    profile_show.add_argument(
        '--chat',
        help='Search this chat first, then show the matched member profile.')
    profile_show.add_argument('--limit', type=int, default=20)
    profile_show.add_argument('--json', action='store_true')
    profile_photos = profile_sub.add_parser(
        'photos', help='List profile-photo metadata for one user/chat.')
    profile_photos.add_argument('query')
    profile_photos.add_argument('--limit', type=int, default=20)
    profile_photos.add_argument('--json', action='store_true')

    hist = sub.add_parser('history', help='Print recent messages from a chat.')
    hist.add_argument('chat')
    hist.add_argument('--limit', '-n', type=int, default=20)
    hist.add_argument('--search')
    hist.add_argument('--from-user')
    hist.add_argument('--min-id', type=int, default=0)
    hist.add_argument('--max-id', type=int, default=0)
    hist.add_argument('--offset-id', type=int, default=0)
    hist.add_argument('--offset-date')
    hist.add_argument('--reverse', action='store_true')
    hist.add_argument('--media-only', action='store_true')
    hist.add_argument('--allow-users', action='store_true')
    hist.add_argument('--filter')
    hist.add_argument('--reply-to', type=int)
    hist.add_argument('--scheduled', action='store_true')
    hist.add_argument('--json', action='store_true')

    send = sub.add_parser('send', help='Send one message through the safety layer.')
    send.add_argument('chat')
    send.add_argument('text')
    send.add_argument('--yes', action='store_true', help='Skip interactive confirmation.')
    send.add_argument('--dry-run', action='store_true', help='Resolve and audit without sending.')
    send.add_argument('--reply-to', type=int)
    send.add_argument(
        '--parse-mode', choices=('md', 'markdown', 'html', 'none'))
    send.add_argument(
        '--link-preview', dest='link_preview', action='store_true',
        default=None)
    send.add_argument(
        '--no-link-preview', dest='link_preview', action='store_false')
    send.add_argument('--silent', action='store_true', default=None)
    send.add_argument('--schedule')
    send.add_argument('--json', action='store_true')

    messages = sub.add_parser('messages', help='Message and media commands.')
    messages_sub = messages.add_subparsers(
        dest='messages_command', required=True)

    messages_history = messages_sub.add_parser(
        'history', help='Print recent messages from a chat.')
    messages_history.add_argument('chat')
    messages_history.add_argument('--limit', '-n', type=int, default=20)
    messages_history.add_argument('--search')
    messages_history.add_argument('--from-user')
    messages_history.add_argument('--min-id', type=int, default=0)
    messages_history.add_argument('--max-id', type=int, default=0)
    messages_history.add_argument('--offset-id', type=int, default=0)
    messages_history.add_argument('--offset-date')
    messages_history.add_argument('--reverse', action='store_true')
    messages_history.add_argument('--media-only', action='store_true')
    messages_history.add_argument('--allow-users', action='store_true')
    messages_history.add_argument('--filter')
    messages_history.add_argument('--reply-to', type=int)
    messages_history.add_argument('--scheduled', action='store_true')
    messages_history.add_argument('--json', action='store_true')

    messages_get = messages_sub.add_parser(
        'get', help='Fetch explicit message ids from one chat.')
    messages_get.add_argument('chat')
    messages_get.add_argument('message_ids', nargs='+')
    messages_get.add_argument('--allow-users', action='store_true')
    messages_get.add_argument('--json', action='store_true')

    messages_replies = messages_sub.add_parser(
        'replies', help='Fetch replies/comments for one message id.')
    messages_replies.add_argument('chat')
    messages_replies.add_argument('message_id', type=int)
    messages_replies.add_argument('--limit', '-n', type=int, default=20)
    messages_replies.add_argument('--json', action='store_true')

    messages_scheduled = messages_sub.add_parser(
        'scheduled', help='Fetch scheduled messages for one chat.')
    messages_scheduled.add_argument('chat')
    messages_scheduled.add_argument('--limit', '-n', type=int, default=20)
    messages_scheduled.add_argument('--json', action='store_true')

    messages_search = messages_sub.add_parser(
        'search', help='Search messages in one chat or globally.')
    messages_search.add_argument('query')
    messages_search.add_argument('--chat')
    messages_search.add_argument('--limit', '-n', type=int, default=20)
    messages_search.add_argument('--filter')
    messages_search.add_argument('--from-user')
    messages_search.add_argument('--global', dest='global_search', action='store_true')
    messages_search.add_argument('--json', action='store_true')

    messages_send = messages_sub.add_parser(
        'send', help='Send one text message through the safety layer.')
    messages_send.add_argument('chat')
    messages_send.add_argument('text')
    messages_send.add_argument('--yes', action='store_true')
    messages_send.add_argument('--dry-run', action='store_true')
    messages_send.add_argument('--reply-to', type=int)
    messages_send.add_argument(
        '--parse-mode', choices=('md', 'markdown', 'html', 'none'))
    messages_send.add_argument(
        '--link-preview', dest='link_preview', action='store_true',
        default=None)
    messages_send.add_argument(
        '--no-link-preview', dest='link_preview', action='store_false')
    messages_send.add_argument('--silent', action='store_true', default=None)
    messages_send.add_argument('--schedule')
    messages_send.add_argument('--clear-draft', action='store_true')
    messages_send.add_argument('--background', action='store_true', default=None)
    messages_send.add_argument('--comment-to', type=int)
    messages_send.add_argument('--send-as')
    messages_send.add_argument('--message-effect-id', type=int)
    messages_send.add_argument('--buttons-json')
    messages_send.add_argument('--json', action='store_true')

    messages_file = messages_sub.add_parser(
        'send-file', help='Send one or more files or media URLs.')
    messages_file.add_argument('chat')
    messages_file.add_argument('files', nargs='+')
    messages_file.add_argument('--caption')
    messages_file.add_argument('--force-document', action='store_true')
    messages_file.add_argument('--reply-to', type=int)
    messages_file.add_argument('--silent', action='store_true', default=None)
    messages_file.add_argument('--schedule')
    messages_file.add_argument('--voice-note', action='store_true')
    messages_file.add_argument('--video-note', action='store_true')
    messages_file.add_argument('--supports-streaming', action='store_true')
    messages_file.add_argument('--thumb')
    messages_file.add_argument('--ttl', type=int)
    messages_file.add_argument('--mime-type')
    messages_file.add_argument('--clear-draft', action='store_true')
    messages_file.add_argument('--background', action='store_true', default=None)
    messages_file.add_argument('--comment-to', type=int)
    messages_file.add_argument('--send-as')
    messages_file.add_argument('--message-effect-id', type=int)
    messages_file.add_argument('--buttons-json')
    messages_file.add_argument('--yes', action='store_true')
    messages_file.add_argument('--dry-run', action='store_true')
    messages_file.add_argument('--json', action='store_true')

    messages_edit = messages_sub.add_parser(
        'edit', help='Edit one text message.')
    messages_edit.add_argument('chat')
    messages_edit.add_argument('message_id', type=int)
    messages_edit.add_argument('text')
    messages_edit.add_argument(
        '--parse-mode', choices=('md', 'markdown', 'html', 'none'))
    messages_edit.add_argument(
        '--link-preview', dest='link_preview', action='store_true',
        default=None)
    messages_edit.add_argument(
        '--no-link-preview', dest='link_preview', action='store_false')
    messages_edit.add_argument('--yes', action='store_true')
    messages_edit.add_argument('--dry-run', action='store_true')
    messages_edit.add_argument('--buttons-json')
    messages_edit.add_argument('--schedule')
    messages_edit.add_argument('--json', action='store_true')

    messages_edit_media = messages_sub.add_parser(
        'edit-media', help='Edit text, media, or buttons for one message.')
    messages_edit_media.add_argument('chat')
    messages_edit_media.add_argument('message_id', type=int)
    messages_edit_media.add_argument('--text')
    messages_edit_media.add_argument('--file')
    messages_edit_media.add_argument('--thumb')
    messages_edit_media.add_argument('--force-document', action='store_true')
    messages_edit_media.add_argument('--supports-streaming', action='store_true')
    messages_edit_media.add_argument(
        '--parse-mode', choices=('md', 'markdown', 'html', 'none'))
    messages_edit_media.add_argument(
        '--link-preview', dest='link_preview', action='store_true',
        default=None)
    messages_edit_media.add_argument(
        '--no-link-preview', dest='link_preview', action='store_false')
    messages_edit_media.add_argument('--buttons-json')
    messages_edit_media.add_argument('--yes', action='store_true')
    messages_edit_media.add_argument('--dry-run', action='store_true')
    messages_edit_media.add_argument('--json', action='store_true')

    messages_delete = messages_sub.add_parser(
        'delete', help='Delete explicit message ids from one chat.')
    messages_delete.add_argument('chat')
    messages_delete.add_argument('message_ids', nargs='+')
    messages_delete.add_argument('--revoke', action='store_true')
    messages_delete.add_argument('--yes', action='store_true')
    messages_delete.add_argument('--dry-run', action='store_true')
    messages_delete.add_argument('--json', action='store_true')

    messages_forward = messages_sub.add_parser(
        'forward', help='Forward explicit message ids to a whitelisted chat.')
    messages_forward.add_argument('from_chat')
    messages_forward.add_argument('to_chat')
    messages_forward.add_argument('message_ids', nargs='+')
    messages_forward.add_argument('--silent', action='store_true', default=None)
    messages_forward.add_argument('--background', action='store_true', default=None)
    messages_forward.add_argument('--with-my-score', action='store_true', default=None)
    messages_forward.add_argument('--schedule')
    messages_forward.add_argument('--drop-author', action='store_true', default=None)
    messages_forward.add_argument('--drop-media-captions', action='store_true', default=None)
    messages_forward.add_argument('--yes', action='store_true')
    messages_forward.add_argument('--dry-run', action='store_true')
    messages_forward.add_argument('--json', action='store_true')

    messages_copy = messages_sub.add_parser(
        'copy', help='Copy explicit message ids without a forward header.')
    messages_copy.add_argument('from_chat')
    messages_copy.add_argument('to_chat')
    messages_copy.add_argument('message_ids', nargs='+')
    messages_copy.add_argument('--silent', action='store_true', default=None)
    messages_copy.add_argument('--yes', action='store_true')
    messages_copy.add_argument('--dry-run', action='store_true')
    messages_copy.add_argument('--json', action='store_true')

    messages_action = messages_sub.add_parser(
        'action', help='Show a bounded chat action such as typing or upload-photo.')
    messages_action.add_argument('chat')
    messages_action.add_argument('action')
    messages_action.add_argument('--duration', type=float, default=2.0)
    messages_action.add_argument('--delay', type=float, default=4.0)
    messages_action.add_argument('--yes', action='store_true')
    messages_action.add_argument('--dry-run', action='store_true')
    messages_action.add_argument('--json', action='store_true')

    messages_read = messages_sub.add_parser(
        'read', help='Mark a chat or explicit messages as read.')
    messages_read.add_argument('chat')
    messages_read.add_argument('message_ids', nargs='*')
    messages_read.add_argument('--clear-mentions', action='store_true')
    messages_read.add_argument('--clear-reactions', action='store_true')
    messages_read.add_argument('--yes', action='store_true')
    messages_read.add_argument('--dry-run', action='store_true')
    messages_read.add_argument('--json', action='store_true')

    messages_pin = messages_sub.add_parser(
        'pin', help='Pin one explicit message.')
    messages_pin.add_argument('chat')
    messages_pin.add_argument('message_id', type=int)
    messages_pin.add_argument('--notify', action='store_true')
    messages_pin.add_argument('--pm-oneside', action='store_true')
    messages_pin.add_argument('--yes', action='store_true')
    messages_pin.add_argument('--dry-run', action='store_true')
    messages_pin.add_argument('--json', action='store_true')

    messages_unpin = messages_sub.add_parser(
        'unpin', help='Unpin one explicit message.')
    messages_unpin.add_argument('chat')
    messages_unpin.add_argument('message_id', type=int)
    messages_unpin.add_argument('--notify', action='store_true')
    messages_unpin.add_argument('--yes', action='store_true')
    messages_unpin.add_argument('--dry-run', action='store_true')
    messages_unpin.add_argument('--json', action='store_true')

    drafts = sub.add_parser('drafts', help='Manage Telegram drafts.')
    drafts_sub = drafts.add_subparsers(dest='drafts_command', required=True)
    drafts_list = drafts_sub.add_parser('list', help='List drafts.')
    drafts_list.add_argument('chat', nargs='?')
    drafts_list.add_argument('--json', action='store_true')
    drafts_set = drafts_sub.add_parser('set', help='Set one draft message.')
    drafts_set.add_argument('chat')
    drafts_set.add_argument('text')
    drafts_set.add_argument(
        '--parse-mode', choices=('md', 'markdown', 'html', 'none'))
    drafts_set.add_argument(
        '--link-preview', dest='link_preview', action='store_true',
        default=None)
    drafts_set.add_argument(
        '--no-link-preview', dest='link_preview', action='store_false')
    drafts_set.add_argument('--reply-to', type=int)
    drafts_set.add_argument('--yes', action='store_true')
    drafts_set.add_argument('--dry-run', action='store_true')
    drafts_set.add_argument('--json', action='store_true')
    drafts_send = drafts_sub.add_parser('send', help='Send one existing draft.')
    drafts_send.add_argument('chat')
    drafts_send.add_argument('--yes', action='store_true')
    drafts_send.add_argument('--dry-run', action='store_true')
    drafts_send.add_argument('--json', action='store_true')
    drafts_delete = drafts_sub.add_parser('delete', help='Delete one draft.')
    drafts_delete.add_argument('chat')
    drafts_delete.add_argument('--yes', action='store_true')
    drafts_delete.add_argument('--dry-run', action='store_true')
    drafts_delete.add_argument('--json', action='store_true')

    downloads = sub.add_parser('downloads', help='Download media without printing bytes.')
    downloads_sub = downloads.add_subparsers(dest='downloads_command', required=True)
    downloads_media = downloads_sub.add_parser(
        'media', help='Download media from one explicit message id.')
    downloads_media.add_argument('chat')
    downloads_media.add_argument('message_id', type=int)
    downloads_media.add_argument('--output-dir')
    downloads_media.add_argument('--output-file')
    downloads_media.add_argument('--allow-users', action='store_true')
    downloads_media.add_argument('--json', action='store_true')
    downloads_profile = downloads_sub.add_parser(
        'profile-photo', help='Download one profile photo.')
    downloads_profile.add_argument('query')
    downloads_profile.add_argument('--output-dir')
    downloads_profile.add_argument('--small', dest='big', action='store_false', default=True)
    downloads_profile.add_argument('--json', action='store_true')

    admin = sub.add_parser('admin', help='Admin and moderation commands.')
    admin_sub = admin.add_subparsers(dest='admin_command', required=True)
    admin_log_cmd = admin_sub.add_parser('log', help='Read admin log events.')
    admin_log_cmd.add_argument('chat')
    admin_log_cmd.add_argument('--limit', type=int, default=20)
    admin_log_cmd.add_argument('--search')
    admin_log_cmd.add_argument('--admin', dest='admins', action='append')
    for flag in (
            'join', 'leave', 'invite', 'restrict', 'unrestrict', 'ban',
            'unban', 'promote', 'demote', 'info', 'settings', 'pinned',
            'edit', 'delete', 'group-call'):
        admin_log_cmd.add_argument('--{}'.format(flag), action='store_true')
    admin_log_cmd.add_argument('--json', action='store_true')
    admin_perm = admin_sub.add_parser('permissions', help='Show or edit permissions.')
    admin_perm_sub = admin_perm.add_subparsers(dest='permissions_command', required=True)
    admin_perm_show = admin_perm_sub.add_parser('show', help='Show chat or user permissions.')
    admin_perm_show.add_argument('chat')
    admin_perm_show.add_argument('--user')
    admin_perm_show.add_argument('--json', action='store_true')
    admin_perm_set = admin_perm_sub.add_parser('set', help='Set chat default or user permissions.')
    admin_perm_set.add_argument('chat')
    admin_perm_set.add_argument('--user')
    admin_perm_set.add_argument('--enable', action='append', default=[])
    admin_perm_set.add_argument('--disable', action='append', default=[])
    admin_perm_set.add_argument('--until')
    admin_perm_set.add_argument('--yes', action='store_true')
    admin_perm_set.add_argument('--dry-run', action='store_true')
    admin_perm_set.add_argument('--json', action='store_true')
    admin_stats = admin_sub.add_parser('stats', help='Show sanitized chat or message stats.')
    admin_stats.add_argument('chat')
    admin_stats.add_argument('--message-id', type=int)
    admin_stats.add_argument('--json', action='store_true')
    admin_kick_cmd = admin_sub.add_parser('kick', help='Kick one participant.')
    admin_kick_cmd.add_argument('chat')
    admin_kick_cmd.add_argument('user')
    admin_kick_cmd.add_argument('--yes', action='store_true')
    admin_kick_cmd.add_argument('--dry-run', action='store_true')
    admin_kick_cmd.add_argument('--json', action='store_true')
    admin_ban_cmd = admin_sub.add_parser('ban', help='Ban one participant.')
    admin_ban_cmd.add_argument('chat')
    admin_ban_cmd.add_argument('user')
    admin_ban_cmd.add_argument('--until')
    admin_ban_cmd.add_argument('--yes', action='store_true')
    admin_ban_cmd.add_argument('--dry-run', action='store_true')
    admin_ban_cmd.add_argument('--json', action='store_true')
    admin_unban_cmd = admin_sub.add_parser('unban', help='Remove participant restrictions.')
    admin_unban_cmd.add_argument('chat')
    admin_unban_cmd.add_argument('user')
    admin_unban_cmd.add_argument('--yes', action='store_true')
    admin_unban_cmd.add_argument('--dry-run', action='store_true')
    admin_unban_cmd.add_argument('--json', action='store_true')
    admin_promote_cmd = admin_sub.add_parser('promote', help='Promote or update admin rights.')
    admin_promote_cmd.add_argument('chat')
    admin_promote_cmd.add_argument('user')
    admin_promote_cmd.add_argument('--enable', action='append', default=[])
    admin_promote_cmd.add_argument('--disable', action='append', default=[])
    admin_promote_cmd.add_argument('--title')
    admin_promote_cmd.add_argument('--yes', action='store_true')
    admin_promote_cmd.add_argument('--dry-run', action='store_true')
    admin_promote_cmd.add_argument('--json', action='store_true')
    admin_demote_cmd = admin_sub.add_parser('demote', help='Remove admin status.')
    admin_demote_cmd.add_argument('chat')
    admin_demote_cmd.add_argument('user')
    admin_demote_cmd.add_argument('--yes', action='store_true')
    admin_demote_cmd.add_argument('--dry-run', action='store_true')
    admin_demote_cmd.add_argument('--json', action='store_true')

    bot = sub.add_parser('bot', help='Bot and inline query commands.')
    bot_sub = bot.add_subparsers(dest='bot_command', required=True)
    bot_inline_query_cmd = bot_sub.add_parser('inline-query', help='Run an inline query without sending.')
    bot_inline_query_cmd.add_argument('bot')
    bot_inline_query_cmd.add_argument('query')
    bot_inline_query_cmd.add_argument('--chat')
    bot_inline_query_cmd.add_argument('--offset')
    bot_inline_query_cmd.add_argument('--json', action='store_true')
    bot_inline_send_cmd = bot_sub.add_parser('inline-send', help='Send one selected inline result.')
    bot_inline_send_cmd.add_argument('bot')
    bot_inline_send_cmd.add_argument('query')
    bot_inline_send_cmd.add_argument('chat')
    bot_inline_send_cmd.add_argument('--index', type=int, default=0)
    bot_inline_send_cmd.add_argument('--reply-to', type=int)
    bot_inline_send_cmd.add_argument('--offset')
    bot_inline_send_cmd.add_argument('--yes', action='store_true')
    bot_inline_send_cmd.add_argument('--dry-run', action='store_true')
    bot_inline_send_cmd.add_argument('--json', action='store_true')

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

    quota_step = quota_sub.add_parser(
        'step',
        help='Show or advance one quota operator step without auto-generating text.')
    quota_step.add_argument(
        '--reply',
        help='Operator-provided reply text. Defaults to dry-run only.')
    quota_step.add_argument(
        '--send', action='store_true',
        help='After dry-run succeeds, explicitly send the provided reply.')
    quota_step.add_argument(
        '--skip-reason',
        help='Skip the selected pending task instead of replying.')
    quota_step.add_argument('--json', action='store_true')

    quota_watch = quota_sub.add_parser(
        'watch', help='Watch quota progress without opening Telegram.')
    quota_watch.add_argument(
        '--interval', type=float, default=5.0,
        help='Seconds between status reads.')
    quota_watch.add_argument(
        '--count', type=int, default=1,
        help='Number of snapshots to read.')
    quota_watch.add_argument('--json', action='store_true')

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


async def _cmd_auth(args, config):
    if args.auth_command == 'status':
        payload = await auth_status(config)
        if args.json:
            _print_json(payload)
        else:
            print('authorized={}'.format(str(payload['authorized']).lower()))
            if payload.get('me'):
                print('me={title} id={id}'.format(**payload['me']))
        return
    if args.auth_command == 'login':
        password = (
            getpass.getpass('2FA password: ')
            if args.password else None)
        payload = await auth_login(
            config, phone=args.phone, bot_token=args.bot_token,
            password=password,
            code_callback=lambda: input('Login code: ').strip())
        if args.json:
            _print_json(payload)
        else:
            print('Logged in as {title} id={id}'.format(**payload['me']))
        return
    if args.auth_command == 'qr-login':
        password = (
            getpass.getpass('2FA password: ')
            if args.password else None)
        payload = await auth_qr_login(
            config, password=password, timeout=args.timeout)
        if args.json:
            _print_json(payload)
        else:
            print('Logged in as {title} id={id}'.format(**payload['me']))
        return
    if args.auth_command == 'logout':
        payload = await auth_logout(
            config, assume_yes=args.yes, dry_run=args.dry_run)
        if args.json:
            _print_json(payload)
        else:
            print('LOGOUT {}'.format(
                'dry-run' if payload['dry_run'] else payload['logged_out']))
        return
    if args.auth_command == 'edit-2fa':
        current_password = (
            getpass.getpass('Current 2FA password: ')
            if args.current_password else None)
        new_password = (
            getpass.getpass('New 2FA password: ')
            if args.new_password else None)
        payload = await auth_edit_2fa(
            config,
            current_password=current_password,
            new_password=new_password,
            hint=args.hint,
            email=args.email,
            email_code_callback=(
                lambda length: input(
                    'Email code ({} chars): '.format(length)).strip()),
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(payload)
        else:
            print('2FA {}'.format(
                'dry-run' if payload['dry_run'] else payload['updated']))
        return
    raise AssertionError(args.auth_command)


async def _cmd_groups(args, config, groups_only=True):
    rows = await _call_async_supported(
        list_dialogs,
        config,
        groups_only=groups_only,
        limit=getattr(args, 'limit', None),
        kind=getattr(args, 'kind', None),
        query=getattr(args, 'query', None),
        archived=getattr(args, 'archived', None),
        folder=getattr(args, 'folder', None))
    if args.json:
        _print_json(rows)
        return
    _print_dialog_rows(rows)


async def _cmd_dialog(args, config):
    if args.dialog_command == 'archive':
        payload = await dialog_folder(
            config, args.chat, 1, assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.dialog_command == 'unarchive':
        payload = await dialog_folder(
            config, args.chat, 0, assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.dialog_command == 'delete':
        payload = await dialog_delete(
            config, args.chat, revoke=args.revoke,
            assume_yes=args.yes, dry_run=args.dry_run)
    else:
        raise AssertionError(args.dialog_command)
    if args.json:
        _print_json(payload)
    else:
        print('{} {}'.format(
            args.dialog_command.upper(),
            'dry-run' if payload['dry_run'] else 'ok'))


async def _cmd_entity(args, config):
    if args.entity_command == 'resolve':
        row = await resolve_entity(
            config, args.query, allow_users=not args.no_users)
        if args.json:
            _print_json(row)
        else:
            username = '@{}'.format(row['username']) if row.get('username') else '-'
            print('[{kind}] {title} | id={id} | peer_id={peer_id} | username={username}'.format(
                username=username, **row))
        return
    raise AssertionError(args.entity_command)


async def _cmd_members(args, config):
    if args.members_command == 'search':
        payload = await search_members(
            config, args.chat, args.query, limit=args.limit)
        if args.json:
            _print_json(payload)
            return
        print('Members: {} (id={}) query={!r}'.format(
            payload['chat']['title'], payload['chat']['id'], payload['query']))
        _print_dialog_rows(payload['members'])
        return
    if args.members_command == 'list':
        payload = await list_members(
            config, args.chat, limit=args.limit,
            participant_filter=args.filter, query=args.query,
            aggressive=args.aggressive)
        if args.json:
            _print_json(payload)
            return
        print('Members: {} (id={}) filter={}'.format(
            payload['chat']['title'], payload['chat']['id'],
            payload.get('filter') or 'all'))
        _print_dialog_rows(payload['members'])
        return
    raise AssertionError(args.members_command)


async def _cmd_profile(args, config):
    if args.profile_command == 'show':
        payload = await show_profile(
            config, args.query, chat=args.chat, limit=args.limit)
        if args.json:
            _print_json(payload)
            return
        profile = payload['profile']
        username = '@{}'.format(profile['username']) if profile.get('username') else '-'
        print('[{kind}] {display_name} | id={id} | peer_id={peer_id} | username={username}'.format(
            username=username, **profile))
        if profile.get('about'):
            print('about={}'.format(profile['about']))
        print('has_profile_photo={}'.format(
            str(bool(profile.get('has_profile_photo'))).lower()))
        return
    if args.profile_command == 'photos':
        payload = await list_profile_photos(
            config, args.query, limit=args.limit)
        if args.json:
            _print_json(payload)
            return
        print('Profile photos: {} count={}'.format(
            payload['entity']['title'], len(payload['photos'])))
        for item in payload['photos']:
            print('[{type}] id={id} date={date}'.format(**item))
        return
    raise AssertionError(args.profile_command)


async def _cmd_history(args, config):
    row, messages = await _call_async_supported(
        history,
        config, args.chat, args.limit,
        search=getattr(args, 'search', None),
        from_user=getattr(args, 'from_user', None),
        min_id=getattr(args, 'min_id', 0),
        max_id=getattr(args, 'max_id', 0),
        offset_id=getattr(args, 'offset_id', 0),
        offset_date=getattr(args, 'offset_date', None),
        reverse=getattr(args, 'reverse', False),
        media_only=getattr(args, 'media_only', False),
        allow_users=getattr(args, 'allow_users', False),
        message_filter=getattr(args, 'filter', None),
        reply_to=getattr(args, 'reply_to', None),
        scheduled=getattr(args, 'scheduled', False),
        global_search=getattr(args, 'global_search', False))
    if args.json:
        _print_json({'chat': row, 'messages': messages})
        return
    _print_messages(row, messages)


async def _cmd_send(args, config):
    kwargs = {
        'assume_yes': args.yes,
        'dry_run': args.dry_run,
        'reply_to': getattr(args, 'reply_to', None),
        'link_preview': getattr(args, 'link_preview', None),
        'silent': getattr(args, 'silent', None),
        'schedule': getattr(args, 'schedule', None),
        'clear_draft': getattr(args, 'clear_draft', False),
        'background': getattr(args, 'background', None),
        'comment_to': getattr(args, 'comment_to', None),
        'send_as': getattr(args, 'send_as', None),
        'message_effect_id': getattr(args, 'message_effect_id', None),
        'buttons_json': getattr(args, 'buttons_json', None),
    }
    if getattr(args, 'parse_mode', None) is not None:
        kwargs['parse_mode'] = _parse_parse_mode(args.parse_mode)
    result = await _call_async_supported(
        send_text,
        config, args.chat, args.text, **kwargs)
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


async def _cmd_messages(args, config):
    if args.messages_command == 'history':
        return await _cmd_history(args, config)
    if args.messages_command == 'get':
        payload = await get_messages_by_ids(
            config, args.chat, _message_ids_arg(args.message_ids),
            allow_users=args.allow_users)
        if args.json:
            _print_json(payload)
        else:
            _print_messages(payload['chat'], payload['messages'])
        return
    if args.messages_command == 'replies':
        row, messages = await history(
            config, args.chat, args.limit, reply_to=args.message_id)
        payload = {'chat': row, 'message_id': args.message_id,
                   'messages': messages}
        if args.json:
            _print_json(payload)
        else:
            _print_messages(row, messages)
        return
    if args.messages_command == 'scheduled':
        row, messages = await history(
            config, args.chat, args.limit, scheduled=True)
        payload = {'chat': row, 'messages': messages}
        if args.json:
            _print_json(payload)
        else:
            _print_messages(row, messages)
        return
    if args.messages_command == 'search':
        row, messages = await history(
            config, args.chat or 'global_search', args.limit,
            search=args.query,
            from_user=args.from_user,
            message_filter=args.filter,
            global_search=args.global_search or args.chat in (None, ''))
        payload = {'chat': row, 'messages': messages}
        if args.json:
            _print_json(payload)
        else:
            _print_messages(row, messages)
        return
    if args.messages_command == 'send':
        return await _cmd_send(args, config)
    if args.messages_command == 'send-file':
        result = await send_media(
            config, args.chat, args.files,
            caption=args.caption,
            force_document=args.force_document,
            reply_to=args.reply_to,
            silent=args.silent,
            schedule=args.schedule,
            voice_note=args.voice_note,
            video_note=args.video_note,
            supports_streaming=args.supports_streaming,
            thumb=args.thumb,
            ttl=args.ttl,
            mime_type=args.mime_type,
            clear_draft=args.clear_draft,
            background=args.background,
            comment_to=args.comment_to,
            send_as=args.send_as,
            message_effect_id=args.message_effect_id,
            buttons_json=args.buttons_json,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        elif result['dry_run']:
            print('DRY-RUN allowed for {} (id={})'.format(
                result['chat']['title'], result['chat']['id']))
        elif result['sent']:
            print('SENT files title={!r} id={} message_ids={}'.format(
                result['chat']['title'], result['chat']['id'],
                ','.join(str(item) for item in result['message_ids'])))
        else:
            print('Cancelled.')
        return
    if args.messages_command == 'edit':
        kwargs = {}
        if args.parse_mode is not None:
            kwargs['parse_mode'] = _parse_parse_mode(args.parse_mode)
        result = await edit_message(
            config, args.chat, args.message_id, args.text,
            link_preview=args.link_preview,
            assume_yes=args.yes,
            dry_run=args.dry_run,
            buttons_json=args.buttons_json,
            schedule=args.schedule,
            **kwargs)
        if args.json:
            _print_json(result)
        else:
            print('EDIT {}'.format('dry-run' if result['dry_run'] else result['message_id']))
        return
    if args.messages_command == 'edit-media':
        kwargs = {}
        if args.parse_mode is not None:
            kwargs['parse_mode'] = _parse_parse_mode(args.parse_mode)
        result = await edit_message_media(
            config, args.chat, args.message_id,
            text=args.text,
            file=args.file,
            thumb=args.thumb,
            force_document=args.force_document,
            supports_streaming=args.supports_streaming,
            link_preview=args.link_preview,
            buttons_json=args.buttons_json,
            assume_yes=args.yes,
            dry_run=args.dry_run,
            **kwargs)
        if args.json:
            _print_json(result)
        else:
            print('EDIT-MEDIA {}'.format(
                'dry-run' if result['dry_run'] else result['message_id']))
        return
    if args.messages_command == 'delete':
        result = await delete_messages(
            config, args.chat, _message_ids_arg(args.message_ids),
            revoke=args.revoke,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('DELETE {}'.format('dry-run' if result['dry_run'] else ','.join(str(item) for item in result['message_ids'])))
        return
    if args.messages_command == 'forward':
        result = await forward_messages(
            config, args.from_chat, args.to_chat,
            _message_ids_arg(args.message_ids),
            silent=args.silent,
            background=args.background,
            with_my_score=args.with_my_score,
            schedule=args.schedule,
            drop_author=args.drop_author,
            drop_media_captions=args.drop_media_captions,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('FORWARD {}'.format('dry-run' if result['dry_run'] else ','.join(str(item) for item in result['forwarded_message_ids'])))
        return
    if args.messages_command == 'copy':
        result = await copy_messages(
            config, args.from_chat, args.to_chat,
            _message_ids_arg(args.message_ids),
            silent=args.silent,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('COPY {}'.format(
                'dry-run' if result['dry_run'] else ','.join(
                    str(item) for item in result['copied_message_ids'])))
        return
    if args.messages_command == 'action':
        result = await message_action(
            config, args.chat, args.action, duration=args.duration,
            delay=args.delay, assume_yes=args.yes, dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('ACTION {}'.format(
                'dry-run' if result['dry_run'] else result['action']))
        return
    if args.messages_command == 'read':
        result = await mark_read(
            config, args.chat, _message_ids_arg(args.message_ids),
            clear_mentions=args.clear_mentions,
            clear_reactions=args.clear_reactions,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('READ {}'.format('dry-run' if result['dry_run'] else 'ok'))
        return
    if args.messages_command == 'pin':
        result = await pin_message_op(
            config, args.chat, args.message_id,
            notify=args.notify,
            pm_oneside=args.pm_oneside,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('PIN {}'.format('dry-run' if result['dry_run'] else result['message_id']))
        return
    if args.messages_command == 'unpin':
        result = await pin_message_op(
            config, args.chat, args.message_id,
            unpin=True,
            notify=args.notify,
            assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(result)
        else:
            print('UNPIN {}'.format('dry-run' if result['dry_run'] else result['message_id']))
        return
    raise AssertionError(args.messages_command)


async def _cmd_drafts(args, config):
    if args.drafts_command == 'list':
        payload = await list_drafts(config, chat=args.chat)
        if args.json:
            _print_json(payload)
        else:
            for item in payload['drafts']:
                chat = item.get('chat') or {}
                print('[{}] {}: {}'.format(
                    chat.get('id') or '-', chat.get('title') or '-',
                    item.get('text') or ''))
        return
    if args.drafts_command == 'set':
        kwargs = {}
        if args.parse_mode is not None:
            kwargs['parse_mode'] = _parse_parse_mode(args.parse_mode)
        payload = await set_draft(
            config, args.chat, args.text,
            link_preview=args.link_preview,
            reply_to=args.reply_to,
            assume_yes=args.yes,
            dry_run=args.dry_run,
            **kwargs)
        if args.json:
            _print_json(payload)
        else:
            print('DRAFT SET {}'.format(
                'dry-run' if payload['dry_run'] else 'ok'))
        return
    if args.drafts_command == 'send':
        payload = await send_draft(
            config, args.chat, assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(payload)
        else:
            print('DRAFT SEND {}'.format(
                'dry-run' if payload['dry_run'] else payload['message_id']))
        return
    if args.drafts_command == 'delete':
        payload = await delete_draft(
            config, args.chat, assume_yes=args.yes,
            dry_run=args.dry_run)
        if args.json:
            _print_json(payload)
        else:
            print('DRAFT DELETE {}'.format(
                'dry-run' if payload['dry_run'] else 'ok'))
        return
    raise AssertionError(args.drafts_command)


async def _cmd_downloads(args, config):
    if args.downloads_command == 'media':
        payload = await download_media(
            config, args.chat, args.message_id,
            output_dir=args.output_dir,
            output_file=args.output_file,
            allow_users=args.allow_users)
    elif args.downloads_command == 'profile-photo':
        payload = await download_profile_photo(
            config, args.query, output_dir=args.output_dir, big=args.big)
    else:
        raise AssertionError(args.downloads_command)
    if args.json:
        _print_json(payload)
    else:
        print('DOWNLOADED {}'.format(payload.get('path') or 'none'))


async def _cmd_admin(args, config):
    if args.admin_command == 'log':
        flags = {
            'join': args.join,
            'leave': args.leave,
            'invite': args.invite,
            'restrict': args.restrict,
            'unrestrict': args.unrestrict,
            'ban': args.ban,
            'unban': args.unban,
            'promote': args.promote,
            'demote': args.demote,
            'info': args.info,
            'settings': args.settings,
            'pinned': args.pinned,
            'edit': args.edit,
            'delete': args.delete,
            'group_call': args.group_call,
        }
        payload = await admin_log(
            config, args.chat, limit=args.limit, admins=args.admins,
            search=args.search, **flags)
        if args.json:
            _print_json(payload)
        else:
            print('Admin log: {} count={}'.format(
                payload['chat']['title'], len(payload['events'])))
        return
    if args.admin_command == 'permissions':
        if args.permissions_command == 'show':
            payload = await show_permissions(
                config, args.chat, user=args.user)
        elif args.permissions_command == 'set':
            payload = await admin_permissions_set(
                config, args.chat, user=args.user,
                until_date=args.until,
                enabled_permissions=args.enable,
                disabled_permissions=args.disable,
                assume_yes=args.yes,
                dry_run=args.dry_run)
        else:
            raise AssertionError(args.permissions_command)
        if args.json:
            _print_json(payload)
        else:
            print('PERMISSIONS {}'.format(
                'dry-run' if payload.get('dry_run') else 'ok'))
        return
    if args.admin_command == 'stats':
        payload = await show_stats(
            config, args.chat, message_id=args.message_id)
        if args.json:
            _print_json(payload)
        else:
            print('STATS {}'.format(payload['stats']['type']))
        return
    if args.admin_command == 'kick':
        payload = await admin_kick(
            config, args.chat, args.user, assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.admin_command == 'ban':
        payload = await admin_permissions_set(
            config, args.chat, user=args.user,
            until_date=args.until,
            disabled_permissions=['view_messages'],
            assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.admin_command == 'unban':
        payload = await admin_permissions_set(
            config, args.chat, user=args.user,
            enabled_permissions=['view_messages'],
            assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.admin_command == 'promote':
        payload = await admin_edit_admin(
            config, args.chat, args.user,
            enabled_rights=args.enable or ['change_info'],
            disabled_rights=args.disable,
            title=args.title,
            is_admin=True,
            assume_yes=args.yes,
            dry_run=args.dry_run)
    elif args.admin_command == 'demote':
        payload = await admin_edit_admin(
            config, args.chat, args.user,
            is_admin=False,
            assume_yes=args.yes,
            dry_run=args.dry_run)
    else:
        raise AssertionError(args.admin_command)
    if args.json:
        _print_json(payload)
    else:
        print('ADMIN {} {}'.format(
            args.admin_command.upper(),
            'dry-run' if payload['dry_run'] else 'ok'))


async def _cmd_bot(args, config):
    if args.bot_command == 'inline-query':
        payload = await bot_inline_query(
            config, args.bot, args.query, chat=args.chat, offset=args.offset)
        if args.json:
            _print_json(payload)
        else:
            for item in payload['results']:
                print('[{index}] {title}'.format(
                    index=item.get('index'),
                    title=item.get('title') or item.get('id') or '-'))
        return
    if args.bot_command == 'inline-send':
        payload = await bot_inline_send(
            config, args.bot, args.query, args.chat,
            index=args.index, reply_to=args.reply_to, offset=args.offset,
            assume_yes=args.yes, dry_run=args.dry_run)
        if args.json:
            _print_json(payload)
        else:
            print('INLINE SEND {}'.format(
                'dry-run' if payload['dry_run'] else ','.join(
                    str(item) for item in payload['message_ids'])))
        return
    raise AssertionError(args.bot_command)


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
        payload = await _quota_reply_payload(
            config, store, state_path, args.task_id, args.text,
            dry_run=args.dry_run)
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

    if args.quota_command == 'step':
        if args.reply and args.skip_reason:
            raise TelegramCliError(
                '--reply and --skip-reason cannot be used together.')
        if args.send and not args.reply:
            raise TelegramCliError('--send requires --reply.')

        step = await _quota_step_next_payload(config, state_path, store)
        task = step.get('task')
        payload = {
            'action': 'next',
            'source': step.get('source'),
            'progress': _quota_progress_payload(step.get('status') or {}),
            'task': task,
            'context': step.get('context'),
            'next_action': 'reply_or_skip' if task is not None else 'wait',
        }

        if task is None:
            if args.reply or args.skip_reason:
                raise TelegramCliError('No active quota task is available.')
            if args.json:
                print(dumps_json(payload))
            else:
                _print_quota_step(payload)
            return

        task_id = task.get('id')
        if not task_id:
            raise TelegramCliError('Quota step task is missing id.')

        if args.skip_reason:
            skip_task = getattr(store, 'skip_task', None)
            if skip_task is None:
                raise TelegramCliError('Quota module does not expose skip_task.')
            skipped = skip_task(
                state_path, task_id, reason=args.skip_reason or 'skipped')
            if skipped is None:
                raise TelegramCliError(
                    'Quota task is not pending or was not found: {}'.format(
                        task_id))
            payload.update({
                'action': 'skip',
                'skipped': True,
                'task': skipped,
                'next_action': 'next',
            })
            payload['progress'] = _quota_progress_payload(_quota_status(config))
        elif args.reply:
            dry_run_payload = await _quota_reply_payload(
                config, store, state_path, task_id, args.reply,
                dry_run=True)
            payload.update({
                'action': 'dry_run',
                'dry_run': dry_run_payload,
                'next_action': 'send_or_adjust',
            })
            if args.send:
                send_payload = await _quota_reply_payload(
                    config, store, state_path, task_id, args.reply,
                    dry_run=False)
                payload.update({
                    'action': 'send',
                    'send': send_payload,
                    'task': send_payload.get('task') or payload.get('task'),
                    'next_action': 'next',
                })
                if hasattr(store, 'status') or hasattr(store, 'get_status'):
                    payload['progress'] = _quota_progress_payload(
                        _quota_status(config))

        if args.json:
            print(dumps_json(payload))
        else:
            _print_quota_step(payload)
        return

    if args.quota_command == 'watch':
        if args.count < 1:
            raise TelegramCliError('--count must be greater than 0.')
        if args.interval < 0:
            raise TelegramCliError('--interval must be 0 or greater.')
        snapshots = []
        for index in range(args.count):
            state = _quota_status(config)
            snapshot = {
                'index': index + 1,
                'progress': _quota_progress_payload(state),
            }
            snapshots.append(snapshot)
            if not args.json:
                _print_quota_watch_snapshot(snapshot)
            if index + 1 < args.count and args.interval > 0:
                time.sleep(args.interval)
        payload = {'snapshots': snapshots}
        if args.json:
            print(dumps_json(payload))
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
    telegram_commands = {
        'auth', 'me', 'groups', 'dialogs', 'dialog', 'entity',
        'members', 'profile', 'history', 'send', 'messages', 'drafts',
        'downloads', 'admin', 'bot', 'game',
    }
    require_credentials = (
        args.command in telegram_commands
        or (args.command == 'daemon' and args.daemon_command == 'run')
        or (
            args.command == 'quota'
            and args.quota_command == 'reply'
            and not args.dry_run)
        or (
            args.command == 'quota'
            and args.quota_command == 'step'))

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

        if args.command == 'auth':
            _run(_cmd_auth(args, config))
        elif args.command == 'me':
            _run(_cmd_me(args, config))
        elif args.command == 'groups':
            _run(_cmd_groups(args, config, groups_only=True))
        elif args.command == 'dialogs':
            _run(_cmd_groups(args, config, groups_only=False))
        elif args.command == 'dialog':
            _run(_cmd_dialog(args, config))
        elif args.command == 'entity':
            _run(_cmd_entity(args, config))
        elif args.command == 'members':
            _run(_cmd_members(args, config))
        elif args.command == 'profile':
            _run(_cmd_profile(args, config))
        elif args.command == 'history':
            _run(_cmd_history(args, config))
        elif args.command == 'send':
            _run(_cmd_send(args, config))
        elif args.command == 'messages':
            _run(_cmd_messages(args, config))
        elif args.command == 'drafts':
            _run(_cmd_drafts(args, config))
        elif args.command == 'downloads':
            _run(_cmd_downloads(args, config))
        elif args.command == 'admin':
            _run(_cmd_admin(args, config))
        elif args.command == 'bot':
            _run(_cmd_bot(args, config))
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
