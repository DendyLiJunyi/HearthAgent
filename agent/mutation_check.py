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
    ('friend mode needs agreement', 'loop.py', "if not self.friend_agreed or game.game_type != FRIENDLY_GAME_TYPE:", "if game.game_type != FRIENDLY_GAME_TYPE:"),
    ('friend mode refuses other games', 'loop.py', "if not self.friend_agreed or game.game_type != FRIENDLY_GAME_TYPE:", "if not self.friend_agreed:"),
    ('friend mode needs a local player', 'loop.py', "if game.local is None:\n                raise Stop('cannot tell which player is local')\n            return\n        friendly", "if False:\n                raise Stop('cannot tell which player is local')\n            return\n        friendly"),
    ('both name lines are read first', 'power.py', "if game.named_players < 2:", "if False:"),
    ('two names use the readable hand', 'power.py', "if len(holders) == 1:", "if False:"),
    ('both readable hands decide nothing', 'power.py', "if len(holders) == 1:", "if holders:"),
    ('the coin does not name a player', 'power.py', "not in (None, '', 'GAME_005')}", "not in (None, '')}"),
    ('restart only when due', 'cli.py', "if plan.game_played() and len(results) < args.games:", "if len(results) < args.games:"),
    ('no restart after the last game', 'cli.py', "if plan.game_played() and len(results) < args.games:", "if plan.game_played():"),
    ('esc beats a restart', 'cli.py', "if inputs.aborted():\n                    raise Stop('stopped by the player')\n                if walker.read_scene()", "if False:\n                    raise Stop('stopped by the player')\n                if walker.read_scene()"),
    ('game scene is never closed', 'cli.py', "if walker.read_scene() == GAME_SCENE:\n                    raise Stop('still in", "if False:\n                    raise Stop('still in"),
    ('restart uses the new log', 'cli.py', "log_path = current_log()\n                walker = new_walker()", "walker = new_walker()"),
    ('restart uses the new window', 'cli.py', "inputs = WindowsInput(window, current_window=game_window)\n                bring_to_front", "bring_to_front"),
    ('reopened game is brought forward', 'cli.py', "bring_to_front(window['hwnd'])  # Otherwise", "pass  # Otherwise"),
    ('stretch picks again', 'restart.py', "self.played = 0\n        self.target = self.rng.choice(self.choices)", "self.played = 0"),
    ('force only after asking fails', 'restart.py', "if post(window['hwnd']) and wait_for_exit(CLOSE_TIMEOUT):", "if False:"),
    ('forced close is confirmed', 'restart.py', "if not wait_for_exit(FORCE_TIMEOUT):", "if False:"),
    ('esc stops the close wait', 'restart.py', "if aborted():\n                raise Stop('stopped by the player')", "if False:\n                raise Stop('stopped by the player')"),
    ('window must settle at full size', 'cli.py', "if window and (window['width'], window['height']) == (1920, 1080):", "if window:"),
    ('window must hold still', 'cli.py', "same = same + 1 if window == last else 1", "same = same + 1"),
    ('reopen failure is reported', 'cli.py', "except SystemExit as error:\n        raise Stop(str(error)) from None", "except ZeroDivisionError as error:\n        raise Stop(str(error)) from None"),
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
    ('recheck before retry', 'loop.py', "try:\n                        self._refresh_guard(game, packet['revision'], packet['id'])\n                    except StateChanged:", "try:\n                        pass\n                    except StateChanged:"),
    ('backlog holds input', 'loop.py', "if not self._log_caught_up(game):", "if False:"),
    ('backlog wait has a limit', 'loop.py', "return self.clock() >= self.drain_wait[2]", "return False"),
    ('backlog limit respected', 'loop.py', "if self.power.backlog.size <= self.backlog_limit:", "if True:"),
    ('backlog pops replayed lines', 'power.py', "self.backlog.played(line.split(' - ', 1)[1].strip())", "pass"),
    ('backlog resets each game', 'power.py', "self.backlog = AnimationBacklog()\n            self.games.append", "self.games.append"),
    ('replay never changes state', 'power.py', "self.backlog.played(line.split(' - ', 1)[1].strip())\n            return", "self.backlog.played(line.split(' - ', 1)[1].strip())"),
    ('decision made once per packet', 'loop.py', "if self.plan_cache and self.plan_cache[0] == key:", "if False:"),
    ('early decision respects game type', 'loop.py', "self.check_allowed(game)\n        try:\n            self._plan(game)", "try:\n            self._plan(game)"),
    ('recovery needs opt-in', 'loop.py', "        if self.recover:\n            return self._abandon_move(game, packet, candidate)", "        if True:\n            return self._abandon_move(game, packet, candidate)"),
    ('recovery stops at wrong action limit', 'loop.py', "if not self.recover or self.wrong_actions >= MAX_WRONG_ACTIONS:", "if not self.recover:"),
    ('failed move not offered again', 'loop.py', "if tuple(candidate[k] for k in MOVE_KEY) in failed:", "if False:"),
    ('failed end turn waits for timer', 'loop.py', "if candidate['kind'] == 'end_turn':\n            self.abandoned = (game.number, packet['id'])", "if False:\n            self.abandoned = (game.number, packet['id'])"),
    ('abandoned packet sends nothing', 'loop.py', "if self.abandoned == (game.number, game.packet['id']):\n                if self._end_turn_relit(game):", "if False:\n                if self._end_turn_relit(game):"),
    ('input waits for a new turn', 'loop.py', "if self.power.backlog.turn_behind and self.clock() < self.drain_wait[3]:", "if False:"),
    ('turn wait has a limit', 'loop.py', "if self.power.backlog.turn_behind and self.clock() < self.drain_wait[3]:", "if self.power.backlog.turn_behind:"),
    ('repeated line matches its own copy', 'power.py', "self.reached = max(self.reached, copies.popleft() + 1)", "self.reached = max(self.reached, copies.pop() + 1)"),
    ('grey button outlasts the short limit', 'loop.py', "self.screen_wait = (*key, self.screen_started + self.button_timeout)", "self.screen_wait = (*key, self.screen_started + self.screen_timeout)"),
    ('failed read uses the short limit', 'loop.py', "self.screen_wait = (*key, min(self.screen_wait[2], self.screen_started + self.screen_timeout))", "pass"),
    ('dropped end turn reopens when lit', 'loop.py', "if self._end_turn_relit(game):\n                    return 'recovered'", "if False:\n                    return 'recovered'"),
    ('relit retries have a limit', 'loop.py', "or self.relit_retries.get(key, 0) >= MAX_RELIT_RETRIES:", "or False:"),
    ('relit needs repeated lit reads', 'loop.py', "if self.lit_reads < self.lit_required:\n            return False\n        self.relit_retries", "if False:\n            return False\n        self.relit_retries"),
    ('relit restores dropped moves', 'loop.py', "self.failed_moves.pop(game.packet['id'], None)  # Moves", "pass  # Moves"),
    ('cut gesture is cancelled', 'loop.py', "if self.needs_cancel:\n            # A gesture", "if False:\n            # A gesture"),
    ('failure slows next moves', 'loop.py', "self.inputs.careful = attempt > 1 or self.cautious_moves > 0", "self.inputs.careful = attempt > 1"),
    ('focus loss stops without recovery', 'loop.py', "except FocusLost:\n                if not self.recover:\n                    raise\n                # The log decides", "except FocusLost:\n                # The log decides"),
    ('esc still stops a choice', 'loop.py', "or 'stopped by the player' in str(stop) or 'new game' in str(stop):", "or 'new game' in str(stop):"),
    ('lit button still needed when fast', 'cli.py', "return lit and stable\n\n    def focus_on", "return stable\n\n    def focus_on"),
    ('patch wait has a cap', 'cli.py', "now - self.focus_started >= self.focus_cap or not self.focus_points or", "not self.focus_points or"),
    ('tactics skip existing lethal', 'policy.py', "if self.tactics and max(scores) < 1000.0 else None", "if self.tactics else None"),
    ('buff before pirate attacks', 'tactics.py', "if not pirate_attack:\n        return None", "return None"),
    ('buff leaves other picks alone', 'tactics.py', "if not pirate_attack:\n        return None", "pass"),
    ('laya applies buff correction', 'policy.py', "if self.tactics:\n            buff = deck_tactics.buff_first(state, candidates, pick, self.cards)", "if False:\n            buff = deck_tactics.buff_first(state, candidates, pick, self.cards)"),
    ('skipper blocks buff', 'tactics.py', "if _skipper_risk(state) or len(state['you']['minions']) >= 7:", "if len(state['you']['minions']) >= 7:"),
    ('full board blocks buff', 'tactics.py', "if _skipper_risk(state) or len(state['you']['minions']) >= 7:", "if _skipper_risk(state):"),
    ('taunt blocks lethal setup', 'tactics.py', "if any('TAUNT' in m['keywords'] for m in opponent['minions']) or _skipper_risk(state):", "if _skipper_risk(state):"),
    ('lethal setup must reach lethal', 'tactics.py', "if total >= enemy and all(", "if all("),
    ('leftmost card is nudged', 'geometry.py', "nudge = LEFTMOST_NUDGE if index == 0 and count >= LEFTMOST_NUDGE_FROM else 0", "nudge = 0"),
    ('only the leftmost card is nudged', 'geometry.py', "nudge = LEFTMOST_NUDGE if index == 0 and count >= LEFTMOST_NUDGE_FROM else 0", "nudge = LEFTMOST_NUDGE if count >= LEFTMOST_NUDGE_FROM else 0"),
    ('small hands are not nudged', 'geometry.py', "nudge = LEFTMOST_NUDGE if index == 0 and count >= LEFTMOST_NUDGE_FROM else 0", "nudge = LEFTMOST_NUDGE if index == 0 else 0"),
    ('wrong card keeps a frame', 'cli.py', "or event.get('recovery') == 'wrong_action':", "or False:"),
    ('hero never attacks into death', 'tactics.py', "if kind == 'your_hero' and target['atk'] >= life:", "if False:"),
    ('a kill is never wasted', 'tactics.py', "(power >= _hp(target) or 'POISONOUS' in words):\n        return False", "(False or 'POISONOUS' in words):\n        return False"),
    ('poison counts as a kill', 'tactics.py', "(power >= _hp(target) or 'POISONOUS' in words):", "(power >= _hp(target)):"),
    ('shield stops a kill', 'tactics.py', "if not shielded and 'IMMUNE' not in target['keywords'] and (power", "if 'IMMUNE' not in target['keywords'] and (power"),
    ('taunt excuses an attack', 'tactics.py', "if 'TAUNT' in target['keywords']:\n        return False\n    if kind == 'your_hero':", "if kind == 'your_hero':"),
    ('large hero hit is wasted', 'tactics.py', "return target['atk'] >= HERO_HIT_LIMIT", "return False"),
    ('surviving attacker is fine', 'tactics.py', "or 'DEATHRATTLE' in words or target['atk'] < life:", "or 'DEATHRATTLE' in words:"),
    ('deathrattle attacker is fine', 'tactics.py', "or 'DEATHRATTLE' in words or target['atk'] < life:", "or target['atk'] < life:"),
    ('others can finish the target', 'tactics.py', "return not _finished_by_others(state, candidate, candidates, found, cards, power)", "return True"),
    ('hozen counts on attack', 'tactics.py', "return attacker['atk'] + buffed, _hp(attacker) + buffed", "return attacker['atk'], _hp(attacker)"),
    ('wasted attack dropped from model pick', 'policy.py', "kept = deck_tactics.without_wasted_attacks(state, candidates, pool, self.cards)", "kept = pool"),
    ('wasted attack dropped from rules pick', 'policy.py', "pool = deck_tactics.without_wasted_attacks(state, candidates, pool, self.cards)", "pass"),
    ('coin needs a card one mana away', 'tactics.py', "if fits and card['cost'] == you['mana'] + 1 and base_id", "if fits and base_id"),
    ('coin skips risky skipper', 'tactics.py', "card['cost'] == you['mana'] + 1 and base_id(card['card']) != RISKY_SKIPPER:", "card['cost'] == you['mana'] + 1:"),
    ('coin needs board space', 'tactics.py', "(card['type'] == 'MINION' and len(you['minions']) < 7)", "card['type'] == 'MINION'"),
    ('coin used instead of passing', 'policy.py', "coin = deck_tactics.coin_before_passing(state, candidates, self.cards)\n                if coin is not None:\n                    self._reason", "coin = None\n                if coin is not None:\n                    self._reason"),
    ('coin needs a tempo gain', 'tactics.py', "return coin if usable_now < mana and _best_spend(costs, mana + 1) > usable_now + 1 else None", "return coin if usable_now < mana else None"),
    ('coin held when mana is usable', 'tactics.py', "return coin if usable_now < mana and _best_spend(costs, mana + 1) > usable_now + 1 else None", "return coin if _best_spend(costs, mana + 1) > usable_now + 1 else None"),
    ('coin stays out of mulligan', 'tactics.py', "real = [row for row in rows if row[2].get('name') != COIN_NAME]", "real = rows"),
    ('tactics Patches mulligan', 'tactics.py', "keep = False  # Another Pirate summons it from the deck for free.", "keep = True"),
    ('slow cards replaced', 'tactics.py', "elif card_id in TOO_SLOW_TO_KEEP:\n            keep = False", "elif card_id in TOO_SLOW_TO_KEEP:\n            keep = True"),
    ('no passing with damage left', 'policy.py', "if self.tactics and candidates[pick]['kind'] == 'end_turn':", "if False:"),
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
    ('own-side damage veto', 'policy.py', "return any(w in text for w in HOSTILE) and 'friendly' not in text\n\n    def is_useful", "return False\n\n    def is_useful"),
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
