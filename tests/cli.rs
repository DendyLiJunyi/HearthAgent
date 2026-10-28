use std::process::Command;

#[test]
fn invalid_command_arguments_fail_with_usage_status() {
    for args in [vec!["replay"], vec!["replay", "unused", "--invalid"],
        vec!["watch"], vec!["watch", "unused", "--invalid"], vec!["review"], vec!["review", "unused", "--invalid"],
        vec!["deck", "code", "extra"], vec!["advise"], vec!["advise", "unused", "url", "extra"], vec!["loop-demo", "extra"]] {
        let output = Command::new(env!("CARGO_BIN_EXE_hearth-agent")).args(&args).output().unwrap();
        assert_eq!(output.status.code(), Some(2), "{args:?}");
        assert!(String::from_utf8(output.stderr).unwrap().contains("Usage:"));
        assert!(output.stdout.is_empty());
    }
}

#[test]
fn loop_demo_exercises_refresh_cancellation_and_deduplication_without_game_input() {
    let output = Command::new(env!("CARGO_BIN_EXE_hearth-agent")).arg("loop-demo").output().unwrap();
    assert!(output.status.success());
    let rows: Vec<serde_json::Value> = String::from_utf8(output.stdout).unwrap().lines()
        .map(|line| serde_json::from_str(line).unwrap()).collect();
    assert_eq!(rows.len(), 5);
    assert_eq!(rows[0]["trace"]["status"], "recorded");
    for (row, error) in rows[1..].iter().zip(["stale_decision", "candidates_changed_without_revision", "cancelled", "already_attempted"]) {
        assert_eq!(row["trace"]["error_code"], error);
    }
    assert!(rows.iter().all(|row| row["game_input_sent"] == false));
    assert!(rows[1..4].iter().all(|row| row["recorded_actions"] == 0));
    assert_eq!(rows[4]["recorded_actions"], 1);
}

#[test]
fn json_replay_of_missing_file_fails_without_publishing_a_snapshot() {
    let missing = std::env::temp_dir().join(format!("hearth-agent-missing-{}-{}.log", std::process::id(),
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
    let output = Command::new(env!("CARGO_BIN_EXE_hearth-agent"))
        .arg("replay").arg(missing).arg("--json").output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8(output.stderr).unwrap().contains("Replay failed:"));
}
