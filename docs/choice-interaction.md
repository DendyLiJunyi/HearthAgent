# Offline choose-one interaction

`scripts/choice_geometry.py` maps one selected offer from a local reviewed choice
preview to a three-event click plan. It requires the Choosing phase, exact
session/game/revision, frame hash, window and choice packet ID. Every offered
entity needs a reviewed rectangle; missing offers, duplicate identities and
overlapping click points are refused. Multi-select choices and mulligans are
not supported by this planner.

```powershell
.venv/Scripts/python.exe scripts/rehearse_attack.py fixtures/choice-geometry.json --mode choice
```

This synthetic rehearsal uses a recording adapter only. Its event count is
three for a choice click, while attack/card drags remain four. The durable
attempt workflow rechecks the complete input envelope before recording.

`scripts/ui_choice_result.py` checks a later complete choice submission against
the original local offer. It refuses an already-submitted baseline, different
packet/selection, stale packet context and owner mismatch. A matching submitted
list is evidence only: it does not certify the chosen card was added to hand,
the effect resolved or a mouse click caused the event. Session/file checks remain
the caller's responsibility; automatic retries are never authorized.

Three geometry tests and four result tests cover these boundaries, including
actual Rust replay of a synthetic choice header followed by its submitted list.
The geometry and result checker are currently separate offline components;
automatic offer-box detection and live choice interaction remain unfinished.
