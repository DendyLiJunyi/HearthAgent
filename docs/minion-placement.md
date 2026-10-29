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
is a pure function and is not yet connected to a live polling/input adapter.

The synthetic Rust preview test and seven Python geometry/rehearsal/result tests
cover this initial implementation. Generated minions, N'Zoth placement/effects,
locations, automatic drop-region detection and effect simulation remain open.

The retained submission export contains ten nonzero placement submissions, all
using position 1. It lacks source observations and does not validate the full
left-to-right placement convention or every insertion slot. Multi-slot geometry
therefore remains synthetic-test validated, with reviewed calibration required.
