# Position-based screen mapping

`scripts/map_visual_slots.py` assigns game entity IDs to visual slots using the
observed `ZONE_POSITION` projection. It removes the need to identify each card's
artwork or manually attach entity IDs to boxes. A detector or reviewer must still
supply clickable regions for the exact captured frame.

```powershell
.venv/Scripts/python.exe scripts/map_visual_slots.py .data/spell-calibration-draft.json .data/visual-slots.json --output .data/mapped-spell-draft.json
```

Visual input contains `frame_sha256`, the exact `window`, `stable: true`,
`occluded: false`, and `groups`. Groups must explicitly contain `local_hand`,
`local_minions`, `opponent_minions`, `local_hero`, and `opponent_hero`; each is a
left-to-right list of normalized `[left, top, right, bottom]` rectangles.
Empty zones must be empty lists. Stability/occlusion flags are supplied evidence,
not a detector implemented by this module.

Hand and minion positions must be unique, contiguous and match visual counts.
Overlapping click centers, missing positions, changed frame/window identity and
unmatched entities are refused. Input array order never substitutes for observed
positions. Results remain `annotation_status: unreviewed`; the tool sends no input
and does not authorize execution.

Three regression tests cover entity assignment, log ordering, count and position
mismatches, changed frames and unstable/occluded scenes. Automatic visual region
detection and validation across board layouts are still unfinished. The one saved
real screenshot shows a fanned hand and animation and is insufficient to validate
that detector. Live testing remains deferred unless the user resumes it.
