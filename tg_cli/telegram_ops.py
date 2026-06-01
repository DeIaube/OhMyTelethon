import asyncio
import datetime as _dt
import json

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
        'Codex instruction: reply with one chat message only; {}. '
        'Use empty input to skip or /quit to stop.'
    ).format(_format_profile_guidance(profile))


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
                            input_func=input, output_func=print):
    config.require_credentials()
    client = _client(config)
    await client.start()
    queue = asyncio.Queue()
    replies = 0
    seen_ids = set()
    last_sent_at = None

    try:
        me = await client.get_me()
        entity, row = await resolve_chat(client, chat)
        safety.require_can_write(config, row['id'])

        output_func(
            'Round started: {} (id={}) duration={}s max_replies={} min_reply_interval={}s end_buffer={}s.'.format(
                row['title'], row['id'], duration, max_replies,
                min_reply_interval, end_buffer))
        output_func('Profile: {}'.format(_format_profile_guidance(config.profile)))
        output_func('Type a reply to send, empty line to skip, /quit to stop.')

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            if not _remember_inbound_message(seen_ids, event.message.id):
                return
            if not include_self and event.sender_id == me.id:
                return
            await queue.put(event)

        loop = asyncio.get_running_loop()
        end_at = loop.time() + float(duration)
        while replies < max_replies:
            now = loop.time()
            remaining = end_at - now
            if remaining <= 0:
                break
            if safety.should_stop_for_end_buffer(now, end_at, end_buffer):
                output_func('Round stopping: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                break
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=max(0.0, remaining - max(0.0, float(end_buffer or 0.0))))
            except asyncio.TimeoutError:
                break

            sender = await event.get_sender()
            sender_name = utils.get_display_name(sender) if sender else str(event.sender_id)
            text = event.message.message or ''
            output_func('\nIncoming [{}] {}: {}'.format(event.message.id, sender_name, text))
            if not quiet_context:
                output_func('Recent context:')
                for item in await _recent_context_lines(client, entity, limit):
                    prefix = 'me' if item['out'] else item['sender']
                    output_func('- [{}] {}: {}'.format(item['id'], prefix, item['text']))
            output_func(_round_instruction(config.profile))

            safety.require_can_write(config, row['id'])
            reply = input_func('Codex reply (empty skip, /quit stop): ').strip()
            if reply == '/quit':
                output_func('Round stopped.')
                break
            if not reply:
                output_func('Skipped.')
                continue

            matches = safety.find_forbidden_terms(config, reply)
            if matches:
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='blocked_forbidden_terms')
                output_func(
                    'Skipped: reply contains forbidden/sensitive profile term(s): {}.'.format(
                        ', '.join(matches)))
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
                    output_func(
                        'Skipped: rate-limit wait would enter end_buffer={}s.'.format(
                            end_buffer))
                    continue
                output_func('Rate limit: waiting {:.1f}s before send.'.format(delay))
                await asyncio.sleep(delay)

            if safety.should_stop_for_end_buffer(loop.time(), end_at, end_buffer):
                safety.audit_record(
                    config, 'game_round_send', row['id'], chat_title=row['title'],
                    text=reply, status='skipped_end_buffer')
                output_func('Skipped: remaining time is below end_buffer={}s.'.format(
                    end_buffer))
                continue

            safety.require_text_allowed(config, reply)

            sent = await client.send_message(entity, reply)
            last_sent_at = loop.time()
            replies += 1
            safety.audit_record(
                config, 'game_round_send', row['id'], chat_title=row['title'],
                text=reply, message_id=sent.id, status='sent')
            output_func('SENT message_id={}'.format(sent.id))

        output_func('Round finished. replies={}'.format(replies))
        return replies
    finally:
        await client.disconnect()


async def codex_context(config, chat, limit):
    row, messages = await history(config, chat, limit)
    return {
        'chat': row,
        'profile': dict(config.profile),
        'messages': messages,
        'instruction': (
            '你是 Codex，基于 messages 生成一条候选群聊回复。'
            '遵守 profile 中的风格、语言、长度、禁用词和回复策略。'
            '只输出要发送的消息文本，不要解释。'
        ),
    }


def dumps_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
