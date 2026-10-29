//! Lossless null elision for already-redacted diagnostic boards, never raw entities.
use serde_json::{json, Map, Value};

const ENCODING: &str = "nullable_card_defaults_v1";
const MEANING: &str = "In each hand, in_play and graveyard card, missing fields equal card_defaults. Merge nested combat defaults too. Null means unknown, never zero or false. No cards or known values have been removed.";

fn defaults() -> Value {
    serde_json::from_str(include_str!("../config/model/card-defaults.json"))
        .expect("checked-in card defaults must be valid JSON")
}

fn transform_card(value: &Value, default: &Value, expand: bool) -> Result<Value, String> {
    let fields = value.as_object().ok_or("card fields must be an object")?;
    let schema = default.as_object().ok_or("card defaults must be an object")?;
    if fields.keys().any(|key| !schema.contains_key(key)) || (!expand && fields.len() != schema.len()) {
        return Err("card schema differs from encoding defaults".into());
    }
    let mut result = if expand { schema.clone() } else { Map::new() };
    for (key, value) in fields {
        if schema[key].is_object() {
            let nested = transform_card(value, &schema[key], expand)?;
            if expand || !nested.as_object().expect("nested fields are an object").is_empty() {
                result.insert(key.clone(), nested);
            }
        } else if expand || !value.is_null() {
            result.insert(key.clone(), value.clone());
        }
    }
    Ok(Value::Object(result))
}

fn transform_board(board: &Value, expand: bool) -> Result<Value, String> {
    let mut board = board.clone();
    let schema = defaults();
    let players = board.get_mut("players").and_then(Value::as_array_mut)
        .ok_or("board players must be an array")?;
    for player in players {
        for zone in ["hand", "in_play", "graveyard"] {
            let cards = player.get_mut(zone).and_then(Value::as_array_mut)
                .ok_or("board card zone must be an array")?;
            for card in cards {
                *card = transform_card(card, &schema, expand)?;
            }
        }
    }
    Ok(board)
}

/// Preserve every known value, entity and ordering; missing nullable fields use explicit defaults.
pub fn compact_board(board: &Value) -> Result<Value, String> {
    Ok(json!({"encoding": ENCODING, "meaning": MEANING, "card_defaults": defaults(),
        "board": transform_board(board, false)?}))
}

/// Restore the exact diagnostic projection, including unknown values, for audit or inspection.
pub fn expand_board(encoded: &Value) -> Result<Value, String> {
    if encoded.get("encoding") != Some(&json!(ENCODING))
        || encoded.get("meaning") != Some(&json!(MEANING))
        || encoded.get("card_defaults") != Some(&defaults()) {
        return Err("unknown encoding schema".into());
    }
    transform_board(encoded.get("board").ok_or("encoded board missing")?, true)
}
