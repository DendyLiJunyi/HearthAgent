use crate::protocol::{Decision, Observation};

/// A local inference service adapter implements this boundary.
/// `laya::LayaPolicy` provides a loopback HTTP adapter with bounded requests.
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
        self.sequence = self.sequence.checked_add(1).ok_or("baseline decision sequence exhausted")?;
        Ok(Decision {
            decision_id: format!("baseline-{}", self.sequence),
            session_id: observation.snapshot.session_id.clone(),
            revision: observation.snapshot.revision,
            candidate_id: candidate.id.clone(),
        })
    }
}
