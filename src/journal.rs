//! Exclusively locked, append-only attempt journal. Every record is synced
//! before it is acknowledged. A malformed tail is never silently discarded.
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom, Write};
use std::path::Path;
use serde::{Deserialize, Serialize};

const MAX_BYTES: u64 = 16 * 1024 * 1024;
const MAX_LINE: u64 = 4096;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct Attempt {
    pub session_id: String,
    pub revision: u64,
    pub decision_id: String,
    pub candidate_id: String,
}

impl Attempt {
    fn valid(&self) -> bool {
        [&self.session_id, &self.decision_id, &self.candidate_id].iter()
            .all(|value| !value.is_empty() && value.len() <= 128)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Outcome { Recorded, Confirmed, Uncertain, Failed, NotDispatched }

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    protocol_version: u32,
    sequence: u64,
    attempt: Attempt,
    /// Null records intent before dispatch; a later record supplies the outcome.
    outcome: Option<Outcome>,
}

pub(crate) struct Journal {
    file: File,
    bytes: u64,
    sequence: u64,
    healthy: bool,
}

pub(crate) struct Recovery {
    pub attempts: Vec<Attempt>,
    pub requires_review: bool,
}

impl Journal {
    #[cfg(test)]
    pub(crate) fn read_only_for_test(path: &Path) -> Self {
        Self { file: File::open(path).unwrap(), bytes: 0, sequence: 0, healthy: true }
    }

    pub fn open(path: &Path) -> Result<(Self, Recovery), String> {
        let mut file = OpenOptions::new().read(true).write(true).create(true).truncate(false)
            .open(path).map_err(|_| "cannot open attempt journal")?;
        file.try_lock().map_err(|_| "attempt journal is locked or exclusive locking is unavailable")?;
        let bytes = file.metadata().map_err(|_| "cannot inspect attempt journal")?.len();
        if bytes > MAX_BYTES { return Err("attempt journal exceeds 16 MiB limit".into()); }
        let mut sequence = 0;
        let mut attempts: Vec<(Attempt, Option<Outcome>)> = Vec::new();
        let mut decision_ids = HashMap::new();
        let mut states = std::collections::HashSet::new();
        {
            let mut reader = BufReader::new(&mut file);
            loop {
                let mut line = Vec::new();
                let count = reader.by_ref().take(MAX_LINE + 1).read_until(b'\n', &mut line)
                    .map_err(|_| "cannot read attempt journal")?;
                if count == 0 { break; }
                if count as u64 > MAX_LINE || !line.ends_with(b"\n") {
                    return Err("attempt journal has an oversized or incomplete record; review required".into());
                }
                let entry: Entry = serde_json::from_slice(&line).map_err(|_| "attempt journal has an invalid record; review required")?;
                if entry.protocol_version != 1 || entry.sequence != sequence + 1 || !entry.attempt.valid() {
                    return Err("attempt journal version, sequence, or identity mismatch".into());
                }
                sequence = entry.sequence;
                let key = (entry.attempt.session_id.clone(), entry.attempt.decision_id.clone());
                if let Some(outcome) = entry.outcome {
                    let index: usize = *decision_ids.get(&key).ok_or("journal outcome has no preceding attempt")?;
                    let (attempt, prior_outcome) = &mut attempts[index];
                    if *attempt != entry.attempt || prior_outcome.is_some() {
                        return Err("journal outcome does not match one unresolved attempt".into());
                    }
                    *prior_outcome = Some(outcome);
                } else {
                    if decision_ids.contains_key(&key)
                        || !states.insert((entry.attempt.session_id.clone(), entry.attempt.revision)) {
                        return Err("duplicate attempt in journal".into());
                    }
                    decision_ids.insert(key, attempts.len());
                    attempts.push((entry.attempt, None));
                }
            }
        }
        file.seek(SeekFrom::End(0)).map_err(|_| "cannot position attempt journal")?;
        let requires_review = attempts.iter().any(|(_, outcome)|
            matches!(outcome, None | Some(Outcome::Uncertain | Outcome::Failed)));
        let recovery = Recovery { attempts: attempts.into_iter().map(|(attempt, _)| attempt).collect(), requires_review };
        Ok((Self { file, bytes, sequence, healthy: true }, recovery))
    }

    pub fn append(&mut self, attempt: &Attempt, outcome: Option<Outcome>) -> Result<(), String> {
        if !self.healthy { return Err("attempt journal is unusable after an earlier write failure".into()); }
        // Poison before any potentially partial operation; only a fully synced record restores health.
        self.healthy = false;
        if !attempt.valid() { return Err("invalid attempt identity".into()); }
        if self.file.metadata().map_err(|_| "cannot inspect attempt journal")?.len() != self.bytes {
            return Err("attempt journal length changed externally".into());
        }
        let sequence = self.sequence.checked_add(1).ok_or("attempt journal sequence exhausted")?;
        let entry = Entry { protocol_version: 1, sequence, attempt: attempt.clone(), outcome };
        let mut data = serde_json::to_vec(&entry).map_err(|_| "cannot encode attempt journal entry")?;
        data.push(b'\n');
        if data.len() as u64 > MAX_LINE || self.bytes + data.len() as u64 > MAX_BYTES {
            return Err("attempt journal size limit reached; review and archive required".into());
        }
        self.file.write_all(&data).and_then(|_| self.file.sync_all())
            .map_err(|_| "attempt journal write or sync failed; review required")?;
        self.sequence = sequence;
        self.bytes += data.len() as u64;
        self.healthy = true;
        Ok(())
    }
}
