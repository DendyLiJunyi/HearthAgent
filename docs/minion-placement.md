# Offline ordinary-minion placement

Closed historical card-play windows now enumerate insertion positions for
Kobold Illusionist (`LOOT_412`) and Shattershambler (`TID_078`). Both Rogue deck
variants contain these cards. A candidate requires a local observed hand minion,
one unambiguous client POWER option with no targets or sub-options, and fewer
than seven local minions with contiguous known zone positions. Unsupported board
occupants such as locations block this narrow placement interpretation.

For N existing minions, candidates use one-based positions 1 through N+1.
Unfinished live packet tails do not generate these candidates. Card effects,
summoning restrictions and complete legality are not simulated or certified.

```powershell
.venv/Scripts/python.exe scripts/minion_geometry.py fixtures/minion-geometry.json
.venv/Scripts/python.exe scripts/rehearse_attack.py fixtures/minion-geometry.json --mode minion
```

The geometry planner requires a reviewed hand rectangle and
`calibration.minion_drop_boxes`: one normalized rectangle per insertion slot,
ordered left to right. The selected drop center cannot overlap another annotated
entity. The entire calibration remains tied to its frame, window and snapshot.
All gestures are proposed or recorded offline; none send input.

`ui_spell_result.assess_minion` matches the zero-target submission and selected
position, then looks for the same source in play at that position after power
blocks close. Immediate death, transformation or triggered repositioning does
not fabricate success; these cases need richer effect evidence. No result permits
automatic retries or claims execution confirmation. The minion result checker
is a pure function. `wait_for_minion` adds bounded callback-driven observation
using a frozen baseline, session checks and the shared evidence deadline.
It is not connected to a live input adapter.

The synthetic Rust preview test and seven Python geometry/rehearsal/result tests
cover this initial implementation. Generated minions, N'Zoth placement/effects,
locations, automatic drop-region detection and effect simulation remain open.

The retained submission export contains ten nonzero placement submissions, all
using position 1. It lacks source observations and does not validate the full
left-to-right placement convention or every insertion slot. Multi-slot geometry
therefore remains synthetic-test validated, with reviewed calibration required.

## Geometry and result rehearsal

`scripts/rehearse_spell_result.py --mode minion <bundle.json>` now connects the
reviewed placement geometry, durable recording attempt and minion result checker.
The bundle has the same `inputs`, `before` and `after` fields as the spell result
rehearsal. Session, game, revision, supplied board fields and selected placement
must agree before reservation. Blocked and partial baselines are rejected.
Partial simulated gestures skip evidence collection; duplicate receipts refuse
a second attempt. Changed sessions cannot report completion.

The bounded wait deep-copies the baseline, discards late results, and stops on
session or observation failures. Tests exercise delayed block closure, baseline
mutation, wrong placement, session changes and partial gestures. All observations
and gestures in this workflow are supplied or recorded offline; no game input is
sent and no result authorizes retry.

Minion previews still require a historical packet boundary. The live replay tail
does not supply that boundary, so the spell observation CLI cannot acquire a live
minion candidate. This workflow does not remove that unresolved acquisition gate.

`test_minion_parser_integration.py` also runs the actual Rust replay and historical
window exporter on a synthetic two-slot board. It checks insertion at slot two,
open blocks, a different final position and immediate death. The test obtains its
preview from the closed historical window; the same live-tail replay correctly
has no minion candidates. This verifies parser compatibility without claiming a
live candidate source or evidence of card effects.
