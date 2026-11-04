# Integrated offline controller

The controller connects supplied observations, a policy, refreshed observations,
geometry planning, durable recording and result checks across successive steps.
It supports attack, spell, reviewed minion, choose-one and end-turn adapters. It stops on policy
abstention, changed state, old revisions, changed game/session, unresolved evidence,
adapter errors, time budget or step limit. A run directory cannot be reused after
completion or interruption; this prevents accidental resumption of uncertain work.

```powershell
# Uses an already-running local Laya service; records no actual mouse input.
.venv/Scripts/python.exe scripts/run_offline_sequence.py fixtures/offline-sequence.json --output .data/sequence-run-001

# Starts its own offline GPU service, runs integration checks, then stops it.
.venv/Scripts/python.exe services/laya/smoke_http.py --sequence fixtures/offline-sequence.json
```

The fixture is synthetic and contains one spell action with supplied before/after
observations. It is not a simulator, actual match, independent strategy label or
proof that the model understands the deck. Multi-step tests also use supplied
transitions; consuming a sequence does not imply that its transitions are legal
or that a complete match has been played.

`LayaAdvicePolicy` calls the Rust `advise-observation` command, preserving its
confidence threshold and reversed-order agreement check. Missing/uncertain advice
stops the run without a fallback. Saved observations are always treated as
incomplete advisory state. Input is bounded to 1 MiB; the original Rust loopback
endpoint restrictions and response validation apply. Actual actions are recorded
only; there is no Windows input adapter in this controller.

October 30 GPU smoke result: the one-step sequence reached
`supplied_sequence_complete`; the ordinary attack and choice advice fixtures
abstained. The owned server stopped and no game input was sent. This verifies
transport and orchestration, not model quality. See
[integration smoke summary](offline-controller-smoke.json).

## Remaining work before unattended gameplay

- Automatically detect trustworthy screen regions across hand sizes, animations,
  choices and overlays; current geometry needs reviewed annotations.
- Establish live candidate completeness and interaction boundaries. Historical
  packet closure cannot be treated as current live legality.
- Complete action coverage: hero power, weapons, Tradeable, secrets, generated
  cards, mulligan, complex choices and deck-specific effects.
- Attacks and end-turn now have result checks in the recording-only controller.
  Production input needs drag timing and mouse
  release handling across interrupted gestures.
- Validate Laya decisions on independent labels and complete match sequences.
  Confidence alone does not establish good play.
- Validate real gameplay after the user resumes live testing. Offline replay
  cannot prove UI behavior or turn/match completion.

The offline controller deliberately does not release the Rust live controller's
recovery latch based on correlated historical evidence. Automatic continuation
here means consuming the next supplied offline frame, not permission for another
live input after an uncertain result.

## End-turn integration

An `end_turn` frame uses the protocol action `"EndTurn"` and a reviewed normalized
`calibration.end_turn_box`. The controller binds the full baseline board and
snapshot identity, verifies a stable local main-action state and end-turn option,
then records three mouse events. It requires a matching new submission and turn
handoff in the supplied later observation before consuming another frame.

Three additional tests cover spell-to-end-turn sequencing, unresolved handoff and
stale/invalid button calibration. These supplied frames do not simulate mana or
other game effects and do not prove the actions form a legal real turn. The
separate one-shot live adapter has not been invoked by this integration work.

## Attack integration

An `attack` frame supplies the usual reviewed geometry, before/after observations,
and `attack_evidence` containing `before_log`, `after_log`, `before_submissions`
and `after_submissions`. Logs are newline-terminated UTF-8 strings; submission
arrays use the Rust `review-submissions` export schema. The later prefix must
extend the earlier prefix with exactly one additional exported submission.

The checker runs the existing attack-block audit over both prefixes and binds
the new send to the snapshot's game, submission count, latest submission, prior
option packet, and selected source/target. Only `matching_attack_block_closed`
advances the controller. Missing closure, a different target, malformed block
structure or mismatched evidence stops progression. The baseline board and
snapshot identity must match the geometry observation.

Generate snapshots and submission exports together from saved prefixes with:

```powershell
.venv/Scripts/python.exe scripts/prepare_attack_evidence.py saved-before.log saved-after.log --output .data/attack-evidence-001.json
```

This helper freezes both prefixes, invokes Rust replay and submission review on
the same bytes, and records their SHA-256 hashes. It rejects partial lines,
rewritten prefixes and game changes, uses one shared parser deadline, and refuses
to overwrite an existing output. Its output is an evidence bundle, not a complete
controller frame: reviewed screen geometry and observation identity are still
required. A real-parser integration test covers completed and unfinished attacks.

Supplied exports and snapshots are not authenticated or independently
replayed by the controller adapter. Its checks establish internal evidence consistency,
not trusted acquisition, damage outcomes or input causation. Tests use synthetic
logs and recording only; no game input was sent. The script suite now passes
134 tests, including attack completion, parser integration and evidence rejection cases.
