//! Deterministic JSON for diagnostic replay and live snapshots.
use crate::board::{BoardView, CardView};
use crate::replay::Game;

pub fn quote(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""), '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"), '\r' => out.push_str("\\r"), '\t' => out.push_str("\\t"),
            c if c < '\u{20}' => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"'); out
}

fn optional(value: Option<impl ToString>) -> String {
    value.map(|v| v.to_string()).unwrap_or("null".into())
}

fn string(value: Option<&str>) -> String {
    value.map(quote).unwrap_or("null".into())
}

fn cards_json(cards: &[CardView<'_>]) -> String {
    let cards = cards.iter().map(|c| format!(concat!(
        "{{\"entity_id\":{},\"position\":{},\"public_zone\":{},\"card_id\":{},",
        "\"card_type\":{},\"cost\":{},\"cost_resource\":{},\"attack\":{},\"health\":{},\"damage\":{},",
        "\"armor\":{},\"durability\":{},\"exhausted\":{},\"combat\":{}}}"),
        c.entity_id, optional(c.position), c.public_zone, string(c.card_id),
        string(c.card_type), optional(c.cost), string(c.cost_resource), optional(c.attack), optional(c.health),
        optional(c.damage), optional(c.armor), optional(c.durability), optional(c.exhausted),
        serde_json::to_string(&c.combat).expect("combat view contains only JSON-safe values")))
        .collect::<Vec<_>>().join(",");
    format!("[{cards}]")
}

pub fn board_json(board: &BoardView<'_>) -> String {
    let players = board.players.iter().map(|p| format!(concat!(
        "{{\"player_id\":{},\"entity_id\":{},\"current_player\":{},\"hero_entity\":{},",
        "\"resources\":{},\"resources_used\":{},\"temporary_resources\":{},",
        "\"in_play\":{},\"hand\":{},\"graveyard\":{},",
        "\"observed_deck_count\":{},\"observed_secret_count\":{}}}"),
        p.player_id, p.entity_id, optional(p.current_player), optional(p.hero_entity),
        optional(p.resources), optional(p.resources_used), optional(p.temporary_resources),
        cards_json(&p.in_play), cards_json(&p.hand), cards_json(&p.graveyard),
        p.observed_deck_count, p.observed_secret_count)).collect::<Vec<_>>().join(",");
    format!(concat!("{{\"perspective\":{},\"perspective_source\":{},\"perspective_conflicting\":{},\"complete\":false,\"actionable\":false,",
        "\"turn\":{},\"active_player\":{},\"invalid_fields\":{},\"players\":[{}]}}"),
        optional(board.perspective), string(board.perspective_source), board.perspective_conflicting,
        optional(board.turn), optional(board.active_player), board.invalid_fields, players)
}

/// Raw entities are diagnostic history; only `board` applies hidden-zone redaction.
pub fn game_json(game: &Game) -> String {
    let entities = game.entities.values().map(|e| {
        let tags = e.tags.iter().map(|(k,v)| format!("{}:{}", quote(k), quote(v))).collect::<Vec<_>>().join(",");
        format!("{{\"id\":{},\"card_id\":{},\"last_observed_tags\":{{{}}}}}", e.id,
            string(e.card_id.as_deref()), tags)
    }).collect::<Vec<_>>().join(",");
    let players = game.players.iter().map(|(p,e)| format!("{{\"player_id\":{p},\"entity_id\":{e}}}")).collect::<Vec<_>>().join(",");
    let ignored_types = game.ignored_power_record_types.iter()
        .map(|(kind, count)| format!("{}:{}", quote(kind), count)).collect::<Vec<_>>().join(",");
    format!(concat!("{{\"game_entity\":{},\"players\":[{}],\"entities\":[{}],",
        "\"unresolved_references\":{},\"malformed_records\":{},\"ignored_power_records\":{},",
        "\"ignored_power_record_types\":{{{}}},\"power_structure\":{},\"board\":{},\"logged_options\":{},\"action_preview\":{},\"logged_choices\":{},\"choice_preview\":{},\"card_play_preview\":{}}}"),
        optional(game.game_entity), players, entities, game.unresolved_references,
        game.malformed_records, game.ignored_power_records, ignored_types,
        game.structure.to_json(), board_json(&BoardView::from_game(game)), game.options.to_json(),
        serde_json::to_string(&crate::preview::ActionPreview::from_game(game)).expect("preview contains only JSON-safe values"),
        serde_json::to_string(&game.choices).expect("choices contain only JSON-safe values"),
        serde_json::to_string(&crate::choice_preview::ChoicePreview::from_game(game))
            .expect("choice preview contains only JSON-safe values"),
        serde_json::to_string(&crate::card_play_preview::from_game(game))
            .expect("card preview contains only JSON-safe values"))
}

/// Project the latest submission's source from the current redacted board.
/// Call at the submission visitor boundary to avoid importing later card state.
pub fn submission_source_json(game: &Game) -> serde_json::Value {
    let Some(id) = game.options.latest_submission.as_ref()
        .and_then(|submission| submission.correlation.source_entity) else {
        return serde_json::Value::Null;
    };
    let board = BoardView::from_game(game);
    for player in &board.players {
        for (zone, cards) in [("in_play", &player.in_play), ("hand", &player.hand)] {
            if let Some(card) = cards.iter().find(|card| card.entity_id == id) {
                return serde_json::json!({"entity_id": id, "player_id": player.player_id,
                    "zone": zone, "public_zone": card.public_zone,
                    "card_id": card.card_id, "card_type": card.card_type});
            }
        }
    }
    serde_json::Value::Null
}
