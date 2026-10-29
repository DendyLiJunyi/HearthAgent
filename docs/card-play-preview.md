# Targeted spell card-play preview

## Untargeted spell extension

Historical `review-card-plays` windows now also support Counterfeit Coin
(`CFM_630`), Preparation (`CORE_EX1_145`) and generated The Coin (`GAME_005`).
These produce `PlayCard` with null target and position only when a packet boundary
was observed, the client reports `NONE`, no targets/sub-options exist, and the
source has exactly one option entry. This interprets card-play shape; it does not
simulate temporary mana, discounts or certify legality.

Live replay/watch previews still omit these untargeted candidates because an
idle log tail cannot certify that the packet ended. The spell geometry planner
now accepts these profiles with a reviewed `calibration.spell_drop_box` rectangle,
and the result checker expects a zero-target submission followed by the source
in the graveyard. Neither validates mana gain or discounts, and neither sends
input. Three Python tests cover drop-region requirements and zero-target evidence.
Two additional
Rust tests cover all three profiles, alternate branches, contradictory targets,
and real visitor behavior at EOF versus an observed boundary.

The prior five-game source log was absent at its recorded path during this
extension. The existing historical coverage report is retained unchanged and
does not include these new candidates; new coverage is synthetic-test validated.

Ordinary minion candidates, drop geometry and result checks are documented in
[minion placement](minion-placement.md).

Replay and watch JSON now include `game.card_play_preview`, separate from the
existing attack preview. It interprets three spells from the pinned Rogue deck
as `PlayCard { source, target, position: null }` when the local hand contains that
observed spell and the current client option explicitly lists a permitted
in-play minion with `error=NONE`:

- Shadowstep (`EX1_144`): friendly minions only.
- Serrated Bone Spike (`REV_939`): friendly or enemy minions.
- Nab (`JAIL_225`): friendly or enemy minions.

The preview preserves option packet, source sequence, option index and target
index. It shares the attack preview's turn, perspective, parsing, closed power
structure and fresh-packet checks. Missing target rows, rejected options,
sub-options, unknown cards and nonlocal/hidden sources produce no candidate.
It uses the redacted board projection rather than cached hidden card identities.

This is a narrow action interpretation, not a simulator or a full legal move
generator. Costs and Shadowstep's resulting hand/cost changes are not simulated.
`actionable`, `complete` and `legality_verified` remain false. The existing Laya
attack advice input is unchanged; card-play advice and mouse execution are not
connected. Other spells, minion placement and generated cards remain unsupported.

Four Rust regression tests cover the supported actions/export and rejection cases.
Run them with:

```powershell
cargo test --offline --target-dir target/validation --test card_play_preview
```

## Historical validation

`review-card-plays <Power.log>` emits prefix-frozen option windows with the
redacted board. Existing attack review output stays separate. To regenerate the
summary from a frozen copy of the five confirmed Rogue games:

```powershell
.venv/Scripts/python.exe scripts/review_card_plays.py D:\Hearthstone\Logs\Hearthstone_2026_10_28_14_28_58\Power.log --output docs/rogue-card-play-review.json
```

The [report](rogue-card-play-review.json) finds supported plays in 53 of 143
option windows across all five games: 126 Shadowstep, 84 Serrated Bone Spike and
148 Nab candidate occurrences. These counts include repeated opportunities and
multiple targets; they are neither actual plays nor strategic accuracy scores.
Unclosed windows and blocked observations are excluded from candidate counts.
The report binds both the frozen input and export with SHA-256 hashes. Two Python
tests verify summary exclusions and refusal of executable claims.

## Spell result evidence

The pure checker in scripts/ui_spell_result.py compares before/after replay
observations for a selected supported spell candidate. It requires exactly one
new submission with matching packet, option, source and target, followed by the
same spell entity in the local graveyard with closed power structure. Partial
logs, conflicting submissions and changed source identities cannot complete it.

This is log evidence only: execution_confirmed and automatic_retry_allowed stay
false. It does not certify damage, discounts, returned minions or input causation.
Session/file identity must be checked by a future polling adapter. The checker
is not yet wired to live input. Four tests cover matching and refusal cases.

## Restored spell geometry workflow

The spell planner, calibration preparation and recording-only rehearsal are now
restored and tested together. Prepare a draft from saved watch/probe/PNG inputs:

```powershell
.venv/Scripts/python.exe scripts/prepare_attack_calibration.py --mode spell --snapshot .data/saved-watch-row.json --probe .data/game-window-probe.json --frame .data/game-window.png --candidate <candidate-id> --output .data/spell-calibration-draft.json
```

Only the local hand and public board are included. Every rectangle starts null;
visually annotate clickable regions and mark the draft reviewed before planning.
This does not certify frame/log capture timing or account for hand hover animation.

The synthetic fixture can be run without a game:

```powershell
.venv/Scripts/python.exe scripts/spell_geometry.py fixtures/spell-geometry.json
.venv/Scripts/python.exe scripts/rehearse_attack.py fixtures/spell-geometry.json --mode spell
```

The proposed gesture is move/down/move/up. It remains non-actionable and has not
been validated against real mouse behavior. Rehearsal dispatch/event counts are
simulated; game_input_sent stays false. Four integrated tests cover preparation,
private-hand exclusion, target restrictions, duplicate attempts, overlapping
boxes, stale frames and changed hands before recording. Live input is not connected.

## Combined offline result rehearsal

`scripts/rehearse_spell_result.py` accepts a JSON bundle with `inputs` (the reviewed
geometry envelope), `before`, and `after` observations. The baseline must include
the geometry's exact session_id, game_number and revision. Supplied geometry
board fields, entity sets and selected action must match that baseline before
an attempt receipt can be created.

```powershell
.venv/Scripts/python.exe scripts/rehearse_spell_result.py .data/spell-result-bundle.json
```

After a complete simulated gesture, the receipt includes the spell result
checker's evidence. Partial insertion skips evidence collection; changed sessions
cannot report completion. All later observations are supplied offline data, not
proof that the recording caused a game event. Three integration tests cover this
connection, mismatched baselines and partial/session-change cases. No actual
mouse adapter or automatic polling is enabled by this command.

## Bounded evidence observation

`ui_spell_result.wait_for_spell` now supports an injected observation callback,
with an eight-second default deadline (maximum 30 seconds). Each callback receives
the remaining time budget and must honor it. Results arriving at or beyond the
deadline are discarded. Session changes, malformed observations and observer
errors stop the wait; none authorize retry or certify execution.

The starting observation is deep-copied before polling. Four fake-clock tests
cover pending-to-complete progression, baseline mutation, late results, timeout,
session/schema/read failures and invalid deadlines. This shares the bounded wait
implementation with end-turn checks, whose regression tests also pass. A live
log reader with file identity/truncation checks is still required; this change
does not connect polling to mouse input or certify that spell effects resolved.

## Read-only log adapter

`scripts/observe_spell.py` now supplies that reader. It captures a bounded log
prefix, verifies all previously observed bytes remain unchanged, replays a
temporary frozen copy with the Rust binary, and rechecks the source identity and
prefix afterward. Truncation, replacement, same-length rewrites, newer sessions,
invalid output and late observations are refused. A failure requires a fresh
observer/baseline; restoring old bytes does not silently resume the observer.

```powershell
.venv/Scripts/python.exe scripts/observe_spell.py <Power.log> --candidate <current-candidate-id> --timeout 8
```

This command only observes a manually performed action after acquiring its
baseline. It sends no input and does not connect the mouse adapter. Baseline
acquisition has its own budget up to five seconds, followed by the requested
evidence deadline. Logs over 64 MiB are refused. Five tests cover append-only
reading, mutation and session failure cases, late replay, and the real Rust
binary with a synthetic log. File changes entirely between observations that
restore identical bytes cannot be detected; these checks do not certify causation.

## Real-parser observation smoke test

```powershell
.venv/Scripts/python.exe scripts/smoke_spell_observer.py
```

This builds a synthetic Shadowstep log in a temporary directory, acquires its
baseline through the actual Rust binary, appends a submission and zone change,
and runs the bounded observer. The three checked outcomes are matching spell
evidence, a rejected wrong target, and timeout while a power block remains open.
Only the polling clock is simulated; all log reads and replay subprocesses are
real. The command never touches the installed game's log or sends input. It is
also included in Python regression discovery when the Rust binary is available.
