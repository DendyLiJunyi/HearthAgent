//! Offline replay of a frozen Power.log prefix. Only GameState's power stream
//! mutates state. PowerTaskList is an animation stream and must not be replayed twice.
use std::collections::{BTreeMap, BTreeSet};
use std::io::{self, BufRead, Read};

pub(crate) const MAX_LINE: usize = 1024 * 1024;
pub(crate) const MAX_GAME_BYTES: usize = 64 * 1024 * 1024;

pub(crate) fn relevant_line(line: &str) -> bool {
    [" GameState.DebugPrintPower() - ", " GameState.DebugPrintGame() - ",
        " GameState.DebugPrintEntityChoices() - ", " GameState.DebugPrintEntitiesChosen() - ",
        " GameState.DebugPrintOptions() - ", " GameState.SendOption() - ", " GameState.SendChoices() - "]
        .iter().any(|marker| line.contains(marker))
}

#[derive(Default, Debug)]
pub struct Entity {
    pub id: u32,
    pub card_id: Option<String>,
    pub tags: BTreeMap<String, String>,
}

impl Entity {
    pub fn tag(&self, key: &str) -> Option<&str> {
        self.tags.get(key).map(String::as_str)
    }
}

#[derive(Default, Debug)]
pub struct Game {
    pub choices: crate::choices::Choices,
    pub perspective: crate::perspective::Perspective,
    pub structure: crate::structure::PowerStructure,
    pub options: crate::options::Options,
    pub entities: BTreeMap<u32, Entity>,
    pub players: BTreeMap<u32, u32>,
    pub game_entity: Option<u32>,
    pub unresolved_references: usize,
    pub malformed_records: usize,
    pub ignored_power_records: usize,
    /// Fixed labels only: unknown record contents must not expose player names.
    pub ignored_power_record_types: BTreeMap<&'static str, usize>,
}

impl Game {
    fn entity(&mut self, id: u32) -> &mut Entity {
        self.entities.entry(id).or_insert_with(|| Entity { id, ..Entity::default() })
    }
    pub fn game_tag(&self, tag: &str) -> Option<&str> {
        self.entities.get(&self.game_entity?)?.tag(tag)
    }
}

#[derive(Default, Debug)]
pub struct Replay {
    pub games: Vec<Game>,
    pub ignored_partial_line: bool,
}

fn field<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    text.split_whitespace().find_map(|token| token.strip_prefix(key))
        .map(|s| s.trim_end_matches([',', ']']))
}

fn number(text: &str, key: &str) -> Option<u32> { field(text, key)?.parse().ok() }
fn power(line: &str) -> Option<&str> {
    line.split_once(" GameState.DebugPrintPower() - ").map(|(_, s)| s.trim())
}
fn tags(text: &str) -> Option<(&str, &str)> {
    Some((field(text, "tag=")?, field(text, "value=")?))
}

fn ignored_record_type(text: &str) -> &'static str {
    match text.split_whitespace().next().unwrap_or("") {
        "BLOCK_START" => "BLOCK_START",
        "BLOCK_END" => "BLOCK_END",
        "META_DATA" => "META_DATA",
        "RESET_GAME" => "RESET_GAME",
        "SHUFFLE_DECK" => "SHUFFLE_DECK",
        "SUB_SPELL_START" => "SUB_SPELL_START",
        "SUB_SPELL_END" => "SUB_SPELL_END",
        "Source" => "SOURCE",
        "CACHED_TAG_FOR_DORMANT_CHANGE" => "CACHED_TAG_FOR_DORMANT_CHANGE",
        token if token.starts_with("Info[") => "INFO",
        token if token.starts_with("Targets[") => "TARGETS",
        _ => "OTHER",
    }
}

/// Names stay private to replay and are never part of the exported game model.
fn aliases(lines: &[String], players: &BTreeMap<u32, u32>) -> BTreeMap<String, BTreeSet<u32>> {
    let mut result: BTreeMap<String, BTreeSet<u32>> = BTreeMap::new();
    // A name can become available only when the mulligan is submitted.
    // Bind that name through its choice ID, never through arbitrary targets.
    let mut owners: BTreeMap<u32, BTreeSet<u32>> = BTreeMap::new();
    let mut invalid = BTreeSet::new();
    let mut active = None;
    for line in lines {
        let Some((_, text)) = line.split_once(" GameState.DebugPrintEntityChoices() - ") else {
            active = None;
            continue;
        };
        if text.contains(" Player=") {
            active = None;
            if let Some(id) = number(text, "id=") {
                if field(text, "ChoiceType=") == Some("MULLIGAN") {
                    active = Some(id);
                } else { invalid.insert(id); }
            }
        } else if text.trim_start().starts_with("Entities[") {
            if let Some(id) = active {
                if let Some(player) = number(text, "player=").filter(|p| players.contains_key(p)) {
                    owners.entry(id).or_default().insert(player);
                } else { invalid.insert(id); }
            }
        } else if text.trim() != "Source=GameEntity" { active = None; }
    }
    for line in lines {
        if let Some((_, text)) = line.split_once(" GameState.DebugPrintEntitiesChosen() - ") {
            if let (Some(id), Some((_, rest))) = (number(text, "id="), text.split_once(" Player=")) {
                if invalid.contains(&id) { continue; }
                if let (Some(controllers), Some((name, _))) = (owners.get(&id), rest.split_once(" EntitiesCount=")) {
                    if controllers.len() == 1 {
                        let entity = players[controllers.iter().next().unwrap()];
                        result.entry(name.to_string()).or_default().insert(entity);
                    }
                }
            }
        }
    }
    let mut choice_name: Option<String> = None;
    let mut choice_controllers = BTreeSet::new();
    let flush = |name: &mut Option<String>, controllers: &mut BTreeSet<u32>, result: &mut BTreeMap<String, BTreeSet<u32>>| {
        if controllers.len() == 1 {
            if let (Some(name), Some(id)) = (name.as_ref(), controllers.iter().next().and_then(|p| players.get(p))) {
                result.entry(name.clone()).or_default().insert(*id);
            }
        }
        *name = None;
        controllers.clear();
    };
    for line in lines {
        if let Some((_, text)) = line.split_once(" GameState.DebugPrintGame() - ") {
            if let (Some(player), Some((_, name))) = (number(text, "PlayerID="), text.split_once("PlayerName=")) {
                if let Some(id) = players.get(&player) {
                    result.entry(name.trim().to_string()).or_default().insert(*id);
                }
            }
        }
        if let Some((_, text)) = line.split_once(" GameState.DebugPrintEntityChoices() - ") {
            if let Some((_, rest)) = text.split_once(" Player=") {
                flush(&mut choice_name, &mut choice_controllers, &mut result);
                // Infer player aliases only from mulligan-owned card choices.
                // Arbitrary choices may contain entities controlled by an opponent.
                if field(text, "ChoiceType=") == Some("MULLIGAN") {
                    choice_name = rest.split_once(" TaskList=").map(|(name, _)| name.to_string());
                }
            } else if text.trim_start().starts_with("Entities[") {
                if let Some(controller) = number(text, "player=") { choice_controllers.insert(controller); }
            } else if text.trim() == "Source=GameEntity" {
                // The source line precedes mulligan entities in the actual log.
            } else {
                flush(&mut choice_name, &mut choice_controllers, &mut result);
            }
        } else {
            flush(&mut choice_name, &mut choice_controllers, &mut result);
        }
    }
    flush(&mut choice_name, &mut choice_controllers, &mut result);
    result
}

/// Bracket display names may contain spaces and id-like tokens; the actual ID
/// occurs in the final structured fields, after the display name.
pub(crate) fn entity_reference(text: &str) -> Option<u32> {
    let text = text.trim();
    if let Ok(id) = text.parse() { return Some(id); }
    let body = text.strip_prefix('[')?.strip_suffix(']')?;
    body.split_whitespace().rev().find_map(|token| token.strip_prefix("id="))?.parse().ok()
}

fn resolve(text: &str, game_id: Option<u32>, aliases: &BTreeMap<String, BTreeSet<u32>>) -> Option<u32> {
    let text = text.trim();
    if let Ok(id) = text.parse() { return Some(id); }
    if text == "GameEntity" { return game_id; }
    if text.starts_with('[') { return entity_reference(text); }
    let ids = aliases.get(text)?;
    (ids.len() == 1).then(|| *ids.iter().next().unwrap())
}

pub(crate) fn build_game(lines: &[String]) -> Game {
    let mut game = Game { options: crate::options::Options::from_lines(lines), ..Game::default() };
    for text in lines.iter().filter_map(|l| power(l)) {
        if text.starts_with("Player EntityID=") {
            if let (Some(id), Some(player)) = (number(text, "EntityID="), number(text, "PlayerID=")) {
                game.players.insert(player, id);
            }
        } else if text.starts_with("GameEntity EntityID=") { game.game_entity = number(text, "EntityID="); }
    }
    let aliases = aliases(lines, &game.players);
    game.choices = crate::choices::Choices::from_lines(lines, |reference| resolve(reference, game.game_entity, &aliases));
    let mut context = None;
    for (index, line) in lines.iter().enumerate() {
        if let Some(player) = crate::perspective::submitted_player(&game, line) {
            game.perspective.record(player);
        }
        if let Some(player) = crate::perspective::submitted_mulligan_player(&game, line, &lines[..index]) {
            game.perspective.record_mulligan(player);
        }
        let Some(text) = power(line) else { continue; };
        game.structure.observe(text);
        if text.starts_with("tag=") {
            if let (Some(id), Some((tag, value))) = (context, tags(text)) {
                game.entity(id).tags.insert(tag.into(), value.into());
            } else { game.malformed_records += 1; }
            continue;
        }
        context = None;
        if text == "CREATE_GAME" { continue; }
        if text.starts_with("GameEntity EntityID=") || text.starts_with("Player EntityID=") {
            if let Some(id) = number(text, "EntityID=") { game.entity(id); context = Some(id); }
            else { game.malformed_records += 1; }
        } else if text.starts_with("FULL_ENTITY - Creating ID=") {
            if let Some(id) = number(text, "ID=") {
                let entity = game.entity(id);
                entity.card_id = field(text, "CardID=").filter(|s| !s.is_empty()).map(str::to_string);
                context = Some(id);
            } else { game.malformed_records += 1; }
        } else if text.starts_with("SHOW_ENTITY - Updating Entity=") || text.starts_with("CHANGE_ENTITY - Updating Entity=") {
            if let Some((reference, card)) = text.split_once("Entity=").and_then(|(_, t)| t.split_once(" CardID=")) {
                if let Some(id) = resolve(reference, game.game_entity, &aliases) {
                    game.entity(id).card_id = card.split_whitespace().next().map(str::to_string);
                    context = Some(id);
                } else { game.unresolved_references += 1; }
            } else { game.malformed_records += 1; }
        } else if text.starts_with("TAG_CHANGE Entity=") || text.starts_with("HIDE_ENTITY - Entity=") {
            if let Some((reference, tail)) = text.split_once("Entity=").and_then(|(_, t)| t.split_once(" tag=")) {
                if let Some(id) = resolve(reference, game.game_entity, &aliases) {
                    if let Some((tag, value)) = tags(&format!("tag={tail}")) {
                        let entity = game.entity(id);
                        entity.tags.insert(tag.into(), value.into());
                        if text.starts_with("HIDE_ENTITY") { entity.card_id = None; }
                    } else { game.malformed_records += 1; }
                } else { game.unresolved_references += 1; }
            } else { game.malformed_records += 1; }
        } else {
            game.ignored_power_records += 1;
            *game.ignored_power_record_types.entry(ignored_record_type(text)).or_default() += 1;
        }
    }
    game
}

/// Two-pass offline replay supports aliases learned after earlier tag changes.
/// This is deliberately not an incremental/live ObservationSource yet.
pub fn read(reader: impl BufRead) -> io::Result<Replay> {
    read_with_limits(reader, MAX_LINE, MAX_GAME_BYTES)
}

fn read_with_limits(mut reader: impl BufRead, max_line: usize, max_game_bytes: usize) -> io::Result<Replay> {
    read_with_visitor(&mut reader, max_line, max_game_bytes, None, None, None)
}

/// Visit each observed option packet before a following record can invalidate
/// it. The callback receives only the prefix available then, never future aliases
/// or player identity. `boundary` is false at EOF: neither value proves that the
/// client emitted every option. Returned games retain the normal replay result.
pub fn visit_option_windows(
    reader: impl BufRead, visitor: &mut dyn FnMut(usize, &Game, bool),
) -> io::Result<Replay> {
    read_with_visitor(reader, MAX_LINE, MAX_GAME_BYTES, Some(visitor), None, None)
}

type WindowVisitor<'a> = Option<&'a mut dyn FnMut(usize, &Game, bool)>;

/// A contiguous choice or submission record group, not a complete transaction.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
pub struct ChoiceWindow {
    pub kind: &'static str,
    pub packet_id: Option<u32>,
}

type ChoiceVisitor<'a> = Option<&'a mut dyn FnMut(usize, &Game, bool, ChoiceWindow)>;

/// Visit every choice/submission prefix before the next record mutates state.
/// No future aliases, card identities or submission results are imported.
pub fn visit_choice_windows(
    reader: impl BufRead, visitor: &mut dyn FnMut(usize, &Game, bool, ChoiceWindow),
) -> io::Result<Replay> {
    read_with_visitor(reader, MAX_LINE, MAX_GAME_BYTES, None, Some(visitor), None)
}

type SubmissionVisitor<'a> = Option<&'a mut dyn FnMut(usize, &Game)>;

/// Emit each complete local SendOption line with its prefix-frozen correlation.
/// No later state or response is used, and no execution success is inferred.
pub fn visit_option_submissions(
    reader: impl BufRead, visitor: &mut dyn FnMut(usize, &Game),
) -> io::Result<Replay> {
    read_with_visitor(reader, MAX_LINE, MAX_GAME_BYTES, None, None, Some(visitor))
}

fn choice_record(line: &str) -> Option<(&'static str, &str)> {
    for (marker, kind) in [(" GameState.DebugPrintEntityChoices() - ", "packet"),
        (" GameState.DebugPrintEntitiesChosen() - ", "submission")] {
        if let Some((_, text)) = line.split_once(marker) { return Some((kind, text.trim())); }
    }
    None
}

fn read_with_visitor(
    mut reader: impl BufRead, max_line: usize, max_game_bytes: usize, mut visitor: WindowVisitor<'_>,
    mut choice_visitor: ChoiceVisitor<'_>,
    mut submission_visitor: SubmissionVisitor<'_>,
) -> io::Result<Replay> {
    let mut result = Replay::default();
    let mut lines = Vec::new();
    let mut bytes = Vec::new();
    let mut started = false;
    let mut size = 0;
    let mut option_window = false;
    let mut choice_window: Option<ChoiceWindow> = None;
    loop {
        bytes.clear();
        // Bound allocation even if a corrupt file never supplies a newline.
        if reader.by_ref().take(max_line as u64 + 2).read_until(b'\n', &mut bytes)? == 0 { break; }
        let terminated = bytes.ends_with(b"\n");
        if bytes.len() - usize::from(terminated) > max_line {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "log line exceeds limit"));
        }
        if !bytes.ends_with(b"\n") { result.ignored_partial_line = true; break; }
        let line = std::str::from_utf8(&bytes[..bytes.len() - 1])
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?.trim_end_matches('\r');
        let is_option = line.contains(" GameState.DebugPrintOptions() - ");
        let new_packet = line.split_once(" GameState.DebugPrintOptions() - ")
            .is_some_and(|(_, text)| text.trim_start().starts_with("id="));
        let choice = choice_record(line);
        if let Some(window) = choice_window {
            if choice.is_none_or(|(kind, text)| kind != window.kind || text.starts_with("id=")) {
                if let Some(visit) = &mut choice_visitor {
                    visit(result.games.len() + 1, &build_game(&lines), true, window);
                }
                choice_window = None;
            }
        }
        if option_window && (!is_option || new_packet) {
            if let Some(visit) = &mut visitor { visit(result.games.len() + 1, &build_game(&lines), true); }
            option_window = false;
        }
        if power(line) == Some("CREATE_GAME") {
            if started { result.games.push(build_game(&lines)); lines.clear(); size = 0; }
            started = true;
        }
        if started && relevant_line(line) {
            size += line.len();
            if size > max_game_bytes {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "active game exceeds limit"));
            }
            lines.push(line.to_string());
            if line.contains(" GameState.SendOption() - ") {
                if let Some(visit) = &mut submission_visitor {
                    visit(result.games.len() + 1, &build_game(&lines));
                }
            }
            if is_option { option_window = true; }
            if let Some((kind, text)) = choice {
                if choice_window.is_none() {
                    let packet_id = text.split_whitespace().next()
                        .and_then(|head| head.strip_prefix("id=")).and_then(|id| id.parse().ok());
                    choice_window = Some(ChoiceWindow { kind, packet_id });
                }
            }
        }
    }
    if option_window {
        if let Some(visit) = &mut visitor { visit(result.games.len() + 1, &build_game(&lines), false); }
    }
    if let Some(window) = choice_window {
        if let Some(visit) = &mut choice_visitor {
            visit(result.games.len() + 1, &build_game(&lines), false, window);
        }
    }
    if started { result.games.push(build_game(&lines)); }
    Ok(result)
}

pub fn print_summary(replay: &Replay) {
    println!("Replayed games: {}; ignored trailing partial line: {}", replay.games.len(), replay.ignored_partial_line);
    for (i, game) in replay.games.iter().enumerate() {
        println!("Game {}: entities={} turn={:?} step={:?} state={:?}", i + 1, game.entities.len(), game.game_tag("TURN"), game.game_tag("STEP"), game.game_tag("STATE"));
        println!("Diagnostics: unresolved={} malformed={} ignored_power_records={}", game.unresolved_references, game.malformed_records, game.ignored_power_records);
        println!("Ignored power record types: {:?}", game.ignored_power_record_types);
        println!("Power structure: {}", game.structure.to_json());
        println!("Options: packets={} malformed={} unsupported={} latest_stale={:?}",
            game.options.packets_seen, game.options.malformed_records, game.options.unsupported_records,
            game.options.latest.as_ref().map(|set| set.stale));
        for (player, id) in &game.players {
            if let Some(entity) = game.entities.get(id) {
                println!("Player {player}: entity={id} result={:?} current={:?} resources={:?} used={:?}", entity.tag("PLAYSTATE"), entity.tag("CURRENT_PLAYER"), entity.tag("RESOURCES"), entity.tag("RESOURCES_USED"));
                let hand = game.entities.values().filter(|e| e.tag("ZONE") == Some("HAND") && e.tag("CONTROLLER").and_then(|v| v.parse::<u32>().ok()) == Some(*player)).count();
                println!("  Hand entities: {hand}");
            }
        }
    }
    println!("Offline diagnostic state only; unknown tags remain unknown. No complete/legal-action snapshot or game input is produced.");
}

#[cfg(test)]
mod limit_tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn terminated_and_unterminated_lines_obey_same_bound() {
        for bytes in [b"123456".as_slice(), b"123456\n", b"12345\r\n"] {
            assert_eq!(read_with_limits(Cursor::new(bytes), 5, 100).unwrap_err().kind(), io::ErrorKind::InvalidData);
        }
        assert!(read_with_limits(Cursor::new(b"12345\n"), 5, 100).is_ok());
        assert!(read_with_limits(Cursor::new(b"1234\r\n"), 5, 100).is_ok());
        assert!(read_with_limits(Cursor::new(b"12345"), 5, 100).unwrap().ignored_partial_line);
    }

    #[test]
    fn game_limit_counts_only_relevant_lines_and_resets_each_game() {
        let create = "D 0 GameState.DebugPrintPower() - CREATE_GAME\n";
        let log = create.to_string() + "unrelated line\n" + create;
        assert_eq!(read_with_limits(Cursor::new(log), 100, create.len() - 1).unwrap().games.len(), 2);
        let log = create.to_string() + "D 0 GameState.DebugPrintPower() - BLOCK_END\n";
        assert_eq!(read_with_limits(Cursor::new(log), 100, create.len() - 1).unwrap_err().kind(), io::ErrorKind::InvalidData);
    }
}
