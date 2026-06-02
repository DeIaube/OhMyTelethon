import random
import string


SHORT_ACKS = {
    '嗯', '恩', '哦', '噢', '昂', '啊', '行', '好', '好吧', '行吧',
    '哈哈', '哈哈哈', '呵呵', '笑死', '真的假的', '真的啊', '是吗',
    'ok', 'okay', 'yes', 'no', 'lol', 'haha',
}
QUESTION_MARKERS = ('?', '？', '吗', '嘛', '咋', '怎么', '谁', '什么', '几点')
INBOUND_SKIP_SIGNALS = (
    (
        'ai_challenge',
        (
            '像ai', '像 ai', 'ai润', 'ai味', '你是ai', '你是 ai',
            '机器人', 'chatgpt', 'gpt味',
        ),
    ),
    (
        'anti_spam_signal',
        (
            '严打', '刷屏', '洗版', '禁言', '举报', '封号',
            '处罚', '监控清单', '别水了', '别刷了',
        ),
    ),
    (
        'adult_service',
        (
            '抓龙筋', '抓龙', '丝足', '寸止', '裸嗨', '根浴',
            '商k', 'mmc', '会所', '嫩妹', '空降', '外围',
            '选榜老师', '精选榜老师',
        ),
    ),
    (
        'nonconsensual_recording',
        (
            '偷拍', '偷偷拍', '拍脸', '拍正面', '拍视频',
            '不能拍脸',
        ),
    ),
    (
        'minor_or_age_risk',
        (
            '未成年', '初中生', '高中生', '幼女', '萝莉',
            '才18岁', '才十八岁', '破处',
        ),
    ),
    (
        'grey_area',
        (
            '灰产', '黑产', '暗网', '查q绑', 'q绑', '绑号',
            '账号买卖', '广告', 'spam',
        ),
    ),
)


def _looks_like_question(text):
    return any(marker in str(text or '') for marker in QUESTION_MARKERS)


def _is_short_ack(text):
    punctuation = string.punctuation + '，。！？、；：「」『』（）【】《》… '
    compact = ''.join(ch for ch in str(text or '').casefold().strip()
                      if ch not in punctuation)
    if not compact:
        return True
    return compact in SHORT_ACKS or len(compact) <= 1


def _normalized_signal_text(text):
    return str(text or '').casefold().replace(' ', '')


def classify_inbound_signal(text):
    compact = _normalized_signal_text(text)
    if not compact:
        return None
    for reason, terms in INBOUND_SKIP_SIGNALS:
        for term in terms:
            if _normalized_signal_text(term) in compact:
                return reason
    return None


def evaluate_message_batch(text, round_config, reply_policy, initiative,
                           character=None, mentions_me=False, me_names=None,
                           rng=None):
    rng = rng or random
    character = character or {}
    actions = character.get('actions') or ['reply', 'skip']
    evaluators = set(character.get('evaluators') or [])
    text = str(text or '').strip()
    if not text:
        return {'should_prompt': False, 'reason': 'empty', 'action': 'skip'}
    inbound_skip_reason = classify_inbound_signal(text)
    if inbound_skip_reason:
        return {
            'should_prompt': False,
            'reason': inbound_skip_reason,
            'action': 'skip',
        }
    if (round_config.get('skip_short_ack')
            or 'skip_short_ack' in evaluators) and _is_short_ack(text):
        return {'should_prompt': False, 'reason': 'short_ack', 'action': 'skip'}

    if mentions_me:
        probability = round_config.get('mention_reply_probability')
        if probability is None:
            probability = round_config.get('reply_probability', 1.0)
    else:
        probability = round_config.get('reply_probability', 1.0)
    probability = float(probability)

    if probability < 0.0 or probability > 1.0:
        raise ValueError('reply probability must be between 0 and 1.')
    if probability <= 0.0:
        return {
            'should_prompt': False,
            'reason': 'probability',
            'action': 'skip',
        }
    if probability < 1.0 and rng.random() > probability:
        return {
            'should_prompt': False,
            'reason': 'probability',
            'action': 'skip',
        }

    if 'reply' in actions:
        action = 'reply'
    elif 'ask_open_question' in actions and _looks_like_question(text):
        action = 'ask_open_question'
    elif 'light_joke' in actions:
        action = 'light_joke'
    else:
        action = 'skip'
    return {
        'should_prompt': action != 'skip',
        'reason': 'prompt' if action != 'skip' else 'no_action',
        'action': action,
    }
