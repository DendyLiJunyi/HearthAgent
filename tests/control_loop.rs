use hearth_agent::controller::{ControlError, Controller};
use hearth_agent::executor::{ActionExecutor, ExecutionOutcome, RecordingExecutor};
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::*;

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
    assert_eq!(Controller::default().execute(&current, &decision, &mut executor), Err(ControlError::StaleDecision));
    assert!(executor.records.is_empty());
}

#[test]
fn prevents_resending_even_with_a_new_decision_id() {
    let (current, mut decision) = fixture();
    let mut controller = Controller::default();
    let mut executor = RecordingExecutor::default();
    assert_eq!(controller.execute(&current, &decision, &mut executor), Ok(ExecutionOutcome::Recorded));
    decision.decision_id = "another-id".into();
    assert_eq!(controller.execute(&current, &decision, &mut executor), Err(ControlError::AlreadyAttempted));
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
    assert!(matches!(controller.execute(&current, &decision, &mut UncertainExecutor), Err(ControlError::Execution(_))));
    assert_eq!(controller.execute(&current, &decision, &mut UncertainExecutor), Err(ControlError::AlreadyAttempted));
}

#[test]
fn incomplete_state_never_reaches_executor() {
    let (mut current, decision) = fixture();
    current.snapshot.complete = false;
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&current, &decision, &mut executor), Err(ControlError::IncompleteState));
    assert!(executor.records.is_empty());
}

#[test]
fn only_choices_are_allowed_in_choice_phase() {
    let (mut current, decision) = fixture();
    current.snapshot.phase = Phase::Choosing;
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&current, &decision, &mut executor), Err(ControlError::WrongPhase));
    current.candidates[0].action = Action::ChooseOption { entity: 42 };
    assert_eq!(Controller::default().execute(&current, &decision, &mut executor), Ok(ExecutionOutcome::Recorded));
}
