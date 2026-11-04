# Reliability and evaluation improvements — 2026-11-04

This batch changes the Python agent. Validation: **165 agent tests and 134 script tests pass;
all 65 mutation checks are caught**. A saved four-game log parsed all six local choice receipts
completely. No input was sent to Hearthstone, and no checkpoint was trained or promoted.

## Execution and screen checks

- `SendOption` must match option, sub-option, target and placement. Hand minions and locations
  retain the rightmost-placement policy; other gestures expect position zero.
- Choice receipts must identify the same player and choice and contain the exact selected
  entity IDs. Mulligan receipts list kept original cards, excluding The Coin; the expected set
  is the selectable original cards minus replacements. Sets are order-independent. Partial receipts stop without
  resending; a choice disappearing is insufficient proof.
- Mulligan recognition timeout stops without input. Standalone live `play` now uses the same
  mulligan recognizer as the menu loop.
- Board and hand stability are checked independently. General choice regions must also settle.
  Empty signatures cannot count as stable. The conservative 20-second opening delay remains.
- Log disappearance, truncation, file replacement or rewriting at the read boundary stops the
  run. Live default-log readers also stop when the newest session changes. Start a new run after
  diagnosing the change; old parser state is not silently attached to a new file.

Live correction: the first improved run stopped after a correct mulligan because the initial
implementation interpreted the receipt as replacements. The saved run `loop-20261104-215117`
replaced entity 16 and reported kept entities 20 and 17. This interpretation is now corrected,
with regressions for replacing the middle card, replacing all cards, and going second with The Coin.

Mulligan recognition correction: `loop-20261104-221053` sent no input because the visible Confirm
button differed from the sole calibration reference (36.83 mean channel difference versus the
14 threshold). The recognizer now accepts both visually reviewed appearances and also requires
the Starting Hand heading. The threshold is unchanged; both original and new frames pass, while
a saved normal-play frame fails. This validates those recordings, not every possible animation.

Confirm-click correction: `loop-20261104-221642` selected the intended two replacements but
received no choice receipt after three Confirm attempts. Coordinates match the saved screenshot.
Immediate pointer parking after a short press is a suspected cause, not established causation.
Choice clicks now use deliberate timing, and parking waits 150 ms after release and rechecks focus.
The change passes offline tests; successful live confirmation is still required.

Submission evidence does not prove every card effect resolved correctly. Screen stability does
not identify artwork or prove a picker is present. Sparse samples and estimated geometry still
need live calibration, especially for multi-step abilities. The boundary check is not a full-file
integrity check. These limitations remain.

## Policy and reporting

### Faster screen readiness

The `loop-20261104-220207` recording showed model decisions taking 0.30–0.76 seconds,
while successive same-turn plans were 3.7–8.5 seconds apart. The run eventually stopped on
screen stability timeout. These gaps include gestures, animations, log waits and capture checks;
they are not all model latency or all avoidable delay.

Input now parks the pointer on empty board space after a gesture, before confirmation, to clear
card/minion hover. Optional `--screen-settle 0.6` on `play` or `loop` shortens the board/hand quiet
interval from 1.5 seconds to 0.6. Movement still resets the interval; lit-button, refresh and receipt
checks remain. Choice stability and the opening delay are unchanged. The faster setting is tested
offline, not yet proven reliable live. Restart the process to load it.

Recorded plans and outcomes now include cumulative `screen_checks`, `screen_blocked` counts
for button/board/hand, and time spent capturing/checking. Counts can overlap and are not durations.
Use these alongside decision latency to diagnose the next run instead of reducing every delay.

Mana-spending, end-turn and text-based targeting heuristics subtract 0.05 from a candidate's mean
probability instead of removing legal options. This is an initial Python API parameter
(`preference_penalty`), not a tuned or proven strength improvement. Explicit aggressive mode
still filters optional trades. Lethal estimates, unsupported abilities and oversized option lists
still route to rules.

Recorded option plans include decision source, reason, selected and raw model indices, whether
preferences changed the pick, elapsed decision time and checkpoint. Prediction errors include
their reason; NaN, infinite and out-of-range probabilities fall back to rules. Choice plans identify
the rules path. Outcome `planned_decisions` counts recorded plans, including plans canceled by a
later guard; it is not a count of accepted actions. `model_fallbacks` still counts prediction errors
only. Draws are reported separately from losses.

## Local configuration

Copy `config/agent.example.json` and edit installation path, Battle.net path, deck ID and checkpoint.
Relative paths resolve from the profile directory. Unknown keys and empty values are rejected.

```powershell
.venv/Scripts/python.exe -X utf8 -m agent.cli --config config/agent.example.json status
.venv/Scripts/python.exe -X utf8 -m agent.cli --config config/agent.example.json play
```

These commands send no input. `--deck-id` on `loop` overrides the profile. A different deck ID does
not recalibrate the menu tile: the existing Chinese 1920×1080 menu calibration still applies.

## Evaluation and independent data

`experiments/imitation/evaluate_lessons.py` reports deployed, raw-model and rules-only agreement
for every suite, plus decision reasons, latency, fallbacks and stable case fingerprints. Existing
promotion gates remain; optional final-test metrics are separate from model selection. Repeatedly
used held-out games are validation data, not an untouched final test.

Optional `--final-test path.jsonl` accepts one object per line with `group` (session/game identity),
`reviewer`, `row` (the full state, candidates and cards mapping), and `label` (candidate index).
It rejects empty files, missing provenance, invalid labels, duplicate cases and overlap with known
development games/cases. It cannot certify that an external checkpoint never saw a case. Keep new
final-test games out of training directories and have an independent reviewer label them before
evaluating a selected model. No such labels were fabricated in this batch.

## Offline checks

```powershell
.venv/Scripts/python.exe -m unittest discover -s agent -t . -p 'test_*.py'
.venv/Scripts/python.exe -m agent.mutation_check
```

Regressions cover wrong placement, wrong choice entities, partial and split receipts, opponent
receipts, mulligan/choice timeouts, independent hand motion, log lifecycle, decision attribution,
malformed model scores, soft preferences and evaluation overlap checks.
