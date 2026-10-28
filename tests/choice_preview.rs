use hearth_agent::{choice_preview::ChoicePreview, replay};
use std::io::Cursor;

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn choice(text: &str) -> String { format!("D 0 GameState.DebugPrintEntityChoices() - {text}\n") }
fn fixture() -> String {
    ["CREATE_GAME", "GameEntity EntityID=1", "tag=STATE value=RUNNING", "tag=STEP value=MAIN_ACTION",
        "Player EntityID=2 PlayerID=1", "tag=CURRENT_PLAYER value=1",
        "Player EntityID=3 PlayerID=2", "tag=CURRENT_PLAYER value=0",
        "FULL_ENTITY - Creating ID=10 CardID=TLC_515", "tag=ZONE value=PLAY",
        "tag=CONTROLLER value=1", "tag=CARDTYPE value=SPELL",
        "FULL_ENTITY - Creating ID=20 CardID=CFM_630", "tag=ZONE value=SETASIDE",
        "tag=CONTROLLER value=1", "tag=CARDTYPE value=SPELL", "tag=COST value=0",
        "FULL_ENTITY - Creating ID=21 CardID=DED_004", "tag=ZONE value=SETASIDE",
        "tag=CONTROLLER value=1", "tag=CARDTYPE value=WEAPON"]
        .into_iter().map(power).collect::<String>()
        + "D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n"
        + &choice("id=7 Player=2 TaskList= ChoiceType=GENERAL CountMin=1 CountMax=1")
        + &choice("Source=10") + &choice("Entities[0]=20") + &choice("Entities[1]=21")
}
fn preview(log: &str) -> ChoicePreview {
    let replay = replay::read(Cursor::new(log)).unwrap();
    ChoicePreview::from_game(&replay.games[0])
}

#[test]
fn local_reviewed_choice_preserves_order_zero_and_unknown_cost_without_execution() {
    let result = preview(&fixture());
    assert!(result.blocked_by.is_empty());
    assert!(!result.complete && !result.actionable && !result.legality_verified);
    let choice = result.choice.unwrap();
    assert_eq!(choice.choice_id, 7);
    assert_eq!(choice.source_card_id, "TLC_515");
    assert_eq!(choice.offered_cards.iter().map(|c| c.entity_id).collect::<Vec<_>>(), [20, 21]);
    assert_eq!(choice.offered_cards[0].observed_cost, Some(0));
    assert_eq!(choice.offered_cards[1].observed_cost, None);
}

#[test]
fn opponent_unknown_owner_hidden_zone_and_unsupported_sources_reveal_no_cards() {
    let original = fixture();
    let no_submission = original.lines().filter(|line| !line.contains(" GameState.SendOption() - "))
        .map(|line| format!("{line}\n")).collect::<String>();
    for log in [no_submission, original.replace("Player=2 TaskList", "Player=3 TaskList"),
        original.replace("Player=2 TaskList", "Player=Unknown TaskList"),
        original.replace("tag=ZONE value=SETASIDE", "tag=ZONE value=DECK"),
        original.replace("CardID=TLC_515", "CardID=UNREVIEWED"),
        original.replace("tag=COST value=0", "tag=COST value=bad")] {
        let result = preview(&log);
        assert!(result.choice.is_none());
        let text = serde_json::to_string(&result).unwrap();
        assert!(!text.contains("CFM_630") && !text.contains("DED_004"));
    }
}

#[test]
fn submission_or_state_change_hides_previous_choice_cards() {
    for suffix in [power("TAG_CHANGE Entity=1 tag=TURN value=2"),
        "D 0 GameState.DebugPrintEntitiesChosen() - id=7 Player=2 EntitiesCount=1\n".into()] {
        let result = preview(&(fixture() + &suffix));
        assert!(result.choice.is_none());
        assert_eq!(result.blocked_by, ["no_current_local_choice"]);
    }
}

#[test]
fn one_opponent_or_hidden_offer_suppresses_the_whole_local_projection() {
    for change in ["TAG_CHANGE Entity=20 tag=CONTROLLER value=2",
        "TAG_CHANGE Entity=21 tag=ZONE value=HAND", "TAG_CHANGE Entity=21 tag=COST value=-1"] {
        let log = fixture().replace("D 0 GameState.SendOption()", 
            &(power(change) + "D 0 GameState.SendOption()"));
        let result = preview(&log);
        assert!(result.choice.is_none());
        assert!(!serde_json::to_string(&result).unwrap().contains("CFM_630"));
    }
}

#[test]
fn offered_stats_share_board_unknown_resource_and_combat_semantics() {
    let log = fixture().replace("D 0 GameState.SendOption()", 
        &(power("TAG_CHANGE Entity=20 tag=ATK value=0")
        + &power("TAG_CHANGE Entity=20 tag=HEALTH value=5")
        + &power("TAG_CHANGE Entity=20 tag=CARD_ALTERNATE_COST value=1")
        + &power("TAG_CHANGE Entity=20 tag=TAUNT value=0")
        + "D 0 GameState.SendOption()"));
    let choice = preview(&log).choice.unwrap();
    let card = &choice.offered_cards[0];
    assert_eq!(card.observed_attack, Some(0));
    assert_eq!(card.observed_health, Some(5));
    assert_eq!(card.observed_cost_resource, Some("health"));
    assert_eq!(card.combat.taunt, Some(false));
    assert_eq!(card.combat.divine_shield, None);
    assert_eq!(choice.offered_cards[1].observed_cost_resource, None);
    let bad = log.replace("tag=TAUNT value=0", "tag=TAUNT value=2");
    assert!(preview(&bad).choice.is_none());
}

#[test]
fn old_god_general_minion_choice_does_not_authorize_other_power_types() {
    let base = fixture().replace("CardID=TLC_515", "CardID=BE_017")
        .replace("tag=CARDTYPE value=SPELL", "tag=CARDTYPE value=MINION")
        .replace("tag=CARDTYPE value=WEAPON", "tag=CARDTYPE value=MINION");
    assert!(preview(&base).choice.is_some());
    // Mutate an offered entity before the fresh packet; only MINION offers are reviewed for this source.
    let changed = base.replace("D 0 GameState.SendOption()", 
        "D 0 GameState.DebugPrintPower() - TAG_CHANGE Entity=21 tag=CARDTYPE value=SPELL\nD 0 GameState.SendOption()");
    assert_eq!(preview(&changed).blocked_by, ["unreviewed_old_god_choice"]);
}
