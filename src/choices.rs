//! Choice records retained without display names. Candidate counts in the log
//! are selection bounds, not the number of options, so completeness stays false.
use std::collections::BTreeMap;
use serde::Serialize;

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ChoiceSet {
    pub id: u32,
    pub owner_entity: Option<u32>,
    pub kind: &'static str,
    pub minimum: u32,
    pub maximum: u32,
    pub source_entity: Option<u32>,
    pub entities: Vec<u32>,
    pub stale: bool,
    pub complete: bool,
    pub malformed_records: usize,
    #[serde(skip)]
    source_seen: bool,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ChoiceSubmission {
    pub id: u32,
    pub owner_entity: Option<u32>,
    pub expected_count: u32,
    pub entities: Vec<u32>,
    pub malformed_records: usize,
    /// Only the submitted list has a declared length. This is not execution confirmation.
    pub list_complete: bool,
}

#[derive(Default, Debug, Serialize, PartialEq, Eq)]
pub struct Choices {
    pub packets_seen: usize,
    pub malformed_records: usize,
    pub unsupported_records: usize,
    pub sets: BTreeMap<u32, ChoiceSet>,
    pub latest_submission: Option<ChoiceSubmission>,
    pub actionable: bool,
}

fn number(text: &str, name: &str) -> Option<u32> {
    text.split_whitespace().find_map(|s| s.strip_prefix(name))?.parse().ok()
}

fn entry(text: &str, prefix: &str) -> Option<(usize, u32)> {
    let (index, reference) = text.strip_prefix(prefix)?.split_once("]=")?;
    Some((index.parse().ok()?, crate::replay::entity_reference(reference)?))
}

impl Choices {
    pub(crate) fn from_lines(lines: &[String], resolve: impl Fn(&str) -> Option<u32>) -> Self {
        let mut result = Self::default();
        let mut active = None;
        let mut submitting = false;
        for line in lines {
            if let Some((_, text)) = line.split_once(" GameState.DebugPrintEntityChoices() - ") {
                submitting = false;
                let text = text.trim();
                if text.starts_with("id=") {
                    result.packets_seen += 1;
                    active = None;
                    let parsed = (|| {
                        let (head, rest) = text.split_once(" Player=")?;
                        let id = head.strip_prefix("id=")?.parse().ok()?;
                        let (owner, fields) = rest.rsplit_once(" TaskList=")?;
                        let kind = match fields.split_whitespace().find_map(|s| s.strip_prefix("ChoiceType="))? {
                            "MULLIGAN" => "MULLIGAN", "GENERAL" => "GENERAL", "TARGET" => "TARGET", _ => "UNKNOWN",
                        };
                        let minimum = number(fields, "CountMin=")?;
                        let maximum = number(fields, "CountMax=")?;
                        if minimum > maximum || maximum > 1024 { return None; }
                        Some(ChoiceSet { id, owner_entity: resolve(owner), kind, minimum, maximum,
                            source_entity: None, entities: Vec::new(), stale: false, complete: false,
                            malformed_records: 0, source_seen: false })
                    })();
                    if let Some(set) = parsed {
                        if set.kind == "UNKNOWN" { result.unsupported_records += 1; }
                        for old in result.sets.values_mut() {
                            if set.owner_entity.is_some() && old.owner_entity == set.owner_entity { old.stale = true; }
                        }
                        active = Some(set.id);
                        result.sets.insert(set.id, set);
                    } else {
                        result.malformed_records += 1;
                        for set in result.sets.values_mut() { set.stale = true; }
                    }
                    continue;
                }
                let Some(set) = active.and_then(|id| result.sets.get_mut(&id)) else {
                    result.malformed_records += 1; continue;
                };
                let valid = if let Some(reference) = text.strip_prefix("Source=") {
                    if set.source_seen || !set.entities.is_empty() { false } else {
                        set.source_seen = true;
                        set.source_entity = resolve(reference);
                        set.source_entity.is_some()
                    }
                } else if let Some((index, entity)) = entry(text, "Entities[") {
                    if !set.source_seen || index != set.entities.len() || set.entities.contains(&entity) || index >= 1024 {
                        false
                    } else { set.entities.push(entity); true }
                } else { false };
                if !valid { set.malformed_records += 1; result.malformed_records += 1; }
                continue;
            }
            active = None;
            if let Some((_, text)) = line.split_once(" GameState.DebugPrintEntitiesChosen() - ") {
                let text = text.trim();
                if text.starts_with("id=") {
                    let parsed = (|| {
                        let (head, rest) = text.split_once(" Player=")?;
                        let id = head.strip_prefix("id=")?.parse().ok()?;
                        let (owner, count) = rest.rsplit_once(" EntitiesCount=")?;
                        let expected_count = count.parse().ok()?;
                        if expected_count > 1024 { return None; }
                        Some(ChoiceSubmission { id, owner_entity: resolve(owner), expected_count,
                            entities: Vec::new(), malformed_records: 0, list_complete: expected_count == 0 })
                    })();
                    if let Some(submission) = &parsed {
                        if let Some(set) = result.sets.get_mut(&submission.id) { set.stale = true; }
                    } else { result.malformed_records += 1; }
                    submitting = parsed.is_some();
                    result.latest_submission = parsed;
                } else if submitting {
                    let submission = result.latest_submission.as_mut().expect("active submission");
                    let parsed = entry(text, "Entities[");
                    if let Some((_, entity)) = parsed.filter(|(index, entity)|
                        *index == submission.entities.len() && *index < submission.expected_count as usize
                            && !submission.entities.contains(entity)) {
                        submission.entities.push(entity);
                    } else {
                        submission.malformed_records += 1; result.malformed_records += 1;
                    }
                    submission.list_complete = submission.malformed_records == 0
                        && submission.entities.len() == submission.expected_count as usize;
                } else { result.malformed_records += 1; }
                continue;
            }
            submitting = false;
            if line.contains(" GameState.DebugPrintPower() - ") || line.contains(" GameState.SendChoices() - ")
                || line.contains(" GameState.SendOption() - ") || line.contains(" GameState.DebugPrintOptions() - ") {
                for set in result.sets.values_mut() { set.stale = true; }
            }
        }
        result
    }
}
