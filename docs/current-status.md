# Current project status — 2026-11-04

**Latest:** [fast play](fast-play.md) makes a log-based animation check the default, keeps playing after failed moves and adds Pirate Warrior tactics. Tested offline only; no live game has run on it.

## Update — 2026-11-04

This is the current summary. [Agent documentation](agent.md) contains commands and historical
experiments; dated results there are not new validation of subsequent changes.

- Python supports option-based play, mulligan, choices, Windows input, focus pause and menu
  traversal. Pirate Warrior is the active deck; the menu defaults to Ranked Wild.
- A complete Ranked Wild cycle was previously recorded; it lost. Other recorded practice results
  are small samples, not a reliable estimate of playing strength.
- The latest changes verify placement and selected choice entities, independently monitor hand
  stability, stop on mulligan recognition timeout, detect log replacement and attribute decisions
  to the model or rules. These changes have offline regression coverage only.
- Broad strategy heuristics are now soft preferences. Model weights remain unchanged; stronger
  play has not been established. Evaluation separates raw-model, rules-only and deployed-policy
  agreement. Existing held-out games are validation; independent reviewed Warrior data is needed.
- No game input was sent while implementing this improvement batch.

See [implementation and validation details](reliability-improvements.md), including remaining
limits of animation detection and submission confirmation.
