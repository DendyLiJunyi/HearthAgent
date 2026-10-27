use hearth_agent::watch::{quote, StreamState, Watcher};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

fn line(s: &str) -> String { format!("D 00:00:00 GameState.DebugPrintPower() - {s}\n") }
fn game(turn: u32) -> String {
    line("CREATE_GAME") + &line("GameEntity EntityID=1")
        + &line(&format!("tag=TURN value={turn}"))
}
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        static SEQ: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!("hearth-watch-{}-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos(), SEQ.fetch_add(1, Ordering::Relaxed)));
        fs::create_dir(&path).unwrap(); Self(path)
    }
    fn session(&self, name: &str) -> PathBuf {
        let path = self.0.join("Logs").join(name); fs::create_dir_all(&path).unwrap(); path.join("Power.log")
    }
}
impl Drop for Temp { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

#[test]
fn partial_lines_and_utf8_are_buffered_across_polls() {
    let mut state = StreamState::default();
    let text = game(1) + &line("TAG_CHANGE Entity=GameEntity tag=NOTE value=测试");
    let split = text.find('测').unwrap() + 1;
    state.feed(&text.as_bytes()[..split]).unwrap();
    assert_eq!(state.game().unwrap().game_tag("NOTE"), None);
    assert!(state.pending_bytes() > 0);
    state.feed(&text.as_bytes()[split..]).unwrap();
    assert_eq!(state.game().unwrap().game_tag("NOTE"), Some("测试"));
    assert_eq!(state.pending_bytes(), 0);
}

#[test]
fn append_updates_once_and_idle_poll_does_not_emit() {
    let tmp = Temp::new(); let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    fs::write(&path, game(1)).unwrap();
    let mut watcher = Watcher::new(&tmp.0);
    let first = watcher.poll().unwrap().unwrap();
    assert!(first.contains("\"TURN\":\"1\""));
    assert!(first.contains("\"complete\":false"));
    assert!(watcher.poll().unwrap().is_none());
    OpenOptions::new().append(true).open(&path).unwrap().write_all(line("TAG_CHANGE Entity=GameEntity tag=TURN value=2").as_bytes()).unwrap();
    assert!(watcher.poll().unwrap().unwrap().contains("\"TURN\":\"2\""));
    assert!(watcher.poll().unwrap().is_none());
}

#[test]
fn newer_session_without_power_invalidates_old_game() {
    let tmp = Temp::new(); let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    fs::write(path, game(5)).unwrap();
    let mut watcher = Watcher::new(&tmp.0); watcher.poll().unwrap();
    tmp.session("Hearthstone_2026_10_27_11_00_00");
    let json = watcher.poll().unwrap().unwrap();
    assert!(json.contains("waiting_for_power_log"));
    assert!(json.contains("\"game\":null"));
    assert!(!json.contains("\"TURN\""));
}

#[test]
fn same_length_replacement_resets_state_instead_of_skipping_new_content() {
    let tmp = Temp::new(); let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    fs::write(&path, game(5)).unwrap(); let mut watcher = Watcher::new(&tmp.0);
    let first = watcher.poll().unwrap().unwrap();
    fs::write(path, game(8)).unwrap();
    let second = watcher.poll().unwrap().unwrap();
    assert!(first.contains("\"generation\":1"));
    assert!(second.contains("\"generation\":2"));
    assert!(second.contains("\"TURN\":\"8\""));
    assert!(second.contains("\"game_number\":1"));
}

#[test]
fn truncation_and_new_game_never_retain_old_entities() {
    let tmp = Temp::new(); let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    fs::write(&path, game(5) + &line("FULL_ENTITY - Creating ID=42 CardID=OLD")).unwrap();
    let mut watcher = Watcher::new(&tmp.0); watcher.poll().unwrap();
    fs::write(&path, "").unwrap();
    assert!(watcher.poll().unwrap().unwrap().contains("\"game\":null"));
    fs::write(path, game(1)).unwrap();
    assert!(!watcher.poll().unwrap().unwrap().contains("OLD"));
    let mut state = StreamState::default(); state.feed((game(5) + &game(1)).as_bytes()).unwrap();
    assert_eq!(state.game_number, 2);
    assert_eq!(state.game().unwrap().game_tag("TURN"), Some("1"));
}

#[test]
fn late_alias_is_reduced_in_original_order_and_names_are_not_exported() {
    let tmp = Temp::new(); let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    let initial = game(1) + &line("Player EntityID=2 PlayerID=1")
        + &line("TAG_CHANGE Entity=SecretName tag=RESOURCES value=2")
        + &line("TAG_CHANGE Entity=2 tag=RESOURCES value=3");
    fs::write(&path, initial).unwrap(); let mut watcher = Watcher::new(&tmp.0);
    assert!(watcher.poll().unwrap().unwrap().contains("\"unresolved_references\":1"));
    OpenOptions::new().append(true).open(path).unwrap().write_all(b"D 00:00:00 GameState.DebugPrintGame() - PlayerID=1, PlayerName=SecretName\n").unwrap();
    let json = watcher.poll().unwrap().unwrap();
    assert!(!json.contains("SecretName"));
    assert!(json.contains("\"RESOURCES\":\"3\""));
    assert!(json.contains("\"unresolved_references\":0"));
}

#[test]
fn unknown_player_alias_remains_unresolved_without_guessing() {
    let mut state = StreamState::default();
    let text = game(1) + &line("Player EntityID=2 PlayerID=1")
        + &line("tag=RESOURCES value=1")
        + &line("TAG_CHANGE Entity=UnmappedName tag=RESOURCES value=9");
    state.feed(text.as_bytes()).unwrap();
    let game = state.game().unwrap();
    assert_eq!(game.unresolved_references, 1);
    assert_eq!(game.entities[&2].tag("RESOURCES"), Some("1"));
}

fn choice(kind: &str, controller: u32) -> String {
    format!("D 00:00:00 GameState.DebugPrintEntityChoices() - id=1 Player=UNKNOWN HUMAN PLAYER TaskList=9 ChoiceType={kind}\nD 00:00:00 GameState.DebugPrintEntityChoices() - Source=GameEntity\nD 00:00:00 GameState.DebugPrintEntityChoices() - Entities[0]=[id=19 player={controller}]\n")
}

#[test]
fn submitted_mulligan_name_repairs_earlier_events_in_live_and_offline_replay() {
    let initial = game(1) + &line("Player EntityID=2 PlayerID=1")
        + &line("TAG_CHANGE Entity=LateName tag=RESOURCES value=7")
        + &line("TAG_CHANGE Entity=2 tag=RESOURCES value=8") + &choice("MULLIGAN", 1);
    let chosen = "D 00:00:00 GameState.DebugPrintEntitiesChosen() - id=1 Player=LateName EntitiesCount=0\n";
    let mut state = StreamState::default(); state.feed(initial.as_bytes()).unwrap();
    assert_eq!(state.game().unwrap().unresolved_references, 1);
    state.feed(chosen.as_bytes()).unwrap();
    let live = state.game().unwrap();
    assert_eq!(live.unresolved_references, 0);
    assert_eq!(live.entities[&2].tag("RESOURCES"), Some("8"));
    let offline = hearth_agent::replay::read(std::io::Cursor::new(initial + chosen)).unwrap();
    assert_eq!(format!("{:?}", live), format!("{:?}", offline.games[0]));
}

#[test]
fn submitted_general_or_unmatched_choice_never_identifies_player() {
    for kind in ["GENERAL", "MULLIGAN"] {
        let mut state = StreamState::default();
        let id = if kind == "GENERAL" { 1 } else { 99 };
        let text = game(1) + &line("Player EntityID=2 PlayerID=1")
            + &choice(kind, 1)
            + &format!("D 00:00:00 GameState.DebugPrintEntitiesChosen() - id={id} Player=LateName EntitiesCount=1\n")
            + &line("TAG_CHANGE Entity=LateName tag=RESOURCES value=7");
        state.feed(text.as_bytes()).unwrap();
        assert_eq!(state.game().unwrap().unresolved_references, 1);
    }
}

#[test]
fn conflicting_mulligan_owners_do_not_resolve_submitted_name() {
    let mut state = StreamState::default();
    let text = game(1) + &line("Player EntityID=2 PlayerID=1") + &line("Player EntityID=3 PlayerID=2")
        + &choice("MULLIGAN", 1) + &choice("MULLIGAN", 2)
        + "D 00:00:00 GameState.DebugPrintEntitiesChosen() - id=1 Player=LateName EntitiesCount=0\n"
        + &line("TAG_CHANGE Entity=LateName tag=RESOURCES value=7");
    state.feed(text.as_bytes()).unwrap();
    assert_eq!(state.game().unwrap().unresolved_references, 1);
}

#[test]
fn invalid_utf8_is_an_error_not_a_fabricated_state() {
    let mut state = StreamState::default();
    assert!(state.feed(b"\xff\n").is_err());
}

#[test]
fn json_escapes_control_characters() {
    assert_eq!(quote("a\"\\\n\u{1}中"), "\"a\\\"\\\\\\n\\u0001中\"");
}

#[test]
fn ignored_record_counts_match_replay_without_exporting_record_contents() {
    let tmp = Temp::new();
    let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    let log = game(1)
        + &line("BLOCK_START BlockType=TRIGGER Entity=PrivatePlayer#123")
        + &line("META_DATA Meta=TARGET Data=0 InfoCount=1")
        + &line("Info[0] = PrivatePlayer#123")
        + &line("BLOCK_END")
        + &line("PrivatePlayer#123 unrecognized record")
        + "D 00:00:00 PowerTaskList.DebugPrintPower() - BLOCK_END\n"
        + &line("TAG_CHANGE Entity=GameEntity");
    fs::write(&path, &log).unwrap();
    let replay = hearth_agent::replay::read(std::io::Cursor::new(&log)).unwrap();
    let mut stream = StreamState::default();
    for chunk in log.as_bytes().chunks(7) { stream.feed(chunk).unwrap(); }
    let live = stream.game().unwrap();
    assert_eq!(live.ignored_power_record_types, replay.games[0].ignored_power_record_types);
    assert_eq!(live.ignored_power_records, 5);
    assert_eq!(live.ignored_power_record_types.values().sum::<usize>(), 5);
    assert_eq!(live.malformed_records, 1);
    let json = Watcher::new(&tmp.0).poll().unwrap().unwrap();
    assert!(json.contains("\"ignored_power_record_types\":{\"BLOCK_END\":1,\"BLOCK_START\":1,\"INFO\":1,\"META_DATA\":1,\"OTHER\":1}"));
    assert!(!json.contains("PrivatePlayer"));
    stream.feed(game(2).as_bytes()).unwrap();
    assert!(stream.game().unwrap().ignored_power_record_types.is_empty());
}

#[test]
fn option_only_append_emits_and_state_update_marks_options_stale() {
    let tmp = Temp::new();
    let path = tmp.session("Hearthstone_2026_10_27_10_00_00");
    fs::write(&path, game(1)).unwrap();
    let mut watcher = Watcher::new(&tmp.0);
    assert!(watcher.poll().unwrap().unwrap().contains("\"latest\":null"));
    let options = "D 0 GameState.DebugPrintOptions() - id=7\nD 0 GameState.DebugPrintOptions() - option 0 type=END_TURN mainEntity= error=NONE errorParam=\n";
    OpenOptions::new().append(true).open(&path).unwrap().write_all(options.as_bytes()).unwrap();
    let snapshot = watcher.poll().unwrap().unwrap();
    assert!(snapshot.contains("\"stale\":false"));
    assert!(snapshot.contains("\"kind\":\"END_TURN\""));
    assert!(watcher.poll().unwrap().is_none());
    OpenOptions::new().append(true).open(&path).unwrap()
        .write_all(line("TAG_CHANGE Entity=GameEntity tag=TURN value=2").as_bytes()).unwrap();
    assert!(watcher.poll().unwrap().unwrap().contains("\"stale\":true"));
    fs::write(&path, game(3)).unwrap();
    assert!(watcher.poll().unwrap().unwrap().contains("\"latest\":null"));
}
