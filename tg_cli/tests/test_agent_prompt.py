from tg_cli.agent_prompt import build_initiative_prompt, build_operator_prompt


def test_build_operator_prompt_includes_character_and_memory():
    prompt = build_operator_prompt(
        operator='codex',
        task_kind='message',
        profile={'style': '短句', 'max_chars': 80},
        persona={'identity': '小林', 'traits': ['外向']},
        reply_policy={'style_rules': ['别像客服'], 'conversation_rules': ['不编造']},
        initiative={'topics': ['游戏']},
        character={
            'name': '小林',
            'actions': ['reply'],
            'evaluators': ['not_everything'],
        },
        memory=[{'scope': 'room', 'content': '这个群喜欢打游戏。'}],
        recent_messages=[{'id': 1, 'sender': 'A', 'text': '晚上开黑吗'}],
    )

    assert 'operator=codex' in prompt
    assert 'character.name=小林' in prompt
    assert '这个群喜欢打游戏' in prompt
    assert '晚上开黑吗' in prompt
    assert '只输出要发送的消息文本' in prompt


def test_build_initiative_prompt_marks_action_space():
    prompt = build_initiative_prompt(
        profile={'style': '自然'},
        persona={'identity': '小林'},
        reply_policy={},
        initiative={'topics': ['游戏'], 'allowed_intents': ['ask_open_question']},
        character={'name': '小林', 'actions': ['ask_open_question']},
        memory=[],
        idle_seconds=120,
        recent_messages=[],
    )

    assert 'initiative' in prompt
    assert 'idle_seconds=120' in prompt
    assert 'ask_open_question' in prompt
