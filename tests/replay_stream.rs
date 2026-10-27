//! Prefix-by-prefix equivalence guards live batching, late aliases, and resets.
use hearth_agent::{export::game_json, replay, watch::StreamState};
use std::io::Cursor;

fn power(text: &str) -> String {
    format!("D 00:00:00 GameState.DebugPrintPower() - {text}\r\n")
}

#[test]
fn every_byte_prefix_matches_frozen_offline_replay() {
    let log = power("CREATE_GAME") + &power("GameEntity EntityID=1")
        + &power("Player EntityID=2 PlayerID=1")
        + &power("Player EntityID=3 PlayerID=2")
        + &power("BLOCK_START BlockType=PLAY")
        + &power("FULL_ENTITY - Creating ID=42 CardID=TEST_CARD")
        + &power("tag=CONTROLLER value=1") + &power("tag=ZONE value=PLAY")
        + &power("TAG_CHANGE Entity=测试玩家 tag=RESOURCES value=2")
        + &power("META_DATA - Meta=TARGET Data=0 InfoCount=1")
        + &power("Info[0] = [id=42]")
        + "D 00:00:00 PowerTaskList.DebugPrintPower() - BLOCK_END\r\n"
        + &power("BLOCK_END")
        + "D 00:00:00 GameState.DebugPrintGame() - PlayerID=1, PlayerName=测试玩家\r\n"
        + &power("TAG_CHANGE Entity=42 tag=ZONE value=HAND")
        + &power("CREATE_GAME") + &power("GameEntity EntityID=1")
        + &power("tag=TURN value=1") + &power("BLOCK_END");
    let mut stream = StreamState::default();
    for (index, byte) in log.bytes().enumerate() {
        stream.feed(&[byte]).unwrap();
        let replay = replay::read(Cursor::new(&log.as_bytes()[..=index])).unwrap();
        assert_eq!(stream.game_number, replay.games.len() as u64);
        assert_eq!(stream.game().as_ref().map(game_json), replay.games.last().map(game_json),
            "stream and replay diverged at byte {index}");
    }
}
