import json

import pytest

from tg_cli import quota


NOW = '2026-06-01T06:00:00+00:00'
LATER = '2026-06-01T06:01:00+00:00'


def test_load_state_defaults_to_empty_state(tmp_path):
    state_path = tmp_path / 'missing' / 'quota-state.json'

    state = quota.load_state(state_path)

    assert state == {
        'version': 1,
        'run_id': None,
        'status': 'empty',
        'created_at': None,
        'updated_at': None,
        'preset': None,
        'targets': [],
        'tasks': [],
    }


def test_save_state_is_atomic_and_creates_parent(tmp_path):
    state_path = tmp_path / 'nested' / 'quota-state.json'
    payload = {
        'version': 1,
        'run_id': 'quota-test',
        'status': 'active',
        'created_at': NOW,
        'updated_at': NOW,
        'preset': None,
        'targets': [],
        'tasks': [],
    }

    saved = quota.save_state(state_path, payload)

    assert saved == payload
    assert json.loads(state_path.read_text(encoding='utf-8')) == payload
    assert list(state_path.parent.glob('*.tmp')) == []


def test_create_run_normalizes_targets_and_status(tmp_path):
    state_path = tmp_path / 'quota-state.json'

    state = quota.create_run(
        state_path,
        [{'chat_id': '111', 'target_count': '2'}, ('222', 3)],
        preset='chat_social',
        now=NOW,
    )

    assert state['run_id'] == 'quota-20260601T060000Z'
    assert state['status'] == 'active'
    assert state['created_at'] == NOW
    assert state['updated_at'] == NOW
    assert state['preset'] == 'chat_social'
    assert state['tasks'] == []
    assert state['targets'] == [
        {
            'chat_id': 111,
            'target_count': 2,
            'sent_count': 0,
            'status': 'active',
            'last_sent_at': None,
            'message_ids': [],
        },
        {
            'chat_id': 222,
            'target_count': 3,
            'sent_count': 0,
            'status': 'active',
            'last_sent_at': None,
            'message_ids': [],
        },
    ]
    assert quota.status(state_path) == state
    assert quota.get_status(state_path) == state


@pytest.mark.parametrize('targets', [
    [],
    [('111', 0)],
    [('111', -1)],
    [('111', 1), (111, 2)],
    ['111'],
])
def test_create_run_validates_targets(tmp_path, targets):
    with pytest.raises(ValueError):
        quota.create_run(tmp_path / 'quota-state.json', targets, now=NOW)


def test_create_run_accepts_mapping_and_chat_count_strings(tmp_path):
    state_path = tmp_path / 'quota-state.json'

    state = quota.create_run(
        state_path,
        {'111': 1, 222: 2},
        now=NOW,
    )
    replaced = quota.create_run(
        state_path,
        ['333:3'],
        now=LATER,
    )

    assert [target['chat_id'] for target in state['targets']] == [111, 222]
    assert replaced['run_id'] == 'quota-20260601T060100Z'
    assert replaced['targets'][0]['chat_id'] == 333
    assert replaced['targets'][0]['target_count'] == 3
    assert replaced['tasks'] == []


def test_next_target_returns_first_active_unfinished_target(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 1), (222, 2)], now=NOW)

    first = quota.next_target(state_path)
    task = quota.create_task(state_path, first['chat_id'], now=NOW)
    quota.complete_task(state_path, task['id'], message_ids=[10], now=LATER)

    second = quota.next_target(state_path)

    assert first['chat_id'] == 111
    assert second['chat_id'] == 222


def test_create_task_stores_context_and_get_task_returns_copy(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    context = {'recent': [{'id': 1, 'text': 'hello'}]}
    quota.create_run(state_path, [(111, 1)], preset='chat_social', now=NOW)

    task = quota.create_task(state_path, 111, context=context, now=NOW)
    context['recent'][0]['text'] = 'changed'
    loaded = quota.get_task(state_path, task['id'])
    loaded['context']['recent'][0]['text'] = 'mutated'

    saved = quota.get_task(state_path, task['id'])
    assert task['id'].startswith('quota-task-20260601T060000Z-')
    assert task['status'] == 'pending'
    assert task['chat_id'] == 111
    assert task['context'] == {'recent': [{'id': 1, 'text': 'hello'}]}
    assert saved['context'] == {'recent': [{'id': 1, 'text': 'hello'}]}


def test_create_task_refuses_unknown_done_or_stopped_targets(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 1)], now=NOW)

    assert quota.create_task(state_path, 222, now=NOW) is None
    task = quota.create_task(state_path, 111, now=NOW)
    quota.complete_task(state_path, task['id'], message_ids=[10], now=LATER)
    assert quota.create_task(state_path, 111, now=LATER) is None

    quota.create_run(state_path, [(111, 1)], now=NOW)
    quota.stop_run(state_path, now=LATER)
    assert quota.create_task(state_path, 111, now=LATER) is None


def test_complete_task_counts_split_message_ids_and_marks_run_done(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 2)], now=NOW)
    task = quota.create_task(state_path, 111, now=NOW)

    completed = quota.complete_task(
        state_path, task['id'], message_ids=[10, '11'], now=LATER)
    state = quota.get_status(state_path)

    assert completed['status'] == 'completed'
    assert completed['dry_run'] is False
    assert completed['message_ids'] == [10, 11]
    assert completed['sent_count_delta'] == 2
    assert state['status'] == 'done'
    assert state['completed_at'] == LATER
    assert state['targets'][0]['sent_count'] == 2
    assert state['targets'][0]['status'] == 'done'
    assert state['targets'][0]['last_sent_at'] == LATER
    assert state['targets'][0]['message_ids'] == [10, 11]
    assert quota.next_target(state_path) is None


def test_complete_task_dry_run_does_not_count_or_consume_task(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 1)], now=NOW)
    task = quota.create_task(state_path, 111, now=NOW)

    completed = quota.complete_task(
        state_path, task['id'], message_ids=[10], dry_run=True, now=LATER)
    state = quota.get_status(state_path)

    assert completed['status'] == 'pending'
    assert completed['dry_run'] is True
    assert completed['dry_run_checked_at'] == '2026-06-01T06:01:00+00:00'
    assert completed['message_ids'] == [10]
    assert completed['sent_count_delta'] == 0
    assert state['status'] == 'active'
    assert state['tasks'][0]['status'] == 'pending'
    assert 'dry_run_checked_at' not in state['tasks'][0]
    assert state['targets'][0]['sent_count'] == 0
    assert state['targets'][0]['status'] == 'active'
    assert state['targets'][0]['message_ids'] == []


def test_run_is_done_only_after_all_targets_are_done(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 2), (222, 1)], now=NOW)

    first = quota.create_task(state_path, 111, now=NOW)
    quota.complete_task(state_path, first['id'], message_ids=[10], now=LATER)
    state = quota.get_status(state_path)
    assert state['status'] == 'active'
    assert state['targets'][0]['status'] == 'active'

    second = quota.create_task(state_path, 111, now=NOW)
    quota.complete_task(state_path, second['id'], message_ids=[11], now=LATER)
    state = quota.get_status(state_path)
    assert state['status'] == 'active'
    assert state['targets'][0]['status'] == 'done'
    assert state['targets'][1]['status'] == 'active'

    third = quota.create_task(state_path, 222, now=NOW)
    quota.complete_task(state_path, third['id'], message_ids=[20], now=LATER)
    state = quota.get_status(state_path)
    assert state['status'] == 'done'
    assert [target['status'] for target in state['targets']] == [
        'done', 'done']


def test_skip_task_does_not_count_and_is_terminal(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 1)], now=NOW)
    task = quota.create_task(state_path, 111, now=NOW)

    skipped = quota.skip_task(
        state_path, task['id'], reason='not useful', now=LATER)
    state = quota.get_status(state_path)

    assert skipped['status'] == 'skipped'
    assert skipped['reason'] == 'not useful'
    assert quota.complete_task(
        state_path, task['id'], message_ids=[10], now=LATER) is None
    assert quota.skip_task(state_path, task['id'], now=LATER) is None
    assert state['status'] == 'active'
    assert state['targets'][0]['sent_count'] == 0


def test_stop_run_prevents_new_task_creation_and_completion(tmp_path):
    state_path = tmp_path / 'quota-state.json'
    quota.create_run(state_path, [(111, 1)], now=NOW)
    task = quota.create_task(state_path, 111, now=NOW)

    stopped = quota.stop_run(state_path, now=LATER)

    assert stopped['status'] == 'stopped'
    assert stopped['stopped_at'] == LATER
    assert quota.create_task(state_path, 111, now=LATER) is None
    assert quota.complete_task(
        state_path, task['id'], message_ids=[10], now=LATER) is None
    state = quota.get_status(state_path)
    assert state['status'] == 'stopped'
    assert state['targets'][0]['sent_count'] == 0
    assert quota.next_target(state_path) is None
