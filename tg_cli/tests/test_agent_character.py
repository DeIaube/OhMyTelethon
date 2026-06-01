import pytest

from tg_cli.agent_character import (
    character_to_social_config, normalize_character,
)
from tg_cli.config import ConfigError


def test_normalize_character_accepts_eliza_like_fields():
    character = normalize_character({
        'name': '小林',
        'bio': ['普通群友', '喜欢短句接梗'],
        'lore': ['不声称自己有真实线下经历'],
        'style': {
            'all': ['自然', '短句'],
            'chat': ['别像客服', '少解释'],
        },
        'topics': ['游戏', '日常闲聊'],
        'adjectives': ['外向', '会接梗'],
        'message_examples': [
            [
                {'user': 'A', 'content': {'text': '今天好累'}},
                {'user': '小林', 'content': {'text': '今天适合直接摆烂五分钟'}},
            ],
        ],
        'actions': ['reply', 'ask_open_question', 'light_joke'],
        'evaluators': ['cooldown', 'not_everything', 'no_identity_claims'],
    })

    assert character['name'] == '小林'
    assert character['style']['chat'] == ['别像客服', '少解释']
    assert character['actions'] == ['reply', 'ask_open_question', 'light_joke']
    assert character['evaluators'] == [
        'cooldown', 'not_everything', 'no_identity_claims']


def test_character_to_social_config_maps_existing_layers():
    social = character_to_social_config(normalize_character({
        'name': '小林',
        'bio': ['普通群友'],
        'style': {'chat': ['短句', '自然']},
        'topics': ['游戏'],
        'adjectives': ['外向'],
        'actions': ['reply', 'light_joke'],
        'evaluators': ['not_everything'],
    }))

    assert social['persona']['identity'] == '小林'
    assert '普通群友' in social['persona']['traits']
    assert '短句' in social['reply_policy']['style_rules']
    assert '游戏' in social['initiative']['topics']
    assert social['actions'] == ['reply', 'light_joke']
    assert social['evaluators'] == ['not_everything']


def test_normalize_character_rejects_non_object():
    with pytest.raises(ConfigError, match='character must contain a JSON object'):
        normalize_character('bad')
