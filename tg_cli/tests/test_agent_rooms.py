from tg_cli.agent_rooms import select_next_room


def test_select_next_room_prioritizes_remaining_count_then_oldest_send():
    rooms = [
        {
            'chat_id': 1,
            'status': 'active',
            'remaining_count': 2,
            'last_sent_at': '2026-06-01T00:10:00+00:00',
        },
        {
            'chat_id': 2,
            'status': 'active',
            'remaining_count': 5,
            'last_sent_at': '2026-06-01T00:20:00+00:00',
        },
        {
            'chat_id': 3,
            'status': 'done',
            'remaining_count': 10,
            'last_sent_at': '',
        },
    ]

    assert select_next_room(rooms)['chat_id'] == 2


def test_select_next_room_returns_none_when_no_active_room():
    assert select_next_room([
        {'chat_id': 1, 'status': 'done', 'remaining_count': 0},
    ]) is None
