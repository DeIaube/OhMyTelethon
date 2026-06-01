import json
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


DEFAULT_PROFILE = {
    'style': '自然、简短、像普通群聊，不要长篇解释。',
    'language': '中文',
    'max_chars': 80,
    'emoji_level': 'low',
    'avoid_topics': [],
    'forbidden_terms': [],
    'reply_policy': '只在有明确可接话的内容时回复；不确定时跳过；不要编造事实或冒充他人。',
}


DEFAULT_ROUND = {
    'duration': 60.0,
    'limit': 12,
    'max_replies': 8,
    'quiet_context': False,
    'min_reply_interval': 2.0,
    'end_buffer': 5.0,
    'reply_probability': 1.0,
    'mention_reply_probability': None,
    'random_delay_min': 0.0,
    'random_delay_max': 0.0,
    'skip_short_ack': False,
    'merge_window': 0.0,
    'split_long_replies': False,
    'split_max_chars': 28,
    'split_delay_min': 1.0,
    'split_delay_max': 2.5,
    'split_max_parts': 3,
}


def _string_list(value, field_name):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        values = [value]
    else:
        try:
            values = list(value)
        except TypeError as exc:
            raise ConfigError('profile.{} must be a string or list of strings.'.format(
                field_name)) from exc

    result = []
    for item in values:
        if item in (None, ''):
            continue
        result.append(str(item).strip())
    return [item for item in result if item]


def normalize_profile(profile=None):
    if profile in (None, ''):
        profile = {}
    if not isinstance(profile, dict):
        raise ConfigError('profile must contain a JSON object.')

    normalized = dict(DEFAULT_PROFILE)
    normalized.update(profile)
    normalized['max_chars'] = int(normalized['max_chars'])
    if normalized['max_chars'] < 1:
        raise ConfigError('profile.max_chars must be greater than 0.')

    normalized['avoid_topics'] = _string_list(
        normalized.get('avoid_topics'), 'avoid_topics')
    normalized['forbidden_terms'] = _string_list(
        normalized.get('forbidden_terms'), 'forbidden_terms')
    return normalized


def _float_field(data, name, minimum=None, allow_none=False):
    value = data.get(name)
    if value is None and allow_none:
        return None
    value = float(value)
    if minimum is not None and value < minimum:
        raise ConfigError('round.{} must be greater than or equal to {}.'.format(
            name, minimum))
    return value


def _int_field(data, name, minimum=None):
    value = int(data.get(name))
    if minimum is not None and value < minimum:
        raise ConfigError('round.{} must be greater than or equal to {}.'.format(
            name, minimum))
    return value


def _probability_field(data, name, allow_none=False):
    value = _float_field(data, name, minimum=0.0, allow_none=allow_none)
    if value is not None and value > 1.0:
        raise ConfigError('round.{} must be between 0 and 1.'.format(name))
    return value


def normalize_round(round_config=None):
    if round_config in (None, ''):
        round_config = {}
    if not isinstance(round_config, dict):
        raise ConfigError('round must contain a JSON object.')

    normalized = dict(DEFAULT_ROUND)
    normalized.update(round_config)
    normalized['duration'] = _float_field(normalized, 'duration', minimum=0.0)
    normalized['limit'] = _int_field(normalized, 'limit', minimum=1)
    normalized['max_replies'] = _int_field(normalized, 'max_replies', minimum=1)
    normalized['quiet_context'] = bool(normalized.get('quiet_context'))
    normalized['min_reply_interval'] = _float_field(
        normalized, 'min_reply_interval', minimum=0.0)
    normalized['end_buffer'] = _float_field(normalized, 'end_buffer', minimum=0.0)
    normalized['reply_probability'] = _probability_field(
        normalized, 'reply_probability')
    normalized['mention_reply_probability'] = _probability_field(
        normalized, 'mention_reply_probability', allow_none=True)
    normalized['random_delay_min'] = _float_field(
        normalized, 'random_delay_min', minimum=0.0)
    normalized['random_delay_max'] = _float_field(
        normalized, 'random_delay_max', minimum=0.0)
    if normalized['random_delay_max'] < normalized['random_delay_min']:
        raise ConfigError('round.random_delay_max must be greater than or equal to random_delay_min.')
    normalized['skip_short_ack'] = bool(normalized.get('skip_short_ack'))
    normalized['merge_window'] = _float_field(normalized, 'merge_window', minimum=0.0)
    normalized['split_long_replies'] = bool(normalized.get('split_long_replies'))
    normalized['split_max_chars'] = _int_field(
        normalized, 'split_max_chars', minimum=1)
    normalized['split_delay_min'] = _float_field(
        normalized, 'split_delay_min', minimum=0.0)
    normalized['split_delay_max'] = _float_field(
        normalized, 'split_delay_max', minimum=0.0)
    if normalized['split_delay_max'] < normalized['split_delay_min']:
        raise ConfigError('round.split_delay_max must be greater than or equal to split_delay_min.')
    normalized['split_max_parts'] = _int_field(
        normalized, 'split_max_parts', minimum=1)
    return normalized


class AppConfig:
    def __init__(
            self, api_id=None, api_hash=None, session_path=None,
            allowed_chats=None, state_path=None, audit_log_path=None,
            profile=None, round_config=None, config_path=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = Path(session_path).expanduser().resolve()
        self.allowed_chats = tuple(int(x) for x in (allowed_chats or ()))
        self.state_path = Path(state_path).expanduser().resolve()
        self.audit_log_path = Path(audit_log_path).expanduser().resolve()
        self.profile = normalize_profile(profile)
        self.round = normalize_round(round_config)
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
        profile=data.get('profile'),
        round_config=data.get('round'),
        config_path=config_path,
    )
    if require_credentials:
        cfg.require_credentials()
    return cfg
