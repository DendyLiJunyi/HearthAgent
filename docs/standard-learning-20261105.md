# Standard Warrior adaptation, November 5

The source is the saved 火炮战 Standard Ranked recordings, not the earlier Wild
deck. `loop-20261105-171112` completed two losses; `loop-20261105-172616`
completed 20 games, with seven wins and 13 losses. One interrupted recording is
excluded. Game outcomes identify review material; they are not automatic labels.

The review contains 447 unique confirmed decisions from 15 completed losses.
Eleven corrections were individually reviewed for defensive Taunt use, immediate
removal, Pirate sequencing and Crowley development. Reasons and reviewer identity
are recorded beside each content-addressed case. These are assistant judgments,
not user demonstrations or proofs of optimal play. Rewind choices are handled by
the existing timeline rules and are not action-head training targets.

Five reviewed decisions from games 016 and 018 of the newer run are reserved for
validation. No training correction uses either game. The evaluator rejects matching
game groups, exact board/candidate overlap and rendered-input overlap with the
actual training file. This small review set is selection validation, not an
independent measurement of ranked strength.

Training starts from `laya-wild-reviewed-20261105` and mixes eight copies of each
Standard correction with 987 replay examples: 1,075 input rows, split by the trainer
into 968 training and 107 calibration items. The encoder candidate uses one epoch,
encoder learning rate `5e-6` and head learning rate `3e-5`. A second candidate blends
25% of this update into the original weights, retaining the original calibration.
A third candidate freezes the encoder and trains only the head for one epoch.

The evaluation runs both models with deployed tactics enabled and activates the
Standard deck profile only for the Standard suites. Historical metrics obtained
without these tactics are not directly comparable. Wild retention checks are
in-sample lessons previously used to train the baseline; Standard correction fit
is also in-sample. Promotion requires no deployed-score regression on any suite,
no inference failures, improved raw Standard correction fit, and no raw-score
regression on the held-out Standard decisions.

| Deployed agreement | Current model | Encoder candidate | 25% blend | Head only |
| --- | --- | --- | --- | --- |
| Warrior validation | 30/61 | 31/61 | 31/61 | 29/61 |
| Older validation | 86/213 | 81/213 | 83/213 | 86/213 |
| Wild lesson retention | 5/6 | 6/6 | 6/6 | 5/6 |
| Standard correction fit | 3/11 | 10/11 | 7/11 | 3/11 |
| Held-out Standard decisions | 2/5 | 2/5 | 2/5 | 2/5 |

Both encoder candidates fail the promotion gate because of older-game regression.
Neither improved the held-out Standard score. Their correction fit is insufficient
evidence to replace the current model.

The head-only candidate also fails: Warrior agreement regresses and raw correction
fit remains 0/11. All 134 encoder tensors were checked and are unchanged from the
baseline. Raw Standard correction fit is 9/11 for the encoder candidate and 4/11
for the blend, versus 0/11 for the baseline. All inference suites completed without
fallbacks or raw inference failures.

**Decision:** do not promote any of these three candidates. The default remains
`laya-wild-reviewed-20261105`, including for Standard. No checkpoint pointer or
running agent was changed. More independently reviewed Standard decisions are
needed before claiming a stronger Standard model; this five-position held-out
set is too small to establish ranked strength.

Exact cases, labels, training-file hashes, candidate logs and evaluation JSON are
in `.data/learning/standard-20261105/`. The candidate checkpoints and exact training
JSONL files remain under `.data/imitation/`; existing checkpoints are preserved.
Fourteen learning/evaluation tests pass, including validation-overlap rejection
and promotion-regression checks. No live games are started by this workflow.
