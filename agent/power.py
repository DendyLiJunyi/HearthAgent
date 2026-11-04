"""Incremental Power.log reader for live play and offline replay.

Only GameState lines change state. PowerTaskList repeats the same events for animation and
must not be applied twice. Opponent hand and deck contents stay hidden because the client
log itself does not reveal them.
"""
import collections
import re

BRACKET = re.compile(r'\[entityName=(.*?) id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\S*) player=(\d+)\]')
ENTITY_ID = re.compile(r'id=(\d+)')
TAG = re.compile(r'tag=(\S+) value=(\S*)')
TAG_CHANGE = re.compile(r'TAG_CHANGE Entity=(.*?) tag=(\S+) value=(\S*)')
CREATE = re.compile(r'FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)')
UPDATE = re.compile(r'(?:FULL_ENTITY|SHOW_ENTITY|CHANGE_ENTITY) - (?:Updating|Changing) Entity=(.*?) CardID=(\S*)')
PLAYER = re.compile(r'Player EntityID=(\d+) PlayerID=(\d+)')
GAME_ENTITY = re.compile(r'GameEntity EntityID=(\d+)')
GAME_PLAYER = re.compile(r'PlayerID=(\d+), PlayerName=(.*)$')
OPTION = re.compile(r'option (\d+) type=(\w+) mainEntity=(.*?) error=(\w+)')
SUB = re.compile(r'subOption (\d+) entity=(.*?) error=(\w+)')
TARGET = re.compile(r'target (\d+) entity=(.*?) error=(\w+)')
SEND = re.compile(r'selectedOption=(-?\d+) selectedSubOption=(-?\d+) selectedTarget=(-?\d+) selectedPosition=(-?\d+)')
CHOICE = re.compile(r'id=(\d+) Player=(.*?) TaskList=\S* ChoiceType=(\w+) CountMin=(\d+) CountMax=(\d+)')
CHOICE_ENTITY = re.compile(r'Entities\[(\d+)\]=(.*)$')
CHOSEN = re.compile(r'id=(\d+) Player=(.*?) EntitiesCount=(\d+)')

UNKNOWN_NAME = 'UNKNOWN HUMAN PLAYER'
KEYWORDS = ['TAUNT', 'DIVINE_SHIELD', 'STEALTH', 'FROZEN', 'CHARGE', 'RUSH', 'WINDFURY',
            'POISONOUS', 'LIFESTEAL', 'SILENCED', 'CANT_ATTACK', 'DEATHRATTLE', 'IMMUNE']


def parse_entity(text):
    match = BRACKET.search(text or '')
    if not match:
        return None
    name, entity, zone, zone_position, card, player = match.groups()
    return {'id': int(entity), 'zone': zone, 'zone_position': int(zone_position),
            'card': card, 'player': int(player), 'name': name}


class AnimationBacklog:
    """Power lines the client has received but has not reached in its animation queue.

    GameState lines are logged on receipt. PowerTaskList repeats them when the client processes them.
    Saved runs show input is ignored while this is large: 18 of 104 moves failed at 13 or more pending
    lines, against 4 of 177 at 12 or fewer. A few trailing lines are normally never repeated, so a
    repeated line also clears anything older, and callers compare against a limit instead of zero.
    """
    def __init__(self):
        self.pending = collections.deque()

    @property
    def size(self):
        return len(self.pending)

    def received(self, body):
        self.pending.append(body)

    def played(self, body):
        if body in self.pending:
            while self.pending.popleft() != body:
                pass


class Game:
    def __init__(self, number):
        self.number = number
        self.entities = collections.defaultdict(dict)
        self.cards = {}
        self.player_entity = {}
        self.names = {}
        self.game_entity = None
        self.game_type = None
        self.format_type = None
        self.local = None
        self.packet = None        # latest option packet not answered yet
        self.choice = None        # latest local entity choice not answered yet
        self.sends = []           # answered option packets, oldest first
        self.choices_sent = []
        self.result = None
        self.revision = 0
        self.option_lines = 0

    @property
    def over(self):
        return self.result is not None

    def resolve(self, text):
        match = ENTITY_ID.search(text) if text.startswith('[') else None
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        if text == 'GameEntity':
            return self.game_entity
        if text in self.names:
            return self.player_entity.get(self.names[text])
        # The opponent can be logged under a placeholder and later under a real name.
        # Any name other than the local player's must therefore be the other player.
        others = [p for p in self.player_entity if p != self.local]
        if self.local is not None and len(others) == 1:
            self.names[text] = others[0]
            return self.player_entity[others[0]]
        unnamed = [p for p in self.player_entity if p not in self.names.values()]
        if len(unnamed) == 1:
            self.names[text] = unnamed[0]
            return self.player_entity[unnamed[0]]
        return None

    def tag(self, entity, key):
        return self.entities.get(entity, {}).get(key)

    def number_tag(self, entity, key):
        value = self.tag(entity, key)
        return int(value) if value and value.lstrip('-').isdigit() else 0

    def view(self, entity):
        tags = self.entities.get(entity, {})
        number = lambda key: self.number_tag(entity, key)
        return {'id': entity, 'card': self.cards.get(entity, ''), 'type': tags.get('CARDTYPE'),
                'cost': number('COST'), 'atk': number('ATK'), 'health': number('HEALTH'),
                'damage': number('DAMAGE'), 'armor': number('ARMOR'), 'durability': number('DURABILITY'),
                'pos': number('ZONE_POSITION'), 'exhausted': number('EXHAUSTED'),
                'attacks': number('NUM_ATTACKS_THIS_TURN'),
                'keywords': [k for k in KEYWORDS if tags.get(k) == '1']}

    def snapshot(self):
        """State at this instant, built only from lines already read."""
        zones = collections.defaultdict(list)
        for entity, tags in self.entities.items():
            controller = tags.get('CONTROLLER')
            if controller and controller.isdigit():
                zones[(int(controller), tags.get('ZONE'))].append(entity)
        players = {}
        for player, entity in self.player_entity.items():
            hero = self.number_tag(entity, 'HERO_ENTITY')
            in_play = [self.view(e) for e in zones[(player, 'PLAY')]]
            used = self.number_tag(entity, 'RESOURCES_USED')
            players[player] = {
                'hero': self.view(hero) if hero else None,
                'mana': self.number_tag(entity, 'RESOURCES') - used + self.number_tag(entity, 'TEMP_RESOURCES'),
                'max_mana': self.number_tag(entity, 'RESOURCES'),
                'combo': self.number_tag(entity, 'COMBO_ACTIVE'),
                'minions': sorted((c for c in in_play if c['type'] in ('MINION', 'LOCATION')),
                                  key=lambda c: c['pos']),
                'weapon': next((c for c in in_play if c['type'] == 'WEAPON'), None),
                'hero_power': next((c for c in in_play if c['type'] == 'HERO_POWER'), None),
                'hand_count': len(zones[(player, 'HAND')]),
                'deck_count': len(zones[(player, 'DECK')]),
                'secrets': len(zones[(player, 'SECRET')]),
            }
            if player == self.local:
                players[player]['hand'] = sorted((self.view(e) for e in zones[(player, 'HAND')]),
                                                 key=lambda c: c['pos'])
        turn = self.tag(self.game_entity, 'TURN') if self.game_entity else None
        return {'turn': int(turn) if turn and turn.isdigit() else 0,
                'step': self.tag(self.game_entity, 'STEP') if self.game_entity else None,
                'you': players.get(self.local),
                'opponent': next((v for k, v in players.items() if k != self.local), None)}

    def card_map(self):
        return {str(k): v for k, v in self.cards.items()}


def candidates_from(packet):
    """Every action the client itself reported as allowed.

    Position is left out because it only affects where a minion lands, not which action it is.
    """
    result = []
    for option in packet['options']:
        if option['type'] == 'END_TURN':
            # The client prints END_TURN with error=INVALID in windows where it is sendable.
            result.append({'option': option['index'], 'sub': -1, 'target': 0, 'kind': 'end_turn', 'source': None})
            continue
        if option['error'] != 'NONE' or not option['entity']:
            continue
        subs = [s for s in option['subs'] if s['error'] == 'NONE']
        # The log lists playable abilities first, but the picker keeps a fixed order that
        # matches entity IDs. Seen on N'Zoth, where log index 1 was the third card on screen.
        on_screen = sorted(s['entity']['id'] for s in option['subs'] if s['entity'])
        holders = [(s, s['index'], s['entity']) for s in subs] or [(option, -1, None)]
        for holder, sub_index, sub_entity in holders:
            targets = [t for t in holder['targets'] if t['error'] == 'NONE']
            for target in targets or [None]:
                result.append({'option': option['index'], 'sub': sub_index,
                               'target': target['entity']['id'] if target and target['entity'] else 0,
                               'kind': 'power', 'source': option['entity']['id'],
                               'sub_entity': sub_entity['id'] if sub_entity else None,
                               'sub_card': sub_entity['card'] if sub_entity else None,
                               'sub_slot': on_screen.index(sub_entity['id']) if sub_entity else None,
                               'sub_total': len(on_screen)})
    return result


class PowerLog:
    """Feed lines in order. `games[-1]` is the current game."""

    def __init__(self, local_name=None):
        self.local_name = local_name
        self.games = []
        self.lines = 0
        self.malformed = 0
        self._entity = None
        self._choice = None
        self._chosen_pending = None
        self.backlog = AnimationBacklog()

    @property
    def game(self):
        return self.games[-1] if self.games else None

    def _set_local(self, game):
        """A BattleTag has '#'. The Innkeeper and other AI names do not."""
        if game.local is not None:
            return
        if self.local_name and self.local_name in game.names:
            game.local = game.names[self.local_name]
            return
        tagged = [(name, player) for name, player in game.names.items() if '#' in name and name != UNKNOWN_NAME]
        if len(tagged) == 1:
            self.local_name, game.local = tagged[0]

    def feed(self, line):
        self.lines += 1
        if 'PowerTaskList.DebugPrintPower()' in line and ' - ' in line:
            self.backlog.played(line.split(' - ', 1)[1].strip())
            return
        if 'GameState.' not in line or ' - ' not in line:
            return
        body = line.split(' - ', 1)[1].rstrip('\r\n')
        stripped = body.strip()
        if 'DebugPrintPower()' in line:
            self.backlog.received(stripped)
            self._power(stripped)
        elif self.game is None:
            return
        elif 'DebugPrintGame()' in line:
            self._game_info(stripped)
        elif 'DebugPrintOptions()' in line:
            self._options(stripped)
        elif 'SendOption()' in line:
            self._send(stripped)
        elif 'DebugPrintEntityChoices()' in line:
            self._choice_line(stripped)
        elif 'DebugPrintEntitiesChosen()' in line:
            self._chosen(stripped)

    def _power(self, stripped):
        if stripped == 'CREATE_GAME':
            self.backlog = AnimationBacklog()
            self.games.append(Game(len(self.games) + 1))
            self._entity = None
            self._choice = None
            self._chosen_pending = None
            return
        game = self.game
        if game is None:
            return
        game.revision += 1
        for pattern, action in ((GAME_ENTITY, self._on_game_entity), (PLAYER, self._on_player),
                                (CREATE, self._on_create), (UPDATE, self._on_update),
                                (TAG_CHANGE, self._on_tag_change)):
            match = pattern.match(stripped)
            if match:
                action(game, match)
                return
        match = TAG.match(stripped)
        if match:
            if self._entity is not None:
                game.entities[self._entity][match.group(1)] = match.group(2)
        else:
            self._entity = None

    def _on_game_entity(self, game, match):
        game.game_entity = self._entity = int(match.group(1))

    def _on_player(self, game, match):
        entity, player = int(match.group(1)), int(match.group(2))
        game.player_entity[player] = entity
        self._entity = entity

    def _on_create(self, game, match):
        self._entity = int(match.group(1))
        game.cards[self._entity] = match.group(2)

    def _on_update(self, game, match):
        self._entity = game.resolve(match.group(1))
        if self._entity is not None and match.group(2):
            game.cards[self._entity] = match.group(2)

    def _on_tag_change(self, game, match):
        self._entity = None
        entity = game.resolve(match.group(1))
        if entity is None:
            self.malformed += 1
            return
        game.entities[entity][match.group(2)] = match.group(3)
        if match.group(2) == 'PLAYSTATE' and match.group(3) in ('WON', 'LOST', 'TIED'):
            player = next((p for p, e in game.player_entity.items() if e == entity), None)
            if game.result is None or player == game.local:
                won = None if match.group(3) == 'TIED' else (match.group(3) == 'WON') == (player == game.local)
                game.result = {'won': won}

    def _game_info(self, stripped):
        game = self.game
        if stripped.startswith('GameType='):
            game.game_type = stripped.split('=', 1)[1]
        elif stripped.startswith('FormatType='):
            game.format_type = stripped.split('=', 1)[1]
        match = GAME_PLAYER.match(stripped)
        if match and match.group(2) != UNKNOWN_NAME:
            game.names[match.group(2)] = int(match.group(1))
            self._set_local(game)

    def _options(self, stripped):
        game = self.game
        game.option_lines += 1
        if stripped.startswith('id='):
            game.packet = {'id': int(stripped[3:]), 'options': [], 'state': game.snapshot(),
                           'revision': game.revision, 'cards': game.card_map()}
            return
        if not game.packet:
            return
        options = game.packet['options']
        match = OPTION.match(stripped)
        if match:
            options.append({'index': int(match.group(1)), 'type': match.group(2),
                            'entity': parse_entity(match.group(3)), 'error': match.group(4),
                            'subs': [], 'targets': []})
            return
        match = SUB.match(stripped)
        if match and options:
            options[-1]['subs'].append({'index': int(match.group(1)), 'entity': parse_entity(match.group(2)),
                                        'error': match.group(3), 'targets': []})
            return
        match = TARGET.match(stripped)
        if match and options:
            # A target printed after a subOption belongs to that subOption.
            holder = options[-1]['subs'][-1] if options[-1]['subs'] else options[-1]
            holder['targets'].append({'index': int(match.group(1)), 'entity': parse_entity(match.group(2)),
                                      'error': match.group(3)})

    def _send(self, stripped):
        game = self.game
        match = SEND.search(stripped)
        if not match or not game.packet:
            return
        sent = dict(zip(('option', 'sub', 'target', 'position'), map(int, match.groups())))
        game.sends.append({'packet': game.packet, 'sent': sent})
        game.packet = None

    def _choice_line(self, stripped):
        game = self.game
        header = CHOICE.match(stripped)
        if header:
            number, player, kind, low, high = header.groups()
            self._choice = {'id': int(number), 'player_name': player, 'type': kind, 'min': int(low),
                            'max': int(high), 'entities': [], 'source': None}
            # Only the local player's name appears in its own packets.
            if player == self.local_name or (game.local is not None and game.names.get(player) == game.local):
                game.choice = self._choice
            return
        if not self._choice:
            return
        if stripped.startswith('Source='):
            self._choice['source'] = parse_entity(stripped[7:])
            return
        match = CHOICE_ENTITY.match(stripped)
        if match:
            self._choice['entities'].append(parse_entity(match.group(2)))

    def _chosen(self, stripped):
        game = self.game
        match = CHOSEN.match(stripped)
        if match:
            self._chosen_pending = None
            number, player, count = match.groups()
            if (game.choice and int(number) == game.choice['id']
                    and player == game.choice['player_name']):
                receipt = dict(game.choice, selected=[], expected_count=int(count), complete=False)
                game.choices_sent.append(receipt)
                self._chosen_pending = receipt
                if int(count) == 0:
                    receipt['complete'] = True
                    game.choice = None
            return
        receipt = self._chosen_pending
        entity_line = CHOICE_ENTITY.match(stripped)
        if receipt is None or receipt['complete'] or not entity_line:
            return
        entity = parse_entity(entity_line.group(2))
        if entity is None or int(entity_line.group(1)) != len(receipt['selected']):
            return  # Incomplete/malformed evidence can never confirm a choice.
        receipt['selected'].append(entity['id'])
        if len(receipt['selected']) == receipt['expected_count']:
            receipt['complete'] = True
            if game.choice and game.choice['id'] == receipt['id']:
                game.choice = None
