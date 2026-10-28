use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use hearth_agent::controller::{ControlError, Controller, ExecutionWindow};
use hearth_agent::executor::RecordingExecutor;
use hearth_agent::laya::{LayaConfig, LayaPolicy};
use hearth_agent::policy::PolicyBackend;
use hearth_agent::protocol::*;
use serde_json::{json, Value};

fn fixture() -> Observation {
    Observation {
        snapshot: Snapshot { session_id: "synthetic-laya-test".into(), revision: 7, phase: Phase::OurTurn, complete: true },
        candidates: vec![Candidate { id: "attack-choice".into(), action: Action::Attack { source: 10, target: 20 } },
            Candidate { id: "end-turn-choice".into(), action: Action::EndTurn }],
    }
}

fn good() -> Value {
    json!({"answers": {"action": {"type": "choice", "choice": "c0", "probabilities": {"c0": 0.9, "c1": 0.1},
        "answer_confidence": 0.9, "abstention": "passed"}},
        "usage": {"input_tokens": 80, "truncated": false, "state_tokens_dropped": 0, "truncated_questions": []}})
}

fn server(status: u16, body: String, delay: Duration) -> (String, JoinHandle<Value>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
        let mut bytes = Vec::new();
        let header_end = loop {
            let mut buffer = [0; 1024];
            let n = stream.read(&mut buffer).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&buffer[..n]);
            if let Some(index) = bytes.windows(4).position(|s| s == b"\r\n\r\n") { break index + 4; }
            assert!(bytes.len() < 64 * 1024);
        };
        let headers = std::str::from_utf8(&bytes[..header_end]).unwrap().to_lowercase();
        assert!(headers.starts_with("post /v1/systemone http/1.1\r\n"));
        let length: usize = headers.lines().find_map(|line| line.strip_prefix("content-length: ")).unwrap().parse().unwrap();
        while bytes.len() - header_end < length {
            let mut buffer = [0; 1024];
            let n = stream.read(&mut buffer).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&buffer[..n]);
        }
        let request = serde_json::from_slice(&bytes[header_end..header_end + length]).unwrap();
        thread::sleep(delay);
        let response = format!("HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nLocation: http://192.0.2.1/\r\n\r\n{body}", body.len());
        let _ = stream.write_all(response.as_bytes());
        request
    });
    (url, handle)
}

fn policy(url: &str, observation: &Observation, timeout: Duration) -> LayaPolicy {
    let mut policy = LayaPolicy::new(url, LayaConfig { timeout, min_answer_confidence: 0.8 }).unwrap();
    policy.bind_state(&observation.snapshot, json!({"fixture": true, "opponent_health": 3})).unwrap();
    policy
}

#[test]
fn valid_response_preserves_snapshot_and_maps_short_labels_back_to_candidate_ids() {
    let (url, server) = server(200, good().to_string(), Duration::ZERO);
    let observation = fixture();
    let mut policy = policy(&url, &observation, Duration::from_secs(2));
    let window = ExecutionWindow::new(&observation.snapshot, Duration::from_secs(10)).unwrap();
    let decision = policy.decide(&observation).unwrap();
    assert_eq!(decision.candidate_id, "attack-choice");
    assert_eq!(decision.session_id, observation.snapshot.session_id);
    assert_eq!(decision.revision, 7);
    let report = policy.last_report.as_ref().unwrap();
    assert_eq!(report.probabilities["attack-choice"], 0.9);
    assert_eq!(report.input_tokens, 80);
    let request = server.join().unwrap();
    assert_eq!(request["model"], "multilingual");
    assert_eq!(request["min_confidence"], 0.8);
    assert_eq!(request["state"]["revision"], 7);
    assert_eq!(request["questions"]["action"]["criteria"].as_object().unwrap().len(), 2);
    let mut changed = observation.clone();
    changed.snapshot.revision += 1;
    assert_eq!(Controller::default().execute(&changed, &decision, &window, &mut RecordingExecutor::default()), Err(ControlError::StaleDecision));
}

#[test]
fn valid_model_reply_after_dispatch_deadline_never_reaches_executor() {
    let (url, server) = server(200, good().to_string(), Duration::from_millis(30));
    let observation = fixture();
    let mut policy = policy(&url, &observation, Duration::from_secs(2));
    let window = ExecutionWindow::new(&observation.snapshot, Duration::from_millis(10)).unwrap();
    let decision = policy.decide(&observation).unwrap();
    server.join().unwrap();
    let mut executor = RecordingExecutor::default();
    assert_eq!(Controller::default().execute(&observation, &decision, &window, &mut executor),
        Err(ControlError::DeadlineExpired));
    assert!(executor.records.is_empty());
}

#[test]
fn mulligan_choices_and_placement_are_described_without_losing_identity() {
    for (phase, actions, expected_text) in [
        (Phase::Mulligan, [Action::Mulligan { choice_id: 17, replace: vec![] },
            Action::Mulligan { choice_id: 17, replace: vec![10] }], "mulligan packet 17, replace entities []"),
        (Phase::Choosing, [Action::ChooseOptions { choice_id: 23, entities: vec![10, 11] },
            Action::ChooseOptions { choice_id: 23, entities: vec![12] }], "choice packet 23, select entities [10, 11]"),
        (Phase::OurTurn, [Action::PlayCard { source: 10, target: Some(20), position: Some(2) },
            Action::EndTurn], "board position Some(2)"),
    ] {
        let mut input = fixture();
        input.snapshot.phase = phase;
        for (candidate, action) in input.candidates.iter_mut().zip(actions) { candidate.action = action; }
        let (url, server) = server(200, good().to_string(), Duration::ZERO);
        let mut policy = policy(&url, &input, Duration::from_secs(2));
        let window = ExecutionWindow::new(&input.snapshot, Duration::from_secs(10)).unwrap();
        let decision = policy.decide(&input).unwrap();
        let request = server.join().unwrap();
        assert!(request["questions"]["action"]["criteria"]["c0"].as_str().unwrap().contains(expected_text));
        let mut executor = RecordingExecutor::default();
        assert!(Controller::default().execute(&input, &decision, &window, &mut executor).is_ok());
        assert_eq!(executor.records[0].1.action, input.candidates[0].action);
    }
}

#[test]
fn invalid_response_variants_never_produce_decisions() {
    let mut cases = Vec::new();
    let mut value = good(); value["answers"]["action"]["choice"] = json!("invented"); cases.push(value);
    let mut value = good(); value["answers"]["action"]["choice"] = json!("c1"); cases.push(value);
    let mut value = good(); value["answers"]["action"]["probabilities"]["c0"] = json!(-0.1); cases.push(value);
    let mut value = good(); value["answers"]["action"]["probabilities"]["c0"] = json!(0.6); cases.push(value);
    let mut value = good(); value["answers"]["action"]["probabilities"]["extra"] = json!(0.0); cases.push(value);
    let mut value = good(); value["answers"]["action"]["probabilities"] = json!({"c0":1.0}); cases.push(value);
    let mut value = good(); value["answers"]["action"]["answer_confidence"] = json!(0.2); cases.push(value);
    let mut value = good(); value["answers"]["action"]["answer_confidence"] = json!(1.1); cases.push(value);
    let mut value = good(); value["answers"]["action"]["abstention"] = json!("abstained"); cases.push(value);
    let mut value = good(); value["answers"]["action"]["abstention"] = json!(true); cases.push(value);
    let mut value = good(); value["answers"]["action"]["type"] = json!("score"); cases.push(value);
    let mut value = good(); value["usage"]["truncated"] = json!(true); cases.push(value);
    let mut value = good(); value["usage"]["state_tokens_dropped"] = json!(1); cases.push(value);
    let mut value = good(); value["usage"]["truncated_questions"] = json!(["action"]); cases.push(value);
    let mut value = good(); value["usage"]["options"] = json!({"action":{"total":2,"distinct":1}}); cases.push(value);
    let mut value = good(); value["usage"].as_object_mut().unwrap().remove("truncated"); cases.push(value);
    let mut value = good(); value["answers"]["unexpected"] = json!({}); cases.push(value);
    cases.push(json!({}));
    for value in cases {
        let (url, server) = server(200, value.to_string(), Duration::ZERO);
        let observation = fixture();
        let mut policy = policy(&url, &observation, Duration::from_secs(2));
        assert!(policy.decide(&observation).is_err(), "accepted invalid response {value}");
        assert!(policy.last_report.is_none());
        server.join().unwrap();
    }
}

#[test]
fn bounded_transport_rejects_redirects_status_failures_oversize_and_non_json() {
    for (status, body) in [(302, good().to_string()), (503, good().to_string()),
        (200, "not json".into()), (200, " ".repeat(65537))] {
        let (url, server) = server(status, body, Duration::ZERO);
        let observation = fixture();
        assert!(policy(&url, &observation, Duration::from_secs(2)).decide(&observation).is_err());
        server.join().unwrap();
    }
}

#[test]
fn inference_timeout_does_not_return_a_late_decision() {
    let (url, server) = server(200, good().to_string(), Duration::from_millis(300));
    let observation = fixture();
    let mut policy = policy(&url, &observation, Duration::from_millis(50));
    assert!(policy.decide(&observation).unwrap_err().contains("timed out"));
    assert!(policy.last_report.is_none());
    server.join().unwrap();
}

#[test]
fn incomplete_stale_ambiguous_and_large_requests_are_rejected_before_transport() {
    let observation = fixture();
    let mut policy = policy("http://127.0.0.1:9", &observation, Duration::from_secs(1));
    let mut bad = observation.clone(); bad.snapshot.complete = false;
    assert!(policy.decide(&bad).unwrap_err().contains("incomplete"));
    let mut bad = observation.clone(); bad.snapshot.revision += 1;
    assert!(policy.decide(&bad).unwrap_err().contains("does not match"));
    let mut bad = observation.clone(); bad.candidates[1].id = bad.candidates[0].id.clone();
    assert!(policy.decide(&bad).unwrap_err().contains("unique"));
    let mut bad = observation.clone(); bad.candidates.clear();
    assert!(policy.decide(&bad).unwrap_err().contains("1..=16"));
    let mut bad = observation.clone(); bad.candidates = vec![bad.candidates[0].clone(); 17];
    assert!(policy.decide(&bad).unwrap_err().contains("1..=16"));
    let mut bad = observation.clone(); bad.candidates[0].action = Action::ChooseOptions { choice_id: 7, entities: vec![42] };
    assert!(policy.decide(&bad).unwrap_err().contains("phase"));
    assert!(policy.bind_state(&observation.snapshot, json!({"text": "x".repeat(16384)})).is_err());
    assert!(policy.decide(&observation).unwrap_err().contains("no model state"));
}

#[test]
fn only_loopback_http_endpoints_and_finite_configuration_are_accepted() {
    for url in ["https://127.0.0.1:8000", "http://example.com", "http://192.0.2.1",
        "http://localhost:8000", "http://user:pass@127.0.0.1:8000", "http://127.0.0.1:8000/other",
        "http://127.0.0.1:8000/?token=secret", "http://127.0.0.1:8000/#fragment", "http://127.0.0.1:0"] {
        assert!(LayaPolicy::new(url, LayaConfig::default()).is_err(), "{url}");
    }
    assert!(LayaPolicy::new("http://[::1]:8000", LayaConfig::default()).is_ok());
    for cutoff in [f64::NAN, f64::INFINITY, -0.1, 1.1] {
        assert!(LayaPolicy::new("http://127.0.0.1:8000", LayaConfig { min_answer_confidence: cutoff, ..LayaConfig::default() }).is_err());
    }
}

#[test]
fn advisory_ranking_preserves_incompleteness_and_cannot_enable_execution() {
    let mut observation = fixture();
    observation.snapshot.complete = false;
    let (url, server) = server(200, good().to_string(), Duration::ZERO);
    let mut policy = policy(&url, &observation, Duration::from_secs(2));
    let advice = policy.advise(&observation).unwrap();
    assert_eq!(advice.candidate_id, "attack-choice");
    assert_eq!(advice.revision, observation.snapshot.revision);
    let request = server.join().unwrap();
    assert!(request["questions"]["action"]["instructions"].as_str().unwrap().contains("incomplete"));
    assert!(!observation.snapshot.complete);
    assert!(policy.decide(&observation).unwrap_err().contains("incomplete"));
    // Even if an external caller manually fabricates a Decision from advice,
    // the unchanged observation still prevents it reaching the executor.
    let fabricated = Decision { decision_id: "fabricated".into(), session_id: advice.session_id,
        revision: advice.revision, candidate_id: advice.candidate_id };
    let window = ExecutionWindow::new(&observation.snapshot, Duration::from_secs(10)).unwrap();
    assert_eq!(Controller::default().execute(&observation, &fabricated, &window, &mut RecordingExecutor::default()),
        Err(ControlError::IncompleteState));
}

#[test]
fn advisory_path_keeps_confidence_and_response_identity_validation() {
    for invalid in ["low_confidence", "unknown_label"] {
        let mut response = good();
        if invalid == "low_confidence" { response["answers"]["action"]["answer_confidence"] = json!(0.5); }
        else { response["answers"]["action"]["choice"] = json!("invented"); }
        let (url, server) = server(200, response.to_string(), Duration::ZERO);
        let mut observation = fixture();
        observation.snapshot.complete = false;
        let mut policy = policy(&url, &observation, Duration::from_secs(2));
        assert!(policy.advise(&observation).is_err());
        assert!(policy.last_report.is_none());
        server.join().unwrap();
    }
}
