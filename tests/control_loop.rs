use hearth_agent::controller::{ControlError, Controller, ExecutionWindow};
use hearth_agent::executor::{ActionExecutor, ExecutionOutcome, RecordingExecutor};
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::*;

fn window(observation: &Observation) -> ExecutionWindow { ExecutionWindow::new(&observation.snapshot, std::time::Duration::from_secs(10)).unwrap() }

fn fixture() -> (Observation, Decision) {
    let observation = Observation {
        snapshot: Snapshot { session_id: "game-1".into(), revision: 5, phase: Phase::OurTurn, complete: true },
        candidates: vec![Candidate { id: "a0".into(), action: Action::EndTurn }],
    };
    let decision = FirstCandidatePolicy::default().decide(&observation).unwrap();
    (observation, decision)
}

#[test]
fn rejects_a_result_when_state_changes_during_inference() {
    let (mut current, decision) = fixture();
    current.snapshot.revision += 1;
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&current, &decision, &window(&current), &mut executor), Err(ControlError::StaleDecision));
    assert!(executor.records.is_empty());
}

#[test]
fn prevents_resending_even_with_a_new_decision_id() {
    let (current, mut decision) = fixture();
    let mut controller = Controller::default();
    let mut executor = RecordingExecutor::default();
    assert_eq!(controller.execute(&current, &decision, &window(&current), &mut executor), Ok(ExecutionOutcome::Recorded));
    decision.decision_id = "another-id".into();
    assert_eq!(controller.execute(&current, &decision, &window(&current), &mut executor), Err(ControlError::AlreadyAttempted));
    assert_eq!(executor.records.len(), 1);
}

struct UncertainExecutor;
impl ActionExecutor for UncertainExecutor {
    fn execute(&mut self, _: &Decision, _: &Candidate) -> Result<ExecutionOutcome, String> {
        Err("timed out after sending input".into())
    }
}

#[test]
fn an_execution_error_does_not_enable_blind_retry() {
    let (current, decision) = fixture();
    let mut controller = Controller::default();
    assert!(matches!(controller.execute(&current, &decision, &window(&current), &mut UncertainExecutor), Err(ControlError::Execution(_))));
    assert_eq!(controller.execute(&current, &decision, &window(&current), &mut UncertainExecutor), Err(ControlError::AlreadyAttempted));
}

#[test]
fn incomplete_state_never_reaches_executor() {
    let (mut current, decision) = fixture();
    current.snapshot.complete = false;
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&current, &decision, &window(&current), &mut executor), Err(ControlError::IncompleteState));
    assert!(executor.records.is_empty());
}

#[test]
fn only_choices_are_allowed_in_choice_phase() {
    let (mut current, decision) = fixture();
    current.snapshot.phase = Phase::Choosing;
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&current, &decision, &window(&current), &mut executor), Err(ControlError::WrongPhase));
    current.candidates[0].action = Action::ChooseOptions { choice_id: 7, entities: vec![42] };
    assert_eq!(Controller::default().execute(&current, &decision, &window(&current), &mut executor), Ok(ExecutionOutcome::Recorded));
}

#[test]
fn cancelled_window_blocks_dispatch_without_consuming_attempt() {
    let (current, decision) = fixture();
    let cancelled = window(&current);
    let stop = cancelled.clone();
    std::thread::spawn(move || stop.cancel()).join().unwrap();
    let mut controller = Controller::default();
    let mut executor = RecordingExecutor::default();
    assert_eq!(controller.execute(&current, &decision, &cancelled, &mut executor), Err(ControlError::Cancelled));
    assert!(executor.records.is_empty());
    assert_eq!(controller.execute(&current, &decision, &window(&current), &mut executor), Ok(ExecutionOutcome::Recorded));
}

#[test]
fn expired_window_blocks_unchanged_state_and_cannot_be_reused_for_another_snapshot() {
    let (mut current, decision) = fixture();
    let expired = ExecutionWindow::new(&current.snapshot, std::time::Duration::from_nanos(1)).unwrap();
    // A deliberately elapsed window tests dispatch rather than timing performance.
    std::thread::sleep(std::time::Duration::from_millis(1));
    let mut executor = RecordingExecutor::default();
    let mut controller = Controller::default();
    assert_eq!(controller.execute(&current, &decision, &expired, &mut executor), Err(ControlError::DeadlineExpired));
    let bound = window(&current);
    current.snapshot.session_id = "another-session".into();
    let new_decision = FirstCandidatePolicy::default().decide(&current).unwrap();
    assert_eq!(controller.execute(&current, &new_decision, &bound, &mut executor), Err(ControlError::StaleDecision));
    assert!(executor.records.is_empty());
}
