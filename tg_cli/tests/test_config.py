import json

import pytest

from tg_cli.config import (
    DEFAULT_DAEMON, DEFAULT_INITIATIVE, DEFAULT_PERSONA, DEFAULT_PROFILE,
    DEFAULT_QUOTA, DEFAULT_REPLY_POLICY, DEFAULT_ROUND, DEFAULT_MEMORY,
    ConfigError, load_config, normalize_chat_id, normalize_daemon,
    normalize_memory, normalize_quota, normalize_round, parse_chat_ids,
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
    assert config.daemon['poll_interval'] == DEFAULT_DAEMON['poll_interval']
    assert config.daemon['task_ttl'] == DEFAULT_DAEMON['task_ttl']
    assert config.daemon['max_pending'] == DEFAULT_DAEMON['max_pending']
    assert config.daemon['queue_path'] == (
        tmp_path / 'tg_cli' / '.tg-cli-daemon-queue.json').resolve()
    assert config.daemon['lock_path'] == (
        tmp_path / 'tg_cli' / '.tg-cli-daemon.lock').resolve()
    assert config.daemon['status_path'] == (
        tmp_path / 'tg_cli' / '.tg-cli-daemon-status.json').resolve()
    assert config.quota['state_path'] == (
        tmp_path / 'tg_cli' / '.tg-cli-quota-state.json').resolve()
    assert DEFAULT_QUOTA['state_path'] is None
    assert config.memory['enabled'] is False
    assert config.memory['path'] == (
        tmp_path / 'tg_cli' / '.tg-cli-memory.sqlite3').resolve()
    assert config.memory['max_task_memories'] == DEFAULT_MEMORY['max_task_memories']
    assert DEFAULT_MEMORY['path'] is None
    assert config.reply_policy == DEFAULT_REPLY_POLICY
    assert config.initiative == DEFAULT_INITIATIVE
    assert config.persona == DEFAULT_PERSONA
    assert config.character['actions'] == ['reply', 'skip']
    assert config.resolve_reply_policy(None) == DEFAULT_REPLY_POLICY
    assert config.resolve_initiative(None) == DEFAULT_INITIATIVE
    assert config.resolve_persona(None) == DEFAULT_PERSONA
    assert config.resolve_character(None)['actions'] == ['reply', 'skip']


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
            'min_starts': '1',
            'min_start_after': '20',
            'avoid_when_active': False,
            'recent_window': '120',
            'topic_sources': 'recent_messages',
            'allow_topic_shift': True,
            'topic_shift_when': 'unsafe context',
            'topic_shift_style': 'casual pivot',
            'fallback_topics': 'games tonight',
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
    assert config.initiative['min_starts'] == 1
    assert config.initiative['min_start_after'] == 20.0
    assert config.initiative['avoid_when_active'] is False
    assert config.initiative['recent_window'] == 120.0
    assert config.initiative['topic_sources'] == ['recent_messages']
    assert config.initiative['allow_topic_shift'] is True
    assert config.initiative['topic_shift_when'] == ['unsafe context']
    assert config.initiative['topic_shift_style'] == 'casual pivot'
    assert config.initiative['fallback_topics'] == ['games tonight']
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


def test_load_config_merges_daemon_defaults_with_file_values(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'daemon': {
            'queue_path': 'queue.json',
            'lock_path': 'daemon.lock',
            'status_path': 'status.json',
            'poll_interval': '0.5',
            'task_ttl': 120,
            'claim_ttl': 45,
            'max_pending': '3',
            'max_task_context': 5,
            'min_reply_interval': 7,
            'max_messages_per_hour': 9,
            'max_consecutive_replies': 2,
            'stale_lock_after': 30,
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.daemon['queue_path'].name == 'queue.json'
    assert config.daemon['lock_path'].name == 'daemon.lock'
    assert config.daemon['status_path'].name == 'status.json'
    assert config.daemon['poll_interval'] == 0.5
    assert config.daemon['task_ttl'] == 120.0
    assert config.daemon['claim_ttl'] == 45.0
    assert config.daemon['max_pending'] == 3
    assert config.daemon['max_task_context'] == 5
    assert config.daemon['min_reply_interval'] == 7.0
    assert config.daemon['max_messages_per_hour'] == 9
    assert config.daemon['max_consecutive_replies'] == 2
    assert config.daemon['stale_lock_after'] == 30.0


def test_load_config_merges_quota_defaults_with_file_values(tmp_path):
    config_path = tmp_path / '.tg-cli.json'
    config_path.write_text(json.dumps({
        'quota': {
            'state_path': 'quota-state.json',
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)

    assert config.quota['state_path'] == (
        tmp_path / 'quota-state.json').resolve()


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
        'character': {
            'name': 'global character',
            'style': {
                'all': ['global all'],
                'chat': ['global chat'],
            },
            'actions': ['reply', 'skip'],
        },
        'daemon': {
            'min_reply_interval': 6,
            'max_messages_per_hour': 20,
        },
        'presets': {
            'social': {
                'daemon': {
                    'min_reply_interval': 2,
                    'max_messages_per_hour': 240,
                    'max_consecutive_replies': 4,
                },
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
                    'allow_topic_shift': True,
                    'topic_shift_when': 'unsafe',
                    'topic_shift_style': 'change subject',
                    'fallback_topics': 'movies',
                },
                'persona': {
                    'traits': ['witty'],
                    'avoid': 'lecturing',
                },
                'character': {
                    'name': 'social character',
                    'style': {
                        'chat': ['preset chat'],
                    },
                    'actions': ['reply', 'light_joke'],
                },
            },
        },
    }), encoding='utf-8')

    config = load_config(config_path, env={}, cwd=tmp_path)
    reply_policy = config.resolve_reply_policy('social')
    initiative = config.resolve_initiative('social')
    persona = config.resolve_persona('social')
    character = config.resolve_character('social')
    daemon = config.resolve_daemon('social')

    assert config.presets['social']['daemon'] == {
        'min_reply_interval': 2.0,
        'max_messages_per_hour': 240,
        'max_consecutive_replies': 4,
    }
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
        'allow_topic_shift': True,
        'topic_shift_when': ['unsafe'],
        'topic_shift_style': 'change subject',
        'fallback_topics': ['movies'],
    }
    assert config.presets['social']['persona'] == {
        'traits': ['witty'],
        'avoid': ['lecturing'],
    }
    assert config.presets['social']['character'] == {
        'name': 'social character',
        'style': {
            'chat': ['preset chat'],
        },
        'actions': ['reply', 'light_joke'],
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
    assert initiative['allow_topic_shift'] is True
    assert initiative['topic_shift_when'] == ['unsafe']
    assert initiative['topic_shift_style'] == 'change subject'
    assert initiative['fallback_topics'] == ['movies']
    assert persona['identity'] == 'global identity'
    assert persona['traits'] == ['witty']
    assert persona['avoid'] == ['lecturing']
    assert character['name'] == 'social character'
    assert character['style']['all'] == ['global all']
    assert character['style']['chat'] == ['preset chat']
    assert character['actions'] == ['reply', 'light_joke']
    assert character['evaluators'] == ['not_everything', 'cooldown', 'no_identity_claims']
    assert daemon['min_reply_interval'] == 2.0
    assert daemon['max_messages_per_hour'] == 240
    assert daemon['max_consecutive_replies'] == 4
    assert config.resolve_daemon(None)['min_reply_interval'] == 6.0
    assert config.resolve_daemon(None)['max_messages_per_hour'] == 20


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

    config_path.write_text(json.dumps({
        'presets': {
            'social': {'daemon': 'not-object'},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.social.daemon'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'presets': {
            'social': {'daemon': {'queue_path': 'other.json'}},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.social.daemon.queue_path'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'presets': {
            'social': {'character': 'not-object'},
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='presets.social.character'):
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
            'min_starts': -1,
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='initiative.min_starts'):
        load_config(config_path, env={}, cwd=tmp_path)

    config_path.write_text(json.dumps({
        'initiative': {
            'min_start_after': -1,
        },
    }), encoding='utf-8')

    with pytest.raises(ConfigError, match='initiative.min_start_after'):
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


def test_normalize_daemon_rejects_invalid_values():
    with pytest.raises(ConfigError, match='daemon.max_pending'):
        normalize_daemon({'max_pending': 0})
    with pytest.raises(ConfigError, match='daemon.poll_interval'):
        normalize_daemon({'poll_interval': -1})
    with pytest.raises(ConfigError, match='daemon.queue_path'):
        normalize_daemon({'queue_path': 123})


def test_normalize_quota_rejects_invalid_values():
    with pytest.raises(ConfigError, match='quota must contain a JSON object'):
        normalize_quota(['not-object'])
    with pytest.raises(ConfigError, match='quota.state_path'):
        normalize_quota({'state_path': 123})


def test_normalize_memory_rejects_invalid_values():
    with pytest.raises(ConfigError, match='memory must contain a JSON object'):
        normalize_memory(['not-object'])
    with pytest.raises(ConfigError, match='memory.path'):
        normalize_memory({'path': 123})
    with pytest.raises(ConfigError, match='memory.max_task_memories'):
        normalize_memory({'max_task_memories': -1})
