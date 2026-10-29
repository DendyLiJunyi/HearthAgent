use std::io::Cursor;
use hearth_agent::{card_play_preview, protocol::Action, replay};

fn fixture() -> String {
    let mut log = ["CREATE_GAME", "GameEntity EntityID=1", "tag=STATE value=RUNNING",
        "tag=STEP value=MAIN_ACTION", "Player EntityID=2 PlayerID=1", "tag=CURRENT_PLAYER value=1",
        "Player EntityID=3 PlayerID=2", "tag=CURRENT_PLAYER value=0",
        "FULL_ENTITY - Creating ID=10 CardID=EX1_144", "tag=ZONE value=HAND",
        "tag=CARDTYPE value=SPELL", "tag=CONTROLLER value=1",
        "FULL_ENTITY - Creating ID=20 CardID=LOOT_412", "tag=ZONE value=PLAY",
        "tag=CARDTYPE value=MINION", "tag=CONTROLLER value=1"]
        .iter().map(|s| format!("D 0 GameState.DebugPrintPower() - {s}\n")).collect::<String>();
    log.push_str("D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n");
    for s in ["id=7", "option 0 type=POWER mainEntity=10 error=NONE errorParam=",
        "target 0 entity=20 error=NONE errorParam="] {
        log.push_str(&format!("D 0 GameState.DebugPrintOptions() - {s}\n"));
    }
    log
}

#[test]
fn damage_spells_accept_explicit_enemy_minions_but_never_heroes() {
    for card in ["REV_939", "JAIL_225"] {
        let log = fixture().replace("EX1_144", card)
            .replace("tag=CARDTYPE value=MINION\nD 0 GameState.DebugPrintPower() - tag=CONTROLLER value=1",
                     "tag=CARDTYPE value=MINION\nD 0 GameState.DebugPrintPower() - tag=CONTROLLER value=2");
        let game = replay::read(Cursor::new(&log)).unwrap().games.remove(0);
        assert_eq!(card_play_preview::from_game(&game).candidates.len(), 1);
        let game = replay::read(Cursor::new(log.replace("value=MINION", "value=HERO"))).unwrap().games.remove(0);
        assert!(card_play_preview::from_game(&game).candidates.is_empty());
    }
}

#[test]
fn shadowstep_has_explicit_target_and_is_exported_without_execution_permission() {
    let game = replay::read(Cursor::new(fixture())).unwrap().games.remove(0);
    let preview = card_play_preview::from_game(&game);
    assert!(preview.blocked_by.is_empty());
    assert!(!preview.actionable && !preview.complete && !preview.legality_verified);
    assert_eq!(preview.candidates.len(), 1);
    assert_eq!(preview.candidates[0].action, Action::PlayCard { source: 10, target: Some(20), position: None });
    let exported: serde_json::Value = serde_json::from_str(&hearth_agent::export::game_json(&game)).unwrap();
    assert_eq!(exported["card_play_preview"]["candidates"].as_array().unwrap().len(), 1);
    assert!(exported["action_preview"]["candidates"].as_array().unwrap().is_empty());
}

#[test]
fn hidden_unknown_wrong_type_and_enemy_targets_are_not_card_plays() {
    for (from, to) in [("CardID=EX1_144", "CardID=UNKNOWN"), ("value=HAND", "value=DECK"),
        ("value=SPELL", "value=MINION"), ("value=MINION", "value=HERO"),
        ("tag=CONTROLLER value=1", "tag=CONTROLLER value=2"),
        ("entity=20 error=NONE", "entity=20 error=INVALID"),
        ("mainEntity=10 error=NONE", "mainEntity=10 error=INVALID") ] {
        let game = replay::read(Cursor::new(fixture().replace(from, to))).unwrap().games.remove(0);
        assert!(card_play_preview::from_game(&game).candidates.is_empty(), "{from}");
    }
}

#[test]
fn partial_target_lists_stale_packets_and_suboptions_do_not_infer_a_play() {
    for log in [fixture().lines().filter(|l| !l.contains("target 0")).collect::<Vec<_>>().join("\n") + "\n",
        fixture() + "D 0 GameState.DebugPrintPower() - TAG_CHANGE Entity=20 tag=ATK value=3\n",
        fixture() + "D 0 GameState.DebugPrintOptions() - subOption 0 entity=10 error=NONE\n"] {
        let game = replay::read(Cursor::new(log)).unwrap().games.remove(0);
        assert!(card_play_preview::from_game(&game).candidates.is_empty());
    }
}
