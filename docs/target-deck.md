# Active target: Wild Rogue

This is the user's sole active deck, replacing the previous Druid target.

```text
AAEBAau2Bwbw5gKh9APj0wTc2gSI2QeF6wcM7QL1uwLn3QP+7gO9gAT3nwS3swT13QTungatpwbBlweD1QcAAA==
```

[Versioned profile](../config/decks/wild-rogue.json): 30 cards, 18 distinct cards, Tess Greymane (`HERO_03bg`). Run `cargo run --offline -- deck` to inspect it. Decoding another code does not change the active target.

Metadata comes from the pinned local HearthstoneJSON snapshot; its date and SHA-256 are in the profile. Static costs do not replace observed costs or transformations.

| Count | Card | Required mechanics |
| --- | --- | --- |
| 2 | Shadowstep | friendly_minion_target, return_to_hand, cost_modifier |
| 2 | Counterfeit Coin | temporary_mana |
| 1 | Kobold Illusionist | deathrattle, hand_minion_copy, summon_modified_stats, placement |
| 2 | Swindle | combo, typed_draw |
| 2 | Shroud of Concealment | typed_draw, conditional_stealth, turn_scoped_effect |
| 1 | SI:7 Extortion | tradeable, undamaged_character_target, spell_damage |
| 2 | Blackwater Cutlass | weapon_equip, tradeable, random_hand_spell_discount |
| 2 | Preparation | next_spell_discount, turn_scoped_effect |
| 2 | Gone Fishin' | dredge, deck_order, combo, draw |
| 1 | Shattershambler | battlecry, next_deathrattle_minion_discount, immediate_death, placement |
| 1 | Double Cross | secret, opponent_mana_trigger, draw |
| 2 | Serrated Bone Spike | minion_damage, death_condition, next_card_discount |
| 2 | Quick Pick | weapon_equip, hero_attack_trigger, draw |
| 2 | Dig for Treasure | typed_draw, pirate_condition, generate_coin |
| 2 | Cultist Map | discover_from_deck, conditional_second_choice, turn_scoped_effect |
| 2 | Nab | minion_damage, death_condition, shuffle_copy, cost_modifier |
| 1 | Shadow of Demise | hand_transformation, last_spell_history |
| 1 | N'Zoth, Dream's End | old_god_unreviewed, deathrattle_summon_history, dynamic_cost, generated_choices |

All cards remain `simulation_supported=false`. Read-only attack previews accept reviewed Kobold Illusionist, Shattershambler and Rogue hero sources with explicit `error=NONE` targets. N'Zoth Old God powers and unknown generated sources are not assumed to be ordinary attacks.

The protocol supports placement, choice-ID-bound selection lists and mulligan selections. Complete legal candidates, Tradeable, Combo, dynamic costs, death and summon history, weapons, Discover/Dredge and Old God transactions still need implementation and real-log validation. Observations remain incomplete and non-actionable.

Next collect and manually review real Rogue windows, then evaluate Laya ranking. Shared visible cards do not establish the full deck. The Druid profile in `config/decks/archive/` is historical only.
