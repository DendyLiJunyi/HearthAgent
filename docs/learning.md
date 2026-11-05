# Learning from failed matches

The latest evaluator reports raw-model, rules-only and deployed-policy agreement separately for
every suite. See [evaluation and independent data](reliability-improvements.md) for optional final-test
input and overlap checks. Broad blunder flags are now soft policy preferences, not exclusions.

Patches the Pirate (`CFM_637`, including the `CORE_` alias) is always returned during mulligan.
Both the rules policy and Laya use this correction. Other cards retain the existing rule of keeping
cards costing at most two mana. Mulligan is still controlled by rules, not Laya's action head.
Recordings now include the replacement entity IDs, so the decision can be reviewed directly.

After a match, the agent writes `lessons.json` and `lessons.md` beside `moves.jsonl` and `Power.log`.
A completed loss produces review cases only for the agent's own planned actions that match a
confirmed `SendOption`. Failed gestures, stopped games, unrelated games in the same log and later
human moves are excluded. Wins are retained as recordings but do not create loss cases.
Copied decisions deduplicate by the contents of the state, candidates and chosen action.

The review includes card names, all executable alternatives, the chosen move and heuristic hints.
Hints are not training labels. For example, a general hint to play an attack buffer can be wrong
when summoning it triggers Risky Skipper and kills the attacker. Losing does not establish that
every move was wrong, either.

Collect recordings and preserve existing corrections:

```powershell
.venv/Scripts/python.exe -m agent.learn collect
```

This writes `.data/learning/cases.jsonl`, `summary.json` and an initial `labels.json`. Read the
per-session `lessons.md`, then record a specific correction with its case ID and candidate number:

```powershell
.venv/Scripts/python.exe -m agent.learn label --id <case-id> --corrected <index> --reason "Why this move is better"
```

Corrections require a reason, reviewer identity, a different legal action and unchanged case contents.
The first five saved corrections are assistant board-review judgments, not user demonstrations or
proven optimal actions. They cover a survival Taunt, unsupported synergy minions, summoning
Parachute Brigand for free and ordering Risky Skipper before a follow-up minion.

Train a separate candidate without modifying the active checkpoint:

```powershell
.venv/Scripts/python.exe -m agent.learn train --output .data/imitation/laya-next
```

By default this updates the action head for two epochs. Add `--train-encoder` to update the encoder
too. Reviewed corrections are mixed with the existing 939 training examples to reduce forgetting;
their weight can be set with `--correction-weight`. Training refuses to overwrite a candidate.
For a shorter encoder adaptation, `--replay-limit 128 --correction-weight 12 --epochs 1`
uses a deterministic sample of 128 earlier examples and twelve copies of each correction.
The generated `.train.jsonl` preserves the exact inputs used. Nothing is sent to an external service.

Evaluate the candidate against the fixed 61 Warrior and 213 older held-out player decisions:

```powershell
.venv/Scripts/python.exe experiments/imitation/evaluate_lessons.py --candidate .data/imitation/laya-next
```

The report separates held-out player agreement from in-sample correction fit and raw action-head
fit. Eligibility requires no regression on either held-out set, no fallbacks, no regression on the
reviewed corrections and improved raw correction fit. It does not measure win rate. Do not substitute
the package's in-sample calibration accuracy for this held-out comparison.
Because these fixed games are used to select checkpoints, treat them as a validation set rather
than an untouched final test of a selected model's strength.

The default active checkpoint is `.data/imitation/laya-wild-reviewed-20261105` following
the reviewed promotion below. Training alone does not switch it. Match outcomes record
the exact checkpoint path used. Explicit `--config` checkpoint settings take precedence.

## First loss-learning run (2026-11-04)

The recordings produced 98 unique confirmed decision cases from completed losses and three
Patches-keep plans. Five assistant-reviewed corrections were saved in `.data/learning/labels.json`.
A head-only candidate did not improve correction fit and was rejected. A targeted encoder update
used those five corrections plus 128 earlier replay examples:

| Check | Current checkpoint | Targeted candidate |
| --- | --- | --- |
| Warrior validation agreement | 30/61 | 31/61 |
| Older validation agreement | 80/213 | 74/213 |
| Reviewed corrections, deployed policy | 3/5 | 4/5 |
| Reviewed corrections, raw action head | 0/5 | 4/5 |
| Model fallbacks | 0 | 0 |

The targeted candidate learned the corrections but regressed on older games, so it was **not
deployed**. It remains at `.data/imitation/laya-loss-targeted-20261104`, with its independent
comparison at `.data/learning/targeted-evaluation.json`. The active model remains `laya-combo`;
the Patches rule is active independently of model weights. The implementation has 125 passing
agent tests; all 62 mutation checks were caught.

## Wild recording review and promotion (2026-11-05)

Two Wild runs with saved deck ID `9569814789` contain 41 completed games:
`loop-20261105-122834` completed 5 (4 wins), then stopped on a log-session change;
`loop-20261105-125141` completed 36 (8 wins), then stopped on Battle.net login.
An additional interrupted game is excluded from training cases. This is not a
single completed 40-game run. The 36-game batch recorded 122 unconfirmed-input
events and 5 wrong-card recoveries; strategy learning does not fix these gestures.

Collection yielded 667 unique confirmed decisions from 29 completed losses.
Six assistant board-review judgments were saved with exact case IDs and reasons,
including survival Taunt, immediate Engineer value and preserving a 1-health Skipper
with Captain. These are reviewed preferences, not human demonstrations or optimality
proofs; heuristic hints and game outcomes were not exported as automatic labels.

The candidate used one encoder-training epoch, 939 earlier replay rows and eight
copies of each correction (987 input rows). The trainer split out 98 calibration
items. Its exact training file, labels, logs and comparison remain under
`.data/imitation/laya-wild-reviewed-20261105.train.jsonl` and
`.data/learning/wild-20261105/`.

| Offline check | Previous `laya-combo` | Reviewed candidate |
| --- | --- | --- |
| Warrior validation agreement | 31/61 | 32/61 |
| Older validation agreement | 82/213 | 89/213 |
| Reviewed correction fit | 0/6 | 5/6 |
| Raw correction fit | 0/6 | 5/6 |
| Model fallbacks / raw failures | 0 / 0 | 0 / 0 |

The candidate passed the existing promotion gate and is the new default for new
CLI/policy loads. `laya-combo` remains intact for rollback through an explicit config.
The comparison uses fixed validation data, and correction fit is in-sample; neither
establishes improved ranked win rate. Existing agents retain their loaded weights.
