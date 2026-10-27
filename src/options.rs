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
}

#[derive(Debug, PartialEq, Eq)]
pub struct OptionSet {
    pub id: u32,
    pub observed_power_sequence: u64,
    pub stale: bool,
    pub options: Vec<LoggedOption>,
}

#[derive(Default, Debug, PartialEq, Eq)]
pub struct Options {
    pub packets_seen: usize,
    pub malformed_records: usize,
    pub unsupported_records: usize,
    pub latest: Option<OptionSet>,
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
        let mut target_parent = None;
        for line in lines {
            let Some((_, text)) = line.split_once(" GameState.DebugPrintOptions() - ") else {
                if line.contains(" GameState.DebugPrintPower() - ") { sequence += 1; }
                if line.contains(" GameState.DebugPrintPower() - ")
                    || line.contains(" GameState.SendOption() - ")
                    || line.contains(" GameState.SendChoices() - ")
                    || line.contains(" GameState.DebugPrintEntityChoices() - ")
                    || line.contains(" GameState.DebugPrintEntitiesChosen() - ") {
                    if let Some(set) = &mut result.latest { set.stale = true; }
                    target_parent = None;
                }
                continue;
            };
            let text = text.trim();
            if let Some(id) = text.strip_prefix("id=") {
                result.packets_seen += 1;
                target_parent = None;
                result.latest = id.parse().ok().map(|id| OptionSet {
                    id, observed_power_sequence: sequence, stale: false, options: Vec::new(),
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
                    Some(LoggedOption { index, kind, entity_id, error: error_code(error), targets: Vec::new() })
                })();
                if let Some(option) = parsed {
                    if option.kind == "UNKNOWN" || option.error == "UNKNOWN" { result.unsupported_records += 1; }
                    target_parent = Some(set.options.len());
                    set.options.push(option);
                } else { result.malformed_records += 1; }
            } else if text.starts_with("target ") {
                let parsed = (|| {
                    let parent = target_parent?;
                    let index = index(text)?;
                    if index as usize != set.options[parent].targets.len() { return None; }
                    let (_, rest) = text.split_once(" entity=")?;
                    let (reference, error) = rest.rsplit_once(" error=")?;
                    let entity_id = crate::replay::entity_reference(reference)?;
                    error.split_whitespace().next()?;
                    Some((parent, Target { index, entity_id, error: error_code(error) }))
                })();
                if let Some((parent, target)) = parsed {
                    if target.error == "UNKNOWN" { result.unsupported_records += 1; }
                    set.options[parent].targets.push(target);
                } else { result.malformed_records += 1; }
            } else {
                target_parent = None;
                result.unsupported_records += 1;
            }
        }
        result
    }

    pub fn to_json(&self) -> String {
        let latest = self.latest.as_ref().map(|set| {
            let options = set.options.iter().map(|option| {
                let targets = option.targets.iter().map(|target| format!(
                    "{{\"index\":{},\"entity_id\":{},\"error\":{}}}", target.index, target.entity_id, quote(&target.error)))
                    .collect::<Vec<_>>().join(",");
                format!("{{\"index\":{},\"kind\":{},\"entity_id\":{},\"error\":{},\"targets\":[{}]}}",
                    option.index, quote(option.kind), option.entity_id.map(|v| v.to_string()).unwrap_or("null".into()),
                    quote(&option.error), targets)
            }).collect::<Vec<_>>().join(",");
            format!("{{\"id\":{},\"observed_power_sequence\":{},\"stale\":{},\"complete\":false,\"options\":[{}]}}",
                set.id, set.observed_power_sequence, set.stale, options)
        }).unwrap_or("null".into());
        format!("{{\"packets_seen\":{},\"malformed_records\":{},\"unsupported_records\":{},\"actionable\":false,\"latest\":{}}}",
            self.packets_seen, self.malformed_records, self.unsupported_records, latest)
    }
}
