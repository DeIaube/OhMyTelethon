import json
import os
import threading
import time

import pytest

from tg_cli import daemon


def make_task(now='2026-06-01T00:00:00+00:00', kind='message'):
    return daemon.create_task(
        chat={'id': 2400000996, 'title': 'test group'},
        messages=[{'id': 1, 'text': 'hello'}],
        profile={'style': 'short'},
        persona={'identity': 'regular member'},
        reply_policy={'reply_threshold': 0.5},
        initiative={'enabled': True},
        preset='chat_social',
        kind=kind,
        prompt='Reply if useful.',
        now=now,
    )


def test_utc_now_returns_iso_utc_string():
    value = daemon.utc_now()

    assert value.endswith('+00:00')
    assert daemon._parse_time(value).tzinfo is not None


def test_load_queue_defaults_and_append_next_complete_lifecycle(tmp_path):
    queue_path = tmp_path / 'queue.json'

    assert daemon.load_queue(queue_path) == {'version': 1, 'tasks': []}

    task = make_task()
    assert daemon.append_task(queue_path, task) is True

    queue = daemon.load_queue(queue_path)
    assert queue['version'] == 1
    assert [item['id'] for item in queue['tasks']] == [task['id']]

    pending = daemon.next_pending_task(queue_path)
    assert pending['id'] == task['id']
    assert pending['status'] == 'pending'
    assert pending['chat']['id'] == 2400000996
    assert pending['messages'][0]['text'] == 'hello'
    assert pending['profile'] == {'style': 'short'}
    assert pending['persona'] == {'identity': 'regular member'}
    assert pending['reply_policy'] == {'reply_threshold': 0.5}
    assert pending['initiative'] == {'enabled': True}
    assert pending['preset'] == 'chat_social'
    assert pending['kind'] == 'message'
    assert pending['prompt'] == 'Reply if useful.'

    completed = daemon.complete_task(
        queue_path, task['id'], message_id=12345, dry_run=True)
    assert completed['status'] == 'completed'
    assert completed['message_id'] == 12345
    assert completed['dry_run'] is True
    assert daemon.next_pending_task(queue_path) is None
    assert daemon.queue_counts(queue_path) == {'completed': 1}


def test_create_task_can_include_context_summary():
    task = daemon.create_task(
        chat={'id': 2400000996, 'title': 'test group'},
        messages=[{'id': 1, 'text': 'hello'}],
        profile={'style': 'short'},
        persona={},
        reply_policy={},
        initiative={},
        context_summary={
            'message_count': 200,
            'summary': 'recent warmup',
            'recent_topics': ['开黑'],
        },
        now='2026-06-01T00:00:00+00:00',
    )

    assert task['context_summary'] == {
        'message_count': 200,
        'summary': 'recent warmup',
        'recent_topics': ['开黑'],
    }


def test_append_task_respects_max_pending(tmp_path):
    queue_path = tmp_path / 'queue.json'
    first = make_task(now='2026-06-01T00:00:00+00:00')
    second = make_task(now='2026-06-01T00:00:01+00:00')

    assert daemon.append_task(queue_path, first, max_pending=1) is True
    assert daemon.append_task(queue_path, second, max_pending=1) is False

    queue = daemon.load_queue(queue_path)
    assert [task['id'] for task in queue['tasks']] == [first['id']]


def test_append_task_counts_reply_pending_as_active(tmp_path):
    queue_path = tmp_path / 'queue.json'
    first = make_task(now='2026-06-01T00:00:00+00:00')
    second = make_task(now='2026-06-01T00:00:01+00:00')

    assert daemon.append_task(queue_path, first, max_pending=1) is True
    daemon.queue_reply_task(queue_path, first['id'], '来了')

    assert daemon.append_task(queue_path, second, max_pending=1) is False
    assert daemon.queue_counts(queue_path) == {'reply_pending': 1}


def test_append_task_serializes_read_modify_write(tmp_path, monkeypatch):
    queue_path = tmp_path / 'queue.json'
    first = make_task(now='2026-06-01T00:00:00+00:00')
    second = make_task(now='2026-06-01T00:00:01+00:00')
    original_write = daemon._atomic_write_json
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    write_count = 0
    count_lock = threading.Lock()
    errors = []

    def slow_first_write(path, payload):
        nonlocal write_count
        with count_lock:
            write_count += 1
            is_first_write = write_count == 1
        if is_first_write:
            first_write_started.set()
            release_first_write.wait(timeout=2.0)
        return original_write(path, payload)

    monkeypatch.setattr(daemon, '_atomic_write_json', slow_first_write)

    def append(task):
        try:
            daemon.append_task(queue_path, task)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    first_thread = threading.Thread(target=append, args=(first,))
    first_thread.start()
    assert first_write_started.wait(timeout=1.0)

    second_thread = threading.Thread(target=append, args=(second,))
    second_thread.start()
    time.sleep(0.05)
    release_first_write.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert errors == []
    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    queue = daemon.load_queue(queue_path)
    assert sorted(task['id'] for task in queue['tasks']) == sorted([
        first['id'], second['id']])


def test_next_pending_task_expires_old_tasks_and_returns_oldest_live(tmp_path):
    queue_path = tmp_path / 'queue.json'
    old_task = make_task(now='2026-06-01T00:00:00+00:00')
    live_task = make_task(now='2026-06-01T00:05:00+00:00')
    daemon.append_task(queue_path, old_task)
    daemon.append_task(queue_path, live_task)

    pending = daemon.next_pending_task(
        queue_path,
        now='2026-06-01T00:06:01+00:00',
        task_ttl=120,
    )

    assert pending['id'] == live_task['id']
    queue = daemon.load_queue(queue_path)
    assert queue['tasks'][0]['status'] == 'expired'
    assert queue['tasks'][0]['updated_at'] == '2026-06-01T00:06:01+00:00'
    assert queue['tasks'][1]['status'] == 'pending'
    assert daemon.queue_counts(queue_path) == {'expired': 1, 'pending': 1}


def test_next_pending_task_uses_created_at_not_file_order(tmp_path):
    queue_path = tmp_path / 'queue.json'
    newer_task = make_task(now='2026-06-01T00:10:00+00:00')
    older_task = make_task(now='2026-06-01T00:09:00+00:00')
    daemon.append_task(queue_path, newer_task)
    daemon.append_task(queue_path, older_task)

    pending = daemon.next_pending_task(
        queue_path,
        now='2026-06-01T00:11:00+00:00',
        task_ttl=600,
    )

    assert pending['id'] == older_task['id']


def test_claim_next_task_leases_oldest_pending_task(tmp_path):
    queue_path = tmp_path / 'queue.json'
    first = make_task(now='2026-06-01T00:00:00+00:00')
    second = make_task(now='2026-06-01T00:00:01+00:00')
    daemon.append_task(queue_path, first)
    daemon.append_task(queue_path, second)

    claimed = daemon.claim_next_task(
        queue_path,
        now='2026-06-01T00:00:10+00:00',
        claim_ttl=60,
        owner='agent-a')

    assert claimed['id'] == first['id']
    assert claimed['status'] == 'claimed'
    assert claimed['claim_owner'] == 'agent-a'
    assert claimed['claim_expires_at'] == '2026-06-01T00:01:10+00:00'
    assert daemon.next_pending_task(
        queue_path,
        now='2026-06-01T00:00:20+00:00')['id'] == second['id']


def test_claim_next_task_releases_expired_claims(tmp_path):
    queue_path = tmp_path / 'queue.json'
    task = make_task(now='2026-06-01T00:00:00+00:00')
    daemon.append_task(queue_path, task)
    daemon.claim_next_task(
        queue_path,
        now='2026-06-01T00:00:10+00:00',
        claim_ttl=30,
        owner='agent-a')

    reclaimed = daemon.claim_next_task(
        queue_path,
        now='2026-06-01T00:00:41+00:00',
        claim_ttl=30,
        owner='agent-b')

    assert reclaimed['id'] == task['id']
    assert reclaimed['claim_owner'] == 'agent-b'


def test_skip_and_complete_only_change_pending_tasks(tmp_path):
    queue_path = tmp_path / 'queue.json'
    skipped_task = make_task(now='2026-06-01T00:00:00+00:00')
    completed_task = make_task(now='2026-06-01T00:00:01+00:00')
    daemon.append_task(queue_path, skipped_task)
    daemon.append_task(queue_path, completed_task)

    skipped = daemon.skip_task(queue_path, skipped_task['id'], reason='not useful')
    assert skipped['status'] == 'skipped'
    assert skipped['reason'] == 'not useful'
    assert daemon.complete_task(queue_path, skipped_task['id'], message_id=1) is None

    completed = daemon.complete_task(queue_path, completed_task['id'])
    assert completed['status'] == 'completed'
    assert 'message_id' not in completed
    assert daemon.skip_task(queue_path, completed_task['id']) is None
    assert daemon.queue_counts(queue_path) == {'skipped': 1, 'completed': 1}


def test_queue_reply_and_complete_reply_pending_task(tmp_path):
    queue_path = tmp_path / 'queue.json'
    task = make_task()
    daemon.append_task(queue_path, task)

    queued = daemon.queue_reply_task(queue_path, task['id'], '短回复')

    assert queued['status'] == 'reply_pending'
    assert queued['reply_text'] == '短回复'
    assert queued['reply_dry_run'] is False
    assert 'reply_queued_at' in queued
    assert daemon.next_pending_task(queue_path) is None
    assert [item['id'] for item in daemon.reply_pending_tasks(queue_path)] == [
        task['id']]
    assert [item['id'] for item in daemon.reply_pending_tasks(queue_path, 2400000996)] == [
        task['id']]
    assert daemon.reply_pending_tasks(queue_path, 1) == []

    completed = daemon.complete_task(
        queue_path, task['id'], message_id=9, message_ids=[9, 10])

    assert completed['status'] == 'completed'
    assert completed['message_id'] == 9
    assert completed['message_ids'] == [9, 10]
    assert daemon.reply_pending_tasks(queue_path) == []


def test_reply_pending_tasks_expire_stale_replies(tmp_path):
    queue_path = tmp_path / 'queue.json'
    task = make_task(now='2026-06-01T00:00:00+00:00')
    daemon.append_task(queue_path, task)
    daemon.queue_reply_task(
        queue_path, task['id'], '短回复',
        now='2026-06-01T00:01:00+00:00')

    assert daemon.reply_pending_tasks(
        queue_path,
        now='2026-06-01T00:02:01+00:00',
        task_ttl=60) == []
    saved = daemon.get_task(queue_path, task['id'])
    assert saved['status'] == 'expired'


def test_held_rate_limited_task_waits_until_retry_after(tmp_path):
    queue_path = tmp_path / 'queue.json'
    task = make_task(now='2026-06-01T00:00:00+00:00')
    daemon.append_task(queue_path, task)
    daemon.queue_reply_task(
        queue_path, task['id'], '短回复',
        now='2026-06-01T00:01:00+00:00')
    held = daemon.hold_rate_limited_task(
        queue_path, task['id'], reason='hourly_limit',
        retry_after='2026-06-01T00:03:00+00:00',
        now='2026-06-01T00:02:00+00:00')

    assert held['status'] == 'held_rate_limit'
    assert daemon.reply_pending_tasks(
        queue_path,
        now='2026-06-01T00:02:30+00:00') == []

    due = daemon.reply_pending_tasks(
        queue_path,
        now='2026-06-01T00:03:00+00:00')

    assert [item['id'] for item in due] == [task['id']]
    saved = daemon.get_task(queue_path, task['id'])
    assert saved['status'] == 'reply_pending'
    assert 'retry_after' not in saved


def test_status_stop_flag_lifecycle(tmp_path):
    status_path = tmp_path / 'status.json'

    assert daemon.read_status(status_path) == {}
    assert daemon.stop_requested(status_path) is False

    written = daemon.write_status(status_path, {'pid': 100})
    assert written['pid'] == 100
    assert daemon.read_status(status_path)['pid'] == 100

    stopped = daemon.request_stop(status_path)
    assert stopped['pid'] == 100
    assert stopped['stop_requested'] is True
    assert daemon.stop_requested(status_path) is True

    resumed = daemon.clear_stop(status_path)
    assert resumed['stop_requested'] is False
    assert daemon.stop_requested(status_path) is False


def test_lock_acquire_release_and_owner_checks(tmp_path):
    lock_path = tmp_path / 'daemon.lock'

    lock = daemon.acquire_lock(lock_path, owner='worker-a')
    assert lock['owner'] == 'worker-a'
    assert lock['pid'] == os.getpid()

    with pytest.raises(daemon.DaemonLockError):
        daemon.acquire_lock(lock_path, owner='worker-b')
    with pytest.raises(daemon.DaemonLockError):
        daemon.release_lock(lock_path, owner='worker-b')

    assert daemon.release_lock(lock_path, owner='worker-a') is True
    assert daemon.release_lock(lock_path, owner='worker-a') is False


def test_lock_acquire_replaces_stale_lock(tmp_path):
    lock_path = tmp_path / 'daemon.lock'
    lock_path.write_text(json.dumps({
        'pid': 999999,
        'owner': 'stale-worker',
        'created_at': '2026-06-01T00:00:00+00:00',
        'updated_at': '2026-06-01T00:00:00+00:00',
    }), encoding='utf-8')

    lock = daemon.acquire_lock(lock_path, owner='fresh-worker', stale_after=0)

    assert lock['owner'] == 'fresh-worker'
    saved = json.loads(lock_path.read_text(encoding='utf-8'))
    assert saved['owner'] == 'fresh-worker'


def test_refresh_lock_updates_owner_timestamp(tmp_path):
    lock_path = tmp_path / 'daemon.lock'
    daemon.acquire_lock(lock_path, owner='worker-a')

    refreshed = daemon.refresh_lock(
        lock_path, owner='worker-a',
        now='2026-06-01T00:01:00+00:00')

    assert refreshed['owner'] == 'worker-a'
    assert refreshed['updated_at'] == '2026-06-01T00:01:00+00:00'
    saved = json.loads(lock_path.read_text(encoding='utf-8'))
    assert saved['updated_at'] == '2026-06-01T00:01:00+00:00'
    with pytest.raises(daemon.DaemonLockError):
        daemon.refresh_lock(lock_path, owner='worker-b')
