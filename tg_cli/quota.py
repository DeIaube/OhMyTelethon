import copy
import contextlib
import datetime as _dt
import json
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


DEFAULT_STATE = {
    'version': 1,
    'run_id': None,
    'status': 'empty',
    'created_at': None,
    'updated_at': None,
    'preset': None,
    'targets': [],
    'tasks': [],
}

ACTIVE_RUN_STATUS = 'active'
DONE_RUN_STATUS = 'done'
STOPPED_RUN_STATUS = 'stopped'
ACTIVE_TARGET_STATUS = 'active'
DONE_TARGET_STATUS = 'done'
PENDING_TASK_STATUS = 'pending'
SENDING_TASK_STATUS = 'sending'

_STATE_THREAD_LOCKS = {}
_STATE_THREAD_LOCKS_GUARD = threading.Lock()


class QuotaStateError(RuntimeError):
    pass


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(
        microsecond=0).isoformat()


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


def _compact_timestamp(value):
    parsed = _parse_time(value) or _parse_time(utc_now())
    return parsed.strftime('%Y%m%dT%H%M%SZ')


def _atomic_write_json(path, payload):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.{}.{}.tmp'.format(target.name, uuid.uuid4().hex))
    try:
        with temp.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2,
                      sort_keys=True)
            handle.write('\n')
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


def _state_lock_path(path):
    target = _path(path)
    return target.with_name('{}.lock'.format(target.name))


def _state_thread_lock(lock_path):
    key = str(_path(lock_path).resolve())
    with _STATE_THREAD_LOCKS_GUARD:
        lock = _STATE_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _STATE_THREAD_LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def _locked_state(path):
    lock_path = _state_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _state_thread_lock(lock_path)
    with thread_lock:
        with lock_path.open('a+', encoding='utf-8') as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                raise QuotaStateError(
                    'Quota state file locking is not supported on this platform.')
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _normalize_state(payload):
    if not isinstance(payload, dict):
        raise ValueError('Quota state file must contain a JSON object.')
    state = _deepcopy_json(payload)
    state.setdefault('version', 1)
    state.setdefault('run_id', None)
    state.setdefault('status', 'empty')
    state.setdefault('created_at', None)
    state.setdefault('updated_at', None)
    state.setdefault('preset', None)
    state.setdefault('targets', [])
    state.setdefault('tasks', [])
    if not isinstance(state['targets'], list):
        raise ValueError('Quota state targets must be a list.')
    if not isinstance(state['tasks'], list):
        raise ValueError('Quota state tasks must be a list.')
    return state


def _load_state_unlocked(path):
    target = _path(path)
    if not target.is_file():
        return _deepcopy_json(DEFAULT_STATE)
    with target.open('r', encoding='utf-8') as handle:
        return _normalize_state(json.load(handle))


def load_state(path):
    return _load_state_unlocked(path)


def _save_state_unlocked(path, payload):
    state = _normalize_state(payload)
    _atomic_write_json(path, state)
    return _deepcopy_json(state)


def save_state(path, payload):
    with _locked_state(path):
        return _save_state_unlocked(path, payload)


def _target_from_item(item):
    if isinstance(item, str):
        if ':' not in item:
            raise ValueError(
                'Quota target strings must use CHAT_ID:COUNT format.')
        chat_id, target_count = item.split(':', 1)
        return chat_id, target_count
    if isinstance(item, dict):
        return item.get('chat_id'), item.get(
            'target_count', item.get('count'))
    try:
        chat_id, target_count = item
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'Quota targets must be dicts, pairs, or CHAT_ID:COUNT strings.'
        ) from exc
    return chat_id, target_count


def _coerce_int(value, label):
    if isinstance(value, bool):
        raise ValueError('{} must be an integer.'.format(label))
    if isinstance(value, float) and not value.is_integer():
        raise ValueError('{} must be an integer.'.format(label))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('{} must be an integer.'.format(label)) from exc


def _normalize_targets(targets):
    if isinstance(targets, dict):
        items = [
            {'chat_id': chat_id, 'target_count': target_count}
            for chat_id, target_count in targets.items()
        ]
    else:
        items = list(targets or [])
    if not items:
        raise ValueError('At least one quota target is required.')

    normalized = []
    seen_chat_ids = set()
    for item in items:
        chat_id, target_count = _target_from_item(item)
        chat_id = _coerce_int(chat_id, 'Quota target chat ids')
        target_count = _coerce_int(target_count, 'Quota target counts')
        if target_count <= 0:
            raise ValueError('Quota target counts must be positive.')
        if chat_id in seen_chat_ids:
            raise ValueError('Quota targets must not contain duplicate chat ids.')
        seen_chat_ids.add(chat_id)
        normalized.append({
            'chat_id': chat_id,
            'target_count': target_count,
            'sent_count': 0,
            'status': ACTIVE_TARGET_STATUS,
            'last_sent_at': None,
            'message_ids': [],
        })
    return normalized


def create_run(path, targets, preset=None, now=None):
    timestamp = _iso_utc(now)
    state = {
        'version': 1,
        'run_id': 'quota-{}'.format(_compact_timestamp(timestamp)),
        'status': ACTIVE_RUN_STATUS,
        'created_at': timestamp,
        'updated_at': timestamp,
        'preset': preset,
        'targets': _normalize_targets(targets),
        'tasks': [],
    }
    return save_state(path, state)


def get_status(path):
    return load_state(path)


def status(path):
    return get_status(path)


def _find_target(state, chat_id):
    chat_id = int(chat_id)
    for target in state['targets']:
        if int(target.get('chat_id')) == chat_id:
            return target
    return None


def _target_remaining(target):
    return max(0, int(target.get('target_count', 0)) -
               int(target.get('sent_count', 0)))


def _refresh_completion(state, now_text):
    changed = False
    for target in state['targets']:
        if target.get('status') == DONE_TARGET_STATUS:
            continue
        if _target_remaining(target) <= 0:
            target['status'] = DONE_TARGET_STATUS
            target['completed_at'] = now_text
            changed = True
    if (state.get('status') == ACTIVE_RUN_STATUS and state['targets'] and
            all(target.get('status') == DONE_TARGET_STATUS
                for target in state['targets'])):
        state['status'] = DONE_RUN_STATUS
        state['completed_at'] = now_text
        changed = True
    if changed:
        state['updated_at'] = now_text
    return changed


def stop_run(path, now=None):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        if state.get('status') == ACTIVE_RUN_STATUS:
            timestamp = _iso_utc(now)
            state['status'] = STOPPED_RUN_STATUS
            state['updated_at'] = timestamp
            state['stopped_at'] = timestamp
            _save_state_unlocked(path, state)
        return _deepcopy_json(state)


def next_target(path):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        now_text = utc_now()
        changed = _refresh_completion(state, now_text)
        selected = None
        if state.get('status') == ACTIVE_RUN_STATUS:
            for target in state['targets']:
                if (target.get('status') == ACTIVE_TARGET_STATUS and
                        _target_remaining(target) > 0):
                    selected = target
                    break
        if changed:
            _save_state_unlocked(path, state)
        return _deepcopy_json(selected) if selected is not None else None


def create_task(path, chat_id, context=None, now=None):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        timestamp = _iso_utc(now)
        _refresh_completion(state, timestamp)
        target = _find_target(state, chat_id)
        if (state.get('status') != ACTIVE_RUN_STATUS or target is None or
                target.get('status') != ACTIVE_TARGET_STATUS or
                _target_remaining(target) <= 0):
            _save_state_unlocked(path, state)
            return None
        for existing in state['tasks']:
            if (int(existing.get('chat_id') or 0) == int(chat_id) and
                    existing.get('status') in (
                        PENDING_TASK_STATUS, SENDING_TASK_STATUS)):
                return _deepcopy_json(existing)
        task = {
            'id': 'quota-task-{}-{}'.format(
                _compact_timestamp(timestamp), uuid.uuid4().hex[:12]),
            'status': PENDING_TASK_STATUS,
            'chat_id': int(chat_id),
            'context': _deepcopy_json(context),
            'created_at': timestamp,
            'updated_at': timestamp,
        }
        state['tasks'].append(task)
        state['updated_at'] = timestamp
        _save_state_unlocked(path, state)
        return _deepcopy_json(task)


def get_task(path, task_id):
    state = load_state(path)
    for task in state['tasks']:
        if task.get('id') == task_id:
            return _deepcopy_json(task)
    return None


def _normalize_message_ids(message_ids):
    if message_ids is None:
        return []
    if isinstance(message_ids, (str, bytes)):
        return [int(message_ids)]
    try:
        return [int(item) for item in message_ids]
    except TypeError:
        return [int(message_ids)]


def begin_task(path, task_id, expected_message_count=1, now=None):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        if state.get('status') != ACTIVE_RUN_STATUS:
            return None
        timestamp = _iso_utc(now)
        expected_message_count = _coerce_int(
            expected_message_count, 'Quota expected message count')
        if expected_message_count < 1:
            raise ValueError('Quota expected message count must be positive.')
        for task in state['tasks']:
            if task.get('id') != task_id:
                continue
            if task.get('status') != PENDING_TASK_STATUS:
                return None
            target = _find_target(state, task.get('chat_id'))
            if (target is None or
                    target.get('status') != ACTIVE_TARGET_STATUS or
                    _target_remaining(target) < expected_message_count):
                return None
            task['status'] = SENDING_TASK_STATUS
            task['updated_at'] = timestamp
            task['sending_started_at'] = timestamp
            task['expected_message_count'] = expected_message_count
            state['updated_at'] = timestamp
            _save_state_unlocked(path, state)
            return _deepcopy_json(task)
        return None


def complete_task(path, task_id, message_ids=None, dry_run=False, now=None):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        timestamp = _iso_utc(now)
        message_ids = _normalize_message_ids(message_ids)
        for task in state['tasks']:
            if task.get('id') != task_id:
                continue
            if task.get('status') not in (
                    PENDING_TASK_STATUS, SENDING_TASK_STATUS):
                return None
            target = _find_target(state, task.get('chat_id'))
            if target is None:
                return None
            if dry_run:
                checked = _deepcopy_json(task)
                checked['dry_run'] = True
                checked['dry_run_checked_at'] = timestamp
                checked['message_ids'] = message_ids
                checked['sent_count_delta'] = 0
                return checked
            if (state.get('status') != ACTIVE_RUN_STATUS and
                    task.get('status') != SENDING_TASK_STATUS):
                return None
            count_delta = len(message_ids)
            if count_delta < 1:
                return None
            if _target_remaining(target) < count_delta:
                return None
            task['status'] = 'completed'
            task['updated_at'] = timestamp
            task['completed_at'] = timestamp
            task['dry_run'] = False
            task['message_ids'] = message_ids
            task['sent_count_delta'] = count_delta
            target['sent_count'] = int(target.get('sent_count', 0)) + count_delta
            target['message_ids'] = list(target.get('message_ids') or [])
            target['message_ids'].extend(message_ids)
            target['last_sent_at'] = timestamp
            _refresh_completion(state, timestamp)
            state['updated_at'] = timestamp
            _save_state_unlocked(path, state)
            return _deepcopy_json(task)
        return None


def skip_task(path, task_id, reason='skipped', now=None):
    with _locked_state(path):
        state = _load_state_unlocked(path)
        timestamp = _iso_utc(now)
        for task in state['tasks']:
            if task.get('id') != task_id:
                continue
            if task.get('status') != PENDING_TASK_STATUS:
                return None
            task['status'] = 'skipped'
            task['updated_at'] = timestamp
            task['skipped_at'] = timestamp
            task['reason'] = str(reason or 'skipped')
            state['updated_at'] = timestamp
            _save_state_unlocked(path, state)
            return _deepcopy_json(task)
        return None
