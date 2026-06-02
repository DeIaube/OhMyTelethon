import json
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


from .agent_character import (
    merge_character, normalize_character, normalize_character_overlay,
)


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
    'min_reply_chars': 7,
    'split_long_replies': False,
    'split_max_chars': 28,
    'split_delay_min': 1.0,
    'split_delay_max': 2.5,
    'split_max_parts': 3,
}


DEFAULT_DAEMON = {
    'queue_path': None,
    'lock_path': None,
    'status_path': None,
    'poll_interval': 1.0,
    'task_ttl': 900.0,
    'claim_ttl': 300.0,
    'max_pending': 20,
    'max_task_context': 8,
    'min_reply_interval': 6.0,
    'max_messages_per_hour': 20,
    'stale_lock_after': 3600.0,
}


DEFAULT_QUOTA = {
    'state_path': None,
}


DEFAULT_MEMORY = {
    'path': None,
    'enabled': False,
    'max_task_memories': 8,
}


DEFAULT_BAD_CASES = {
    'enabled': True,
    'path': None,
    'max_records': 1000,
    'max_task_bad_cases': 3,
    'recent_days': 14,
}


DEFAULT_REPLY_POLICY = {
    'group_type': 'group',
    'reply_threshold': 0.6,
    'prefer_reply_when': [
        'direct question',
        'mentioned by name',
        'clear conversational opening',
    ],
    'skip_when': [
        'no clear contribution',
        'sensitive topic',
        'heated argument',
    ],
    'style_rules': [
        'keep replies short',
        'sound like a regular group chat participant',
    ],
    'conversation_rules': [
        'do not fabricate facts',
        'do not impersonate other people',
    ],
}


DEFAULT_INITIATIVE = {
    'enabled': False,
    'group_type': 'group',
    'style': 'low_key',
    'idle_after': 300.0,
    'cooldown': 600.0,
    'max_starts': 1,
    'min_starts': 0,
    'min_start_after': 60.0,
    'avoid_when_active': True,
    'active_threshold': 3,
    'recent_window': 300.0,
    'self_context_guard': True,
    'self_context_recent': 6,
    'self_context_max_trailing_own': 2,
    'topic_sources': ['recent_messages'],
    'topics': [],
    'allow_topic_shift': False,
    'topic_shift_when': [],
    'topic_shift_style': '',
    'fallback_topics': [],
    'allowed_intents': ['light_chat', 'ask_open_question'],
    'forbidden_topics': [],
}


DEFAULT_PERSONA = {
    'identity': '',
    'traits': [],
    'catchphrases': [],
    'avoid': [],
    'style_notes': [],
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
    normalized['min_reply_chars'] = _int_field(
        normalized, 'min_reply_chars', minimum=0)
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


def normalize_daemon(daemon_config=None):
    if daemon_config in (None, ''):
        daemon_config = {}
    if not isinstance(daemon_config, dict):
        raise ConfigError('daemon must contain a JSON object.')

    normalized = dict(DEFAULT_DAEMON)
    normalized.update(daemon_config)
    normalized.pop('max_consecutive_replies', None)
    for field_name in ('queue_path', 'lock_path', 'status_path'):
        value = normalized.get(field_name)
        if value in (None, ''):
            normalized[field_name] = None
        elif isinstance(value, Path):
            normalized[field_name] = str(value)
        elif not isinstance(value, str):
            raise ConfigError('daemon.{} must be a string.'.format(field_name))
    for field_name in (
            'poll_interval', 'task_ttl', 'claim_ttl', 'min_reply_interval',
            'stale_lock_after'):
        value = float(normalized.get(field_name))
        if value < 0.0:
            raise ConfigError(
                'daemon.{} must be greater than or equal to 0.'.format(
                    field_name))
        normalized[field_name] = value
    for field_name in (
            'max_pending', 'max_task_context',
            'max_messages_per_hour'):
        value = int(normalized.get(field_name))
        if value < 1:
            raise ConfigError(
                'daemon.{} must be greater than or equal to 1.'.format(
                    field_name))
        normalized[field_name] = value
    return normalized


def normalize_quota(quota_config=None):
    if quota_config in (None, ''):
        quota_config = {}
    if not isinstance(quota_config, dict):
        raise ConfigError('quota must contain a JSON object.')

    normalized = dict(DEFAULT_QUOTA)
    normalized.update(quota_config)
    value = normalized.get('state_path')
    if value in (None, ''):
        normalized['state_path'] = None
    elif isinstance(value, Path):
        normalized['state_path'] = str(value)
    elif not isinstance(value, str):
        raise ConfigError('quota.state_path must be a string.')
    return normalized


def normalize_memory(memory_config=None):
    if memory_config in (None, ''):
        memory_config = {}
    if not isinstance(memory_config, dict):
        raise ConfigError('memory must contain a JSON object.')

    normalized = dict(DEFAULT_MEMORY)
    normalized.update(memory_config)
    normalized['enabled'] = bool(normalized.get('enabled'))
    value = normalized.get('path')
    if value in (None, ''):
        normalized['path'] = None
    elif isinstance(value, Path):
        normalized['path'] = str(value)
    elif not isinstance(value, str):
        raise ConfigError('memory.path must be a string.')
    max_task_memories = int(normalized.get('max_task_memories'))
    if max_task_memories < 0:
        raise ConfigError(
            'memory.max_task_memories must be greater than or equal to 0.')
    normalized['max_task_memories'] = max_task_memories
    return normalized


def normalize_bad_cases(bad_cases_config=None):
    bad_cases_config = _object_config(bad_cases_config, 'bad_cases')
    normalized = dict(DEFAULT_BAD_CASES)
    normalized.update(bad_cases_config)
    normalized['enabled'] = bool(normalized.get('enabled'))
    value = normalized.get('path')
    if value in (None, ''):
        normalized['path'] = None
    elif isinstance(value, Path):
        normalized['path'] = str(value)
    elif not isinstance(value, str):
        raise ConfigError('bad_cases.path must be a string.')
    for field_name in ('max_records', 'max_task_bad_cases'):
        value = int(normalized.get(field_name))
        if value < 0:
            raise ConfigError(
                'bad_cases.{} must be greater than or equal to 0.'.format(
                    field_name))
        normalized[field_name] = value
    recent_days = int(normalized.get('recent_days'))
    if recent_days < 0:
        raise ConfigError(
            'bad_cases.recent_days must be greater than or equal to 0.')
    normalized['recent_days'] = recent_days
    return normalized


def _normalize_daemon_overlay(daemon_config, preset_name):
    normalized = dict(daemon_config)
    normalized.pop('max_consecutive_replies', None)
    for field_name in ('queue_path', 'lock_path', 'status_path'):
        if field_name in normalized:
            raise ConfigError(
                'presets.{}.daemon.{} is not supported; configure daemon.{} at the top level.'.format(
                    preset_name, field_name, field_name))

    float_fields = {
        'poll_interval': 0.0,
        'task_ttl': 0.0,
        'claim_ttl': 0.0,
        'min_reply_interval': 0.0,
        'stale_lock_after': 0.0,
    }
    int_fields = {
        'max_pending': 1,
        'max_task_context': 1,
        'max_messages_per_hour': 1,
    }
    for field_name, minimum in float_fields.items():
        if field_name in normalized:
            value = float(normalized[field_name])
            if value < minimum:
                raise ConfigError(
                    'presets.{}.daemon.{} must be greater than or equal to {}.'.format(
                        preset_name, field_name, minimum))
            normalized[field_name] = value
    for field_name, minimum in int_fields.items():
        if field_name in normalized:
            value = int(normalized[field_name])
            if value < minimum:
                raise ConfigError(
                    'presets.{}.daemon.{} must be greater than or equal to {}.'.format(
                        preset_name, field_name, minimum))
            normalized[field_name] = value
    return normalized


def _copy_config_dict(defaults):
    copied = {}
    for key, value in defaults.items():
        copied[key] = list(value) if isinstance(value, list) else value
    return copied


def _object_config(value, path):
    if value in (None, ''):
        return {}
    if not isinstance(value, dict):
        raise ConfigError('{} must contain a JSON object.'.format(path))
    return value


def _social_string(value, path):
    if value in (None, ''):
        return ''
    if not isinstance(value, str):
        raise ConfigError('{} must be a string.'.format(path))
    return value.strip()


def _social_string_list(value, path):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        values = [value]
    else:
        if isinstance(value, dict):
            raise ConfigError(
                '{} must be a string or list of strings.'.format(path))
        try:
            values = list(value)
        except TypeError as exc:
            raise ConfigError(
                '{} must be a string or list of strings.'.format(path)) from exc

    result = []
    for item in values:
        if item in (None, ''):
            continue
        if not isinstance(item, str):
            raise ConfigError(
                '{} must be a string or list of strings.'.format(path))
        item = item.strip()
        if item:
            result.append(item)
    return result


def _social_float(data, name, path, minimum=None, maximum=None):
    field_path = '{}.{}'.format(path, name)
    try:
        value = float(data.get(name))
    except (TypeError, ValueError) as exc:
        raise ConfigError('{} must be a number.'.format(field_path)) from exc
    if minimum is not None and value < minimum:
        raise ConfigError('{} must be greater than or equal to {}.'.format(
            field_path, minimum))
    if maximum is not None and value > maximum:
        raise ConfigError('{} must be between {} and {}.'.format(
            field_path, minimum, maximum))
    return value


def _social_int(data, name, path, minimum=None):
    field_path = '{}.{}'.format(path, name)
    value = data.get(name)
    if isinstance(value, bool):
        raise ConfigError('{} must be an integer.'.format(field_path))
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError('{} must be an integer.'.format(field_path))
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError('{} must be an integer.'.format(field_path)) from exc
    if minimum is not None and value < minimum:
        raise ConfigError('{} must be greater than or equal to {}.'.format(
            field_path, minimum))
    return value


def _social_bool(data, name, path):
    field_path = '{}.{}'.format(path, name)
    value = data.get(name)
    if not isinstance(value, bool):
        raise ConfigError('{} must be a boolean.'.format(field_path))
    return value


def normalize_reply_policy(reply_policy=None, path='reply_policy',
                           include_defaults=True):
    reply_policy = _object_config(reply_policy, path)
    normalized = (
        _copy_config_dict(DEFAULT_REPLY_POLICY)
        if include_defaults else {}
    )
    normalized.update(reply_policy)

    if 'group_type' in normalized:
        normalized['group_type'] = _social_string(
            normalized.get('group_type'), '{}.group_type'.format(path))
    if 'reply_threshold' in normalized:
        normalized['reply_threshold'] = _social_float(
            normalized, 'reply_threshold', path, minimum=0.0, maximum=1.0)
    for field_name in (
            'prefer_reply_when', 'skip_when', 'style_rules',
            'conversation_rules'):
        if field_name in normalized:
            normalized[field_name] = _social_string_list(
                normalized.get(field_name), '{}.{}'.format(path, field_name))
    return normalized


def normalize_initiative(initiative=None, path='initiative',
                         include_defaults=True):
    initiative = _object_config(initiative, path)
    normalized = (
        _copy_config_dict(DEFAULT_INITIATIVE)
        if include_defaults else {}
    )
    normalized.update(initiative)

    for field_name in (
            'enabled', 'avoid_when_active', 'allow_topic_shift',
            'self_context_guard'):
        if field_name in normalized:
            normalized[field_name] = _social_bool(normalized, field_name, path)
    for field_name in ('group_type', 'style', 'topic_shift_style'):
        if field_name in normalized:
            normalized[field_name] = _social_string(
                normalized.get(field_name), '{}.{}'.format(path, field_name))
    for field_name in (
            'idle_after', 'cooldown', 'min_start_after', 'recent_window'):
        if field_name in normalized:
            normalized[field_name] = _social_float(
                normalized, field_name, path, minimum=0.0)
    for field_name in ('max_starts', 'min_starts', 'active_threshold'):
        if field_name in normalized:
            normalized[field_name] = _social_int(
                normalized, field_name, path, minimum=0)
    for field_name in ('self_context_recent', 'self_context_max_trailing_own'):
        if field_name in normalized:
            normalized[field_name] = _social_int(
                normalized, field_name, path, minimum=1)
    for field_name in (
            'topic_sources', 'topics', 'allowed_intents',
            'forbidden_topics', 'topic_shift_when', 'fallback_topics'):
        if field_name in normalized:
            normalized[field_name] = _social_string_list(
                normalized.get(field_name), '{}.{}'.format(path, field_name))
    return normalized


def normalize_persona(persona=None, path='persona', include_defaults=True):
    persona = _object_config(persona, path)
    normalized = (
        _copy_config_dict(DEFAULT_PERSONA)
        if include_defaults else {}
    )
    normalized.update(persona)

    if 'identity' in normalized:
        normalized['identity'] = _social_string(
            normalized.get('identity'), '{}.identity'.format(path))
    for field_name in ('traits', 'catchphrases', 'avoid', 'style_notes'):
        if field_name in normalized:
            normalized[field_name] = _social_string_list(
                normalized.get(field_name), '{}.{}'.format(path, field_name))
    return normalized


def _normalize_profile_overlay(profile, preset_name):
    normalized = dict(profile)
    if 'max_chars' in normalized:
        normalized['max_chars'] = int(normalized['max_chars'])
        if normalized['max_chars'] < 1:
            raise ConfigError('presets.{}.profile.max_chars must be greater than 0.'.format(
                preset_name))
    if 'avoid_topics' in normalized:
        normalized['avoid_topics'] = _string_list(
            normalized.get('avoid_topics'), 'avoid_topics')
    if 'forbidden_terms' in normalized:
        normalized['forbidden_terms'] = _string_list(
            normalized.get('forbidden_terms'), 'forbidden_terms')
    return normalized


def _normalize_round_overlay(round_config, preset_name):
    normalized = dict(round_config)
    float_fields = {
        'duration': 0.0,
        'min_reply_interval': 0.0,
        'end_buffer': 0.0,
        'random_delay_min': 0.0,
        'random_delay_max': 0.0,
        'merge_window': 0.0,
        'split_delay_min': 0.0,
        'split_delay_max': 0.0,
    }
    int_fields = {
        'limit': 1,
        'max_replies': 1,
        'min_reply_chars': 0,
        'split_max_chars': 1,
        'split_max_parts': 1,
    }
    bool_fields = {
        'quiet_context',
        'skip_short_ack',
        'split_long_replies',
    }
    probability_fields = {
        'reply_probability': False,
        'mention_reply_probability': True,
    }

    for field_name, minimum in float_fields.items():
        if field_name in normalized:
            value = float(normalized[field_name])
            if value < minimum:
                raise ConfigError('presets.{}.round.{} must be greater than or equal to {}.'.format(
                    preset_name, field_name, minimum))
            normalized[field_name] = value

    for field_name, minimum in int_fields.items():
        if field_name in normalized:
            value = int(normalized[field_name])
            if value < minimum:
                raise ConfigError('presets.{}.round.{} must be greater than or equal to {}.'.format(
                    preset_name, field_name, minimum))
            normalized[field_name] = value

    for field_name in bool_fields:
        if field_name in normalized:
            normalized[field_name] = bool(normalized[field_name])

    for field_name, allow_none in probability_fields.items():
        if field_name in normalized:
            value = normalized[field_name]
            if value is None and allow_none:
                normalized[field_name] = None
                continue
            value = float(value)
            if value < 0.0 or value > 1.0:
                raise ConfigError('presets.{}.round.{} must be between 0 and 1.'.format(
                    preset_name, field_name))
            normalized[field_name] = value

    return normalized


def normalize_presets(presets=None):
    if presets in (None, ''):
        return {}
    if not isinstance(presets, dict):
        raise ConfigError('presets must contain a JSON object.')

    normalized = {}
    for name, preset in presets.items():
        preset_name = str(name).strip()
        if not preset_name:
            raise ConfigError('preset names must not be empty.')
        if not isinstance(preset, dict):
            raise ConfigError('presets.{} must contain a JSON object.'.format(
                preset_name))

        profile = preset.get('profile', {})
        round_config = preset.get('round', {})
        reply_policy = preset.get('reply_policy', {})
        initiative = preset.get('initiative', {})
        persona = preset.get('persona', {})
        daemon_config = preset.get('daemon', {})
        character = preset.get('character', {})
        if profile in (None, ''):
            profile = {}
        if round_config in (None, ''):
            round_config = {}
        if reply_policy in (None, ''):
            reply_policy = {}
        if initiative in (None, ''):
            initiative = {}
        if persona in (None, ''):
            persona = {}
        if daemon_config in (None, ''):
            daemon_config = {}
        if character in (None, ''):
            character = {}
        if not isinstance(profile, dict):
            raise ConfigError(
                'presets.{}.profile must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(round_config, dict):
            raise ConfigError(
                'presets.{}.round must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(reply_policy, dict):
            raise ConfigError(
                'presets.{}.reply_policy must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(initiative, dict):
            raise ConfigError(
                'presets.{}.initiative must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(persona, dict):
            raise ConfigError(
                'presets.{}.persona must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(daemon_config, dict):
            raise ConfigError(
                'presets.{}.daemon must contain a JSON object.'.format(
                    preset_name))
        if not isinstance(character, dict):
            raise ConfigError(
                'presets.{}.character must contain a JSON object.'.format(
                    preset_name))

        normalized[preset_name] = {
            'profile': _normalize_profile_overlay(profile, preset_name),
            'round': _normalize_round_overlay(round_config, preset_name),
            'daemon': _normalize_daemon_overlay(daemon_config, preset_name),
            'reply_policy': normalize_reply_policy(
                reply_policy,
                path='presets.{}.reply_policy'.format(preset_name),
                include_defaults=False),
            'initiative': normalize_initiative(
                initiative,
                path='presets.{}.initiative'.format(preset_name),
                include_defaults=False),
            'persona': normalize_persona(
                persona,
                path='presets.{}.persona'.format(preset_name),
                include_defaults=False),
            'character': normalize_character_overlay(character, preset_name),
        }
    return normalized


def normalize_account_name(value=None):
    if value in (None, ''):
        return ''
    if not isinstance(value, str):
        raise ConfigError('account_name must be a string.')
    normalized = value.strip()
    if not normalized:
        raise ConfigError('account_name must not be blank.')
    return normalized


def _resolve_path_value(value, path_base):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(path_base) / path
    return str(path)


class AppConfig:
    def __init__(
            self, api_id=None, api_hash=None, session_path=None,
            allowed_chats=None, state_path=None, audit_log_path=None,
            profile=None, round_config=None, presets=None, config_path=None,
            reply_policy=None, initiative=None, persona=None,
            daemon_config=None, quota_config=None, character=None,
            memory_config=None, bad_cases_config=None, account_name=None):
        self.account_name = normalize_account_name(account_name)
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = Path(session_path).expanduser().resolve()
        self.allowed_chats = tuple(int(x) for x in (allowed_chats or ()))
        self.state_path = Path(state_path).expanduser().resolve()
        self.audit_log_path = Path(audit_log_path).expanduser().resolve()
        self.profile = normalize_profile(profile)
        self.round = normalize_round(round_config)
        self.daemon = normalize_daemon(daemon_config)
        for field_name in ('queue_path', 'lock_path', 'status_path'):
            if self.daemon.get(field_name) is not None:
                self.daemon[field_name] = (
                    Path(self.daemon[field_name]).expanduser().resolve())
        self.quota = normalize_quota(quota_config)
        if self.quota.get('state_path') is not None:
            self.quota['state_path'] = (
                Path(self.quota['state_path']).expanduser().resolve())
        self.memory = normalize_memory(memory_config)
        if self.memory.get('path') is not None:
            self.memory['path'] = (
                Path(self.memory['path']).expanduser().resolve())
        self.bad_cases = normalize_bad_cases(bad_cases_config)
        if self.bad_cases.get('path') is not None:
            self.bad_cases['path'] = (
                Path(self.bad_cases['path']).expanduser().resolve())
        self.reply_policy = normalize_reply_policy(reply_policy)
        self.initiative = normalize_initiative(initiative)
        self.persona = normalize_persona(persona)
        self.character = normalize_character(character)
        self.presets = normalize_presets(presets)
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None

    def require_credentials(self):
        if not self.api_id:
            raise ConfigError('Missing api_id. Set TG_API_ID or add api_id to config.')
        if not self.api_hash:
            raise ConfigError('Missing api_hash. Set TG_API_HASH or add api_hash to config.')

    def _preset(self, preset_name=None):
        if preset_name in (None, ''):
            return None
        preset_name = str(preset_name).strip()
        if not preset_name:
            return None
        if preset_name not in self.presets:
            available = ', '.join(sorted(self.presets)) or 'none'
            raise ConfigError(
                'Unknown preset "{}". Available presets: {}.'.format(
                    preset_name, available))
        return self.presets[preset_name]

    def resolve_profile(self, preset_name=None):
        profile = dict(self.profile)
        preset = self._preset(preset_name)
        if preset:
            profile.update(preset.get('profile') or {})
        return normalize_profile(profile)

    def resolve_round(self, preset_name=None):
        round_config = dict(self.round)
        preset = self._preset(preset_name)
        if preset:
            round_config.update(preset.get('round') or {})
        return normalize_round(round_config)

    def resolve_reply_policy(self, preset_name=None):
        reply_policy = dict(self.reply_policy)
        preset = self._preset(preset_name)
        if preset:
            reply_policy.update(preset.get('reply_policy') or {})
        return normalize_reply_policy(reply_policy)

    def resolve_initiative(self, preset_name=None):
        initiative = dict(self.initiative)
        preset = self._preset(preset_name)
        if preset:
            initiative.update(preset.get('initiative') or {})
        return normalize_initiative(initiative)

    def resolve_persona(self, preset_name=None):
        persona = dict(self.persona)
        preset = self._preset(preset_name)
        if preset:
            persona.update(preset.get('persona') or {})
        return normalize_persona(persona)

    def resolve_character(self, preset_name=None):
        character = dict(self.character)
        preset = self._preset(preset_name)
        if preset:
            return merge_character(character, preset.get('character') or {})
        return normalize_character(character)

    def resolve_daemon(self, preset_name=None):
        daemon_config = dict(self.daemon)
        preset = self._preset(preset_name)
        if preset:
            daemon_config.update(preset.get('daemon') or {})
        return normalize_daemon(daemon_config)


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
    path_base = Path(config_path).expanduser().parent if config_path else base

    api_id = env.get('TG_API_ID') or data.get('api_id')
    if api_id not in (None, ''):
        api_id = int(api_id)

    session_path = _resolve_path_value(
        env.get('TG_CLI_SESSION')
        or env.get('TG_SESSION_PATH')
        or data.get('session_path')
        or str(base / 'printer.session'),
        path_base
    )

    allowed_chats = parse_chat_ids(
        env.get('TG_CLI_ALLOWED_CHATS')
        if env.get('TG_CLI_ALLOWED_CHATS') is not None
        else data.get('allowed_chats', [])
    )

    state_path = _resolve_path_value(
        env.get('TG_CLI_STATE')
        or data.get('state_path')
        or str(base / 'tg_cli' / '.tg-cli-state.json'),
        path_base
    )
    audit_log_path = _resolve_path_value(
        env.get('TG_CLI_AUDIT_LOG')
        or data.get('audit_log_path')
        or str(base / 'tg_cli' / 'tg-cli.audit.log'),
        path_base
    )
    daemon_config = dict(data.get('daemon') or {})
    daemon_config.setdefault(
        'queue_path',
        str(base / 'tg_cli' / '.tg-cli-daemon-queue.json'))
    daemon_config.setdefault(
        'lock_path',
        str(base / 'tg_cli' / '.tg-cli-daemon.lock'))
    daemon_config.setdefault(
        'status_path',
        str(base / 'tg_cli' / '.tg-cli-daemon-status.json'))
    for field_name in ('queue_path', 'lock_path', 'status_path'):
        if daemon_config.get(field_name) not in (None, ''):
            daemon_config[field_name] = _resolve_path_value(
                daemon_config[field_name], path_base)
    quota_config = dict(data.get('quota') or {})
    quota_config.setdefault(
        'state_path',
        str(base / 'tg_cli' / '.tg-cli-quota-state.json'))
    if quota_config.get('state_path') not in (None, ''):
        quota_config['state_path'] = _resolve_path_value(
            quota_config['state_path'], path_base)
    memory_config = dict(data.get('memory') or {})
    memory_config.setdefault(
        'path',
        str(base / 'tg_cli' / '.tg-cli-memory.sqlite3'))
    if memory_config.get('path') not in (None, ''):
        memory_config['path'] = _resolve_path_value(
            memory_config['path'], path_base)
    bad_cases_config = dict(data.get('bad_cases') or {})
    bad_cases_config.setdefault(
        'path',
        str(base / 'tg_cli' / '.tg-cli-bad-cases.jsonl'))
    if bad_cases_config.get('path') not in (None, ''):
        bad_cases_config['path'] = _resolve_path_value(
            bad_cases_config['path'], path_base)

    cfg = AppConfig(
        api_id=api_id,
        api_hash=env.get('TG_API_HASH') or data.get('api_hash'),
        session_path=session_path,
        allowed_chats=allowed_chats,
        state_path=state_path,
        audit_log_path=audit_log_path,
        profile=data.get('profile'),
        round_config=data.get('round'),
        presets=data.get('presets'),
        config_path=config_path,
        reply_policy=data.get('reply_policy'),
        initiative=data.get('initiative'),
        persona=data.get('persona'),
        character=data.get('character'),
        daemon_config=daemon_config,
        quota_config=quota_config,
        memory_config=memory_config,
        bad_cases_config=bad_cases_config,
        account_name=env.get('TG_CLI_ACCOUNT') or data.get('account_name'),
    )
    if require_credentials:
        cfg.require_credentials()
    return cfg
