use hearth_agent::controller::{Controller, ExecutionWindow};
use hearth_agent::executor::RecordingExecutor;
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::{Action, Candidate, Observation, Phase, Snapshot};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("review-submissions") {
        if args.len() != 2 {
            eprintln!("Usage: hearth-agent review-submissions <Power.log>");
            std::process::exit(2);
        }
        if let Err(error) = review_submissions(&args[1]) {
            eprintln!("Submission review failed: {error}");
            std::process::exit(1);
        }
        return;
    }
    if args.first().map(String::as_str) == Some("review-choices") {
        if args.len() != 2 {
            eprintln!("Usage: hearth-agent review-choices <Power.log>");
            std::process::exit(2);
        }
        if let Err(error) = review_choices(&args[1]) {
            eprintln!("Choice review failed: {error}");
            std::process::exit(1);
        }
        return;
    }
    if args.first().map(String::as_str) == Some("loop-demo") {
        if args.len() != 1 {
            eprintln!("Usage: hearth-agent loop-demo");
            std::process::exit(2);
        }
        if let Err(error) = loop_demo() {
            eprintln!("Loop demo failed: {error}");
            std::process::exit(1);
        }
        return;
    }
    if matches!(args.first().map(String::as_str), Some("advise" | "advise-choice")) {
        if args.len() < 2 || args.len() > 3 {
            eprintln!("Usage: hearth-agent advise|advise-choice <Power.log> [http://127.0.0.1:8791]");
            std::process::exit(2);
        }
        let endpoint = args.get(2).map(String::as_str).unwrap_or("http://127.0.0.1:8791");
        match advise(&args[1], endpoint, args[0] == "advise-choice") {
            Ok(report) => println!("{report}"),
            Err(error) => { eprintln!("Advice failed: {error}"); std::process::exit(1); }
        }
        return;
    }
    if args.first().map(String::as_str) == Some("deck") {
        if args.len() > 2 {
            eprintln!("Usage: hearth-agent deck [deck-code]");
            std::process::exit(2);
        }
        let profile = hearth_agent::deck::target_profile();
        let code = args.get(1).map(String::as_str).unwrap_or_else(|| profile["deck_code"].as_str().expect("target deck code"));
        match hearth_agent::deck::decode(code) {
            Ok(deck) => println!("{}", serde_json::json!({"deck": deck, "legality_verified": false,
                "target_profile": if code == profile["deck_code"].as_str().unwrap() { profile } else { serde_json::Value::Null }})),
            Err(error) => { eprintln!("Deck decode failed: {error}"); std::process::exit(1); }
        }
        return;
    }
    if args.first().map(String::as_str) == Some("review") {
        if args.len() != 2 {
            eprintln!("Usage: hearth-agent review <Power.log>");
            std::process::exit(2);
        }
        if let Err(error) = review(&args[1]) {
            eprintln!("Review failed: {error}");
            std::process::exit(1);
        }
        return;
    }
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
        println!("Hearth Agent 0.1.0\nCommands: demo; loop-demo; deck [deck-code]; laya-demo [loopback-url]; inspect [directory]; replay <Power.log> [--json]; review <Power.log>; advise <Power.log> [loopback-url]; watch <directory> [--once]\nRead-only observation and offline demo; no game input is sent.");
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
    let window = ExecutionWindow::new(&observation.snapshot, std::time::Duration::from_secs(10))
        .expect("valid demo budget");
    let decision = policy.decide(&observation).expect("demo candidates exist");
    println!("Observation: {:?}", observation.snapshot);
    println!("Decision: {decision:?}");
    // Offline fixture is immutable; live operation must reacquire the observation here.
    let outcome = controller.execute(&observation, &decision, &window, &mut executor).expect("valid demo");
    println!("Outcome: {outcome:?} (no game input sent)");
    println!("Duplicate: {:?}", controller.execute(&observation, &decision, &window, &mut executor));
}

fn loop_demo() -> std::io::Result<()> {
    use std::collections::VecDeque;
    use std::io::Write;
    use hearth_agent::protocol::ObservationSource;
    use hearth_agent::runner::StepRunner;
    struct Source(VecDeque<Observation>);
    impl ObservationSource for Source {
        fn observe(&mut self) -> Result<Observation, String> {
            self.0.pop_front().ok_or_else(|| "synthetic observations exhausted".into())
        }
    }
    let initial = Observation {
        snapshot: Snapshot { session_id: "synthetic-loop-demo".into(), revision: 1, phase: Phase::OurTurn, complete: true },
        candidates: vec![Candidate { id: "end".into(), action: Action::EndTurn }],
    };
    let stdout = std::io::stdout();
    let mut output = stdout.lock();
    for scenario in ["stable", "changed_revision", "changed_candidate", "cancelled", "duplicate"] {
        let mut runner = StepRunner::default();
        let mut refreshed = initial.clone();
        match scenario {
            "changed_revision" => refreshed.snapshot.revision += 1,
            "changed_candidate" => refreshed.candidates[0].action = Action::Attack { source: 10, target: 20 },
            "cancelled" => runner.stop_token().stop(),
            _ => {},
        }
        let mut executor = RecordingExecutor::default();
        let mut policy = FirstCandidatePolicy::default();
        let mut source = Source([initial.clone(), refreshed.clone(), initial.clone(), refreshed].into());
        if scenario == "duplicate" {
            runner.step(&mut source, &mut policy, &mut executor, std::time::Duration::from_secs(10));
        }
        let result = runner.step(&mut source, &mut policy, &mut executor, std::time::Duration::from_secs(10));
        writeln!(output, "{}", serde_json::json!({"source": "synthetic_loop_demo",
            "scenario": scenario, "game_input_sent": false, "recorded_actions": executor.records.len(),
            "trace": result.trace}))?;
    }
    Ok(())
}

fn review_submissions(path: &str) -> std::io::Result<()> {
    use std::io::{Read, Write};
    let file = std::fs::File::open(path)?;
    let length = file.metadata()?.len();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut output_error = None;
    hearth_agent::replay::visit_option_submissions(std::io::BufReader::new(file.take(length)),
        &mut |number, game| {
            if output_error.is_some() { return; }
            let row = serde_json::json!({
                "protocol_version": 1, "source": "offline_option_submission",
                "game_number": number, "actionable": false, "complete": false,
                "submission_number": game.options.submissions_seen,
                "malformed_submissions": game.options.malformed_submissions,
                "submission": game.options.latest_submission,
            });
            if let Err(error) = writeln!(out, "{row}") { output_error = Some(error); }
        })?;
    match output_error { Some(error) => Err(error), None => Ok(()) }
}

fn review_choices(path: &str) -> std::io::Result<()> {
    use std::io::{Read, Write};
    let file = std::fs::File::open(path)?;
    let length = file.metadata()?.len();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut output_error = None;
    hearth_agent::replay::visit_choice_windows(std::io::BufReader::new(file.take(length)),
        &mut |number, game, boundary, window| {
            if output_error.is_some() { return; }
            let board = hearth_agent::export::board_json(&hearth_agent::board::BoardView::from_game(game));
            let line = format!("{{\"protocol_version\":1,\"source\":\"offline_choice_window\",\"game_number\":{number},\"actionable\":false,\"complete\":false,\"packet_boundary_observed\":{boundary},\"window\":{},\"board\":{board},\"logged_choices\":{},\"choice_preview\":{}}}",
                serde_json::to_string(&window).expect("choice window is JSON-safe"),
                serde_json::to_string(&game.choices).expect("choices are JSON-safe"),
                serde_json::to_string(&hearth_agent::choice_preview::ChoicePreview::from_game(game))
                    .expect("choice preview is JSON-safe"));
            if let Err(error) = writeln!(out, "{line}") { output_error = Some(error); }
        })?;
    match output_error { Some(error) => Err(error), None => Ok(()) }
}

fn review(path: &str) -> std::io::Result<()> {
    use std::io::{Read, Write};
    let file = std::fs::File::open(path)?;
    let length = file.metadata()?.len();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut output_error = None;
    hearth_agent::replay::visit_option_windows(std::io::BufReader::new(file.take(length)),
        &mut |number, game, boundary| {
            if output_error.is_some() { return; }
            let preview = hearth_agent::preview::ActionPreview::from_game(game);
            let board = hearth_agent::export::board_json(&hearth_agent::board::BoardView::from_game(game));
            let line = format!("{{\"protocol_version\":1,\"source\":\"offline_option_window\",\"game_number\":{number},\"actionable\":false,\"complete\":false,\"packet_boundary_observed\":{boundary},\"board\":{board},\"action_preview\":{}}}",
                serde_json::to_string(&preview).expect("preview contains only JSON-safe values"));
            if let Err(error) = writeln!(out, "{line}") { output_error = Some(error); }
        })?;
    match output_error { Some(error) => Err(error), None => Ok(()) }
}

fn advise(path: &str, endpoint: &str, choice_mode: bool) -> Result<serde_json::Value, String> {
    use std::io::Read;
    use hearth_agent::laya::{LayaConfig, LayaPolicy};
    let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let length = file.metadata().map_err(|e| e.to_string())?.len();
    let replay = hearth_agent::replay::read(std::io::BufReader::new(file.take(length))).map_err(|e| e.to_string())?;
    let mut report = serde_json::json!({"source":"frozen_log_advice", "actionable":false,
        "complete":false, "game_input_sent":false, "model_query_attempted":false,
        "game_number":replay.games.len(), "ignored_partial_line":replay.ignored_partial_line});
    let Some(game) = replay.games.last() else {
        report["status"] = "no_game".into();
        return Ok(report);
    };
    let (candidates, phase, revision, extra) = if choice_mode {
        report["source"] = "frozen_choice_advice".into();
        let preview = hearth_agent::choice_preview::ChoicePreview::from_game(game);
        report["choice_preview"] = serde_json::to_value(&preview).map_err(|e| e.to_string())?;
        let Some(choice) = preview.choice else {
            report["status"] = "blocked".into();
            return Ok(report);
        };
        let candidates: Vec<Candidate> = choice.offered_cards.iter().map(|card| Candidate {
            id: format!("choice-{}-entity-{}", choice.choice_id, card.entity_id),
            action: Action::ChooseOptions { choice_id: choice.choice_id, entities: vec![card.entity_id] },
        }).collect();
        // Frozen-file byte length is a diagnostic revision, not a live transaction sequence.
        (candidates, Phase::Choosing, length, serde_json::json!({"offered_choice": choice}))
    } else {
        let preview = hearth_agent::preview::ActionPreview::from_game(game);
        report["action_preview"] = serde_json::to_value(&preview).map_err(|e| e.to_string())?;
        let candidates = preview.candidates.iter().map(|c| Candidate {
            id: c.id.clone(), action: c.action.clone(),
        }).collect();
        (candidates, Phase::OurTurn, preview.observed_power_sequence.unwrap_or(0),
            serde_json::json!({"omitted": preview.omitted}))
    };
    if replay.ignored_partial_line || candidates.is_empty() {
        report["status"] = "blocked".into();
        return Ok(report);
    }
    let snapshot = Snapshot {
        session_id: format!("frozen-advice-{}-{}-{}", std::process::id(), replay.games.len(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos()),
        revision, phase, complete: false,
    };
    let observation = Observation { snapshot, candidates };
    let board: serde_json::Value = serde_json::from_str(&hearth_agent::export::board_json(
        &hearth_agent::board::BoardView::from_game(game))).map_err(|e| e.to_string())?;
    let mut policy = LayaPolicy::new(endpoint, LayaConfig::default())?;
    let board = hearth_agent::model_state::compact_board(&board)?;
    let mut state = serde_json::json!({"observation":board, "candidate_coverage_complete":false});
    state.as_object_mut().expect("state is an object")
        .extend(extra.as_object().expect("extra state is an object").clone());
    policy.bind_state(&observation.snapshot, state)?;
    report["model_query_attempted"] = true.into();
    report["advice_method"] = "confidence_gated_original_and_reversed_order".into();
    report["candidate_order_check_required"] = (observation.candidates.len() > 1).into();
    match policy.advise_consistent(&observation) {
        Ok(advice) => {
            report["status"] = "advice".into();
            report["advice"] = serde_json::to_value(advice).map_err(|e| e.to_string())?;
            report["model_report"] = serde_json::to_value(policy.last_report).map_err(|e| e.to_string())?;
        }
        Err(error) => {
            report["status"] = "no_advice".into();
            report["reason"] = error.into();
        }
    }
    Ok(report)
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
