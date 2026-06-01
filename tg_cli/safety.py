import datetime as _dt
import hashlib
import json


class SafetyError(RuntimeError):
    pass


def load_state(config):
    path = config.state_path
    if not path.is_file():
        return {'paused': False}
    with path.open('r', encoding='utf-8') as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise SafetyError('State file must contain a JSON object.')
    state.setdefault('paused', False)
    return state


def save_state(config, state):
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    with config.state_path.open('w', encoding='utf-8') as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')


def set_paused(config, paused):
    state = load_state(config)
    state['paused'] = bool(paused)
    save_state(config, state)
    return state


def is_paused(config):
    return bool(load_state(config).get('paused'))


def require_allowed_chat(config, chat_id):
    normalized = int(chat_id)
    if normalized not in config.allowed_chats:
        allowed = ', '.join(str(x) for x in config.allowed_chats) or 'none'
        raise SafetyError(
            'Chat {} is not whitelisted. Allowed chats: {}.'.format(
                normalized, allowed))


def require_can_write(config, chat_id):
    if is_paused(config):
        raise SafetyError('tg-cli is paused. Run `tg-cli resume` before sending.')
    require_allowed_chat(config, chat_id)


def confirm_send(chat_title, chat_id, text, assume_yes=False, input_func=input, output_func=print):
    if assume_yes:
        return True
    output_func('Target: {} (id={})'.format(chat_title, chat_id))
    output_func('Message: {}'.format(text))
    answer = input_func('Send? [y/N] ').strip().lower()
    return answer in ('y', 'yes')


def audit_record(config, action, chat_id, chat_title=None, text=None,
                 message_id=None, dry_run=False, status='ok'):
    config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'ts': _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        'action': action,
        'chat_id': int(chat_id) if chat_id is not None else None,
        'chat_title': chat_title,
        'message_id': message_id,
        'dry_run': bool(dry_run),
        'status': status,
    }
    if text is not None:
        encoded = text.encode('utf-8')
        payload['text_sha256'] = hashlib.sha256(encoded).hexdigest()
        payload['text_length'] = len(text)

    with config.audit_log_path.open('a', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write('\n')
    return payload
