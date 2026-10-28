//! One bounded control step with fresh observations and a small diagnostic trace.
//! No log projection is promoted to a complete observation here.
use std::collections::BTreeMap;
use std::time::{Duration, Instant};
use serde::Serialize;
use crate::controller::{ControlError, Controller, ExecutionWindow, StopToken};
use crate::executor::{ActionExecutor, ExecutionOutcome};
use crate::policy::PolicyBackend;
use crate::protocol::{Decision, Observation, ObservationSource, Phase};

#[derive(Debug, PartialEq, Eq)]
pub enum StepError {
    Observation(String),
    Policy(String),
    InvalidObservation(&'static str),
    CandidatesChanged,
    RecoveryRequired,
    SequenceExhausted,
    Control(ControlError),
}

impl StepError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Observation(_) => "observation_failed",
            Self::Policy(_) => "policy_failed",
            Self::InvalidObservation(code) => code,
            Self::CandidatesChanged => "candidates_changed_without_revision",
            Self::RecoveryRequired => "recovery_required",
            Self::SequenceExhausted => "step_sequence_exhausted",
            Self::Control(error) => match error {
                ControlError::IncompleteState => "incomplete_state",
                ControlError::InvalidIdentity => "invalid_identity",
                ControlError::InvalidAction => "invalid_action",
                ControlError::StaleDecision => "stale_decision",
                ControlError::WrongPhase => "wrong_phase",
                ControlError::UnknownCandidate => "unknown_candidate",
                ControlError::AmbiguousCandidate => "ambiguous_candidate",
                ControlError::AlreadyAttempted => "already_attempted",
                ControlError::InvalidBudget => "invalid_budget",
                ControlError::DeadlineExpired => "deadline_expired",
                ControlError::Cancelled => "cancelled",
                ControlError::RecoveryRequired => "recovery_required",
                ControlError::Journal(_) => "journal_failed",
                ControlError::Execution(_) => "execution_failed",
            },
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum StepStage { Observe, Infer, Refresh, Dispatch }

#[derive(Debug, Serialize)]
pub struct StageTiming {
    pub stage: StepStage,
    pub elapsed_ms: u128,
}

/// Contains only semantic protocol data and stable error codes, never adapter
/// error strings, raw Power.log text, or model state. Store it as one JSONL row.
#[derive(Debug, Serialize)]
pub struct StepTrace {
    pub protocol_version: u32,
    pub step_id: u64,
    pub initial: Option<Observation>,
    pub refreshed: Option<Observation>,
    pub decision: Option<Decision>,
    pub timings: Vec<StageTiming>,
    pub elapsed_ms: u128,
    pub status: &'static str,
    pub failure_stage: Option<StepStage>,
    pub error_code: Option<&'static str>,
}

pub struct StepResult {
    pub result: Result<ExecutionOutcome, StepError>,
    pub trace: StepTrace,
}

/// Retain one runner across steps to preserve the attempt ledger. A dispatch
/// error/uncertain outcome latches recovery_required; there is no blind retry.
#[derive(Default)]
pub struct StepRunner {
    controller: Controller,
    stop: StopToken,
    sequence: u64,
    recovery_required: bool,
}

impl StepRunner {
    pub fn with_journal(path: impl AsRef<std::path::Path>) -> Result<Self, ControlError> {
        let controller = Controller::with_journal(path)?;
        Ok(Self { recovery_required: controller.recovery_required(), controller, ..Self::default() })
    }

    pub fn stop_token(&self) -> StopToken { self.stop.clone() }

    pub fn step<S: ObservationSource, P: PolicyBackend, E: ActionExecutor>(
        &mut self, source: &mut S, policy: &mut P, executor: &mut E, budget: Duration,
    ) -> StepResult {
        let started = Instant::now();
        let mut stage = StepStage::Observe;
        let mut trace = StepTrace { protocol_version: 1, step_id: self.sequence,
            initial: None, refreshed: None, decision: None, timings: Vec::new(),
            elapsed_ms: 0, status: "rejected", failure_stage: None, error_code: None };
        let result = (|| {
            self.sequence = self.sequence.checked_add(1).ok_or(StepError::SequenceExhausted)?;
            trace.step_id = self.sequence;
            if self.stop.is_stopped() { return Err(StepError::Control(ControlError::Cancelled)); }
            if self.recovery_required { return Err(StepError::RecoveryRequired); }
            if budget.is_zero() || started.checked_add(budget).is_none() {
                return Err(StepError::Control(ControlError::InvalidBudget));
            }
            let before = Instant::now();
            let initial = source.observe();
            trace.timings.push(StageTiming { stage, elapsed_ms: before.elapsed().as_millis() });
            let initial = initial.map_err(StepError::Observation)?;
            validate(&initial)?;
            trace.initial = Some(initial.clone());
            let window = ExecutionWindow::for_run(&initial.snapshot, budget, started, self.stop.clone())
                .map_err(StepError::Control)?;
            window.check_current(&initial.snapshot).map_err(StepError::Control)?;

            stage = StepStage::Infer;
            let before = Instant::now();
            let decision = policy.decide(&initial);
            trace.timings.push(StageTiming { stage, elapsed_ms: before.elapsed().as_millis() });
            // A late or stopped run cannot proceed, even if the policy returned success.
            window.check_current(&initial.snapshot).map_err(StepError::Control)?;
            let decision = decision.map_err(StepError::Policy)?;
            if decision.decision_id.is_empty() || decision.decision_id.len() > 128
                || decision.session_id != initial.snapshot.session_id
                || decision.revision != initial.snapshot.revision {
                return Err(StepError::Control(ControlError::StaleDecision));
            }
            if !initial.candidates.iter().any(|candidate| candidate.id == decision.candidate_id) {
                return Err(StepError::Control(ControlError::UnknownCandidate));
            }
            trace.decision = Some(decision.clone());

            stage = StepStage::Refresh;
            let before = Instant::now();
            let refreshed = source.observe();
            trace.timings.push(StageTiming { stage, elapsed_ms: before.elapsed().as_millis() });
            let refreshed = refreshed.map_err(StepError::Observation)?;
            validate(&refreshed)?;
            trace.refreshed = Some(refreshed.clone());
            window.check_current(&refreshed.snapshot).map_err(StepError::Control)?;
            let candidates = |observation: &Observation| observation.candidates.iter()
                .map(|candidate| (candidate.id.clone(), candidate.action.clone())).collect::<BTreeMap<_, _>>();
            if candidates(&initial) != candidates(&refreshed) { return Err(StepError::CandidatesChanged); }

            stage = StepStage::Dispatch;
            let before = Instant::now();
            let outcome = self.controller.execute(&refreshed, &decision, &window, executor);
            trace.timings.push(StageTiming { stage, elapsed_ms: before.elapsed().as_millis() });
            if self.controller.recovery_required() {
                self.recovery_required = true;
            }
            outcome.map_err(StepError::Control)
        })();
        trace.elapsed_ms = started.elapsed().as_millis();
        match &result {
            Ok(outcome) => trace.status = match outcome {
                ExecutionOutcome::Recorded => "recorded",
                ExecutionOutcome::Confirmed => "confirmed_by_adapter",
                ExecutionOutcome::Uncertain(_) => "uncertain",
            },
            Err(error) => {
                trace.failure_stage = Some(stage); trace.error_code = Some(error.code());
                if matches!(error, StepError::Control(ControlError::Execution(_) | ControlError::Journal(_))) {
                    trace.status = "failed_requires_review";
                }
            }
        }
        StepResult { result, trace }
    }
}

fn validate(observation: &Observation) -> Result<(), StepError> {
    if !observation.snapshot.complete { return Err(StepError::Control(ControlError::IncompleteState)); }
    if observation.snapshot.session_id.is_empty() || observation.snapshot.session_id.len() > 128 {
        return Err(StepError::InvalidObservation("invalid_session_id"));
    }
    if !matches!(observation.snapshot.phase, Phase::OurTurn | Phase::Choosing | Phase::Mulligan) {
        return Err(StepError::Control(ControlError::WrongPhase));
    }
    if observation.candidates.is_empty() || observation.candidates.len() > 1024 {
        return Err(StepError::InvalidObservation("invalid_candidate_count"));
    }
    let mut seen = std::collections::HashSet::new();
    for candidate in &observation.candidates {
        if candidate.id.is_empty() || candidate.id.len() > 128 || !seen.insert(&candidate.id) {
            return Err(StepError::InvalidObservation("invalid_candidate_identity"));
        }
        if !candidate.action.allowed_in(&observation.snapshot.phase) { return Err(StepError::Control(ControlError::WrongPhase)); }
        if !candidate.action.well_formed() { return Err(StepError::Control(ControlError::InvalidAction)); }
    }
    Ok(())
}
