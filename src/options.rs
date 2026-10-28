//! Last logged option packet, preserved for diagnostics only.
//! Logs do not declare a packet length, so this never certifies completeness.
use crate::export::quote;

#[derive(Debug, PartialEq, Eq)]
pub struct Target {
    pub index: u32,
    pub entity_id: u32,
    pub error: String,
}

#[derive(Debug, PartialEq, Eq)]
pub struct LoggedOption {
    pub index: u32,
    pub kind: &'static str,
    pub entity_id: Option<u32>,
    pub error: String,
    pub targets: Vec<Target>,
    pub sub_options: Vec<SubOption>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SubOption {
    pub index: u32,
    pub entity_id: u32,
    pub error: String,
    pub targets: Vec<Target>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct OptionSet {
    pub id: u32,
    pub observed_power_sequence: u64,
    pub stale: bool,
    pub options: Vec<LoggedOption>,
    pub malformed_records: usize,
    pub unsupported_records: usize,
}

#[derive(Default, Debug, PartialEq, Eq)]
pub struct Options {
    pub packets_seen: usize,
    pub malformed_records: usize,
    pub unsupported_records: usize,
    pub latest: Option<OptionSet>,
    pub submissions_seen: usize,
    pub malformed_submissions: usize,
    pub latest_submission: Option<crate::option_submission::OptionSubmission>,
}

fn error_code(text: &str) -> String {
    let code = text.split_whitespace().next().unwrap_or("");
    if matches!(code, "NONE" | "INVALID") || (code.starts_with("REQ_")
        && code.bytes().all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')) {
        code.to_string()
    } else { "UNKNOWN".into() }
}

fn index(text: &str) -> Option<u32> {
    text.split_whitespace().nth(1)?.parse().ok()
}

impl Options {
    pub(crate) fn from_lines(lines: &[String]) -> Self {
        let mut result = Self::default();
        let mut sequence = 0;
        // Once a row cannot be understood, targets cannot safely attach to a prior option.
        let mut target_parent: Option<(usize, Option<usize>)> = None;
        let mut option_parent = None;
        for line in lines {
            if line.contains(" GameState.SendOption() - ") {
                result.submissions_seen += 1;
                result.latest_submission = crate::option_submission::Selection::parse(line)
                    .map(|selection| crate::option_submission::OptionSubmission::new(selection, sequence, result.latest.as_ref()));
                if result.latest_submission.is_none() { result.malformed_submissions += 1; }
            }
            let Some((_, text)) = line.split_once(" GameState.DebugPrintOptions() - ") else {
                if line.contains(" GameState.DebugPrintPower() - ") { sequence += 1; }
                if line.contains(" GameState.DebugPrintPower() - ")
                    || line.contains(" GameState.SendOption() - ")
                    || line.contains(" GameState.SendChoices() - ")
                    || line.contains(" GameState.DebugPrintEntityChoices() - ")
                    || line.contains(" GameState.DebugPrintEntitiesChosen() - ") {
                    if let Some(set) = &mut result.latest { set.stale = true; }
                    target_parent = None;
                    option_parent = None;
                }
                continue;
            };
            let text = text.trim();
            if let Some(id) = text.strip_prefix("id=") {
                result.packets_seen += 1;
                target_parent = None;
                option_parent = None;
                result.latest = id.parse().ok().map(|id| OptionSet {
                    id, observed_power_sequence: sequence, stale: false, options: Vec::new(),
                    malformed_records: 0, unsupported_records: 0,
                });
                if result.latest.is_none() { result.malformed_records += 1; }
                continue;
            }
            let Some(set) = &mut result.latest else {
                result.malformed_records += 1;
                continue;
            };
            if text.starts_with("option ") {
                target_parent = None;
                option_parent = None;
                let parsed = (|| {
                    let index = index(text)?;
                    if index as usize != set.options.len() { return None; }
                    let (head, rest) = text.split_once(" mainEntity=")?;
                    let (reference, error) = rest.rsplit_once(" error=")?;
                    let kind = match head.split_whitespace().find_map(|s| s.strip_prefix("type="))? {
                        "END_TURN" => "END_TURN", "POWER" => "POWER", _ => "UNKNOWN",
                    };
                    let entity_id = if reference.is_empty() && kind == "END_TURN" { None }
                        else { Some(crate::replay::entity_reference(reference)?) };
                    error.split_whitespace().next()?;
                    Some(LoggedOption { index, kind, entity_id, error: error_code(error), targets: Vec::new(), sub_options: Vec::new() })
                })();
                if let Some(option) = parsed {
                    if option.kind == "UNKNOWN" || option.error == "UNKNOWN" {
                        result.unsupported_records += 1; set.unsupported_records += 1;
                    }
                    option_parent = Some(set.options.len());
                    target_parent = Some((set.options.len(), None));
                    set.options.push(option);
                } else { result.malformed_records += 1; set.malformed_records += 1; }
            } else if text.starts_with("subOption ") {
                target_parent = None;
                let parsed = (|| {
                    let parent = option_parent?;
                    let index = index(text)?;
                    if index as usize != set.options[parent].sub_options.len() { return None; }
                    let (_, rest) = text.split_once(" entity=")?;
                    let (reference, error) = rest.rsplit_once(" error=")?;
                    let entity_id = crate::replay::entity_reference(reference)?;
                    error.split_whitespace().next()?;
                    Some((parent, SubOption { index, entity_id, error: error_code(error), targets: Vec::new() }))
                })();
                if let Some((parent, sub)) = parsed {
                    if sub.error == "UNKNOWN" { result.unsupported_records += 1; set.unsupported_records += 1; }
                    target_parent = Some((parent, Some(set.options[parent].sub_options.len())));
                    set.options[parent].sub_options.push(sub);
                } else {
                    result.malformed_records += 1; set.malformed_records += 1;
                    option_parent = None;
                }
            } else if text.starts_with("target ") {
                let parsed = (|| {
                    let (parent, sub) = target_parent?;
                    let index = index(text)?;
                    let targets = match sub {
                        Some(sub) => &set.options[parent].sub_options[sub].targets,
                        None => &set.options[parent].targets,
                    };
                    if index as usize != targets.len() { return None; }
                    let (_, rest) = text.split_once(" entity=")?;
                    let (reference, error) = rest.rsplit_once(" error=")?;
                    let entity_id = crate::replay::entity_reference(reference)?;
                    error.split_whitespace().next()?;
                    Some((parent, sub, Target { index, entity_id, error: error_code(error) }))
                })();
                if let Some((parent, sub, target)) = parsed {
                    if target.error == "UNKNOWN" { result.unsupported_records += 1; set.unsupported_records += 1; }
                    match sub {
                        Some(sub) => set.options[parent].sub_options[sub].targets.push(target),
                        None => set.options[parent].targets.push(target),
                    }
                } else {
                    result.malformed_records += 1; set.malformed_records += 1;
                    target_parent = None;
                }
            } else {
                target_parent = None;
                option_parent = None;
                result.unsupported_records += 1; set.unsupported_records += 1;
            }
        }
        result
    }

    pub fn to_json(&self) -> String {
        let latest = self.latest.as_ref().map(|set| {
            let options = set.options.iter().map(|option| {
                let targets = targets_json(&option.targets);
                let subs = option.sub_options.iter().map(|sub| format!(
                    "{{\"index\":{},\"entity_id\":{},\"error\":{},\"targets\":[{}]}}",
                    sub.index, sub.entity_id, quote(&sub.error), targets_json(&sub.targets)))
                    .collect::<Vec<_>>().join(",");
                format!("{{\"index\":{},\"kind\":{},\"entity_id\":{},\"error\":{},\"targets\":[{}],\"sub_options\":[{}]}}",
                    option.index, quote(option.kind), option.entity_id.map(|v| v.to_string()).unwrap_or("null".into()),
                    quote(&option.error), targets, subs)
            }).collect::<Vec<_>>().join(",");
            format!("{{\"id\":{},\"observed_power_sequence\":{},\"stale\":{},\"complete\":false,\"malformed_records\":{},\"unsupported_records\":{},\"options\":[{}]}}",
                set.id, set.observed_power_sequence, set.stale, set.malformed_records, set.unsupported_records, options)
        }).unwrap_or("null".into());
        format!("{{\"packets_seen\":{},\"malformed_records\":{},\"unsupported_records\":{},\"actionable\":false,\"latest\":{},\"submissions_seen\":{},\"malformed_submissions\":{},\"latest_submission\":{}}}",
            self.packets_seen, self.malformed_records, self.unsupported_records, latest,
            self.submissions_seen, self.malformed_submissions,
            serde_json::to_string(&self.latest_submission).expect("submission contains only JSON-safe fields"))
    }
}

fn targets_json(targets: &[Target]) -> String {
    targets.iter().map(|target| format!(
        "{{\"index\":{},\"entity_id\":{},\"error\":{}}}", target.index, target.entity_id, quote(&target.error)))
        .collect::<Vec<_>>().join(",")
}
