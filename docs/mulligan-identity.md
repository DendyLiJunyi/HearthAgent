# Local identity at mulligan submission

Replay and live observation can identify the local player when the client logs
`GameState.SendChoices` for a mulligan. The inference uses only choice records
preceding that send header and entity state reduced up to that point.

The packet must be a uniquely identified mulligan from GameEntity, with minimum
zero and 3–5 observed entries matching its maximum. Every offered entity must be
in HAND and belong to the same known player; that player's mulligan state must be
INPUT. The game must be RUNNING at BEGIN_MULLIGAN, with two players and no malformed
or unresolved state records. Known packet ownership must agree. Server-side
EntitiesChosen records alone do not establish local identity.

The exported `perspective_source` records `local_mulligan_submission`. The first
valid evidence source is preserved when a later main-action submission agrees.
Conflicting local submissions hide both players' private hands until a new game.
Completeness and actionability remain false.

This identifies the player **after submitting the opening selection**. It does
not enable advice before that selection, nor certify the packet's legality or
successful execution. Packet bounds here are an inference constraint, not a
general claim that logged candidate lists are complete.

Three regression tests cover valid identity/redaction, rejected ambiguous or
incomplete evidence, and byte-by-byte live/replay agreement with conflict and
new-game reset. The five confirmed Rogue games were separately replayed with
each prefix ending immediately after its local mulligan send header: all five
established identity. See [prefix audit](mulligan-identity-review.json).

Previously frozen model-review datasets and their hashes are unchanged. New
exports may contain earlier local-hand visibility and different provenance;
they must be versioned separately from those frozen datasets.
