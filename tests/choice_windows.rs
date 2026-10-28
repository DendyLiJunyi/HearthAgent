use hearth_agent::replay::{self, ChoiceWindow};
use std::io::Cursor;
use serde_json::Value;

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn choice(text: &str) -> String { format!("D 0 GameState.DebugPrintEntityChoices() - {text}\n") }
fn chosen(text: &str) -> String { format!("D 0 GameState.DebugPrintEntitiesChosen() - {text}\n") }
fn base() -> String {
    power("CREATE_GAME") + &power("GameEntity EntityID=1") + &power("Player EntityID=2 PlayerID=1")
}
fn packet(id: u32) -> String {
    choice(&format!("id={id} Player=2 TaskList= ChoiceType=GENERAL CountMin=1 CountMax=1"))
        + &choice("Source=GameEntity") + &choice("Entities[0]=10") + &choice("Entities[1]=11")
}
fn windows(log: &str) -> Vec<(usize, bool, ChoiceWindow, Value)> {
    let mut result = Vec::new();
    replay::visit_choice_windows(Cursor::new(log), &mut |n, game, boundary, window| {
        result.push((n, boundary, window, serde_json::to_value(&game.choices).unwrap()));
    }).unwrap();
    result
}

#[test]
fn packets_and_submissions_are_frozen_before_next_record_and_never_merged() {
    let log = base() + &packet(7) + &chosen("id=7 Player=2 EntitiesCount=1")
        + &chosen("Entities[0]=10") + &packet(8) + &power("TAG_CHANGE Entity=1 tag=TURN value=3");
    let rows = windows(&log);
    assert_eq!(rows.len(), 3);
    assert!(rows.iter().all(|r| r.1));
    assert_eq!(rows[0].2.kind, "packet");
    assert_eq!(rows[0].3["sets"]["7"]["stale"], false);
    assert!(rows[0].3["latest_submission"].is_null());
    assert_eq!(rows[1].2.kind, "submission");
    assert_eq!(rows[1].3["latest_submission"]["entities"], serde_json::json!([10]));
    assert_eq!(rows[1].3["latest_submission"]["correlation"]["execution_confirmed"], false);
    assert!(rows[1].3["sets"].get("8").is_none());
    assert_eq!(rows[2].2.packet_id, Some(8));
}

#[test]
fn eof_and_partial_lines_never_claim_a_boundary_or_complete_submission() {
    let log = base() + &packet(7) + &chosen("id=7 Player=2 EntitiesCount=1")
        + "D 0 GameState.DebugPrintEntitiesChosen() - Entities[0]=10";
    let rows = windows(&log);
    assert_eq!(rows.len(), 2);
    assert!(!rows[1].1);
    assert_eq!(rows[1].3["latest_submission"]["list_complete"], false);
    let closed = windows(&(log + "\n"));
    assert!(!closed[1].1);
    assert_eq!(closed[1].3["latest_submission"]["list_complete"], true);
}

#[test]
fn reused_ids_new_games_and_malformed_headers_keep_window_identity() {
    let log = base() + &packet(7) + &packet(7) + &base()
        + &choice("id=bad Player=2 TaskList= ChoiceType=GENERAL CountMin=1 CountMax=1")
        + &power("TAG_CHANGE Entity=1 tag=TURN value=2");
    let rows = windows(&log);
    assert_eq!(rows.len(), 3);
    assert_eq!((rows[0].0, rows[1].0, rows[2].0), (1, 1, 2));
    assert_eq!(rows[2].2.packet_id, None);
    assert_eq!(rows[2].3["malformed_records"], 1);
    assert_eq!(rows[2].3["sets"], serde_json::json!({}));
}

#[test]
fn future_aliases_cannot_repair_earlier_unknown_owners() {
    let log = base() + &packet(7).replace("Player=2 TaskList", "Player=Private Alias TaskList")
        + "D 0 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Private Alias\n";
    let rows = windows(&log);
    assert!(rows[0].3["sets"]["7"]["owner_entity"].is_null());
    assert!(!rows[0].3.to_string().contains("Private Alias"));
    let final_replay = replay::read(Cursor::new(log)).unwrap();
    assert_eq!(final_replay.games[0].choices.sets[&7].owner_entity, Some(2));
}
