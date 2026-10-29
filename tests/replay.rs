use hearth_agent::replay;
use std::io::Cursor;

fn line(text: &str) -> String { format!("D 00:00:00 GameState.DebugPrintPower() - {text}\n") }
fn base() -> String {
    ["CREATE_GAME", "GameEntity EntityID=1", "tag=CARDTYPE value=GAME", "Player EntityID=2 PlayerID=1", "tag=PLAYER_ID value=1", "Player EntityID=3 PlayerID=2", "tag=PLAYER_ID value=2"].map(line).concat()
}

#[test]
fn late_mulligan_alias_resolves_earlier_unicode_player_updates() {
    let mut log = base();
    log += &line("TAG_CHANGE Entity=测试玩家#12 tag=RESOURCES value=7");
    log += "D 00:00:00 GameState.DebugPrintEntityChoices() - id=1 Player=测试玩家#12 TaskList=8 ChoiceType=MULLIGAN CountMin=0 CountMax=4\n";
    log += "D 00:00:00 GameState.DebugPrintEntityChoices() -   Source=GameEntity\r\n";
    log += "D 00:00:00 GameState.DebugPrintEntityChoices() - Entities[0]=[entityName=UNKNOWN ENTITY [cardType=INVALID] id=42 zone=HAND player=2]\n";
    let parsed = replay::read(Cursor::new(log)).unwrap();
    assert_eq!(parsed.games[0].entities[&3].tag("RESOURCES"), Some("7"));
    assert_eq!(parsed.games[0].unresolved_references, 0);
}

#[test]
fn animation_stream_cannot_reset_state_and_last_partial_line_is_ignored() {
    let log = base() + &line("TAG_CHANGE Entity=GameEntity tag=TURN value=15")
        + "D 00:00:00 PowerTaskList.DebugPrintPower() - CREATE_GAME\n"
        + "D 00:00:00 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=TURN value=99";
    let parsed = replay::read(Cursor::new(log)).unwrap();
    assert_eq!(parsed.games.len(), 1);
    assert_eq!(parsed.games[0].game_tag("TURN"), Some("15"));
    assert!(parsed.ignored_partial_line);
}

#[test]
fn bracket_references_show_and_hide_cards_without_leaking_identity() {
    let log = base() + &line("FULL_ENTITY - Creating ID=42 CardID=")
        + &line("tag=ZONE value=HAND")
        + &line("SHOW_ENTITY - Updating Entity=[entityName=UNKNOWN ENTITY [cardType=INVALID] id=42 zone=HAND player=1] CardID=TEST_001")
        + &line("tag=COST value=4")
        + &line("HIDE_ENTITY - Entity=[entityName=Sample id=42 zone=HAND player=1] tag=ZONE value=DECK");
    let parsed = replay::read(Cursor::new(log)).unwrap();
    let e = &parsed.games[0].entities[&42];
    assert_eq!(e.card_id, None);
    assert_eq!(e.tag("ZONE"), Some("DECK"));
    assert_eq!(e.tag("COST"), Some("4")); // Last observed, not guaranteed current.
}

#[test]
fn matches_are_isolated_and_ambiguous_names_remain_unresolved() {
    let mut log = base();
    log += "D 00:00:00 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Same\n";
    log += "D 00:00:00 GameState.DebugPrintGame() - PlayerID=2, PlayerName=Same\n";
    log += &line("TAG_CHANGE Entity=Same tag=PLAYSTATE value=WON");
    log += &base();
    log += &line("TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE");
    let parsed = replay::read(Cursor::new(log)).unwrap();
    assert_eq!(parsed.games.len(), 2);
    assert_eq!(parsed.games[0].unresolved_references, 1);
    assert_eq!(parsed.games[1].unresolved_references, 0);
    assert_eq!(parsed.games[1].game_tag("STATE"), Some("COMPLETE"));
}

#[test]
fn arbitrary_choices_do_not_identify_the_player_from_targets() {
    let log = base()
        + "D 00:00:00 GameState.DebugPrintEntityChoices() - id=1 Player=Unknown TaskList=8 ChoiceType=GENERAL CountMin=1 CountMax=1\n"
        + "D 00:00:00 GameState.DebugPrintEntityChoices() - Entities[0]=[id=42 player=2]\n"
        + &line("TAG_CHANGE Entity=Unknown tag=RESOURCES value=7");
    assert_eq!(replay::read(Cursor::new(log)).unwrap().games[0].unresolved_references, 1);
}

#[test]
fn bracket_entity_id_is_not_taken_from_display_name() {
    let log = base() + &line("FULL_ENTITY - Creating ID=42 CardID=TEST_CARD")
        + &line("TAG_CHANGE Entity=[entityName=Name id=999 spoof id=42 zone=PLAY player=1] tag=ATK value=5");
    let parsed = replay::read(Cursor::new(log)).unwrap();
    assert_eq!(parsed.games[0].entities[&42].tag("ATK"), Some("5"));
    assert!(!parsed.games[0].entities.contains_key(&999));
}
