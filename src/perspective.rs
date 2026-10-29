//! Identify the local acting player from a client-side submission, never names
//! or visible hand contents. This does not certify observation completeness.
use crate::replay::Game;

#[derive(Default, Debug)]
pub struct Perspective {
    player: Option<u32>,
    source: Option<&'static str>,
    pub conflicting: bool,
}

impl Perspective {
    pub fn player_id(&self) -> Option<u32> {
        self.player.filter(|_| !self.conflicting)
    }

    pub(crate) fn record(&mut self, player: u32) {
        self.record_source(player, "local_main_action_submission");
    }

    pub fn source(&self) -> Option<&'static str> {
        self.player_id().and(self.source)
    }

    pub(crate) fn record_mulligan(&mut self, player: u32) {
        self.record_source(player, "local_mulligan_submission");
    }

    fn record_source(&mut self, player: u32, source: &'static str) {
        if self.player.is_some_and(|previous| previous != player) {
            self.conflicting = true;
        }
        self.player = Some(player);
        if self.source.is_none() { self.source = Some(source); }
    }
}

/// Identify only at the local send header, using packets already present in the
/// prefix. A server-side EntitiesChosen record is not local identity evidence.
pub(crate) fn submitted_mulligan_player(game: &Game, line: &str, prefix: &[String]) -> Option<u32> {
    let (_, text) = line.split_once(" GameState.SendChoices() - ")?;
    let mut fields = text.split_whitespace();
    let id = fields.next()?.strip_prefix("id=")?.parse::<u32>().ok()?;
    if fields.next()? != "ChoiceType=MULLIGAN" || fields.next().is_some()
        || game.players.len() != 2 || game.game_tag("STATE") != Some("RUNNING")
        || game.game_tag("STEP") != Some("BEGIN_MULLIGAN")
        || game.unresolved_references != 0 || game.malformed_records != 0 {
        return None;
    }
    let choices = crate::choices::Choices::from_lines(prefix, |reference| {
        if reference.trim() == "GameEntity" { game.game_entity }
        else { crate::replay::entity_reference(reference) }
    });
    if choices.malformed_records != 0 || choices.unsupported_records != 0 { return None; }
    let set = choices.sets.get(&id)?;
    // Reused packet IDs are ambiguous for this inference, even if the newest
    // packet happens to have the same owner. Never repair using a later packet.
    let occurrences = prefix.iter().filter(|line| {
        line.split_once(" GameState.DebugPrintEntityChoices() - ")
            .and_then(|(_, text)| text.split_whitespace().next())
            .and_then(|field| field.strip_prefix("id="))
            .and_then(|value| value.parse::<u32>().ok()) == Some(id)
    }).count();
    if occurrences != 1 || set.kind != "MULLIGAN" || set.minimum != 0
        || !(3..=5).contains(&set.maximum) || set.entities.len() != set.maximum as usize
        || set.source_entity != game.game_entity || game.game_entity.is_none() {
        return None;
    }
    let mut owner = None;
    for id in &set.entities {
        let card = game.entities.get(id)?;
        if card.tag("ZONE") != Some("HAND") { return None; }
        let controller = card.tag("CONTROLLER")?.parse::<u32>().ok()?;
        if !game.players.contains_key(&controller) || owner.is_some_and(|p| p != controller) {
            return None;
        }
        owner = Some(controller);
    }
    let player = owner?;
    let entity = *game.players.get(&player)?;
    if set.owner_entity.is_some_and(|id| id != entity)
        || game.entities.get(&entity)?.tag("MULLIGAN_STATE") != Some("INPUT") {
        return None;
    }
    Some(player)
}

/// SendOption is logged inside the client's non-spectator branch. Restrict
/// inference to ordinary two-player main actions with fully observed turn flags.
pub(crate) fn submitted_player(game: &Game, line: &str) -> Option<u32> {
    crate::option_submission::Selection::parse(line)?;
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
