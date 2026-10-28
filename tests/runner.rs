use std::collections::VecDeque;
use std::time::Duration;
use hearth_agent::controller::{ControlError, StopToken};
use hearth_agent::executor::{ActionExecutor, ExecutionOutcome, RecordingExecutor};
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::*;
use hearth_agent::runner::{StepError, StepRunner, StepStage};

const BUDGET: Duration = Duration::from_secs(10);

fn observation() -> Observation {
    Observation { snapshot: Snapshot { session_id: "synthetic-runner".into(), revision: 1,
        phase: Phase::OurTurn, complete: true },
        candidates: vec![Candidate { id: "end".into(), action: Action::EndTurn }] }
}

struct Source {
    rows: VecDeque<Result<Observation, String>>,
    calls: usize,
    stop_on: Option<(usize, StopToken)>,
    delay: Duration,
}

impl Source {
    fn new(rows: Vec<Observation>) -> Self {
        Self { rows: rows.into_iter().map(Ok).collect(), calls: 0, stop_on: None, delay: Duration::ZERO }
    }
}

impl ObservationSource for Source {
    fn observe(&mut self) -> Result<Observation, String> {
        self.calls += 1;
        if let Some((call, token)) = &self.stop_on {
            if *call == self.calls { token.stop(); }
        }
        if !self.delay.is_zero() { std::thread::sleep(self.delay); }
        self.rows.pop_front().expect("runner made an unexpected observation request")
    }
}

#[derive(Default)]
struct Policy {
    baseline: FirstCandidatePolicy,
    calls: usize,
    stop: Option<StopToken>,
    error: bool,
}

impl PolicyBackend for Policy {
    fn decide(&mut self, input: &Observation) -> Result<Decision, String> {
        self.calls += 1;
        if let Some(stop) = &self.stop { stop.stop(); }
        if self.error { return Err("private upstream error text".into()); }
        self.baseline.decide(input)
    }
}

#[test]
fn step_reobserves_and_records_a_bounded_trace() {
    let input = observation();
    let mut source = Source::new(vec![input.clone(), input]);
    let mut policy = Policy::default();
    let mut executor = RecordingExecutor::default();
    let step = StepRunner::default().step(&mut source, &mut policy, &mut executor, BUDGET);
    assert_eq!(step.result, Ok(ExecutionOutcome::Recorded));
    assert_eq!((source.calls, policy.calls, executor.records.len()), (2, 1, 1));
    assert_eq!(step.trace.status, "recorded");
    assert_eq!(step.trace.step_id, 1);
    assert!(step.trace.initial.is_some() && step.trace.refreshed.is_some());
    assert_eq!(step.trace.timings.iter().map(|event| event.stage).collect::<Vec<_>>(),
        [StepStage::Observe, StepStage::Infer, StepStage::Refresh, StepStage::Dispatch]);
    let json: serde_json::Value = serde_json::from_str(&serde_json::to_string(&step.trace).unwrap()).unwrap();
    assert_eq!(json["protocol_version"], 1);
    assert_eq!(json["error_code"], serde_json::Value::Null);
}

#[test]
fn changed_revision_or_rebound_candidate_never_dispatches() {
    for changed_kind in ["revision", "session", "action", "removed", "added"] {
        let initial = observation();
        let mut changed = initial.clone();
        match changed_kind {
            "revision" => changed.snapshot.revision += 1,
            "session" => changed.snapshot.session_id = "new-session".into(),
            "action" => changed.candidates[0].action = Action::Attack { source: 1, target: 2 },
            "removed" => changed.candidates[0].id = "different".into(),
            "added" => changed.candidates.push(Candidate { id: "extra".into(), action: Action::EndTurn }),
            _ => unreachable!(),
        }
        let mut executor = RecordingExecutor::default();
        let result = StepRunner::default().step(&mut Source::new(vec![initial, changed]),
            &mut Policy::default(), &mut executor, BUDGET);
        assert!(matches!(result.result, Err(StepError::CandidatesChanged | StepError::Control(ControlError::StaleDecision))));
        assert_eq!(result.trace.failure_stage, Some(StepStage::Refresh));
        assert!(executor.records.is_empty());
    }
}

#[test]
fn equivalent_candidate_reordering_is_allowed() {
    let mut input = observation();
    input.candidates.push(Candidate { id: "attack".into(), action: Action::Attack { source: 10, target: 20 } });
    let mut reordered = input.clone();
    reordered.candidates.reverse();
    let mut executor = RecordingExecutor::default();
    let step = StepRunner::default().step(&mut Source::new(vec![input, reordered]),
        &mut Policy::default(), &mut executor, BUDGET);
    assert_eq!(step.result, Ok(ExecutionOutcome::Recorded));
    assert_eq!(executor.records[0].1.action, Action::EndTurn);
}

#[test]
fn invalid_observations_never_reach_policy() {
    for invalid_kind in ["incomplete", "phase", "empty", "duplicate", "identity", "wrong_action", "session"] {
        let mut input = observation();
        match invalid_kind {
            "incomplete" => input.snapshot.complete = false,
            "phase" => input.snapshot.phase = Phase::Animating,
            "empty" => input.candidates.clear(),
            "duplicate" => input.candidates.push(input.candidates[0].clone()),
            "identity" => input.candidates[0].id.clear(),
            "wrong_action" => input.candidates[0].action = Action::ChooseOptions { choice_id: 7, entities: vec![42] },
            "session" => input.snapshot.session_id.clear(),
            _ => unreachable!(),
        }
        let mut policy = Policy::default();
        let mut executor = RecordingExecutor::default();
        let step = StepRunner::default().step(&mut Source::new(vec![input]), &mut policy, &mut executor, BUDGET);
        assert!(step.result.is_err(), "{invalid_kind}");
        assert_eq!(policy.calls, 0);
        assert!(executor.records.is_empty());
    }
}

#[test]
fn cancellation_before_observation_during_policy_or_during_refresh_is_latched() {
    for stop_at in 0..3 {
        let input = observation();
        let mut source = Source::new(vec![input.clone(), input]);
        let mut runner = StepRunner::default();
        let token = runner.stop_token();
        let mut policy = Policy::default();
        match stop_at {
            0 => token.stop(),
            1 => policy.stop = Some(token),
            2 => source.stop_on = Some((2, token)),
            _ => unreachable!(),
        }
        let mut executor = RecordingExecutor::default();
        for _ in 0..2 {
            let result = runner.step(&mut source, &mut policy, &mut executor, BUDGET);
            assert_eq!(result.result, Err(StepError::Control(ControlError::Cancelled)));
        }
        assert_eq!(source.calls, stop_at);
        assert!(executor.records.is_empty());
    }
}

#[test]
fn initial_observation_time_counts_towards_budget() {
    let mut source = Source::new(vec![observation()]);
    source.delay = Duration::from_millis(2);
    let mut policy = Policy::default();
    let step = StepRunner::default().step(&mut source, &mut policy, &mut RecordingExecutor::default(), Duration::from_nanos(1));
    assert_eq!(step.result, Err(StepError::Control(ControlError::DeadlineExpired)));
    assert_eq!(policy.calls, 0);
}

#[test]
fn failed_refresh_and_failed_policy_do_not_dispatch_or_leak_errors_into_trace() {
    for policy_failure in [false, true] {
        let mut source = Source::new(vec![observation()]);
        source.rows.push_back(Err("private adapter error text".into()));
        let mut policy = Policy { error: policy_failure, ..Policy::default() };
        let mut executor = RecordingExecutor::default();
        let result = StepRunner::default().step(&mut source, &mut policy, &mut executor, BUDGET);
        assert!(result.result.is_err());
        assert_eq!(result.trace.failure_stage, Some(if policy_failure { StepStage::Infer } else { StepStage::Refresh }));
        assert!(!serde_json::to_string(&result.trace).unwrap().contains("private"));
        assert!(executor.records.is_empty());
    }
}

struct UncertainExecutor { fail: bool, calls: usize }
impl ActionExecutor for UncertainExecutor {
    fn execute(&mut self, _: &Decision, _: &Candidate) -> Result<ExecutionOutcome, String> {
        self.calls += 1;
        if self.fail { Err("possibly sent input".into()) }
        else { Ok(ExecutionOutcome::Uncertain("possibly sent input".into())) }
    }
}

#[test]
fn uncertain_or_failed_dispatch_requires_recovery_even_if_the_next_state_changes() {
    for fail in [false, true] {
        let input = observation();
        let mut source = Source::new(vec![input.clone(), input]);
        let mut runner = StepRunner::default();
        let mut policy = Policy::default();
        let mut executor = UncertainExecutor { fail, calls: 0 };
        let first = runner.step(&mut source, &mut policy, &mut executor, BUDGET);
        assert_eq!(first.trace.status, if fail { "failed_requires_review" } else { "uncertain" });
        let mut next = observation();
        next.snapshot.revision += 1;
        source.rows.push_back(Ok(next));
        let second = runner.step(&mut source, &mut policy, &mut executor, BUDGET);
        assert_eq!(second.result, Err(StepError::RecoveryRequired));
        assert_eq!((executor.calls, source.calls), (1, 2));
    }
}

#[test]
fn attempt_ledger_survives_successive_steps_and_rejects_repeat_state() {
    let mut runner = StepRunner::default();
    let input = observation();
    let mut source = Source::new(vec![input; 4]);
    let mut executor = RecordingExecutor::default();
    let mut policy = Policy::default();
    assert!(runner.step(&mut source, &mut policy, &mut executor, BUDGET).result.is_ok());
    let repeated = runner.step(&mut source, &mut policy, &mut executor, BUDGET);
    assert_eq!(repeated.result, Err(StepError::Control(ControlError::AlreadyAttempted)));
    assert_eq!(repeated.trace.step_id, 2);
    assert_eq!(executor.records.len(), 1);
}

#[test]
fn invalid_budget_is_rejected_without_observing() {
    let mut source = Source::new(vec![]);
    let mut policy = Policy::default();
    let result = StepRunner::default().step(&mut source, &mut policy, &mut RecordingExecutor::default(), Duration::ZERO);
    assert_eq!(result.result, Err(StepError::Control(ControlError::InvalidBudget)));
    assert_eq!((source.calls, policy.calls), (0, 0));
}
