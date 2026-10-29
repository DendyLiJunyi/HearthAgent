//! Incremental file transport with conservative, read-only JSON snapshots.
//! For correctness with late player aliases, the active game's lines are reduced
//! again per changed batch. This is NOT yet an O(1) per-event reducer.
use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::time::SystemTime;
use crate::replay::{self, Game};
use crate::replay::{MAX_GAME_BYTES, MAX_LINE};
use crate::export::game_json;
pub use crate::export::quote;

const MAX_BATCH: u64 = 4 * 1024 * 1024;

/// Current game only; names remain in private parsing buffers, never JSON.
#[derive(Default)]
pub struct StreamState {
    pending: Vec<u8>,
    lines: Vec<String>,
    size: usize,
    pub game_number: u64,
}

impl StreamState {
    pub fn feed(&mut self, bytes: &[u8]) -> io::Result<bool> {
        self.pending.extend_from_slice(bytes);
        let mut changed = false;
        let mut consumed = 0;
        while let Some(end) = self.pending[consumed..].iter().position(|b| *b == b'\n') {
            let end = consumed + end;
            if end - consumed > MAX_LINE { return Err(io::Error::new(io::ErrorKind::InvalidData, "log line exceeds limit")); }
            let line = std::str::from_utf8(&self.pending[consumed..end])
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?.trim_end_matches('\r');
            if line.split_once(" GameState.DebugPrintPower() - ").map(|(_, s)| s.trim()) == Some("CREATE_GAME") {
                self.lines.clear(); self.size = 0; self.game_number += 1;
                changed = true;
            }
            if self.game_number > 0 && replay::relevant_line(line) {
                self.size += line.len();
                if self.size > MAX_GAME_BYTES { return Err(io::Error::new(io::ErrorKind::InvalidData, "active game exceeds limit")); }
                self.lines.push(line.to_string()); changed = true;
            }
            consumed = end + 1;
        }
        self.pending.drain(..consumed);
        if self.pending.len() > MAX_LINE { return Err(io::Error::new(io::ErrorKind::InvalidData, "unfinished line exceeds limit")); }
        Ok(changed)
    }

    pub fn game(&self) -> Option<Game> {
        (self.game_number > 0).then(|| replay::build_game(&self.lines))
    }

    pub fn pending_bytes(&self) -> usize { self.pending.len() }
}

fn latest_power(root: &Path) -> io::Result<Option<PathBuf>> {
    let entries = match fs::read_dir(root.join("Logs")) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e),
    };
    let mut sessions = Vec::new();
    for entry in entries {
        let entry = entry?;
        if entry.file_type()?.is_dir() && crate::diagnostics::session_name(&entry.file_name().to_string_lossy()) {
            sessions.push(entry.path());
        }
    }
    sessions.sort();
    Ok(sessions.pop().map(|p| p.join("Power.log")))
}

pub struct Watcher {
    root: PathBuf,
    path: Option<PathBuf>,
    created: Option<SystemTime>,
    offset: u64,
    prefix: Vec<u8>,
    boundary: Vec<u8>,
    state: StreamState,
    generation: u64,
    revision: u64,
    last: Option<String>,
    cached_game: String,
    perspective: Option<u32>,
    run_id: String,
}

impl Watcher {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into(), path: None, created: None, offset: 0,
            prefix: Vec::new(), boundary: Vec::new(), state: StreamState::default(),
            generation: 0, revision: 0, last: None, cached_game: "null".into(), perspective: None,
            run_id: format!("{}-{}", std::process::id(), SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap_or_default().as_nanos()) }
    }

    fn reset(&mut self) {
        self.offset = 0; self.prefix.clear(); self.boundary.clear();
        self.state = StreamState::default(); self.created = None; self.generation += 1;
        self.cached_game = "null".into();
        self.perspective = None;
    }

    fn emit(&mut self, status: &str, lag: bool) -> Option<String> {
        let game = &self.cached_game;
        let session = self.path.as_ref().and_then(|p| p.parent()).and_then(|p| p.file_name())
            .map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        let content = format!("\"session_id\":{},\"generation\":{},\"game_number\":{},\"status\":{},\"pending_bytes\":{},\"backlog\":{},\"game\":{}",
            quote(&format!("{}:{}:{}", self.run_id, session, self.generation)), self.generation,
            self.state.game_number, quote(status), self.state.pending_bytes(), lag, game);
        if self.last.as_deref() == Some(&content) { return None; }
        self.last = Some(content.clone()); self.revision += 1;
        let now = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap_or_default().as_millis();
        Some(format!("{{\"protocol_version\":1,\"revision\":{},\"observed_at_unix_ms\":{},\"complete\":false,\"actionable\":false,\"perspective\":{},\"reason\":\"rules_and_live_stability_not_verified\",{}}}", self.revision, now,
            self.perspective.map(|p| p.to_string()).unwrap_or("null".into()), content))
    }

    /// On I/O or parsing failure caller must stop consuming prior snapshots.
    pub fn poll(&mut self) -> io::Result<Option<String>> {
        let result = self.poll_inner();
        if result.is_err() { self.reset(); self.last = None; }
        result
    }

    fn poll_inner(&mut self) -> io::Result<Option<String>> {
        if !self.root.is_dir() { return Err(io::Error::new(io::ErrorKind::NotFound, "installation root missing")); }
        let path = latest_power(&self.root)?;
        if path != self.path { self.reset(); self.path = path; }
        let Some(path) = self.path.as_ref() else { return Ok(self.emit("waiting_for_session", false)); };
        let mut file = match File::open(path) {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                if self.offset > 0 { self.reset(); }
                return Ok(self.emit("waiting_for_power_log", false));
            }
            Err(e) => return Err(e),
        };
        let metadata = file.metadata()?;
        let length = metadata.len();
        let created = metadata.created().ok();
        let mut replaced = length < self.offset || (self.created.is_some() && created != self.created);
        if !replaced && self.offset > 0 {
            let mut prefix = vec![0; self.prefix.len()];
            file.read_exact(&mut prefix)?;
            file.seek(SeekFrom::Start(self.offset - self.boundary.len() as u64))?;
            let mut boundary = vec![0; self.boundary.len()]; file.read_exact(&mut boundary)?;
            replaced = prefix != self.prefix || boundary != self.boundary;
        }
        if replaced { self.reset(); }
        self.created = created;
        file.seek(SeekFrom::Start(self.offset))?;
        let amount = (length - self.offset).min(MAX_BATCH);
        if amount > 0 {
            let mut bytes = vec![0; amount as usize]; file.read_exact(&mut bytes)?;
            if self.prefix.is_empty() { self.prefix = bytes[..bytes.len().min(128)].to_vec(); }
            if self.state.feed(&bytes)? {
                let game = self.state.game();
                self.perspective = game.as_ref().and_then(|g| g.perspective.player_id());
                self.cached_game = game.as_ref().map(game_json).unwrap_or("null".into());
            }
            self.offset += amount;
            let boundary_len = self.offset.min(128) as usize;
            file.seek(SeekFrom::Start(self.offset - boundary_len as u64))?;
            self.boundary = vec![0; boundary_len]; file.read_exact(&mut self.boundary)?;
        }
        Ok(self.emit(if self.state.game_number == 0 { "waiting_for_create_game" } else { "observed_log_state" }, self.offset < length))
    }
}
