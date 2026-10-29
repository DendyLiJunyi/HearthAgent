use hearth_agent::{replay, watch::StreamState};
use std::io::Cursor;

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn option(text: &str) -> String { format!("D 0 GameState.DebugPrintOptions() - {text}\n") }
fn send(option: u32, sub: i32, target: u32, position: u32) -> String {
    format!("D 0 GameState.SendOption() - selectedOption={option} selectedSubOption={sub} selectedTarget={target} selectedPosition={position}\n")
}
fn packet() -> String {
    power("CREATE_GAME") + &option("id=7")
        + &option("option 0 type=END_TURN mainEntity= error=NONE")
        + &option("option 1 type=POWER mainEntity=[entityName=Private id=42 zone=HAND player=1] error=REQ_ENOUGH_MANA")
        + &option("target 0 entity=13 error=NONE")
        + &option("subOption 0 entity=100 error=NONE")
        + &option("target 0 entity=14 error=REQ_TARGET_NOT_ENEMY")
}
fn parse(log: &str) -> replay::Game { replay::read(Cursor::new(log)).unwrap().games.pop().unwrap() }

#[test]
fn main_and_suboption_submissions_bind_to_their_exact_target_branch() {
    for (sub, target, expected_error) in [(-1, 13, Some("NONE")),
        (0, 14, Some("REQ_TARGET_NOT_ENEMY")), (0, 13, None)] {
        let game = parse(&(packet() + &send(1, sub, target, 2)));
        let submission = game.options.latest_submission.as_ref().unwrap();
        let c = &submission.correlation;
        assert_eq!(submission.selection.position, 2);
        assert_eq!(submission.power_sequence, 1);
        assert_eq!(c.packet_id, Some(7));
        assert_eq!(c.packet_was_stale, Some(false));
        assert_eq!(c.source_entity, Some(42));
        assert_eq!(c.option_error.as_deref(), Some("REQ_ENOUGH_MANA"));
        assert_eq!(c.target_seen, Some(expected_error.is_some()));
        assert_eq!(c.target_error.as_deref(), expected_error);
        assert_eq!(c.sub_option_seen, (sub == 0).then_some(true));
        assert_eq!(c.sub_option_entity, (sub == 0).then_some(100));
        assert!(!c.legality_verified && !c.candidate_list_complete && !c.execution_confirmed);
        assert!(game.options.latest.as_ref().unwrap().stale);
        assert!(!game.options.to_json().contains("Private"));
    }
}

#[test]
fn end_turn_and_missing_parent_or_target_remain_distinct() {
    for (selected, sub, target, option_seen, sub_seen, target_seen) in [
        (0, -1, 0, Some(true), None, None),
        (9, -1, 13, Some(false), None, None),
        (1, 9, 13, Some(true), Some(false), None),
        (1, -1, 999, Some(true), None, Some(false)),
    ] {
        let game = parse(&(packet() + &send(selected, sub, target, 0)));
        let c = game.options.latest_submission.unwrap().correlation;
        assert_eq!(c.option_seen, option_seen);
        assert_eq!(c.sub_option_seen, sub_seen);
        assert_eq!(c.target_seen, target_seen);
    }
    let game = parse(&(power("CREATE_GAME") + &send(0, -1, 0, 0)));
    let c = game.options.latest_submission.unwrap().correlation;
    assert_eq!(c.packet_id, None);
    assert_eq!(c.option_seen, None);
}

#[test]
fn later_packets_and_state_changes_cannot_repair_or_rewrite_submission_context() {
    let initial = packet() + &send(1, -1, 13, 0);
    let game = parse(&initial);
    let saved = serde_json::to_value(&game.options.latest_submission).unwrap();
    for suffix in [option("id=8"), option("id=7"), power("TAG_CHANGE Entity=42 tag=ZONE value=GRAVEYARD")] {
        let later = parse(&(initial.clone() + &suffix));
        assert_eq!(serde_json::to_value(&later.options.latest_submission).unwrap(), saved);
    }
    let no_packet = power("CREATE_GAME") + &send(1, -1, 13, 0) + &option("id=7")
        + &option("option 0 type=END_TURN mainEntity= error=NONE");
    assert_eq!(parse(&no_packet).options.latest_submission.unwrap().correlation.packet_id, None);
}

#[test]
fn stale_malformed_and_ambiguous_evidence_is_preserved_without_success_claims() {
    let log = packet() + &power("TAG_CHANGE Entity=1 tag=TURN value=2") + &send(1, -1, 13, 0);
    assert_eq!(parse(&log).options.latest_submission.unwrap().correlation.packet_was_stale, Some(true));
    let log = packet() + &option("target 2 entity=15 error=NONE") + &send(1, 0, 14, 0);
    assert_eq!(parse(&log).options.latest_submission.unwrap().correlation.packet_malformed_records, Some(1));
    let log = packet() + &option("target 1 entity=14 error=NONE") + &send(1, 0, 14, 0);
    let c = parse(&log).options.latest_submission.unwrap().correlation;
    assert_eq!(c.target_seen, Some(true));
    assert!(c.target_ambiguous);
    assert_eq!(c.target_error, None);
    assert!(!c.execution_confirmed);
}

#[test]
fn malformed_sends_clear_previous_submission_and_other_streams_do_not_submit() {
    for bad in ["selectedOption=1", "selectedOption=1 selectedSubOption=-2 selectedTarget=0 selectedPosition=0",
        "selectedOption=1 selectedSubOption=-1 selectedTarget=0 selectedPosition=0 extra=1",
        "selectedOption=1 selectedSubOption=-1 selectedTarget=-1 selectedPosition=0"] {
        let log = packet() + &send(0, -1, 0, 0) + "D 0 GameState.SendOption() - " + bad + "\n";
        let game = parse(&log);
        assert_eq!(game.options.submissions_seen, 2);
        assert_eq!(game.options.malformed_submissions, 1);
        assert!(game.options.latest_submission.is_none());
    }
    let log = packet() + &send(0, -1, 0, 0).replace("GameState", "PowerTaskList");
    assert_eq!(parse(&log).options.submissions_seen, 0);
}

#[test]
fn submission_visitor_ignores_partial_lines_and_resets_per_game() {
    let log = packet() + &send(1, -1, 13, 0) + &option("id=99")
        + &power("CREATE_GAME") + &send(0, -1, 0, 0)
        + "D 0 GameState.SendOption() - selectedOption=1";
    let mut rows = Vec::new();
    let replay = replay::visit_option_submissions(Cursor::new(&log), &mut |number, game| {
        rows.push((number, game.options.submissions_seen,
            game.options.latest_submission.as_ref().unwrap().correlation.packet_id));
    }).unwrap();
    assert_eq!(rows, [(1, 1, Some(7)), (2, 1, None)]);
    assert!(replay.ignored_partial_line);
    let mut stream = StreamState::default();
    for end in 1..=log.len() {
        stream.feed(&log.as_bytes()[end - 1..end]).unwrap();
        let expected = replay::read(Cursor::new(&log.as_bytes()[..end])).unwrap();
        assert_eq!(stream.game().map(|game| game.options.to_json()),
            expected.games.last().map(|game| game.options.to_json()));
    }
}
