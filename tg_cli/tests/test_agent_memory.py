import pytest

from tg_cli.agent_memory import MemoryStore


def test_memory_store_records_room_and_user_memory(tmp_path):
    db_path = tmp_path / 'agent-memory.sqlite3'
    store = MemoryStore(db_path)
    store.ensure_schema()

    store.upsert_room(chat_id=123, title='测试群')
    store.remember(
        chat_id=123, scope='room', content='这个群喜欢晚上开黑。',
        kind='preference')
    store.remember(
        chat_id=123, scope='user', sender_id=456, sender_name='阿强',
        content='阿强常聊游戏。', kind='profile')

    memories = store.relevant_memories(chat_id=123, sender_id=456, limit=10)

    assert [item['content'] for item in memories] == [
        '阿强常聊游戏。',
        '这个群喜欢晚上开黑。',
    ]


def test_memory_store_hashes_events_without_raw_text(tmp_path):
    store = MemoryStore(tmp_path / 'agent-memory.sqlite3')
    store.ensure_schema()
    store.record_event(
        chat_id=123,
        message_id=10,
        sender_id=456,
        sender_name='阿强',
        direction='in',
        text='晚上开黑吗',
    )

    rows = store.events(chat_id=123, limit=1)

    assert rows[0]['text_len'] == 5
    assert rows[0]['text_hash']
    assert '晚上开黑吗' not in str(rows[0])


def test_memory_store_rejects_invalid_confidence(tmp_path):
    store = MemoryStore(tmp_path / 'agent-memory.sqlite3')

    with pytest.raises(ValueError, match='confidence must be between 0 and 1'):
        store.remember(
            chat_id=123, scope='room', content='note', confidence=2.0)


def test_memory_store_zero_relevant_memory_limit_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / 'agent-memory.sqlite3')
    store.remember(
        chat_id=123, scope='room', content='这个群喜欢晚上开黑。')

    assert store.relevant_memories(chat_id=123, limit=0) == []


def test_memory_store_requires_sender_for_user_scope(tmp_path):
    store = MemoryStore(tmp_path / 'agent-memory.sqlite3')

    with pytest.raises(ValueError, match='sender_id is required'):
        store.remember(chat_id=123, scope='user', content='note')
