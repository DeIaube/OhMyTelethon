import json


def _lines(title, values):
    lines = [title]
    if isinstance(values, list):
        for item in values:
            lines.append('- {}'.format(item))
    elif isinstance(values, dict):
        for key in sorted(values):
            lines.append('- {}={}'.format(
                key, json.dumps(values[key], ensure_ascii=False)
                if isinstance(values[key], (dict, list)) else values[key]))
    elif values not in (None, ''):
        lines.append('- {}'.format(values))
    return '\n'.join(lines)


def _messages(recent_messages):
    lines = []
    for item in recent_messages or []:
        lines.append('- [{id}] {sender}: {text}'.format(
            id=item.get('id'),
            sender=item.get('sender') or item.get('sender_id') or 'unknown',
            text=item.get('text') or '',
        ))
    return '\n'.join(lines) if lines else '- none'


def _memory(memory):
    lines = []
    for item in memory or []:
        lines.append('- {scope}: {content}'.format(
            scope=item.get('scope', 'memory'),
            content=item.get('content', ''),
        ))
    return '\n'.join(lines) if lines else '- none'


def build_operator_prompt(operator, task_kind, profile, persona, reply_policy,
                          initiative, character=None, memory=None,
                          recent_messages=None, action=None):
    character = character or {}
    persona = persona or {}
    return '\n'.join([
        'operator={}'.format(operator or 'agent'),
        'task_kind={}'.format(task_kind or 'message'),
        'action={}'.format(action or 'decide'),
        'character.name={}'.format(
            character.get('name') or persona.get('identity') or ''),
        _lines('profile', profile or {}),
        _lines('persona', persona),
        _lines('reply_policy', reply_policy or {}),
        _lines('initiative', initiative or {}),
        _lines('character', character),
        _lines('actions', character.get('actions') or []),
        _lines('evaluators', character.get('evaluators') or []),
        'memory',
        _memory(memory),
        'recent_messages',
        _messages(recent_messages),
        '规则：如果不适合回复，输出空内容。适合回复时，只输出要发送的消息文本，不要解释。',
        '规则：不要声称真实身份、线下经历、私密关系或未发生的事实。',
    ])


def build_initiative_prompt(profile, persona, reply_policy, initiative,
                            character=None, memory=None, idle_seconds=0,
                            recent_messages=None):
    return '\n'.join([
        'initiative',
        'idle_seconds={}'.format(int(float(idle_seconds or 0))),
        build_operator_prompt(
            operator='codex',
            task_kind='initiative',
            profile=profile,
            persona=persona,
            reply_policy=reply_policy,
            initiative=initiative,
            character=character,
            memory=memory,
            recent_messages=recent_messages,
            action='initiative',
        ),
    ])
