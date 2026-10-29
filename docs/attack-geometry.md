# Read-only attack gesture planning

`scripts/attack_geometry.py` maps an existing attack candidate to a proposed
move/down/move/up gesture using explicit calibrated entity rectangles. It does
not detect cards in screenshots, generate legal candidates, or send mouse input.

Calibration is bound to session, game number, snapshot revision, captured frame
SHA-256 and exact window geometry. Each attack endpoint must be a visible public
hero/minion in play: the source belongs to the local active player and the target
to the other player. Candidate and calibrated entity IDs must be unambiguous.
Boxes use normalized client coordinates. Their centers are converted to physical
screen pixels, including negative monitor origins. Missing boxes, overlapping
click points, invalid coordinates and collapsed endpoints reject the plan.

The observation envelope includes `game_number` in addition to the Rust snapshot
identity fields. Attack actions retain Rust's externally tagged JSON form:
`{"Attack":{"source":10,"target":20}}`. Explicit entity rectangles are required;
the planner never assumes that an entity is the third card or second minion.

```powershell
.venv/Scripts/python.exe scripts/attack_geometry.py fixtures/attack-geometry.json
```

The fixture is wholly synthetic. Its frame hash and window identity are placeholders
for testing, not a real-game calibration. Seven planner regression tests cover normal
coordinate mapping, identity/frame/window changes, invalid/ambiguous boxes,
hidden or wrongly owned entities, and unsupported/ambiguous candidate actions.

All output remains `actionable=false`, `legality_verified=false` and
`game_input_sent=false`. Frame binding only checks the supplied association; a
future capture producer must provide truthful current metadata and detect
overlays/animations. Live entity recognition, gesture timing, fresh validation
between input stages, cancellation/release handling and attack-result
confirmation are still required before execution.

## Preparing an annotation draft

```powershell
.venv/Scripts/python.exe scripts/prepare_attack_calibration.py --snapshot .data/saved-watch-row.json --probe .data/game-window-probe.json --frame .data/game-window.png --candidate <candidate-id> --output .data/attack-calibration-draft.json
```

Use saved inputs from the same observation. The preparer validates PNG framing,
chunk checksums and dimensions, but does not decode image pixels or certify that
the screenshot and log were captured simultaneously. It refuses partial/backlog
snapshots, ambiguous windows and existing output files. Only public in-play
heroes/minions are included; private hand entities are omitted.

The draft contains null entity boxes and `annotation_status=unreviewed`.
Visually identify each required entity, enter its normalized rectangle, and mark
the annotation `reviewed` only after checking it. Boxes must span at least four
physical pixels in both dimensions. The planner rejects unreviewed annotations,
duplicate JSON keys, non-finite values and invalid identity/window types. Four
additional preparation tests exercise privacy, review requirements and corrupt
or mismatched inputs. This manual workflow remains read-only.

## Offline attempt rehearsal

```powershell
.venv/Scripts/python.exe scripts/rehearse_attack.py fixtures/attack-geometry.json
```

This connects the planner to the same durable attempt orchestration used by the
one-shot experiment, with a recording-only adapter. The receipt is temporary and
printed with the planned gesture. Dispatch and event-count fields represent
simulation; `game_input_sent` and `execution_confirmed` remain false.

The complete input envelope and resulting plan must match at both preflight
checks, including the check after intent is persisted. Four expected events are
required for this gesture; the existing end-turn caller retains its three-event
default. A partial result cannot collect evidence or retry. Four regression
tests cover recording, duplicate reservations, changed board data, partial
gestures and invalid event-count configuration. Actual gesture timing, mouse
release on interruption, live evidence and production integration remain open.
