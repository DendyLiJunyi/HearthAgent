/// IDs are meaningful only within their session and state revision.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub session_id: String,
    pub revision: u64,
    pub phase: Phase,
    pub complete: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Phase {
    OurTurn,
    OpponentTurn,
    Choosing,
    Animating,
    Finished,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    PlayCard { source: u32, target: Option<u32> },
    Attack { source: u32, target: u32 },
    HeroPower { target: Option<u32> },
    ChooseOption { entity: u32 },
    EndTurn,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    pub id: String,
    pub action: Action,
}

/// An observation adapter must check candidate legality against this snapshot.
/// The controller validates identity and phase, not Hearthstone's full rules.
#[derive(Clone, Debug)]
pub struct Observation {
    pub snapshot: Snapshot,
    pub candidates: Vec<Candidate>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decision {
    pub decision_id: String,
    pub session_id: String,
    pub revision: u64,
    pub candidate_id: String,
}

pub trait ObservationSource {
    fn observe(&mut self) -> Result<Observation, String>;
}
