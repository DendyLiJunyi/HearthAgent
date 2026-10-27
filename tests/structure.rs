use hearth_agent::{replay, watch::StreamState};
use std::io::Cursor;

fn line(text: &str) -> String {
    format!("D 00:00:00 GameState.DebugPrintPower() - {text}\n")
}

fn parse(records: &[&str]) -> replay::Game {
    let log = line("CREATE_GAME") + &records.iter().map(|s| line(s)).collect::<String>();
    replay::read(Cursor::new(log)).unwrap().games.remove(0)
}

#[test]
fn nested_blocks_and_sub_spells_require_matching_boundaries() {
    let game = parse(&["BLOCK_START BlockType=PLAY", "SUB_SPELL_START - Source=0",
        "BLOCK_START BlockType=TRIGGER", "BLOCK_END", "SUB_SPELL_END", "BLOCK_END"]);
    assert!(game.structure.closed());
    assert_eq!(game.structure.max_depth, 3);
    assert_eq!(game.structure.blocks_completed, 2);
    assert_eq!(game.structure.sub_spells_completed, 1);
    let broken = parse(&["BLOCK_START BlockType=PLAY", "SUB_SPELL_START - Source=0",
        "BLOCK_END", "SUB_SPELL_END", "BLOCK_END"]);
    assert_eq!(broken.structure.errors, 1);
    assert_eq!(broken.structure.error_types["unmatched_block_end"], 1);
    assert_eq!(broken.structure.first_error_power_sequence, Some(4));
    assert_eq!(broken.structure.open_blocks(), 0);
    assert!(!broken.structure.closed());
    assert!(!parse(&["BLOCK_END"]).structure.closed());
    assert!(!parse(&["BLOCK_START", "BLOCK_END"]).structure.closed());
    assert!(!parse(&["SUB_SPELL_START", "SUB_SPELL_END"]).structure.closed());
}

#[test]
fn metadata_requires_exact_contiguous_indices_and_nonempty_values() {
    let game = parse(&["META_DATA - Meta=TARGET Data=0 InfoCount=2", "Info[0] = 12", "Info[1] = 13"]);
    assert!(game.structure.closed());
    assert_eq!(game.structure.metadata_entries, 2);
    for records in [
        vec!["META_DATA - InfoCount=2", "Info[1] = 12"],
        vec!["META_DATA - InfoCount=1", "Info[0] ="],
        vec!["META_DATA - InfoCount=1", "Info[0] = 12", "Info[0] = 12"],
        vec!["META_DATA - InfoCount=2", "Info[0] = 12", "TAG_CHANGE Entity=1 tag=TURN value=2"],
        vec!["META_DATA - InfoCount=-1"],
        vec!["META_DATA - InfoCount=4294967296"],
        vec!["Info[0] = 12"],
    ] {
        let broken = parse(&records);
        assert!(broken.structure.errors > 0, "{records:?}");
        assert!(!broken.structure.closed());
    }
    assert!(parse(&["META_DATA - InfoCount=0"]).structure.closed());
}

#[test]
fn unfinished_prefix_is_pending_and_finishes_only_after_complete_lines() {
    let mut stream = StreamState::default();
    stream.feed((line("CREATE_GAME") + &line("BLOCK_START BlockType=PLAY")
        + &line("META_DATA - InfoCount=1")).as_bytes()).unwrap();
    let pending = stream.game().unwrap();
    assert_eq!(pending.structure.open_blocks(), 1);
    assert_eq!(pending.structure.pending_metadata_entries(), 1);
    assert_eq!(pending.structure.errors, 0);
    assert!(!pending.structure.closed());
    let tail = line("Info[0] = 12") + &line("BLOCK_END");
    stream.feed(&tail.as_bytes()[..tail.len() - 1]).unwrap();
    assert!(!stream.game().unwrap().structure.closed());
    stream.feed(b"\n").unwrap();
    assert!(stream.game().unwrap().structure.closed());
}

#[test]
fn authoritative_stream_only_and_new_games_reset_diagnostics() {
    let log = line("CREATE_GAME") + &line("BLOCK_START BlockType=PLAY")
        + &line("META_DATA - InfoCount=1")
        + "D 00:00:00 PowerTaskList.DebugPrintPower() - BLOCK_END\n"
        + &line("Info[0] = 12") + &line("BLOCK_END")
        + &line("BLOCK_END") + &line("CREATE_GAME");
    let replay = replay::read(Cursor::new(&log)).unwrap();
    assert_eq!(replay.games[0].structure.errors, 1);
    assert_eq!(replay.games[0].structure.metadata_entries, 1);
    assert!(replay.games[1].structure.closed());
    let mut stream = StreamState::default();
    for chunk in log.as_bytes().chunks(11) { stream.feed(chunk).unwrap(); }
    assert_eq!(stream.game().unwrap().structure, replay.games[1].structure);
}
