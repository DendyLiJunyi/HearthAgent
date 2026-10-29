# Targeted spell card-play preview

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
