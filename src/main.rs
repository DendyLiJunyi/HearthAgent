use hearth_agent::controller::Controller;
use hearth_agent::executor::RecordingExecutor;
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::{Action, Candidate, Observation, Phase, Snapshot};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("laya-demo") {
        if args.len() > 2 {
            eprintln!("Usage: hearth-agent laya-demo [http://127.0.0.1:8791]");
            std::process::exit(2);
        }
        let endpoint = args.get(1).map(String::as_str).unwrap_or("http://127.0.0.1:8791");
        if let Err(error) = laya_demo(endpoint) {
            eprintln!("Laya demo failed: {error}");
            std::process::exit(1);
        }
        return;
    }
    if args.first().map(String::as_str) == Some("watch") {
        if args.len() < 2 || args.len() > 3 || (args.len() == 3 && args[2] != "--once") {
            eprintln!("Usage: hearth-agent watch <installation-directory> [--once]");
            std::process::exit(2);
        }
        let mut watcher = hearth_agent::watch::Watcher::new(&args[1]);
        use std::io::Write;
        let stdout = std::io::stdout();
        let mut out = stdout.lock();
        loop {
            match watcher.poll() {
                Ok(Some(json)) => {
                    if writeln!(out, "{json}").and_then(|_| out.flush()).is_err() { break; }
                }
                Ok(None) => {},
                Err(error) => {
                    let _ = writeln!(out, "{{\"protocol_version\":1,\"status\":\"error\",\"complete\":false,\"actionable\":false,\"game\":null}}");
                    let _ = out.flush();
                    eprintln!("Watch stopped; invalidate prior snapshot: {error}");
                    std::process::exit(1);
                }
            }
            if args.len() == 3 { break; }
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        return;
    }
    if args.first().map(String::as_str) == Some("replay") {
        if args.len() < 2 || args.len() > 3 || (args.len() == 3 && args[2] != "--json") {
            eprintln!("Usage: hearth-agent replay <Power.log> [--json]");
            std::process::exit(2);
        }
        use std::io::Read;
        let result = (|| -> std::io::Result<_> {
            let file = std::fs::File::open(&args[1])?;
            let length = file.metadata()?.len();
            hearth_agent::replay::read(std::io::BufReader::new(file.take(length)))
        })();
        match result {
            Ok(replay) if args.len() == 3 => {
                use std::io::Write;
                let stdout = std::io::stdout();
                let mut out = stdout.lock();
                for (index, game) in replay.games.iter().enumerate() {
                    if writeln!(out, "{{\"protocol_version\":1,\"source\":\"offline_replay\",\"game_number\":{},\"complete\":false,\"actionable\":false,\"ignored_partial_line\":{},\"game\":{}}}",
                        index + 1, replay.ignored_partial_line, hearth_agent::export::game_json(game)).is_err() { break; }
                }
            }
            Ok(replay) => hearth_agent::replay::print_summary(&replay),
            Err(error) => { eprintln!("Replay failed: {error}"); std::process::exit(1); }
        }
        return;
    }
    if args.first().map(String::as_str) == Some("inspect") {
        if args.len() > 2 {
            eprintln!("Usage: hearth-agent inspect [installation-directory]");
            std::process::exit(2);
        }
        let root = args.get(1).map(String::as_str).unwrap_or("D:/Hearthstone");
        match hearth_agent::diagnostics::inspect(std::path::Path::new(root)) {
            Ok(report) => hearth_agent::diagnostics::print_report(&report),
            Err(error) => {
                eprintln!("Inspection failed: {error}");
                std::process::exit(1);
            }
        }
        return;
    }
    if args != ["demo"] {
        println!("Hearth Agent 0.1.0\nCommands: demo; laya-demo [loopback-url]; inspect [directory]; replay <Power.log> [--json]; watch <directory> [--once]\nRead-only observation and offline demo; no game input is sent.");
        if !args.is_empty() { std::process::exit(2); }
        return;
    }
    let observation = Observation {
        snapshot: Snapshot {
            session_id: "offline-demo".into(), revision: 1,
            phase: Phase::OurTurn, complete: true,
        },
        candidates: vec![Candidate {
            id: "a0".into(), action: Action::Attack { source: 10, target: 20 },
        }, Candidate { id: "a1".into(), action: Action::EndTurn }],
    };
    let mut policy = FirstCandidatePolicy::default();
    let mut controller = Controller::default();
    let mut executor = RecordingExecutor::default();
    let decision = policy.decide(&observation).expect("demo candidates exist");
    println!("Observation: {:?}", observation.snapshot);
    println!("Decision: {decision:?}");
    // Offline fixture is immutable; live operation must reacquire the observation here.
    let outcome = controller.execute(&observation, &decision, &mut executor).expect("valid demo");
    println!("Outcome: {outcome:?} (no game input sent)");
    println!("Duplicate: {:?}", controller.execute(&observation, &decision, &mut executor));
}

fn laya_demo(endpoint: &str) -> Result<(), String> {
    use hearth_agent::laya::{LayaConfig, LayaPolicy};
    let observation = Observation {
        snapshot: Snapshot { session_id: "synthetic-laya-demo".into(), revision: 1, phase: Phase::OurTurn, complete: true },
        candidates: vec![
            Candidate { id: "attack".into(), action: Action::Attack { source: 10, target: 20 } },
            Candidate { id: "end_turn".into(), action: Action::EndTurn },
        ],
    };
    // Zero cutoff exposes the result for this synthetic smoke test only; it is not a live policy threshold.
    let mut policy = LayaPolicy::new(endpoint, LayaConfig { min_answer_confidence: 0.0, ..LayaConfig::default() })?;
    let state = serde_json::from_str(include_str!("../fixtures/laya/lethal.json")).map_err(|e| e.to_string())?;
    policy.bind_state(&observation.snapshot, state)?;
    let decision = policy.decide(&observation)?;
    let report = policy.last_report.as_ref().ok_or("missing Laya diagnostics")?;
    println!("{}", serde_json::json!({
        "source": "synthetic_laya_demo", "actionable": false, "game_input_sent": false,
        "session_id": decision.session_id, "revision": decision.revision,
        "candidate_id": decision.candidate_id, "expected_candidate_id": "attack",
        "correct": decision.candidate_id == "attack", "probabilities": report.probabilities,
        "answer_confidence": report.answer_confidence, "input_tokens": report.input_tokens,
        "elapsed_ms": report.elapsed_ms,
    }));
    Ok(())
}
