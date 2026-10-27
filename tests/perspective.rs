use std::io::Cursor;
use hearth_agent::board::BoardView;
use hearth_agent::export::{board_json, game_json};
use hearth_agent::replay::{read, Game};
use hearth_agent::watch::StreamState;

fn power(text: &str) -> String {
    format!("D 0 GameState.DebugPrintPower() - {text}\n")
}

fn submission() -> &'static str {
    "D 0 GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=0 selectedPosition=1\n"
}

fn fixture() -> String {
    ["CREATE_GAME", "GameEntity EntityID=1", "tag=STATE value=RUNNING", "tag=STEP value=MAIN_ACTION",
        "Player EntityID=2 PlayerID=1", "tag=CURRENT_PLAYER value=0",
        "Player EntityID=3 PlayerID=2", "tag=CURRENT_PLAYER value=1",
        "FULL_ENTITY - Creating ID=10 CardID=OPPONENT_PRIVATE", "tag=ZONE value=HAND",
        "tag=CONTROLLER value=1", "tag=COST value=9",
        "FULL_ENTITY - Creating ID=20 CardID=LOCAL_CARD", "tag=ZONE value=HAND",
        "tag=CONTROLLER value=2", "tag=COST value=2"]
        .into_iter().map(power).collect()
}

fn parse(log: &str) -> Game {
    read(Cursor::new(log)).unwrap().games.pop().unwrap()
}

#[test]
fn only_local_submission_reveals_own_hand_without_making_it_public_or_actionable() {
    let mut log = fixture();
    assert_eq!(parse(&log).perspective.player_id(), None);
    log.push_str(submission());
    let game = parse(&log);
    let board = BoardView::from_game(&game);
    assert_eq!(board.perspective, Some(2));
    assert_eq!(board.players[0].hand[0].card_id, None);
    assert_eq!(board.players[0].hand[0].cost, None);
    assert_eq!(board.players[1].hand[0].card_id, Some("LOCAL_CARD"));
    assert_eq!(board.players[1].hand[0].cost, Some(2));
    assert!(!board.players[1].hand[0].public_zone);
    let json: serde_json::Value = serde_json::from_str(&board_json(&board)).unwrap();
    assert_eq!(json["perspective_source"], "local_main_action_submission");
    assert_eq!(json["complete"], false);
    assert_eq!(json["actionable"], false);
    assert!(!json.to_string().contains("OPPONENT_PRIVATE"));
}

#[test]
fn choices_options_and_animation_do_not_establish_local_identity() {
    for line in [
        "GameState.SendChoices() - id=1 ChoiceType=MULLIGAN",
        "GameState.DebugPrintEntitiesChosen() - id=1 Player=Someone EntitiesCount=0",
        "GameState.DebugPrintOptions() - id=1",
        "PowerTaskList.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=0 selectedPosition=1",
        "GameState.SendOption() - selectedOption=1 selectedSubOption=-2 selectedTarget=0 selectedPosition=1",
        "GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=0",
    ] {
        let game = parse(&(fixture() + "D 0 " + line + "\n"));
        assert_eq!(game.perspective.player_id(), None, "{line}");
    }
}

#[test]
fn incomplete_ambiguous_or_non_action_turn_state_cannot_identify_a_player() {
    for log in [
        fixture().replace("tag=CURRENT_PLAYER value=0", "tag=CURRENT_PLAYER value=1"),
        fixture().replace("tag=CURRENT_PLAYER value=0", "tag=CURRENT_PLAYER value=unknown"),
        fixture().replace(&power("tag=CURRENT_PLAYER value=0"), ""),
        fixture().replace("value=MAIN_ACTION", "value=BEGIN_MULLIGAN"),
        fixture().replace("value=RUNNING", "value=COMPLETE"),
        fixture().replace("Player EntityID=2 PlayerID=1", "GameEntity EntityID=2"),
        fixture() + &power("TAG_CHANGE Entity=UnknownPlayer tag=CURRENT_PLAYER value=1"),
        fixture() + &power("FULL_ENTITY - Creating ID=invalid CardID="),
    ] {
        assert_eq!(parse(&(log + submission())).perspective.player_id(), None);
    }
}

#[test]
fn perspective_is_bound_at_submission_and_conflicts_stay_redacted_until_new_game() {
    let mut log = fixture() + submission();
    log += &power("TAG_CHANGE Entity=3 tag=CURRENT_PLAYER value=0");
    log += &power("TAG_CHANGE Entity=2 tag=CURRENT_PLAYER value=1");
    assert_eq!(parse(&log).perspective.player_id(), Some(2));
    log += submission();
    let game = parse(&log);
    assert!(game.perspective.conflicting);
    assert_eq!(game.perspective.player_id(), None);
    let json = board_json(&BoardView::from_game(&game));
    assert!(!json.contains("LOCAL_CARD"));
    assert!(!json.contains("OPPONENT_PRIVATE"));
    log += submission();
    assert!(parse(&log).perspective.conflicting);
    log += &fixture();
    assert!(!parse(&log).perspective.conflicting);
    assert_eq!(parse(&log).perspective.player_id(), None);
}

#[test]
fn hidden_local_identity_also_redacts_cached_stats_and_deck_or_secret_cards() {
    for event in ["HIDE_ENTITY - Entity=20 tag=ZONE value=HAND",
        "TAG_CHANGE Entity=20 tag=ZONE value=DECK",
        "TAG_CHANGE Entity=20 tag=ZONE value=SECRET"] {
        let game = parse(&(fixture() + submission() + &power(event)));
        let json = board_json(&BoardView::from_game(&game));
        assert!(!json.contains("LOCAL_CARD"));
        assert!(!json.contains("\"cost\":2"));
    }
}

#[test]
fn every_byte_prefix_agrees_with_replay_and_submission_requires_a_complete_line() {
    let log = fixture() + submission() + &fixture();
    let mut stream = StreamState::default();
    for end in 1..=log.len() {
        stream.feed(&log.as_bytes()[end - 1..end]).unwrap();
        let expected = read(Cursor::new(&log.as_bytes()[..end])).unwrap();
        assert_eq!(stream.game().as_ref().map(game_json), expected.games.last().map(game_json));
    }
}
