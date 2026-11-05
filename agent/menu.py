"""Walks the menus to practice or ranked games using both scene and screen checks.

Every click needs two independent proofs: the scene in LoadingScreen.log, and small screen regions
compared against frames recorded while the player walked the same route. Anything else, such as a
popup or a moved deck, matches nothing, and the walker stops instead of guessing.
The selected mode's game-type and format checks stay in force during play.
"""
import json
import time
from pathlib import Path

from .loop import Stop

REFS = Path(__file__).with_name('menu_refs.json')
STEP = 3

# name: (frame in the recording, box). Boxes hold fixed text, away from glows and the mouse.
REGIONS = {
    'entrance_prompt': ('entrance.png', (808, 842, 1118, 902)),
    'entrance_notice': ('entrance.png', (378, 932, 1600, 958)),
    'hub_buttons': ('051.png', (890, 548, 1030, 578)),
    'hub_bar': ('051.png', (600, 990, 1310, 1014)),
    'mode_title': ('004.png', (865, 15, 1045, 42)),
    'mode_adventure': ('004.png', (765, 700, 900, 728)),
    'adv_left': ('053.png', (640, 18, 750, 42)),
    'adv_right': ('053.png', (1290, 18, 1490, 40)),
    'adv_expert': ('053.png', (1420, 275, 1540, 300)),
    'deck_title': ('056.png', (655, 20, 765, 42)),
    'deck_choose': ('056.png', (670, 115, 775, 138)),
    'deck_tile': ('056.png', (388, 280, 462, 300)),
    'deck_name': ('056.png', (1365, 672, 1440, 692)),
    'opp_title': ('058.png', (1370, 10, 1460, 30)),
    'opp_warrior': ('058.png', (1240, 255, 1290, 278)),
    'opp_selected': ('058.png', (1225, 286, 1555, 294)),
    'mulligan_confirm': ('013.png', (925, 835, 1005, 870)),
    'mulligan_title': ('013.png', (870, 138, 1050, 178)),
}

# Checked in order, most specific first: (scene, screen, regions, click). A region starting with ! must not match.
# The opponent list slides over the deck screen and leaves the deck tiles showing, so deck rows exclude it.
SCREENS = [
    ('LOGIN', 'entrance_ready', ('entrance_prompt', 'entrance_notice'), (960, 872)),
    ('HUB', 'hub', ('hub_buttons', 'hub_bar'), (963, 560)),
    ('GAME_MODE', 'mode_ready', ('mode_title', 'mode_adventure'), (1370, 750)),
    ('GAME_MODE', 'mode_pick', ('mode_title',), (940, 365)),
    ('ADVENTURE', 'opp_ready', ('opp_title', 'opp_warrior', 'opp_selected'), (1420, 865)),
    ('ADVENTURE', 'opp_pick', ('opp_title',), (1392, 258)),
    ('ADVENTURE', 'deck_ready', ('deck_title', 'deck_choose', 'deck_tile', 'deck_name', '!opp_title'), (1403, 880)),
    ('ADVENTURE', 'deck_pick', ('deck_title', 'deck_choose', 'deck_tile', '!opp_title'), (480, 272)),
    ('ADVENTURE', 'adv_ready', ('adv_left', 'adv_right', 'adv_expert'), (1390, 890)),
    ('ADVENTURE', 'adv_pick', ('adv_left', 'adv_right'), (1380, 288)),
]
# Ranked Wild has a separate route so practice recognition cannot start an online game.
# The format picker is shared by Standard, Wild and Casual; always choose Wild explicitly.
WILD_REGIONS = {
    'wild_title': ('wild-ready.png', (653, 24, 780, 52)),
    'constructed_choose': ('wild-ready.png', (669, 119, 780, 148)),
    'wild_deck_tile': ('wild-ready.png', (383, 282, 465, 309)),
    'wild_deck_name': ('wild-ready.png', (1360, 677, 1443, 701)),
    'wild_start': ('wild-ready.png', (1345, 858, 1463, 920)),
    'format_wild': ('formats.png', (545, 634, 695, 675)),
    'format_standard': ('formats.png', (860, 562, 1044, 604)),
}
WILD_SCREENS = [
    SCREENS[0],
    ('HUB', 'wild_hub', ('hub_buttons', 'hub_bar'), (960, 330)),
    ('TOURNAMENT', 'wild_format_pick', ('format_wild', 'format_standard'), (620, 420)),
    ('TOURNAMENT', 'wild_ready', ('wild_title', 'constructed_choose', 'wild_deck_tile', 'wild_deck_name', 'wild_start'), (1400, 890)),
    ('TOURNAMENT', 'wild_deck_pick', ('wild_title', 'constructed_choose', 'wild_deck_tile', '!wild_deck_name'), (480, 280)),
    ('TOURNAMENT', 'wild_format_open', ('constructed_choose', '!wild_title', '!format_wild'), (1402, 55)),
]
STANDARD_SCREENS = [
    SCREENS[0],
    ('HUB', 'standard_hub', ('hub_buttons', 'hub_bar'), (960, 330)),
    ('TOURNAMENT', 'standard_format_pick', ('format_wild', 'format_standard'), (950, 420)),
    ('TOURNAMENT', 'standard_ready', ('standard_title', 'constructed_choose', 'standard_deck_tile', 'standard_deck_name', 'standard_start'), (1400, 890)),
    ('TOURNAMENT', 'standard_deck_pick', ('standard_title', 'constructed_choose', 'standard_deck_tile', '!standard_deck_name'), (480, 280)),
    ('TOURNAMENT', 'standard_format_open', ('constructed_choose', '!standard_title', '!format_standard'), (1402, 55)),
]
# An empty part of the end-of-game screen, where any click continues.
CONTINUE = (1221, 883)
AWAY = (960, 1066)  # Parks the mouse, because hovering a button changes how it looks.
GAME_SCENE = 'GAMEPLAY'
# Before the main menu the game shows loading screens, which can legitimately take a while. Only the entrance gets a click.
STARTING_SCENES = (None, 'STARTUP', 'LOGIN')


def signature(bgra, width, box):
    left, top, right, bottom = box
    values = []
    for y in range(top, bottom, STEP):
        row = y * width
        for x in range(left, right, STEP):
            at = (row + x) * 4
            values += (bgra[at], bgra[at + 1], bgra[at + 2])
    return values


def difference(first, second):
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


class Regions:
    """Compares the live screen with the recorded references."""
    TOLERANCE = 14.0

    def __init__(self, screen, refs=None):
        self.screen = screen
        self.refs = refs if refs is not None else json.loads(REFS.read_text(encoding='utf-8'))
        self.pixels = None

    def refresh(self):
        if (self.screen.width, self.screen.height) != (1920, 1080):
            raise Stop('menu references require a 1920x1080 game window')
        self.pixels = self.screen.frame()

    def matches(self, name):
        if name not in self.refs:
            raise Stop(f'missing calibrated menu reference: {name}')
        ref = self.refs[name]
        sampled = signature(self.pixels, self.screen.width, ref['box'])
        return any(difference(sampled, candidate) <= self.TOLERANCE
                   for candidate in [ref['signature'], *ref.get('variants', [])])

    def mulligan_ready(self):
        self.refresh()
        return self.matches('mulligan_title') and self.matches('mulligan_confirm')


def latest_scene(lines, current=None):
    for line in lines:
        if 'OnSceneLoaded() - prevMode=' in line and 'currMode=' in line:
            current = line.split('currMode=')[1].split()[0]
    return current


def identify(scene, matches, screens=None):
    """Returns the matching row of SCREENS, or None. Only the current scene's screens are considered."""
    for row in SCREENS if screens is None else screens:
        if row[0] == scene and all(not matches(n[1:]) if n.startswith('!') else matches(n) for n in row[2]):
            return row
    return None


class MenuWalker:
    def __init__(self, scenes, regions, inputs, *, timeout=45.0, startup_timeout=240.0, max_clicks=12, settle=0.5, slide_time=3.0,
                 clock=time.monotonic, sleep=time.sleep, log=print, mode='practice', deck_click=None):
        if mode not in ('practice', 'wild', 'standard'):
            raise ValueError(f'unsupported mode: {mode}')
        self.screens = {'practice': SCREENS, 'wild': WILD_SCREENS, 'standard': STANDARD_SCREENS}[mode]
        if deck_click is not None:
            self.screens = [(scene, name, refs, tuple(deck_click) if name.endswith('deck_pick') else point)
                            for scene, name, refs, point in self.screens]
        self.scenes, self.regions, self.inputs = scenes, regions, inputs
        self.timeout, self.max_clicks, self.settle, self.slide_time = timeout, max_clicks, settle, slide_time
        self.clock, self.sleep, self.log = clock, sleep, log
        self.startup_timeout = startup_timeout
        self.scene = None

    def read_scene(self):
        self.scene = latest_scene(self.scenes(), self.scene)
        return self.scene

    def _check_abort(self):
        if self.inputs.aborted():
            raise Stop('stopped by the player')
        started = self.clock()
        ready = getattr(self.inputs, 'ready', None)
        paused = False
        while ready and not ready():
            if not paused:
                self.log('menu paused: bring Hearthstone to the foreground to continue')
                paused = True
            if self.inputs.aborted():
                raise Stop('stopped by the player')
            self.sleep(0.1)
        if paused:
            self.log('menu resumed')
        return self.clock() - started

    def to_game(self):
        """Click through to a game. Stops on anything unrecognized, without clicking it."""
        clicks = 0
        last = None
        repeats = 0
        self._check_abort()
        recognized_at = clicked_at = started = self.clock()
        self.inputs.careful = True
        self.inputs.send([('move', AWAY)])
        while self.read_scene() != GAME_SCENE:
            paused = self._check_abort()
            recognized_at += paused
            clicked_at += paused
            started += paused
            self.regions.refresh()
            row = identify(self.scene, self.regions.matches, self.screens)
            if self.scene in STARTING_SCENES and row is None:
                if self.clock() - started > self.startup_timeout:
                    raise Stop(f'the game did not reach the main menu; still in {self.scene}')
                recognized_at = self.clock()
                self.sleep(0.5)
                continue
            if row is None:
                if self.clock() - recognized_at > self.timeout:
                    raise Stop(f'unrecognized screen in scene {self.scene}; leaving it alone')
                self.sleep(0.2)
                continue
            recognized_at = self.clock()
            _, name, _, point = row
            # The opponent list takes about a second to slide in, and until then the screen reads as deck_pick.
            if name == 'deck_pick' and last == 'deck_ready' and self.clock() - clicked_at < self.slide_time:
                self.sleep(0.2)
                continue
            repeats = repeats + 1 if name == last else 1
            if repeats > 3:
                raise Stop(f'clicking {name} three times changed nothing')
            if clicks >= self.max_clicks:
                raise Stop('menu click limit reached')
            last = name
            clicks += 1
            clicked_at = self.clock()
            self.log(f'menu: {name} in {self.scene}, click {point}')
            self.inputs.careful = True
            self.inputs.send([('click', point), ('move', AWAY)])
            self.sleep(self.settle)
            # A start click can take seconds to load the game, so allow the scene to change first.
            deadline = self.clock() + (6.0 if name.endswith('ready') else 1.0)
            while self.clock() < deadline and self.read_scene() != GAME_SCENE:
                paused = self._check_abort()
                deadline += paused
                recognized_at += paused
                started += paused
                clicked_at += paused
                self.regions.refresh()
                if identify(self.scene, self.regions.matches, self.screens) != row:
                    break
                self.sleep(0.2)
        self.log('menu: game is loading')

    def leave_game(self):
        """Click past the end-of-game screens, only while the game scene is still showing."""
        clicks = 0
        deadline = self.clock() + self.timeout
        while self.read_scene() == GAME_SCENE:
            deadline += self._check_abort()
            if self.clock() > deadline or clicks >= self.max_clicks * 2:
                raise Stop('could not leave the end-of-game screen')
            self.inputs.careful = True
            self.inputs.send([('click', CONTINUE)])
            clicks += 1
            self.sleep(1.0)
        self.log(f'menu: back in {self.scene} after {clicks} clicks')


def latest_deck_id(lines, current=None):
    """The deck the game just searched with, from Decks.log."""
    waiting = False
    for line in lines:
        if 'Finding Game With Deck' in line:
            waiting = True
        elif waiting and '# Deck ID:' in line:
            current = line.split('# Deck ID:')[1].strip()
            waiting = False
    return current


def decode_png(path):
    """Reads the frames this project saves (8-bit RGB, no row filters) back to BGRA."""
    import struct
    import zlib
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n' or tuple(data[24:29]) != (8, 2, 0, 0, 0):
        raise ValueError('decode_png requires an unfiltered 8-bit RGB project capture, not an RGBA screenshot')
    width, height = struct.unpack('>II', data[16:24])
    at = 8
    packed = b''
    while at < len(data):
        length = struct.unpack('>I', data[at:at + 4])[0]
        if data[at + 4:at + 8] == b'IDAT':
            packed += data[at + 8:at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(packed)
    stride = width * 3 + 1
    bgra = bytearray(width * height * 4)
    for y in range(height):
        if raw[y * stride] != 0:
            raise ValueError('decode_png does not support PNG row filters')
        row = raw[y * stride + 1:(y + 1) * stride]
        start = y * width * 4
        bgra[start:start + width * 4:4] = row[2::3]
        bgra[start + 1:start + width * 4:4] = row[1::3]
        bgra[start + 2:start + width * 4:4] = row[0::3]
    return bytes(bgra), width, height


def calibrate(folder):
    """Writes the references from a recording, then shows how every recorded frame is identified."""
    folder = Path(folder)
    refs = json.loads(REFS.read_text(encoding='utf-8')) if REFS.exists() else {}
    for name, (frame, box) in REGIONS.items():
        pixels, width, _ = decode_png(folder / frame)
        refs[name] = {**refs.get(name, {}), 'box': list(box), 'signature': signature(pixels, width, box)}
    REFS.write_text(json.dumps(refs), encoding='utf-8')
    scene = None
    scenes_by_frame = {}
    for line in open(folder / 'clicks.jsonl', encoding='utf-8'):
        entry = json.loads(line)
        if entry['kind'] == 'scene':
            scene = entry['line'].split('currMode=')[1]
        else:
            scenes_by_frame[entry['frame']] = (scene, entry['x'], entry['y'])
    print('frame | scene when clicked | click | screen | worst region difference for that screen')
    for frame in sorted(scenes_by_frame):
        pixels, width, _ = decode_png(folder / frame)
        scores = {n: difference(signature(pixels, width, r['box']), r['signature']) for n, r in refs.items()}
        found = identify(scenes_by_frame[frame][0], lambda n: scores[n] <= Regions.TOLERANCE)
        found = found[1] if found else None
        print(frame, *scenes_by_frame[frame], found, 'mulligan' if scores['mulligan_confirm'] <= Regions.TOLERANCE else '',
              {n: round(s, 1) for n, s in scores.items() if s <= 30})
