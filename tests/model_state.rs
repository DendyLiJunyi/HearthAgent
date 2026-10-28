use hearth_agent::model_state::{compact_board, expand_board};
use hearth_agent::{board::BoardView, export, replay};
use serde_json::{json, Value};
use std::io::Cursor;

fn fixture_board() -> Value {
    let replay = replay::read(Cursor::new(include_str!("../fixtures/wild-rogue-attacks.log"))).unwrap();
    serde_json::from_str(&export::board_json(&BoardView::from_game(&replay.games[0]))).unwrap()
}

#[test]
fn real_parser_projection_roundtrips_without_dropping_unknowns_or_entities() {
    let board = fixture_board();
    let encoded = compact_board(&board).unwrap();
    assert_eq!(expand_board(&encoded).unwrap(), board);
    assert_eq!(encoded["encoding"], "nullable_card_defaults_v1");
    assert!(encoded.to_string().len() < board.to_string().len());
    assert_eq!(encoded["board"]["actionable"], false);
    assert_eq!(encoded["board"]["complete"], false);
}

#[test]
fn false_zero_and_hidden_unknown_values_remain_distinct() {
    let mut board = fixture_board();
    let card = &mut board["players"][0]["in_play"][0];
    card["attack"] = json!(0);
    card["exhausted"] = json!(false);
    card["combat"]["taunt"] = json!(false);
    card["combat"]["divine_shield"] = json!(true);
    card["health"] = Value::Null;
    let encoded = compact_board(&board).unwrap();
    let card = &encoded["board"]["players"][0]["in_play"][0];
    assert_eq!(card["attack"], 0);
    assert_eq!(card["exhausted"], false);
    assert_eq!(card["combat"]["taunt"], false);
    assert_eq!(card["combat"]["divine_shield"], true);
    assert!(card.get("health").is_none());
    assert_eq!(expand_board(&encoded).unwrap(), board);
}

#[test]
fn schema_drift_or_changed_defaults_are_rejected() {
    let mut board = fixture_board();
    board["players"][0]["in_play"][0]["new_field"] = json!(1);
    assert!(compact_board(&board).is_err());
    let mut board = fixture_board();
    board["players"][0]["in_play"][0].as_object_mut().unwrap().remove("health");
    assert!(compact_board(&board).is_err());
    let mut encoded = compact_board(&fixture_board()).unwrap();
    encoded["card_defaults"]["health"] = json!(0);
    assert!(expand_board(&encoded).is_err());
}
