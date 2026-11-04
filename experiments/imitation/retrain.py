"""Fine-tune a new Laya checkpoint on the player's own moves. The current checkpoint is not touched.

Agent-played practice games are left out, so the model does not learn from itself.
Warrior training games count three times, because that deck is the target.
"""
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'laya'))
from agent.policy import load_cards
from agent.power import PowerLog, candidates_from
from features import TEST_GROUPS, question, render_candidate, render_state
from runtime import MODEL_REVISION, ROOT, configure_environment

# Fixed before any model saw them: one win and one loss.
WARRIOR_TEST = {'Hearthstone_2026_11_04_09_49_04/game-7', 'Hearthstone_2026_11_04_09_49_04/game-9'}
WARRIOR_WEIGHT = 3
OUTPUT = ROOT / '.data/imitation/laya-warrior'
KEYS = ('option', 'sub', 'target')


def decisions():
    """Yields (group, class, state row, label) for each of the player's decisions with a real choice."""
    cards = load_cards()
    for path in sorted(glob.glob(str(ROOT / '.data/logs/*/Power.log'))) + sorted(glob.glob(str(ROOT / '.data/logs-warrior/*/Power.log'))):
        session = os.path.basename(os.path.dirname(path))
        log = PowerLog()
        with open(path, encoding='utf-8', errors='replace') as handle:
            for line in handle:
                log.feed(line)
        for game in log.games:
            if game.game_type == 'GT_VS_AI':
                continue  # Every practice game so far was played by the agent.
            group = f'{session}/game-{game.number}'
            for entry in game.sends:
                packet = entry['packet']
                state = packet['state']
                if not state['you'] or not state['opponent'] or not state['you']['hero']:
                    continue
                found = candidates_from(packet)
                match = [i for i, c in enumerate(found) if all(c[k] == entry['sent'][k] for k in KEYS)]
                if len(match) != 1 or not 1 < len(found) <= 32:
                    continue
                hero = cards.get(state['you']['hero']['card'], {}).get('cardClass')
                yield group, hero, {'state': state, 'candidates': found, 'cards': packet['cards']}, match[0]


def main():
    configure_environment()
    os.environ['HF_HUB_OFFLINE'] = '1'
    cards = load_cards()
    held_out = TEST_GROUPS | WARRIOR_TEST
    rows, counts = [], {'warrior_decisions': 0, 'other_decisions': 0}
    for group, hero, row, label in decisions():
        if group in held_out:
            continue
        item = {'state': render_state(row, cards),
                'questions': question([render_candidate(row, c, cards) for c in row['candidates']]),
                'gold': {'action': {'probabilities': {f'c{label}': 1.0}}}}
        warrior = hero == 'WARRIOR'
        counts['warrior_decisions' if warrior else 'other_decisions'] += 1
        rows += [item] * (WARRIOR_WEIGHT if warrior else 1)
    random.Random(0).shuffle(rows)
    data = ROOT / '.data/imitation/train-warrior.jsonl'
    with open(data, 'w', encoding='utf-8') as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({**counts, 'training_rows': len(rows)}), flush=True)
    base = ROOT / '.tools/huggingface/hub/models--convaiinnovations--laya/snapshots' / MODEL_REVISION / 'multilingual'
    from laya.train import TrainConfig, finetune
    config = TrainConfig(epochs=6, micro_batch=4, grad_accum=2, loss='soft-ce', shuffle_options=('choice',),
                         max_len=2048, head_max_len=1024, log_every=40)
    summary = finetune(str(data), str(base), str(OUTPUT), config, device='cuda')
    print(json.dumps(summary, default=str)[:600], flush=True)


if __name__ == '__main__':
    main()
