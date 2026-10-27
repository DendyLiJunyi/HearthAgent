use hearth_agent::{replay, watch::StreamState};
use std::io::Cursor;

fn power(text: &str) -> String {
    format!("D 0 GameState.DebugPrintPower() - {text}\n")
}

fn option(text: &str) -> String {
    format!("D 0 GameState.DebugPrintOptions() - {text}\n")
}

fn parse(log: &str) -> replay::Game {
    replay::read(Cursor::new(log)).unwrap().games.remove(0)
}

fn packet() -> String {
    power("CREATE_GAME") + &option("id=7")
        + &option("option 0 type=END_TURN mainEntity= error=NONE errorParam=")
        + &option("option 1 type=POWER mainEntity=[entityName=Private id=999 name id=42 zone=HAND player=1] error=REQ_ENOUGH_MANA errorParam=")
        + &option("target 0 entity=[entityName=PrivateTarget id=13 zone=PLAY player=2] error=NONE errorParam=")
}

#[test]
fn parses_options_targets_and_errors_without_display_names() {
    let game = parse(&packet());
    assert_eq!(game.options.packets_seen, 1);
    assert_eq!(game.options.malformed_records, 0);
    let set = game.options.latest.as_ref().unwrap();
    assert_eq!(set.id, 7);
    assert_eq!(set.observed_power_sequence, 1);
    assert!(!set.stale);
    assert_eq!(set.options[0].entity_id, None);
    assert_eq!(set.options[1].entity_id, Some(42));
    assert_eq!(set.options[1].error, "REQ_ENOUGH_MANA");
    assert_eq!(set.options[1].targets[0].entity_id, 13);
    let json = game.options.to_json();
    assert!(!json.contains("Private"));
    assert!(json.contains("\"complete\":false"));
    assert!(json.contains("\"actionable\":false"));
}

#[test]
fn state_updates_and_submissions_invalidate_but_animation_does_not() {
    for event in [power("TAG_CHANGE Entity=1 tag=TURN value=2"),
        "D 0 GameState.SendOption() - selectedOption=1\n".into(),
        "D 0 GameState.SendChoices() - id=1\n".into(),
        "D 0 GameState.DebugPrintEntityChoices() - id=1\n".into(),
        "D 0 GameState.DebugPrintEntitiesChosen() - id=1\n".into()] {
        assert!(parse(&(packet() + &event)).options.latest.unwrap().stale);
    }
    let log = packet() + "D 0 PowerTaskList.DebugPrintPower() - BLOCK_START\n";
    assert!(!parse(&log).options.latest.unwrap().stale);
}

#[test]
fn replacement_headers_and_new_games_never_retain_prior_options() {
    let log = packet() + &power("TAG_CHANGE Entity=1 tag=TURN value=2") + &option("id=8");
    let game = parse(&log);
    let set = game.options.latest.unwrap();
    assert_eq!(set.id, 8);
    assert!(set.options.is_empty());
    assert!(!set.stale);
    let broken = parse(&(log.clone() + &option("id=not-a-number")));
    assert!(broken.options.latest.is_none());
    assert_eq!(broken.options.malformed_records, 1);
    let replay = replay::read(Cursor::new(log + &power("CREATE_GAME"))).unwrap();
    assert_eq!(replay.games[1].options.packets_seen, 0);
    assert!(replay.games[1].options.latest.is_none());
}

#[test]
fn targets_do_not_attach_across_bad_rows_or_unknown_suboptions() {
    for bad in ["option 2 broken", "subOption 0 unsupported", "option 9 type=POWER mainEntity=1 error=NONE"] {
        let log = packet() + &option(bad) + &option("target 1 entity=14 error=NONE errorParam=");
        let game = parse(&log);
        assert!(game.options.malformed_records > 0);
        assert_eq!(game.options.latest.unwrap().options[1].targets.len(), 1);
    }
    let log = power("CREATE_GAME") + &option("id=1")
        + &option("target 0 entity=13 error=NONE errorParam=");
    assert_eq!(parse(&log).options.malformed_records, 1);
}

#[test]
fn unsupported_error_payload_is_not_exported() {
    let log = power("CREATE_GAME") + &option("id=1")
        + &option("option 0 type=POWER mainEntity=10 error=PrivatePlayer#123 errorParam=");
    let game = parse(&log);
    assert_eq!(game.options.unsupported_records, 1);
    assert!(!game.options.to_json().contains("PrivatePlayer"));
}

#[test]
fn streaming_option_packets_match_replay_at_each_line_boundary() {
    let log = packet() + &power("TAG_CHANGE Entity=1 tag=TURN value=2") + &option("id=8");
    let mut state = StreamState::default();
    let mut prefix = String::new();
    for line in log.split_inclusive('\n') {
        prefix.push_str(line);
        for byte in line.bytes() { state.feed(&[byte]).unwrap(); }
        assert_eq!(state.game().unwrap().options, parse(&prefix).options);
    }
}

#[test]
fn suboption_targets_keep_their_own_parent_and_restart_indices() {
    let log = packet()
        + &option("subOption 0 entity=100 error=NONE errorParam=")
        + &option("target 0 entity=101 error=NONE errorParam=")
        + &option("subOption 1 entity=200 error=REQ_ENOUGH_MANA errorParam=")
        + &option("target 0 entity=201 error=REQ_TARGET_NOT_ENEMY errorParam=");
    let game = parse(&log);
    assert_eq!(game.options.malformed_records, 0);
    assert_eq!(game.options.unsupported_records, 0);
    let main = &game.options.latest.as_ref().unwrap().options[1];
    assert_eq!(main.targets[0].entity_id, 13);
    assert_eq!(main.sub_options[0].targets[0].entity_id, 101);
    assert_eq!(main.sub_options[1].targets[0].entity_id, 201);
    let json: serde_json::Value = serde_json::from_str(&game.options.to_json()).unwrap();
    assert_eq!(json["latest"]["options"][1]["sub_options"][0]["entity_id"], 100);
    let mut state = StreamState::default();
    for byte in log.bytes() { state.feed(&[byte]).unwrap(); }
    assert_eq!(state.game().unwrap().options, game.options);
}

#[test]
fn invalid_suboptions_and_targets_do_not_silently_repair_packet_validity() {
    for bad in ["subOption 2 entity=100 error=NONE", "subOption 0 entity=missing error=NONE",
        "target 2 entity=100 error=NONE", "futureRow 0 entity=100"] {
        let log = packet() + &option(bad) + &option("target 1 entity=999 error=NONE");
        let game = parse(&log);
        let set = game.options.latest.as_ref().unwrap();
        assert!(set.malformed_records + set.unsupported_records > 0);
        assert_eq!(set.options[1].targets.len(), 1);
        let replacement = parse(&(log + &option("id=8")));
        assert!(replacement.options.malformed_records + replacement.options.unsupported_records > 0);
        let set = replacement.options.latest.unwrap();
        assert_eq!(set.malformed_records + set.unsupported_records, 0);
    }
}
