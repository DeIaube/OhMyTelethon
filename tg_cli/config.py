import json
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


class AppConfig:
    def __init__(
            self, api_id=None, api_hash=None, session_path=None,
            allowed_chats=None, state_path=None, audit_log_path=None,
            profile=None, config_path=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = Path(session_path).expanduser().resolve()
        self.allowed_chats = tuple(int(x) for x in (allowed_chats or ()))
        self.state_path = Path(state_path).expanduser().resolve()
        self.audit_log_path = Path(audit_log_path).expanduser().resolve()
        self.profile = profile or {}
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None

    def require_credentials(self):
        if not self.api_id:
            raise ConfigError('Missing api_id. Set TG_API_ID or add api_id to config.')
        if not self.api_hash:
            raise ConfigError('Missing api_hash. Set TG_API_HASH or add api_hash to config.')


def default_config_paths(cwd=None):
    base = Path(cwd or os.getcwd())
    return (
        base / 'tg_cli' / '.tg-cli.json',
        base / '.tg-cli.json',
        Path.home() / '.config' / 'tg-cli' / 'config.json',
    )


def parse_chat_ids(value):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        parts = [x.strip() for x in value.split(',')]
    else:
        parts = list(value)

    result = []
    for item in parts:
        if item in (None, ''):
            continue
        result.append(int(normalize_chat_id(item)))
    return result


def normalize_chat_id(value):
    text = str(value).strip()
    if text.startswith('-100') and text[4:].isdigit():
        return int(text[4:])
    if text.startswith('-') and text[1:].isdigit():
        return abs(int(text))
    return int(text)


def _read_json(path):
    if not path or not Path(path).is_file():
        return {}
    with Path(path).open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ConfigError('Config file must contain a JSON object.')
    return data


def _find_config_path(explicit_path=None, cwd=None):
    if explicit_path:
        return Path(explicit_path).expanduser()
    for path in default_config_paths(cwd):
        if path.is_file():
            return path
    return None


def load_config(path=None, env=None, cwd=None, require_credentials=False):
    env = env if env is not None else os.environ
    base = Path(cwd or os.getcwd()).resolve()
    config_path = _find_config_path(path, base)
    data = _read_json(config_path)

    api_id = env.get('TG_API_ID') or data.get('api_id')
    if api_id not in (None, ''):
        api_id = int(api_id)

    session_path = (
        env.get('TG_CLI_SESSION')
        or env.get('TG_SESSION_PATH')
        or data.get('session_path')
        or str(base / 'printer.session')
    )

    allowed_chats = parse_chat_ids(
        env.get('TG_CLI_ALLOWED_CHATS')
        if env.get('TG_CLI_ALLOWED_CHATS') is not None
        else data.get('allowed_chats', [])
    )

    state_path = (
        env.get('TG_CLI_STATE')
        or data.get('state_path')
        or str(base / 'tg_cli' / '.tg-cli-state.json')
    )
    audit_log_path = (
        env.get('TG_CLI_AUDIT_LOG')
        or data.get('audit_log_path')
        or str(base / 'tg_cli' / 'tg-cli.audit.log')
    )

    cfg = AppConfig(
        api_id=api_id,
        api_hash=env.get('TG_API_HASH') or data.get('api_hash'),
        session_path=session_path,
        allowed_chats=allowed_chats,
        state_path=state_path,
        audit_log_path=audit_log_path,
        profile=data.get('profile') or {},
        config_path=config_path,
    )
    if require_credentials:
        cfg.require_credentials()
    return cfg
