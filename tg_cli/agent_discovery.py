import argparse
import json
from pathlib import Path

from . import daemon as daemon_store
from . import safety


RISK_LEVELS = {
    'local': 'Local-only inspection or local runtime-state changes.',
    'read': 'Reads Telegram or local runtime data without mutating Telegram.',
    'write': 'Can mutate Telegram or queued Telegram writes behind safety gates.',
    'admin': 'Can change chat moderation/admin state behind safety gates.',
    'auth': 'Can create, inspect, or destroy local Telegram authorization state.',
}


JSON_ERROR_SCHEMA = {
    'ok': False,
    'error': {
        'code': 'machine_readable_error_code',
        'message': 'human readable message',
        'type': 'ExceptionClassName',
        'hint': 'optional next action',
    },
}


GUIDES = {
    ('capabilities',): {
        'category': 'agent_discovery',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Does not read Telegram, local sessions, or runtime state.',
            'Use this as the first command when an agent needs to learn the CLI surface.',
        ],
        'examples': ['tg-cli capabilities --json'],
    },
    ('doctor',): {
        'category': 'agent_discovery',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Does not connect to Telegram.',
            'Reports local readiness, runtime paths, queue state, and docs pointers.',
        ],
        'examples': ['tg-cli doctor agent --json'],
    },
    ('config',): {
        'category': 'configuration',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Use config doctor when coordinating multiple accounts to avoid shared session or queue paths.',
        ],
        'examples': [
            'tg-cli config inspect --json',
            'tg-cli --config account-a.json config doctor --other-config account-b.json --json',
        ],
    },
    ('auth',): {
        'category': 'authorization',
        'risk': 'auth',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Never log or print API hashes, phone numbers, login codes, passwords, bot tokens, or session bytes.',
        ],
        'examples': [
            'tg-cli auth status --json',
            'tg-cli auth login --phone "+1234567890"',
        ],
    },
    ('me',): {
        'category': 'account',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli me --json'],
    },
    ('groups',): {
        'category': 'discovery',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli groups --query 游戏 --kind supergroup --json'],
    },
    ('dialogs',): {
        'category': 'discovery',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli dialogs --limit 50 --archived --json'],
    },
    ('dialog',): {
        'category': 'dialog_management',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'Live mutations require whitelist, pause, confirmation, and audit checks.',
        ],
        'examples': ['tg-cli dialog archive 5217114569 --dry-run --json'],
    },
    ('entity',): {
        'category': 'discovery',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Entity JSON must stay sanitized and must not expose access hashes.',
        ],
        'examples': ['tg-cli entity resolve @some_group --json'],
    },
    ('members',): {
        'category': 'people',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Member rows must remain public/sanitized: no phone numbers, access hashes, or raw TL objects.',
        ],
        'examples': [
            'tg-cli members search 5217114569 薇薇 --json',
            'tg-cli members list 5217114569 --filter admins --limit 50 --json',
        ],
    },
    ('profile',): {
        'category': 'people',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Profile output may include public profile fields, but never phone numbers, access hashes, session data, or image bytes.',
        ],
        'examples': [
            'tg-cli profile show 薇薇 --chat 5217114569 --json',
            'tg-cli profile photos 薇薇 --limit 5 --json',
        ],
    },
    ('history',): {
        'category': 'messages',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli history 5217114569 --limit 50 --json'],
    },
    ('send',): {
        'category': 'messages',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'Always dry-run first for new chats or changed profile rules.',
            'Live sends require whitelist, pause check, forbidden-term check, confirmation unless --yes, and audit logging.',
        ],
        'examples': ['tg-cli send 5217114569 "测试消息" --dry-run --yes --json'],
    },
    ('messages',): {
        'category': 'messages',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'Read subcommands are safe inspection; write subcommands must keep dry-run/confirmation/audit gates.',
            'Message management requires explicit message ids; no range deletion or unpin-all.',
        ],
        'examples': [
            'tg-cli messages history 5217114569 --limit 50 --json',
            'tg-cli messages send 5217114569 "回复一下" --dry-run --json',
        ],
    },
    ('drafts',): {
        'category': 'messages',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'examples': [
            'tg-cli drafts list --json',
            'tg-cli drafts set 5217114569 "稍后发" --dry-run --json',
        ],
    },
    ('downloads',): {
        'category': 'downloads',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Writes downloaded bytes only to local files; JSON returns paths and shallow metadata only.',
        ],
        'examples': ['tg-cli downloads media 5217114569 123 --output-dir tg_cli/downloads --json'],
    },
    ('admin',): {
        'category': 'moderation',
        'risk': 'admin',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'Admin write commands require explicit target users and safety gates.',
        ],
        'examples': [
            'tg-cli admin log 5217114569 --limit 20 --json',
            'tg-cli admin ban 5217114569 薇薇 --dry-run --json',
        ],
    },
    ('bot',): {
        'category': 'bots',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'examples': [
            'tg-cli bot inline-query @like "Do you like Telethon?" --chat 5217114569 --json',
            'tg-cli bot inline-send @like "Do you like Telethon?" 5217114569 --index 0 --dry-run --json',
        ],
    },
    ('pause',): {
        'category': 'safety',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli pause'],
    },
    ('resume',): {
        'category': 'safety',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli resume'],
    },
    ('status',): {
        'category': 'safety',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'examples': ['tg-cli status --json'],
    },
    ('game',): {
        'category': 'agent_runtime',
        'risk': 'write',
        'credential_mode': 'required',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'game context and suggest do not call a model provider.',
            'game round owns live Telegram IO and remains bounded by duration, max replies, pause, whitelist, pacing, and audit.',
        ],
        'examples': [
            'tg-cli game context 5217114569 --preset chat_social --operator codex --json',
            'tg-cli game round 5217114569 --duration 300 --preset chat_social',
        ],
    },
    ('daemon',): {
        'category': 'agent_runtime',
        'risk': 'write',
        'credential_mode': 'conditional',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'daemon run owns Telegram IO for one foreground chat.',
            'daemon next/reply/skip/status operate on the local queue and should be safe while daemon run owns the session.',
        ],
        'examples': [
            'tg-cli daemon run 5217114569 --preset chat_social --duration 3600 --dry-run',
            'tg-cli daemon next --json',
            'tg-cli daemon reply <task_id> "这把先看看" --dry-run --json',
        ],
    },
    ('quota',): {
        'category': 'agent_runtime',
        'risk': 'write',
        'credential_mode': 'conditional',
        'allowed_chat_mode': 'required_for_live_write',
        'safety_notes': [
            'quota step never generates text and defaults to dry-run when --reply is supplied.',
            'Use quota skip instead of filler replies when context is unsuitable.',
        ],
        'examples': [
            'tg-cli quota status --json',
            'tg-cli quota step --json',
            'tg-cli quota step --reply "西瓜现在甜不甜呀" --json',
            'tg-cli quota step --reply "西瓜现在甜不甜呀" --send --json',
        ],
    },
    ('scenario',): {
        'category': 'agent_runtime',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'required_when_started',
        'examples': ['tg-cli scenario start authorized-chat-social-150 --json'],
    },
    ('memory',): {
        'category': 'agent_runtime',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Memory stores operator-authored summaries only, not raw Telegram text.',
        ],
        'examples': ['tg-cli memory list 5217114569 --json'],
    },
    ('badcase',): {
        'category': 'agent_runtime',
        'risk': 'local',
        'credential_mode': 'not_required',
        'allowed_chat_mode': 'not_required',
        'safety_notes': [
            'Bad cases store hashes, lengths, reason labels, and lessons, not raw Telegram text.',
        ],
        'examples': ['tg-cli badcase list --chat 5217114569 --json'],
    },
}


READ_ONLY_MESSAGE_SUBCOMMANDS = {
    ('messages', 'history'),
    ('messages', 'get'),
    ('messages', 'replies'),
    ('messages', 'scheduled'),
    ('messages', 'search'),
}


ADMIN_READ_ONLY_SUBCOMMANDS = {
    ('admin', 'log'),
    ('admin', 'permissions', 'show'),
    ('admin', 'stats'),
}


LOCAL_DAEMON_SUBCOMMANDS = {
    ('daemon', 'next'),
    ('daemon', 'reply'),
    ('daemon', 'skip'),
    ('daemon', 'status'),
    ('daemon', 'stop'),
}


LOCAL_QUOTA_SUBCOMMANDS = {
    ('quota', 'start'),
    ('quota', 'status'),
    ('quota', 'stop'),
    ('quota', 'next'),
    ('quota', 'skip'),
    ('quota', 'watch'),
}


def _subparser_action(parser):
    for action in getattr(parser, '_actions', []):
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _action_default(value):
    if value is argparse.SUPPRESS:
        return None
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _action_payload(action):
    payload = {
        'dest': action.dest,
        'required': bool(getattr(action, 'required', False)),
    }
    if getattr(action, 'nargs', None) is not None:
        payload['nargs'] = action.nargs
    if getattr(action, 'choices', None) is not None:
        payload['choices'] = list(action.choices)
    default = _action_default(getattr(action, 'default', None))
    if default is not None:
        payload['default'] = default
    if getattr(action, 'help', None):
        payload['help'] = action.help
    if action.option_strings:
        payload['flags'] = list(action.option_strings)
    else:
        payload['name'] = action.dest
    return payload


def _guide_for_path(path):
    path_tuple = tuple(path)
    for length in range(len(path_tuple), 0, -1):
        guide = GUIDES.get(path_tuple[:length])
        if guide:
            return guide
    return {
        'category': 'uncategorized',
        'risk': 'read',
        'credential_mode': 'required',
        'allowed_chat_mode': 'not_required',
        'examples': [],
        'safety_notes': [],
    }


def _path_risk(path, guide):
    path_tuple = tuple(path)
    if path_tuple in READ_ONLY_MESSAGE_SUBCOMMANDS:
        return 'read'
    if path_tuple in ADMIN_READ_ONLY_SUBCOMMANDS:
        return 'read'
    if path_tuple in LOCAL_DAEMON_SUBCOMMANDS:
        return 'local'
    if path_tuple in LOCAL_QUOTA_SUBCOMMANDS:
        return 'local'
    if path_tuple == ('drafts', 'list'):
        return 'read'
    if path_tuple == ('bot', 'inline-query'):
        return 'read'
    return guide.get('risk') or 'read'


def _credential_mode(path, guide):
    path_tuple = tuple(path)
    if path_tuple in LOCAL_DAEMON_SUBCOMMANDS:
        return 'not_required'
    if path_tuple in LOCAL_QUOTA_SUBCOMMANDS:
        return 'not_required'
    if path_tuple == ('quota', 'reply'):
        return 'conditional'
    return guide.get('credential_mode') or 'required'


def _walk_parser(parser, path=None, help_text=''):
    path = list(path or [])
    subparsers = _subparser_action(parser)
    if subparsers is not None:
        help_by_choice = {
            action.dest: action.help
            for action in getattr(subparsers, '_choices_actions', [])
        }
        for name in sorted(subparsers.choices):
            yield from _walk_parser(
                subparsers.choices[name],
                path + [name],
                help_by_choice.get(name) or '')
        return

    options = []
    positionals = []
    for action in getattr(parser, '_actions', []):
        if action.dest == 'help':
            continue
        if isinstance(action, argparse._SubParsersAction):
            continue
        payload = _action_payload(action)
        if action.option_strings:
            options.append(payload)
        else:
            positionals.append(payload)

    guide = _guide_for_path(path)
    risk = _path_risk(path, guide)
    command = 'tg-cli {}'.format(' '.join(path)).strip()
    supports_json = any(
        '--json' in item.get('flags', []) for item in options)
    supports_dry_run = any(
        '--dry-run' in item.get('flags', []) for item in options)
    supports_yes = any(
        '--yes' in item.get('flags', []) for item in options)

    yield {
        'command': command,
        'path': path,
        'summary': help_text or '',
        'category': guide.get('category') or 'uncategorized',
        'risk': risk,
        'credential_mode': _credential_mode(path, guide),
        'allowed_chat_mode': guide.get('allowed_chat_mode') or 'not_required',
        'supports_json': supports_json,
        'supports_dry_run': supports_dry_run,
        'supports_confirmation_bypass': supports_yes,
        'positionals': positionals,
        'options': options,
        'examples': list(guide.get('examples') or []),
        'safety_notes': list(guide.get('safety_notes') or []),
    }


def build_capabilities_payload(parser):
    commands = list(_walk_parser(parser))
    commands.sort(key=lambda item: item['command'])
    return {
        'schema_version': 1,
        'generated_from': 'argparse',
        'command_count': len(commands),
        'risk_levels': RISK_LEVELS,
        'json_error_schema': JSON_ERROR_SCHEMA,
        'agent_entrypoints': {
            'discover': 'tg-cli capabilities --json',
            'preflight': 'tg-cli doctor agent --json',
            'local_status': 'tg-cli status --json',
            'safe_send_pattern': [
                'Use a read/context command first.',
                'Dry-run the operator-authored text.',
                'Send live only with an explicit live-send flag or confirmation.',
            ],
        },
        'documentation': [
            'tg_cli/AGENTS.md',
            'tg_cli/README.md',
            'tg_cli/docs/agent-recipes.md',
        ],
        'commands': commands,
    }


def format_capabilities_text(payload):
    lines = [
        'tg-cli capabilities: {} commands'.format(payload.get('command_count') or 0),
        'Use `tg-cli capabilities --json` for machine-readable details.',
    ]
    for command in payload.get('commands') or []:
        lines.append('{command} [{risk}] {summary}'.format(
            command=command.get('command'),
            risk=command.get('risk'),
            summary=command.get('summary') or '',
        ).rstrip())
    return '\n'.join(lines)


def _safe_json_file(path):
    target = Path(path).expanduser()
    if not target.is_file():
        return {}
    with target.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _path_info(path):
    target = Path(path).expanduser()
    return {
        'path': str(target),
        'exists': target.exists(),
        'is_file': target.is_file(),
        'is_dir': target.is_dir(),
    }


def _queue_summary(path):
    target = Path(path).expanduser()
    if not target.is_file():
        return {'path': str(target), 'exists': False, 'counts': {}}
    return {
        'path': str(target),
        'exists': True,
        'counts': daemon_store.queue_counts(target),
    }


def _daemon_summary(config):
    daemon_config = getattr(config, 'daemon', {}) or {}
    lock_path = daemon_config.get('lock_path')
    status_path = daemon_config.get('status_path')
    queue_path = daemon_config.get('queue_path')
    lock_payload = _safe_json_file(lock_path) if lock_path else {}
    status_payload = daemon_store.read_status(status_path) if status_path else {}
    return {
        'queue': _queue_summary(queue_path) if queue_path else {},
        'lock': {
            **(_path_info(lock_path) if lock_path else {}),
            'payload': lock_payload,
        },
        'status': {
            **(_path_info(status_path) if status_path else {}),
            'payload': status_payload,
        },
        'limits': {
            'min_reply_interval': daemon_config.get('min_reply_interval'),
            'max_messages_per_hour': daemon_config.get('max_messages_per_hour'),
            'max_pending': daemon_config.get('max_pending'),
        },
    }


def _quota_summary(config):
    quota_config = getattr(config, 'quota', {}) or {}
    state_path = quota_config.get('state_path')
    if not state_path:
        return {}
    state_file = Path(state_path).expanduser()
    if not state_file.is_file():
        return {
            'state_path': str(state_file),
            'exists': False,
            'status': 'empty',
            'targets': [],
            'tasks': [],
        }
    payload = _safe_json_file(state_file)
    return {
        'state_path': str(state_file),
        'exists': True,
        'status': payload.get('status') or 'unknown',
        'run_id': payload.get('run_id'),
        'targets': payload.get('targets') or [],
        'task_count': len(payload.get('tasks') or []),
    }


def _doc_info(root):
    docs = [
        root / 'tg_cli' / 'AGENTS.md',
        root / 'tg_cli' / 'README.md',
        root / 'tg_cli' / 'docs' / 'agent-recipes.md',
    ]
    return [_path_info(path) for path in docs]


def build_agent_doctor_payload(config, root=None):
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    state = safety.load_state(config)
    allowed_chats = list(getattr(config, 'allowed_chats', ()) or ())
    session_exists = Path(config.session_path).is_file()
    credentials_present = bool(getattr(config, 'api_id', None)) and bool(
        getattr(config, 'api_hash', None))
    paused = bool(state.get('paused'))
    findings = []

    if not credentials_present:
        findings.append({
            'severity': 'warning',
            'code': 'missing_credentials',
            'message': 'TG_API_ID/TG_API_HASH or config credentials are not present.',
            'next_action': 'Set credentials before commands that connect to Telegram.',
        })
    if not session_exists:
        findings.append({
            'severity': 'warning',
            'code': 'missing_session',
            'message': 'The configured Telethon session file does not exist.',
            'next_action': 'Run `tg-cli auth status --json` or complete login before Telegram IO.',
        })
    if not allowed_chats:
        findings.append({
            'severity': 'warning',
            'code': 'no_allowed_chats',
            'message': 'No allowed_chats are configured, so live writes will be blocked.',
            'next_action': 'Set TG_CLI_ALLOWED_CHATS or config allowed_chats for authorized test chats.',
        })
    if paused:
        findings.append({
            'severity': 'warning',
            'code': 'paused',
            'message': 'tg-cli is paused and will block live writes.',
            'next_action': 'Run `tg-cli resume` only when live writes should be allowed.',
        })

    readiness = {
        'local_inspection': True,
        'telegram_io': credentials_present and session_exists,
        'live_writes': (
            credentials_present and session_exists and bool(allowed_chats)
            and not paused),
    }

    return {
        'schema_version': 1,
        'ok': not any(item.get('severity') == 'error' for item in findings),
        'account_name': getattr(config, 'account_name', '') or '',
        'readiness': readiness,
        'findings': findings,
        'state': {
            'paused': paused,
            'path': str(config.state_path),
            'exists': Path(config.state_path).is_file(),
        },
        'allowed_chats': allowed_chats,
        'runtime_paths': {
            'config_path': str(config.config_path) if getattr(config, 'config_path', None) else '',
            'session_path': str(config.session_path),
            'state_path': str(config.state_path),
            'audit_log_path': str(config.audit_log_path),
            'daemon_queue_path': str((getattr(config, 'daemon', {}) or {}).get('queue_path') or ''),
            'daemon_lock_path': str((getattr(config, 'daemon', {}) or {}).get('lock_path') or ''),
            'daemon_status_path': str((getattr(config, 'daemon', {}) or {}).get('status_path') or ''),
            'quota_state_path': str((getattr(config, 'quota', {}) or {}).get('state_path') or ''),
            'memory_path': str((getattr(config, 'memory', {}) or {}).get('path') or ''),
            'bad_cases_path': str((getattr(config, 'bad_cases', {}) or {}).get('path') or ''),
        },
        'session': _path_info(config.session_path),
        'daemon': _daemon_summary(config),
        'quota': _quota_summary(config),
        'docs': _doc_info(root_path),
        'recommended_first_commands': [
            'tg-cli capabilities --json',
            'tg-cli doctor agent --json',
            'tg-cli status --json',
            'tg-cli quota step --json',
        ],
    }


def format_agent_doctor_text(payload):
    readiness = payload.get('readiness') or {}
    lines = [
        'agent doctor ok={}'.format(str(bool(payload.get('ok'))).lower()),
        'telegram_io={}'.format(str(bool(readiness.get('telegram_io'))).lower()),
        'live_writes={}'.format(str(bool(readiness.get('live_writes'))).lower()),
        'paused={}'.format(str(bool((payload.get('state') or {}).get('paused'))).lower()),
        'allowed_chats={}'.format(
            ','.join(str(x) for x in payload.get('allowed_chats') or []) or 'none'),
    ]
    for finding in payload.get('findings') or []:
        lines.append('[{severity}] {code}: {message}'.format(**finding))
        if finding.get('next_action'):
            lines.append('next_action={}'.format(finding['next_action']))
    return '\n'.join(lines)
