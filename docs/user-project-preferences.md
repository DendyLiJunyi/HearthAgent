# User instructions and deck variants

Updated 2026-10-29 from explicit user instructions.

- Continue through successive useful offline tasks without asking the user to
  say continue after every small change. Report checkpoints without claiming the
  remaining automation work is complete.
- Continue development and validation offline. Do not send further game input
  unless the user explicitly resumes live testing. The earlier one-action
  practice authorization was used for the end-turn test and is complete.
- Retain the original Rogue deck in `config/decks/wild-rogue.json`.
- Also recognize the supplied 恩佐斯贼 modification in
  `config/decks/wild-rogue-nzoth-2026-10-29.json`; it is a supported metadata
  variant, not a claim of complete gameplay implementation.
- The five confirmed October 28 games remain associated with the original deck.
  Do not relabel them as the new variant or infer a full deck from a partial hand.

New variant code:

```
AAEBAau2Bwrf4wLw5gL/7gOh9APj0wTIlAbBlweD1QeI2QeF6wcK7QL1uwLn3QP+7gO9gAT3nwS3swT13QTungatpwYAAA==
```

Changes: add one Evasion, one Savory Deviate Delight and one Stick Up; remove
Double Cross; reduce Cultist Map and Nab to one copy each. Both decks have 30
cards. The new list has 20 unique cards; the original has 18.

Shared attack and targeted-spell previews remain applicable where their exact
observed card IDs and state checks pass. Stick Up now has a read-only local choice
projection under the existing visibility checks, synthetically tested with
observed offers. It does not reconstruct the offer pool or Quickdraw effects.
New secrets and random hand transformations remain unimplemented.
End-turn button detection does not establish reliable targeting, animated hand
mapping, effect simulation or Laya decision quality.
