import asyncio
import copy
import collections
import datetime as _dt
import json
import os
import random
import re
import string

from telethon import TelegramClient, events, utils
from telethon.tl.types import Channel, Chat, User

from .config import normalize_chat_id
from . import daemon as daemon_store
from . import safety


class TelegramCliError(RuntimeError):
    pass


def _client(config):
    return TelegramClient(str(config.session_path), config.api_id, config.api_hash)


def _entity_kind(entity):
    if isinstance(entity, Channel):
        if getattr(entity, 'megagroup', False):
            return 'supergroup'
        if getattr(entity, 'broadcast', False):
            return 'channel'
        return 'channel'
    if isinstance(entity, Chat):
        return 'chat'
    if isinstance(entity, User):
        return 'bot' if getattr(entity, 'bot', False) else 'user'
    return entity.__class__.__name__.lower()


def _dialog_row(dialog):
    entity = dialog.entity
    username = getattr(entity, 'username', None)
    return {
        'id': getattr(entity, 'id', None),
        'title': dialog.name,
        'kind': _entity_kind(entity),
        'username': username,
        'participants_count': getattr(entity, 'participants_count', None),
    }


def _format_ts(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.isoformat()


_ENGLISH_STOP_WORDS = {
    'the', 'and', 'for', 'you', 'are', 'with', 'that', 'this', 'have', 'from',
    'just', 'not', 'but', 'all', 'can', 'will', 'was', 'were', 'has', 'had',
    'they', 'them', 'his', 'her', 'she', 'him', 'our', 'out', 'about', 'what',
    'when', 'where', 'why', 'how', 'your', 'into', 'then', 'than', 'too',
    'joined', 'left', 'group', 'channel', 'message',
}

_CHINESE_STOP_CHARS = set('的了呢啊呀吧吗么哦嗯哈我你他她它们这那个一是不在有就都和也还先')
_QUESTION_RE = re.compile(r'[?？]|(吗|嘛|么|呢|谁|啥|什么|怎么|怎样|如何|哪|几|是否|有没有)')
_URL_RE = re.compile(r'https?://\S+|www\.\S+')
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")
_CHINESE_TEXT_RE = re.compile(r'[\u4e00-\u9fff]{2,}')
_NOTICE_PHRASES = (
    'joined the group',
    'left the group',
    'pinned a message',
    'changed the group',
    'created the group',
    'removed',
    '加入了群',
    '加入群',
    '退出了群',
    '离开了群',
    '置顶',
    '群公告',
    '撤回了一条消息',
)


def _emit(output_func, text=''):
    try:
        output_func(text, flush=True)
    except TypeError:
        output_func(text)


def _remember_inbound_message(seen_ids, message_id):
    if message_id in seen_ids:
        return False
    seen_ids.add(message_id)
    return True


def _clean_context_text(text):
    text = _URL_RE.sub(' ', str(text or ''))
    return text.strip()


def _is_question_text(text):
    return bool(_QUESTION_RE.search(str(text or '')))


def _is_bot_or_notice_message(item):
    text = str((item or {}).get('text') or '')
    sender = str((item or {}).get('sender') or '')
    sender_lower = sender.casefold()
    text_lower = text.casefold()
    if 'bot' in sender_lower:
        return True
    return any(phrase in text_lower for phrase in _NOTICE_PHRASES)


def _context_message_excerpt(item, max_chars=120):
    text = str((item or {}).get('text') or '').strip()
    max_chars = int(max_chars)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + '...'
    return {
        'id': (item or {}).get('id'),
        'date': (item or {}).get('date'),
        'sender_id': (item or {}).get('sender_id'),
        'sender': (item or {}).get('sender'),
        'out': bool((item or {}).get('out')),
        'text': text,
    }


def _context_keywords(messages, max_keywords=10):
    counts = collections.Counter()
    last_seen = {}
    for index, item in enumerate(messages or []):
        if _is_bot_or_notice_message(item):
            continue
        text = _clean_context_text((item or {}).get('text'))
        if not text:
            continue

        for match in _ENGLISH_WORD_RE.findall(text):
            token = match.casefold().strip("_'-")
            if len(token) < 3 or token in _ENGLISH_STOP_WORDS:
                continue
            counts[token] += 1
            last_seen[token] = index

        for chunk in _CHINESE_TEXT_RE.findall(text):
            if 2 <= len(chunk) <= 6 and not any(ch in _CHINESE_STOP_CHARS for ch in chunk):
                counts[chunk] += 1
                last_seen[chunk] = index
            if len(chunk) >= 3:
                for start in range(0, len(chunk) - 1):
                    token = chunk[start:start + 2]
                    if any(ch in _CHINESE_STOP_CHARS for ch in token):
                        continue
                    counts[token] += 1
                    last_seen[token] = index

    ranked = sorted(
        counts,
        key=lambda token: (-counts[token], -last_seen.get(token, -1), token))
    return [
        {'text': token, 'count': counts[token]}
        for token in ranked[:int(max_keywords)]
    ]


def _context_active_speakers(messages, max_speakers=8):
    counts = {}
    order = {}
    for index, item in enumerate(messages or []):
        if _is_bot_or_notice_message(item):
            continue
        sender = (item or {}).get('sender') or 'unknown'
        sender_id = (item or {}).get('sender_id')
        key = (sender_id, sender)
        counts[key] = counts.get(key, 0) + 1
        order[key] = index

    ranked = sorted(
        counts,
        key=lambda key: (-counts[key], -order.get(key, -1), str(key[1])))
    return [
        {
            'sender': key[1],
            'sender_id': key[0],
            'count': counts[key],
        }
        for key in ranked[:int(max_speakers)]
    ]


def _context_recent_questions(messages, max_questions=5):
    questions = []
    for item in messages or []:
        if _is_bot_or_notice_message(item):
            continue
        if _is_question_text((item or {}).get('text')):
            questions.append(_context_message_excerpt(item))
    return questions[-int(max_questions):]


def _context_notices(messages, max_messages=5):
    notices = [
        _context_message_excerpt(item)
        for item in (messages or [])
        if _is_bot_or_notice_message(item)
    ]
    return {
        'count': len(notices),
        'messages': notices[-int(max_messages):],
    }


def _context_summary_sentence(message_count, active_speakers, keywords,
                              recent_questions, notice_count):
    speaker_text = ', '.join(
        '{}({})'.format(item['sender'], item['count'])
        for item in active_speakers[:5])
    keyword_text = ', '.join(item['text'] for item in keywords[:6])
    parts = ['最近 {} 条消息'.format(int(message_count))]
    parts.append('活跃发言者: {}'.format(speaker_text or 'none'))
    parts.append('高频话题: {}'.format(keyword_text or 'none'))
    if recent_questions:
        latest = recent_questions[-1]
        parts.append('最近问题: [{}] {}: {}'.format(
            latest.get('id'), latest.get('sender'), latest.get('text')))
    else:
        parts.append('最近问题: none')
    parts.append('机器人/通知类消息: {} 条'.format(int(notice_count)))
    return '；'.join(parts) + '。'


def _context_guidance(profile, reply_policy, initiative, recent_questions):
    max_chars = (profile or {}).get('max_chars')
    guidance = [
        'Use summary and recent_topics for warmup; use messages_tail for exact latest wording.',
        'Only reply when the latest tail or recent_questions gives a natural opening; otherwise skip.',
    ]
    if max_chars:
        guidance.append(
            'Keep any proposed reply short, preferably within profile.max_chars={}.'.format(
                max_chars))
    skip_when = (reply_policy or {}).get('skip_when') or []
    if skip_when:
        guidance.append('Skip when context matches: {}.'.format(
            _format_named_list(skip_when)))
    if initiative and initiative.get('enabled'):
        guidance.append(
            'Initiative is enabled but remains bounded by idle/cooldown/risk guidance.')
    if recent_questions:
        guidance.append('Recent questions may be the best entry point if still relevant.')
    return guidance


def summarize_group_context(config, row, messages, operator='agent', preset=None,
                            tail_limit=12):
    messages = list(messages or [])
    profile = dict(getattr(config, 'profile', {}) or {})
    persona = dict(getattr(config, 'persona', {}) or {})
    reply_policy = dict(getattr(config, 'reply_policy', {}) or {})
    initiative = dict(getattr(config, 'initiative', {}) or {})
    operator = (operator or 'agent').strip() or 'agent'
    tail_limit = max(0, int(tail_limit))

    active_speakers = _context_active_speakers(messages)
    keywords = _context_keywords(messages)
    recent_questions = _context_recent_questions(messages)
    bot_or_notice_messages = _context_notices(messages)
    recent_topics = [item['text'] for item in keywords[:6]]
    messages_tail = [
        _context_message_excerpt(item, max_chars=200)
        for item in messages[-tail_limit:]
    ] if tail_limit else []
    summary = _context_summary_sentence(
        len(messages), active_speakers, keywords, recent_questions,
        bot_or_notice_messages['count'])

    return {
        'chat': copy.deepcopy(row),
        'operator': operator,
        'preset': preset or None,
        'profile': profile,
        'persona': persona,
        'reply_policy': reply_policy,
        'initiative': initiative,
        'message_count': len(messages),
        'active_speakers': active_speakers,
        'recent_topics': recent_topics,
        'keywords': keywords,
        'bot_or_notice_messages': bot_or_notice_messages,
        'recent_questions': recent_questions,
        'summary': summary,
        'guidance': _context_guidance(
            profile, reply_policy, initiative, recent_questions),
        'messages_tail': messages_tail,
    }


def _task_context_summary(context):
    if not context:
        return None
    notices = context.get('bot_or_notice_messages') or {}
    return {
        'message_count': context.get('message_count', 0),
        'active_speakers': copy.deepcopy(context.get('active_speakers') or []),
        'recent_topics': list(context.get('recent_topics') or []),
        'keywords': copy.deepcopy(context.get('keywords') or []),
        'bot_or_notice_count': int(notices.get('count') or 0),
        'recent_questions': copy.deepcopy(context.get('recent_questions') or []),
        'summary': context.get('summary') or '',
        'guidance': list(context.get('guidance') or []),
    }


def _format_profile_guidance(profile):
    profile = profile or {}
    parts = [
        'language={}'.format(profile.get('language')),
        'style={}'.format(profile.get('style')),
        'max_chars={}'.format(profile.get('max_chars')),
        'emoji_level={}'.format(profile.get('emoji_level')),
    ]
    avoid_topics = profile.get('avoid_topics') or []
    forbidden_terms = profile.get('forbidden_terms') or []
    if avoid_topics:
        parts.append('avoid_topics={}'.format(', '.join(avoid_topics)))
    if forbidden_terms:
        parts.append('forbidden_terms={}'.format(', '.join(forbidden_terms)))
    if profile.get('reply_policy'):
        parts.append('reply_policy={}'.format(profile.get('reply_policy')))
    return '; '.join(parts)


def _format_named_list(values):
    values = [str(value) for value in (values or []) if value not in (None, '')]
    return ', '.join(values) if values else 'none'


def _format_persona_guidance(persona):
    persona = persona or {}
    if not persona:
        return 'persona=default'
    parts = []
    for key in ('identity', 'style'):
        if persona.get(key):
            parts.append('{}={}'.format(key, persona.get(key)))
    for key in ('traits', 'catchphrases', 'avoid', 'style_notes'):
        if persona.get(key):
            parts.append('{}={}'.format(key, _format_named_list(persona.get(key))))
    return '; '.join(parts) if parts else 'persona=default'


def _format_reply_policy_guidance(reply_policy):
    reply_policy = reply_policy or {}
    if not reply_policy:
        return 'reply_policy=default'
    parts = []
    for key in ('group_type', 'reply_threshold', 'mode'):
        if key in reply_policy and reply_policy.get(key) not in (None, ''):
            parts.append('{}={}'.format(key, reply_policy.get(key)))
    for key in ('prefer_reply_when', 'skip_when'):
        if reply_policy.get(key):
            parts.append('{}={}'.format(key, _format_named_list(reply_policy.get(key))))
    style_rules = reply_policy.get('style_rules') or {}
    if style_rules:
        parts.append('style_rules={}'.format(
            json.dumps(style_rules, ensure_ascii=False, sort_keys=True)))
    conversation_rules = reply_policy.get('conversation_rules') or {}
    if conversation_rules:
        parts.append('conversation_rules={}'.format(
            json.dumps(conversation_rules, ensure_ascii=False, sort_keys=True)))
    return '; '.join(parts) if parts else 'reply_policy=default'


def _format_initiative_guidance(initiative):
    initiative = initiative or {}
    if not initiative:
        return 'initiative=disabled'
    parts = [
        'enabled={}'.format(bool(initiative.get('enabled'))),
        'group_type={}'.format(initiative.get('group_type')),
        'style={}'.format(initiative.get('style')),
        'idle_after={}'.format(initiative.get('idle_after')),
        'cooldown={}'.format(initiative.get('cooldown')),
        'max_starts={}'.format(initiative.get('max_starts')),
        'avoid_when_active={}'.format(bool(initiative.get('avoid_when_active', True))),
        'active_threshold={}'.format(initiative.get('active_threshold')),
        'recent_window={}'.format(initiative.get('recent_window')),
    ]
    if initiative.get('topics'):
        parts.append('topics={}'.format(_format_named_list(initiative.get('topics'))))
    if initiative.get('allowed_intents'):
        parts.append('allowed_intents={}'.format(
            _format_named_list(initiative.get('allowed_intents'))))
    if initiative.get('forbidden_topics'):
        parts.append('forbidden_topics={}'.format(
            _format_named_list(initiative.get('forbidden_topics'))))
    return '; '.join(parts)


def _round_instruction(profile, persona=None, reply_policy=None):
    return (
        'Agent instruction: decide whether a normal person would reply. '
        'If not, use empty input to skip. Reply with one short chat message only. '
        '{}. {}. {}. Do not explain your decision. Use /quit to stop.'
    ).format(
        _format_profile_guidance(profile),
        _format_persona_guidance(persona),
        _format_reply_policy_guidance(reply_policy))


def _initiative_instruction(profile, persona, reply_policy, initiative,
                            preset=None, idle_seconds=0.0, recent_messages=None):
    recent_messages = recent_messages or []
    recent_lines = []
    for item in recent_messages[-6:]:
        recent_lines.append('[{id}] {sender}: {text}'.format(**item))
    recent_context = '\n'.join(recent_lines) if recent_lines else 'none'
    return (
        'Agent initiative opportunity:\n'
        'The group has been idle for {idle:.1f}s. preset={preset}.\n'
        '{profile}.\n{persona}.\n{reply_policy}.\n{initiative}.\n'
        'Recent context:\n{recent}\n'
        'Prefer continuing a harmless recent topic. If none exists, you may start one light, short, open-ended topic. '
        'Do not mention AI/Codex/Claude/operator identity. Do not advertise, moderate, summarize the group, ask private questions, or join risky topics. '
        'Output one message to send, or empty input to skip.'
    ).format(
        idle=float(idle_seconds),
        preset=preset or 'default',
        profile=_format_profile_guidance(profile),
        persona=_format_persona_guidance(persona),
        reply_policy=_format_reply_policy_guidance(reply_policy),
        initiative=_format_initiative_guidance(initiative),
        recent=recent_context)


class RoundReport:
    def __init__(self, duration=0.0):
        self.duration = float(duration)
        self.elapsed = 0.0
        self.received_batches = 0
        self.received_messages = 0
        self.prompted = 0
        self.sent_replies = 0
        self.sent_message_ids = []
        self.skip_reasons = {}
        self.reply_chars = []
        self.initiative_prompts = 0
        self.initiative_sent = 0
        self.initiative_skipped = 0
        self.initiative_skip_reasons = {}
        self.initiative_sent_message_ids = []

    def record_batch(self, message_count):
        self.received_batches += 1
        self.received_messages += int(message_count)

    def record_prompt(self):
        self.prompted += 1

    def record_skip(self, reason):
        reason = str(reason or 'skipped')
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def record_sent_message(self, message_id):
        self.sent_message_ids.append(int(message_id))

    def record_sent_reply(self, text=''):
        self.sent_replies += 1
        if text:
            self.reply_chars.append(len(text))

    def record_initiative_prompt(self):
        self.initiative_prompts += 1

    def record_initiative_skip(self, reason):
        reason = str(reason or 'skipped')
        self.initiative_skipped += 1
        self.initiative_skip_reasons[reason] = (
            self.initiative_skip_reasons.get(reason, 0) + 1)

    def record_initiative_sent(self, message_ids):
        self.initiative_sent += 1
        self.initiative_sent_message_ids.extend(int(x) for x in message_ids)

    @property
    def total_sent(self):
        return self.sent_replies + self.initiative_sent

    @property
    def avg_reply_chars(self):
        if not self.reply_chars:
            return 0.0
        return sum(self.reply_chars) / len(self.reply_chars)

    def finish(self, elapsed):
        self.elapsed = max(0.0, float(elapsed))
        return self

    def as_dict(self):
        return {
            'duration': self.duration,
            'elapsed': self.elapsed,
            'received_batches': self.received_batches,
            'received_messages': self.received_messages,
            'prompted': self.prompted,
            'sent_replies': self.sent_replies,
            'sent_message_ids': list(self.sent_message_ids),
            'skip_reasons': dict(self.skip_reasons),
            'avg_reply_chars': round(self.avg_reply_chars, 2),
            'initiative_prompts': self.initiative_prompts,
            'initiative_sent': self.initiative_sent,
            'initiative_skipped': self.initiative_skipped,
            'initiative_skip_reasons': dict(self.initiative_skip_reasons),
            'initiative_sent_message_ids': list(self.initiative_sent_message_ids),
        }


def _format_seconds(value):
    return '{:.1f}s'.format(float(value))


def _format_round_report(report):
    payload = report.as_dict()
    sent_ids = (
        ','.join(str(x) for x in payload['sent_message_ids'])
        if payload['sent_message_ids'] else 'none')
    skip_reasons = (
        json.dumps(payload['skip_reasons'], ensure_ascii=False, sort_keys=True)
        if payload['skip_reasons'] else '{}')
    initiative_ids = (
        ','.join(str(x) for x in payload['initiative_sent_message_ids'])
        if payload['initiative_sent_message_ids'] else 'none')
    initiative_skip_reasons = (
        json.dumps(
            payload['initiative_skip_reasons'],
            ensure_ascii=False, sort_keys=True)
        if payload['initiative_skip_reasons'] else '{}')
    return [
        'Round report:',
        'duration={}'.format(_format_seconds(payload['duration'])),
        'elapsed={}'.format(_format_seconds(payload['elapsed'])),
        'received_batches={}'.format(payload['received_batches']),
        'received_messages={}'.format(payload['received_messages']),
        'prompted={}'.format(payload['prompted']),
        'sent_replies={}'.format(payload['sent_replies']),
        'sent_message_ids={}'.format(sent_ids),
        'skip_reasons={}'.format(skip_reasons),
        'avg_reply_chars={}'.format(payload['avg_reply_chars']),
        'initiative_prompts={}'.format(payload['initiative_prompts']),
        'initiative_sent={}'.format(payload['initiative_sent']),
        'initiative_skipped={}'.format(payload['initiative_skipped']),
        'initiative_sent_message_ids={}'.format(initiative_ids),
        'initiative_skip_reasons={}'.format(initiative_skip_reasons),
    ]


_SHORT_ACKS = {
    '嗯', '恩', '哦', '噢', '昂', '啊', '行', '好', '好吧', '行吧',
    '哈哈', '哈哈哈', '呵呵', '笑死', '真的假的', '真的啊', '是吗',
    'ok', 'okay', 'yes', 'no', 'lol', 'haha',
}


def _compact_text(text):
    punctuation = string.punctuation + '，。！？、；：「」『』（）【】《》… '
    return ''.join(ch for ch in (text or '').casefold().strip()
                   if ch not in punctuation)


def _is_short_ack(text):
    compact = _compact_text(text)
    if not compact:
        return True
    return compact in _SHORT_ACKS or len(compact) <= 1


def _mention_names(me):
    names = []
    for attr in ('username', 'first_name', 'last_name'):
        value = getattr(me, attr, None)
        if value:
            names.append(str(value))
    display = utils.get_display_name(me) if me else None
    if display:
        names.append(display)
    return tuple(dict.fromkeys(x.casefold() for x in names if x))


def _mentions_me(text, names):
    haystack = (text or '').casefold()
    return any(name and name in haystack for name in names)


def _validate_probability(value, name):
    value = float(value)
    if value < 0.0 or value > 1.0:
        raise TelegramCliError('{} must be between 0 and 1.'.format(name))
    return value


def _validate_nonnegative(value, name):
    value = float(value)
    if value < 0.0:
        raise TelegramCliError('{} must be greater than or equal to 0.'.format(name))
    return value


def _should_prompt_for_text(text, reply_probability=1.0,
                            mention_reply_probability=None, mentions_me=False,
                            skip_short_ack=False, random_value=None):
    if skip_short_ack and _is_short_ack(text):
        return False, 'short_ack'

    probability = reply_probability
    if mentions_me and mention_reply_probability is not None:
        probability = mention_reply_probability
    probability = _validate_probability(probability, 'reply probability')

    if probability >= 1.0:
        return True, 'prompt'
    if probability <= 0.0:
        return False, 'probability'

    draw = random.random() if random_value is None else float(random_value)
    if draw <= probability:
        return True, 'prompt'
    return False, 'probability'


def _random_reply_delay(delay_min, delay_max, random_func=None):
    delay_min = _validate_nonnegative(delay_min, 'random delay min')
    delay_max = _validate_nonnegative(delay_max, 'random delay max')
    if delay_max < delay_min:
        raise TelegramCliError('random delay max must be greater than or equal to min.')
    if delay_max == 0.0:
        return 0.0
    random_func = random_func or random.uniform
    return float(random_func(delay_min, delay_max))


def _terms_in_text(terms, text):
    haystack = (text or '').casefold()
    matches = []
    for term in terms or []:
        term = str(term or '').strip()
        if term and term.casefold() in haystack:
            matches.append(term)
    return tuple(dict.fromkeys(matches))


def _inbound_message_ids(messages):
    ids = set()
    for item in messages or []:
        if item.get('out'):
            continue
        message_id = item.get('id')
        if message_id is None:
            continue
        ids.add(int(message_id))
    return ids


def _new_inbound_ids(previous_messages, latest_messages):
    return _inbound_message_ids(latest_messages) - _inbound_message_ids(previous_messages)


def _split_reply_text(text, max_chars=28, max_parts=3):
    text = (text or '').strip()
    if not text:
        return []
    max_chars = int(max_chars)
    max_parts = int(max_parts)
    if max_chars < 1:
        raise TelegramCliError('split max chars must be greater than 0.')
    if max_parts < 1:
        raise TelegramCliError('split max parts must be greater than 0.')
    if len(text) <= max_chars:
        return [text]

    parts = []
    current = ''
    split_chars = '。！？!?；;，,、\n'
    for ch in text:
        current += ch
        if ch in split_chars or len(current) >= max_chars:
            part = current.strip()
            if part:
                parts.append(part)
            current = ''
    if current.strip():
        parts.append(current.strip())

    merged = []
    for part in parts:
        if len(part) <= max_chars:
            merged.append(part)
            continue
        for start in range(0, len(part), max_chars):
            merged.append(part[start:start + max_chars])

    if len(merged) <= max_parts:
        return merged
    head = merged[:max_parts - 1]
    tail = ''.join(merged[max_parts - 1:]).strip()
    if tail:
        head.append(tail)
    return head


def _round_reply_parts(config, reply):
    round_config = getattr(config, 'round', {}) or {}
    if not round_config.get('split_long_replies'):
        return [reply.strip()] if reply.strip() else []
    return _split_reply_text(
        reply,
        max_chars=round_config.get('split_max_chars', 28),
        max_parts=round_config.get('split_max_parts', 3),
    )


def _remaining_message_budget(report, max_replies):
    remaining = int(max_replies) - len(report.sent_message_ids)
    return max(0, remaining)


async def _collect_merged_events(queue, first_event, merge_window, end_at, loop):
    events_ = [first_event]
    merge_window = _validate_nonnegative(merge_window, 'merge window')
    if merge_window <= 0.0:
        return events_

    deadline = min(end_at, loop.time() + merge_window)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return events_
        try:
            events_.append(await asyncio.wait_for(queue.get(), timeout=remaining))
        except asyncio.TimeoutError:
            return events_


async def get_me(config):
    config.require_credentials()
    async with _client(config) as client:
        me = await client.get_me()
        return {
            'id': me.id,
            'first_name': getattr(me, 'first_name', None),
            'last_name': getattr(me, 'last_name', None),
            'username': getattr(me, 'username', None),
            'bot': bool(getattr(me, 'bot', False)),
            'display_name': utils.get_display_name(me),
        }


async def list_dialogs(config, groups_only=False):
    config.require_credentials()
    rows = []
    async with _client(config) as client:
        async for dialog in client.iter_dialogs():
            row = _dialog_row(dialog)
            if groups_only and row['kind'] not in ('chat', 'supergroup', 'channel'):
                continue
            rows.append(row)
    return rows


async def resolve_chat(client, query, allow_users=False):
    query_text = str(query).strip()
    wanted_id = None
    if query_text.lstrip('-').isdigit():
        wanted_id = normalize_chat_id(query_text)

    matches = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        row = _dialog_row(dialog)
        if row['kind'] == 'user' and not allow_users:
            continue
        if wanted_id is not None and row['id'] == wanted_id:
            return entity, row
        username = (row.get('username') or '').lower()
        if query_text.startswith('@') and username == query_text[1:].lower():
            return entity, row
        if row['title'] == query_text:
            matches.append((entity, row))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ', '.join('{} ({})'.format(row['title'], row['id']) for _, row in matches)
        raise TelegramCliError('Chat title matched multiple dialogs: {}'.format(names))
    raise TelegramCliError('Chat not found: {}'.format(query))


async def history(config, chat, limit):
    config.require_credentials()
    async with _client(config) as client:
        entity, row = await resolve_chat(client, chat)
        messages = []
        async for message in client.iter_messages(entity, limit=limit):
            sender = await message.get_sender()
            messages.append({
                'id': message.id,
                'date': _format_ts(message.date),
                'sender_id': getattr(sender, 'id', None),
                'sender': utils.get_display_name(sender) if sender else None,
                'out': bool(message.out),
                'text': message.message or '',
            })
        messages.reverse()
        return row, messages


async def group_context(config, chat, limit, operator='agent', preset=None):
    limit = int(limit)
    if limit < 1:
        raise TelegramCliError('limit must be greater than 0.')
    row, messages = await history(config, chat, limit)
    return summarize_group_context(
        config, row, messages, operator=operator, preset=preset)


async def send_text(config, chat, text, assume_yes=False, dry_run=False,
                    input_func=input, output_func=print):
    config.require_credentials()
    async with _client(config) as client:
        entity, row = await resolve_chat(client, chat)
        safety.require_can_write(config, row['id'])
        matches = safety.find_forbidden_terms(config, text)
        if matches:
            safety.audit_record(
                config, 'send', row['id'], chat_title=row['title'],
                text=text, dry_run=dry_run, status='blocked_forbidden_terms')
            raise safety.SafetyError(
                'Message contains forbidden/sensitive profile term(s): {}.'.format(
                    ', '.join(matches)))
        if dry_run:
            safety.audit_record(
                config, 'send', row['id'], chat_title=row['title'],
                text=text, dry_run=True, status='dry_run')
            return {'sent': False, 'dry_run': True, 'chat': row, 'message_id': None}

        if not safety.confirm_send(
                row['title'], row['id'], text, assume_yes=assume_yes,
                input_func=input_func, output_func=output_func):
            safety.audit_record(
                config, 'send', row['id'], chat_title=row['title'],
                text=text, status='cancelled')
            return {'sent': False, 'dry_run': False, 'chat': row, 'message_id': None}

        sent = await client.send_message(entity, text)
        safety.audit_record(
            config, 'send', row['id'], chat_title=row['title'],
            text=text, message_id=sent.id, status='sent')
        return {'sent': True, 'dry_run': False, 'chat': row, 'message_id': sent.id}


async def observe(config, chat, include_self=False, timeout=None):
    config.require_credentials()
    client = _client(config)
    await client.start()
    me = await client.get_me()
    entity, row = await resolve_chat(client, chat)

    print('Observing {} (id={}). Press Ctrl+C to stop.'.format(row['title'], row['id']))

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        if not include_self and event.sender_id == me.id:
            return
        sender = await event.get_sender()
        name = utils.get_display_name(sender) if sender else str(event.sender_id)
        text = event.message.message or ''
        print('[{}] {}: {}'.format(event.message.id, name, text), flush=True)

    try:
        if timeout:
            try:
                await asyncio.wait_for(client.disconnected, timeout=timeout)
            except asyncio.TimeoutError:
                return
        else:
            await client.run_until_disconnected()
    finally:
        await client.disconnect()


async def _recent_context_lines(client, entity, limit):
    messages = []
    async for message in client.iter_messages(entity, limit=limit):
        sender = await message.get_sender()
        messages.append({
            'id': message.id,
            'sender': utils.get_display_name(sender) if sender else str(message.sender_id),
            'out': bool(message.out),
            'text': message.message or '',
        })
    messages.reverse()
    return messages


async def _recent_inbound_activity_times(client, entity, me_id, limit,
                                         recent_window, now_mono):
    recent_window = _validate_nonnegative(recent_window, 'recent window')
    if recent_window <= 0:
        return []
    now_wall = _dt.datetime.now(_dt.timezone.utc)
    times = []
    async for message in client.iter_messages(entity, limit=limit):
        if getattr(message, 'out', False) or message.sender_id == me_id:
            continue
        message_date = message.date
        if message_date is None:
            continue
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=_dt.timezone.utc)
        age = max(0.0, (now_wall - message_date).total_seconds())
        if age <= recent_window:
            times.append(max(0.0, now_mono - age))
    return times


async def interactive_round(config, chat, duration=60, limit=12, max_replies=8,
                            include_self=False, quiet_context=False,
                            min_reply_interval=2.0, end_buffer=5.0,
                            reply_probability=1.0,
                            mention_reply_probability=None,
                            random_delay_min=0.0, random_delay_max=0.0,
                            skip_short_ack=False, merge_window=0.0,
                            split_long_replies=None,
                            input_func=input, output_func=print):
    config.require_credentials()
    def emit(text=''):
        _emit(output_func, text)

    profile = getattr(config, 'profile', {}) or {}
    persona = getattr(config, 'persona', {}) or {}
    reply_policy = getattr(config, 'reply_policy', {}) or {}
    initiative = getattr(config, 'initiative', {}) or {}
    preset_name = getattr(config, 'preset_name', None)

    if split_long_replies is not None:
        config.round['split_long_replies'] = bool(split_long_replies)
    reply_probability = _validate_probability(reply_probability, 'reply probability')
    if mention_reply_probability is not None:
        mention_reply_probability = _validate_probability(
            mention_reply_probability, 'mention reply probability')
    random_delay_min = _validate_nonnegative(random_delay_min, 'random delay min')
    random_delay_max = _validate_nonnegative(random_delay_max, 'random delay max')
    if random_delay_max < random_delay_min:
        raise TelegramCliError('random delay max must be greater than or equal to min.')
    merge_window = _validate_nonnegative(merge_window, 'merge window')
    max_replies = int(max_replies)
    if max_replies < 1:
        raise TelegramCliError('max replies must be greater than 0.')
    report = RoundReport(duration=duration)

    client = _client(config)
    await client.start()
    queue = asyncio.Queue()
    seen_ids = set()
    last_sent_at = None

    try:
        me = await client.get_me()
        me_names = _mention_names(me)
        entity, row = await resolve_chat(client, chat)
        safety.require_can_write(config, row['id'])

        emit(
            'Round started: {} (id={}) duration={}s max_replies={} min_reply_interval={}s end_buffer={}s reply_probability={} random_delay={}-{}s merge_window={}s.'.format(
                row['title'], row['id'], duration, max_replies,
                min_reply_interval, end_buffer, reply_probability,
                random_delay_min, random_delay_max, merge_window))
        emit('Profile: {}'.format(_format_profile_guidance(profile)))
        emit('Persona: {}'.format(_format_persona_guidance(persona)))
        emit('Reply policy: {}'.format(_format_reply_policy_guidance(reply_policy)))
        emit('Initiative: {}'.format(_format_initiative_guidance(initiative)))
        emit('Type a reply to send, empty line to skip, /quit to stop.')

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            if not _remember_inbound_message(seen_ids, event.message.id):
                return
            if not include_self and event.sender_id == me.id:
                return
            await queue.put(event)

        loop = asyncio.get_running_loop()
        round_started_at = loop.time()
        end_at = round_started_at + float(duration)
        last_activity_at = round_started_at
        last_initiative_at = None
        initiative_starts = 0
        recent_event_times = []
        if initiative and initiative.get('enabled'):
            startup_recent_window = float(initiative.get('recent_window') or 300.0)
            startup_times = await _recent_inbound_activity_times(
                client, entity, me.id, min(limit, 30),
                startup_recent_window, round_started_at)
            if startup_times:
                recent_event_times.extend(startup_times)
                last_activity_at = max(startup_times)

        def record_skip(source, reason):
            if source == 'initiative':
                report.record_initiative_skip(reason)
            else:
                report.record_skip(reason)

        def finalize_sent(source, reply, sent_ids):
            if not sent_ids:
                return
            if source == 'initiative':
                report.record_initiative_sent(sent_ids)
            else:
                report.record_sent_reply(reply)

        async def send_operator_text(reply, source):
            nonlocal last_sent_at, last_activity_at
            matches = list(safety.find_forbidden_terms(config, reply))
            if source == 'initiative':
                matches.extend(_terms_in_text(
                    initiative.get('forbidden_topics') or [], reply))
                matches = list(dict.fromkeys(matches))
            if matches:
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='blocked_forbidden_terms')
                emit(
                    'Skipped: reply contains forbidden/sensitive profile term(s): {}.'.format(
                        ', '.join(matches)))
                record_skip(source, 'forbidden_terms')
                return []

            delay = safety.reply_interval_delay(
                loop.time(), last_sent_at, min_reply_interval)
            if delay > 0:
                if safety.should_stop_for_end_buffer(
                        loop.time() + delay, end_at, end_buffer):
                    safety.audit_record(
                        config, 'game_round_send', row['id'],
                        chat_title=row['title'], text=reply,
                        status='skipped_end_buffer')
                    emit(
                        'Skipped: rate-limit wait would enter end_buffer={}s.'.format(
                            end_buffer))
                    record_skip(source, 'rate_limit_end_buffer')
                    return []
                emit('Rate limit: waiting {:.1f}s before send.'.format(delay))
                await asyncio.sleep(delay)

            if safety.should_stop_for_end_buffer(loop.time(), end_at, end_buffer):
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='skipped_end_buffer')
                emit('Skipped: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                record_skip(source, 'end_buffer')
                return []

            reply_parts = _round_reply_parts(config, reply)
            if not reply_parts:
                emit('Skipped.')
                record_skip(source, 'empty_reply_parts')
                return []
            remaining_message_budget = _remaining_message_budget(report, max_replies)
            if len(reply_parts) > remaining_message_budget:
                safety.audit_record(
                    config, 'game_round_send', row['id'],
                    chat_title=row['title'], text=reply,
                    status='skipped_max_replies')
                emit(
                    'Skipped: reply would exceed max_replies={} outbound message cap.'.format(
                        max_replies))
                record_skip(source, 'max_replies')
                return []

            sent_ids = []
            for index, part in enumerate(reply_parts):
                safety.require_text_allowed(config, part)

                random_delay = (
                    _random_reply_delay(random_delay_min, random_delay_max)
                    if index == 0 else 0.0)
                if random_delay > 0:
                    if safety.should_stop_for_end_buffer(
                            loop.time() + random_delay, end_at, end_buffer):
                        safety.audit_record(
                            config, 'game_round_send', row['id'],
                            chat_title=row['title'], text=part,
                            status='skipped_end_buffer')
                        emit(
                            'Skipped: random delay would enter end_buffer={}s.'.format(
                                end_buffer))
                        record_skip(source, 'random_delay_end_buffer')
                        finalize_sent(source, reply, sent_ids)
                        return sent_ids
                    emit('Human delay: waiting {:.1f}s before send.'.format(
                        random_delay))
                    await asyncio.sleep(random_delay)

                if index > 0:
                    split_delay = _random_reply_delay(
                        config.round.get('split_delay_min', 1.0),
                        config.round.get('split_delay_max', 2.5))
                    if split_delay > 0:
                        if safety.should_stop_for_end_buffer(
                                loop.time() + split_delay, end_at, end_buffer):
                            safety.audit_record(
                                config, 'game_round_send', row['id'],
                                chat_title=row['title'], text=part,
                                status='skipped_end_buffer')
                            emit(
                                'Skipped: split delay would enter end_buffer={}s.'.format(
                                    end_buffer))
                            record_skip(source, 'split_delay_end_buffer')
                            finalize_sent(source, reply, sent_ids)
                            return sent_ids
                        emit('Split delay: waiting {:.1f}s.'.format(split_delay))
                        await asyncio.sleep(split_delay)

                if safety.should_stop_for_end_buffer(loop.time(), end_at, end_buffer):
                    safety.audit_record(
                        config, 'game_round_send', row['id'],
                        chat_title=row['title'], text=part,
                        status='skipped_end_buffer')
                    emit('Skipped: remaining time is below end_buffer={}s.'.format(
                        end_buffer))
                    record_skip(source, 'end_buffer')
                    finalize_sent(source, reply, sent_ids)
                    return sent_ids

                sent = await client.send_message(entity, part)
                last_sent_at = loop.time()
                last_activity_at = last_sent_at
                sent_ids.append(sent.id)
                report.record_sent_message(sent.id)
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=part, message_id=sent.id, status='sent')
                emit('SENT message_id={}'.format(sent.id))

            finalize_sent(source, reply, sent_ids)
            return sent_ids

        def initiative_wait_seconds(now):
            if not initiative or not initiative.get('enabled'):
                return None
            max_starts = int(initiative.get('max_starts') or 0)
            if initiative_starts >= max_starts:
                return None
            idle_after = float(initiative.get('idle_after') or 0.0)
            cooldown = float(initiative.get('cooldown') or 0.0)
            due_at = last_activity_at + idle_after
            if last_initiative_at is not None:
                due_at = max(due_at, last_initiative_at + cooldown)
            return max(0.0, due_at - now)

        async def run_initiative_prompt(now):
            nonlocal initiative_starts, last_initiative_at, last_activity_at
            recent_window = float(initiative.get('recent_window') or 300.0)
            active_threshold = int(initiative.get('active_threshold') or 0)
            recent_count = len([
                item for item in recent_event_times
                if item >= now - recent_window])
            if initiative.get('avoid_when_active', True) and active_threshold > 0:
                if recent_count >= active_threshold:
                    report.record_initiative_skip('active_chat')
                    last_initiative_at = now
                    return False

            initiative_starts += 1
            last_initiative_at = now
            report.record_initiative_prompt()
            recent_context = await _recent_context_lines(
                client, entity, min(limit, 8))
            emit('')
            emit(_initiative_instruction(
                profile, persona, reply_policy, initiative,
                preset=preset_name, idle_seconds=now - last_activity_at,
                recent_messages=recent_context))
            safety.require_can_write(config, row['id'])
            reply = input_func(
                'Agent initiative (empty skip, /quit stop): ').strip()
            if reply == '/quit':
                emit('Round stopped.')
                return True
            if not reply:
                emit('Skipped initiative.')
                report.record_initiative_skip('empty_input')
                return False
            latest_context = await _recent_context_lines(
                client, entity, min(limit, 8))
            new_ids = _new_inbound_ids(recent_context, latest_context)
            if new_ids:
                now_after_input = loop.time()
                last_activity_at = now_after_input
                recent_event_times.extend([now_after_input] * len(new_ids))
                emit('Skipped initiative: newer inbound activity arrived.')
                report.record_initiative_skip('stale_context')
                return False
            await send_operator_text(reply, 'initiative')
            return False

        while len(report.sent_message_ids) < max_replies:
            now = loop.time()
            remaining = end_at - now
            if remaining <= 0:
                break
            if safety.should_stop_for_end_buffer(now, end_at, end_buffer):
                emit('Round stopping: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                report.record_skip('end_buffer')
                break
            wait_timeout = max(0.0, remaining - max(0.0, float(end_buffer or 0.0)))
            initiative_wait = initiative_wait_seconds(now)
            if initiative_wait == 0.0:
                should_stop = await run_initiative_prompt(now)
                if should_stop:
                    break
                continue
            if initiative_wait is not None:
                wait_timeout = min(wait_timeout, initiative_wait)
            if wait_timeout <= 0:
                break
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                continue

            events_batch = await _collect_merged_events(
                queue, event, merge_window, end_at, loop)
            last_activity_at = loop.time()
            recent_event_times.extend([last_activity_at] * len(events_batch))
            report.record_batch(len(events_batch))
            incoming_lines = []
            combined_text = []
            for item_event in events_batch:
                sender = await item_event.get_sender()
                sender_name = (
                    utils.get_display_name(sender)
                    if sender else str(item_event.sender_id))
                text = item_event.message.message or ''
                incoming_lines.append((item_event.message.id, sender_name, text))
                combined_text.append(text)

            emit('')
            if len(incoming_lines) == 1:
                msg_id, sender_name, text = incoming_lines[0]
                emit('Incoming [{}] {}: {}'.format(msg_id, sender_name, text))
            else:
                emit('Incoming batch ({} messages):'.format(len(incoming_lines)))
                for msg_id, sender_name, text in incoming_lines:
                    emit('- [{}] {}: {}'.format(msg_id, sender_name, text))

            should_prompt, reason = _should_prompt_for_text(
                '\n'.join(combined_text),
                reply_probability=reply_probability,
                mention_reply_probability=mention_reply_probability,
                mentions_me=_mentions_me('\n'.join(combined_text), me_names),
                skip_short_ack=skip_short_ack)
            if not should_prompt:
                emit('Skipped: {}.'.format(reason))
                report.record_skip(reason)
                continue

            if not quiet_context:
                emit('Recent context:')
                for item in await _recent_context_lines(client, entity, limit):
                    prefix = 'me' if item['out'] else item['sender']
                    emit('- [{}] {}: {}'.format(item['id'], prefix, item['text']))
            emit(_round_instruction(profile, persona, reply_policy))
            report.record_prompt()

            safety.require_can_write(config, row['id'])
            reply = input_func('Agent reply (empty skip, /quit stop): ').strip()
            if reply == '/quit':
                emit('Round stopped.')
                break
            if not reply:
                emit('Skipped.')
                report.record_skip('empty_input')
                continue

            await send_operator_text(reply, 'reply')

        report.finish(loop.time() - round_started_at)
        emit('Round finished. replies={} initiatives={}'.format(
            report.sent_replies, report.initiative_sent))
        for line in _format_round_report(report):
            emit(line)
        return report
    finally:
        await client.disconnect()


def _daemon_task_prompt(profile, persona, reply_policy):
    return _round_instruction(profile, persona, reply_policy)


def _task_config(base_config, task):
    task_config = copy.copy(base_config)
    task_config.profile = task.get('profile') or getattr(base_config, 'profile', {})
    task_config.persona = task.get('persona') or getattr(base_config, 'persona', {})
    task_config.reply_policy = (
        task.get('reply_policy') or getattr(base_config, 'reply_policy', {}))
    task_config.initiative = (
        task.get('initiative') or getattr(base_config, 'initiative', {}))
    return task_config


def _daemon_parse_time(value):
    if value in (None, ''):
        return None
    text = str(value)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _daemon_reply_counts(queue_path, chat_id, now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    queue = daemon_store.load_queue(queue_path)
    hourly = 0
    consecutive = 0
    counting_consecutive = True
    for task in reversed(queue.get('tasks', [])):
        chat = task.get('chat') or {}
        if int(chat.get('id') or 0) != int(chat_id):
            continue
        status = task.get('status')
        updated_at = _daemon_parse_time(task.get('updated_at')) or now
        if status in ('reply_pending', 'held_rate_limit'):
            continue
        if status == 'completed' and task.get('message_id') is not None:
            if (now - updated_at).total_seconds() <= 3600:
                hourly += 1
            if counting_consecutive:
                consecutive += 1
            continue
        counting_consecutive = False
    return hourly, consecutive


def _daemon_retry_after(seconds, now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return now + _dt.timedelta(seconds=max(0.0, float(seconds or 0.0)))


async def _daemon_send_reply_task(client, entity, config, row, task,
                                  last_sent_at, dry_run, emit):
    queue_path = config.daemon['queue_path']
    status_path = config.daemon['status_path']
    reply = (task.get('reply_text') or '').strip()
    if not reply:
        daemon_store.skip_task(queue_path, task['id'], reason='empty_reply')
        return last_sent_at

    task_config = _task_config(config, task)
    safety.require_can_write(task_config, row['id'])
    matches = safety.find_forbidden_terms(task_config, reply)
    if matches:
        safety.audit_record(
            task_config, 'daemon_reply_send', row['id'],
            chat_title=row['title'], text=reply,
            dry_run=bool(dry_run or task.get('reply_dry_run')),
            status='blocked_forbidden_terms')
        daemon_store.skip_task(
            queue_path, task['id'], reason='forbidden_terms')
        emit('Skipped queued reply {}: forbidden terms.'.format(task['id']))
        return last_sent_at

    now = asyncio.get_running_loop().time()
    delay = safety.reply_interval_delay(
        now, last_sent_at, config.daemon['min_reply_interval'])
    if delay > 0:
        emit('Daemon rate limit: waiting {:.1f}s before send.'.format(delay))
        await asyncio.sleep(delay)

    if daemon_store.stop_requested(status_path):
        emit('Queued reply {} held: stop requested.'.format(task['id']))
        return last_sent_at
    current_task = daemon_store.get_task(queue_path, task['id'])
    if current_task is None or current_task.get('status') != 'reply_pending':
        emit('Queued reply {} held: task status changed.'.format(task['id']))
        return last_sent_at
    reply = (current_task.get('reply_text') or '').strip()
    if not reply:
        daemon_store.skip_task(queue_path, task['id'], reason='empty_reply')
        return last_sent_at
    safety.require_can_write(task_config, row['id'])
    matches = safety.find_forbidden_terms(task_config, reply)
    if matches:
        safety.audit_record(
            task_config, 'daemon_reply_send', row['id'],
            chat_title=row['title'], text=reply,
            dry_run=bool(dry_run or current_task.get('reply_dry_run')),
            status='blocked_forbidden_terms')
        daemon_store.skip_task(
            queue_path, task['id'], reason='forbidden_terms')
        emit('Skipped queued reply {}: forbidden terms.'.format(task['id']))
        return last_sent_at

    hourly, consecutive = _daemon_reply_counts(queue_path, row['id'])
    if hourly >= int(config.daemon['max_messages_per_hour']):
        retry_after = _daemon_retry_after(60.0)
        daemon_store.hold_rate_limited_task(
            queue_path, task['id'], reason='hourly_limit',
            retry_after=retry_after)
        emit('Queued reply {} held: hourly daemon limit reached.'.format(
            task['id']))
        return last_sent_at
    if consecutive >= int(config.daemon['max_consecutive_replies']):
        retry_after = _daemon_retry_after(
            max(1.0, float(config.daemon['min_reply_interval'])))
        daemon_store.hold_rate_limited_task(
            queue_path, task['id'], reason='consecutive_limit',
            retry_after=retry_after)
        emit('Queued reply {} held: consecutive daemon limit reached.'.format(
            task['id']))
        return last_sent_at

    if dry_run or current_task.get('reply_dry_run'):
        safety.audit_record(
            task_config, 'daemon_reply_send', row['id'],
            chat_title=row['title'], text=reply, dry_run=True,
            status='dry_run')
        daemon_store.complete_task(queue_path, task['id'], dry_run=True)
        emit('DRY-RUN queued reply task={}'.format(task['id']))
        return last_sent_at

    sent = await client.send_message(entity, reply)
    last_sent_at = asyncio.get_running_loop().time()
    safety.audit_record(
        task_config, 'daemon_reply_send', row['id'],
        chat_title=row['title'], text=reply, message_id=sent.id,
        status='sent')
    daemon_store.complete_task(
        queue_path, task['id'], message_id=sent.id, dry_run=False)
    emit('SENT queued reply task={} message_id={}'.format(
        task['id'], sent.id))
    return last_sent_at


async def daemon_run(config, chat, preset=None, duration=3600.0, dry_run=False,
                     output_func=print):
    config.require_credentials()

    def emit(text=''):
        _emit(output_func, text)

    profile = getattr(config, 'profile', {}) or {}
    persona = getattr(config, 'persona', {}) or {}
    reply_policy = getattr(config, 'reply_policy', {}) or {}
    initiative = getattr(config, 'initiative', {}) or {}
    round_config = getattr(config, 'round', {}) or {}
    daemon_config = getattr(config, 'daemon', {}) or {}
    queue_path = daemon_config['queue_path']
    lock_path = daemon_config['lock_path']
    status_path = daemon_config['status_path']
    owner = 'tg-cli-daemon:{}'.format(os.getpid())
    lock = daemon_store.acquire_lock(
        lock_path, owner=owner,
        stale_after=daemon_config.get('stale_lock_after', 3600.0))
    client = None

    def update_status(row=None, running=True):
        nonlocal lock
        lock = daemon_store.refresh_lock(lock_path, owner=owner)
        current = daemon_store.read_status(status_path)
        payload = {
            'running': bool(running),
            'pid': os.getpid(),
            'owner': owner,
            'preset': preset or None,
            'dry_run': bool(dry_run),
            'lock': lock,
            'queue_counts': daemon_store.queue_counts(queue_path),
        }
        if row is not None or 'chat' not in current:
            payload['chat'] = row
        current.update(payload)
        daemon_store.write_status(status_path, current)

    try:
        daemon_store.clear_stop(status_path)

        client = _client(config)
        await client.start()
        queue = asyncio.Queue()
        seen_ids = set()
        last_sent_at = None

        me = await client.get_me()
        me_names = _mention_names(me)
        entity, row = await resolve_chat(client, chat)
        safety.require_allowed_chat(config, row['id'])
        startup_messages = await _recent_context_lines(client, entity, 200)
        startup_context = summarize_group_context(
            config, row, startup_messages, operator='daemon', preset=preset,
            tail_limit=min(int(daemon_config['max_task_context']), 12))
        context_summary = _task_context_summary(startup_context)
        update_status(row=row, running=True)
        emit(
            'Daemon started: {} (id={}) duration={}s preset={} dry_run={}.'.format(
                row['title'], row['id'], duration, preset or 'default',
                str(bool(dry_run)).lower()))

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            if not _remember_inbound_message(seen_ids, event.message.id):
                return
            if event.sender_id == me.id:
                return
            await queue.put(event)

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        end_at = started_at + float(duration)
        last_activity_at = started_at
        last_initiative_at = None
        initiative_starts = 0
        recent_event_times = []

        async def append_context_task(kind, prompt, messages):
            task = daemon_store.create_task(
                chat=row,
                messages=messages[-int(daemon_config['max_task_context']):],
                profile=profile,
                persona=persona,
                reply_policy=reply_policy,
                initiative=initiative,
                preset=preset,
                kind=kind,
                prompt=prompt,
                context_summary=context_summary)
            task['dry_run'] = bool(dry_run)
            appended = daemon_store.append_task(
                queue_path, task,
                max_pending=daemon_config['max_pending'])
            if appended:
                emit('Queued daemon task id={} kind={}.'.format(
                    task['id'], kind))
            else:
                emit('Skipped daemon task: max_pending reached.')
            return appended

        def initiative_due(now):
            if not initiative or not initiative.get('enabled'):
                return None
            if initiative_starts >= int(initiative.get('max_starts') or 0):
                return None
            due_at = last_activity_at + float(initiative.get('idle_after') or 0.0)
            if last_initiative_at is not None:
                due_at = max(
                    due_at,
                    last_initiative_at + float(initiative.get('cooldown') or 0.0))
            return max(0.0, due_at - now)

        async def maybe_queue_initiative(now):
            nonlocal initiative_starts, last_initiative_at
            recent_window = float(initiative.get('recent_window') or 300.0)
            active_threshold = int(initiative.get('active_threshold') or 0)
            recent_count = len([
                item for item in recent_event_times
                if item >= now - recent_window])
            if initiative.get('avoid_when_active', True) and active_threshold > 0:
                if recent_count >= active_threshold:
                    last_initiative_at = now
                    return
            recent_context = await _recent_context_lines(
                client, entity, min(round_config.get('limit', 12),
                                    daemon_config['max_task_context']))
            prompt = _initiative_instruction(
                profile, persona, reply_policy, initiative,
                preset=preset, idle_seconds=now - last_activity_at,
                recent_messages=recent_context)
            initiative_starts += 1
            last_initiative_at = now
            await append_context_task('initiative', prompt, recent_context)

        while True:
            now = loop.time()
            if now >= end_at:
                break
            if daemon_store.stop_requested(status_path):
                emit('Daemon stopping: stop requested.')
                break

            for task in daemon_store.reply_pending_tasks(
                    queue_path, row['id'], task_ttl=daemon_config['task_ttl']):
                last_sent_at = await _daemon_send_reply_task(
                    client, entity, config, row, task, last_sent_at,
                    dry_run, emit)
                update_status(row=row, running=True)

            wait_timeout = min(
                float(daemon_config['poll_interval']),
                max(0.0, end_at - now))
            initiative_wait = initiative_due(now)
            if initiative_wait == 0.0:
                await maybe_queue_initiative(now)
                update_status(row=row, running=True)
                continue
            if initiative_wait is not None:
                wait_timeout = min(wait_timeout, initiative_wait)

            try:
                event = await asyncio.wait_for(queue.get(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                update_status(row=row, running=True)
                continue

            events_batch = await _collect_merged_events(
                queue, event, round_config.get('merge_window', 0.0), end_at, loop)
            last_activity_at = loop.time()
            recent_event_times.extend([last_activity_at] * len(events_batch))
            combined_text = []
            incoming_lines = []
            for item_event in events_batch:
                sender = await item_event.get_sender()
                sender_name = (
                    utils.get_display_name(sender)
                    if sender else str(item_event.sender_id))
                text = item_event.message.message or ''
                combined_text.append(text)
                incoming_lines.append((item_event.message.id, sender_name, text))

            should_prompt, reason = _should_prompt_for_text(
                '\n'.join(combined_text),
                reply_probability=round_config.get('reply_probability', 1.0),
                mention_reply_probability=round_config.get(
                    'mention_reply_probability'),
                mentions_me=_mentions_me('\n'.join(combined_text), me_names),
                skip_short_ack=round_config.get('skip_short_ack', False))
            if not should_prompt:
                emit('Skipped daemon task: {}.'.format(reason))
                update_status(row=row, running=True)
                continue

            recent_context = await _recent_context_lines(
                client, entity, min(round_config.get('limit', 12),
                                    daemon_config['max_task_context']))
            prompt = _daemon_task_prompt(profile, persona, reply_policy)
            await append_context_task('message', prompt, recent_context)
            update_status(row=row, running=True)

        emit('Daemon finished.')
    finally:
        try:
            update_status(running=False)
        finally:
            if client is not None:
                await client.disconnect()
            daemon_store.release_lock(lock_path, owner=owner)


async def codex_context(config, chat, limit, operator='agent', preset=None):
    profile = dict(config.profile)
    persona = dict(getattr(config, 'persona', {}) or {})
    reply_policy = dict(getattr(config, 'reply_policy', {}) or {})
    initiative = dict(getattr(config, 'initiative', {}) or {})
    row, messages = await history(config, chat, limit)
    operator = (operator or 'agent').strip() or 'agent'
    return {
        'chat': row,
        'operator': operator,
        'preset': preset or None,
        'profile': profile,
        'persona': persona,
        'reply_policy': reply_policy,
        'initiative': initiative,
        'messages': messages,
        'instruction': (
            '你是 {}，基于 messages 判断是否自然回复。'
            '遵守 profile、persona、reply_policy 和 initiative 中的约束。'
            '如果不适合回复，输出空内容；如果适合，只输出要发送的消息文本，不要解释。'
        ).format(operator),
    }


def dumps_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
