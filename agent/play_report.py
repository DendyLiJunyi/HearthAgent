"""Count play mistakes in a saved run, so two versions can be compared without hundreds of games.

    python -m agent.play_report .data/live/loop-20261105-100034

Win rate against the practice AI is too close to its ceiling to show small gains, so this counts events.
Options are not recorded, so the wasted-attack count judges each chosen attack alone and then checks that the
target was still alive at the end of the turn. That is a close match for the live rule, not the same test.
"""
import argparse
import json
from pathlib import Path

from .tactics import coin_before_passing, wasted_attack

LONG_GAME_TURN = 16
COIN_CARD = 'GAME_005'


def read_rows(folder):
    with open(folder / 'moves.jsonl', encoding='utf-8') as lines:
        return [json.loads(line) for line in lines]


def wasted_attacks(options, cards):
    """Each attacker counts once per turn, because a retried drag records the same move again."""
    last_of_turn = {row['turn']: row for row in options}
    seen = set()
    for row in options:
        move = row['candidate']
        key = row['turn'], move['source']
        if key in seen or not wasted_attack(row['state'], move, [move], cards):
            continue
        seen.add(key)
        final = last_of_turn[row['turn']]['state']['opponent']['minions']
        if any(minion['id'] == move['target'] for minion in final):
            yield row


def coin_held_turns(options, cards):
    turns = set()
    for row in options:
        if row['candidate']['kind'] != 'end_turn' or row['options'] < 2:
            continue
        hand = row['state']['you'].get('hand', [])
        moves = [row['candidate'], *({'source': card['id']} for card in hand if card['card'] == COIN_CARD)]
        if coin_before_passing(row['state'], moves, cards) is not None:
            turns.add(row['turn'])
    return len(turns)


def game_report(folder, cards):
    rows = read_rows(folder)
    outcome = json.loads((folder / 'outcome.json').read_text(encoding='utf-8'))
    options = [row for row in rows if row['kind'] == 'option' and 'state' in row]
    report = {'won': (outcome.get('result') or {}).get('won'), 'first': bool(options) and options[0]['turn'] % 2 == 1,
              'last_turn': options[-1]['turn'] if options else 0, 'leftmost_plays': 0, 'other_plays': 0,
              'leftmost_wrong': 0, 'other_wrong': 0, 'failed_drags': sum(row['kind'] == 'no_send' for row in rows),
              'wasted_attacks': sum(1 for _ in wasted_attacks(options, cards)),
              'coin_held_turns': coin_held_turns(options, cards), 'decisions': outcome.get('planned_decisions') or {}}
    place = None
    for row in rows:
        if row['kind'] == 'option' and 'state' in row:
            ids = [card['id'] for card in row['state']['you'].get('hand', [])]
            source = row['candidate'].get('source')
            place = None
            if source in ids:
                place = 'leftmost' if ids.index(source) == 0 else 'other'
                report[f'{place}_plays'] += 1
        elif row['kind'] == 'recovery' and row['recovery'] == 'wrong_action' and place:
            report[f'{place}_wrong'] += 1
    return report


def run_report(folder, cards):
    games = [game_report(path, cards) for path in sorted(folder.iterdir())
             if path.is_dir() and (path / 'outcome.json').exists() and (path / 'moves.jsonl').exists()]
    return [game for game in games if game['last_turn']]


def summary(games):
    wins = sum(game['won'] is True for game in games)
    count = lambda key: sum(game[key] for game in games)
    fired = lambda reason: sum(game['decisions'].get(reason, 0) for game in games)
    first = [game for game in games if game['first']]
    second = [game for game in games if not game['first']]
    longer = [game for game in games if game['last_turn'] >= LONG_GAME_TURN]
    record = lambda part: f"{sum(game['won'] is True for game in part)}-{sum(game['won'] is not True for game in part)}"
    return '\n'.join([
        f'Games: {len(games)}, record {record(games)} ({wins / max(len(games), 1):.0%})',
        f'Going first {record(first)}, going second {record(second)}, past turn {LONG_GAME_TURN - 1} {record(longer)}',
        f"Wrong card: leftmost {count('leftmost_wrong')} of {count('leftmost_plays')} plays, "
        f"other positions {count('other_wrong')} of {count('other_plays')}",
        f"Drags the game did not take: {count('failed_drags')}",
        f"Wasted attacks: {count('wasted_attacks')}",
        f"Turns ended holding a Coin that could pay for a card: {count('coin_held_turns')}",
        f"Rules used: wasted attack stopped {fired('tactics:no_wasted_attack')}, "
        f"Coin before passing {fired('tactics:coin_before_passing')}",
    ])


def main():
    from .cli import load_cards
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='A loop folder holding numbered game folders.')
    print(summary(run_report(parser.parse_args().run, load_cards())))


if __name__ == '__main__':
    main()
