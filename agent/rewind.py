"""Recognize timeline controls by card ID, never by their order or mana costs."""
KEEP = 'TIME_000ta'
REWIND = 'TIME_000tb'


def option_ids(entities, cards):
    return [cards.get(str(e['id'])) or e.get('card', '') for e in entities]


def is_timeline(ids):
    return len(ids) == 2 and set(ids) == {KEEP, REWIND}


def choose(choice, cards):
    ids = option_ids(choice['entities'], cards)
    if not is_timeline(ids):
        return None
    pick, reason = KEEP, 'rewind:keep_unknown_result'
    source = choice.get('source') or {}
    source_id = cards.get(str(source.get('id'))) or source.get('card', '')
    state = choice.get('state')
    if source_id == 'TIME_034' and state:
        you, enemy = state['you'], state['opponent']
        own, other = you.get('weapon'), enemy.get('weapon')
        if own and other:
            attack, opposing = own['atk'], other['atk']
            life = you['hero']['health'] - you['hero']['damage'] + you['hero']['armor']
            # A narrow reroll preference, not a simulation of the random weapon pool.
            if opposing >= life or opposing >= attack + 3 or attack <= 1:
                pick, reason = REWIND, 'rewind:announcer_bad_weapons'
            else:
                reason = 'rewind:announcer_keep_weapons'
    return ids.index(pick), reason
