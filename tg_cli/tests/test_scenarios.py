import json

import pytest

from tg_cli.scenarios import (
    DEFAULT_SCENARIOS_PATH, DEFAULT_STOP_ON, ScenarioConfigError, get_scenario,
    load_scenarios, validate_scenario,
)


def _scenario(**overrides):
    item = {
        'name': 'long-run-smoke',
        'account': 'test-account',
        'chat_id': 12345,
        'persona': 'casual_member',
        'preset': 'chat_social',
        'target_messages': 5,
    }
    item.update(overrides)
    return item


def test_validate_scenario_supplies_defaults():
    scenario = validate_scenario(_scenario())

    assert DEFAULT_SCENARIOS_PATH.name == '.tg-cli-scenarios.json'
    assert scenario == {
        'name': 'long-run-smoke',
        'account': 'test-account',
        'chat_id': 12345,
        'persona': 'casual_member',
        'preset': 'chat_social',
        'target_messages': 5,
        'dry_run_first': True,
        'max_runtime_minutes': None,
        'stop_on': DEFAULT_STOP_ON,
    }


def test_validate_scenario_keeps_target_150():
    scenario = validate_scenario(_scenario(target_messages=150))

    assert scenario['target_messages'] == 150


def test_validate_scenario_merges_stop_reasons_and_runtime():
    scenario = validate_scenario(_scenario(
        dry_run_first=False,
        max_runtime_minutes='30',
        stop_on=['custom_stop', 'manual_stop'],
    ))

    assert scenario['dry_run_first'] is False
    assert scenario['max_runtime_minutes'] == 30.0
    assert scenario['stop_on'][0] == 'custom_stop'
    assert scenario['stop_on'].count('manual_stop') == 1
    assert set(DEFAULT_STOP_ON).issubset(set(scenario['stop_on']))


@pytest.mark.parametrize('overrides', [
    {'name': ''},
    {'account': None},
    {'persona': []},
    {'preset': '  '},
    {'chat_id': 1.2},
    {'chat_id': True},
    {'target_messages': 0},
    {'max_runtime_minutes': 0},
    {'stop_on': 'manual_stop'},
    {'stop_on': ['manual_stop', '']},
    {'api_hash': 'secret'},
    {'session_path': 'account.session'},
])
def test_validate_scenario_rejects_invalid_config(overrides):
    with pytest.raises(ScenarioConfigError):
        validate_scenario(_scenario(**overrides))


def test_load_scenarios_reads_list_and_returns_copy(tmp_path):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps([
        _scenario(name='first'),
        _scenario(name='second', chat_id='67890'),
    ]), encoding='utf-8')

    scenarios = load_scenarios(path)
    scenarios[0]['name'] = 'changed'

    assert [item['name'] for item in load_scenarios(path)] == ['first', 'second']
    assert load_scenarios(path)[1]['chat_id'] == 67890


def test_load_scenarios_reads_object_wrapper(tmp_path):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps({
        'scenarios': [_scenario(name='wrapped')],
    }), encoding='utf-8')

    assert load_scenarios(path)[0]['name'] == 'wrapped'


def test_load_scenarios_rejects_duplicate_names(tmp_path):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps([
        _scenario(name='same'),
        _scenario(name='same'),
    ]), encoding='utf-8')

    with pytest.raises(ScenarioConfigError):
        load_scenarios(path)


def test_load_scenarios_missing_file_is_empty(tmp_path):
    assert load_scenarios(tmp_path / 'missing.json') == []


def test_get_scenario_finds_by_name_and_returns_copy(tmp_path):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps([
        _scenario(name='alpha'),
        _scenario(name='beta', target_messages=150),
    ]), encoding='utf-8')

    scenario = get_scenario(path, 'beta')
    scenario['target_messages'] = 1

    assert scenario['chat_id'] == 12345
    assert get_scenario(path, 'beta')['target_messages'] == 150


def test_get_scenario_rejects_missing_name(tmp_path):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps([_scenario(name='alpha')]), encoding='utf-8')

    with pytest.raises(ScenarioConfigError):
        get_scenario(path, 'missing')
