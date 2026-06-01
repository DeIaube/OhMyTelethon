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
                            include_self=False, input_func=input, output_func=print):
    config.require_credentials()
    client = _client(config)
    await client.start()
    queue = asyncio.Queue()
    replies = 0
    seen_ids = set()

    try:
        me = await client.get_me()
        entity, row = await resolve_chat(client, chat)
        safety.require_can_write(config, row['id'])

        output_func(
            'Round started: {} (id={}) duration={}s max_replies={}.'.format(
                row['title'], row['id'], duration, max_replies))
        output_func('Type a reply to send, empty line to skip, /quit to stop.')

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            if event.message.id in seen_ids:
                return
            seen_ids.add(event.message.id)
            if not include_self and event.sender_id == me.id:
                return
            await queue.put(event)

        loop = asyncio.get_running_loop()
        end_at = loop.time() + float(duration)
        while replies < max_replies:
            remaining = end_at - loop.time()
            if remaining <= 0:
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            sender = await event.get_sender()
            sender_name = utils.get_display_name(sender) if sender else str(event.sender_id)
            text = event.message.message or ''
            output_func('\nIncoming [{}] {}: {}'.format(event.message.id, sender_name, text))
            output_func('Recent context:')
            for item in await _recent_context_lines(client, entity, limit):
                prefix = 'me' if item['out'] else item['sender']
                output_func('- [{}] {}: {}'.format(item['id'], prefix, item['text']))

            safety.require_can_write(config, row['id'])
            reply = input_func('Codex reply (empty skip, /quit stop): ').strip()
            if reply == '/quit':
                output_func('Round stopped.')
                break
            if not reply:
                output_func('Skipped.')
                continue

            sent = await client.send_message(entity, reply)
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
    profile = {
        'style': '自然、简短、像普通群聊，不要长篇解释。',
        'language': '中文',
        'max_chars': 80,
        'emoji_level': 'low',
    }
    profile.update(config.profile or {})
    return {
        'chat': row,
        'profile': profile,
        'messages': messages,
        'instruction': (
            '你是 Codex，基于 messages 生成一条候选群聊回复。'
            '只输出要发送的消息文本，不要解释。'
        ),
    }


def dumps_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
