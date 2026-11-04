"""Check the agent against recorded games. Nothing is sent, and recorded moves are not imitated.

For every recorded decision the agent plans its own action. This shows the parsing, choice and
gesture code cope with real positions. It says nothing about move quality or click accuracy.
"""
import collections
import glob
import json
import sys

from . import geometry
from .policy import RulesPolicy, load_cards
from .power import PowerLog, candidates_from


def check(paths):
    cards = load_cards()
    policy = RulesPolicy(cards)
    stats = collections.Counter()
    hand_targets = collections.Counter()

    def plan(packet):
        state = packet['state']
        candidates = candidates_from(packet)
        stats['decisions'] += 1
        for candidate in candidates:
            stats['candidates'] += 1
            try:
                geometry.plan_action(state, candidate)
                stats['candidates_plannable'] += 1
            except geometry.GeometryError:
                stats['candidates_unplannable'] += 1
                if any(c['id'] == candidate['target'] for c in state['you'].get('hand', [])):
                    source = packet['cards'].get(str(candidate['source']))
                    hand_targets[cards.get(source, {}).get('name', source)] += 1
        choice = candidates[policy.choose(state, candidates, packet['cards'])]
        try:
            geometry.plan_action(state, choice)
            stats['chosen_plannable'] += 1
        except geometry.GeometryError:
            stats['chosen_unplannable'] += 1

    for path in paths:
        log = PowerLog()
        seen = set()
        with open(path, encoding='utf-8', errors='replace') as handle:
            lines = handle.readlines()
        for line in lines:
            previous = log.game
            packet = previous.packet if previous else None
            sends = len(previous.sends) if previous else 0
            log.feed(line)
            game = log.game
            if not game:
                continue
            if previous is game and packet and len(game.sends) > sends:
                same = packet['revision'] == game.revision
                stats['send_with_no_state_change_after_packet' if same else 'send_after_state_changed'] += 1
            if previous is game and packet and game.packet is not packet and len(game.sends) == sends:
                stats['packet_replaced_without_send'] += 1
            if game.choice and (game.number, game.choice['id']) not in seen and game.choice['entities']:
                seen.add((game.number, game.choice['id']))
                stats[f"choice_{game.choice['type']}"] += 1
        for game in log.games:
            stats['games'] += 1
            for entry in game.sends:
                if entry['packet']['state']['you'] and entry['packet']['state']['opponent']:
                    plan(entry['packet'])
        stats['malformed'] += log.malformed
    return {'stats': dict(stats), 'hand_target_sources': dict(hand_targets)}


if __name__ == '__main__':
    print(json.dumps(check(sorted(glob.glob(sys.argv[1]))), indent=1, ensure_ascii=False))
