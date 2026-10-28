# Reviewing real attack windows

The Rogue corpus currently has 47 samples from five games. All are unreviewed;
there is no real-game Laya accuracy result yet. Samples contain only an incomplete
attack subset, so a preference means best among those candidates, not best legal
move in the game. A sole candidate is not evidence of strategic skill.

Keep the exporter output and manifest as frozen sources. The separate label
sidecar leaves them unchanged; another corpus export overwrites its destination.

```powershell
.venv/Scripts/python.exe scripts/validate_review.py .data/attack-review.jsonl
.venv/Scripts/python.exe scripts/prepare_review.py .data/attack-review.jsonl --manifest .data/review-manifest.json
```

The packet is `.data/rogue-review.md`; labels are `.data/rogue-labels.json`.
Existing review outputs are never overwritten by the preparation command.
For each sample, inspect the board and supplied candidates. Change only its
`annotation` in the sidecar. A reviewed annotation looks like this (use actual IDs):

```json
{
  "status": "reviewed",
  "preferred_candidate_ids": ["actual-candidate-id"],
  "reviewer": "reviewer identifier",
  "reason": "Explain the preference using the observed prefix only."
}
```

Multiple preferred IDs express ties. If missing state prevents a defensible
preference, use `status: "excluded"`, an empty preference list, and a reviewer
and reason. Leave untouched samples `unreviewed`. Do not use later outcomes or
the player's selected move as automatic ground truth. Labels require human
review; the validation command checks consistency, not strategic correctness.

The validator checks schema, active deck code, content hashes, non-executable
flags, supported attack shapes, unique candidates and game windows, and label
references. Hashes detect content changes but do not authenticate a source or
reviewer. Input limits are 100,000 records and 4 MiB per record.

The output `.data/review-manifest.json` records sample identity, annotation status
and a deterministic game-level split. For at least two games, the last fifth
(at least one game) in hash order is held out. A single game has no evaluation
split. Freeze the manifest and corpus before model tuning: adding games can
change the split. Never tune on held-out labels. The manifest carries no boards
or preferred answers and is not itself model input.

Validation on 2026-10-28: 47 samples in five groups passed; zero labelled evaluation
samples, `evaluation_ready=false`. Six new integrity tests and five existing
corpus tests passed. GPU evaluation on labelled real windows remains pending.

## Frozen evaluation

```powershell
.venv/Scripts/python.exe services/laya/evaluate_real.py .data/attack-review.jsonl --manifest .data/review-manifest.json --labels .data/rogue-labels.json --representation sparse --mode evaluate
```

The manifest must exactly match the frozen source dataset. Sidecar labels bind
to its dataset hash; duplicate or unknown sample IDs are rejected. Labels,
reviewer notes, visible-card evidence and later outcomes are excluded from model
requests. Without reviewed held-out samples, the command writes an explicit
`no_eligible_samples` report and does not load the model. Tied preferences are
allowed. Accuracy excludes single-candidate cases and reports invalid replies
separately rather than counting them as successful evidence.

The development-only GPU diagnostic is now complete; see
[real-window input audit](laya-real-diagnostic.md). It exposes strong candidate
order sensitivity despite resolving input truncation. This is not a scored
held-out evaluation.
