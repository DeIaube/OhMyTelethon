import copy
import json
from pathlib import Path


DEFAULT_SCENARIOS_PATH = Path(__file__).resolve().parent / '.tg-cli-scenarios.json'

DEFAULT_STOP_ON = [
    'target_reached',
    'manual_stop',
    'moderation_warning',
    'spam_complaint',
    'too_many_stale_context',
]

SENSITIVE_FIELDS = {
    'api_hash',
    'api_id',
    'credentials',
    'password',
    'phone',
    'session',
    'session_path',
}


class ScenarioConfigError(ValueError):
    pass


def _copy(value):
    return copy.deepcopy(value)


def _coerce_non_empty_string(item, name):
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioConfigError('scenario.{} must be a non-empty string.'.format(name))
    return value.strip()


def _coerce_int(item, name):
    value = item.get(name)
    if isinstance(value, bool):
        raise ScenarioConfigError('scenario.{} must be an integer.'.format(name))
    if isinstance(value, float) and not value.is_integer():
        raise ScenarioConfigError('scenario.{} must be an integer.'.format(name))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioConfigError(
            'scenario.{} must be an integer.'.format(name)) from exc


def _coerce_positive_int(item, name):
    value = _coerce_int(item, name)
    if value <= 0:
        raise ScenarioConfigError(
            'scenario.{} must be greater than 0.'.format(name))
    return value


def _coerce_optional_positive_float(item, name):
    value = item.get(name)
    if value in (None, ''):
        return None
    if isinstance(value, bool):
        raise ScenarioConfigError(
            'scenario.{} must be greater than 0.'.format(name))
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ScenarioConfigError(
            'scenario.{} must be greater than 0.'.format(name)) from exc
    if normalized <= 0:
        raise ScenarioConfigError(
            'scenario.{} must be greater than 0.'.format(name))
    return normalized


def _coerce_stop_on(item):
    value = item.get('stop_on')
    if value is None:
        return list(DEFAULT_STOP_ON)
    if isinstance(value, str) or not isinstance(value, list):
        raise ScenarioConfigError('scenario.stop_on must be a list of strings.')

    normalized = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ScenarioConfigError(
                'scenario.stop_on must be a list of non-empty strings.')
        text = entry.strip()
        if text not in normalized:
            normalized.append(text)

    for required in DEFAULT_STOP_ON:
        if required not in normalized:
            normalized.append(required)
    return normalized


def validate_scenario(item):
    if not isinstance(item, dict):
        raise ScenarioConfigError('scenario must contain a JSON object.')

    sensitive = sorted(SENSITIVE_FIELDS.intersection(item))
    if sensitive:
        raise ScenarioConfigError(
            'scenario must not contain credential or session fields: {}.'.format(
                ', '.join(sensitive)))

    normalized = {
        'name': _coerce_non_empty_string(item, 'name'),
        'account': _coerce_non_empty_string(item, 'account'),
        'chat_id': _coerce_int(item, 'chat_id'),
        'persona': _coerce_non_empty_string(item, 'persona'),
        'preset': _coerce_non_empty_string(item, 'preset'),
        'target_messages': _coerce_positive_int(item, 'target_messages'),
        'dry_run_first': bool(item.get('dry_run_first', True)),
        'max_runtime_minutes': _coerce_optional_positive_float(
            item, 'max_runtime_minutes'),
        'stop_on': _coerce_stop_on(item),
    }
    return normalized


def _scenario_items(payload):
    if payload in (None, ''):
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('scenarios'), list):
        return payload['scenarios']
    raise ScenarioConfigError(
        'scenario config must contain a JSON list or an object with scenarios.')


def load_scenarios(path=DEFAULT_SCENARIOS_PATH):
    target = Path(path).expanduser()
    if not target.is_file():
        return []
    with target.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)

    scenarios = [validate_scenario(item) for item in _scenario_items(payload)]
    names = set()
    duplicates = set()
    for item in scenarios:
        name = item['name']
        if name in names:
            duplicates.add(name)
        names.add(name)
    if duplicates:
        raise ScenarioConfigError(
            'scenario names must be unique: {}.'.format(
                ', '.join(sorted(duplicates))))
    return _copy(scenarios)


def get_scenario(path, name):
    if not isinstance(name, str) or not name.strip():
        raise ScenarioConfigError('scenario name must be a non-empty string.')
    wanted = name.strip()
    for item in load_scenarios(path):
        if item['name'] == wanted:
            return _copy(item)
    raise ScenarioConfigError('scenario not found: {}.'.format(wanted))
