# Rogue real-window input and ordering audit

On 2026-10-28, the cached multilingual Laya model ran offline on 41 development
windows from four Rogue games. The six windows in the held-out game were not
queried. Each position used original and reversed candidate order, twice each:
164 measured predictions per representation, plus one warmup per run.

The user confirmed all five source games used the exact active deck; see
[session provenance](rogue-session-confirmation.json). This confirmation is not
a model feature or a claim that the observations are complete.

| Measurement | Original board | Compact board |
| --- | ---: | ---: |
| Measured trials | 164 | 164 |
| Valid, untruncated responses | 68 | 164 |
| Truncated responses | 96 | 0 |
| Multi-candidate positions valid in every trial | 7 | 20 |
| Those positions selecting the same candidate in every trial | 0 | 1 |

This is an input-integrity and order-sensitivity diagnostic, **not an accuracy
evaluation**. Labels remain unreviewed. Confidence above 0.8 does not establish
correctness, and single-candidate positions cannot demonstrate ranking ability.
Neither representation supports accepting Laya as a gameplay policy yet.

## Lossless compact board

`nullable_card_defaults_v1` stores the schema's unknown card values once in
`card_defaults`. Card objects retain all non-null fields, including false and
zero. Missing nested combat fields also take their declared null defaults.
The request explicitly explains that null means unknown, never false or zero.
Every entity, zone order, player field and known value is preserved.

Python and Rust share [card-defaults.json](../config/model/card-defaults.json).
Schema drift is rejected rather than silently dropped. All 47 frozen source
boards round-tripped exactly: 1,080,475 original JSON bytes became 269,601 encoded
bytes, approximately 75% smaller. The largest encoded board was 12,696 bytes.
All measured compact requests fit the Rust 16 KiB state budget.

The Rust `advise` CLI now uses this encoding. Diagnostic `watch` and `replay`
exports retain the full board format. A loopback integration test compares the
actual Rust HTTP request against the Python encoder and verifies the CLI still
rejects a low-confidence answer. No execution permission follows from encoding.

## Reproduction

```powershell
.venv/Scripts/python.exe services/laya/evaluate_real.py .data/attack-review.jsonl --manifest .data/review-manifest.json --mode diagnostic --representation raw --runs 2 --output .data/laya-real-diagnostic.json
.venv/Scripts/python.exe services/laya/evaluate_real.py .data/attack-review.jsonl --manifest .data/review-manifest.json --mode diagnostic --representation sparse --runs 2 --output .data/laya-real-sparse-diagnostic.json
```

These calls force offline model loading, use the pinned revision, and never send
game input. The inference threshold is zero for ranking diagnostics; a post-hoc
0.8 filter is reported separately and is not the Rust acceptance path. The
diagnostic invokes the model directly even when an original state exceeds the
Rust byte gate; the report separates byte-budget admission from token truncation.

Detailed counts, identities and latency summaries are in
[laya-real-diagnostic.json](laya-real-diagnostic.json). Local trial-level output
remains under `.data/`. Next steps are independently reviewed labels and better
decision quality; raising confidence or dropping difficult windows is not a
substitute for those checks.
