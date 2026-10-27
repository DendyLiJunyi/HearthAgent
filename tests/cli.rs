use std::process::Command;

#[test]
fn invalid_command_arguments_fail_with_usage_status() {
    for args in [vec!["replay"], vec!["replay", "unused", "--invalid"],
        vec!["watch"], vec!["watch", "unused", "--invalid"]] {
        let output = Command::new(env!("CARGO_BIN_EXE_hearth-agent")).args(&args).output().unwrap();
        assert_eq!(output.status.code(), Some(2), "{args:?}");
        assert!(String::from_utf8(output.stderr).unwrap().contains("Usage:"));
        assert!(output.stdout.is_empty());
    }
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
