"""Review completed losses and save human-reviewed corrections."""
import argparse
import json
from pathlib import Path

from .learning import collect, validate_labels
from .policy import ROOT, load_cards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    review = commands.add_parser('collect')
    review.add_argument('--sessions', type=Path, default=ROOT / '.data/live')
    review.add_argument('--output', type=Path, default=ROOT / '.data/learning')
    label = commands.add_parser('label', help='Record a reviewed correction; candidate numbers are in lessons.md.')
    label.add_argument('--lessons', type=Path, default=ROOT / '.data/learning')
    label.add_argument('--id', required=True)
    label.add_argument('--corrected', type=int, required=True)
    label.add_argument('--reason', required=True)
    label.add_argument('--reviewer', default='user')
    args = parser.parse_args()
    if args.command == 'collect':
        print(json.dumps(collect(args.sessions, args.output, load_cards()), ensure_ascii=False, indent=1))
        return
    if args.command == 'label':
        from .learning import read_json
        import tempfile
        labels_path = args.lessons / 'labels.json'
        labels = read_json(labels_path)
        labels['labels'] = [l for l in labels['labels'] if l['id'] != args.id]
        labels['labels'].append({'id': args.id, 'corrected': args.corrected,
                                 'reason': args.reason, 'reviewer': args.reviewer})
        # Validate the proposed complete file before replacing any saved reviews.
        with tempfile.TemporaryDirectory() as tmp:
            proposal = Path(tmp) / 'labels.json'
            proposal.write_text(json.dumps(labels), encoding='utf-8')
            validate_labels(args.lessons / 'cases.jsonl', proposal)
        labels_path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding='utf-8')
        print('Correction saved:', args.id)
        return


if __name__ == '__main__':
    main()
