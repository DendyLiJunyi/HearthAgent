//! Read-only interpretation of client-reported options. It cannot be converted
//! into an executable observation: neither packet completeness nor live UI
//! stability is certified by Power.log.
use std::collections::BTreeMap;
use serde::Serialize;
use crate::board::BoardView;
use crate::protocol::Action;
use crate::replay::Game;

#[derive(Debug, Serialize)]
pub struct PreviewCandidate {
    pub id: String,
    pub option_index: u32,
    pub target_index: Option<u32>,
    pub source_entity: u32,
    pub action: Action,
}

#[derive(Debug, Serialize)]
pub struct ActionPreview {
    pub actionable: bool,
    pub complete: bool,
    pub legality_verified: bool,
    pub perspective: Option<u32>,
    pub option_packet_id: Option<u32>,
    pub observed_power_sequence: Option<u64>,
    pub blocked_by: Vec<&'static str>,
    pub omitted: BTreeMap<&'static str, usize>,
    pub candidates: Vec<PreviewCandidate>,
}

impl ActionPreview {
    pub fn from_game(game: &Game) -> Self {
        let board = BoardView::from_game(game);
        let set = game.options.latest.as_ref();
        let mut result = Self {
            actionable: false, complete: false, legality_verified: false, perspective: board.perspective,
            option_packet_id: set.map(|s| s.id),
            observed_power_sequence: set.map(|s| s.observed_power_sequence),
            blocked_by: Vec::new(), omitted: BTreeMap::new(), candidates: Vec::new(),
        };
        if board.perspective.is_none() { result.blocked_by.push("unknown_perspective"); }
        if game.game_tag("STATE") != Some("RUNNING") || game.game_tag("STEP") != Some("MAIN_ACTION") {
            result.blocked_by.push("not_main_action");
        }
        if board.active_player.is_none() || board.active_player != board.perspective {
            result.blocked_by.push("not_our_turn");
        }
        if game.unresolved_references != 0 || game.malformed_records != 0 || board.invalid_fields != 0 {
            result.blocked_by.push("invalid_observation");
        }
        if !game.structure.closed() { result.blocked_by.push("unclosed_power_structure"); }
        let Some(set) = set else {
            result.blocked_by.push("missing_options");
            return result;
        };
        if set.stale { result.blocked_by.push("stale_options"); }
        if set.malformed_records != 0 || set.unsupported_records != 0 {
            result.blocked_by.push("invalid_options");
        }
        if !result.blocked_by.is_empty() { return result; }
        for option in &set.options {
            if option.error != "NONE" {
                result.omit("client_did_not_report_valid");
                continue;
            }
            if option.kind != "POWER" {
                result.omit("unsupported_option_kind");
                continue;
            }
            if !option.sub_options.is_empty() {
                result.omit("sub_options_require_transaction");
                continue;
            }
            let Some(source) = option.entity_id.and_then(|id| game.entities.get(&id)) else {
                result.omit("unknown_source"); continue;
            };
            if source.tag("CONTROLLER").and_then(|v| v.parse().ok()) != board.perspective {
                result.omit("source_not_ours"); continue;
            }
            let attack = matches!(source.tag("CARDTYPE"), Some("MINION" | "HERO"))
                && source.tag("ZONE") == Some("PLAY");
            // A missing target list can be an unfinished log packet. Never infer
            // an untargeted action from the absence of target rows.
            if option.targets.is_empty() {
                result.omit("no_explicit_targets"); continue;
            }
            if !attack {
                result.omit("unsupported_source_action"); continue;
            }
            let reviewed_source = match source.tag("CARDTYPE") {
                Some("MINION") => source.card_id.as_deref().is_some_and(|id| crate::deck::TARGET_ATTACK_SOURCES.contains(&id)),
                Some("HERO") => source.card_id.as_deref().is_some_and(|id| id.starts_with("HERO_06"))
                    && board.players.iter().any(|p| Some(p.player_id) == board.perspective && p.hero_entity == Some(source.id)),
                _ => false,
            };
            if !reviewed_source {
                result.omit("unreviewed_source_mechanic"); continue;
            }
            if source.tag("ATK").and_then(|v| v.parse::<u32>().ok()).unwrap_or(0) == 0 {
                result.omit("unknown_or_zero_attack"); continue;
            }
            for target in &option.targets {
                if target.error != "NONE" {
                    result.omit("client_rejected_target"); continue;
                }
                let Some(entity) = game.entities.get(&target.entity_id) else {
                    result.omit("unknown_target"); continue;
                };
                let controller = entity.tag("CONTROLLER").and_then(|v| v.parse::<u32>().ok());
                if controller.is_none() || controller == board.perspective
                    || !controller.is_some_and(|p| game.players.contains_key(&p))
                    || entity.tag("ZONE") != Some("PLAY")
                    || !matches!(entity.tag("CARDTYPE"), Some("HERO" | "MINION")) {
                    result.omit("unsupported_target"); continue;
                }
                // Index provenance is scoped to the enclosing game snapshot.
                result.candidates.push(PreviewCandidate {
                    id: format!("p{}-s{}-o{}-t{}", set.id, set.observed_power_sequence, option.index, target.index),
                    option_index: option.index, target_index: Some(target.index), source_entity: source.id,
                    action: Action::Attack { source: source.id, target: target.entity_id },
                });
            }
        }
        result
    }

    fn omit(&mut self, reason: &'static str) {
        *self.omitted.entry(reason).or_default() += 1;
    }
}
