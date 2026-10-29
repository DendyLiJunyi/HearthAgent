//! Narrow, non-executable hand-card preview. Known untargeted profiles additionally
//! require an observed historical packet boundary; absence alone is insufficient.
use crate::board::BoardView;
use crate::preview::{ActionPreview, PreviewCandidate};
use crate::protocol::Action;
use crate::replay::Game;

pub fn from_game(game: &Game) -> ActionPreview {
    from_window(game, false)
}

/// A boundary permits interpreting known untargeted profiles, not claiming a
/// complete legal move set. Never supply true for an idle/unfinished live tail.
pub fn from_window(game: &Game, boundary_observed: bool) -> ActionPreview {
    // Share the attack preview's observation/packet gates. Its candidate and
    // omission lists are independent from this card-play interpretation.
    let mut result = ActionPreview::from_game(game);
    result.candidates.clear();
    result.omitted.clear();
    if !result.blocked_by.is_empty() { return result; }
    let board = BoardView::from_game(game);
    let Some(local) = board.players.iter().find(|p| Some(p.player_id) == board.perspective) else {
        result.blocked_by.push("unknown_local_player");
        return result;
    };
    let Some(set) = game.options.latest.as_ref() else { return result; };
    for option in &set.options {
        let reason = if option.kind != "POWER" || option.error != "NONE" {
            Some("unsupported_or_rejected_option")
        } else if !option.sub_options.is_empty() {
            Some("sub_options_require_transaction")
        } else { None };
        if let Some(reason) = reason {
            *result.omitted.entry(reason).or_default() += 1;
            continue;
        }
        let source = local.hand.iter().find(|c| Some(c.entity_id) == option.entity_id
            && ((matches!(c.card_id, Some("EX1_144" | "REV_939" | "JAIL_225" | "CFM_630" | "CORE_EX1_145" | "GAME_005"))
                && c.card_type == Some("SPELL"))
                || (matches!(c.card_id, Some("LOOT_412" | "TID_078")) && c.card_type == Some("MINION"))));
        let Some(source) = source else {
            *result.omitted.entry("unsupported_hand_card").or_default() += 1;
            continue;
        };
        if source.card_type == Some("MINION") {
            let mut positions: Vec<u32> = local.in_play.iter().filter(|c| c.card_type == Some("MINION"))
                .filter_map(|c| c.position).collect();
            positions.sort_unstable();
            let count = local.in_play.iter().filter(|c| c.card_type == Some("MINION")).count();
            let known_slots = count < 7 && positions == (1..=count as u32).collect::<Vec<_>>()
                && local.in_play.iter().all(|c| matches!(c.card_type, Some("MINION" | "HERO" | "HERO_POWER" | "WEAPON")));
            if !boundary_observed || !option.targets.is_empty() || !known_slots
                || set.options.iter().filter(|o| o.entity_id == Some(source.entity_id)).count() != 1 {
                *result.omitted.entry("unresolved_minion_placement").or_default() += 1;
                continue;
            }
            for position in 1..=count as u32 + 1 {
                result.candidates.push(PreviewCandidate {
                    id: format!("play-p{}-s{}-o{}-slot{}", set.id, set.observed_power_sequence, option.index, position),
                    option_index: option.index, target_index: None, source_entity: source.entity_id,
                    action: Action::PlayCard { source: source.entity_id, target: None, position: Some(position) },
                });
            }
            continue;
        }
        if matches!(source.card_id, Some("CFM_630" | "CORE_EX1_145" | "GAME_005")) {
            if !boundary_observed {
                *result.omitted.entry("untargeted_requires_packet_boundary").or_default() += 1;
            } else if !option.targets.is_empty() {
                *result.omitted.entry("unexpected_targets_for_untargeted_spell").or_default() += 1;
            } else if set.options.iter().filter(|o| o.entity_id == Some(source.entity_id)).count() != 1 {
                *result.omitted.entry("ambiguous_source_options").or_default() += 1;
            } else {
                result.candidates.push(PreviewCandidate {
                    id: format!("play-p{}-s{}-o{}-untargeted", set.id, set.observed_power_sequence, option.index),
                    option_index: option.index, target_index: None, source_entity: source.entity_id,
                    action: Action::PlayCard { source: source.entity_id, target: None, position: None },
                });
            }
            continue;
        }
        if option.targets.is_empty() {
            *result.omitted.entry("no_explicit_targets").or_default() += 1;
        }
        for target in &option.targets {
            let friendly_only = source.card_id == Some("EX1_144");
            if target.error != "NONE" || !board.players.iter()
                .filter(|p| !friendly_only || p.player_id == local.player_id)
                .flat_map(|p| &p.in_play).any(|c|
                    c.entity_id == target.entity_id && c.public_zone && c.card_type == Some("MINION")) {
                *result.omitted.entry("unsupported_or_rejected_target").or_default() += 1;
                continue;
            }
            result.candidates.push(PreviewCandidate {
                id: format!("play-p{}-s{}-o{}-t{}", set.id, set.observed_power_sequence, option.index, target.index),
                option_index: option.index, target_index: Some(target.index), source_entity: source.entity_id,
                action: Action::PlayCard { source: source.entity_id, target: Some(target.entity_id), position: None },
            });
        }
    }
    result
}
