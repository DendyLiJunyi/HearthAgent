"""Lossless, schema-bound null elision for already-redacted board projections."""
import copy
import json

from runtime import ROOT

DEFAULTS = json.loads((ROOT / 'config/model/card-defaults.json').read_text(encoding='utf-8'))
ENCODING = 'nullable_card_defaults_v1'
MEANING = ('In each hand, in_play and graveyard card, missing fields equal card_defaults. '
           'Merge nested combat defaults too. Null means unknown, never zero or false. '
           'No cards or known values have been removed.')


def difference(value, defaults):
    if not isinstance(value, dict) or set(value) != set(defaults):
        raise ValueError('card schema differs from encoding defaults')
    result = {}
    for key, default in defaults.items():
        if isinstance(default, dict):
            nested = difference(value[key], default)
            if nested:
                result[key] = nested
        elif value[key] is not None:
            result[key] = value[key]
    return result


def restore(value, defaults):
    if not isinstance(value, dict) or not set(value) <= set(defaults):
        raise ValueError('unknown compact card field')
    result = copy.deepcopy(defaults)
    for key, item in value.items():
        result[key] = restore(item, defaults[key]) if isinstance(defaults[key], dict) else item
    return result


def encode(board):
    result = copy.deepcopy(board)
    for player in result['players']:
        for zone in ('hand', 'in_play', 'graveyard'):
            player[zone] = [difference(card, DEFAULTS) for card in player[zone]]
    return {'encoding': ENCODING, 'meaning': MEANING, 'card_defaults': copy.deepcopy(DEFAULTS),
            'board': result}


def decode(encoded):
    if (encoded['encoding'] != ENCODING or encoded['card_defaults'] != DEFAULTS
            or encoded['meaning'] != MEANING):
        raise ValueError('unknown encoding schema')
    result = copy.deepcopy(encoded['board'])
    for player in result['players']:
        for zone in ('hand', 'in_play', 'graveyard'):
            player[zone] = [restore(card, DEFAULTS) for card in player[zone]]
    return result
