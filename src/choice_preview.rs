//! Contextual, read-only projection of reviewed local face-up choice mechanisms.
//! Does not expose opponent choices, ordinary deck contents or all SETASIDE entities.
use crate::replay::Game;
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct OfferedCard {
    pub entity_id: u32,
    pub card_id: String,
    pub card_type: String,
    pub observed_cost: Option<u32>,
    pub observed_cost_resource: Option<&'static str>,
    pub observed_attack: Option<u32>,
    pub observed_health: Option<u32>,
    pub observed_damage: Option<u32>,
    pub observed_armor: Option<u32>,
    pub observed_durability: Option<u32>,
    pub combat: crate::board::CombatView,
}

#[derive(Debug, Serialize)]
pub struct LocalChoice {
    pub choice_id: u32,
    pub source_entity: u32,
    pub source_card_id: String,
    pub minimum: u32,
    pub maximum: u32,
    pub offered_cards: Vec<OfferedCard>,
}

#[derive(Debug, Serialize)]
pub struct ChoicePreview {
    pub actionable: bool,
    pub complete: bool,
    pub legality_verified: bool,
    pub blocked_by: Vec<&'static str>,
    pub choice: Option<LocalChoice>,
}

impl ChoicePreview {
    pub fn from_game(game: &Game) -> Self {
        match project(game) {
            Ok(choice) => Self { actionable: false, complete: false, legality_verified: false,
                blocked_by: Vec::new(), choice: Some(choice) },
            Err(reason) => Self { actionable: false, complete: false, legality_verified: false,
                blocked_by: vec![reason], choice: None },
        }
    }
}

fn project(game: &Game) -> Result<LocalChoice, &'static str> {
    let local = game.perspective.player_id().ok_or("unknown_perspective")?;
    if game.game_tag("STATE") != Some("RUNNING") { return Err("game_not_running"); }
    if game.unresolved_references != 0 || game.malformed_records != 0
        || game.choices.malformed_records != 0 || game.choices.unsupported_records != 0 {
        return Err("invalid_observation_or_choices");
    }
    let owner = game.players.get(&local).ok_or("unknown_local_entity")?;
    let mut sets = game.choices.sets.values().filter(|s| s.owner_entity == Some(*owner) && !s.stale);
    let set = sets.next().ok_or("no_current_local_choice")?;
    if sets.next().is_some() { return Err("ambiguous_local_choices"); }
    if set.kind != "GENERAL" || set.minimum != 1 || set.maximum != 1 || set.malformed_records != 0 {
        return Err("unsupported_choice_shape");
    }
    let source = set.source_entity.and_then(|id| game.entities.get(&id)).ok_or("unknown_choice_source")?;
    if source.tag("ZONE") != Some("PLAY")
        || source.tag("CONTROLLER").and_then(|v| v.parse::<u32>().ok()) != Some(local) {
        return Err("source_not_local_in_play");
    }
    let source_id = source.card_id.as_deref().ok_or("unknown_source_card")?;
    let reviewed = matches!((source_id, source.tag("CARDTYPE")),
        ("TLC_515" | "TSC_916" | "WW_411", Some("SPELL")) | ("TLC_515e", Some("ENCHANTMENT"))
        | ("BE_017", Some("MINION")));
    if !reviewed { return Err("unreviewed_choice_mechanic"); }
    if set.entities.is_empty() || set.entities.len() > 16 { return Err("unsupported_choice_count"); }
    let mut cards = Vec::new();
    for id in &set.entities {
        if *id == 0 { return Err("invalid_offered_entity"); }
        let entity = game.entities.get(id).ok_or("unknown_offered_entity")?;
        if entity.tag("ZONE") != Some("SETASIDE")
            || entity.tag("CONTROLLER").and_then(|v| v.parse::<u32>().ok()) != Some(local) {
            return Err("offered_entity_not_local_setaside");
        }
        let card_id = entity.card_id.as_deref().filter(|s| !s.is_empty()).ok_or("unknown_offered_card")?;
        let kind = entity.tag("CARDTYPE").filter(|kind|
            matches!(*kind, "MINION" | "SPELL" | "WEAPON" | "HERO" | "LOCATION"))
            .ok_or("unsupported_offered_card_type")?;
        if source_id == "BE_017" && kind != "MINION" { return Err("unreviewed_old_god_choice"); }
        // Reuse the board's numeric/resource/unknown semantics only after the
        // contextual visibility checks above; never expose arbitrary SETASIDE cards.
        let mut invalid = 0;
        let observed = crate::board::card(entity, false, true, &mut invalid);
        if invalid != 0 { return Err("invalid_offered_stats"); }
        cards.push(OfferedCard { entity_id: *id, card_id: card_id.to_string(),
            card_type: kind.to_string(), observed_cost: observed.cost,
            observed_cost_resource: observed.cost_resource, observed_attack: observed.attack,
            observed_health: observed.health, observed_damage: observed.damage,
            observed_armor: observed.armor, observed_durability: observed.durability,
            combat: observed.combat });
    }
    Ok(LocalChoice { choice_id: set.id, source_entity: source.id, source_card_id: source_id.to_string(),
        minimum: set.minimum, maximum: set.maximum, offered_cards: cards })
}
