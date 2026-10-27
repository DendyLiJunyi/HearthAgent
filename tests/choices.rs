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
