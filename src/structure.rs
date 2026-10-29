//! Structural diagnostics for the authoritative Power stream, not UI stability.
//! Record payloads and entity names are deliberately not retained.
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Frame { Block, SubSpell }

#[derive(Default, Debug, PartialEq, Eq)]
pub struct PowerStructure {
    frames: Vec<Frame>,
    metadata: Option<(u32, u32)>, // expected count, next index
    pub blocks_started: usize,
    pub blocks_completed: usize,
    pub sub_spells_started: usize,
    pub sub_spells_completed: usize,
    pub max_depth: usize,
    pub metadata_records: usize,
    pub metadata_entries: usize,
    pub errors: usize,
    pub error_types: BTreeMap<&'static str, usize>,
    pub first_error_power_sequence: Option<u64>,
    power_sequence: u64,
}

impl PowerStructure {
    fn error(&mut self, kind: &'static str) {
        self.errors += 1;
        *self.error_types.entry(kind).or_default() += 1;
        self.first_error_power_sequence.get_or_insert(self.power_sequence);
    }

    pub fn open_blocks(&self) -> usize {
        self.frames.iter().filter(|f| **f == Frame::Block).count()
    }

    pub fn open_sub_spells(&self) -> usize {
        self.frames.iter().filter(|f| **f == Frame::SubSpell).count()
    }

    pub fn pending_metadata_entries(&self) -> u32 {
        self.metadata.map(|(expected, next)| expected - next).unwrap_or(0)
    }

    /// A closed prefix says nothing about animation, freshness, or legal actions.
    pub fn closed(&self) -> bool {
        self.frames.is_empty() && self.metadata.is_none() && self.errors == 0
    }

    fn start(&mut self, frame: Frame) {
        self.frames.push(frame);
        self.max_depth = self.max_depth.max(self.frames.len());
    }

    fn end(&mut self, frame: Frame) {
        if self.frames.last() == Some(&frame) {
            self.frames.pop();
            match frame {
                Frame::Block => self.blocks_completed += 1,
                Frame::SubSpell => self.sub_spells_completed += 1,
            }
        } else {
            // Keep the stack and a sticky error: never manufacture a clean boundary.
            self.error(match frame { Frame::Block => "unmatched_block_end", Frame::SubSpell => "unmatched_sub_spell_end" });
        }
    }

    pub(crate) fn observe(&mut self, text: &str) {
        self.power_sequence += 1;
        let kind = text.split_whitespace().next().unwrap_or("");
        if kind.starts_with("Info[") {
            let index = kind.strip_prefix("Info[").and_then(|s| s.strip_suffix(']'))
                .and_then(|s| s.parse::<u32>().ok());
            if let (Some(index), Some((expected, next))) = (index, self.metadata) {
                if index == next && text.split_once('=').is_some_and(|(_, v)| !v.trim().is_empty()) {
                    self.metadata_entries += 1;
                    self.metadata = (next + 1 < expected).then_some((expected, next + 1));
                    return;
                }
            }
            self.error("invalid_metadata_entry");
            return;
        }
        if self.metadata.take().is_some() { self.error("missing_metadata_entries"); }
        match kind {
            "BLOCK_START" => {
                if !text.split_whitespace().any(|t| t.strip_prefix("BlockType=").is_some_and(|v| !v.is_empty())) {
                    self.error("missing_block_type");
                }
                self.blocks_started += 1;
                self.start(Frame::Block);
            }
            "BLOCK_END" if text == "BLOCK_END" => self.end(Frame::Block),
            "SUB_SPELL_START" => {
                if !text.split_whitespace().any(|t| t.strip_prefix("Source=").is_some_and(|v| !v.is_empty())) {
                    self.error("missing_sub_spell_source");
                }
                self.sub_spells_started += 1;
                self.start(Frame::SubSpell);
            }
            "SUB_SPELL_END" if text == "SUB_SPELL_END" => self.end(Frame::SubSpell),
            "BLOCK_END" | "SUB_SPELL_END" => self.error("malformed_end_record"),
            "META_DATA" => {
                self.metadata_records += 1;
                match text.split_whitespace().find_map(|t| t.strip_prefix("InfoCount="))
                    .and_then(|n| n.parse::<u32>().ok()) {
                    Some(0) => {},
                    Some(count) => self.metadata = Some((count, 0)),
                    None => self.error("invalid_metadata_count"),
                }
            }
            _ => {},
        }
    }

    pub fn to_json(&self) -> String {
        let error_types = self.error_types.iter().map(|(kind, count)| format!("\"{kind}\":{count}"))
            .collect::<Vec<_>>().join(",");
        let first_error = self.first_error_power_sequence.map(|s| s.to_string()).unwrap_or("null".into());
        format!(concat!("{{\"blocks_started\":{},\"blocks_completed\":{},",
            "\"sub_spells_started\":{},\"sub_spells_completed\":{},",
            "\"open_blocks\":{},\"open_sub_spells\":{},\"max_depth\":{},",
            "\"metadata_records\":{},\"metadata_entries\":{},",
            "\"pending_metadata_entries\":{},\"errors\":{},\"closed\":{},",
            "\"error_types\":{{{}}},\"first_error_power_sequence\":{}}}"),
            self.blocks_started, self.blocks_completed, self.sub_spells_started,
            self.sub_spells_completed, self.open_blocks(), self.open_sub_spells(),
            self.max_depth, self.metadata_records, self.metadata_entries,
            self.pending_metadata_entries(), self.errors, self.closed(), error_types, first_error)
    }
}
