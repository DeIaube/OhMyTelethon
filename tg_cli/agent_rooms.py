def select_next_room(rooms):
    candidates = []
    for room in rooms or []:
        if room.get('status') != 'active':
            continue
        remaining = int(room.get('remaining_count') or 0)
        if remaining <= 0:
            continue
        candidates.append((remaining, room.get('last_sent_at') or '', room))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]
