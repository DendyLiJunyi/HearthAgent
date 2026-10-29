//! Read-only installation/log inspection. This is not a complete state parser.
use std::fs::{self, File};
use std::io::{self, BufRead, BufReader};
use std::path::{Path, PathBuf};

#[derive(Debug, Default)]
pub struct PowerSummary {
    pub lines: u64,
    pub create_game: u64,
    pub full_entity: u64,
    pub tag_change: u64,
    pub block_start: u64,
}

#[derive(Debug)]
pub struct InstallationReport {
    pub root: PathBuf,
    pub executable_present: bool,
    pub mono_present: bool,
    pub managed_assembly_present: bool,
    pub latest_session: Option<PathBuf>,
    pub scene: Option<String>,
    pub power: Option<PowerSummary>,
}

/// Select by the timestamp in the standard directory name, not modified time:
/// an old session's contents can be touched after a new session starts.
pub(crate) fn session_name(name: &str) -> bool {
    let Some(suffix) = name.strip_prefix("Hearthstone_") else { return false; };
    let parts: Vec<&str> = suffix.split('_').collect();
    parts.len() == 6 && parts.iter().enumerate().all(|(i, part)| {
        part.len() == if i == 0 { 4 } else { 2 }
            && part.bytes().all(|c| c.is_ascii_digit())
    })
}

pub fn summarize_power(reader: impl BufRead) -> io::Result<PowerSummary> {
    let mut summary = PowerSummary::default();
    for line in reader.lines() {
        let line = line?;
        summary.lines += 1;
        // Diagnostic markers can occur in multiple log streams; these are NOT
        // unique game-event counts and must not drive a state reducer.
        summary.create_game += u64::from(line.contains("CREATE_GAME"));
        summary.full_entity += u64::from(line.contains("FULL_ENTITY"));
        summary.tag_change += u64::from(line.contains("TAG_CHANGE"));
        summary.block_start += u64::from(line.contains("BLOCK_START"));
    }
    Ok(summary)
}

fn read_scene(path: &Path) -> io::Result<Option<String>> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e),
    };
    let mut scene = None;
    for line in BufReader::new(file).lines() {
        let line = line?;
        if let Some((_, rest)) = line.split_once("currMode=") {
            if let Some(mode) = rest.split_whitespace().next() {
                // Print only a scene token; never dump raw player/account logs.
                if !mode.is_empty() && mode.bytes().all(|c| c.is_ascii_uppercase() || c == b'_') {
                    scene = Some(mode.to_string());
                }
            }
        }
    }
    Ok(scene)
}

pub fn inspect(root: &Path) -> io::Result<InstallationReport> {
    if !root.is_dir() {
        return Err(io::Error::new(io::ErrorKind::NotFound, "installation directory does not exist"));
    }
    let mut report = InstallationReport {
        root: root.to_path_buf(),
        executable_present: root.join("Hearthstone.exe").is_file(),
        mono_present: root.join("MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll").is_file(),
        managed_assembly_present: root.join("Hearthstone_Data/Managed/Assembly-CSharp.dll").is_file(),
        latest_session: None, scene: None, power: None,
    };
    let entries = match fs::read_dir(root.join("Logs")) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(report),
        Err(e) => return Err(e),
    };
    let mut sessions = Vec::new();
    for entry in entries {
        let entry = entry?;
        if entry.file_type()?.is_dir() && session_name(&entry.file_name().to_string_lossy()) {
            sessions.push(entry.path());
        }
    }
    sessions.sort();
    if let Some(session) = sessions.pop() {
        report.scene = read_scene(&session.join("LoadingScreen.log"))?;
        match File::open(session.join("Power.log")) {
            Ok(file) => report.power = Some(summarize_power(BufReader::new(file))?),
            Err(e) if e.kind() == io::ErrorKind::NotFound => {},
            Err(e) => return Err(e),
        }
        report.latest_session = Some(session);
    }
    Ok(report)
}

pub fn print_report(report: &InstallationReport) {
    println!("Installation: {}", report.root.display());
    println!("Hearthstone.exe: {}", report.executable_present);
    println!("Mono runtime: {}", report.mono_present);
    println!("Managed game assembly: {}", report.managed_assembly_present);
    match &report.latest_session {
        Some(path) => println!("Latest recorded session: {}", path.display()),
        None => println!("Latest recorded session: none"),
    }
    println!("Last recorded scene: {}", report.scene.as_deref().unwrap_or("unknown"));
    match &report.power {
        Some(power) => println!("Power.log diagnostic marker counts (not deduplicated): {power:?}"),
        None => println!("Power.log: missing in latest session; no battle state can be reconstructed yet."),
    }
    println!("Read-only inspection. Log history does not prove a process is running or state is current.");
    println!("No game input, process attachment, or model invocation performed.");
}
