# Choice transaction history

`review-choices` exports every contiguous choice packet and submission group at
its original log boundary. Earlier packets are no longer lost when the replay
retains a later submission.

```powershell
cargo run --offline -- review-choices <Power.log>
.venv/Scripts/python.exe scripts/review_choices.py <Power.log>
```

The Python command uses the binary in `target/validation/debug/` and writes
UTF-8 JSONL to `.data/choice-windows.jsonl` plus a summary report. Build that
binary after code changes. Each window includes game number, packet/submission
kind, parsed header ID, boundary status, redacted board and choice diagnostics.
It excludes raw entity history and display names. Source-card evidence comes
only from the visible prefix board, never later card identities.

The visitor flushes before the following record is applied. Consecutive headers,
reused IDs and new games remain separate. A malformed header has no usable packet
identity; stale or malformed retained packets are excluded from source counts.
An unterminated final line is ignored. EOF windows do not claim an observed
boundary. Even a bounded packet does not prove all candidates were logged.

## Confirmed Rogue session

The October 28 14:28:58 session yielded 76 bounded windows in five games:

- 38 choice packets: 10 mulligan and 28 general.
- 38 submitted lists, all structurally complete.
- 16 packets with local ownership already known at that prefix.
- 11 packets with visible N'Zoth (`BE_017`) source evidence.
- Two Cultist Map (`TLC_515`) packets and one `TLC_515e` source packet.
- Two Gone Fishin' (`TSC_916`) packets.
- 26 submissions correlated with packets already marked stale.

Other packet sources include the opponent's cards. Mulligan source identities
are unknown in the visible projection; the local perspective is not yet known
there. Source counts alone are not an implementation of card effects. Staleness
can follow an intervening state event, so correlation must not be promoted to an
actionable transaction or successful-execution proof.

The full summary is [rogue-choice-window-review.json](rogue-choice-window-review.json).
The user independently confirmed the five games' deck identity in
[session provenance](rogue-session-confirmation.json).

## Restricted local choice projection

`game.choice_preview` now exposes the offered cards for reviewed local GENERAL
choose-one packets from `TLC_515`, `TLC_515e`, `TSC_916`, and `BE_017`. It requires
known local perspective, a current non-stale local packet, an owned source in
PLAY with the expected card type, and owned offered entities in SETASIDE. For
N'Zoth, only the observed minion-choice shape is accepted. Other Old God powers
are not inferred from this behavior.

Every offered card must have observed identity and a supported type; malformed
costs, hidden zones, unknown ownership and unsupported sources suppress the
entire projection. Observed attack, health, damage, armor, durability, payment resource and combat flags now reuse the typed-board parser. Missing values remain unknown; zero and false are preserved. The view
does not enumerate other SETASIDE or deck entities. Submission or state changes
invalidate the packet and hide the prior choices.

The five-game replay produced 16 local choice previews containing 47 offered
card entries. All remain `complete=false`, `actionable=false` and
`legality_verified=false`. These entries are distinct from the 47 attack-review
windows in the separate attack corpus.

## Frozen choice advice

```powershell
cargo run --offline -- advise-choice fixtures/wild-rogue-choice.log
cargo run --offline -- advise-choice <Power.log> http://127.0.0.1:8791
```

Start the local Laya service first. The command considers only the last game in
the frozen file; it does not fall back to an earlier available choice. Candidates
select one offered entity and retain the exact choice ID. The model sees the
compact redacted board plus the restricted choice projection. An incomplete
trailing line or blocked projection prevents querying.

Both `advise` and `advise-choice` now require independently confidence-gated
agreement between original and reversed candidate orders for multi-candidate
advice. A changed semantic selection or either rejected response produces
`no_advice`. A sole candidate receives one query and makes no ranking-quality
claim. Agreement is not proof of correctness or legality. These commands return
advisory types and never send game input.

Remaining work: establish complete choice lists, multi-stage transaction identity
and independent execution confirmation. N'Zoth POWER options remain excluded
from ordinary attack previews.

## Initial choice-model diagnostic (identity and cost only)

The pinned CUDA model evaluated 14 development-game choice windows with original
and reversed candidate order, twice each: 56 measured predictions plus one warmup.
All 56 were valid and untruncated, and all fit the Rust state-byte limit. Nine of
14 positions retained the same semantic selection across all variants. None of
the 56 predictions reached 0.8 confidence. Accuracy is unknown because labels
remain unreviewed. Eight windows belonging to the held-out game (including its
two supported choice packets) were excluded before model input construction.

```powershell
.venv/Scripts/python.exe services/laya/evaluate_choices.py .data/rogue-choice-windows.jsonl --source-report .data/choice-window-review.json
```

The evaluator verifies the source-file hash and reuses the frozen attack-corpus
game split. It never creates a fresh split that could expose held-out games.
See [choice diagnostic report](laya-choice-diagnostic.json). No game input was sent.

## Follow-up with observed choice stats

After adding observed combat stats and payment-resource fields, the same 14
positions were audited again with the same game split, order variants and repeats.
All 56 trials remained valid, untruncated and within the Rust byte budget. Eleven
of 14 positions were order/repeat stable, compared with nine in the initial run.
Two trials reached 0.8 confidence, but no position was confident across all four
variants. These are descriptive results, not evidence of improved accuracy.

The current source report's file hash binds the enriched projection. The initial
report above preserves the earlier input hash. See the [current stats diagnostic](laya-choice-stats-diagnostic.json).
