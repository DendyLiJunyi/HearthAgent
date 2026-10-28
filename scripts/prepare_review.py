"""Create a local Markdown review packet and a dataset-bound label sidecar."""
import argparse
import json
from pathlib import Path

from validate_review import checked_manifest, digest, load_samples, require, strict_json


def render(samples, frozen):
    splits = checked_manifest(samples, frozen)
    sections = ['# Offline Rogue attack review',
        'Only the supplied incomplete attack subset is being ranked. Unknown values stay unknown. '
        'Do not infer correctness from later outcomes. Record labels in the separate JSON sidecar.',
        f"Frozen dataset SHA-256: `{digest(samples)}`",
        'Keep evaluation labels hidden from model tuning. The full observed prefix projection '
        'is included under each sample; no later game information is added.']
    for sample in samples:
        board = sample['board']
        sections.extend([f"## {sample['group_id']} / window {sample['window_ordinal']}",
            f"Sample: `{sample['sample_id']}`  \nSplit: **{splits[sample['sample_id']]}**  \n"
            f"Turn: {board.get('turn')} / local player: {board.get('perspective')}",
            '| Candidate | Source entity | Target entity |', '| --- | --- | --- |'])
        for candidate in sample['action_preview']['candidates']:
            attack = candidate['action']['Attack']
            sections.append(f"| `{candidate['id']}` | {attack['source']} | {attack['target']} |")
        for player in board.get('players', []):
            sections.extend([f"### Player {player['player_id']}",
                f"Resources: {player.get('resources')} / used: {player.get('resources_used')} / "
                f"temporary: {player.get('temporary_resources')}",
                '| Zone | Entity | Card ID | Attack | Health | Damage | Armor | Cost |',
                '| --- | --- | --- | --- | --- | --- | --- | --- |'])
            for zone in ('in_play', 'hand'):
                for card in player[zone]:
                    values = [zone] + [card.get(k) for k in
                        ('entity_id', 'card_id', 'attack', 'health', 'damage', 'armor', 'cost')]
                    sections.append('| ' + ' | '.join('?' if v is None else str(v) for v in values) + ' |')
        sections.append('\nFull observed board (null means unknown):\n\n```json\n'
                        + json.dumps(board, indent=2, ensure_ascii=False) + '\n```')
        sections.append('Omitted option diagnostics:\n\n```json\n'
                        + json.dumps(sample['action_preview']['omitted'], indent=2) + '\n```')
    return '\n\n'.join(sections) + '\n'


def sidecar(samples):
    return {'schema_version': 1, 'dataset_sha256': digest(samples), 'labels': [
        {'sample_id': sample['sample_id'], 'annotation': {
            'status': 'unreviewed', 'preferred_candidate_ids': [], 'reviewer': '', 'reason': None}}
        for sample in samples]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--profile', type=Path, default=Path('config/decks/wild-rogue.json'))
    parser.add_argument('--packet', type=Path, default=Path('.data/rogue-review.md'))
    parser.add_argument('--labels', type=Path, default=Path('.data/rogue-labels.json'))
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.dataset, args.manifest, args.profile, args.packet, args.labels)]
    require(len(set(paths)) == len(paths), 'input/output paths must differ')
    require(not args.labels.exists() and not args.packet.exists(),
            'review outputs already exist; choose new paths to preserve existing work')
    samples = load_samples(args.dataset, strict_json(args.profile.read_text(encoding='utf-8'))['deck_code'])
    packet = render(samples, strict_json(args.manifest.read_text(encoding='utf-8')))
    for path in (args.packet, args.labels):
        path.parent.mkdir(parents=True, exist_ok=True)
    with args.packet.open('x', encoding='utf-8') as stream:
        stream.write(packet)
    with args.labels.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(sidecar(samples), indent=2) + '\n')
    print(json.dumps({'samples': len(samples), 'packet': str(args.packet), 'labels': str(args.labels)}))


if __name__ == '__main__':
    main()
