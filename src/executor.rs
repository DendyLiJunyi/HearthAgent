use crate::protocol::{Candidate, Decision};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExecutionOutcome {
    /// Offline recording only; no game action was sent or acknowledged.
    Recorded,
    /// A live adapter may report this only after observing the expected result.
    Confirmed,
    /// The adapter cannot tell whether the action reached the game.
    Uncertain(String),
}

pub trait ActionExecutor {
    fn execute(&mut self, decision: &Decision, candidate: &Candidate)
        -> Result<ExecutionOutcome, String>;
}

#[derive(Default)]
pub struct RecordingExecutor {
    pub records: Vec<(Decision, Candidate)>,
}

impl ActionExecutor for RecordingExecutor {
    fn execute(&mut self, decision: &Decision, candidate: &Candidate)
        -> Result<ExecutionOutcome, String> {
        self.records.push((decision.clone(), candidate.clone()));
        Ok(ExecutionOutcome::Recorded)
    }
}
