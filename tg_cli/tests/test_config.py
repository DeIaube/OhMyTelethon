import json

import pytest

from tg_cli.config import (
    DEFAULT_INITIATIVE, DEFAULT_PERSONA, DEFAULT_PROFILE,
    DEFAULT_REPLY_POLICY, DEFAULT_ROUND, ConfigError, load_config,
    normalize_chat_id, normalize_round, parse_chat_ids,
)


def test_normalize_chat_id_accepts_telegram_peer_forms():
    assert normalize_chat_id('5217114569') == 5217114569
    assert normalize_chat_id('-5217114569') == 5217114569
    assert normalize_chat_id('-1001937176825') == 1937176825


def test_parse_chat_ids_accepts_string_or_list():
    assert parse_chat_ids('5217114569,-1001937176825') == [5217114569, 1937176825]
    assert parse_chat_ids([5217114569, '-1937176825']) == [5217114569, 1937176825]


def test_load_config_prefers_environment_over_file(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'api_id': 111,
        'api_hash': 'file-hash',
        'session_path': 'file.session',
        'allowed_chats': [1],
        'state_path': 'file-state.json',
        'audit_log_path': 'file-audit.log',
    }), encoding='utf-8')

    env = {
        'TG_API_ID': '222',
        'TG_API_HASH': 'env-hash',
        'TG_CLI_SESSION': str(tmp_path / 'env.session'),
        'TG_CLI_ALLOWED_CHATS': '5217114569,-1001937176825',
        'TG_CLI_STATE': str(tmp_path / 'env-state.json'),
        'TG_CLI_AUDIT_LOG': str(tmp_path / 'env-audit.log'),
    }

    config = load_config(config_path, env=env, cwd=tmp_path, require_credentials=True)

    assert config.api_id == 222
    assert config.api_hash == 'env-hash'
    assert config.session_path == (tmp_path / 'env.session').resolve()
    assert config.allowed_chats == (5217114569, 1937176825)
    assert config.state_path == (tmp_path / 'env-state.json').resolve()
    assert config.audit_log_path == (tmp_path / 'env-audit.log').resolve()


def test_load_config_requires_credentials_when_requested(tmp_path):
    with pytest.raises(ConfigError):
        load_config(env={}, cwd=tmp_path, require_credentials=True)


def test_load_config_supplies_profile_defaults_when_omitted(tmp_path):
    config = load_config(env={}, cwd=tmp_path)

    assert config.profile == DEFAULT_PROFILE
    assert config.round == DEFAULT_ROUND
    assert config.reply_policy == DEFAULT_REPLY_POLICY
    assert config.initiative == DEFAULT_INITIATIVE
    assert config.persona == DEFAULT_PERSONA
    assert config.resolve_reply_policy(None) == DEFAULT_REPLY_POLICY
    assert config.resolve_initiative(None) == DEFAULT_INITIATIVE
    assert config.resolve_persona(None) == DEFAULT_PERSONA


def test_load_config_merges_social_policy_defaults_with_file_values(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'reply_policy': {
            'reply_threshold': '0.75',
            'prefer_reply_when': 'asked directly',
            'skip_when': ['busy thread', None, ''],
            'custom_hint': 'prefer direct questions',
        },
        'initiative': {
            'enabled': True,
            'idle_after': '10',
            'cooldown': 3,
            'max_starts': '2',
            'avoid_when_active': False,
            'recent_window': '120',
            'topic_sources': 'recent_messages',
        },
        'persona': {
            'identity': 'regular chat member',
            'traits': 'dry humor',
            'catchphrases': ['行吧'],
            'style_notes': None,
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.reply_policy['group_type'] == DEFAULT_REPLY_POLICY['group_type']
    assert config.reply_policy['reply_threshold'] == 0.75
    assert config.reply_policy['prefer_reply_when'] == ['asked directly']
    assert config.reply_policy['skip_when'] == ['busy thread']
    assert config.reply_policy['style_rules'] == DEFAULT_REPLY_POLICY['style_rules']
    assert config.reply_policy['custom_hint'] == 'prefer direct questions'
    assert config.initiative['enabled'] is True
    assert config.initiative['group_type'] == DEFAULT_INITIATIVE['group_type']
    assert config.initiative['idle_after'] == 10.0
    assert config.initiative['cooldown'] == 3.0
    assert config.initiative['max_starts'] == 2
    assert config.initiative['avoid_when_active'] is False
    assert config.initiative['recent_window'] == 120.0
    assert config.initiative['topic_sources'] == ['recent_messages']
    assert config.persona['identity'] == 'regular chat member'
    assert config.persona['traits'] == ['dry humor']
    assert config.persona['catchphrases'] == ['行吧']
    assert config.persona['style_notes'] == []


def test_load_config_merges_profile_defaults_with_file_values(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'profile': {
            'style': 'brief and dry',
            'max_chars': 42,
            'avoid_topics': 'spoilers',
            'forbidden_terms': ['classified', 'internal'],
            'custom_hint': 'keep it casual',
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.profile['style'] == 'brief and dry'
    assert config.profile['language'] == DEFAULT_PROFILE['language']
    assert config.profile['max_chars'] == 42
    assert config.profile['emoji_level'] == DEFAULT_PROFILE['emoji_level']
    assert config.profile['avoid_topics'] == ['spoilers']
    assert config.profile['forbidden_terms'] == ['classified', 'internal']
    assert config.profile['reply_policy'] == DEFAULT_PROFILE['reply_policy']
    assert config.profile['custom_hint'] == 'keep it casual'


def test_load_config_merges_round_defaults_with_file_values(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'round': {
            'duration': 120,
            'reply_probability': 0.8,
            'quiet_context': True,
            'split_long_replies': True,
            'split_max_chars': 24,
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.round['duration'] == 120.0
    assert config.round['reply_probability'] == 0.8
    assert config.round['quiet_context'] is True
    assert config.round['split_long_replies'] is True
    assert config.round['split_max_chars'] == 24
    assert config.round['max_replies'] == DEFAULT_ROUND['max_replies']


def test_load_config_presets_resolve_over_global_profile_and_round(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'profile': {
            'style': 'global style',
            'avoid_topics': ['global topic'],
        },
        'round': {
            'duration': 120,
            'max_replies': 4,
            'quiet_context': False,
        },
        'presets': {
            'casual': {
                'profile': {
                    'max_chars': 42,
                    'forbidden_terms': 'preset secret',
                },
                'round': {
                    'duration': 30,
                    'quiet_context': True,
                },
            },
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)
    profile = config.resolve_profile('casual')
    round_config = config.resolve_round('casual')

    assert config.presets['casual']['profile'] == {
        'max_chars': 42,
        'forbidden_terms': ['preset secret'],
    }
    assert config.presets['casual']['round'] == {
        'duration': 30.0,
        'quiet_context': True,
    }
    assert profile['style'] == 'global style'
    assert profile['avoid_topics'] == ['global topic']
    assert profile['max_chars'] == 42
    assert profile['forbidden_terms'] == ['preset secret']
    assert round_config['duration'] == 30.0
    assert round_config['max_replies'] == 4
    assert round_config['quiet_context'] is True
    assert config.resolve_profile(None)['max_chars'] == DEFAULT_PROFILE['max_chars']
    assert config.resolve_round(None)['duration'] == 120.0


def test_load_config_presets_resolve_over_global_social_policy(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'reply_policy': {
            'reply_threshold': 0.4,
            'prefer_reply_when': ['global cue'],
        },
        'initiative': {
            'enabled': True,
            'idle_after': 30,
            'cooldown': 60,
        },
        'persona': {
            'identity': 'global identity',
            'traits': ['global trait'],
        },
        'presets': {
            'social': {
                'reply_policy': {
                    'reply_threshold': 0.9,
                    'skip_when': 'heated argument',
                },
                'initiative': {
                    'enabled': False,
                    'cooldown': 15,
                    'avoid_when_active': False,
                    'recent_window': 90,
                    'topics': 'music',
                },
                'persona': {
                    'traits': ['witty'],
                    'avoid': 'lecturing',
                },
            },
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)
    reply_policy = config.resolve_reply_policy('social')
    initiative = config.resolve_initiative('social')
    persona = config.resolve_persona('social')

    assert config.presets['social']['reply_policy'] == {
        'reply_threshold': 0.9,
        'skip_when': ['heated argument'],
    }
    assert config.presets['social']['initiative'] == {
        'enabled': False,
        'cooldown': 15.0,
        'avoid_when_active': False,
        'recent_window': 90.0,
        'topics': ['music'],
    }
    assert config.presets['social']['persona'] == {
        'traits': ['witty'],
        'avoid': ['lecturing'],
    }
    assert reply_policy['reply_threshold'] == 0.9
    assert reply_policy['prefer_reply_when'] == ['global cue']
    assert reply_policy['skip_when'] == ['heated argument']
    assert initiative['enabled'] is False
    assert initiative['idle_after'] == 30.0
    assert initiative['cooldown'] == 15.0
    assert initiative['avoid_when_active'] is False
    assert initiative['recent_window'] == 90.0
    assert initiative['topics'] == ['music']
    assert persona['identity'] == 'global identity'
    assert persona['traits'] == ['witty']
    assert persona['avoid'] == ['lecturing']


def test_resolve_unknown_preset_raises_clear_error(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'presets': {
            'casual': {'profile': {'style': 'casual'}},
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    with pytest.raises(ConfigError, match='Unknown preset "missing".*casual'):
        config.resolve_profile('missing')

    with pytest.raises(ConfigError, match='Unknown preset "missing".*casual'):
        config.resolve_reply_policy('missing')


def test_load_config_rejects_invalid_presets_shape(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'presets': ['not-object'],
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets must contain a JSON object'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_load_config_rejects_invalid_preset_value(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'presets': {
            'casual': ['not-object'],
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.casual must contain a JSON object'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_load_config_rejects_invalid_preset_profile_shape(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'presets': {
            'casual': {'profile': 'not-object'},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.casual.profile'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_load_config_rejects_invalid_social_policy_shapes(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'reply_policy': ['not-object'],
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='reply_policy must contain a JSON object'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'persona': {
            'traits': {'not': 'a-list'},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='persona.traits'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'presets': {
            'social': {'initiative': 'not-object'},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.social.initiative'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_load_config_rejects_invalid_social_policy_values_with_paths(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'presets': {
            'social': {
                'initiative': {
                    'idle_after': -1,
                },
            },
        },
    }), encoding='utf-8')

    with pytest.raises(
            ConfigError,
            match='presets.social.initiative.idle_after'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'initiative': {
            'enabled': 'yes',
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='initiative.enabled'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'reply_policy': {
            'reply_threshold': -0.1,
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='reply_policy.reply_threshold'):
        load_config(config_path, env={}, cwd=tmp_path)


def test_normalize_round_rejects_invalid_probability():
    with pytest.raises(ConfigError):
        normalize_round({'reply_probability': 1.2})
