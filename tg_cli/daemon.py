import copy
import datetime as _dt
import json
import os
import uuid
from pathlib import Path


DEFAULT_QUEUE = {
    'version': 1,
    'tasks': [],
}


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


def load_queue(path):
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


def save_queue(path, payload):
    queue = _deepcopy_json(payload)
    if not isinstance(queue, dict):
        raise ValueError('Queue payload must be a JSON object.')
    queue.setdefault('version', 1)
    queue.setdefault('tasks', [])
    if not isinstance(queue['tasks'], list):
        raise ValueError('Queue payload tasks must be a list.')
    _atomic_write_json(path, queue)
    return queue


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


def _pending_count(tasks):
    return sum(1 for task in tasks if task.get('status') == 'pending')


def append_task(path, task, max_pending=None):
    queue = load_queue(path)
    if max_pending is not None and _pending_count(queue['tasks']) >= int(max_pending):
        return False
    queue['tasks'].append(_deepcopy_json(task))
    save_queue(path, queue)
    return True


def _is_expired(task, now_dt, task_ttl):
    if task_ttl is None:
        return False
    ttl = float(task_ttl)
    if ttl < 0:
        return False
    created_at = _parse_time(task.get('created_at'))
    if created_at is None:
        return False
    return (now_dt - created_at).total_seconds() > ttl


def next_pending_task(path, now=None, task_ttl=None):
    queue = load_queue(path)
    now_text = _iso_utc(now)
    now_dt = _parse_time(now_text)
    changed = False
    oldest = None
    oldest_created_at = None

    for task in queue['tasks']:
        if task.get('status') != 'pending':
            continue
        if _is_expired(task, now_dt, task_ttl):
            task['status'] = 'expired'
            task['updated_at'] = now_text
            changed = True
            continue
        created_at = _parse_time(task.get('created_at')) or now_dt
        if oldest is None or created_at < oldest_created_at:
            oldest = task
            oldest_created_at = created_at

    if changed:
        save_queue(path, queue)
    return _deepcopy_json(oldest) if oldest is not None else None


def _update_task(path, task_id, status, fields=None, now=None,
                 allowed_statuses=('pending',)):
    queue = load_queue(path)
    now_text = _iso_utc(now)
    fields = fields or {}
    for task in queue['tasks']:
        if task.get('id') != task_id:
            continue
        if allowed_statuses is not None and task.get('status') not in allowed_statuses:
            return None
        task['status'] = status
        task['updated_at'] = now_text
        task.update(fields)
        save_queue(path, queue)
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
        allowed_statuses=('pending', 'reply_pending'))


def skip_task(path, task_id, reason='skipped'):
    return _update_task(
        path, task_id, 'skipped', fields={'reason': reason},
        allowed_statuses=('pending', 'reply_pending'))


def queue_reply_task(path, task_id, text, dry_run=False):
    return _update_task(
        path, task_id, 'reply_pending',
        fields={
            'reply_text': str(text or '').strip(),
            'reply_dry_run': bool(dry_run),
        },
        allowed_statuses=('pending',))


def reply_pending_tasks(path, chat_id=None):
    queue = load_queue(path)
    tasks = []
    for task in queue['tasks']:
        if task.get('status') != 'reply_pending':
            continue
        if chat_id is not None:
            task_chat = task.get('chat') or {}
            if int(task_chat.get('id')) != int(chat_id):
                continue
        tasks.append(_deepcopy_json(task))
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
