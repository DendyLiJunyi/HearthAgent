use std::io::Cursor;
use hearth_agent::preview::ActionPreview;
use hearth_agent::protocol::Action;
use hearth_agent::replay::{self, Game};

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn option(text: &str) -> String { format!("D 0 GameState.DebugPrintOptions() - {text}\n") }
fn parse(log: &str) -> Game { replay::read(Cursor::new(log)).unwrap().games.remove(0) }

fn board() -> String {
    ["CREATE_GAME", "GameEntity EntityID=1", "tag=STATE value=RUNNING", "tag=STEP value=MAIN_ACTION",
        "Player EntityID=2 PlayerID=1", "tag=CURRENT_PLAYER value=1",
        "Player EntityID=3 PlayerID=2", "tag=CURRENT_PLAYER value=0",
        "FULL_ENTITY - Creating ID=10 CardID=DRG_311t", "tag=ZONE value=PLAY", "tag=CARDTYPE value=MINION",
        "tag=CONTROLLER value=1", "tag=ATK value=2",
        "FULL_ENTITY - Creating ID=20 CardID=ENEMY_HERO", "tag=ZONE value=PLAY", "tag=CARDTYPE value=HERO",
        "tag=CONTROLLER value=2"]
        .into_iter().map(power).collect::<String>()
        + "D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n"
}

fn packet() -> String {
    option("id=7")
        + &option("option 0 type=END_TURN mainEntity= error=INVALID errorParam=")
        + &option("option 1 type=POWER mainEntity=10 error=NONE errorParam=")
        + &option("target 0 entity=20 error=NONE errorParam=")
}

#[test]
fn attack_preview_is_explicitly_non_executable_and_retains_option_provenance() {
    let preview = ActionPreview::from_game(&parse(&(board() + &packet())));
    assert!(preview.blocked_by.is_empty());
    assert!(!preview.complete && !preview.actionable);
    assert_eq!(preview.option_packet_id, Some(7));
    assert_eq!(preview.candidates.len(), 1);
    let candidate = &preview.candidates[0];
    assert_eq!(candidate.action, Action::Attack { source: 10, target: 20 });
    assert_eq!(candidate.option_index, 1);
    assert_eq!(candidate.target_index, Some(0));
    assert_eq!(preview.omitted["client_did_not_report_valid"], 1);
}

#[test]
fn uncertain_sources_targets_and_suboptions_are_never_interpreted_as_attacks() {
    for (log, reason) in [
        ((board() + &packet()).replace("entity=20 error=NONE", "entity=20 error=INVALID"), "client_rejected_target"),
        ((board() + &packet()).replace("mainEntity=10 error=NONE", "mainEntity=10 error=INVALID"), "client_did_not_report_valid"),
        ((board() + &packet()).replace("entity=20 error=NONE", "entity=999 error=NONE"), "unknown_target"),
        ((board() + &packet()).replace("entity=20 error=NONE", "entity=10 error=NONE"), "unsupported_target"),
        ((board() + &packet()).replace("mainEntity=10", "mainEntity=20"), "source_not_ours"),
        ((board() + &packet()).replace("tag=ATK value=2", "tag=ATK value=0"), "unknown_or_zero_attack"),
        ((board() + &packet()).replace("CardID=DRG_311t", "CardID=UNKNOWN_ACTIVATED_MINION"), "unreviewed_source_mechanic"),
        (board() + &packet() + &option("subOption 0 entity=42 error=NONE"), "sub_options_require_transaction"),
        ((board() + &packet()).replace(&option("target 0 entity=20 error=NONE errorParam="), ""), "no_explicit_targets"),
    ] {
        let preview = ActionPreview::from_game(&parse(&log));
        assert!(preview.candidates.is_empty(), "{reason}");
        assert!(preview.omitted.contains_key(reason), "{reason}: {preview:?}");
    }
}

#[test]
fn snapshots_are_blocked_on_turn_structure_parse_errors_or_stale_packets() {
    for (log, reason) in [
        (board().replace("GameState.SendOption()", "GameState.SendChoices()") + &packet(), "unknown_perspective"),
        (board() + &power("TAG_CHANGE Entity=2 tag=CURRENT_PLAYER value=0") + &power("TAG_CHANGE Entity=3 tag=CURRENT_PLAYER value=1") + &packet(), "not_our_turn"),
        (board() + &power("BLOCK_START BlockType=POWER Entity=10") + &packet(), "unclosed_power_structure"),
        (board() + &power("TAG_CHANGE Entity=Unresolved tag=ATK value=1") + &packet(), "invalid_observation"),
        (board() + &packet() + &power("TAG_CHANGE Entity=10 tag=ATK value=3"), "stale_options"),
        (board() + &packet() + &option("target 9 entity=20 error=NONE"), "invalid_options"),
    ] {
        let preview = ActionPreview::from_game(&parse(&log));
        assert!(preview.candidates.is_empty());
        assert!(preview.blocked_by.contains(&reason), "{reason}: {preview:?}");
    }
}

#[test]
fn review_windows_use_the_original_prefix_and_do_not_learn_future_identity() {
    let initial = board().replace("GameState.SendOption()", "GameState.SendChoices()");
    let log = initial + &packet()
        + "D 0 GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=20 selectedPosition=0\n"
        + &packet();
    let mut windows = Vec::new();
    let replay = replay::visit_option_windows(Cursor::new(log), &mut |game, state, boundary| {
        windows.push((game, ActionPreview::from_game(state), boundary));
    }).unwrap();
    assert_eq!(windows.len(), 2);
    assert_eq!(windows[0].0, 1);
    assert_eq!(windows[0].1.perspective, None);
    assert!(windows[0].2);
    assert_eq!(windows[1].1.perspective, Some(1));
    assert!(!windows[1].2);
    assert_eq!(windows[1].1.candidates.len(), 1);
    assert_eq!(replay.games[0].perspective.player_id(), Some(1));
}

#[test]
fn consecutive_headers_new_games_and_partial_tail_never_merge_review_windows() {
    let log = board() + &packet() + &option("id=8") + &board() + &packet()
        + "D 0 GameState.DebugPrintOptions() - target 1 entity=30 error=NONE";
    let mut windows = Vec::new();
    let replay = replay::visit_option_windows(Cursor::new(log), &mut |number, game, boundary| {
        windows.push((number, game.options.latest.as_ref().unwrap().id,
            ActionPreview::from_game(game).candidates.len(), boundary));
    }).unwrap();
    assert_eq!(windows, [(1, 7, 1, true), (1, 8, 0, true), (2, 7, 1, false)]);
    assert!(replay.ignored_partial_line);
}
