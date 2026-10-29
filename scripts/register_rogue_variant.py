"""Reproduce the user-supplied October 29 Rogue variant from cached metadata."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

CODE = 'AAEBAau2Bwrf4wLw5gL/7gOh9APj0wTIlAbBlweD1QeI2QeF6wcK7QL1uwLn3QP+7gO9gAT3nwS3swT13QTungatpwYAAA=='


def main():
    original = json.loads(Path('config/decks/wild-rogue.json').read_text(encoding='utf-8'))
    data = Path('.data/cards-enUS.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != original['source']['sha256']:
        raise ValueError('cached metadata differs from pinned source')
    metadata = {c['dbfId']: c for c in json.loads(data)}
    result = subprocess.run(['target/validation/debug/hearth-agent.exe', 'deck', CODE],
                            capture_output=True, check=True, timeout=10)
    deck = json.loads(result.stdout)['deck']
    existing = {c['dbfId']: c for c in original['cards']}
    features = {45535: ['secret', 'hero_damage_trigger', 'temporary_immunity'],
                63359: ['both_hands_transformation', 'random_generated_minion', 'hidden_information'],
                100936: ['discover', 'other_class_generation', 'quickdraw']}
    profile = copy.deepcopy(original)
    profile.update(name='User N\u0027Zoth Rogue — October 29 variant', deck_code=CODE,
                   variant_of='wild-rogue.json', user_supplied_date='2026-10-29',
                   user_label='恩佐斯贼', gameplay_supported=False)
    profile['cards'] = []
    for raw_id, count in sorted(deck['cards'].items(), key=lambda item: int(item[0])):
        identity = int(raw_id)
        if identity in existing:
            card = copy.deepcopy(existing[identity])
        else:
            source = metadata[identity]
            card = {key: source[key] for key in ('dbfId', 'id', 'name', 'cost', 'type')}
            card.update(required_features=features[identity], simulation_supported=False)
        card['count'] = count
        profile['cards'].append(card)
    Path('config/decks/wild-rogue-nzoth-2026-10-29.json').write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'registered_cards': deck['total_cards'], 'unique_cards': len(deck['cards']),
                      'gameplay_supported': False}))


if __name__ == '__main__': main()
