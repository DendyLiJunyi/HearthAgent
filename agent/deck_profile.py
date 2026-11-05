"""Deck identity metadata, independent of observed in-game costs and legal moves."""
import base64
import json
from pathlib import Path

STANDARD_WARRIOR = Path(__file__).resolve().parents[1] / 'config/decks/standard-warrior-cannon.json'


def decode(code):
    data = base64.b64decode(code, validate=True)
    at = 0

    def uint():
        nonlocal at
        value = 0
        for shift in range(0, 35, 7):
            if at >= len(data):
                raise ValueError('truncated deck code')
            byte = data[at]
            at += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('invalid deck integer')

    if [uint(), uint()] != [0, 1]:
        raise ValueError('unsupported deck code')
    mode = {1: 'wild', 2: 'standard'}.get(uint())
    if not mode or uint() != 1:
        raise ValueError('unsupported deck format or heroes')
    hero = uint()
    cards = {}
    for fixed in (1, 2, None):
        entries = uint()
        if entries > 100:
            raise ValueError('too many cards')
        for _ in range(entries):
            card = uint()
            count = fixed or uint()
            if card in cards or not card or not 1 <= count <= 100:
                raise ValueError('invalid deck entry')
            cards[card] = count
    if at < len(data) and uint() != 0:
        raise ValueError('sideboards unsupported')
    if at != len(data):
        raise ValueError('trailing deck data')
    return mode, hero, cards


def load_profile(path, mode):
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    decoded_mode, hero, counts = decode(profile['deck_code'])
    if profile['mode'] != mode or decoded_mode != mode:
        raise ValueError('deck profile does not match selected mode')
    if sum(counts.values()) != 30 or counts != {c['dbfId']: c['count'] for c in profile['cards']}:
        raise ValueError('deck profile does not match its 30-card code')
    if 'hero_dbf_id' in profile and profile['hero_dbf_id'] != hero:
        raise ValueError('deck hero does not match its code')
    return profile
