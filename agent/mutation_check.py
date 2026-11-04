"""Break each safety rule in a temporary copy and confirm the tests notice. Real files are untouched."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [
    ('Patches mulligan exception', 'policy.py', "card_id.removeprefix('CORE_') in MULLIGAN_RETURN_TO_DECK or ", ""),
    ('opening animation delay', 'loop.py', "if self.clock() < self.opening_ready_at:", "if False:"),
    ('wild requires ranked', 'loop.py', "game.game_type != 'GT_RANKED' or game.format_type != 'FT_WILD'", "game.format_type != 'FT_WILD'"),
    ('wild requires format', 'loop.py', "game.game_type != 'GT_RANKED' or game.format_type != 'FT_WILD'", "game.game_type != 'GT_RANKED'"),
    ('wild needs local player', 'loop.py', "if game.local is None:\n                raise Stop('cannot tell which player is local')", "if False:\n                raise Stop('cannot tell which player is local')"),
    ('practice-only gate', 'loop.py', "if game.game_type not in ALLOWED_GAME_TYPES and not friendly:", "if False:"),
    ('friendly needs agreement', 'loop.py', "friendly = self.friend_agreed and game.game_type == FRIENDLY_GAME_TYPE", "friendly = game.game_type == FRIENDLY_GAME_TYPE"),
    ('agreement covers only friendly', 'loop.py', "friendly = self.friend_agreed and game.game_type == FRIENDLY_GAME_TYPE", "friendly = self.friend_agreed"),
    ('aggressive filter on Laya', 'policy.py', "return self.rules.face_first(state, candidates, safe) if self.aggressive else safe", "return safe"),
    ('aggressive filter on rules', 'policy.py', "pool = self.face_first(state, candidates, pool)", "pass"),
    ('forced trade stays legal', 'policy.py', "and move['source'] in can_hit_face and move.get('sub', -1) < 0)", "and move.get('sub', -1) < 0)"),
    ('settle wait', 'loop.py', "if not self.quiet():", "if False:"),
    ('stale packet check', 'loop.py', "if game.packet['revision'] != game.revision:", "if False:"),
    ('revision guard', 'loop.py', "if self.power.game is not game or game.revision != revision:", "if False:"),
    ('send must match plan', 'loop.py', "if any(sent[k] != candidate[k] for k in ('option', 'sub', 'target', 'position')):", "if False:"),
    ('placement confirmation', 'loop.py', "('option', 'sub', 'target', 'position')", "('option', 'sub', 'target')"),
    ('choice entity confirmation', 'loop.py', "if set(receipt['selected']) != expected or len(receipt['selected']) != len(expected):", "if False:"),
    ('partial choice cannot retry', 'loop.py', "if len(game.choices_sent) > before:\n                raise Stop('incomplete choice receipt; refusing to resend')", "if False:\n                raise Stop('incomplete choice receipt; refusing to resend')"),
    ('missing send is detected', 'loop.py', "raise NoSend('no SendOption after input')", "return"),
    ('retry limit', 'loop.py', "attempts = self.max_attempts if len(gestures) == 1 else 1", "attempts = 50"),
    ('recheck before retry', 'loop.py', "self._refresh_guard(game, packet['revision'], packet['id'])\n        self.inputs.send([CANCEL])", "pass\n        self.inputs.send([CANCEL])"),
    ('ability screen order', 'power.py', "'sub_slot': on_screen.index(sub_entity['id']) if sub_entity else None", "'sub_slot': sub_index if sub_entity else None"),
    ('model skips abilities', 'policy.py', "if max(scores) >= 1000.0 or ability or len(candidates) > self.MAX_OPTIONS:", "if max(scores) >= 1000.0 or len(candidates) > self.MAX_OPTIONS:"),
    ('abort check', 'loop.py', "if self.inputs.aborted():\n            raise Stop('stopped by the player')\n        self.pump()",
     "self.pump()"),
    ('action limit', 'loop.py', "if self.actions >= self.max_actions:", "if False:"),
    ('game over check', 'loop.py', "if game.over:", "if False:"),
    ('rejected options', 'power.py', "if option['error'] != 'NONE' or not option['entity']:", "if not option['entity']:"),
    ('rejected targets', 'power.py', "targets = [t for t in holder['targets'] if t['error'] == 'NONE']",
     "targets = list(holder['targets'])"),
    ('animation stream ignored', 'power.py', "if 'GameState.' not in line or ' - ' not in line:", "if ' - ' not in line:"),
    ('16:9 check', 'geometry.py', "if width <= 0 or height <= 0 or abs(width / height - BASE_W / BASE_H) > 0.01:", "if False:"),
    ('desktop bounds', 'windows_input.py', "if width <= 1 or height <= 1 or not (left <= point[0] < left + width and top <= point[1] < top + height):", "if False:"),
    ('choice resend limit', 'loop.py', "for attempt in range(1, self.max_attempts + 1):\n            self.inputs.careful = True", "for attempt in range(1, 51):\n            self.inputs.careful = True"),
    ('choice resend only confirms', 'loop.py', "self.inputs.send(gestures if attempt == 1 else gestures[-1:])", "self.inputs.send(gestures)"),
    ('recheck before choice resend', 'loop.py', "self._refresh_guard(game, revision)\n        raise Stop(f'choice", "pass\n        raise Stop(f'choice"),
    ('soft strategy preferences', 'policy.py', "totals[i] -= self.preference_penalty * self.orders", "totals[i] -= 0"),
    ('own-side damage veto', 'policy.py', "return any(w in text for w in HOSTILE) and 'friendly' not in text\n\n    def _free_value", "return False\n\n    def _free_value"),
    ('end-turn veto', 'policy.py', "return any(self._free_value(c, found, candidates, state) for c in candidates)", "return False"),
    ('screen wait', 'loop.py', "if not self._screen_caught_up(game):", "if False:"),
    ('screen wait has a limit', 'loop.py', "if self.clock() < self.screen_wait[2]:", "if True:"),
    ('per-packet screen wait', 'loop.py', "if not self.screen_wait or self.screen_wait[:2] != key:", "if not self.screen_wait:"),
    ('lit button rule', 'geometry.py', "return blue < 40 and max(red, green) >= 80 and max(red, green) - blue >= 60", "return blue < 40"),
    ('last-moment button check', 'loop.py', "if not self._still_lit():", "if False:"),
    ('two lit readings', 'loop.py', "if self.lit_reads >= self.lit_required:", "if self.lit_reads >= 1:"),
    ('spare hero power', 'policy.py', "if kind == 'your_power':\n            return not target", "if False:\n            return not target"),
    ('going second mulligan row', 'geometry.py', "5: (4, 257, 964)", "5: (5, 250, 960)"),
    ('menu screen must match', 'menu.py', "if row[0] == scene and all(not matches(n[1:]) if n.startswith('!') else matches(n) for n in row[2]):", "if row[0] == scene:"),
    ('menu scene must match', 'menu.py', "if row[0] == scene and all(", "if all("),
    ('menu exclusions', 'menu.py', "not matches(n[1:]) if n.startswith('!') else matches(n)", "True if n.startswith('!') else matches(n)"),
    ('slide cooldown', 'menu.py', "if name == 'deck_pick' and last == 'deck_ready' and self.clock() - clicked_at < self.slide_time:", "if False:"),
    ('menu repeat limit', 'menu.py', "if repeats > 3:", "if False:"),
    ('leave only in game scene', 'menu.py', "if self.clock() > deadline or clicks >= self.max_clicks * 2:", "if False:"),
    ('mulligan waits for screen', 'loop.py', "if game.choice['type'] == 'MULLIGAN' and not self._mulligan_on_screen():", "if False:"),
    ('silent log stop', 'loop.py', "if status != 'paused' and self.idle_limit and self.clock() - self.last_line_time > self.idle_limit:", "if False:"),
    ('deck id search only', 'menu.py', "elif waiting and '# Deck ID:' in line:", "elif '# Deck ID:' in line:"),
    ('retry cancels first', 'loop.py', "self.inputs.send(gestures if attempt == 1 else [CANCEL, *gestures])", "self.inputs.send(gestures)"),
    ('cancel before handing back', 'loop.py', "self.inputs.send([CANCEL])  # Never", "pass  # Never"),
    ('login screens are waited for', 'menu.py', "if self.scene in STARTING_SCENES and row is None:", "if False:"),
    ('wasted mana rule', 'policy.py', "return self._hits_own_side(candidate, found) or self.wastes_mana(state, candidate, candidates)", "return self._hits_own_side(candidate, found)"),
    ('wasted mana compares best spend', 'policy.py', "mana - costs[candidate['source']]) < best", "mana - costs[candidate['source']]) < 0"),
    ('mulligan keep cost', 'policy.py', "MULLIGAN_KEEP_COST = 2", "MULLIGAN_KEEP_COST = 3"),
    ('careful retry', 'loop.py', "self.inputs.careful = attempt > 1", "self.inputs.careful = False"),
    ('lit readings must be consecutive', 'loop.py', "self.lit_reads = self.lit_reads + 1 if self.screen_ready() else 0", "self.lit_reads = self.lit_reads + (1 if self.screen_ready() else 0)"),
    ('rules on lethal', 'policy.py', "if max(scores) >= 1000.0 or ability or len(candidates) > self.MAX_OPTIONS:", "if ability or len(candidates) > self.MAX_OPTIONS:"),
    ('model fallback', 'policy.py', "self.fallbacks += 1\n            return self.rules.choose(state, candidates, cards)", "raise"),
    ('order averaging', 'policy.py', "for order in self._orders(len(candidates)):", "for order in self._orders(len(candidates))[:1]:"),
]


def main():
    # A failing baseline would make every mutation look caught.
    baseline = subprocess.run([sys.executable, '-m', 'unittest', 'agent.test_agent', 'agent.test_wild', 'agent.test_learning', 'agent.test_screen_settle', 'agent.test_focus_pause', 'agent.test_reliability', 'agent.test_evaluation'], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)
    if baseline.returncode != 0:
        raise SystemExit('the tests already fail without any mutation, so this check would prove nothing')
    survived = []
    for name, filename, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / 'agent'
            shutil.copytree(ROOT / 'agent', copy, ignore=shutil.ignore_patterns('__pycache__'))
            target = copy / filename
            text = target.read_text(encoding='utf-8')
            if old not in text:
                raise SystemExit(f'mutation text not found: {name}')
            target.write_text(text.replace(old, new, 1), encoding='utf-8')
            try:
                result = subprocess.run([sys.executable, '-m', 'unittest', 'agent.test_agent', 'agent.test_wild', 'agent.test_learning', 'agent.test_screen_settle', 'agent.test_focus_pause', 'agent.test_reliability', 'agent.test_evaluation'], cwd=folder,
                                        capture_output=True, text=True, timeout=30)
                caught = result.returncode != 0
            except subprocess.TimeoutExpired:
                caught = True  # Removing a limit made a test run forever, so the tests did notice.
            print(('caught  ' if caught else 'SURVIVED'), name, flush=True)
            if not caught:
                survived.append(name)
    print(f'{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} caught')
    sys.exit(1 if survived else 0)


if __name__ == '__main__':
    main()
