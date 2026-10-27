//! Identify the local acting player from a client-side submission, never names
//! or visible hand contents. This does not certify observation completeness.
use crate::replay::Game;

#[derive(Default, Debug)]
pub struct Perspective {
    player: Option<u32>,
    pub conflicting: bool,
}

impl Perspective {
    pub fn player_id(&self) -> Option<u32> {
        self.player.filter(|_| !self.conflicting)
    }

    pub(crate) fn record(&mut self, player: u32) {
        if self.player.is_some_and(|previous| previous != player) {
            self.conflicting = true;
        }
        self.player = Some(player);
    }
}

/// SendOption is logged inside the client's non-spectator branch. Restrict
/// inference to ordinary two-player main actions with fully observed turn flags.
pub(crate) fn submitted_player(game: &Game, line: &str) -> Option<u32> {
    let (_, text) = line.split_once(" GameState.SendOption() - ")?;
    let fields: Vec<_> = text.split_whitespace().collect();
    if fields.len() != 4 { return None; }
    fields[0].strip_prefix("selectedOption=")?.parse::<u32>().ok()?;
    let sub = fields[1].strip_prefix("selectedSubOption=")?.parse::<i32>().ok()?;
    if sub < -1 { return None; }
    fields[2].strip_prefix("selectedTarget=")?.parse::<u32>().ok()?;
    fields[3].strip_prefix("selectedPosition=")?.parse::<u32>().ok()?;
    if game.unresolved_references != 0 || game.malformed_records != 0
        || game.players.len() != 2 || game.game_tag("STATE") != Some("RUNNING")
        || game.game_tag("STEP") != Some("MAIN_ACTION") {
        return None;
    }
    let mut active = None;
    for (&player, id) in &game.players {
        match game.entities.get(id)?.tag("CURRENT_PLAYER")? {
            "0" => {},
            "1" if active.is_none() => active = Some(player),
            _ => return None,
        }
    }
    active
}
