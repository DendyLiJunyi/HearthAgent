"""Commands: `status` and `watch` read only, `preview` draws without input, `play` is dry-run unless --execute.

`loop` always sends real input, from the menus onward, and requires an explicit game count.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import geometry
from .screen import GameScreen
from .loop import Agent, RecordingInput, Stop
from .policy import LayaPolicy, RulesPolicy, load_cards
from .power import PowerLog, candidates_from

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
INSTALL = Path(r'D:\Hearthstone')
BATTLE_NET = Path(r'D:\Battle.net\Battle.net.exe')
DECK_ID = '9567872927'  # The player's 海盗战 deck, as Decks.log names it.


def current_log():
    sessions = sorted(p for p in (INSTALL / 'Logs').iterdir() if p.is_dir() and p.name.startswith('Hearthstone_'))
    if not sessions:
        raise SystemExit('no Hearthstone log session found')
    return sessions[-1] / 'Power.log'


class Tail:
    """Returns only complete lines, so a half-written line is never parsed."""

    def __init__(self, path):
        self.path, self.position, self.partial = Path(path), 0, b''

    def __call__(self):
        if not self.path.exists():
            return []
        with open(self.path, 'rb') as handle:
            handle.seek(self.position)
            data = handle.read()
            self.position = handle.tell()
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
    print(json.dumps({'game': game.number, 'type': game.game_type, 'local': game.local, 'over': game.over,
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

    def __init__(self, folder, log_path, screen=None, every_frame=False):
        self.folder, self.log_path, self.count = Path(folder), Path(log_path), 0
        self.screen, self.every_frame = screen, every_frame
        self.button = None
        self.folder.mkdir(parents=True, exist_ok=True)

    def capture(self, name):
        done = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(ROOT / 'scripts/capture-game-window.ps1'), '-OutputPath', str(self.folder / name)],
                              capture_output=True, timeout=10, check=True)
        return json.loads(done.stdout)

    def screen_ready(self):
        """Read-only. An unmeasured window size raises, and the agent then falls back to its timeout."""
        self.button = self.screen.button_rgb()
        return geometry.end_turn_lit(self.button)

    def __call__(self, event):
        self.count += 1
        name = f'{self.count:03d}.png'
        with open(self.folder / 'moves.jsonl', 'a', encoding='utf-8') as out:
            out.write(json.dumps(dict(event, frame=name, button=self.button, at=time.time()), ensure_ascii=False) + '\n')
        # Saving a frame costs real time, so a normal move skips it. A failed click is worth the cost.
        if self.every_frame or event['kind'] == 'no_send':
            self.screen.save(self.folder / name)

    def finish(self, outcome):
        with open(self.folder / 'outcome.json', 'w', encoding='utf-8') as out:
            json.dump(outcome, out, ensure_ascii=False, indent=1)
        try:
            self.capture('final.png')
        except Exception as error:
            print('final frame not saved:', error)
        if self.log_path.exists():
            shutil.copy2(self.log_path, self.folder / 'Power.log')
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
    return LayaPolicy.load(cards, aggressive=aggressive)


def play(args):
    policy = build_policy(args.policy, args.aggressive)
    log_path = Path(args.log or current_log())
    record = None
    if args.execute:
        from .windows_input import WindowsInput
        window = game_window()
        inputs = WindowsInput(window, current_window=game_window)
        record = SessionRecord(ROOT / '.data/live' / time.strftime('%Y%m%d-%H%M%S'), log_path,
                               GameScreen(window), args.frames)
        style = 'aggressive ' if args.aggressive else ''
        modes = 'Practice and agreed friendly games only' if args.friend_agreed else 'Practice games only'
        print(f'LIVE INPUT ENABLED with the {style}{policy.name} policy. Hold Esc to stop. {modes}.', flush=True)
    else:
        inputs = RecordingInput()
        print('Dry run: nothing is sent to the game.', flush=True)
    agent = Agent(Tail(log_path), policy, inputs, before_input=record, settle=0.5, confirm_timeout=2.0,
                  choice_timeout=5.0, lit_required=3,
                  screen_ready=record.screen_ready if record else None, friend_agreed=args.friend_agreed)
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
    outcome.update(policy=policy.name, aggressive=args.aggressive, actions=agent.actions, model_fallbacks=getattr(policy, 'fallbacks', 0))
    print(json.dumps(outcome), flush=True)
    if record:
        record.finish(outcome)
    for gestures in getattr(inputs, 'gestures', []):
        print(gestures)
    if 'stopped' in outcome and args.execute:
        sys.exit(2)


def ensure_game(timeout=240):
    """Open Hearthstone through Battle.net if it is not running, then wait for its window."""
    from probe_game_window import probe
    if probe()['windows']:
        return game_window()
    if not BATTLE_NET.exists():
        raise Stop(f'Battle.net not found at {BATTLE_NET}')
    print('Opening Hearthstone through Battle.net.', flush=True)
    before = current_log()
    subprocess.Popen([str(BATTLE_NET), '--exec=launch WTCG'])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # The new log folder must exist too, or the loop would read the previous session's scenes.
        if probe()['windows'] and current_log() != before:
            return game_window()
        time.sleep(1)
    raise Stop('Hearthstone did not open')


def end_of(path):
    return Path(path).stat().st_size if Path(path).exists() else 0


def run_loop(args):
    """Practice games from the menus, one after another, until the count, a stop, or Esc."""
    from .menu import GAME_SCENE, MenuWalker, Regions, latest_deck_id
    from .windows_input import WindowsInput
    policy = build_policy(args.policy, args.aggressive)
    window = ensure_game()
    screen = GameScreen(window)
    regions = Regions(screen)
    inputs = WindowsInput(window, current_window=game_window)
    print(f'LIVE INPUT ENABLED: {args.games} practice games with the {policy.name} policy. Hold Esc to stop.', flush=True)
    wait_for_focus(inputs, window)
    folder = ROOT / '.data/live' / ('loop-' + time.strftime('%Y%m%d-%H%M%S'))
    results, stopped = [], None
    summary = lambda: {'games': len(results), 'won': sum(1 for r in results if r.get('won')),
                       'lost': sum(1 for r in results if not r.get('won')), 'results': results, 'stopped': stopped,
                       'policy': policy.name, 'model_fallbacks': getattr(policy, 'fallbacks', 0)}
    try:
        log_path = current_log()
        walker = MenuWalker(Tail(log_path.parent / 'LoadingScreen.log'), regions, inputs)
        while len(results) < args.games:
            tail = Tail(log_path)
            if walker.read_scene() != GAME_SCENE:
                tail.position = end_of(log_path)
                walker.to_game()
            deck = latest_deck_id(Tail(log_path.parent / 'Decks.log')())
            if deck != args.deck_id:
                raise Stop(f'the game started with deck {deck}, not {args.deck_id}; leaving it alone')
            record = SessionRecord(folder / f'{len(results) + 1:03d}', log_path, screen, args.frames)
            agent = Agent(tail, policy, inputs, before_input=record, settle=0.5, confirm_timeout=2.0, choice_timeout=5.0,
                          lit_required=3, screen_ready=record.screen_ready, idle_limit=args.idle_limit,
                          mulligan_ready=lambda: (regions.refresh(), regions.matches('mulligan_confirm'))[1])
            agent.pump()
            if agent.power.game and agent.power.game.over:
                walker.leave_game()  # Started on an end screen, so this game does not count.
                continue
            try:
                result = agent.run_game()
            except (Stop, RuntimeError, geometry.GeometryError) as stop:
                record.finish({'stopped': str(stop), 'actions': agent.actions})
                raise
            record.finish({'result': result, 'policy': policy.name, 'actions': agent.actions,
                           'model_fallbacks': getattr(policy, 'fallbacks', 0)})
            results.append({**result, 'actions': agent.actions})
            print(f'Game {len(results)}: {"won" if result.get("won") else "lost"} ({agent.actions} actions)', flush=True)
            walker.leave_game()
    except (Stop, RuntimeError, geometry.GeometryError) as stop:
        stopped = str(stop)
    folder.mkdir(parents=True, exist_ok=True)
    if stopped:
        screen.save(folder / 'stopped.png')
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
    commands = parser.add_subparsers(dest='command', required=True)
    for name, handler in (('status', status), ('preview', preview), ('play', play), ('watch', watch), ('loop', run_loop)):
        command = commands.add_parser(name)
        command.set_defaults(handler=handler)
        command.add_argument('--log')
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
            command.add_argument('--deck-id', default=DECK_ID)
            command.add_argument('--idle-limit', type=float, default=180.0)
        if name == 'play':
            command.add_argument('--frames', action='store_true', help='Save a frame before every move. Slower.')
            command.add_argument('--execute', action='store_true', help='Send real mouse input.')
            command.add_argument('--policy', choices=['laya', 'rules'], default='laya')
            command.add_argument('--aggressive', action='store_true', help='Hit face whenever an attacker can.')
            command.add_argument('--friend-agreed', action='store_true',
                                 help='Also act in a friendly challenge. Use only if your opponent knows a bot is playing.')
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    main()
