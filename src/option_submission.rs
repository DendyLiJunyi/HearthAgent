//! Correlate a client send with the option packet visible at that instant.
//! Matching a log record is neither a legality check nor execution confirmation.
use crate::options::OptionSet;
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Selection {
    pub option: u32,
    pub sub_option: i32,
    pub target: u32,
    pub position: u32,
}

impl Selection {
    pub(crate) fn parse(line: &str) -> Option<Self> {
        let (_, text) = line.split_once(" GameState.SendOption() - ")?;
        let mut fields = text.split_whitespace();
        let option = fields.next()?.strip_prefix("selectedOption=")?.parse().ok()?;
        let sub_option = fields.next()?.strip_prefix("selectedSubOption=")?.parse().ok()?;
        let target = fields.next()?.strip_prefix("selectedTarget=")?.parse().ok()?;
        let position = fields.next()?.strip_prefix("selectedPosition=")?.parse().ok()?;
        if fields.next().is_some() || sub_option < -1 { return None; }
        Some(Self { option, sub_option, target, position })
    }
}

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct OptionSubmission {
    pub selection: Selection,
    pub power_sequence: u64,
    pub correlation: Correlation,
}

#[derive(Default, Debug, PartialEq, Eq, Serialize)]
pub struct Correlation {
    pub packet_id: Option<u32>,
    pub packet_was_stale: Option<bool>,
    pub packet_malformed_records: Option<usize>,
    pub packet_unsupported_records: Option<usize>,
    pub option_seen: Option<bool>,
    pub option_kind: Option<&'static str>,
    pub source_entity: Option<u32>,
    pub option_error: Option<String>,
    pub sub_option_seen: Option<bool>,
    pub sub_option_entity: Option<u32>,
    pub sub_option_error: Option<String>,
    /// Null for target zero or an unresolved parent; false means unobserved.
    pub target_seen: Option<bool>,
    pub target_ambiguous: bool,
    pub target_error: Option<String>,
    pub candidate_list_complete: bool,
    pub legality_verified: bool,
    pub execution_confirmed: bool,
}

impl OptionSubmission {
    pub(crate) fn new(selection: Selection, power_sequence: u64, packet: Option<&OptionSet>) -> Self {
        let mut correlation = Correlation::default();
        if let Some(packet) = packet {
            correlation.packet_id = Some(packet.id);
            correlation.packet_was_stale = Some(packet.stale);
            correlation.packet_malformed_records = Some(packet.malformed_records);
            correlation.packet_unsupported_records = Some(packet.unsupported_records);
            let option = packet.options.iter().find(|option| option.index == selection.option);
            correlation.option_seen = Some(option.is_some());
            if let Some(option) = option {
                correlation.option_kind = Some(option.kind);
                correlation.source_entity = option.entity_id;
                correlation.option_error = Some(option.error.clone());
                let targets = if selection.sub_option == -1 {
                    Some(&option.targets)
                } else {
                    let sub = option.sub_options.iter().find(|sub| sub.index == selection.sub_option as u32);
                    correlation.sub_option_seen = Some(sub.is_some());
                    sub.map(|sub| {
                        correlation.sub_option_entity = Some(sub.entity_id);
                        correlation.sub_option_error = Some(sub.error.clone());
                        &sub.targets
                    })
                };
                if let Some(targets) = targets.filter(|_| selection.target != 0) {
                    let mut matches = targets.iter().filter(|target| target.entity_id == selection.target);
                    let target = matches.next();
                    correlation.target_seen = Some(target.is_some());
                    correlation.target_ambiguous = matches.next().is_some();
                    if !correlation.target_ambiguous {
                        correlation.target_error = target.map(|target| target.error.clone());
                    }
                }
            }
        }
        Self { selection, power_sequence, correlation }
    }
}
