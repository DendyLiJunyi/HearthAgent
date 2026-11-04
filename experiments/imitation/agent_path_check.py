"""Score the deployed LayaPolicy through the agent's own parser on the same held-out games."""
import glob
import json
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(__file__))
from agent.policy import LayaPolicy, load_cards
from agent.power import PowerLog, candidates_from
from features import TEST_GROUPS

cards = load_cards()
policy = LayaPolicy.load(cards)
scored = hits = lethal = 0
for path in sorted(glob.glob('.data/logs/*/Power.log')):
    log = PowerLog()
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            log.feed(line)
    session = os.path.basename(os.path.dirname(path))
    for game in log.games:
        if f'{session}/game-{game.number}' not in TEST_GROUPS:
            continue
        for entry in game.sends:
            found = candidates_from(entry['packet'])
            if not 1 < len(found) <= 32:
                continue
            state = entry['packet']['state']
            if max(policy.rules.scores(state, found)) >= 1000:
                lethal += 1
            picked = found[policy.choose(state, found, entry['packet']['cards'])]
            scored += 1
            hits += all(picked[k] == entry['sent'][k] for k in ('option', 'sub', 'target'))
print(json.dumps({'decisions': scored, 'top1': round(hits / scored, 4), 'lethal_overrides': lethal,
                  'model_fallbacks': policy.fallbacks}))
