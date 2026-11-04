"""Screen positions for each action, in client pixels of a 16:9 window.

Measured from one 1920x1080 capture: heroes, hero power, End Turn and a six-card hand.
Everything else (other hand sizes, minion rows, mulligan and discover cards) is an estimate.
A wrong click is caught afterwards because the logged SendOption will not match the plan.
Run `python -m agent.cli preview` on a real frame before trusting these numbers.
"""
BASE_W, BASE_H = 1920, 1080
CENTER_X = 965
END_TURN = (1558, 492)
LOCAL_HERO = (965, 825)
ENEMY_HERO = (965, 195)
HERO_POWER = (1138, 830)
LOCAL_MINION_Y = 590
ENEMY_MINION_Y = 380
MINION_SPACING = 138
HAND_Y = 1010
HAND_CENTER_X = 915  # The fan sits left of the board center, measured with six cards.
# Center-to-center spacing by hand size. Six, nine and ten were measured, the others are estimates.
HAND_SPACING = {1: 0, 2: 170, 3: 160, 4: 140, 5: 115, 6: 100, 7: 86, 8: 68, 9: 60, 10: 54}
# Large hands overlap, so aim lower, where each card shows a wider strip. Eight is an estimate.
LARGE_HAND_CENTER = {8: 890, 9: 884, 10: 884}
LARGE_HAND_Y = 1030
PLAY_DROP = (965, 560)
CANCEL_POINT = (1300, 490)  # Empty board between the minion rows, for a right-click that drops a stuck arrow.
CHOICE_Y = 500
CHOICE_SPACING = {1: 330, 2: 330, 3: 330, 4: 373, 5: 260}  # 4 measured live; 5 not yet seen
MULLIGAN_Y = 500
# Going second, the log lists four cards and The Coin, but the screen shows only the four cards.
# (cards shown, spacing, center), measured from live frames.
MULLIGAN_ROW = {3: (3, 342, 962), 4: (4, 257, 964), 5: (4, 257, 964)}
MULLIGAN_CONFIRM = (960, 850)
# Measured from a capture of N'Zoth's picker with four abilities. Other counts are estimates.
ABILITY_Y = 530
ABILITY_SPACING = 313
PICKER_WAIT = 1.2


class GeometryError(ValueError):
    pass


def row_x(index, count, spacing, center=CENTER_X):
    return round(center + (index - (count - 1) / 2) * spacing)


def hand_point(index, count):
    if not 0 <= index < count or count not in HAND_SPACING:
        raise GeometryError(f'no hand position for card {index} of {count}')
    if count in LARGE_HAND_CENTER:
        return row_x(index, count, HAND_SPACING[count], LARGE_HAND_CENTER[count]), LARGE_HAND_Y
    return row_x(index, count, HAND_SPACING[count], HAND_CENTER_X), HAND_Y


def minion_point(index, count, local):
    if not 0 <= index < count or count > 7:
        raise GeometryError(f'no minion position for {index} of {count}')
    return row_x(index, count, MINION_SPACING), LOCAL_MINION_Y if local else ENEMY_MINION_Y


def placement_point(position, count):
    """Drop point for a new minion, where position is the 1-based slot it should take."""
    if count == 0:
        return PLAY_DROP
    # A gap between slot centers, in the row as it looks before the card lands.
    return row_x(position - 1.5, count, MINION_SPACING), LOCAL_MINION_Y


def choice_point(index, count):
    if not 0 <= index < count or count > 5:
        raise GeometryError(f'no choice position for {index} of {count}')
    return row_x(index, count, CHOICE_SPACING[count], 960), CHOICE_Y


def mulligan_point(index, count):
    if count not in MULLIGAN_ROW or not 0 <= index < MULLIGAN_ROW[count][0]:
        raise GeometryError(f'no mulligan position for {index} of {count}')
    shown, spacing, center = MULLIGAN_ROW[count]
    return row_x(index, shown, spacing, center), MULLIGAN_Y


def ability_point(slot, total):
    if not 0 <= slot < total or total > 4:
        raise GeometryError(f'no ability position for {slot} of {total}')
    return row_x(slot, total, ABILITY_SPACING, 960), ABILITY_Y


def entity_point(state, entity):
    """Where an entity on the battlefield is, using its logged slot and never an image guess."""
    you, opponent = state['you'], state['opponent']
    if you['hero'] and you['hero']['id'] == entity:
        return LOCAL_HERO
    if opponent['hero'] and opponent['hero']['id'] == entity:
        return ENEMY_HERO
    for player, local in ((you, True), (opponent, False)):
        minions = player['minions']
        for index, minion in enumerate(minions):
            if minion['id'] == entity:
                return minion_point(index, len(minions), local)
    raise GeometryError(f'entity {entity} is not on the battlefield')


def hand_index(state, entity):
    hand = state['you'].get('hand', [])
    for index, card in enumerate(hand):
        if card['id'] == entity:
            return index, len(hand)
    raise GeometryError(f'entity {entity} is not in hand')


def plan_action(state, candidate):
    """Turn one candidate into mouse gestures. Raises instead of guessing.

    Gestures are `click`, `drag` and `wait`, so a plan can be recorded, drawn or sent.
    """
    if candidate['kind'] == 'end_turn':
        return [('click', END_TURN)]
    source, target = candidate['source'], candidate['target']
    you = state['you']
    if you['hero_power'] and you['hero_power']['id'] == source:
        gestures = [('click', HERO_POWER)]
        if target:
            gestures.append(('click', entity_point(state, target)))
        return gestures
    if you['hero'] and you['hero']['id'] == source:
        if not target:
            raise GeometryError('hero action has no target')
        return [('drag', LOCAL_HERO, entity_point(state, target))]
    if any(card['id'] == source for card in you.get('hand', [])):
        return _plan_hand(state, candidate)
    if any(m['id'] == source for m in you['minions']):
        point = entity_point(state, source)
        if candidate.get('sub', -1) >= 0:
            # A Titan or Old God: click it, pick an ability, then pick any target.
            gestures = [('click', point), ('wait', PICKER_WAIT),
                        ('click', ability_point(candidate['sub_slot'], candidate['sub_total']))]
            if target:
                gestures += [('wait', PICKER_WAIT), ('click', entity_point(state, target))]
            return gestures
        if target:
            return [('drag', point, entity_point(state, target))]
        return [('click', point)]  # Location with no target
    raise GeometryError(f'source {source} is not an actionable local entity')


def _plan_hand(state, candidate):
    source, target = candidate['source'], candidate['target']
    you = state['you']
    index, count = hand_index(state, source)
    card = you['hand'][index]
    start = hand_point(index, count)
    if card['type'] in ('MINION', 'LOCATION'):
        if len(you['minions']) >= 7:
            raise GeometryError('board is full')
        # New minions go on the right. A later policy can use other slots.
        gestures = [('drag', start, placement_point(len(you['minions']) + 1, len(you['minions'])))]
        if target:
            gestures.append(('click', entity_point(state, target)))
    elif target:
        gestures = [('drag', start, entity_point(state, target))]
    else:
        gestures = [('drag', start, PLAY_DROP)]
    if candidate.get('sub', -1) >= 0:
        # Choose-one cards appear after the drop, at one row of two.
        gestures.insert(1, ('click', choice_point(candidate['sub_slot'], candidate['sub_total'])))
    return gestures


def expected_position(state, candidate):
    """The placement encoded by our gesture, not a new policy-selected action."""
    for card in state['you'].get('hand', []):
        if card['id'] == candidate['source'] and card['type'] in ('MINION', 'LOCATION'):
            return len(state['you']['minions']) + 1
    return 0


def end_turn_lit(rgb):
    """True when the End Turn button shows the player's turn, so the game is taking input.

    The log reports a new turn well before the screen catches up, and drags sent in that gap are
    ignored. Lit buttons are bright with almost no blue: yellow near (137, 99, 8) or green near
    (45, 151, 10). The grey opponent-turn button is near (83, 66, 70), and transitions are dark.
    """
    red, green, blue = rgb
    return blue < 40 and max(red, green) >= 80 and max(red, green) - blue >= 60


def scale(point, window):
    """Map base pixels into a real client area. Only 16:9 is supported."""
    width, height = window['width'], window['height']
    if width <= 0 or height <= 0 or abs(width / height - BASE_W / BASE_H) > 0.01:
        raise GeometryError(f'unsupported client size {width}x{height}')
    return (window.get('left', 0) + round(point[0] * width / BASE_W),
            window.get('top', 0) + round(point[1] * height / BASE_H))
