"""The play loop. Input is injected, so offline tests and live play run the same logic.

Rules that keep a wrong click from becoming a runaway:
- Only practice games are acted on, plus friendly challenges when the player says the opponent
  agreed. Ranked, casual, arena and anything unrecognized are always refused.
- Nothing is sent until the log has been quiet for `settle` seconds.
- If a screen check is supplied, moves also wait for the End Turn button to light up, because
  the log runs ahead of the screen. An unreadable button only delays play by `screen_timeout`.
- Before input, the packet and revision are re-read. Any change cancels the action.
- After input, the logged SendOption must match the plan. Otherwise the agent stops.
- A single-gesture move can be resent only if the log shows nothing was sent and nothing changed.
  In a live test, first-of-turn drags sent nothing and then worked unchanged, so this is bounded,
  not open-ended. Multi-step moves are never resent, and the last timeout hands the game back.
"""
import time

from . import geometry
from .power import PowerLog, candidates_from

ALLOWED_GAME_TYPES = {'GT_VS_AI'}
FRIENDLY_GAME_TYPE = 'GT_VS_FRIEND'
CANCEL = ('right_click', geometry.CANCEL_POINT)


class Stop(Exception):
    """The agent must stop and leave the game to the player."""


class StateChanged(Stop):
    """The log moved on while deciding."""


class NoSend(Stop):
    """Input went out but the game logged no move."""


class RecordingInput:
    """Sends nothing. Gestures are kept for inspection."""

    def __init__(self):
        self.gestures = []

    def send(self, gestures):
        self.gestures.append(gestures)

    def aborted(self):
        return False


class Agent:
    def __init__(self, reader, policy, inputs, *, settle=1.5, confirm_timeout=5.0, max_actions=200,
                 max_attempts=3, screen_ready=None, screen_timeout=25.0, friend_agreed=False,
                 lit_required=2, choice_timeout=None, mulligan_ready=None, mulligan_timeout=40.0, idle_limit=None,
                 clock=time.monotonic, sleep=time.sleep, log=print, before_input=None):
        self.reader, self.policy, self.inputs = reader, policy, inputs
        self.power = PowerLog()
        self.settle, self.confirm_timeout, self.max_actions = settle, confirm_timeout, max_actions
        self.clock, self.sleep, self.log = clock, sleep, log
        self.actions = 0
        self.max_attempts = max_attempts
        self.friend_agreed = friend_agreed
        self.screen_ready, self.screen_timeout = screen_ready, screen_timeout
        self.screen_wait = None  # (game number, packet id, deadline)
        self.lit_reads = 0
        self.lit_required = lit_required
        self.choice_timeout = confirm_timeout if choice_timeout is None else choice_timeout
        self.mulligan_ready, self.mulligan_timeout = mulligan_ready, mulligan_timeout
        self.mulligan_wait = None
        self.idle_limit = idle_limit
        self.last_line_time = clock()
        self.handled_choice = None
        self.before_input = before_input

    def pump(self):
        """Read any new lines, returning True if there were some."""
        lines = self.reader()
        for line in lines:
            self.power.feed(line)
        if lines:
            self.last_line_time = self.clock()
        return bool(lines)

    def quiet(self):
        return self.clock() - self.last_line_time >= self.settle

    def check_allowed(self, game):
        friendly = self.friend_agreed and game.game_type == FRIENDLY_GAME_TYPE
        if game.game_type not in ALLOWED_GAME_TYPES and not friendly:
            raise Stop(f'refusing to act in {game.game_type}: only practice games and agreed friendly challenges are allowed')
        if game.local is None:
            raise Stop('cannot tell which player is local')

    def step(self):
        """One decision. Returns a short status string."""
        if self.inputs.aborted():
            raise Stop('stopped by the player')
        self.pump()
        game = self.power.game
        if game is None:
            return 'no_game'
        if game.over:
            return 'game_over'
        if not game.packet and not game.choice:
            return 'waiting'
        if not self.quiet():
            return 'settling'
        self.check_allowed(game)
        if self.actions >= self.max_actions:
            raise Stop('action limit reached')
        if game.choice and (game.number, game.choice['id']) != self.handled_choice:
            if game.choice['type'] == 'MULLIGAN' and not self._mulligan_on_screen():
                return 'animating'
            return self._act_on_choice(game)
        if game.packet:
            # All 714 recorded sends had no state lines after their packet, so newer lines
            # mean this packet is out of date, such as a turn that ended on the timer.
            if game.packet['revision'] != game.revision:
                return 'stale_packet'
            if not self._screen_caught_up(game):
                return 'animating'
            return self._act_on_packet(game)
        return 'waiting'

    def _mulligan_on_screen(self):
        """The log offers the mulligan before the cards are dealt, and early clicks would be lost."""
        if not self.mulligan_ready:
            return True
        if self.mulligan_wait is None:
            self.mulligan_wait = self.clock() + self.mulligan_timeout
        try:
            if self.mulligan_ready():
                return True
        except Exception as error:
            self.log(f'screen check failed: {error}')
        if self.clock() < self.mulligan_wait:
            return False
        self.log('mulligan screen never recognized; acting anyway')
        return True

    def _screen_caught_up(self, game):
        if not self.screen_ready:
            return True
        key = (game.number, game.packet['id'])
        if not self.screen_wait or self.screen_wait[:2] != key:
            self.screen_wait = (*key, self.clock() + self.screen_timeout)
            self.lit_reads = 0
        try:
            # One lit reading can be a passing transition, as seen right after a mulligan.
            self.lit_reads = self.lit_reads + 1 if self.screen_ready() else 0
            if self.lit_reads >= self.lit_required:
                return True
        except Exception as error:
            self.lit_reads = 0
            self.log(f'screen check failed: {error}')
        if self.clock() < self.screen_wait[2]:
            return False
        self.log('End Turn button never lit up; acting anyway')
        return True

    def _still_lit(self):
        """A last read after the slow capture, right before input, because a live frame went grey here."""
        if not self.screen_ready or self.clock() >= self.screen_wait[2]:
            return True
        try:
            if self.screen_ready():
                return True
        except Exception as error:
            self.log(f'screen check failed: {error}')
        self.lit_reads = 0
        return False

    def _note(self, event):
        """Run the observer before the guard, so its delay cannot hide a state change."""
        if self.before_input:
            try:
                self.before_input(event)
            except Exception as error:
                self.log(f'session record failed: {error}')

    def _refresh_guard(self, game, revision, packet_id=None):
        """Re-read the log right before input. Anything new means the decision is stale."""
        self.pump()
        if self.power.game is not game or game.revision != revision:
            raise StateChanged('state changed before input')
        if packet_id is not None and (not game.packet or game.packet['id'] != packet_id):
            raise StateChanged('option packet changed before input')

    def _act_on_packet(self, game):
        packet = game.packet
        state = packet['state']
        if not state['you'] or not state['opponent'] or not state['you']['hero'] or not state['opponent']['hero']:
            raise Stop('state is incomplete')
        plans = []
        for candidate in candidates_from(packet):
            try:
                plan = geometry.plan_action(state, candidate)
            except geometry.GeometryError:
                continue  # A move the agent cannot perform is never offered to the policy.
            plans.append((candidate, plan))
        if not plans:
            raise Stop('no plannable candidates')
        candidate, gestures = plans[self.policy.choose(state, [c for c, _ in plans], packet['cards'])]
        self._note({'kind': 'option', 'turn': state['turn'], 'packet': packet['id'], 'candidate': candidate,
                    'options': len(plans), 'gestures': gestures, 'state': state})
        if not self._still_lit():
            return 'animating'
        try:
            self._refresh_guard(game, packet['revision'], packet['id'])
        except StateChanged:
            return 'state_changed'  # Nothing has been sent, so decide again on the new state.
        self.log(f'turn {state["turn"]} packet {packet["id"]}: {candidate}')
        self.actions += 1
        attempts = self.max_attempts if len(gestures) == 1 else 1
        before = len(game.sends)
        for attempt in range(1, attempts + 1):
            self.inputs.careful = attempt > 1  # A fast drag that failed is retried at the slow, proven speed.
            # A release during an animation can leave the targeting arrow up, and then a repeat drag cannot land.
            self.inputs.send(gestures if attempt == 1 else [CANCEL, *gestures])
            try:
                self._confirm_send(game, before, candidate)
                return 'acted'
            except NoSend:
                self._note({'kind': 'no_send', 'attempt': attempt, 'packet': packet['id'], 'candidate': candidate})
                if attempt < attempts:
                    self._refresh_guard(game, packet['revision'], packet['id'])
        self.inputs.send([CANCEL])  # Never hand the game back with an arrow still up.
        raise Stop(f'no SendOption after {attempts} attempt(s); handing the game back')

    def _confirm_send(self, game, before, candidate):
        """The client's own SendOption line is the only accepted proof of what was submitted."""
        deadline = self.clock() + self.confirm_timeout
        while self.clock() < deadline:
            if self.inputs.aborted():
                raise Stop('stopped by the player')
            self.pump()
            # Check the send first: one read can hold a game-ending send and the next game's start.
            if len(game.sends) > before:
                sent = game.sends[before]['sent']
                if any(sent[k] != candidate[k] for k in ('option', 'sub', 'target')):
                    raise Stop(f'the game received a different action: sent {sent}, planned {candidate}')
                return
            if self.power.game is not game:
                raise Stop('a new game started while confirming')
            self.sleep(0.05)
        raise NoSend('no SendOption after input')

    def _act_on_choice(self, game):
        choice = game.choice
        revision = game.revision
        entities = choice['entities']
        if not entities:
            raise Stop('choice has no entities')
        cards = game.card_map()
        if choice['type'] == 'MULLIGAN':
            replace = {e for e in self.policy.mulligan(entities, cards)}
            gestures = []
            try:
                for index, entity in enumerate(entities):
                    if entity['id'] in replace:
                        gestures.append(('click', geometry.mulligan_point(index, len(entities))))
            except geometry.GeometryError as error:
                raise Stop(f'cannot plan mulligan: {error}') from error
            gestures.append(('click', geometry.MULLIGAN_CONFIRM))
        else:
            if choice['type'] != 'GENERAL' or choice['max'] != 1:
                raise Stop(f'unsupported {choice["type"]} choice with up to {choice["max"]} picks')
            index = self.policy.pick_choice(choice, cards)
            try:
                gestures = [('click', geometry.choice_point(index, len(entities)))]
            except geometry.GeometryError as error:
                raise Stop(f'cannot plan choice: {error}') from error
        self._note({'kind': 'choice', 'type': choice['type'], 'choice': choice['id'], 'gestures': gestures,
                    'entities': [e['id'] for e in entities],
                    'cards': [cards.get(str(e['id'])) for e in entities]})
        try:
            self._refresh_guard(game, revision)
        except StateChanged:
            return 'state_changed'
        self.log(f'choice {choice["id"]} {choice["type"]}: {gestures}')
        self.actions += 1
        self.handled_choice = (game.number, choice['id'])
        # A resend repeats only the last click. Repeating a mulligan card click would toggle it back.
        for attempt in range(1, self.max_attempts + 1):
            self.inputs.send(gestures if attempt == 1 else gestures[-1:])
            deadline = self.clock() + self.choice_timeout
            while self.clock() < deadline:
                if self.inputs.aborted():
                    raise Stop('stopped by the player')
                self.pump()
                if game.choice is None or game.choice['id'] != choice['id']:
                    return 'acted'
                self.sleep(0.05)
            self._note({'kind': 'no_send', 'attempt': attempt, 'choice': choice['id']})
            if attempt < self.max_attempts:
                self._refresh_guard(game, revision)
        raise Stop(f'choice not answered after {self.max_attempts} attempts; handing the game back')

    def run_game(self, poll=0.05):
        """Play until the game ends. Stop propagates, because the caller must see why."""
        while True:
            status = self.step()
            if status == 'game_over':
                return self.power.game.result
            if self.idle_limit and self.clock() - self.last_line_time > self.idle_limit:
                raise Stop(f'the game log was silent for {self.idle_limit} seconds')
            if status != 'acted':
                self.sleep(poll)
