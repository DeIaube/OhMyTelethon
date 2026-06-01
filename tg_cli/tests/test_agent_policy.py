from tg_cli.agent_policy import evaluate_message_batch


class FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_evaluator_skips_short_ack_when_enabled():
    decision = evaluate_message_batch(
        text='哈哈',
        round_config={'skip_short_ack': True, 'reply_probability': 1.0},
        reply_policy={'reply_threshold': 0.6},
        initiative={},
        character={'evaluators': ['skip_short_ack']},
        mentions_me=False,
        me_names=[],
    )

    assert decision['should_prompt'] is False
    assert decision['reason'] == 'short_ack'
    assert decision['action'] == 'skip'


def test_evaluator_prompts_direct_question():
    decision = evaluate_message_batch(
        text='你觉得晚上开黑吗？',
        round_config={'skip_short_ack': True, 'reply_probability': 1.0},
        reply_policy={'reply_threshold': 0.6},
        initiative={},
        character={
            'actions': ['reply', 'ask_open_question'],
            'evaluators': ['direct_question'],
        },
        mentions_me=False,
        me_names=[],
    )

    assert decision['should_prompt'] is True
    assert decision['action'] == 'reply'


def test_evaluator_preserves_zero_reply_probability_for_questions():
    decision = evaluate_message_batch(
        text='你觉得晚上开黑吗？',
        round_config={'reply_probability': 0.0},
        reply_policy={},
        initiative={},
        character={'actions': ['reply']},
        mentions_me=False,
    )

    assert decision == {
        'should_prompt': False,
        'reason': 'probability',
        'action': 'skip',
    }


def test_evaluator_preserves_zero_reply_probability_for_mentions_without_override():
    decision = evaluate_message_batch(
        text='小林你怎么看？',
        round_config={'reply_probability': 0.0, 'mention_reply_probability': None},
        reply_policy={},
        initiative={},
        character={'actions': ['reply']},
        mentions_me=True,
    )

    assert decision['should_prompt'] is False
    assert decision['reason'] == 'probability'


def test_evaluator_uses_explicit_mention_probability_override():
    decision = evaluate_message_batch(
        text='小林你怎么看？',
        round_config={'reply_probability': 0.0, 'mention_reply_probability': 1.0},
        reply_policy={},
        initiative={},
        character={'actions': ['reply']},
        mentions_me=True,
    )

    assert decision['should_prompt'] is True
    assert decision['action'] == 'reply'


def test_evaluator_uses_character_skip_short_ack_hint():
    decision = evaluate_message_batch(
        text='真的假的',
        round_config={'reply_probability': 1.0, 'skip_short_ack': False},
        reply_policy={},
        initiative={},
        character={'evaluators': ['skip_short_ack']},
    )

    assert decision['should_prompt'] is False
    assert decision['reason'] == 'short_ack'


def test_not_everything_hint_does_not_override_skip_short_ack_flag():
    decision = evaluate_message_batch(
        text='哈哈哈',
        round_config={'reply_probability': 1.0, 'skip_short_ack': False},
        reply_policy={},
        initiative={},
        character={'actions': ['reply'], 'evaluators': ['not_everything']},
    )

    assert decision['should_prompt'] is True
    assert decision['action'] == 'reply'


def test_evaluator_skips_legacy_short_ack_forms():
    decision = evaluate_message_batch(
        text='哈哈哈',
        round_config={'reply_probability': 1.0, 'skip_short_ack': True},
        reply_policy={},
        initiative={},
        character={'actions': ['reply']},
    )

    assert decision['should_prompt'] is False
    assert decision['reason'] == 'short_ack'


def test_evaluator_keeps_probability_reason_compatible():
    decision = evaluate_message_batch(
        text='普通一句话',
        round_config={'reply_probability': 0.25},
        reply_policy={},
        initiative={},
        character={'actions': ['reply']},
        rng=FixedRng(0.9),
    )

    assert decision == {
        'should_prompt': False,
        'reason': 'probability',
        'action': 'skip',
    }
