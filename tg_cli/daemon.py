import copy
import contextlib
import datetime as _dt
import json
import os
import threading
import uuid
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on non-Windows platforms.
    msvcrt = None


DEFAULT_QUEUE = {
    'version': 1,
    'tasks': [],
}

ACTIVE_TASK_STATUSES = ('pending', 'claimed', 'reply_pending', 'held_rate_limit')
CLAIM_FIELDS = ('claim_owner', 'claimed_at', 'claim_expires_at')
RATE_LIMIT_FIELDS = ('rate_limit_reason', 'retry_after')

_QUEUE_THREAD_LOCKS = {}
_QUEUE_THREAD_LOCKS_GUARD = threading.Lock()


class DaemonLockError(RuntimeError):
    pass


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _path(path):
    return Path(path).expanduser()


def _deepcopy_json(value):
    return copy.deepcopy(value)


def _iso_utc(value=None):
    if value is None:
        return utc_now()
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc).replace(
            microsecond=0).isoformat()
    return str(value)


def _parse_time(value):
    if value in (None, ''):
        return None
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)
    text = str(value)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _atomic_write_json(path, payload):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.{}.{}.tmp'.format(target.name, uuid.uuid4().hex))
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
    temp.replace(target)


def _queue_lock_path(path):
    target = _path(path)
    return target.with_name('{}.lock'.format(target.name))


def _queue_thread_lock(lock_path):
    key = str(_path(lock_path).resolve())
    with _QUEUE_THREAD_LOCKS_GUARD:
        lock = _QUEUE_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _QUEUE_THREAD_LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def _locked_queue(path):
    lock_path = _queue_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _queue_thread_lock(lock_path)
    with thread_lock:
        with lock_path.open('a+', encoding='utf-8') as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                raise DaemonLockError(
                    'Queue file locking is not supported on this platform.')
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _load_queue_unlocked(path):
    target = _path(path)
    if not target.is_file():
        return _deepcopy_json(DEFAULT_QUEUE)
    with target.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError('Queue file must contain a JSON object.')
    payload.setdefault('version', 1)
    payload.setdefault('tasks', [])
    if not isinstance(payload['tasks'], list):
        raise ValueError('Queue file tasks must be a list.')
    return payload


def load_queue(path):
    return _load_queue_unlocked(path)


def _save_queue_unlocked(path, payload):
    queue = _deepcopy_json(payload)
    if not isinstance(queue, dict):
        raise ValueError('Queue payload must be a JSON object.')
    queue.setdefault('version', 1)
    queue.setdefault('tasks', [])
    if not isinstance(queue['tasks'], list):
        raise ValueError('Queue payload tasks must be a list.')
    _atomic_write_json(path, queue)
    return queue


def save_queue(path, payload):
    with _locked_queue(path):
        return _save_queue_unlocked(path, payload)


def create_task(chat, messages, profile, persona, reply_policy, initiative,
                preset=None, kind='message', prompt=None, now=None):
    timestamp = _iso_utc(now)
    compact_ts = timestamp.replace(':', '').replace('+', '').replace('-', '')
    compact_ts = compact_ts.replace('.', '')
    return {
        'id': '{}-{}'.format(compact_ts, uuid.uuid4().hex[:12]),
        'status': 'pending',
        'kind': str(kind),
        'chat': _deepcopy_json(chat),
        'messages': _deepcopy_json(messages),
        'profile': _deepcopy_json(profile),
        'persona': _deepcopy_json(persona),
        'reply_policy': _deepcopy_json(reply_policy),
        'initiative': _deepcopy_json(initiative),
        'preset': preset,
        'created_at': timestamp,
        'updated_at': timestamp,
        'prompt': prompt,
    }


def _active_count(tasks):
    return sum(
        1 for task in tasks
        if task.get('status') in ACTIVE_TASK_STATUSES)


def append_task(path, task, max_pending=None):
    with _locked_queue(path):
        queue = _load_queue_unlocked(path)
        if max_pending is not None and _active_count(queue['tasks']) >= int(max_pending):
            return False
        queue['tasks'].append(_deepcopy_json(task))
        _save_queue_unlocked(path, queue)
        return True


def _is_expired(task, now_dt, task_ttl, timestamp_fields=('created_at',)):
    if task_ttl is None:
        return False
    ttl = float(task_ttl)
    if ttl < 0:
        return False
    started_at = None
    for field_name in timestamp_fields:
        started_at = _parse_time(task.get(field_name))
        if started_at is not None:
            break
    if started_at is None:
        return False
    return (now_dt - started_at).total_seconds() > ttl


def _clear_fields(task, field_names):
    for field_name in field_names:
        task.pop(field_name, None)


def _release_expired_claim(task, now_dt, now_text):
    if task.get('status') != 'claimed':
        return False
    expires_at = _parse_time(task.get('claim_expires_at'))
    if expires_at is None or expires_at > now_dt:
        return False
    task['status'] = 'pending'
    task['updated_at'] = now_text
    _clear_fields(task, CLAIM_FIELDS)
    return True


def _expire_pending_tasks(queue, now_dt, now_text, task_ttl):
    changed = False
    for task in queue['tasks']:
        if task.get('status') not in ('pending', 'claimed'):
            continue
        if _is_expired(task, now_dt, task_ttl):
            task['status'] = 'expired'
            task['updated_at'] = now_text
            _clear_fields(task, CLAIM_FIELDS)
            changed = True
            continue
        changed = _release_expired_claim(task, now_dt, now_text) or changed
    return changed


def _oldest_pending_task(queue, now_dt):
    oldest = None
    oldest_created_at = None
    for task in queue['tasks']:
        if task.get('status') != 'pending':
            continue
        created_at = _parse_time(task.get('created_at')) or now_dt
        if oldest is None or created_at < oldest_created_at:
            oldest = task
            oldest_created_at = created_at
    return oldest


def next_pending_task(path, now=None, task_ttl=None):
    with _locked_queue(path):
        queue = _load_queue_unlocked(path)
        now_text = _iso_utc(now)
        now_dt = _parse_time(now_text)
        changed = _expire_pending_tasks(queue, now_dt, now_text, task_ttl)
        oldest = _oldest_pending_task(queue, now_dt)

        if changed:
            _save_queue_unlocked(path, queue)
        return _deepcopy_json(oldest) if oldest is not None else None


def claim_next_task(path, now=None, task_ttl=None, claim_ttl=300, owner=None):
    with _locked_queue(path):
        queue = _load_queue_unlocked(path)
        now_text = _iso_utc(now)
        now_dt = _parse_time(now_text)
        changed = _expire_pending_tasks(queue, now_dt, now_text, task_ttl)
        oldest = _oldest_pending_task(queue, now_dt)
        if oldest is None:
            if changed:
                _save_queue_unlocked(path, queue)
            return None

        claim_ttl = max(0.0, float(claim_ttl or 0.0))
        expires_at = now_dt + _dt.timedelta(seconds=claim_ttl)
        oldest['status'] = 'claimed'
        oldest['updated_at'] = now_text
        oldest['claim_owner'] = owner or str(os.getpid())
        oldest['claimed_at'] = now_text
        oldest['claim_expires_at'] = _iso_utc(expires_at)
        _save_queue_unlocked(path, queue)
        return _deepcopy_json(oldest)


def _update_task(path, task_id, status, fields=None, now=None,
                 allowed_statuses=('pending',), clear_fields=()):
    with _locked_queue(path):
        queue = _load_queue_unlocked(path)
        now_text = _iso_utc(now)
        fields = fields or {}
        for task in queue['tasks']:
            if task.get('id') != task_id:
                continue
            if allowed_statuses is not None and task.get('status') not in allowed_statuses:
                return None
            task['status'] = status
            task['updated_at'] = now_text
            _clear_fields(task, clear_fields)
            task.update(fields)
            _save_queue_unlocked(path, queue)
            return _deepcopy_json(task)
        return None


def get_task(path, task_id):
    queue = load_queue(path)
    for task in queue['tasks']:
        if task.get('id') == task_id:
            return _deepcopy_json(task)
    return None


def complete_task(path, task_id, message_id=None, dry_run=False):
    fields = {
        'dry_run': bool(dry_run),
    }
    if message_id is not None:
        fields['message_id'] = message_id
    return _update_task(
        path, task_id, 'completed', fields=fields,
        allowed_statuses=('pending', 'claimed', 'reply_pending', 'held_rate_limit'),
        clear_fields=CLAIM_FIELDS + RATE_LIMIT_FIELDS)


def skip_task(path, task_id, reason='skipped'):
    return _update_task(
        path, task_id, 'skipped', fields={'reason': reason},
        allowed_statuses=('pending', 'claimed', 'reply_pending', 'held_rate_limit'),
        clear_fields=CLAIM_FIELDS + RATE_LIMIT_FIELDS)


def queue_reply_task(path, task_id, text, dry_run=False, now=None):
    now_text = _iso_utc(now)
    return _update_task(
        path, task_id, 'reply_pending',
        fields={
            'reply_text': str(text or '').strip(),
            'reply_dry_run': bool(dry_run),
            'reply_queued_at': now_text,
        },
        now=now_text,
        allowed_statuses=('pending', 'claimed'),
        clear_fields=CLAIM_FIELDS + RATE_LIMIT_FIELDS)


def hold_rate_limited_task(path, task_id, reason='rate_limit',
                           retry_after=None, now=None):
    retry_after_text = _iso_utc(retry_after) if retry_after is not None else None
    fields = {'rate_limit_reason': str(reason or 'rate_limit')}
    if retry_after_text is not None:
        fields['retry_after'] = retry_after_text
    return _update_task(
        path, task_id, 'held_rate_limit',
        fields=fields,
        now=now,
        allowed_statuses=('reply_pending',),
        clear_fields=CLAIM_FIELDS)


def _expire_or_release_reply_tasks(queue, now_dt, now_text, task_ttl):
    changed = False
    for task in queue['tasks']:
        status = task.get('status')
        if status not in ('reply_pending', 'held_rate_limit'):
            continue
        if _is_expired(
                task, now_dt, task_ttl,
                timestamp_fields=('reply_queued_at', 'updated_at', 'created_at')):
            task['status'] = 'expired'
            task['updated_at'] = now_text
            _clear_fields(task, CLAIM_FIELDS + RATE_LIMIT_FIELDS)
            changed = True
            continue
        if status != 'held_rate_limit':
            continue
        retry_after = _parse_time(task.get('retry_after'))
        if retry_after is not None and retry_after > now_dt:
            continue
        task['status'] = 'reply_pending'
        task['updated_at'] = now_text
        _clear_fields(task, RATE_LIMIT_FIELDS)
        changed = True
    return changed


def reply_pending_tasks(path, chat_id=None, now=None, task_ttl=None):
    with _locked_queue(path):
        queue = _load_queue_unlocked(path)
        now_text = _iso_utc(now)
        now_dt = _parse_time(now_text)
        changed = _expire_or_release_reply_tasks(
            queue, now_dt, now_text, task_ttl)
        tasks = []
        for task in queue['tasks']:
            if task.get('status') != 'reply_pending':
                continue
            if chat_id is not None:
                task_chat = task.get('chat') or {}
                if int(task_chat.get('id')) != int(chat_id):
                    continue
            tasks.append(_deepcopy_json(task))
        if changed:
            _save_queue_unlocked(path, queue)
    tasks.sort(key=lambda item: _parse_time(item.get('updated_at')) or _parse_time(utc_now()))
    return tasks


def queue_counts(path):
    queue = load_queue(path)
    counts = {}
    for task in queue['tasks']:
        status = task.get('status') or 'unknown'
        counts[status] = counts.get(status, 0) + 1
    return counts


def write_status(path, payload):
    if not isinstance(payload, dict):
        raise ValueError('Status payload must be a JSON object.')
    status = _deepcopy_json(payload)
    status.setdefault('updated_at', utc_now())
    _atomic_write_json(path, status)
    return status


def read_status(path):
    target = _path(path)
    if not target.is_file():
        return {}
    with target.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError('Status file must contain a JSON object.')
    return payload


def request_stop(path):
    status = read_status(path)
    status['stop_requested'] = True
    status['updated_at'] = utc_now()
    return write_status(path, status)


def clear_stop(path):
    status = read_status(path)
    status['stop_requested'] = False
    status['updated_at'] = utc_now()
    return write_status(path, status)


def stop_requested(path):
    return bool(read_status(path).get('stop_requested'))


def _lock_payload(owner=None, now=None):
    timestamp = _iso_utc(now)
    return {
        'pid': os.getpid(),
        'owner': owner or str(os.getpid()),
        'created_at': timestamp,
        'updated_at': timestamp,
    }


def _load_lock(path):
    target = _path(path)
    if not target.is_file():
        return None
    with target.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise DaemonLockError('Lock file must contain a JSON object.')
    return payload


def _lock_is_stale(payload, stale_after):
    if stale_after is None:
        return False
    stale_after = float(stale_after)
    if stale_after < 0:
        return False
    timestamp = payload.get('updated_at') or payload.get('created_at')
    parsed = _parse_time(timestamp)
    if parsed is None:
        return True
    now_dt = _parse_time(utc_now())
    return (now_dt - parsed).total_seconds() > stale_after


def acquire_lock(path, owner=None, stale_after=3600):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _lock_payload(owner=owner)

    while True:
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            existing = _load_lock(target)
            if existing is None:
                continue
            if existing is not None and _lock_is_stale(existing, stale_after):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise DaemonLockError(
                'Daemon lock is already held by owner={} pid={}.'.format(
                    existing.get('owner'), existing.get('pid'))) from exc
        else:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2,
                          sort_keys=True)
                handle.write('\n')
            return payload


def refresh_lock(path, owner=None, now=None):
    target = _path(path)
    if not target.is_file():
        raise DaemonLockError('Daemon lock does not exist.')
    payload = _load_lock(target)
    if owner is not None and payload.get('owner') != owner:
        raise DaemonLockError(
            'Daemon lock is held by owner={}, not {}.'.format(
                payload.get('owner'), owner))
    payload['updated_at'] = _iso_utc(now)
    _atomic_write_json(target, payload)
    return payload


def release_lock(path, owner=None):
    target = _path(path)
    if not target.is_file():
        return False
    payload = _load_lock(target)
    if owner is not None and payload.get('owner') != owner:
        raise DaemonLockError(
            'Daemon lock is held by owner={}, not {}.'.format(
                payload.get('owner'), owner))
    target.unlink()
    return True
