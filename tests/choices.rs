use std::io::Cursor;
use hearth_agent::{replay, watch::StreamState};

fn power(text: &str) -> String { format!("D 0 GameState.DebugPrintPower() - {text}\n") }
fn choice(text: &str) -> String { format!("D 0 GameState.DebugPrintEntityChoices() - {text}\n") }
fn chosen(text: &str) -> String { format!("D 0 GameState.DebugPrintEntitiesChosen() - {text}\n") }
fn parse(log: &str) -> replay::Game { replay::read(Cursor::new(log)).unwrap().games.pop().unwrap() }
fn base() -> String {
    power("CREATE_GAME") + &power("GameEntity EntityID=1")
        + &power("Player EntityID=2 PlayerID=1") + &power("Player EntityID=3 PlayerID=2")
}
fn packet(id: u32, owner: u32, kind: &str) -> String {
    choice(&format!("id={id} Player={owner} TaskList= ChoiceType={kind} CountMin=1 CountMax=1"))
        + &choice("Source=GameEntity")
        + &choice("Entities[0]=[entityName=PrivateCard id=10 zone=SETASIDE player=1]")
        + &choice("Entities[1]=11")
}

#[test]
fn choice_bounds_are_not_option_count_and_different_players_keep_separate_sets() {
    let game = parse(&(base() + &packet(7, 2, "GENERAL") + &packet(8, 3, "MULLIGAN")));
    assert_eq!(game.choices.packets_seen, 2);
    assert_eq!(game.choices.malformed_records, 0);
    let set = &game.choices.sets[&7];
    assert_eq!(set.owner_entity, Some(2));
    assert_eq!(set.source_entity, Some(1));
    assert_eq!(set.entities, [10, 11]);
    assert_eq!(set.maximum, 1);
    assert!(!set.complete && !set.stale);
    let json = serde_json::to_string(&game.choices).unwrap();
    assert!(!json.contains("PrivateCard"));
    assert!(!json.contains("source_seen"));
    assert!(!game.choices.actionable);
}

#[test]
fn submission_list_completeness_requires_exact_unique_contiguous_entries() {
    let initial = base() + &packet(7, 2, "GENERAL")
        + &chosen("id=7 Player=2 EntitiesCount=2") + &chosen("Entities[0]=10");
    let game = parse(&initial);
    assert!(game.choices.sets[&7].stale);
    assert!(!game.choices.latest_submission.unwrap().list_complete);
    let game = parse(&(initial.clone() + &chosen("Entities[1]=11")));
    assert!(game.choices.latest_submission.unwrap().list_complete);
    for row in ["Entities[1]=10", "Entities[2]=11", "Entities[0]=10"] {
        let game = parse(&(initial.clone() + &chosen(row)));
        assert!(game.choices.malformed_records > 0);
        assert!(!game.choices.latest_submission.unwrap().list_complete);
    }
    let zero = parse(&(base() + &chosen("id=7 Player=2 EntitiesCount=0")));
    assert!(zero.choices.latest_submission.unwrap().list_complete);
}

#[test]
fn malformed_choice_rows_remain_diagnostic_and_unknown_owners_are_not_guessed() {
    for row in ["Entities[3]=12", "Entities[1]=10", "Source=GameEntity", "Entities[2]=missing"] {
        let game = parse(&(base() + &packet(7, 2, "GENERAL") + &choice(row)));
        assert!(game.choices.sets[&7].malformed_records > 0);
    }
    let log = (base() + &packet(7, 2, "GENERAL")).replace("Player=2 TaskList=", "Player=Unknown Name TaskList=");
    let game = parse(&log);
    assert_eq!(game.choices.sets[&7].owner_entity, None);
    assert!(!serde_json::to_string(&game.choices).unwrap().contains("Unknown Name"));
}

#[test]
fn new_choices_replace_same_owner_and_state_events_invalidate_current_choices() {
    let game = parse(&(base() + &packet(7, 2, "GENERAL") + &packet(8, 2, "TARGET")));
    assert!(game.choices.sets[&7].stale);
    assert!(!game.choices.sets[&8].stale);
    for tail in [power("TAG_CHANGE Entity=1 tag=TURN value=2"),
        "D 0 GameState.SendChoices() - id=7 ChoiceType=GENERAL\n".into(),
        "D 0 GameState.DebugPrintOptions() - id=1\n".into()] {
        assert!(parse(&(base() + &packet(7, 2, "GENERAL") + &tail)).choices.sets[&7].stale);
    }
    let game = parse(&(base() + &packet(7, 2, "GENERAL") + &base()));
    assert!(game.choices.sets.is_empty());
}

#[test]
fn unknown_kind_and_broken_headers_never_look_like_supported_packets() {
    let game = parse(&(base() + &packet(7, 2, "FUTURE_KIND")));
    assert_eq!(game.choices.unsupported_records, 1);
    assert_eq!(game.choices.sets[&7].kind, "UNKNOWN");
    let log = base() + &packet(7, 2, "GENERAL")
        + &choice("id=bad Player=2 TaskList= ChoiceType=GENERAL CountMin=2 CountMax=1");
    let game = parse(&log);
    assert_eq!(game.choices.malformed_records, 1);
    assert!(game.choices.sets[&7].stale);
}

#[test]
fn choices_match_replay_at_every_line_boundary_and_ignore_partial_submission() {
    let log = base() + &packet(7, 2, "GENERAL")
        + &chosen("id=7 Player=2 EntitiesCount=1") + &chosen("Entities[0]=10");
    let mut stream = StreamState::default();
    let mut prefix = String::new();
    for line in log.split_inclusive('\n') {
        prefix.push_str(line);
        stream.feed(line.as_bytes()).unwrap();
        assert_eq!(stream.game().unwrap().choices, parse(&prefix).choices);
    }
    let partial = &log[..log.len() - 1];
    assert!(!parse(partial).choices.latest_submission.unwrap().list_complete);
}

#[test]
fn submission_correlation_checks_owner_bounds_and_observed_entities_separately() {
    let game = parse(&(base() + &packet(7, 2, "GENERAL")
        + &chosen("id=7 Player=3 EntitiesCount=2")
        + &chosen("Entities[0]=10") + &chosen("Entities[1]=99")));
    let submission = game.choices.latest_submission.unwrap();
    assert!(submission.list_complete); // Length correctness is independent of semantics.
    let correlation = submission.correlation;
    assert!(correlation.packet_seen);
    assert_eq!(correlation.owner_matches, Some(false));
    assert_eq!(correlation.declared_count_within_bounds, Some(false));
    assert_eq!(correlation.unobserved_entities, [99]);
    assert_eq!(correlation.packet_was_stale, Some(false));
    assert!(!correlation.candidate_list_complete && !correlation.execution_confirmed);
}

#[test]
fn matching_submission_is_not_execution_confirmation() {
    let game = parse(&(base() + &packet(7, 2, "TARGET")
        + &chosen("id=7 Player=2 EntitiesCount=1") + &chosen("Entities[0]=11")));
    let submission = game.choices.latest_submission.unwrap();
    let correlation = &submission.correlation;
    assert_eq!(correlation.owner_matches, Some(true));
    assert_eq!(correlation.declared_count_within_bounds, Some(true));
    assert_eq!(correlation.packet_kind, Some("TARGET"));
    assert!(correlation.unobserved_entities.is_empty());
    assert!(!correlation.execution_confirmed);
    let json = serde_json::to_string(&submission).unwrap();
    assert!(!json.contains("context") && !json.contains("source_seen"));
}

#[test]
fn later_or_reused_choice_ids_cannot_repair_submission_context() {
    let submitted = base() + &chosen("id=7 Player=2 EntitiesCount=1") + &chosen("Entities[0]=10");
    let game = parse(&(submitted + &packet(7, 2, "GENERAL")));
    let correlation = game.choices.latest_submission.unwrap().correlation;
    assert!(!correlation.packet_seen);
    assert_eq!(correlation.owner_matches, None);
    assert_eq!(correlation.declared_count_within_bounds, None);

    let original = base() + &packet(7, 2, "GENERAL")
        + &chosen("id=7 Player=2 EntitiesCount=1") + &chosen("Entities[0]=99");
    let replacement = packet(7, 3, "TARGET").replace("Entities[1]=11", "Entities[1]=99");
    let game = parse(&(original + &replacement));
    let correlation = game.choices.latest_submission.unwrap().correlation;
    assert_eq!(correlation.packet_kind, Some("GENERAL"));
    assert_eq!(correlation.owner_matches, Some(true));
    assert_eq!(correlation.unobserved_entities, [99]);
}

#[test]
fn uncertain_packets_and_incomplete_submissions_keep_their_diagnostics() {
    let uncertain = packet(7, 2, "FUTURE_KIND").replace("Player=2 TaskList=", "Player=Unknown TaskList=");
    let initial = base() + &uncertain + &choice("Entities[4]=12")
        + &power("TAG_CHANGE Entity=1 tag=TURN value=2")
        + &chosen("id=7 Player=2 EntitiesCount=1");
    let game = parse(&initial);
    let submission = game.choices.latest_submission.unwrap();
    assert!(!submission.list_complete);
    assert_eq!(submission.correlation.owner_matches, None);
    assert_eq!(submission.correlation.packet_kind, Some("UNKNOWN"));
    assert_eq!(submission.correlation.packet_malformed_records, Some(1));
    assert_eq!(submission.correlation.packet_was_stale, Some(true));
    let broken = parse(&(initial + &chosen("Entities[1]=10")));
    assert!(!broken.choices.latest_submission.unwrap().list_complete);
}
