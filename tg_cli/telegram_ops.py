import asyncio
import datetime as _dt
import json
import random
import string

from telethon import TelegramClient, events, utils
from telethon.tl.types import Channel, Chat, User

from .config import normalize_chat_id
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


def _round_instruction(profile):
    return (
        'Agent instruction: reply with one chat message only; {}. '
        'Use empty input to skip or /quit to stop.'
    ).format(_format_profile_guidance(profile))


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

    def record_sent_reply(self):
        self.sent_replies += 1

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
        emit('Profile: {}'.format(_format_profile_guidance(config.profile)))
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
        while report.sent_replies < max_replies:
            now = loop.time()
            remaining = end_at - now
            if remaining <= 0:
                break
            if safety.should_stop_for_end_buffer(now, end_at, end_buffer):
                emit('Round stopping: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                report.record_skip('end_buffer')
                break
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=max(0.0, remaining - max(0.0, float(end_buffer or 0.0))))
            except asyncio.TimeoutError:
                break

            events_batch = await _collect_merged_events(
                queue, event, merge_window, end_at, loop)
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
            emit(_round_instruction(config.profile))
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

            matches = safety.find_forbidden_terms(config, reply)
            if matches:
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='blocked_forbidden_terms')
                emit(
                    'Skipped: reply contains forbidden/sensitive profile term(s): {}.'.format(
                        ', '.join(matches)))
                report.record_skip('forbidden_terms')
                continue

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
                    report.record_skip('rate_limit_end_buffer')
                    continue
                emit('Rate limit: waiting {:.1f}s before send.'.format(delay))
                await asyncio.sleep(delay)

            if safety.should_stop_for_end_buffer(loop.time(), end_at, end_buffer):
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='skipped_end_buffer')
                emit('Skipped: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                report.record_skip('end_buffer')
                continue

            reply_parts = _round_reply_parts(config, reply)
            if not reply_parts:
                emit('Skipped.')
                report.record_skip('empty_reply_parts')
                continue

            sent_ids = []
            split_skipped = False
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
                        report.record_skip('random_delay_end_buffer')
                        split_skipped = True
                        break
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
                            report.record_skip('split_delay_end_buffer')
                            split_skipped = True
                            break
                        emit('Split delay: waiting {:.1f}s.'.format(split_delay))
                        await asyncio.sleep(split_delay)

                if safety.should_stop_for_end_buffer(loop.time(), end_at, end_buffer):
                    safety.audit_record(
                        config, 'game_round_send', row['id'],
                        chat_title=row['title'], text=part,
                        status='skipped_end_buffer')
                    emit('Skipped: remaining time is below end_buffer={}s.'.format(
                        end_buffer))
                    report.record_skip('end_buffer')
                    split_skipped = True
                    break

                sent = await client.send_message(entity, part)
                last_sent_at = loop.time()
                sent_ids.append(sent.id)
                report.record_sent_message(sent.id)
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=part, message_id=sent.id, status='sent')
                emit('SENT message_id={}'.format(sent.id))

            if sent_ids:
                report.record_sent_reply()
            elif split_skipped:
                continue

        report.finish(loop.time() - round_started_at)
        emit('Round finished. replies={}'.format(report.sent_replies))
        for line in _format_round_report(report):
            emit(line)
        return report
    finally:
        await client.disconnect()


async def codex_context(config, chat, limit, operator='agent', preset=None):
    profile = dict(config.profile)
    row, messages = await history(config, chat, limit)
    operator = (operator or 'agent').strip() or 'agent'
    return {
        'chat': row,
        'operator': operator,
        'preset': preset or None,
        'profile': profile,
        'messages': messages,
        'instruction': (
            '你是 {}，基于 messages 生成一条候选群聊回复。'
            '遵守 profile 中的风格、语言、长度、禁用词和回复策略。'
            '只输出要发送的消息文本，不要解释。'
        ).format(operator),
    }


def dumps_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
