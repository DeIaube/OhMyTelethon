def _count(items, key):
    counts = {}
    for item in items:
        value = item.get(key)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def summarize_agent_run(events):
    events = list(events or [])
    return {
        'total': len(events),
        'actions': _count(events, 'action'),
        'statuses': _count(events, 'status'),
        'reasons': _count(events, 'reason'),
    }
