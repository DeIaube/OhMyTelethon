from tg_cli.agent_report import summarize_agent_run


def test_summarize_agent_run_counts_actions_and_skips():
    summary = summarize_agent_run([
        {'action': 'reply', 'status': 'sent'},
        {'action': 'skip', 'status': 'skipped', 'reason': 'short_ack'},
        {'action': 'light_joke', 'status': 'blocked', 'reason': 'forbidden_terms'},
    ])

    assert summary['total'] == 3
    assert summary['actions'] == {'reply': 1, 'skip': 1, 'light_joke': 1}
    assert summary['statuses'] == {'sent': 1, 'skipped': 1, 'blocked': 1}
    assert summary['reasons'] == {'short_ack': 1, 'forbidden_terms': 1}
