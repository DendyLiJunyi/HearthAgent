use hearth_agent::diagnostics::{inspect, summarize_power};
use std::fs;
use std::io::Cursor;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

struct TempDirectory(PathBuf);
impl TempDirectory {
    fn new() -> Self {
        static SEQ: AtomicUsize = AtomicUsize::new(0);
        let root = std::env::temp_dir().join(format!("hearth-agent-inspect-{}-{}-{}",
            std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos(),
            SEQ.fetch_add(1, Ordering::Relaxed)));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for TempDirectory {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}

#[test]
fn newer_menu_session_does_not_reuse_an_older_battle_log() {
    let root = TempDirectory::new();
    let old = root.0.join("Logs/Hearthstone_2026_10_26_23_59_59");
    let new = root.0.join("Logs/Hearthstone_2026_10_27_00_07_53");
    fs::create_dir_all(&old).unwrap();
    fs::create_dir_all(&new).unwrap();
    fs::create_dir_all(root.0.join("Logs/Hearthstone_unrelated")).unwrap();
    fs::write(old.join("Power.log"), "CREATE_GAME\nFULL_ENTITY\n").unwrap();
    fs::write(new.join("LoadingScreen.log"), "D prevMode=PACKOPENING currMode=HUB\n").unwrap();
    let report = inspect(&root.0).unwrap();
    assert_eq!(report.latest_session.as_ref(), Some(&new));
    assert_eq!(report.scene.as_deref(), Some("HUB"));
    assert!(report.power.is_none());
}

#[test]
fn summary_is_explicitly_marker_counts_not_reconstructed_state() {
    let summary = summarize_power(Cursor::new("D CREATE_GAME\nD FULL_ENTITY\nD TAG_CHANGE\nD BLOCK_START\n")).unwrap();
    assert_eq!((summary.lines, summary.create_game, summary.full_entity, summary.tag_change, summary.block_start), (4,1,1,1,1));
}

#[test]
fn no_logs_does_not_mean_a_complete_empty_board() {
    let root = TempDirectory::new();
    let report = inspect(&root.0).unwrap();
    assert!(report.latest_session.is_none());
    assert!(report.power.is_none());
}
