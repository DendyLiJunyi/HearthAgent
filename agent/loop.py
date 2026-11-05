"""The play loop. Input is injected, so offline tests and live play run the same logic.

Rules that keep a wrong click from becoming a runaway:
- Practice mode allows AI games and agreed friendly challenges. Wild mode requires Ranked Wild.
  Friend mode allows agreed friendly challenges and nothing else.
  Casual, arena and anything unrecognized are refused.
- Nothing is sent until the log has been quiet for `settle` seconds.
- If a screen check is supplied, moves also wait for the End Turn button to light up, because
  the log runs ahead of the screen. An unreadable button only delays play by `screen_timeout`.
  A readable button that is not lit can hold moves for the longer `button_timeout`.
- Before input, the packet and revision are re-read. Any change cancels the action.
- After input, the logged SendOption must match the plan. Otherwise the agent stops.
- A single-gesture move can be resent only if the log shows nothing was sent and nothing changed.
  In a live test, first-of-turn drags sent nothing and then worked unchanged, so this is bounded,
  not open-ended. Multi-step moves are never resent, and the last timeout hands the game back.
- With `recover`, a move the game will not take is dropped and the turn continues, because stopping
  in a game against another player forfeits it on the timer. Game-type refusals, Esc and the action
  limit still stop, and every recovery is recorded.
- With `backlog_limit`, the log's own animation queue replaces the 20-second opening wait and the
  whole-board pixel wait. The End Turn check remains, and moves also wait for the queue to reach a
  new turn, up to `button_timeout`.
"""
import time

from . import geometry
from .power import PowerLog, candidates_from

ALLOWED_GAME_TYPES = {'GT_VS_AI'}
FRIENDLY_GAME_TYPE = 'GT_VS_FRIEND'
CANCEL = ('right_click', geometry.CANCEL_POINT)
MOVE_KEY = ('option', 'sub', 'target')
CAUTIOUS_MOVES = 3  # After a failed move, the next few go at the slow, proven speed.
CAUTIOUS_SETTLE = 0.5
MAX_WRONG_ACTIONS = 3
MAX_RELIT_RETRIES = 2  # Fresh tries per packet after a dropped End Turn, if the button is lit.


class Stop(Exception):
    """The agent must stop and leave the game to the player."""


class StateChanged(Stop):
    """The log moved on while deciding."""


class NoSend(Stop):
    """Input went out but the game logged no move."""


class WrongAction(Stop):
    """The game logged a move other than the planned one, so it has already happened."""


class FocusLost(RuntimeError):
    """Another window took the foreground during a gesture."""


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
                 clock=time.monotonic, sleep=time.sleep, log=print, before_input=None, mode='practice', opening_delay=0.0,
                 choice_ready=None, backlog_limit=None, drain_timeout=6.0, recover=False, eager_decision=False,
                 button_timeout=None):
        if mode not in ('practice', 'wild', 'friend'):
            raise ValueError(f'unsupported mode: {mode}')
        self.mode = mode
        self.opening_delay = opening_delay
        self.opening_ready_at = None
        self.reader, self.policy, self.inputs = reader, policy, inputs
        self.power = PowerLog()
        self.settle, self.confirm_timeout, self.max_actions = settle, confirm_timeout, max_actions
        self.clock, self.sleep, self.log = clock, sleep, log
        self.actions = 0
        self.max_attempts = max_attempts
        self.friend_agreed = friend_agreed
        self.screen_ready, self.screen_timeout = screen_ready, screen_timeout
        self.button_timeout = screen_timeout if button_timeout is None else button_timeout
        self.screen_started = None
        self.screen_reset = None
        self.strict_screen = False
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
        self.focus_paused = False
        self.choice_ready = choice_ready
        self.choice_screen_wait = None
        self.backlog_limit, self.drain_timeout = backlog_limit, drain_timeout
        self.recover, self.eager_decision = recover, eager_decision
        self.drain_wait = None
        self.plan_cache = None
        self.on_plan = None
        self.failed_moves = {}  # packet id -> moves the game would not take
        self.abandoned = None
        self.end_turn_dropped = None
        self.relit_retries = {}
        self.cautious_moves = 0
        self.wrong_actions = 0
        self.needs_cancel = False
        self.recoveries = []
        self.packet_seen = None
        self.option_lines_seen = None
        self.option_lines_at = clock()

    def pump(self):
        """Read any new lines, returning True if there were some."""
        lines = self.reader()
        for line in lines:
            self.power.feed(line)
        if lines:
            self.last_line_time = self.clock()
            game = self.power.game
            if game and game.option_lines != self.option_lines_seen:
                self.option_lines_seen, self.option_lines_at = game.option_lines, self.clock()
        return bool(lines)

    def quiet(self):
        return self.clock() - self.last_line_time >= self.settle + (CAUTIOUS_SETTLE if self.cautious_moves else 0)

    def _recovered(self, kind, detail):
        """Keep playing, and leave a record of what went wrong."""
        self.recoveries.append({'kind': kind, 'detail': detail})
        self.log(f'recovering ({kind}): {detail}')
        self._note({'kind': 'recovery', 'recovery': kind, 'detail': detail})

    def check_allowed(self, game):
        if self.mode == 'wild':
            if game.game_type != 'GT_RANKED' or game.format_type != 'FT_WILD':
                raise Stop(f'refusing to act in {game.game_type}/{game.format_type}: Ranked Wild required')
            if game.local is None:
                raise Stop('cannot tell which player is local')
            return
        if self.mode == 'friend':
            if not self.friend_agreed or game.game_type != FRIENDLY_GAME_TYPE:
                raise Stop(f'refusing to act in {game.game_type}: only an agreed friendly challenge is allowed')
            if game.local is None:
                raise Stop('cannot tell which player is local')
            return
        friendly = self.friend_agreed and game.game_type == FRIENDLY_GAME_TYPE
        if game.game_type not in ALLOWED_GAME_TYPES and not friendly:
            raise Stop(f'refusing to act in {game.game_type}: only practice games and agreed friendly challenges are allowed')
        if game.local is None:
            raise Stop('cannot tell which player is local')

    def _focus_ready(self):
        ready = getattr(self.inputs, 'ready', None)
        if ready and not ready():
            if not self.focus_paused:
                self.log('paused: click inside Hearthstone to resume; input stays paused while another app is active')
            self.focus_paused = True
            self.screen_wait = None
            return False
        if self.focus_paused:
            self.log('resumed: Hearthstone is in the foreground')
            self.focus_paused = False
            self.last_line_time = self.clock()
        return True

    def step(self):
        """One decision. Returns a short status string."""
        if self.inputs.aborted():
            raise Stop('stopped by the player')
        self.pump()
        game = self.power.game
        if game is None:
            return 'no_game'
        if game.packet and self.opening_ready_at is None:
            # Start-of-game effects can leave End Turn lit while the hand and mana are still
            # animating. Start this once, when options first arrive, not after each log update.
            turn = game.packet['state']['turn']
            self.opening_ready_at = self.clock() + (self.opening_delay if turn <= 2 else 0)
        if game.over:
            return 'game_over'
        if not self._focus_ready():
            return 'paused'
        if self.needs_cancel:
            # A gesture was cut short, so an arrow or a held card may still be up.
            self.needs_cancel = False
            try:
                self.inputs.send([CANCEL])
            except FocusLost:
                self.needs_cancel = True
                return 'paused'
        if not game.packet and not game.choice:
            return 'waiting'
        self._decide_early(game)
        if not self.quiet():
            return 'settling'
        self.check_allowed(game)
        if self.actions >= self.max_actions:
            raise Stop('action limit reached')
        if game.choice and (game.number, game.choice['id']) != self.handled_choice:
            try:
                if game.choice['type'] == 'MULLIGAN' and not self._mulligan_on_screen():
                    return 'animating'
                if game.choice['type'] != 'MULLIGAN' and not self._choice_on_screen(game):
                    return 'animating'
                return self._act_on_choice(game)
            except FocusLost:
                if not self.recover:
                    raise
                self.handled_choice = None
                self.needs_cancel = True
                return 'paused'
            except StateChanged:
                if not self.recover:
                    raise
                self.handled_choice = None  # The log moved on, so look again rather than guess.
                return 'state_changed'
            except Stop as stop:
                if not self.recover or 'stopped by the player' in str(stop) or 'new game' in str(stop):
                    raise
                # The game answers an open choice itself when its timer runs out.
                self.handled_choice = (game.number, game.choice['id']) if game.choice else self.handled_choice
                self._recovered('choice', str(stop))
                return 'choice_skipped'
        if game.packet:
            if self.clock() < self.opening_ready_at:
                return 'opening_animation'
            # All 714 recorded sends had no state lines after their packet, so newer lines
            # mean this packet is out of date, such as a turn that ended on the timer.
            if game.packet['revision'] != game.revision:
                return 'stale_packet'
            if self.abandoned == (game.number, game.packet['id']):
                if self._end_turn_relit(game):
                    return 'recovered'
                return 'waiting'  # Nothing more can be done until the state changes or the timer ends the turn.
            if not self._log_caught_up(game):
                return 'animating'
            if not self._screen_caught_up(game):
                return 'animating'
            try:
                return self._act_on_packet(game)
            except FocusLost:
                if not self.recover:
                    raise
                # The log decides what happened: an accepted move clears the packet.
                self.needs_cancel = True
                return 'paused'
        return 'waiting'

    def _decide_early(self, game):
        """Run the model while animations play, so its time is not added to the wait.

        Options arrive long before the client can take input, so the packet must be complete but
        the screen need not be ready.
        """
        packet = game.packet
        if (not self.eager_decision or not packet or game.choice or game.over or packet['revision'] != game.revision
                or self.abandoned == (game.number, packet['id'])
                or self.clock() - self.option_lines_at < 0.05):
            return
        self.check_allowed(game)
        try:
            self._plan(game)
        except Stop:
            pass  # An unplannable packet is reported when the move is actually attempted.

    def _log_caught_up(self, game):
        """Wait for the client to work through its animation queue, up to a limit."""
        if self.backlog_limit is None:
            return True
        key = (game.number, game.packet['id'])
        if not self.drain_wait or self.drain_wait[:2] != key:
            self.drain_wait = (*key, self.clock() + self.drain_timeout, self.clock() + self.button_timeout)
        if self.power.backlog.turn_behind and self.clock() < self.drain_wait[3]:
            # The screen is still showing the last turn. The shorter limit starts once it gets here.
            self.drain_wait = (*key, self.clock() + self.drain_timeout, self.drain_wait[3])
            return False
        if self.power.backlog.size <= self.backlog_limit:
            return True
        return self.clock() >= self.drain_wait[2]  # A few lines are never repeated, so this cannot wait forever.

    def _plan(self, game):
        """Choose once for each packet. Returns (candidate, gestures, number of options)."""
        packet = game.packet
        failed = self.failed_moves.get(packet['id'], set())
        key = (game.number, packet['id'], packet['revision'], len(failed))
        if self.plan_cache and self.plan_cache[0] == key:
            return self.plan_cache[1]
        state = packet['state']
        if not state['you'] or not state['opponent'] or not state['you']['hero'] or not state['opponent']['hero']:
            raise Stop('state is incomplete')
        plans = []
        for candidate in candidates_from(packet):
            if tuple(candidate[k] for k in MOVE_KEY) in failed:
                continue
            try:
                plan = geometry.plan_action(state, candidate)
            except geometry.GeometryError:
                continue  # A move the agent cannot perform is never offered to the policy.
            plans.append((candidate, plan))
        if not plans:
            raise Stop('no plannable candidates')
        candidate, gestures = plans[self.policy.choose(state, [c for c, _ in plans], packet['cards'])]
        candidate = dict(candidate, position=geometry.expected_position(state, candidate))
        result = (candidate, gestures, len(plans), getattr(self.policy, 'last_decision', None))
        self.plan_cache = (key, result)
        if self.on_plan:
            self.on_plan(gestures)
        return result

    def _abandon_move(self, game, packet, candidate):
        """Drop a move the game would not take and let the policy pick another."""
        self.failed_moves.setdefault(packet['id'], set()).add(tuple(candidate[k] for k in MOVE_KEY))
        self.cautious_moves = CAUTIOUS_MOVES
        self._recovered('dropped_move', f'turn {packet["state"]["turn"]}: {candidate}')
        if candidate['kind'] == 'end_turn':
            self.abandoned = (game.number, packet['id'])
            self.end_turn_dropped = self.abandoned
            self.lit_reads = 0
        return 'recovered'

    def _end_turn_relit(self, game):
        """Clicks on a grey button are ignored, so a button that lights afterwards reopens the turn."""
        key = (game.number, game.packet['id'])
        if not self.screen_ready or self.end_turn_dropped != key or self.relit_retries.get(key, 0) >= MAX_RELIT_RETRIES:
            return False
        try:
            self.lit_reads = self.lit_reads + 1 if self.screen_ready() else 0
        except Exception:
            self.lit_reads = 0  # This repeats every step while waiting, so it is not logged.
        if self.lit_reads < self.lit_required:
            return False
        self.relit_retries[key] = self.relit_retries.get(key, 0) + 1
        self.abandoned = self.end_turn_dropped = self.screen_wait = None
        self.failed_moves.pop(game.packet['id'], None)  # Moves dropped for the same reason get another chance too.
        self._recovered('end_turn_relit', f'packet {game.packet["id"]}: End Turn is lit, so the turn is open again')
        return True

    def _choice_on_screen(self, game):
        if not self.choice_ready:
            return True
        key = (game.number, game.choice['id'])
        if not self.choice_screen_wait or self.choice_screen_wait[:2] != key:
            self.choice_screen_wait = (*key, self.clock() + self.screen_timeout)
        try:
            if self.choice_ready(key):
                return True
        except Exception as error:
            self.log(f'choice screen check failed: {error}')
        if self.clock() >= self.choice_screen_wait[2]:
            raise Stop('choice screen did not settle before the timeout')
        return False

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
        raise Stop('mulligan screen was not recognized before the timeout')

    def _screen_caught_up(self, game):
        if not self.screen_ready:
            return True
        key = (game.number, game.packet['id'])
        if not self.screen_wait or self.screen_wait[:2] != key:
            self.screen_started = self.clock()
            self.screen_wait = (*key, self.screen_started + self.button_timeout)
            self.lit_reads = 0
            if self.screen_reset:
                self.screen_reset()
        try:
            # One lit reading can be a passing transition, as seen right after a mulligan.
            self.lit_reads = self.lit_reads + 1 if self.screen_ready() else 0
            if self.lit_reads >= self.lit_required:
                return True
        except Exception as error:
            self.lit_reads = 0
            self.log(f'screen check failed: {error}')
            # A failed read says nothing about the button, so only the short limit applies.
            self.screen_wait = (*key, min(self.screen_wait[2], self.screen_started + self.screen_timeout))
        if self.clock() < self.screen_wait[2]:
            return False
        if self.strict_screen:
            raise Stop('battlefield or End Turn button did not settle before the screen timeout')
        self.log('End Turn button never lit up; acting anyway')
        return True

    def _still_lit(self):
        """A last read after the slow capture, right before input, because a live frame went grey here."""
        if not self.screen_ready or (not self.strict_screen and self.clock() >= self.screen_wait[2]):
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
        try:
            candidate, gestures, options, decision = self._plan(game)
        except Stop:
            if not self.recover:
                raise
            self.abandoned = (game.number, packet['id'])
            self._recovered('no_move', f'nothing plannable in packet {packet["id"]}; waiting for the timer')
            return 'recovered'
        self._note({'kind': 'option', 'turn': state['turn'], 'packet': packet['id'], 'candidate': candidate,
                    'options': options, 'gestures': gestures, 'state': state,
                    'decision': decision, 'backlog': self.power.backlog.size})
        if not self._focus_ready():
            return 'paused'
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
            if attempt > 1 and self.screen_ready:
                if self.screen_reset:
                    self.screen_reset()
                self.lit_reads = 0
                while not self._screen_caught_up(game):
                    if self.inputs.aborted():
                        raise Stop('stopped by the player')
                    self._refresh_guard(game, packet['revision'], packet['id'])
                    self.sleep(0.05)
                self._refresh_guard(game, packet['revision'], packet['id'])
            # A fast drag that failed is retried at the slow, proven speed.
            self.inputs.careful = attempt > 1 or self.cautious_moves > 0
            # A release during an animation can leave the targeting arrow up, and then a repeat drag cannot land.
            self.inputs.send(gestures if attempt == 1 else [CANCEL, *gestures])
            if hasattr(self.inputs, 'park'):
                self.inputs.park()
            try:
                self._confirm_send(game, before, candidate)
                self.cautious_moves = max(0, self.cautious_moves - 1)
                return 'acted'
            except WrongAction as wrong:
                self.wrong_actions += 1
                if not self.recover or self.wrong_actions >= MAX_WRONG_ACTIONS:
                    raise
                self.cautious_moves = CAUTIOUS_MOVES
                self._recovered('wrong_action', str(wrong))
                return 'acted'
            except NoSend:
                self._note({'kind': 'no_send', 'attempt': attempt, 'packet': packet['id'], 'candidate': candidate,
                            'backlog': self.power.backlog.size})
                self.cautious_moves = CAUTIOUS_MOVES
                if attempt < attempts:
                    try:
                        self._refresh_guard(game, packet['revision'], packet['id'])
                    except StateChanged:
                        if not self.recover:
                            raise
                        return 'state_changed'  # A slow receipt or the turn timer, so never repeat the drag.
        self.inputs.send([CANCEL])  # Never hand the game back with an arrow still up.
        if self.recover:
            return self._abandon_move(game, packet, candidate)
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
                if any(sent[k] != candidate[k] for k in ('option', 'sub', 'target', 'position')):
                    raise WrongAction(f'the game received a different action: sent {sent}, planned {candidate}')
                return
            if self.power.game is not game:
                raise Stop('a new game started while confirming')
            self.sleep(0.05)
        raise NoSend('no SendOption after input')

    def _act_on_choice(self, game):
        started = self.clock()
        choice = game.choice
        revision = game.revision
        entities = choice['entities']
        if not entities:
            raise Stop('choice has no entities')
        cards = game.card_map()
        if choice['type'] == 'MULLIGAN':
            replace = {e for e in self.policy.mulligan(entities, cards)}
            # Mulligan receipts list the original cards KEPT, not those replaced.
            # The Coin is offered in the log but is not a selectable screen card.
            shown = geometry.MULLIGAN_ROW.get(len(entities), (0,))[0]
            expected = {e['id'] for e in entities[:shown]} - replace
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
            expected = {entities[index]['id']}
            try:
                gestures = [('click', geometry.choice_point(index, len(entities)))]
            except geometry.GeometryError as error:
                raise Stop(f'cannot plan choice: {error}') from error
        self._note({'kind': 'choice', 'type': choice['type'], 'choice': choice['id'], 'gestures': gestures,
                    'replace': sorted(replace) if choice['type'] == 'MULLIGAN' else None,
                    'entities': [e['id'] for e in entities],
                    'cards': [cards.get(str(e['id'])) for e in entities],
                    'decision': {'source': 'rules', 'reason': choice['type'].lower(),
                                 'elapsed_ms': (self.clock() - started) * 1000,
                                 'checkpoint': getattr(self.policy, 'checkpoint', None)}})
        if not self._focus_ready():
            return 'paused'
        try:
            self._refresh_guard(game, revision)
        except StateChanged:
            return 'state_changed'
        self.log(f'choice {choice["id"]} {choice["type"]}: {gestures}')
        self.actions += 1
        self.handled_choice = (game.number, choice['id'])
        before = len(game.choices_sent)
        # A resend repeats only the last click. Repeating a mulligan card click would toggle it back.
        for attempt in range(1, self.max_attempts + 1):
            self.inputs.careful = True  # UI buttons need a deliberate press, including the first attempt.
            self.inputs.send(gestures if attempt == 1 else gestures[-1:])
            if hasattr(self.inputs, 'park'):
                self.inputs.park()
            deadline = self.clock() + self.choice_timeout
            while self.clock() < deadline:
                if self.inputs.aborted():
                    raise Stop('stopped by the player')
                self.pump()
                receipts = game.choices_sent[before:]
                if receipts:
                    receipt = receipts[0]
                    if receipt['id'] != choice['id']:
                        raise Stop('a different choice was answered')
                    if receipt['complete']:
                        if set(receipt['selected']) != expected or len(receipt['selected']) != len(expected):
                            raise Stop('the game received different choice entities than planned')
                        return 'acted'
                if self.power.game is not game:
                    raise Stop('a new game started while confirming a choice')
                if game.choice is None or game.choice['id'] != choice['id']:
                    raise Stop('choice changed without matching selected-entity evidence')
                self.sleep(0.05)
            if len(game.choices_sent) > before:
                raise Stop('incomplete choice receipt; refusing to resend')
            self._note({'kind': 'no_send', 'attempt': attempt, 'choice': choice['id']})
            if attempt < self.max_attempts:
                self._refresh_guard(game, revision)
        raise Stop(f'choice not answered after {self.max_attempts} attempts; handing the game back')

    def run_game(self, poll=0.02):
        """Play until the game ends. Stop propagates, because the caller must see why."""
        reported, reported_at = None, self.clock()
        messages = {
            'paused': 'paused: click inside Hearthstone to resume; another app has focus',
            'waiting': 'waiting for the game to offer a move (usually the opponent turn)',
            'opening_animation': 'waiting for the opening animation buffer',
            'animating': 'waiting for the animations or choice screen to settle',
            'settling': 'waiting for the game log to settle',
            'stale_packet': 'waiting for a fresh action packet',
            'no_game': 'waiting for a game in the log',
        }
        while True:
            status = self.step()
            now = self.clock()
            if status in messages and ((status != reported and now - reported_at >= 2)
                                       or now - reported_at >= 10):
                self.log(messages[status])
                reported, reported_at = status, now
            if status == 'game_over':
                return self.power.game.result
            if status != 'paused' and self.idle_limit and self.clock() - self.last_line_time > self.idle_limit:
                raise Stop(f'the game log was silent for {self.idle_limit} seconds')
            if status != 'acted':
                self.sleep(poll)
