use crate::protocol::{Decision, Observation};

/// A local inference service adapter implements this boundary.
/// Transport, model format and timeouts will be chosen after model identification.
pub trait PolicyBackend {
    fn decide(&mut self, observation: &Observation) -> Result<Decision, String>;
}

/// Deterministic plumbing baseline, not a competitive Hearthstone strategy.
#[derive(Default)]
pub struct FirstCandidatePolicy {
    sequence: u64,
}

impl PolicyBackend for FirstCandidatePolicy {
    fn decide(&mut self, observation: &Observation) -> Result<Decision, String> {
        let candidate = observation.candidates.first().ok_or("no candidates")?;
        self.sequence += 1;
        Ok(Decision {
            decision_id: format!("baseline-{}", self.sequence),
            session_id: observation.snapshot.session_id.clone(),
            revision: observation.snapshot.revision,
            candidate_id: candidate.id.clone(),
        })
    }
}
