# Observed progression after an end-turn submission

The offline audit checks what the authoritative GameState power log records after
an end-turn send. It requires an ordered sequence: GameEntity STEP=MAIN_END during
the starting turn, GameEntity TURN incrementing by exactly one, then
GameEntity STEP=MAIN_ACTION. Player TURN tags and PowerTaskList animation events
do not satisfy these conditions.

The starting state must be RUNNING at MAIN_ACTION with a known positive turn
number. The submitted end-turn must refer to an observed option in a non-stale
packet without packet parse/unsupported errors, and must have no target,
sub-option, or placement. Both NONE and INVALID option error values are retained
for this diagnostic audit; neither grants execution permission.

A next submission, new game, changed game state, or discontinuous turn number
ends a pending check. Later events cannot repair it. A prefix ending before all
three observations is reported as incomplete evidence. Results freeze once the
ordered progression is observed. The final unterminated line is never consumed.

This is **not execution confirmation**. Turn progression can also be caused by
timeout or other game behavior. It does not establish that a particular mouse
input was delivered, that the opponent became active, or that retry is safe.
No result is passed to the controller or model.

## Reproduce

```powershell
cargo build --offline --target-dir target/validation
.venv/Scripts/python.exe scripts/audit_turns.py <Power.log>
```

The script reads the input bytes once, makes a temporary frozen copy for Rust's
submission exporter, and audits those same bytes. It verifies game/submission
numbers and selection fields against the export, refusing mismatches. Reports
include hashes of the frozen log prefix and submission export; no raw log text,
names, or account details are included. The temporary copy is removed afterward.

## Confirmed Rogue session

All 21 end-turn submissions in the five confirmed Rogue games were followed by
the ordered progression. All 21 had the logged main-option error INVALID. These
observations show why that error value alone cannot establish failed execution;
they do not establish its general meaning or justify treating it as legal.

See [audit results](rogue-turn-progression-review.json), including the send and
evidence line numbers for each attempt. Six regression tests cover event order,
animation/player-tag exclusion, partial lines, discontinuities, next-send and
new-game boundaries, unsupported baselines, and mismatched export refusal.
