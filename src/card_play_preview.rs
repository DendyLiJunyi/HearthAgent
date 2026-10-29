//! Narrow, non-executable hand-card preview. Only pinned targeted spell profiles
//! is interpreted; absent targets never imply an untargeted play.
use crate::board::BoardView;
use crate::preview::{ActionPreview, PreviewCandidate};
use crate::protocol::Action;
use crate::replay::Game;

pub fn from_game(game: &Game) -> ActionPreview {
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
            && matches!(c.card_id, Some("EX1_144" | "REV_939" | "JAIL_225")) && c.card_type == Some("SPELL"));
        let Some(source) = source else {
            *result.omitted.entry("unsupported_hand_card").or_default() += 1;
            continue;
        };
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
