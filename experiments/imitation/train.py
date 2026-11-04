"""Fine-tune Laya on training games only, with option-order shuffling. Test games are never written."""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'laya'))
from features import TEST_GROUPS, load_cards, load_rows, question, render_candidate, render_state
from runtime import MODEL_REVISION, ROOT, configure_environment


def write_training_data(path):
    cards = load_cards()
    rows = [r for r in load_rows() if r['group'] not in TEST_GROUPS and 1 < len(r['candidates']) <= 32]
    random.Random(0).shuffle(rows)
    with open(path, 'w', encoding='utf-8') as out:
        for row in rows:
            texts = [render_candidate(row, c, cards) for c in row['candidates']]
            out.write(json.dumps({'state': render_state(row, cards), 'questions': question(texts),
                                  'gold': {'action': {'probabilities': {f"c{row['label']}": 1.0}}}}, ensure_ascii=False) + '\n')
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / '.data/imitation/laya-finetuned'))
    parser.add_argument('--epochs', type=int, default=6)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    configure_environment()
    os.environ['HF_HUB_OFFLINE'] = '1'
    data = ROOT / '.data/imitation/train.jsonl'
    print('training rows', write_training_data(data), flush=True)
    base = (ROOT / '.tools/huggingface/hub/models--convaiinnovations--laya/snapshots'
            / MODEL_REVISION / 'multilingual')
    from laya.train import TrainConfig, dry_run, finetune
    config = TrainConfig(epochs=args.epochs, micro_batch=4, grad_accum=2, loss='soft-ce',
                         shuffle_options=('choice',), max_len=2048, head_max_len=1024, log_every=20)
    if args.dry_run:
        print(json.dumps(dry_run(str(data), str(base), config), default=str, indent=1)[:2500])
        return
    print(json.dumps(finetune(str(data), str(base), args.output, config, device='cuda'), default=str, indent=1)[:4000])


if __name__ == '__main__':
    main()
