from types import SimpleNamespace

from tg_cli import bad_cases


def make_config(tmp_path, **overrides):
    config = {
        'enabled': True,
        'path': tmp_path / '.tg-cli-bad-cases.jsonl',
        'max_records': 20,
        'max_task_bad_cases': 3,
        'recent_days': 30,
    }
    config.update(overrides)
    return SimpleNamespace(bad_cases=config)


def test_record_bad_case_hashes_message_text(tmp_path):
    config = make_config(tmp_path)

    record = bad_cases.record_bad_case(
        config,
        source='daemon',
        reason='self_context_wait',
        chat={'id': 5217114569, 'title': '秘密群'},
        preset='chat_social',
        messages=[
            {'id': 1, 'sender': 'A', 'out': False, 'text': '这里有原文'},
            {'id': 2, 'sender': 'me', 'out': True, 'text': '我的原文'},
        ])

    assert record['case_type'] == 'self_flood'
    assert record['lesson']
    saved = config.bad_cases['path'].read_text(encoding='utf-8')
    assert '这里有原文' not in saved
    assert '我的原文' not in saved
    assert '秘密群' not in saved
    assert 'text_hash' in saved


def test_list_bad_cases_filters_chat_and_limits_newest(tmp_path):
    config = make_config(tmp_path)
    bad_cases.record_bad_case(
        config, source='round', reason='min_reply_chars', chat_id=1)
    newer = bad_cases.record_bad_case(
        config, source='round', reason='stale_context', chat_id=2)
    latest = bad_cases.record_bad_case(
        config, source='round', reason='self_context_wait', chat_id=2)

    assert [
        item['id'] for item in bad_cases.list_bad_cases(config, limit=2)
    ] == [latest['id'], newer['id']]
    assert [
        item['chat_id'] for item in bad_cases.list_bad_cases(
            config, chat_id=2, limit=10)
    ] == [2, 2]


def test_bad_case_prompt_guidance_is_compact(tmp_path):
    config = make_config(tmp_path)
    bad_cases.record_bad_case(
        config, source='daemon', reason='self_context_wait',
        chat_id=5217114569, task_id='task-1')

    guidance = bad_cases.recent_bad_case_guidance(
        config, chat_id=5217114569, limit=1)

    assert guidance == [{
        'case_type': 'self_flood',
        'reason': 'self_context_wait',
        'source': 'daemon',
        'lesson': 'Wait for a newer human message before opening another topic; do not keep starting topics after your own tail messages.',
    }]


def test_record_bad_case_noops_when_disabled_or_unknown_reason(tmp_path):
    disabled = make_config(tmp_path, enabled=False)
    unknown = make_config(tmp_path)

    assert bad_cases.record_bad_case(
        disabled, source='daemon', reason='self_context_wait', chat_id=1) is None
    assert bad_cases.record_bad_case(
        unknown, source='daemon', reason='ordinary_skip', chat_id=1) is None
