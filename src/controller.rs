use std::collections::HashSet;
use crate::executor::{ActionExecutor, ExecutionOutcome};
use crate::protocol::{Action, Decision, Observation, Phase};

#[derive(Debug, PartialEq, Eq)]
pub enum ControlError {
    IncompleteState,
    StaleDecision,
    WrongPhase,
    UnknownCandidate,
    AmbiguousCandidate,
    AlreadyAttempted,
    Execution(String),
}

/// In-memory attempt ledger. A live adapter must resynchronize after restart.
#[derive(Default)]
pub struct Controller {
    attempted_decisions: HashSet<(String, String)>,
    attempted_states: HashSet<(String, u64)>,
}

impl Controller {
    /// Caller must provide a freshly observed state, not the inference input copy.
    pub fn execute<E: ActionExecutor>(
        &mut self, current: &Observation, decision: &Decision, executor: &mut E,
    ) -> Result<ExecutionOutcome, ControlError> {
        let snapshot = &current.snapshot;
        if !snapshot.complete { return Err(ControlError::IncompleteState); }
        if snapshot.session_id != decision.session_id || snapshot.revision != decision.revision {
            return Err(ControlError::StaleDecision);
        }
        let mut matches = current.candidates.iter().filter(|c| c.id == decision.candidate_id);
        let candidate = matches.next().ok_or(ControlError::UnknownCandidate)?;
        if matches.next().is_some() { return Err(ControlError::AmbiguousCandidate); }
        let phase_valid = match (&snapshot.phase, &candidate.action) {
            (Phase::Choosing, Action::ChooseOption { .. }) => true,
            (Phase::OurTurn, action) => !matches!(action, Action::ChooseOption { .. }),
            _ => false,
        };
        if !phase_valid { return Err(ControlError::WrongPhase); }
        let decision_key = (snapshot.session_id.clone(), decision.decision_id.clone());
        let state_key = (snapshot.session_id.clone(), snapshot.revision);
        if self.attempted_decisions.contains(&decision_key) || self.attempted_states.contains(&state_key) {
            return Err(ControlError::AlreadyAttempted);
        }
        // Record BEFORE sending: even an error can mean the input was partially delivered.
        self.attempted_decisions.insert(decision_key);
        self.attempted_states.insert(state_key);
        executor.execute(decision, candidate).map_err(ControlError::Execution)
    }
}
