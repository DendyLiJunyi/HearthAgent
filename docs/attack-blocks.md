# Historical attack block audit

```powershell
.venv/Scripts/python.exe scripts/audit_attacks.py D:\Hearthstone\Logs\Hearthstone_2026_10_28_14_28_58\Power.log --output docs/rogue-attack-block-review.json
```

The five user-confirmed Rogue games contain 31 targeted main-option POWER
submissions. The audit identifies 20 matching, fully closed ATTACK blocks and
11 submissions whose observed source was a non-attack card/action. There were
zero block-structure errors. See [the report](rogue-attack-block-review.json).

The tool freezes the log bytes before exporting Rust submission records and
records SHA-256 hashes of both inputs. Source type and zone come from the public
board projection at the submission boundary, before later card movement or
reveals. Hidden identities remain redacted. Missing source information stays
unknown; it is not automatically classified as a card play.

Attack evidence requires a fresh supported option/target correlation, the same
source and target in a later authoritative ATTACK header, and closure of that
specific block after any nested blocks. Animation records and incomplete final
lines cannot complete it. Changed targets, malformed boundaries, another send
or a new game terminate the attempt without future repair.

Seven Python tests cover these boundaries and source classification. Three Rust
tests cover source visibility and prefix-only export. Historical block closure
does not prove mouse-input causation, damage, victory, or successful autonomous
play; every report remains non-actionable and execution-unconfirmed.
