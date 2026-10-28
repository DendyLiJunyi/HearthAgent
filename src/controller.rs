use std::collections::{HashMap, HashSet};
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use std::time::{Duration, Instant};
use crate::executor::{ActionExecutor, ExecutionOutcome};
use crate::protocol::{Decision, Observation, Snapshot};

#[derive(Debug, PartialEq, Eq)]
pub enum ControlError {
    IncompleteState,
    InvalidIdentity,
    InvalidAction,
    StaleDecision,
    WrongPhase,
    UnknownCandidate,
    AmbiguousCandidate,
    AlreadyAttempted,
    InvalidBudget,
    DeadlineExpired,
    Cancelled,
    RecoveryRequired,
    Journal(String),
    Execution(String),
}

/// Shared, one-way stop signal. A stopped run cannot be restarted accidentally
/// by creating another decision window.
#[derive(Clone, Debug, Default)]
pub struct StopToken(Arc<AtomicBool>);

impl StopToken {
    pub fn stop(&self) { self.0.store(true, Ordering::SeqCst); }
    pub fn is_stopped(&self) -> bool { self.0.load(Ordering::SeqCst) }
}

/// Create before inference, then reuse unchanged for dispatch. Clones share an
/// irreversible cancellation flag. This bounds dispatch, not executor completion.
#[derive(Clone, Debug)]
pub struct ExecutionWindow {
    snapshot: Snapshot,
    deadline: Instant,
    stop: StopToken,
}

impl ExecutionWindow {
    pub fn new(snapshot: &Snapshot, budget: Duration) -> Result<Self, ControlError> {
        Self::at(snapshot, budget, Instant::now())
    }

    fn at(snapshot: &Snapshot, budget: Duration, now: Instant) -> Result<Self, ControlError> {
        Self::for_run(snapshot, budget, now, StopToken::default())
    }

    pub(crate) fn for_run(snapshot: &Snapshot, budget: Duration, now: Instant, stop: StopToken) -> Result<Self, ControlError> {
        if budget.is_zero() { return Err(ControlError::InvalidBudget); }
        let deadline = now.checked_add(budget).ok_or(ControlError::InvalidBudget)?;
        Ok(Self { snapshot: snapshot.clone(), deadline, stop })
    }

    pub fn cancel(&self) { self.stop.stop(); }

    pub(crate) fn check_current(&self, snapshot: &Snapshot) -> Result<(), ControlError> {
        self.check(snapshot, Instant::now())
    }

    fn check(&self, snapshot: &Snapshot, now: Instant) -> Result<(), ControlError> {
        if self.stop.is_stopped() { return Err(ControlError::Cancelled); }
        if now >= self.deadline { return Err(ControlError::DeadlineExpired); }
        if &self.snapshot != snapshot { return Err(ControlError::StaleDecision); }
        Ok(())
    }
}

/// Attempt ledger; default is in-memory, with_journal opts into durable records.
/// An unresolved attempt requires independent recovery, not a new revision alone.
#[derive(Default)]
pub struct Controller {
    attempted_decisions: HashSet<(String, String)>,
    attempted_states: HashSet<(String, u64)>,
    highest_attempted_revision: HashMap<String, u64>,
    journal: Option<crate::journal::Journal>,
    recovery_required: bool,
}

impl Controller {
    /// Restore deduplication under an exclusive file lock. Unresolved or uncertain
    /// attempts prevent new dispatch until an independent recovery workflow exists.
    pub fn with_journal(path: impl AsRef<std::path::Path>) -> Result<Self, ControlError> {
        let (journal, recovery) = crate::journal::Journal::open(path.as_ref()).map_err(ControlError::Journal)?;
        let mut controller = Self { journal: Some(journal), recovery_required: recovery.requires_review, ..Self::default() };
        for attempt in recovery.attempts {
            controller.highest_attempted_revision.entry(attempt.session_id.clone())
                .and_modify(|revision| *revision = (*revision).max(attempt.revision)).or_insert(attempt.revision);
            controller.attempted_decisions.insert((attempt.session_id.clone(), attempt.decision_id));
            controller.attempted_states.insert((attempt.session_id, attempt.revision));
        }
        Ok(controller)
    }

    pub fn recovery_required(&self) -> bool { self.recovery_required }

    fn persist(&mut self, attempt: &crate::journal::Attempt, outcome: Option<crate::journal::Outcome>) -> Result<(), ControlError> {
        if let Some(journal) = &mut self.journal {
            if let Err(error) = journal.append(attempt, outcome) {
                self.recovery_required = true;
                return Err(ControlError::Journal(error));
            }
        }
        Ok(())
    }

    /// Caller must provide a freshly observed state, not the inference input copy,
    /// and the unchanged window created before inference. Checks guard dispatch
    /// only; they cannot interrupt an executor already running.
    pub fn execute<E: ActionExecutor>(
        &mut self, current: &Observation, decision: &Decision, window: &ExecutionWindow, executor: &mut E,
    ) -> Result<ExecutionOutcome, ControlError> {
        let snapshot = &current.snapshot;
        if !snapshot.complete { return Err(ControlError::IncompleteState); }
        if [&snapshot.session_id, &decision.decision_id, &decision.candidate_id].iter()
            .any(|id| id.is_empty() || id.len() > 128) {
            return Err(ControlError::InvalidIdentity);
        }
        window.check(snapshot, Instant::now())?;
        if snapshot.session_id != decision.session_id || snapshot.revision != decision.revision {
            return Err(ControlError::StaleDecision);
        }
        let mut matches = current.candidates.iter().filter(|c| c.id == decision.candidate_id);
        let candidate = matches.next().ok_or(ControlError::UnknownCandidate)?;
        if matches.next().is_some() { return Err(ControlError::AmbiguousCandidate); }
        if !candidate.action.allowed_in(&snapshot.phase) { return Err(ControlError::WrongPhase); }
        if !candidate.action.well_formed() { return Err(ControlError::InvalidAction); }
        let decision_key = (snapshot.session_id.clone(), decision.decision_id.clone());
        let state_key = (snapshot.session_id.clone(), snapshot.revision);
        if self.attempted_decisions.contains(&decision_key) || self.attempted_states.contains(&state_key) {
            return Err(ControlError::AlreadyAttempted);
        }
        if self.recovery_required { return Err(ControlError::RecoveryRequired); }
        if self.highest_attempted_revision.get(&snapshot.session_id).is_some_and(|revision| snapshot.revision < *revision) {
            return Err(ControlError::StaleDecision);
        }
        window.check(snapshot, Instant::now())?;
        // Record BEFORE sending: even an error can mean the input was partially delivered.
        self.attempted_decisions.insert(decision_key);
        self.attempted_states.insert(state_key);
        self.highest_attempted_revision.insert(snapshot.session_id.clone(), snapshot.revision);
        let attempt = crate::journal::Attempt { session_id: snapshot.session_id.clone(), revision: snapshot.revision,
            decision_id: decision.decision_id.clone(), candidate_id: candidate.id.clone() };
        self.persist(&attempt, None)?;
        // Durable I/O may have used the remaining budget. Record non-dispatch if
        // the deadline or stop signal changed while syncing the intent.
        if let Err(error) = window.check_current(snapshot) {
            self.persist(&attempt, Some(crate::journal::Outcome::NotDispatched))?;
            return Err(error);
        }
        let outcome = executor.execute(decision, candidate);
        let stored = match &outcome {
            Ok(ExecutionOutcome::Recorded) => crate::journal::Outcome::Recorded,
            Ok(ExecutionOutcome::Confirmed) => crate::journal::Outcome::Confirmed,
            Ok(ExecutionOutcome::Uncertain(_)) => crate::journal::Outcome::Uncertain,
            Err(_) => crate::journal::Outcome::Failed,
        };
        if matches!(stored, crate::journal::Outcome::Uncertain | crate::journal::Outcome::Failed) {
            self.recovery_required = true;
        }
        self.persist(&attempt, Some(stored))?;
        outcome.map_err(ControlError::Execution)
    }
}

#[cfg(test)]
mod timing_tests {
    use super::*;
    use crate::protocol::{Action, Phase};

    #[test]
    fn monotonic_deadline_is_exclusive_and_cancellation_is_shared() {
        let snapshot = Snapshot { session_id: "test".into(), revision: 1, phase: Phase::OurTurn, complete: true };
        let start = Instant::now();
        let window = ExecutionWindow::at(&snapshot, Duration::from_secs(1), start).unwrap();
        assert_eq!(window.check(&snapshot, start), Ok(()));
        assert_eq!(window.check(&snapshot, start + Duration::from_secs(1)), Err(ControlError::DeadlineExpired));
        window.clone().cancel();
        assert_eq!(window.check(&snapshot, start), Err(ControlError::Cancelled));
        assert!(matches!(ExecutionWindow::new(&snapshot, Duration::ZERO), Err(ControlError::InvalidBudget)));
        assert!(matches!(ExecutionWindow::new(&snapshot, Duration::MAX), Err(ControlError::InvalidBudget)));
    }

    #[test]
    fn journal_write_failure_prevents_dispatch_and_latches_recovery() {
        let path = std::env::temp_dir().join(format!("hearth-agent-readonly-journal-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        std::fs::write(&path, "").unwrap();
        let mut controller = Controller { journal: Some(crate::journal::Journal::read_only_for_test(&path)), ..Controller::default() };
        let observation = Observation {
            snapshot: Snapshot { session_id: "test".into(), revision: 1, phase: Phase::OurTurn, complete: true },
            candidates: vec![crate::protocol::Candidate { id: "end".into(), action: Action::EndTurn }],
        };
        let decision = Decision { session_id: "test".into(), revision: 1, decision_id: "d1".into(), candidate_id: "end".into() };
        let window = ExecutionWindow::new(&observation.snapshot, Duration::from_secs(10)).unwrap();
        let mut executor = crate::executor::RecordingExecutor::default();
        assert!(matches!(controller.execute(&observation, &decision, &window, &mut executor), Err(ControlError::Journal(_))));
        assert!(controller.recovery_required());
        assert!(executor.records.is_empty());
        drop(controller);
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "");
        std::fs::remove_file(path).unwrap();
    }
}
