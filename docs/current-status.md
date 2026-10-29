# Current project checkpoint — 2026-10-29

The sole target is the user's Wild Rogue deck. The user confirmed that all five
games in the October 28 14:28:58 session used that exact list. The project remains
a read-only observation and offline advice system; automatic gameplay is not
implemented.

## Working components

- Pinned local Laya checkpoint, CUDA runtime, Rust HTTP integration and offline audits.
- Streaming and frozen log replay, prefix-bound history, local perspective after a
  validated local mulligan submission (or main-action submission), hidden-zone
  redaction and unknown-valued combat fields.
- Limited attack previews plus reviewed local choose-one previews for Cultist Map,
  its follow-up, Gone Fishin', and N'Zoth minion choices.
- `advise` and `advise-choice`, using compact observations, confidence gating and
  semantic agreement under reversed candidate order. Advisory results cannot be
  passed directly to the execution controller.
- Controller/runner safeguards: refresh before dispatch, deadlines, cancellation,
  duplicate suppression, persistent attempt journal and uncertainty recovery latch.
  The executor still records synthetic actions only.
- Frozen review datasets, separate label sidecars, game-level held-out split and
  validators that exclude labels from model requests.
- Client option submission correlation frozen at the send line, including
  sub-option targets, placement and prior packet diagnostics. This records
  attempts and does not confirm execution.

## Evidence

| Check | Result |
| --- | --- |
| Attack review data | 47 unlabelled windows from five confirmed Rogue games |
| Lossless board round-trip | 47/47 exact; approximately 75% smaller |
| Compact attack diagnostic | 164/164 valid, untruncated trials on 41 development windows |
| Attack order stability | 1/20 multi-candidate positions stable across all variants |
| Choice history | 38 packets and 38 submissions; 16 restricted local previews |
| Choice diagnostic | 56/56 valid trials on 14 development windows; 2 at 0.8 confidence, no position confident across all variants |
| Early local identity | Established at mulligan submission in all five confirmed Rogue games |
| Client submission audit | 142 sends across five Rogue games; all referenced options/targets observed |
| End-turn progression audit | Ordered end-step/next-turn/action-phase evidence after all 21 end-turn sends; causation unverified |
| Rust regression tests | 146 passed |
| Python regression tests | 89 passed |
| Clippy | Passed with warnings denied |

The held-out game was not sent to either real-window GPU diagnostic. Neither
diagnostic reports accuracy: the real samples lack independently reviewed labels.
Formatting verification remains unavailable because rustfmt is not installed.

The Rust HTTP client also rejects duplicate answer and probability keys,
including equivalent JSON-escaped keys. Ambiguous replies cannot produce either
advice or executable decisions. Regression cases cover overwritten confidence
and truncation fields as well; all Rust tests and Clippy pass after this change.

## What prevents automatic gameplay

Laya still shows strong candidate-order sensitivity. No reliable real-game
decision-quality result exists. The log projection and candidate lists remain
incomplete; identity before mulligan submission, Tradeable and many card effects are unresolved.
There is no Windows game-input adapter, complete multi-stage action executor, or
independent execution-result confirmation and recovery implementation.

The next useful steps are reviewed labels, complete candidate/transaction
coverage, stronger and independently evaluated decision quality, and then a
single-step UI adapter with result confirmation. Installation and fast inference
alone do not establish gameplay readiness.

The [first automated match plan](first-automated-match.md) makes the UI route
concrete. The read-only Windows probe and game-window capture both ran successfully
outside the desktop-restricted sandbox after the user opened Hearthstone. The
1920x1080 client area was visually inspected and four control positions were
recorded as a non-actionable calibration draft. A separate [one-shot end-turn
experiment](one-shot-ui-test.md) is implemented; its first live run aborted on
a changed turn before dispatch. Hand/minion entity mapping, production input
integration and successful click confirmation remain unfinished. No game input
has been sent.

Live input testing is deferred at the user's request. Offline post-input checks
now require a matching new submission and observed opponent-turn handoff, with
bounded waiting and refusal of changed sessions, conflicting sends, and late
results. These checks still do not certify causation or authorize a retry.

The one-shot experiment now uses a shared, offline-tested dispatch workflow with
exclusive durable reservations and atomic receipt updates. The synthetic
rehearsal covers full/partial/failed batches without touching the game; duplicate
attempts, preflight changes and failed intent writes cannot dispatch again.

A [read-only attack gesture planner](attack-geometry.md) maps explicit source
and target entity boxes to screen coordinates, bound to a snapshot and captured
frame. Its synthetic tests pass; live entity recognition and gesture execution
are not implemented by this planner.

Calibration preparation now validates the supplied PNG and window dimensions,
exports only public in-play entities, and requires explicit box review before
planning. The [attack block audit](attack-blocks.md) separates 20 completed attack
blocks from 11 non-attack source submissions in the five confirmed Rogue games.
These are historical log observations, not automated execution confirmations.

The offline attack rehearsal now connects geometry planning to the durable
single-attempt workflow using a recording adapter. It rechecks the entire saved
observation before recording, uses four expected events for attacks, and refuses
duplicate attempts or partial batches. It has no live input adapter and provides
no execution confirmation.

Replay/watch now expose a separate [targeted spell card-play preview](card-play-preview.md)
for Shadowstep, Serrated Bone Spike and Nab. It creates targeted `PlayCard`
candidates from the observed local hand and explicit minion targets, with the same
stale-state gates as attack previews. Historical review found supported candidates
in 53 of 143 option windows across all five confirmed Rogue games.
It remains non-executable; other card mechanics and hand-to-screen mapping are
still needed before playing the deck automatically.

## Useful commands

```powershell
cargo run --offline -- deck
cargo run --offline -- watch D:\Hearthstone
cargo run --offline -- review-choices <Power.log>
cargo run --offline -- review-submissions <Power.log>
.venv/Scripts/python.exe services/laya/probe.py --offline --runs 20
.venv/Scripts/python.exe services/laya/smoke_http.py
```

`smoke_http.py` starts its own hidden loopback server, checks the pinned model
and actual device, exercises Rust attack/choice advice, and stops that server.
It does not stop a separately running service or send game input.

For manual frozen advice with a persistent service:

```powershell
.venv/Scripts/python.exe services/laya/run_server.py
# In another terminal, after the service is ready:
cargo run --offline -- advise fixtures/wild-rogue-attacks.log
cargo run --offline -- advise-choice fixtures/wild-rogue-choice.log
```

An end-of-game log usually has no current usable choice or attack window. Advice
does not silently return to an earlier position. `no_advice` is an expected result
when confidence or order consistency fails.

See [attack diagnostic](laya-real-diagnostic.md), [choice review](choice-windows.md),
[submission correlation](option-submissions.md), and [review/label workflow](review-dataset.md)
for reproducible commands and limits.

The [turn progression audit](turn-progression.md) follows end-turn sends through
later log records. It records observed progression, not independent execution
confirmation, and does not release the controller's recovery latch.

The owned offline HTTP smoke passed both Rust commands with the pinned CUDA checkpoint and zero CPU fallback. Both returned `no_advice` through model gating; the temporary server was stopped. See [smoke report](laya-http-smoke.json).
