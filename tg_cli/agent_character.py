import copy


DEFAULT_CHARACTER = {
    'name': '',
    'bio': [],
    'lore': [],
    'style': {
        'all': [],
        'chat': [],
    },
    'topics': [],
    'adjectives': [],
    'message_examples': [],
    'actions': ['reply', 'skip'],
    'evaluators': ['not_everything', 'cooldown', 'no_identity_claims'],
}


def _config_error(message):
    from .config import ConfigError
    return ConfigError(message)


def _string(value, path):
    if value in (None, ''):
        return ''
    if not isinstance(value, str):
        raise _config_error('{} must be a string.'.format(path))
    return value.strip()


def _string_list(value, path):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        values = [value]
    else:
        if isinstance(value, dict):
            raise _config_error(
                '{} must be a string or list of strings.'.format(path))
        try:
            values = list(value)
        except TypeError as exc:
            raise _config_error(
                '{} must be a string or list of strings.'.format(path)) from exc

    result = []
    for item in values:
        if item in (None, ''):
            continue
        if not isinstance(item, str):
            raise _config_error(
                '{} must be a string or list of strings.'.format(path))
        item = item.strip()
        if item:
            result.append(item)
    return result


def _style(value, path='character.style', include_defaults=True):
    if value in (None, ''):
        value = {}
    if not isinstance(value, dict):
        raise _config_error('{} must contain a JSON object.'.format(path))
    normalized = {}
    if include_defaults or 'all' in value:
        normalized['all'] = _string_list(value.get('all'), '{}.all'.format(path))
    if include_defaults or 'chat' in value:
        normalized['chat'] = _string_list(
            value.get('chat'), '{}.chat'.format(path))
    return normalized


def _message_examples(value, path='character.message_examples'):
    if value in (None, ''):
        return []
    if not isinstance(value, list):
        raise _config_error('{} must be a list.'.format(path))
    return copy.deepcopy(value)


def normalize_character(character=None, path='character', include_defaults=True):
    if character in (None, ''):
        character = {}
    if not isinstance(character, dict):
        raise _config_error('{} must contain a JSON object.'.format(path))

    base = copy.deepcopy(DEFAULT_CHARACTER) if include_defaults else {}
    base.update(character)
    normalized = {}
    if 'name' in base:
        normalized['name'] = _string(base.get('name'), '{}.name'.format(path))
    if 'bio' in base:
        normalized['bio'] = _string_list(base.get('bio'), '{}.bio'.format(path))
    if 'lore' in base:
        normalized['lore'] = _string_list(base.get('lore'), '{}.lore'.format(path))
    if 'style' in base:
        normalized['style'] = _style(
            base.get('style'), '{}.style'.format(path),
            include_defaults=include_defaults)
    if 'topics' in base:
        normalized['topics'] = _string_list(
            base.get('topics'), '{}.topics'.format(path))
    if 'adjectives' in base:
        normalized['adjectives'] = _string_list(
            base.get('adjectives'), '{}.adjectives'.format(path))
    if 'message_examples' in base:
        normalized['message_examples'] = _message_examples(
            base.get('message_examples'),
            '{}.message_examples'.format(path))
    if 'actions' in base:
        normalized['actions'] = _string_list(
            base.get('actions'), '{}.actions'.format(path))
    if 'evaluators' in base:
        normalized['evaluators'] = _string_list(
            base.get('evaluators'), '{}.evaluators'.format(path))
    return normalized


def normalize_character_overlay(character=None, preset_name=None):
    path = 'presets.{}.character'.format(preset_name)
    return normalize_character(character, path=path, include_defaults=False)


def merge_character(base, overlay=None):
    merged = normalize_character(base)
    overlay = normalize_character(
        overlay, path='character', include_defaults=False)
    if not overlay:
        return merged
    for key, value in overlay.items():
        if key == 'style':
            current = dict(merged.get('style') or {})
            current.update(value)
            merged['style'] = _style(current)
        else:
            merged[key] = copy.deepcopy(value)
    return normalize_character(merged)


def character_to_social_config(character):
    character = normalize_character(character)
    name = character.get('name') or '普通群友'
    traits = []
    traits.extend(character.get('bio') or [])
    traits.extend(character.get('adjectives') or [])
    style_rules = []
    style_rules.extend((character.get('style') or {}).get('all') or [])
    style_rules.extend((character.get('style') or {}).get('chat') or [])
    return {
        'persona': {
            'identity': name,
            'traits': traits,
            'catchphrases': [],
            'avoid': list(character.get('lore') or []),
            'style_notes': style_rules,
        },
        'reply_policy': {
            'style_rules': style_rules,
            'conversation_rules': list(character.get('lore') or []),
        },
        'initiative': {
            'topics': list(character.get('topics') or []),
        },
        'actions': list(character.get('actions') or []),
        'evaluators': list(character.get('evaluators') or []),
    }
