/// IDs are meaningful only within their session and state revision.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Snapshot {
    pub session_id: String,
    pub revision: u64,
    pub phase: Phase,
    pub complete: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Phase {
    Mulligan,
    OurTurn,
    OpponentTurn,
    Choosing,
    Animating,
    Finished,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Action {
    /// One-based board placement when required; adapter checks actual legal slots.
    PlayCard { source: u32, target: Option<u32>, position: Option<u32> },
    Attack { source: u32, target: u32 },
    HeroPower { target: Option<u32> },
    /// Entities belong to this exact choice packet. Empty lists require min=0.
    ChooseOptions { choice_id: u32, entities: Vec<u32> },
    /// Empty replacement list means keep all cards, not end the turn.
    Mulligan { choice_id: u32, replace: Vec<u32> },
    EndTurn,
}

impl Action {
    pub fn allowed_in(&self, phase: &Phase) -> bool {
        matches!((phase, self),
            (Phase::Mulligan, Self::Mulligan { .. })
            | (Phase::Choosing, Self::ChooseOptions { .. })
            | (Phase::OurTurn, Self::PlayCard { .. } | Self::Attack { .. } | Self::HeroPower { .. } | Self::EndTurn))
    }

    /// Protocol shape only, never a substitute for the game's legality rules.
    pub fn well_formed(&self) -> bool {
        let valid_list = |entities: &[u32]| entities.len() <= 32 && !entities.contains(&0)
            && entities.iter().collect::<std::collections::HashSet<_>>().len() == entities.len();
        match self {
            Self::PlayCard { source, target, position } => *source != 0 && *target != Some(0) && *position != Some(0),
            Self::Attack { source, target } => *source != 0 && *target != 0,
            Self::HeroPower { target } => *target != Some(0),
            Self::ChooseOptions { entities, .. } => valid_list(entities),
            Self::Mulligan { replace, .. } => valid_list(replace),
            Self::EndTurn => true,
        }
    }

    pub fn description(&self) -> String {
        match self {
            Self::PlayCard { source, target, position } => format!("Play card {source}; target {target:?}; board position {position:?}"),
            Self::Attack { source, target } => format!("Attack with entity {source} against entity {target}"),
            Self::HeroPower { target } => format!("Use hero power; target {target:?}"),
            Self::ChooseOptions { choice_id, entities } => format!("For choice packet {choice_id}, select entities {entities:?}"),
            Self::Mulligan { choice_id, replace } => format!("For mulligan packet {choice_id}, replace entities {replace:?}; keep the other cards"),
            Self::EndTurn => "End the current turn".into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Candidate {
    pub id: String,
    pub action: Action,
}

/// An observation adapter must check candidate legality against this snapshot.
/// The controller validates identity and phase, not Hearthstone's full rules.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Observation {
    pub snapshot: Snapshot,
    pub candidates: Vec<Candidate>,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct Decision {
    pub decision_id: String,
    pub session_id: String,
    pub revision: u64,
    pub candidate_id: String,
}

pub trait ObservationSource {
    fn observe(&mut self) -> Result<Observation, String>;
}
