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
from .screen import GameScreen, BattlefieldSettler, battlefield_signature, hand_signature, choice_signature, average_rgb
from .loop import Agent, RecordingInput, Stop
from .policy import LayaPolicy, RulesPolicy, load_cards
from .power import PowerLog, candidates_from

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
INSTALL = Path(r'D:\Hearthstone')
BATTLE_NET = Path(r'D:\Battle.net\Battle.net.exe')
BATTLE_NET_LOGS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Battle.net/Logs'
DECK_ID = '9567872927'  # The player's 海盗战 deck, as Decks.log names it.
CHECKPOINT = ROOT / '.data/imitation/laya-combo'


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

    def __init__(self, folder, log_path, screen=None, every_frame=False, screen_settle=1.5):
        self.folder, self.log_path, self.count = Path(folder), Path(log_path), 0
        self.screen, self.every_frame = screen, every_frame
        self.button = None
        self.settler = BattlefieldSettler(seconds=screen_settle)
        self.hand_settler = BattlefieldSettler(seconds=screen_settle)
        self.choice_settler = BattlefieldSettler()
        self.choice_key = None
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
        stable = self.settler.ready(battlefield_signature(pixels, self.screen.width))
        hand_stable = self.hand_settler.ready(hand_signature(pixels, self.screen.width))
        lit = geometry.end_turn_lit(self.button)
        self.screen_checks += 1
        self.screen_check_seconds += time.monotonic() - started
        for reason, ready in (('button', lit), ('board', stable), ('hand', hand_stable)):
            self.screen_blocked[reason] += not ready
        return lit and stable and hand_stable

    def reset_screen(self):
        self.settler.reset()
        self.hand_settler.reset()

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
        # Saving a frame costs real time, so a normal move skips it. A failed click is worth the cost.
        if self.every_frame or event['kind'] == 'no_send':
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


def build_policy(name, aggressive=False):
    cards = load_cards()
    if name == 'rules':
        return RulesPolicy(cards, aggressive)
    return LayaPolicy.load(cards, path=CHECKPOINT, aggressive=aggressive)


def play(args):
    policy = build_policy(args.policy, args.aggressive)
    log_path = Path(args.log or current_log())
    record = None
    if args.execute:
        from .menu import Regions
        from .windows_input import WindowsInput
        window = game_window()
        inputs = WindowsInput(window, current_window=game_window)
        record = SessionRecord(ROOT / '.data/live' / time.strftime('%Y%m%d-%H%M%S'), log_path,
                               GameScreen(window), args.frames, args.screen_settle)
        regions = Regions(record.screen)
        style = 'aggressive ' if args.aggressive else ''
        modes = ('Ranked Wild only' if args.mode == 'wild' else
                 'Practice and agreed friendly games only' if args.friend_agreed else 'Practice games only')
        print(f'LIVE INPUT ENABLED with the {style}{policy.name} policy. Hold Esc to stop. {modes}.', flush=True)
    else:
        inputs = RecordingInput()
        print('Dry run: nothing is sent to the game.', flush=True)
    agent = Agent(Tail(log_path, session_check=current_log if args.execute and not args.log else None),
                  policy, inputs, before_input=record, settle=0.5, confirm_timeout=2.0,
                  choice_timeout=5.0, lit_required=3,
                  screen_ready=record.screen_ready if record else None, friend_agreed=args.friend_agreed, mode=args.mode,
                  mulligan_ready=regions.mulligan_ready if record else None,
                  choice_ready=record.choice_ready if record else None,
                  opening_delay=20.0 if args.execute else 0.0)
    if record:
        agent.screen_reset = record.reset_screen
        agent.strict_screen = True
    if not args.execute:
        # Nobody answers the game in a dry run, so print one plan for the open decision.
        agent.settle = 0
        agent.confirm_timeout = 0
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
    outcome.update(mode=args.mode, policy=policy.name, checkpoint=getattr(policy, 'checkpoint', None),
                   aggressive=args.aggressive, actions=agent.actions, model_fallbacks=getattr(policy, 'fallbacks', 0))
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


def end_of(path):
    return Path(path).stat().st_size if Path(path).exists() else 0


def outcome_counts(results):
    return {'games': len(results), 'won': sum(r.get('won') is True for r in results),
            'lost': sum(r.get('won') is False for r in results),
            'drawn': sum(r.get('won') is None for r in results)}


def run_loop(args):
    """Games from the menus, one after another, until the count, a stop, or Esc."""
    from .menu import GAME_SCENE, MenuWalker, Regions, latest_deck_id
    from .windows_input import WindowsInput
    policy = build_policy(args.policy, args.aggressive)
    window = ensure_game()
    screen = GameScreen(window)
    regions = Regions(screen)
    inputs = WindowsInput(window, current_window=game_window)
    print(f'LIVE INPUT ENABLED: {args.games} {args.mode} games with the {policy.name} policy. Hold Esc to stop.', flush=True)
    folder = ROOT / '.data/live' / ('loop-' + time.strftime('%Y%m%d-%H%M%S'))
    results, stopped = [], None
    summary = lambda: {**outcome_counts(results), 'results': results, 'stopped': stopped,
                       'mode': args.mode, 'policy': policy.name, 'checkpoint': getattr(policy, 'checkpoint', None),
                       'model_fallbacks': getattr(policy, 'fallbacks', 0)}
    try:
        wait_for_focus(inputs, window)
        log_path = current_log()
        walker = MenuWalker(Tail(log_path.parent / 'LoadingScreen.log'), regions, inputs, mode=args.mode,
                            timeout=180.0 if args.mode == 'wild' else 45.0)
        while len(results) < args.games:
            tail = Tail(log_path, session_check=current_log)
            if walker.read_scene() != GAME_SCENE:
                tail.position = end_of(log_path)
                walker.to_game()
            deck = latest_deck_id(Tail(log_path.parent / 'Decks.log')())
            if deck != args.deck_id:
                raise Stop(f'the game started with deck {deck}, not {args.deck_id}; leaving it alone')
            record = SessionRecord(folder / f'{len(results) + 1:03d}', log_path, screen, args.frames, args.screen_settle)
            agent = Agent(tail, policy, inputs, before_input=record, settle=0.5, confirm_timeout=2.0, choice_timeout=5.0,
                          lit_required=3, screen_ready=record.screen_ready, idle_limit=args.idle_limit,
                          mulligan_ready=regions.mulligan_ready, mode=args.mode,
                          choice_ready=record.choice_ready,
                          opening_delay=20.0)
            agent.screen_reset = record.reset_screen
            agent.strict_screen = True
            agent.pump()
            if agent.power.game and agent.power.game.over:
                walker.leave_game()  # Started on an end screen, so this game does not count.
                continue
            try:
                result = agent.run_game()
            except KeyboardInterrupt:
                reason = 'stopped from terminal (Ctrl+C)'
                record.finish({'stopped': reason, 'actions': agent.actions, 'mode': args.mode,
                               'policy': policy.name, 'checkpoint': getattr(policy, 'checkpoint', None)})
                raise Stop(reason) from None
            except (Stop, RuntimeError, geometry.GeometryError) as stop:
                record.finish({'stopped': str(stop), 'actions': agent.actions, 'mode': args.mode,
                               'policy': policy.name, 'checkpoint': getattr(policy, 'checkpoint', None),
                               'model_fallbacks': getattr(policy, 'fallbacks', 0)})
                raise
            record.finish({'result': result, 'policy': policy.name, 'actions': agent.actions,
                           'checkpoint': getattr(policy, 'checkpoint', None),
                           'model_fallbacks': getattr(policy, 'fallbacks', 0)})
            results.append({**result, 'actions': agent.actions})
            label = 'won' if result.get('won') is True else 'lost' if result.get('won') is False else 'drawn'
            print(f'Game {len(results)}: {label} ({agent.actions} actions)', flush=True)
            walker.leave_game()
    except (Stop, RuntimeError, geometry.GeometryError, OSError) as stop:
        stopped = str(stop)
    except KeyboardInterrupt:
        stopped = 'stopped from terminal (Ctrl+C)'
    folder.mkdir(parents=True, exist_ok=True)
    if stopped:
        try:
            screen.save(folder / 'stopped.png')
        except OSError as error:
            print('Stopped frame unavailable:', error, flush=True)
    with open(folder / 'summary.json', 'w', encoding='utf-8') as out:
        json.dump(summary(), out, ensure_ascii=False, indent=1)
    print(json.dumps(summary(), ensure_ascii=False), flush=True)
    print('Saved to', folder, flush=True)
    if stopped:
        sys.exit(2)


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
    for name, handler in (('status', status), ('preview', preview), ('play', play), ('watch', watch), ('loop', run_loop)):
        command = commands.add_parser(name)
        command.set_defaults(handler=handler)
        command.add_argument('--log')
        if name in ('play', 'loop'):
            command.add_argument('--screen-settle', type=float, default=1.5,
                                 help='Stable board/hand interval in seconds (0.5 to 5; default 1.5). Try 0.6 for faster play.')
            command.add_argument('--mode', choices=['practice', 'wild'], default='wild' if name == 'loop' else 'practice',
                                 help='wild requires Ranked Wild; practice allows AI games.')
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
            command.add_argument('--idle-limit', type=float, default=180.0)
        if name == 'play':
            command.add_argument('--frames', action='store_true', help='Save a frame before every move. Slower.')
            command.add_argument('--execute', action='store_true', help='Send real mouse input.')
            command.add_argument('--policy', choices=['laya', 'rules'], default='laya')
            command.add_argument('--aggressive', action='store_true', help='Hit face whenever an attacker can.')
            command.add_argument('--friend-agreed', action='store_true',
                                 help='Also act in a friendly challenge. Use only if your opponent knows a bot is playing.')
    args = parser.parse_args()
    if args.command in ('play', 'loop') and not 0.5 <= args.screen_settle <= 5:
        parser.error('--screen-settle must be between 0.5 and 5 seconds')
    if args.config:
        try:
            configure(args.config)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    if args.command == 'loop':
        args.deck_id = args.deck_id or DECK_ID
    if args.command == 'loop' and args.games <= 0:
        parser.error('--games must be positive')
    args.handler(args)


if __name__ == '__main__':
    main()
