import datetime as _dt
import hashlib
import json
import uuid
from pathlib import Path


BAD_CASE_REASON_RULES = {
    'self_context_wait': {
        'case_type': 'self_flood',
        'lesson': (
            'Wait for a newer human message before opening another topic; '
            'do not keep starting topics after your own tail messages.'),
    },
    'stale_context': {
        'case_type': 'stale_context',
        'lesson': (
            'Do not reply to a stale prompt after newer inbound activity; '
            're-read the latest tail first.'),
    },
    'duplicate_reply_context': {
        'case_type': 'stale_context',
        'lesson': (
            'Avoid answering the same context twice; wait for a new human turn '
            'or pick a clearly new opening.'),
    },
    'min_reply_chars': {
        'case_type': 'too_short',
        'lesson': (
            'Every outgoing message part must carry at least the configured '
            'minimum non-space characters.'),
    },
    'max_replies': {
        'case_type': 'over_split',
        'lesson': (
            'Do not split or queue more message parts than the remaining bounded '
            'run allows.'),
    },
    'forbidden_terms': {
        'case_type': 'unsafe_engage',
        'lesson': (
            'Do not send text that matches forbidden or sensitive profile terms; '
            'skip or pivot.'),
    },
    'anti_spam_signal': {
        'case_type': 'safety_skip',
        'lesson': (
            'Treat anti-spam or flood-control signals as skip/pivot context, '
            'not as a topic to engage.'),
    },
    'direct_moderation_warning': {
        'case_type': 'moderation_scope',
        'lesson': (
            'If moderation clearly names the logged-in account, stop or cool '
            'down instead of continuing normally.'),
    },
    'ambient_moderation_warning': {
        'case_type': 'moderation_scope',
        'lesson': (
            'If moderation is aimed at another user, skip or pivot away; do not '
            'treat it as a direct account warning.'),
    },
    'ai_challenge': {
        'case_type': 'ai_tone',
        'lesson': (
            'Do not answer AI/robot accusations directly; reduce polished or '
            'explanatory tone in the next natural opening.'),
    },
    'adult_service': {
        'case_type': 'unsafe_engage',
        'lesson': (
            'Do not engage real adult-service solicitation; skip direct reply '
            'or pivot to a safe adjacent topic.'),
    },
    'grey_area': {
        'case_type': 'unsafe_engage',
        'lesson': (
            'Do not engage actual account, black-market, ad, or grey-area '
            'content; skip or pivot.'),
    },
    'nonconsensual_recording': {
        'case_type': 'unsafe_engage',
        'lesson': (
            'Do not engage non-consensual recording content; skip the task.'),
    },
    'minor_or_age_risk': {
        'case_type': 'unsafe_engage',
        'lesson': (
            'Do not engage minor or age-risk content; skip the task.'),
    },
    'hourly_limit': {
        'case_type': 'over_frequency',
        'lesson': (
            'Respect hourly pacing; do not keep trying to send when the chat '
            'has reached its local rate cap.'),
    },
}


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(
        microsecond=0).isoformat()


def _config(config):
    return getattr(config, 'bad_cases', {}) or {}


def _enabled(config):
    return bool(_config(config).get('enabled', True))


def _path(config):
    value = _config(config).get('path')
    if value in (None, ''):
        return None
    return Path(value).expanduser()


def _max_records(config):
    return max(1, int(_config(config).get('max_records') or 1000))


def _sha(text):
    return hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()[:16]


def _text_len(text):
    return len(str(text or ''))


def _chat_id(chat=None, chat_id=None):
    if chat_id not in (None, ''):
        return int(chat_id)
    if isinstance(chat, dict) and chat.get('id') not in (None, ''):
        return int(chat.get('id'))
    return None


def _message_fingerprint(item):
    item = item or {}
    text = str(item.get('text') or '')
    sender = item.get('sender_id')
    if sender in (None, ''):
        sender = item.get('sender')
    return {
        'id': item.get('id'),
        'out': bool(item.get('out')),
        'sender_hash': _sha(sender),
        'text_hash': _sha(text),
        'text_len': _text_len(text),
    }


def _message_fingerprints(messages, max_messages=6):
    items = list(messages or [])[-int(max_messages or 6):]
    return [_message_fingerprint(item) for item in items]


def _reply_fingerprint(reply):
    if reply in (None, ''):
        return None
    return {
        'text_hash': _sha(reply),
        'text_len': _text_len(reply),
    }


def _reason_rule(reason, case_type=None, lesson=None):
    if case_type:
        return {
            'case_type': str(case_type),
            'lesson': str(lesson or ''),
        }
    rule = BAD_CASE_REASON_RULES.get(str(reason or ''))
    if not rule:
        return None
    return dict(rule)


def _load_records(path):
    target = Path(path)
    if not target.is_file():
        return []
    records = []
    with target.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
    return records


def _write_records(path, records):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.{}.{}.tmp'.format(target.name, uuid.uuid4().hex))
    with temp.open('w', encoding='utf-8') as handle:
        for item in records:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True))
            handle.write('\n')
    temp.replace(target)


def append_bad_case(config, record):
    path = _path(config)
    if not _enabled(config) or path is None:
        return None
    records = _load_records(path)
    records.append(dict(record))
    records = records[-_max_records(config):]
    _write_records(path, records)
    return dict(record)


def record_bad_case(config, source, reason, chat=None, chat_id=None,
                    preset=None, task_id=None, action=None, messages=None,
                    reply=None, metadata=None, case_type=None, lesson=None,
                    severity='medium'):
    if not _enabled(config):
        return None
    rule = _reason_rule(reason, case_type=case_type, lesson=lesson)
    if rule is None:
        return None
    resolved_chat_id = _chat_id(chat=chat, chat_id=chat_id)
    record = {
        'version': 1,
        'id': '{}-{}'.format(
            utc_now().replace(':', '').replace('-', ''), uuid.uuid4().hex[:10]),
        'created_at': utc_now(),
        'case_type': rule['case_type'],
        'source': str(source or 'unknown'),
        'reason': str(reason or ''),
        'lesson': rule.get('lesson') or '',
        'severity': str(severity or 'medium'),
        'chat_id': resolved_chat_id,
        'preset': preset or None,
        'task_id': task_id or None,
        'action': action or None,
        'messages': _message_fingerprints(messages),
        'reply': _reply_fingerprint(reply),
        'metadata': dict(metadata or {}),
    }
    return append_bad_case(config, record)


def list_bad_cases(config, chat_id=None, case_type=None, reason=None, limit=20):
    path = _path(config)
    if path is None:
        return []
    records = list(reversed(_load_records(path)))
    if chat_id not in (None, ''):
        chat_id = int(chat_id)
        records = [item for item in records if item.get('chat_id') == chat_id]
    if case_type not in (None, ''):
        records = [
            item for item in records
            if item.get('case_type') == str(case_type)
        ]
    if reason not in (None, ''):
        records = [
            item for item in records
            if item.get('reason') == str(reason)
        ]
    if limit is not None:
        records = records[:max(0, int(limit))]
    return records


def recent_bad_case_guidance(config, chat_id=None, limit=None):
    config_values = _config(config)
    if limit is None:
        limit = config_values.get('max_task_bad_cases', 3)
    records = list_bad_cases(config, chat_id=chat_id, limit=limit)
    guidance = []
    for item in records:
        guidance.append({
            'case_type': item.get('case_type') or 'bad_case',
            'reason': item.get('reason') or '',
            'source': item.get('source') or '',
            'lesson': item.get('lesson') or '',
        })
    return guidance


def dumps_jsonl(records):
    return '\n'.join(
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in records)
