"""Turn Power.log files into decision windows: full legal options plus the move actually sent.

Offline analysis only. The GameState stream is the client's own view, so opponent hand and
deck contents stay hidden. A window is one option packet that was answered by a SendOption.
"""
import argparse
import collections
import glob
import json
import os
import re

ENTITY = re.compile(r'id=(\d+)')
BRACKET = re.compile(r'\[entityName=(.*?) id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\S*) player=(\d+)\]')
TAG = re.compile(r'tag=(\S+) value=(\S*)')
TAG_CHANGE = re.compile(r'TAG_CHANGE Entity=(.*?) tag=(\S+) value=(\S*)')
CREATE = re.compile(r'FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)')
UPDATE = re.compile(r'(FULL_ENTITY|SHOW_ENTITY|CHANGE_ENTITY) - (?:Updating|Changing) Entity=(.*?) CardID=(\S*)')
PLAYER = re.compile(r'Player EntityID=(\d+) PlayerID=(\d+)')
GAME_ENTITY = re.compile(r'GameEntity EntityID=(\d+)')
GAME_PLAYER = re.compile(r'PlayerID=(\d+), PlayerName=(.*)$')
OPTION = re.compile(r'option (\d+) type=(\w+) mainEntity=(.*?) error=(\w+)')
SUB = re.compile(r'subOption (\d+) entity=(.*?) error=(\w+)')
TARGET = re.compile(r'target (\d+) entity=(.*?) error=(\w+)')
SEND = re.compile(r'selectedOption=(-?\d+) selectedSubOption=(-?\d+) selectedTarget=(-?\d+) selectedPosition=(-?\d+)')

KEYWORDS = ['TAUNT', 'DIVINE_SHIELD', 'STEALTH', 'FROZEN', 'CHARGE', 'RUSH', 'WINDFURY',
            'POISONOUS', 'LIFESTEAL', 'SILENCED', 'CANT_ATTACK', 'DEATHRATTLE', 'IMMUNE']


class Game:
    def __init__(self, source, number):
        self.source, self.number = source, number
        self.entities = collections.defaultdict(dict)
        self.cards = {}
        self.player_entity = {}  # player id -> entity id
        self.names = {}          # player name -> player id
        self.game_entity = None
        self.game_type = None
        self.format_type = None
        self.packet = None
        self.windows = []
        self.result = None

    def resolve(self, text, local_name):
        match = ENTITY.search(text) if text.startswith('[') else None
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        if text == 'GameEntity':
            return self.game_entity
        if text in self.names:
            return self.player_entity.get(self.names[text])
        # A name not seen yet belongs to whichever player has not been named.
        unnamed = [p for p in self.player_entity if p not in self.names.values()]
        if len(unnamed) == 1:
            self.names[text] = unnamed[0]
            return self.player_entity[unnamed[0]]
        return None


def parse_entity(text):
    match = BRACKET.search(text or '')
    if not match:
        return None
    name, entity, zone, _, card, player = match.groups()
    return {'id': int(entity), 'zone': zone, 'card': card, 'player': int(player), 'name': name}


def view(game, entity_id):
    tags = game.entities.get(entity_id, {})
    def number(key):
        try:
            return int(tags.get(key, 0))
        except ValueError:
            return 0
    return {'id': entity_id, 'card': game.cards.get(entity_id, ''), 'type': tags.get('CARDTYPE'),
            'cost': number('COST'), 'atk': number('ATK'), 'health': number('HEALTH'),
            'damage': number('DAMAGE'), 'armor': number('ARMOR'), 'durability': number('DURABILITY'),
            'pos': number('ZONE_POSITION'), 'exhausted': number('EXHAUSTED'),
            'attacks': number('NUM_ATTACKS_THIS_TURN'),
            'keywords': [k for k in KEYWORDS if tags.get(k) == '1']}


def snapshot(game, local):
    """Public state plus the local hand. Nothing here uses later log lines."""
    players = {}
    by_zone = collections.defaultdict(list)
    for entity_id, tags in game.entities.items():
        controller = tags.get('CONTROLLER')
        if controller and controller.isdigit():
            by_zone[(int(controller), tags.get('ZONE'))].append(entity_id)
    for player, entity in game.player_entity.items():
        tags = game.entities[entity]
        hero = int(tags.get('HERO_ENTITY', 0) or 0)
        in_play = [view(game, e) for e in by_zone[(player, 'PLAY')]]
        def number(key):
            try:
                return int(tags.get(key, 0))
            except ValueError:
                return 0
        players[player] = {
            'hero': view(game, hero) if hero else None,
            'mana': number('RESOURCES') - number('RESOURCES_USED') + number('TEMP_RESOURCES'),
            'max_mana': number('RESOURCES'),
            'combo': number('COMBO_ACTIVE'),
            'minions': sorted((c for c in in_play if c['type'] == 'MINION'), key=lambda c: c['pos']),
            'weapon': next((c for c in in_play if c['type'] == 'WEAPON'), None),
            'hero_power': next((c for c in in_play if c['type'] == 'HERO_POWER'), None),
            'hand_count': len(by_zone[(player, 'HAND')]),
            'deck_count': len(by_zone[(player, 'DECK')]),
            'secrets': len(by_zone[(player, 'SECRET')]),
        }
        if player == local:
            players[player]['hand'] = sorted((view(game, e) for e in by_zone[(player, 'HAND')]),
                                             key=lambda c: c['pos'])
    turn = game.entities[game.game_entity].get('TURN', '0') if game.game_entity else '0'
    return {'turn': int(turn) if turn.isdigit() else 0, 'you': players.get(local),
            'opponent': next((v for k, v in players.items() if k != local), None)}


def candidates_from(packet):
    """Every action the client reported as allowed. Position is an execution detail, so it is dropped."""
    result = []
    for option in packet['options']:
        if option['type'] == 'END_TURN':
            # The client prints END_TURN with error=INVALID even when it is sendable.
            result.append({'option': option['index'], 'sub': -1, 'target': 0, 'kind': 'end_turn', 'source': None})
            continue
        if option['error'] != 'NONE' or not option['entity']:
            continue
        subs = [s for s in option['subs'] if s['error'] == 'NONE']
        for holder, sub_index, sub_entity in ([(s, s['index'], s['entity']) for s in subs] or [(option, -1, None)]):
            targets = [t for t in holder['targets'] if t['error'] == 'NONE']
            for target in targets or [None]:
                result.append({'option': option['index'], 'sub': sub_index,
                               'target': target['entity']['id'] if target and target['entity'] else 0,
                               'kind': 'power', 'source': option['entity']['id'],
                               'sub_entity': sub_entity['id'] if sub_entity else None})
    return result


def parse_log(path, local_name):
    games, game = [], None
    pending_full = None
    for line in open(path, encoding='utf-8', errors='replace'):
        if 'GameState.' not in line:
            continue
        body = line.split(' - ', 1)[1].rstrip('\n') if ' - ' in line else ''
        stripped = body.strip()
        if 'DebugPrintPower()' in line:
            if stripped == 'CREATE_GAME':
                game = Game(os.path.basename(os.path.dirname(path)), len(games) + 1)
                games.append(game)
                pending_full = None
                continue
            if game is None:
                continue
            match = GAME_ENTITY.match(stripped)
            if match:
                game.game_entity = int(match.group(1))
                pending_full = game.game_entity
                continue
            match = PLAYER.match(stripped)
            if match:
                entity, player = int(match.group(1)), int(match.group(2))
                game.player_entity[player] = entity
                pending_full = entity
                continue
            match = CREATE.match(stripped)
            if match:
                pending_full = int(match.group(1))
                game.cards[pending_full] = match.group(2)
                continue
            match = UPDATE.match(stripped)
            if match:
                pending_full = game.resolve(match.group(2), local_name)
                if pending_full is not None and match.group(3):
                    game.cards[pending_full] = match.group(3)
                continue
            match = TAG_CHANGE.match(stripped)
            if match:
                pending_full = None
                entity = game.resolve(match.group(1), local_name)
                if entity is not None:
                    game.entities[entity][match.group(2)] = match.group(3)
                    if match.group(2) == 'PLAYSTATE' and match.group(3) in ('WON', 'LOST', 'TIED'):
                        player = next((p for p, e in game.player_entity.items() if e == entity), None)
                        if game.result is None or player == game.names.get(local_name):
                            game.result = {'player': player, 'state': match.group(3)}
                continue
            match = TAG.match(stripped)
            if match and pending_full is not None:
                game.entities[pending_full][match.group(1)] = match.group(2)
                continue
            if not stripped.startswith('tag='):
                pending_full = None
        elif game is None:
            continue
        elif 'DebugPrintGame()' in line:
            if stripped.startswith('GameType='):
                game.game_type = stripped.split('=', 1)[1]
            elif stripped.startswith('FormatType='):
                game.format_type = stripped.split('=', 1)[1]
            match = GAME_PLAYER.match(stripped)
            if match and match.group(2) != 'UNKNOWN HUMAN PLAYER':
                game.names[match.group(2)] = int(match.group(1))
        elif 'DebugPrintOptions()' in line:
            if stripped.startswith('id='):
                local = game.names.get(local_name)
                game.packet = {'id': int(stripped[3:]), 'options': [],
                               'state': snapshot(game, local) if local else None, 'local': local}
                continue
            if not game.packet:
                continue
            match = OPTION.match(stripped)
            if match:
                game.packet['options'].append({'index': int(match.group(1)), 'type': match.group(2),
                    'entity': parse_entity(match.group(3)), 'error': match.group(4), 'subs': [], 'targets': []})
                continue
            match = SUB.match(stripped)
            if match and game.packet['options']:
                game.packet['options'][-1]['subs'].append({'index': int(match.group(1)),
                    'entity': parse_entity(match.group(2)), 'error': match.group(3), 'targets': []})
                continue
            match = TARGET.match(stripped)
            if match and game.packet['options']:
                option = game.packet['options'][-1]
                # Targets printed after a subOption belong to that subOption.
                holder = option['subs'][-1] if option['subs'] else option
                holder['targets'].append({'index': int(match.group(1)),
                    'entity': parse_entity(match.group(2)), 'error': match.group(3)})
        elif 'SendOption()' in line and game.packet:
            match = SEND.search(stripped)
            if match and game.packet['state']:
                game.windows.append({'packet': game.packet['id'], 'state': game.packet['state'],
                    'candidates': candidates_from(game.packet),
                    'sent': {'option': int(match.group(1)), 'sub': int(match.group(2)),
                             'target': int(match.group(3)), 'position': int(match.group(4))},
                    'cards': {str(k): v for k, v in game.cards.items()}})
            game.packet = None
    return games


def local_name_of(path):
    counts = collections.Counter()
    for line in open(path, encoding='utf-8', errors='replace'):
        if 'GameState.DebugPrintGame()' in line:
            match = GAME_PLAYER.search(line.split(' - ', 1)[1].strip())
            if match and match.group(2) != 'UNKNOWN HUMAN PLAYER':
                counts[match.group(2)] += 1
    return counts.most_common(1)[0][0] if counts else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('logs', help='glob of Power.log files')
    parser.add_argument('output')
    args = parser.parse_args()
    rows, stats = [], collections.Counter()
    for path in sorted(glob.glob(args.logs)):
        if os.path.getsize(path) == 0:
            continue
        local_name = local_name_of(path)
        if not local_name:
            continue
        for game in parse_log(path, local_name):
            group = f'{game.source}/game-{game.number}'
            local = game.names.get(local_name)
            won = None
            if game.result:
                state = game.result['state']
                won = (state == 'WON') == (game.result['player'] == local) if state != 'TIED' else None
            stats['games'] += 1
            for ordinal, window in enumerate(game.windows):
                stats['windows'] += 1
                sent = window['sent']
                match = [i for i, c in enumerate(window['candidates'])
                         if c['option'] == sent['option'] and c['sub'] == sent['sub'] and c['target'] == sent['target']]
                if len(match) != 1:
                    stats['unmatched_send'] += 1
                    continue
                stats['matched'] += 1
                rows.append({'group': group, 'ordinal': ordinal, 'game_type': game.game_type,
                             'format': game.format_type, 'won': won, 'state': window['state'],
                             'candidates': window['candidates'], 'label': match[0], 'cards': window['cards']})
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
