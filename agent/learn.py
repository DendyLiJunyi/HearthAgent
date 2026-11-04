"""Review failures and train a candidate checkpoint on corrected decisions, with replay data."""
import argparse
import json
import sys
from pathlib import Path

from .learning import collect, corrected_rows
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
    train = commands.add_parser('train')
    train.add_argument('--lessons', type=Path, default=ROOT / '.data/learning')
    train.add_argument('--base', type=Path, default=ROOT / '.data/imitation/laya-combo')
    train.add_argument('--replay', type=Path, default=ROOT / '.data/imitation/train-combo.jsonl')
    train.add_argument('--output', type=Path, required=True)
    train.add_argument('--epochs', type=int, default=2)
    train.add_argument('--correction-weight', type=int, default=8)
    train.add_argument('--train-encoder', action='store_true', help='Update the encoder too; slower and needs regression evaluation.')
    train.add_argument('--replay-limit', type=int, default=0, help='Deterministic replay sample size; zero uses all replay rows.')
    args = parser.parse_args()
    cards = load_cards()
    if args.command == 'collect':
        print(json.dumps(collect(args.sessions, args.output, cards), ensure_ascii=False, indent=1))
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
            corrected_rows(args.lessons / 'cases.jsonl', proposal, cards)
        labels_path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding='utf-8')
        print('Correction saved:', args.id)
        return
    if args.output.exists():
        parser.error('output already exists; use a fresh candidate checkpoint directory')
    if args.epochs < 1 or args.correction_weight < 1 or args.replay_limit < 0:
        parser.error('epochs and correction weight must be positive; replay limit must be nonnegative')
    corrections = corrected_rows(args.lessons / 'cases.jsonl', args.lessons / 'labels.json', cards)
    if not corrections:
        parser.error('no corrected decisions; review lessons.md and label cases before training')
    replay = [json.loads(line) for line in args.replay.read_text(encoding='utf-8').splitlines()]
    if not replay:
        parser.error('replay data must not be empty')
    if args.replay_limit and len(replay) > args.replay_limit:
        import random
        replay = random.Random(0).sample(replay, args.replay_limit)
    rows = replay + corrections * args.correction_weight
    data = args.output.with_suffix('.train.jsonl')
    data.parent.mkdir(parents=True, exist_ok=True)
    if data.exists():
        parser.error('training data path already exists')
    data.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'services/laya'))
    from runtime import configure_environment
    configure_environment()
    import os
    os.environ['HF_HUB_OFFLINE'] = '1'
    from laya.train import TrainConfig, finetune
    config = TrainConfig(epochs=args.epochs, micro_batch=4, grad_accum=2, loss='soft-ce',
                         freeze_encoder=not args.train_encoder, encoder_lr=5e-6, head_lr=3e-5,
                         shuffle_options=('choice',), max_len=2048,
                         head_max_len=1024, log_every=20)
    print(json.dumps({'corrections': len(corrections), 'replay': len(replay), 'rows': len(rows),
                      'base': str(args.base), 'output': str(args.output)}), flush=True)
    finetune(str(data), str(args.base), str(args.output), config, device='cuda')
    print('Candidate checkpoint saved. Evaluate against held-out games before deploying it.', flush=True)


if __name__ == '__main__':
    main()
