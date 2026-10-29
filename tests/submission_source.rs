use std::io::Cursor;
use hearth_agent::{export::submission_source_json, replay};

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn fixture(owner: u32, zone: &str) -> String {
    let mut log = ["CREATE_GAME", "GameEntity EntityID=1", "tag=STATE value=RUNNING",
        "tag=STEP value=MAIN_ACTION", "Player EntityID=2 PlayerID=1", "tag=CURRENT_PLAYER value=1",
        "Player EntityID=3 PlayerID=2", "tag=CURRENT_PLAYER value=0",
        "FULL_ENTITY - Creating ID=10 CardID=PRIVATE_SOURCE", "tag=CARDTYPE value=SPELL"]
        .into_iter().map(power).collect::<String>();
    log += &power(&format!("tag=CONTROLLER value={owner}"));
    log += &power(&format!("tag=ZONE value={zone}"));
    log += "D 0 GameState.DebugPrintOptions() - id=7\n";
    log += "D 0 GameState.DebugPrintOptions() - option 0 type=POWER mainEntity=10 error=NONE\n";
    log += "D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n";
    log
}

#[test]
fn local_hand_and_public_sources_preserve_visible_type_and_zone() {
    for (owner, zone, expected_zone) in [(1, "HAND", "hand"), (2, "PLAY", "in_play")] {
        let replay = replay::read(Cursor::new(fixture(owner, zone))).unwrap();
        let value = submission_source_json(&replay.games[0]);
        assert_eq!(value["card_id"], "PRIVATE_SOURCE");
        assert_eq!(value["card_type"], "SPELL");
        assert_eq!(value["zone"], expected_zone);
        assert_eq!(value["public_zone"], zone == "PLAY");
    }
}

#[test]
fn opponent_hand_and_unknown_or_hidden_sources_never_reveal_cached_identity() {
    for (owner, zone) in [(2, "HAND"), (1, "DECK"), (1, "SECRET")] {
        let replay = replay::read(Cursor::new(fixture(owner, zone))).unwrap();
        let value = submission_source_json(&replay.games[0]);
        assert!(!value.to_string().contains("PRIVATE_SOURCE"));
        assert!(value["card_type"].is_null());
    }
}

#[test]
fn submission_visitor_freezes_source_before_later_movement_or_identity_change() {
    let log = fixture(1, "HAND") + &power("SHOW_ENTITY - Updating Entity=10 CardID=LATER_CARD")
        + &power("TAG_CHANGE Entity=10 tag=ZONE value=PLAY");
    let mut rows = Vec::new();
    replay::visit_option_submissions(Cursor::new(log), &mut |_, game| {
        rows.push(submission_source_json(game));
    }).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["card_id"], "PRIVATE_SOURCE");
    assert_eq!(rows[0]["zone"], "hand");
}
