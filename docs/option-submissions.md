# Client action submission correlation

`game.logged_options.latest_submission` records the latest complete
`GameState.SendOption` line and its relationship to the most recent option packet
at that instant. `submissions_seen` and `malformed_submissions` count client send
lines separately from option-packet diagnostics. Malformed sends clear the latest
submission instead of leaving an older successful parse in its place.

The selection preserves option index, sub-option index, target entity ID, and
placement. Correlation records the prior packet ID, stale status, diagnostics,
source entity, main/sub-option error codes, and whether the target appeared in
the selected branch. A target belonging only to the main option does not satisfy
a sub-option selection. Duplicate target entities are marked ambiguous and no
single error code is chosen for them.

Target zero means no target was supplied, so target correlation is null. An
unresolved parent also produces null; a resolved parent with no matching target
produces false. Neither value proves legality or illegality because candidate
coverage remains incomplete. Placement is retained but not validated.

Correlation is frozen before the send marks the packet stale. Later packets,
including reused IDs, cannot repair or overwrite it. New games clear it. The
shared strict send parser is also used by main-action perspective inference.
No names or raw record strings are added to the exported correlation.

`candidate_list_complete`, `legality_verified`, and `execution_confirmed` are
always false. A client send is an attempt, not an acknowledgement. This work
provides evidence for a future result-confirmation layer; it does not implement
that layer or send any game input.

## Reproduce the audit

```powershell
cargo build --offline --target-dir target/validation
target/validation/debug/hearth-agent.exe review-submissions <Power.log>
.venv/Scripts/python.exe scripts/review_submissions.py <Power.log>
```

The Rust command emits one JSONL row immediately after each complete client send
line, with no future records. It freezes the input file length at open and ignores
a trailing partial line. The Python script summarizes these rows and hashes the
saved JSONL. It refuses diagnostic rows claiming execution or legality.

For the five confirmed Rogue games, all 142 client sends parsed and referenced
observed options in non-stale packets: 121 POWER and 21 END_TURN. All 55 nonzero
targets and all 41 sub-option selections were found in their respective branches;
10 sends supplied nonzero placement. There were no malformed packets, missing
parents, or ambiguous target matches in this audit.

All 21 END_TURN records carried the observed main-option error `INVALID`; it is
retained as an unresolved log-semantic detail, not converted to legal or illegal.
See [audit report](rogue-submission-review.json). The report does not evaluate
player decision quality, Laya accuracy, or successful game execution.

The subsequent [turn progression audit](turn-progression.md) found the ordered
end-step/next-turn/action-phase sequence after all 21 end-turn sends. This does
not establish what caused progression or change the recorded INVALID value.

Six Rust regression tests cover main/sub-target separation, unknown parents,
frozen correlation, stale/malformed/ambiguous evidence, strict send syntax, game
reset, partial lines, and live/offline prefix equivalence. Three Python tests
cover summary semantics and refusal of unsupported success claims.
