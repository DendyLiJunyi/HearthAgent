use std::fs;
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::sync::atomic::{AtomicU64, Ordering};
use hearth_agent::controller::{ControlError, Controller, ExecutionWindow};
use hearth_agent::executor::{ActionExecutor, ExecutionOutcome, RecordingExecutor};
use hearth_agent::protocol::*;

struct TemporaryJournal(PathBuf);
impl TemporaryJournal {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!("hearth-agent-journal-{}-{}-{}.jsonl", std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
            NEXT.fetch_add(1, Ordering::Relaxed))))
    }
}
impl Drop for TemporaryJournal {
    fn drop(&mut self) { let _ = fs::remove_file(&self.0); }
}

fn input(revision: u64) -> (Observation, Decision, ExecutionWindow) {
    let observation = Observation {
        snapshot: Snapshot { session_id: "synthetic-journal".into(), revision, phase: Phase::OurTurn, complete: true },
        candidates: vec![Candidate { id: "end".into(), action: Action::EndTurn }],
    };
    let decision = Decision { session_id: observation.snapshot.session_id.clone(), revision,
        decision_id: format!("d{revision}"), candidate_id: "end".into() };
    let window = ExecutionWindow::new(&observation.snapshot, Duration::from_secs(10)).unwrap();
    (observation, decision, window)
}

#[test]
fn completed_attempts_are_restored_and_deduplicated_after_reopening() {
    let path = TemporaryJournal::new();
    let (observation, mut decision, window) = input(1);
    let mut executor = RecordingExecutor::default();
    {
        let mut controller = Controller::with_journal(&path.0).unwrap();
        assert_eq!(controller.execute(&observation, &decision, &window, &mut executor), Ok(ExecutionOutcome::Recorded));
    }
    let contents = fs::read_to_string(&path.0).unwrap();
    let rows: Vec<serde_json::Value> = contents.lines().map(|line| serde_json::from_str(line).unwrap()).collect();
    assert_eq!(rows.len(), 2);
    assert!(rows[0]["outcome"].is_null());
    assert_eq!(rows[1]["outcome"], "recorded");
    assert_eq!(rows[1]["sequence"], 2);
    let mut restored = Controller::with_journal(&path.0).unwrap();
    assert!(!restored.recovery_required());
    decision.decision_id = "renamed-decision".into();
    assert_eq!(restored.execute(&observation, &decision, &window, &mut executor), Err(ControlError::AlreadyAttempted));
    let (next, decision, window) = input(2);
    assert_eq!(restored.execute(&next, &decision, &window, &mut executor), Ok(ExecutionOutcome::Recorded));
    assert_eq!(executor.records.len(), 2);
}

#[test]
fn second_writer_is_refused_and_lock_is_released_on_drop() {
    let path = TemporaryJournal::new();
    let controller = Controller::with_journal(&path.0).unwrap();
    assert!(matches!(Controller::with_journal(&path.0), Err(ControlError::Journal(_))));
    drop(controller);
    assert!(Controller::with_journal(&path.0).is_ok());
}

struct Unknown { fail: bool }
impl ActionExecutor for Unknown {
    fn execute(&mut self, _: &Decision, _: &Candidate) -> Result<ExecutionOutcome, String> {
        if self.fail { Err("private execution error".into()) }
        else { Ok(ExecutionOutcome::Uncertain("private execution detail".into())) }
    }
}

#[test]
fn uncertainty_or_execution_error_survives_restart_without_exporting_error_text() {
    for fail in [false, true] {
        let path = TemporaryJournal::new();
        let (observation, decision, window) = input(1);
        {
            let mut controller = Controller::with_journal(&path.0).unwrap();
            let _ = controller.execute(&observation, &decision, &window, &mut Unknown { fail });
            assert!(controller.recovery_required());
        }
        assert!(!fs::read_to_string(&path.0).unwrap().contains("private"));
        let mut restored = Controller::with_journal(&path.0).unwrap();
        assert!(restored.recovery_required());
        let (next, decision, window) = input(2);
        let mut executor = RecordingExecutor::default();
        assert_eq!(restored.execute(&next, &decision, &window, &mut executor), Err(ControlError::RecoveryRequired));
        assert!(executor.records.is_empty());
    }
}

fn record(sequence: u64, outcome: serde_json::Value) -> serde_json::Value {
    serde_json::json!({"protocol_version": 1, "sequence": sequence, "outcome": outcome,
        "attempt": {"session_id": "synthetic-journal", "revision": 1, "decision_id": "d1", "candidate_id": "end"}})
}

#[test]
fn intent_without_outcome_blocks_new_states_after_crash() {
    let path = TemporaryJournal::new();
    fs::write(&path.0, format!("{}\n", record(1, serde_json::Value::Null))).unwrap();
    let mut controller = Controller::with_journal(&path.0).unwrap();
    let (next, decision, window) = input(2);
    let mut executor = RecordingExecutor::default();
    assert!(controller.recovery_required());
    assert_eq!(controller.execute(&next, &decision, &window, &mut executor), Err(ControlError::RecoveryRequired));
    assert!(executor.records.is_empty());
}

#[test]
fn corrupt_truncated_reordered_or_unmatched_journals_are_never_silently_repaired() {
    let intent = record(1, serde_json::Value::Null);
    let mut wrong_identity = record(2, serde_json::json!("recorded"));
    wrong_identity["attempt"]["candidate_id"] = serde_json::json!("different");
    let cases = [
        "{broken}\n".to_string(), intent.to_string(),
        format!("{}\n", record(2, serde_json::Value::Null)),
        format!("{}\n", record(1, serde_json::json!("recorded"))),
        format!("{intent}\n{wrong_identity}\n"),
        format!("{intent}\n{}\n", record(2, serde_json::Value::Null)),
        format!("{intent}\n{}\n{}\n", record(2, serde_json::json!("recorded")), record(3, serde_json::json!("recorded"))),
        format!("{}\n", " ".repeat(5000)),
    ];
    for contents in cases {
        let path = TemporaryJournal::new();
        fs::write(&path.0, &contents).unwrap();
        assert!(matches!(Controller::with_journal(&path.0), Err(ControlError::Journal(_))));
        assert_eq!(fs::read_to_string(&path.0).unwrap(), contents);
    }
}

#[test]
fn confirmed_non_dispatch_remains_deduplicated_without_recovery_latch() {
    let path = TemporaryJournal::new();
    fs::write(&path.0, format!("{}\n{}\n", record(1, serde_json::Value::Null),
        record(2, serde_json::json!("not_dispatched")))).unwrap();
    let mut controller = Controller::with_journal(&path.0).unwrap();
    assert!(!controller.recovery_required());
    let (current, decision, window) = input(1);
    assert_eq!(controller.execute(&current, &decision, &window, &mut RecordingExecutor::default()), Err(ControlError::AlreadyAttempted));
}

#[test]
fn restart_rejects_older_unattempted_revision_in_same_session() {
    let path = TemporaryJournal::new();
    let (latest, decision, window) = input(10);
    {
        let mut controller = Controller::with_journal(&path.0).unwrap();
        controller.execute(&latest, &decision, &window, &mut RecordingExecutor::default()).unwrap();
    }
    let mut restored = Controller::with_journal(&path.0).unwrap();
    let (older, decision, window) = input(5);
    let mut executor = RecordingExecutor::default();
    assert_eq!(restored.execute(&older, &decision, &window, &mut executor), Err(ControlError::StaleDecision));
    assert!(executor.records.is_empty());
}
