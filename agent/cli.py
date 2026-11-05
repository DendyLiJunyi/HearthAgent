"""Commands: `status` and `watch` read only, `preview` draws without input, `play` is dry-run unless --execute.

`loop` always sends real input, from the menus onward, and requires an explicit game count.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import geometry
from .screen import (GameScreen, BattlefieldSettler, battlefield_signature, hand_signature, choice_signature,
                     average_rgb, region_signature)
from .loop import Agent, RecordingInput, Stop
from .policy import DEFAULT_CHECKPOINT, LayaPolicy, RulesPolicy, load_cards
from .power import PowerLog, candidates_from
from .restart import RestartPlan, bring_to_front, close_game, parse_restart_every

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
INSTALL = Path(r'D:\Hearthstone')
BATTLE_NET = Path(r'D:\Battle.net\Battle.net.exe')
BATTLE_NET_LOGS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Battle.net/Logs'
DECK_ID = '9567872927'  # The player's 海盗战 deck, as Decks.log names it.
CHECKPOINT = DEFAULT_CHECKPOINT
# Fast trusts the log's animation queue, then checks only the pixels the next gesture touches.
# Careful is exactly the earlier behavior, with whole-board stability and a 20-second opening wait.
PACES = {
    'fast': {'agent': dict(settle=0.15, confirm_timeout=1.2, choice_timeout=4.0, lit_required=2, opening_delay=0.0,
                           screen_timeout=8.0, backlog_limit=12, drain_timeout=6.0, recover=True, eager_decision=True,
                           button_timeout=60.0),  # Saved replays reach 24.6 s, and input must leave time to act.
             'strict_screen': False, 'choice_settle': 0.4, 'focus_settle': 0.12, 'focus_cap': 0.5},
    'careful': {'agent': dict(settle=0.5, confirm_timeout=2.0, choice_timeout=5.0, lit_required=3, opening_delay=20.0),
                'strict_screen': True, 'choice_settle': 1.5, 'focus_settle': None, 'focus_cap': None},
}


def configure(path):
    """Load an explicit local profile; no implicit per-machine overrides."""
    global INSTALL, BATTLE_NET, DECK_ID, CHECKPOINT
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    allowed = {'install', 'battle_net', 'deck_id', 'checkpoint'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('profile must contain only install, battle_net, deck_id, checkpoint')
    if any(not isinstance(v, str) or not v.strip() for v in config.values()):
        raise ValueError('profile values must be nonempty strings')
    base = Path(path).resolve().parent
    def local_path(key, default):
        if key not in config:
            return default
        value = Path(config[key])
        return value.resolve() if value.is_absolute() else (base / value).resolve()
    INSTALL = local_path('install', INSTALL)
    BATTLE_NET = local_path('battle_net', BATTLE_NET)
    CHECKPOINT = local_path('checkpoint', CHECKPOINT)
    DECK_ID = config.get('deck_id', DECK_ID)


def current_log():
    sessions = sorted(p for p in (INSTALL / 'Logs').glob('Hearthstone_*') if p.is_dir())
    if not sessions:
        raise Stop('no Hearthstone log session found')
    return sessions[-1] / 'Power.log'


class Tail:
    """Returns only complete lines, so a half-written line is never parsed."""

    def __init__(self, path, session_check=None):
        self.path, self.position, self.partial = Path(path), 0, b''
        self.identity = None
        self.anchor = b''
        self.session_check = session_check

    def __call__(self):
        if self.session_check and Path(self.session_check()).resolve() != self.path.resolve():
            raise Stop('log session changed; start a new run')
        if not self.path.exists():
            if self.identity is not None:
                raise Stop('log file disappeared; start a new run')
            return []
        with open(self.path, 'rb') as handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if self.identity is not None and identity != self.identity:
                raise Stop('log file was replaced; start a new run')
            if stat.st_size < self.position:
                raise Stop('log file was truncated; start a new run')
            if self.anchor:
                handle.seek(self.position - len(self.anchor))
                if handle.read(len(self.anchor)) != self.anchor:
                    raise Stop('log file was rewritten; start a new run')
            self.identity = identity
            handle.seek(self.position)
            data = handle.read()
            self.position = handle.tell()
            self.anchor = (self.anchor + data)[-64:]
        if not data:
            return []
        lines = (self.partial + data).split(b'\n')
        self.partial = lines.pop()
        return [line.decode('utf-8', errors='replace') + '\n' for line in lines]


def game_window():
    from probe_game_window import probe
    result = probe()
    if result['status'] != 'window_found' or result['errors'] or len(result['windows']) != 1:
        raise SystemExit('exactly one visible Hearthstone window is required')
    window = result['windows'][0]
    rect = window['client_screen_rect']
    if window['minimized']:
        raise SystemExit('the game window is minimized')
    return {**window, 'left': rect['left'], 'top': rect['top'],
            'width': rect['right'] - rect['left'], 'height': rect['bottom'] - rect['top']}


def read_all(path):
    log = PowerLog()
    for line in Tail(path)():
        log.feed(line)
    return log


def status(args):
    log = read_all(args.log or current_log())
    game = log.game
    if not game:
        print(json.dumps({'game': None}))
        return
    packet = game.packet
    print(json.dumps({'game': game.number, 'type': game.game_type, 'format': game.format_type, 'local': game.local, 'over': game.over,
                      'turn': game.snapshot()['turn'], 'open_choice': bool(game.choice),
                      'open_options': len(candidates_from(packet)) if packet else 0}))


def preview(args):
    """Write an SVG of every planned gesture over a saved frame, to check positions by eye."""
    game = read_all(args.log or current_log()).game
    packet = game.packet if game and game.packet else (game.sends[-1]['packet'] if game and game.sends else None)
    if not packet:
        raise SystemExit('no option packet to preview')
    state = packet['state']
    width, height = geometry.BASE_W, geometry.BASE_H
    marks = []
    for candidate in candidates_from(packet):
        try:
            gestures = geometry.plan_action(state, candidate)
        except geometry.GeometryError as error:
            print('unplannable', candidate, error)
            continue
        for gesture in gestures:
            if gesture[0] == 'wait':
                continue
            x, y = gesture[1]
            if gesture[0] == 'drag':
                marks.append(f'<line x1="{x}" y1="{y}" x2="{gesture[2][0]}" y2="{gesture[2][1]}" stroke="cyan" stroke-width="2"/>')
            marks.append(f'<circle cx="{x}" cy="{y}" r="10" fill="none" stroke="magenta" stroke-width="3"/>')
    frame = Path(args.frame).resolve().as_uri()
    Path(args.output).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
                                 f'<image href="{frame}" width="{width}" height="{height}"/>' + ''.join(marks) + '</svg>',
                                 encoding='utf-8')
    print('wrote', args.output)


class SessionRecord:
    """Saves a frame and the plan before each move, so a run can be calibrated from afterwards."""

    def __init__(self, folder, log_path, screen=None, every_frame=False, screen_settle=1.5, pace='careful',
                 clock=time.monotonic):
        self.folder, self.log_path, self.count = Path(folder), Path(log_path), 0
        self.screen, self.every_frame = screen, every_frame
        self.button = None
        self.settler = BattlefieldSettler(seconds=screen_settle)
        self.hand_settler = BattlefieldSettler(seconds=screen_settle)
        settings = PACES[pace]
        self.pace, self.clock = pace, clock
        self.choice_settler = BattlefieldSettler(seconds=settings['choice_settle'])
        self.choice_key = None
        self.focus_cap = settings['focus_cap']
        self.focus_settler = BattlefieldSettler(seconds=settings['focus_settle'] or 0.12, tolerance=6.0, clock=clock)
        self.focus_points = []
        self.focus_started = None
        self.screen_checks = 0
        self.screen_blocked = {'button': 0, 'board': 0, 'hand': 0}
        self.screen_check_seconds = 0.0
        self.decision_counts = {}
        self.folder.mkdir(parents=True, exist_ok=True)

    def capture(self, name):
        done = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(ROOT / 'scripts/capture-game-window.ps1'), '-OutputPath', str(self.folder / name)],
                              capture_output=True, timeout=10, check=True)
        return json.loads(done.stdout)

    def screen_ready(self):
        """Require a lit button and independently stable board and hand regions."""
        if (self.screen.width, self.screen.height) != (1920, 1080):
            raise ValueError('screen checks require 1920x1080')
        started = time.monotonic()
        pixels = self.screen.frame()
        self.button = average_rgb(pixels, self.screen.width)
        if self.focus_cap is not None:
            return self._focused_ready(pixels, started)
        stable = self.settler.ready(battlefield_signature(pixels, self.screen.width))
        hand_stable = self.hand_settler.ready(hand_signature(pixels, self.screen.width))
        lit = geometry.end_turn_lit(self.button)
        self.screen_checks += 1
        self.screen_check_seconds += time.monotonic() - started
        for reason, ready in (('button', lit), ('board', stable), ('hand', hand_stable)):
            self.screen_blocked[reason] += not ready
        return lit and stable and hand_stable

    def _focused_ready(self, pixels, started):
        """A lit button is required. Patch stability only delays, because idle glows may never stop."""
        now = self.clock()
        if self.focus_started is None:
            self.focus_started = now
        lit = geometry.end_turn_lit(self.button)
        stable = (now - self.focus_started >= self.focus_cap or not self.focus_points or
                  self.focus_settler.ready(region_signature(pixels, self.screen.width, self.focus_points)))
        self.screen_checks += 1
        self.screen_check_seconds += time.monotonic() - started
        self.screen_blocked['button'] += not lit
        self.screen_blocked['board'] += not stable
        return lit and stable

    def focus_on(self, gestures):
        """Remember where the next move's gestures land."""
        points = []
        for gesture in gestures:
            if gesture[0] in ('click', 'drag'):
                points += [tuple(p) for p in gesture[1:]]
        self.focus_points = points
        self.focus_settler.reset()

    def reset_screen(self):
        self.settler.reset()
        self.hand_settler.reset()
        self.focus_settler.reset()
        self.focus_started = None

    def choice_ready(self, key):
        if key != self.choice_key:
            self.choice_key = key
            self.choice_settler.reset()
        return self.choice_settler.ready(choice_signature(self.screen.frame(), self.screen.width))

    def __call__(self, event):
        decision = event.get('decision') or {}
        if decision.get('reason'):
            reason = decision['reason']
            self.decision_counts[reason] = self.decision_counts.get(reason, 0) + 1
        self.count += 1
        name = f'{self.count:03d}.png'
        with open(self.folder / 'moves.jsonl', 'a', encoding='utf-8') as out:
            out.write(json.dumps(dict(event, frame=name, button=self.button, at=time.time(),
                                      screen_checks=self.screen_checks, screen_blocked=dict(self.screen_blocked),
                                      screen_check_seconds=self.screen_check_seconds), ensure_ascii=False) + '\n')
        # Saving a frame costs real time, so a normal move skips it. A failed click or a wrong card is worth the cost.
        if self.every_frame or event['kind'] == 'no_send' or event.get('recovery') == 'wrong_action':
            self.screen.save(self.folder / name)

    def finish(self, outcome):
        outcome = dict(outcome, planned_decisions=self.decision_counts, screen_checks=self.screen_checks,
                       screen_blocked=self.screen_blocked, screen_check_seconds=self.screen_check_seconds,
                       screen_settle=self.settler.seconds)
        with open(self.folder / 'outcome.json', 'w', encoding='utf-8') as out:
            json.dump(outcome, out, ensure_ascii=False, indent=1)
        try:
            self.capture('final.png')
        except Exception as error:
            print('final frame not saved:', error)
        if self.log_path.exists():
            shutil.copy2(self.log_path, self.folder / 'Power.log')
            try:
                from .learning import review_session, write_review
                cards = load_cards()
                write_review(review_session(self.folder, cards), self.folder, cards)
            except Exception as error:
                print('lesson review failed:', error, flush=True)
        print('Session saved to', self.folder, flush=True)


def wait_for_focus(inputs, window, timeout=60, clock=time.monotonic, sleep=time.sleep):
    """The terminal has focus at launch, so give the player time to click the game."""
    print(f'Click the Hearthstone window now. Waiting up to {timeout} seconds.', flush=True)
    deadline = clock() + timeout
    while clock() < deadline:
        if inputs.user.GetForegroundWindow() == window['hwnd']:
            return
        sleep(0.1)
    raise Stop('the game window never got focus')


def build_policy(name, aggressive=False, tactics=True):
    cards = load_cards()
    if name == 'rules':
        return RulesPolicy(cards, aggressive, tactics=tactics)
    return LayaPolicy.load(cards, path=CHECKPOINT, aggressive=aggressive, tactics=tactics)


def configure_deck(policy, args):
    from .deck_profile import STANDARD_WARRIOR, load_profile
    path = getattr(args, 'deck_profile', None)
    if path is None and args.mode == 'standard':
        path = STANDARD_WARRIOR
    if path:
        profile = load_profile(path, args.mode)
        policy.deck_profile = profile
        if hasattr(policy, 'rules'):
            policy.rules.deck_profile = profile
    return policy


def build_agent(tail, policy, inputs, record, *, pace, mode, friend_agreed=False, idle_limit=None, mulligan_ready=None):
    """The same settings for `play` and `loop`, chosen by pace."""
    agent = Agent(tail, policy, inputs, before_input=record, mode=mode, friend_agreed=friend_agreed, idle_limit=idle_limit,
                  screen_ready=record.screen_ready if record else None, mulligan_ready=mulligan_ready,
                  choice_ready=record.choice_ready if record else None, **PACES[pace]['agent'])
    if record:
        agent.screen_reset = record.reset_screen
        agent.strict_screen = PACES[pace]['strict_screen']
        agent.on_plan = record.focus_on
    return agent


def play(args):
    policy = build_policy(args.policy, args.aggressive, not args.no_tactics)
    configure_deck(policy, args)
    log_path = Path(args.log or current_log())
    record = None
    if args.execute:
        from .menu import Regions
        from .windows_input import WindowsInput
        window = game_window()
        inputs = WindowsInput(window, current_window=game_window)
        record = SessionRecord(ROOT / '.data/live' / time.strftime('%Y%m%d-%H%M%S'), log_path,
                               GameScreen(window), args.frames, args.screen_settle, args.pace)
        regions = Regions(record.screen)
        style = 'aggressive ' if args.aggressive else ''
        modes = ('Ranked Standard only' if args.mode == 'standard' else 'Ranked Wild only' if args.mode == 'wild' else
                 'Practice and agreed friendly games only' if args.friend_agreed else 'Practice games only')
        print(f'LIVE INPUT ENABLED with the {style}{policy.name} policy. Hold Esc to stop. {modes}.', flush=True)
    else:
        inputs = RecordingInput()
        print('Dry run: nothing is sent to the game.', flush=True)
    agent = build_agent(Tail(log_path, session_check=current_log if args.execute and not args.log else None),
                        policy, inputs, record, pace=args.pace, mode=args.mode, friend_agreed=args.friend_agreed,
                        mulligan_ready=regions.mulligan_ready if record else None)
    if not args.execute:
        # Nobody answers the game in a dry run, so print one plan for the open decision.
        agent.settle = 0
        agent.confirm_timeout = 0
        agent.opening_delay = 0.0
        agent.backlog_limit = None
    outcome = {}
    try:
        if args.execute:
            wait_for_focus(inputs, window)
            outcome = {'result': agent.run_game()}
        else:
            outcome = {'status': agent.step()}
    except (Stop, RuntimeError, geometry.GeometryError) as stop:
        outcome = {'stopped': str(stop)}
    except KeyboardInterrupt:
        outcome = {'stopped': 'stopped from terminal (Ctrl+C)'}
    outcome.update(mode=args.mode, policy=policy.name, checkpoint=getattr(policy, 'checkpoint', None), pace=args.pace,
                   aggressive=args.aggressive, actions=agent.actions, model_fallbacks=getattr(policy, 'fallbacks', 0),
                   recoveries=agent.recoveries)
    print(json.dumps(outcome), flush=True)
    if record:
        record.finish(outcome)
    for gestures in getattr(inputs, 'gestures', []):
        print(gestures)
    if 'stopped' in outcome and args.execute:
        sys.exit(2)


class ClientLog:
    """Reads Battle.net's own log, to tell a client still logging in from one that dropped the launch request."""

    LOGGED_IN = b'Logged into Battle.net successfully'
    LAUNCHED = b'LaunchBinary: uid=hs_beta'

    def __init__(self, folder=BATTLE_NET_LOGS):
        self.folder = Path(folder)
        self.start = self._newest()
        self.offset = self.start.stat().st_size if self.start else 0

    def _newest(self):
        logs = sorted(self.folder.glob('battle.net-*.log'))
        return logs[-1] if logs else None

    def read(self):
        """Return (logged_in, launched). A launch only counts if it was logged after this object was made."""
        newest = self._newest()
        if newest is None:
            return False, False
        data = newest.read_bytes()
        since = data[self.offset:] if newest == self.start else data
        return self.LOGGED_IN in data, self.LAUNCHED in since


def request_launch(send, game_open, client, *, timeout=240, retry_every=15, max_sends=4,
                   clock=time.monotonic, sleep=time.sleep):
    """Ask Battle.net to open the game until it does.

    A client started by the launch command logs in and then ignores that command, so once logged in it is asked again.
    Asking stops as soon as its log shows a launch, so a slow game is not opened twice.
    """
    send()
    sends, last = 1, clock()
    deadline = last + timeout
    logged_in = launched = False
    while clock() < deadline:
        if game_open():
            return
        logged_in, launched = client.read()
        if logged_in and not launched and sends < max_sends and clock() - last >= retry_every:
            print('Battle.net is logged in but has not opened the game. Asking again.', flush=True)
            send()
            sends, last = sends + 1, clock()
        sleep(1)
    if launched:
        raise Stop('Battle.net started Hearthstone, but its window and new log did not appear')
    if logged_in:
        raise Stop(f'Battle.net is logged in but ignored {sends} requests to open Hearthstone')
    raise Stop('Battle.net never logged in; check its window')


def ensure_game(timeout=240):
    """Open Hearthstone through Battle.net if it is not running, then wait for its window."""
    from probe_game_window import probe
    if probe()['windows']:
        return game_window()
    if not BATTLE_NET.exists():
        raise Stop(f'Battle.net not found at {BATTLE_NET}')
    print('Opening Hearthstone through Battle.net.', flush=True)
    try:
        before = current_log()
    except Stop:
        before = None
    def new_game_open():
        if not probe()['windows']:
            return False
        try:
            return current_log() != before
        except Stop:
            return False
    # The new log folder must exist too, or the loop would read the previous session's scenes.
    request_launch(lambda: subprocess.Popen([str(BATTLE_NET), '--exec=launch WTCG']),
                   new_game_open, ClientLog(), timeout=timeout)
    return game_window()


def settled_window(get=None, *, reads=3, timeout=90.0, clock=time.monotonic, sleep=time.sleep):
    """A window just opened can still change size, and later input would then be refused as a moved window."""
    get = get or game_window
    deadline = clock() + timeout
    last, same = None, 0
    while clock() < deadline:
        try:
            window = get()
        except SystemExit:
            window = None
        if window and (window['width'], window['height']) == (1920, 1080):
            same = same + 1 if window == last else 1
            last = window
            if same >= reads:
                return window
        else:
            last, same = None, 0
        sleep(1)
    raise Stop('the reopened game window did not settle at 1920x1080')


def reopen_game():
    """Open the game again after a restart, as a Stop so that the run still saves what it has."""
    try:
        ensure_game()
        return settled_window()
    except SystemExit as error:
        raise Stop(str(error)) from None


def end_of(path):
    return Path(path).stat().st_size if Path(path).exists() else 0


def reopened_log(previous, aborted, *, timeout=60.0, clock=time.monotonic, sleep=time.sleep):
    """Wait for the reopened process's log session instead of reusing the old one."""
    deadline = clock() + timeout
    while clock() < deadline:
        if aborted():
            raise Stop('stopped by the player')
        try:
            path = current_log()
            # Power.log may not exist until the first match; the session directory
            # is created during startup and LoadingScreen.log drives the menus.
            if path.parent != Path(previous).parent:
                return path
        except Stop:
            pass
        sleep(0.2)
    raise Stop('the reopened game did not create a new log session')


def outcome_counts(results):
    return {'games': len(results), 'won': sum(r.get('won') is True for r in results),
            'lost': sum(r.get('won') is False for r in results),
            'drawn': sum(r.get('won') is None for r in results)}


def run_loop(args):
    """Games from the menus, one after another, until the count, a stop, or Esc."""
    from .menu import GAME_SCENE, MenuWalker, Regions, latest_deck_id
    from .windows_input import WindowsInput
    menu_profile = None
    if getattr(args, 'menu_profile', None):
        from .menu_profile import load
        menu_profile = load(args.menu_profile, args.mode, args.deck_id)
    elif args.mode == 'standard':
        raise Stop('Standard loops require --menu-profile calibrated for --deck-id; see docs/ranked-modes.md')
    policy = build_policy(args.policy, args.aggressive, not args.no_tactics)
    configure_deck(policy, args)
    window = ensure_game()
    screen = GameScreen(window)
    regions = Regions(screen, refs=menu_profile['regions']) if menu_profile else Regions(screen)
    inputs = WindowsInput(window, current_window=game_window)
    print(f'LIVE INPUT ENABLED: {args.games} {args.mode} games with the {policy.name} policy. Hold Esc to stop.', flush=True)
    folder = ROOT / '.data/live' / ('loop-' + time.strftime('%Y%m%d-%H%M%S'))
    results, stopped = [], None
    plan = RestartPlan(args.restart_every)
    restarts = 0
    summary = lambda: {**outcome_counts(results), 'results': results, 'stopped': stopped, 'restarts': restarts,
                       'mode': args.mode, 'deck_id': args.deck_id,
                       'deck_profile': getattr(policy, 'deck_profile', {}).get('name'),
                       'policy': policy.name, 'checkpoint': getattr(policy, 'checkpoint', None),
                       'model_fallbacks': getattr(policy, 'fallbacks', 0)}
    try:
        wait_for_focus(inputs, window)
        log_path = current_log()
        def new_walker():
            return MenuWalker(Tail(log_path.parent / 'LoadingScreen.log'), regions, inputs, mode=args.mode,
                              **({'deck_click': menu_profile['deck_click']} if menu_profile else {}),
                              timeout=180.0 if args.mode in ('wild', 'standard') else 45.0)
        walker = new_walker()
        while len(results) < args.games:
            tail = Tail(log_path, session_check=current_log)
            if walker.read_scene() != GAME_SCENE:
                tail.position = end_of(log_path)
                walker.to_game()
            deck = latest_deck_id(Tail(log_path.parent / 'Decks.log')())
            if deck != args.deck_id:
                raise Stop(f'the game started with deck {deck}, not {args.deck_id}; leaving it alone')
            record = SessionRecord(folder / f'{len(results) + 1:03d}', log_path, screen, args.frames, args.screen_settle,
                                   args.pace)
            agent = build_agent(tail, policy, inputs, record, pace=args.pace, mode=args.mode, idle_limit=args.idle_limit,
                                mulligan_ready=regions.mulligan_ready)
            agent.pump()
            if agent.power.game and agent.power.game.over:
                walker.leave_game()  # Started on an end screen, so this game does not count.
                continue
            results.append(recorded_game(agent, record, policy, args.mode, args.pace, len(results) + 1))
            walker.leave_game()
            if plan.game_played() and len(results) < args.games:
                if inputs.aborted():
                    raise Stop('stopped by the player')
                if walker.read_scene() == GAME_SCENE:
                    raise Stop('still in the game scene, so the game was not closed')
                print(f'Restarting Hearthstone after {plan.played} games ({len(results)} of {args.games} played).', flush=True)
                close_game(window, inputs.aborted)
                restarts += 1
                plan.restarted()
                window = reopen_game()
                screen = GameScreen(window)
                regions = Regions(screen, refs=menu_profile['regions']) if menu_profile else Regions(screen)
                inputs = WindowsInput(window, current_window=game_window)
                bring_to_front(window['hwnd'])  # Otherwise the menu walker waits for someone to click the game.
                log_path = reopened_log(log_path, inputs.aborted)
                walker = new_walker()
    except (Stop, RuntimeError, geometry.GeometryError, OSError) as stop:
        stopped = str(stop)
    except KeyboardInterrupt:
        stopped = 'stopped from terminal (Ctrl+C)'
    save_run(folder, screen, summary(), stopped)
    if stopped:
        sys.exit(2)


def run_friend(args):
    """Agreed friendly games. The player sends or accepts each challenge and the agent plays what follows."""
    from .menu import GAME_SCENE, MenuWalker, Regions
    from .windows_input import WindowsInput
    policy = build_policy(args.policy, args.aggressive, not args.no_tactics)
    window = game_window()
    screen = GameScreen(window)
    regions = Regions(screen)
    inputs = WindowsInput(window, current_window=game_window)
    count = 'until you hold Esc' if args.games is None else f'for {args.games} game(s)'
    print(f'LIVE INPUT ENABLED: agreed friendly challenges only, {count}, with the {policy.name} policy.', flush=True)
    print('Send or accept the challenge and pick your deck in Hearthstone. The agent takes over in the game.', flush=True)
    folder = ROOT / '.data/live' / ('friend-' + time.strftime('%Y%m%d-%H%M%S'))
    results, stopped = [], None
    summary = lambda: {**outcome_counts(results), 'results': results, 'stopped': stopped, 'mode': 'friend',
                       'policy': policy.name, 'checkpoint': getattr(policy, 'checkpoint', None),
                       'model_fallbacks': getattr(policy, 'fallbacks', 0)}
    try:
        log_path = current_log()
        walker = MenuWalker(Tail(log_path.parent / 'LoadingScreen.log'), regions, inputs)
        while args.games is None or len(results) < args.games:
            tail = Tail(log_path, session_check=current_log)
            if walker.read_scene() != GAME_SCENE:
                tail.position = end_of(log_path)  # Earlier games in this log are not the next challenge.
            record = SessionRecord(folder / f'{len(results) + 1:03d}', log_path, screen, args.frames, args.screen_settle,
                                   args.pace)
            # No idle limit: waiting for a friend to accept is normal, and Esc ends the session.
            agent = build_agent(tail, policy, inputs, record, pace=args.pace, mode='friend', friend_agreed=True,
                                mulligan_ready=regions.mulligan_ready)
            agent.pump()
            if agent.power.game and agent.power.game.over:
                walker.leave_game()  # Started on an end screen, so this game does not count.
                continue
            results.append(recorded_game(agent, record, policy, 'friend', args.pace, len(results) + 1))
            walker.leave_game()
    except (Stop, RuntimeError, geometry.GeometryError, OSError) as stop:
        stopped = str(stop)
    except KeyboardInterrupt:
        stopped = 'stopped from terminal (Ctrl+C)'
    save_run(folder, screen, summary(), stopped)
    if stopped and stopped not in ('stopped by the player', 'stopped from terminal (Ctrl+C)'):
        sys.exit(2)


def recorded_game(agent, record, policy, mode, pace, number):
    """Play one game and save its outcome, however it ends. Returns the entry for the run's summary."""
    shared = {'policy': policy.name, 'actions': agent.actions, 'pace': pace, 'mode': mode,
              'checkpoint': getattr(policy, 'checkpoint', None)}
    def finish(**outcome):
        record.finish({**outcome, **shared, 'actions': agent.actions, 'recoveries': agent.recoveries,
                       'model_fallbacks': getattr(policy, 'fallbacks', 0)})
    try:
        result = agent.run_game()
    except KeyboardInterrupt:
        reason = 'stopped from terminal (Ctrl+C)'
        finish(stopped=reason)
        raise Stop(reason) from None
    except (Stop, RuntimeError, geometry.GeometryError) as stop:
        finish(stopped=str(stop))
        raise
    finish(result=result)
    label = 'won' if result.get('won') is True else 'lost' if result.get('won') is False else 'drawn'
    print(f'Game {number}: {label} ({agent.actions} actions)', flush=True)
    return {**result, 'actions': agent.actions}


def save_run(folder, screen, summary, stopped):
    folder.mkdir(parents=True, exist_ok=True)
    if stopped:
        try:
            screen.save(folder / 'stopped.png')
        except OSError as error:
            print('Stopped frame unavailable:', error, flush=True)
    with open(folder / 'summary.json', 'w', encoding='utf-8') as out:
        json.dump(summary, out, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print('Saved to', folder, flush=True)


def watch(args):
    """Read-only: while the game is in front, note each left click and the frame just before it."""
    import ctypes
    import threading
    from ctypes import wintypes
    window = game_window()
    screen = GameScreen(window)
    user = ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    scenes = Tail(current_log().parent / 'LoadingScreen.log')
    scenes()  # Skip scene changes from before this recording.
    folder = ROOT / '.data/menu-demo' / time.strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    notes = open(folder / 'clicks.jsonl', 'a', encoding='utf-8')

    def note(entry):
        notes.write(json.dumps(dict(entry, at=time.time()), ensure_ascii=False) + '\n')
        notes.flush()

    print(f'Recording clicks in the game window for up to {args.minutes} minutes. Nothing is sent to the game.', flush=True)
    print('Saving to', folder, flush=True)
    end = time.monotonic() + args.minutes * 60
    pixels, grabbed, held, count = None, 0.0, False, 0
    while time.monotonic() < end:
        for line in scenes():
            if 'OnSceneLoaded() - prevMode=' in line:
                note({'kind': 'scene', 'line': line.split(' - ', 1)[1].strip()})
        in_front = user.GetForegroundWindow() == window['hwnd']
        if in_front and time.monotonic() - grabbed >= 0.5:
            pixels, grabbed = screen.frame(), time.monotonic()
        down = bool(user.GetAsyncKeyState(0x01) & 0x8000)
        if down and not held and in_front and pixels is not None:
            count += 1
            point = wintypes.POINT()
            user.GetCursorPos(ctypes.byref(point))
            name = f'{count:03d}.png'
            note({'kind': 'click', 'x': point.x - window['left'], 'y': point.y - window['top'], 'frame': name})
            threading.Thread(target=screen.save, args=(folder / name, pixels)).start()
        held = down
        time.sleep(0.01)
    print('Recording finished:', count, 'clicks', flush=True)


def utf8_command(argv):
    """Windows defaults to the system code page, which cannot read the model's UTF-8 config."""
    return [sys.executable, '-X', 'utf8', '-m', 'agent.cli', *argv]


def main():
    if not sys.flags.utf8_mode:
        sys.exit(subprocess.run(utf8_command(sys.argv[1:])).returncode)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Local JSON profile; paths are relative to this file.')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, handler in (('status', status), ('preview', preview), ('play', play), ('watch', watch), ('loop', run_loop),
                          ('friend', run_friend)):
        command = commands.add_parser(name)
        command.set_defaults(handler=handler)
        command.add_argument('--log')
        if name in ('play', 'loop', 'friend'):
            command.add_argument('--pace', choices=sorted(PACES), default='fast',
                                 help='fast (default) trusts the log animation queue and keeps playing after a failed '
                                      'move; careful is the earlier slower behavior that stops instead.')
            command.add_argument('--no-tactics', action='store_true', help='Turn off the Pirate Warrior tactics.')
            command.add_argument('--screen-settle', type=float, default=1.5,
                                 help='With --pace careful: stable board/hand interval in seconds (0.5 to 5; default 1.5).')
        if name in ('play', 'loop'):
            command.add_argument('--deck-profile', help='Deck metadata JSON; Standard defaults to the supplied cannon Warrior.')
            command.add_argument('--mode', choices=['practice', 'wild', 'standard'], default='wild' if name == 'loop' else 'practice',
                                 help='wild/standard require the corresponding ranked format; practice allows AI games.')
        if name == 'preview':
            command.add_argument('frame')
            command.add_argument('output')
        if name == 'watch':
            command.add_argument('--minutes', type=float, default=15)
        if name == 'loop':
            command.add_argument('--games', type=int, required=True)
            command.add_argument('--policy', choices=['laya', 'rules'], default='laya')
            command.add_argument('--aggressive', action='store_true')
            command.add_argument('--frames', action='store_true')
            command.add_argument('--deck-id', default=None)
            command.add_argument('--menu-profile', help='Calibrated ranked menu JSON bound to this deck ID.')
            command.add_argument('--idle-limit', type=float, default=180.0)
            command.add_argument('--restart-every', default=None, metavar='N[,N...]',
                                 help='Close and reopen the game between games. 5,6,7 picks one at random each time.')
        if name == 'friend':
            command.add_argument('--friend-agreed', action='store_true', required=True,
                                 help='Required. Confirms your opponent knows a bot is playing.')
            command.add_argument('--games', type=int, default=None, help='Stop after this many games. Default: until Esc.')
            command.add_argument('--policy', choices=['laya', 'rules'], default='laya')
            command.add_argument('--aggressive', action='store_true', help='Hit face whenever an attacker can.')
            command.add_argument('--frames', action='store_true', help='Save a frame before every move. Slower.')
        if name == 'play':
            command.add_argument('--frames', action='store_true', help='Save a frame before every move. Slower.')
            command.add_argument('--execute', action='store_true', help='Send real mouse input.')
            command.add_argument('--policy', choices=['laya', 'rules'], default='laya')
            command.add_argument('--aggressive', action='store_true', help='Hit face whenever an attacker can.')
            command.add_argument('--friend-agreed', action='store_true',
                                 help='Also act in a friendly challenge. Use only if your opponent knows a bot is playing.')
    args = parser.parse_args()
    if args.command in ('play', 'loop', 'friend') and not 0.5 <= args.screen_settle <= 5:
        parser.error('--screen-settle must be between 0.5 and 5 seconds')
    if args.config:
        try:
            configure(args.config)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    if args.command == 'loop':
        if args.mode == 'standard' and not args.deck_id:
            parser.error('Standard loops require an explicit --deck-id for the imported Warrior deck')
        args.deck_id = args.deck_id or DECK_ID
        if args.mode == 'standard' and not args.menu_profile:
            parser.error('Standard loops require --menu-profile; see docs/ranked-modes.md')
        if args.menu_profile:
            from .menu_profile import load
            try:
                load(args.menu_profile, args.mode, args.deck_id)
            except (ValueError, KeyError, TypeError, OSError) as error:
                parser.error(f'--menu-profile: {error}')
        if args.restart_every is not None:
            try:
                args.restart_every = parse_restart_every(args.restart_every)
            except ValueError as error:
                parser.error(f'--restart-every: {error}')
    if args.command == 'friend' and args.games is not None and args.games <= 0:
        parser.error('--games must be positive')
    if args.command == 'loop' and args.games <= 0:
        parser.error('--games must be positive')
    args.handler(args)


if __name__ == '__main__':
    main()
