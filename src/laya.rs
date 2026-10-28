//! Local Laya HTTP policy. Responses are suggestions bound to the input snapshot.
//! This module never generates candidates or performs game input.
use std::collections::BTreeMap;
use std::io::Read;
use std::net::IpAddr;
use std::time::Duration;
use reqwest::blocking::Client;
use reqwest::{redirect, Url};
use serde::Deserialize;
use serde_json::{json, Value};
use crate::policy::PolicyBackend;
use crate::protocol::{Decision, Observation, Snapshot};

const MAX_RESPONSE_BYTES: u64 = 64 * 1024;
const MAX_STATE_BYTES: usize = 16 * 1024;
const MAX_CANDIDATES: usize = 16;

#[derive(Clone, Debug)]
pub struct LayaConfig {
    pub timeout: Duration,
    /// Experimental cutoff, not a claim about Hearthstone calibration.
    pub min_answer_confidence: f64,
}

impl Default for LayaConfig {
    fn default() -> Self {
        Self { timeout: Duration::from_secs(10), min_answer_confidence: 0.8 }
    }
}

#[derive(Clone, Debug, serde::Serialize)]
pub struct LayaReport {
    pub choice_probability: f64,
    pub answer_confidence: f64,
    pub probabilities: BTreeMap<String, f64>,
    pub input_tokens: u64,
    pub elapsed_ms: u128,
}

/// An advisory ranking cannot be passed to Controller::execute, which requires
/// a Decision. Incomplete observations never acquire execution permission here.
#[derive(Debug, serde::Serialize)]
pub struct AdvisoryChoice {
    pub session_id: String,
    pub revision: u64,
    pub candidate_id: String,
}

pub struct LayaPolicy {
    client: Client,
    endpoint: Url,
    config: LayaConfig,
    context: Option<(Snapshot, Value)>,
    sequence: u64,
    pub last_report: Option<LayaReport>,
}

#[derive(Deserialize)]
struct Response {
    answers: BTreeMap<String, Answer>,
    usage: Usage,
}

#[derive(Deserialize)]
struct Answer {
    #[serde(rename = "type")]
    kind: String,
    choice: String,
    probabilities: BTreeMap<String, f64>,
    answer_confidence: f64,
    abstention: String,
}

#[derive(Deserialize)]
struct Usage {
    input_tokens: u64,
    truncated: bool,
    state_tokens_dropped: u64,
    truncated_questions: Vec<String>,
    #[serde(default)]
    options: BTreeMap<String, Value>,
}

impl LayaPolicy {
    pub fn new(base_url: &str, config: LayaConfig) -> Result<Self, String> {
        let mut endpoint = Url::parse(base_url).map_err(|_| "invalid Laya base URL")?;
        let local = endpoint.host_str().map(|h| h.trim_matches(['[', ']']))
            .and_then(|h| h.parse::<IpAddr>().ok()).is_some_and(|ip| ip.is_loopback());
        if endpoint.scheme() != "http" || !local || !endpoint.username().is_empty()
            || endpoint.password().is_some() || endpoint.path() != "/"
            || endpoint.query().is_some() || endpoint.fragment().is_some()
            || endpoint.port() == Some(0) {
            return Err("Laya URL must be a plain HTTP loopback IP and port, without credentials or a path".into());
        }
        if config.timeout.is_zero() || config.timeout > Duration::from_secs(300)
            || !config.min_answer_confidence.is_finite()
            || !(0.0..=1.0).contains(&config.min_answer_confidence) {
            return Err("invalid Laya timeout or confidence cutoff".into());
        }
        endpoint.set_path("/v1/systemone");
        let client = Client::builder().no_proxy().redirect(redirect::Policy::none())
            .timeout(config.timeout).connect_timeout(config.timeout.min(Duration::from_secs(3)))
            .build().map_err(|e| format!("cannot build Laya client: {e}"))?;
        Ok(Self { client, endpoint, config, context: None, sequence: 0, last_report: None })
    }

    /// A producer must supply state and candidates from this exact snapshot.
    /// Binding cannot make an incomplete live observation executable.
    pub fn bind_state(&mut self, snapshot: &Snapshot, state: Value) -> Result<(), String> {
        self.context = None;
        self.last_report = None;
        if !state.is_object() || serde_json::to_vec(&state).map_err(|e| e.to_string())?.len() > MAX_STATE_BYTES {
            return Err("model state must be an object no larger than 16 KiB; it is never truncated".into());
        }
        self.context = Some((snapshot.clone(), state));
        Ok(())
    }

    fn request(&self, observation: &Observation, advisory: bool) -> Result<(Value, BTreeMap<String, String>), String> {
        let snapshot = &observation.snapshot;
        if !advisory && !snapshot.complete { return Err("incomplete observation cannot be sent to a decision policy".into()); }
        let (bound, state) = self.context.as_ref().ok_or("no model state bound to this policy")?;
        if bound != snapshot { return Err("model state does not match the observation snapshot".into()); }
        if snapshot.session_id.is_empty() || snapshot.session_id.len() > 128 {
            return Err("invalid snapshot session ID".into());
        }
        if observation.candidates.is_empty() || observation.candidates.len() > MAX_CANDIDATES {
            return Err("Laya policy requires 1..=16 candidates; candidate sets are never truncated".into());
        }
        let mut criteria = BTreeMap::new();
        let mut mapping = BTreeMap::new();
        let mut seen = std::collections::BTreeSet::new();
        for (index, candidate) in observation.candidates.iter().enumerate() {
            if candidate.id.is_empty() || candidate.id.len() > 128 || !seen.insert(&candidate.id) {
                return Err("candidate IDs must be nonempty, unique, and at most 128 bytes".into());
            }
            if !candidate.action.allowed_in(&snapshot.phase) { return Err("candidate does not match an actionable interaction phase".into()); }
            if !candidate.action.well_formed() { return Err("candidate has an invalid action shape".into()); }
            let description = candidate.action.description();
            // Short labels preserve the option-token budget; map back locally after validation.
            let label = format!("c{index}");
            criteria.insert(label.clone(), description);
            mapping.insert(label, candidate.id.clone());
        }
        let request = json!({
            "model": "multilingual", "max_len": 8192, "head_max_len": 1024,
            "min_confidence": self.config.min_answer_confidence,
            "state": {"session_id": snapshot.session_id, "revision": snapshot.revision, "board": state},
            "questions": {"action": {"type": "choice",
                "instructions": if advisory {
                    "Rank only the supplied Hearthstone actions for read-only advice. The observation and candidate list are incomplete; no action will be executed. Use only the given state."
                } else { "Choose the best supplied Hearthstone action for the acting player. Use only the given state." },
                "criteria": criteria}}
        });
        Ok((request, mapping))
    }
    pub fn advise(&mut self, observation: &Observation) -> Result<AdvisoryChoice, String> {
        let candidate_id = self.query(observation, true)?;
        Ok(AdvisoryChoice { session_id: observation.snapshot.session_id.clone(),
            revision: observation.snapshot.revision, candidate_id })
    }

    fn query(&mut self, observation: &Observation, advisory: bool) -> Result<String, String> {
        self.last_report = None;
        let (request, mapping) = self.request(observation, advisory)?;
        let started = std::time::Instant::now();
        let response = self.client.post(self.endpoint.clone()).json(&request).send()
            .map_err(|e| if e.is_timeout() { "Laya request timed out".into() } else { format!("Laya transport failed: {e}") })?;
        if !response.status().is_success() {
            return Err(format!("Laya returned HTTP {}", response.status().as_u16()));
        }
        let mut bytes = Vec::new();
        response.take(MAX_RESPONSE_BYTES + 1).read_to_end(&mut bytes)
            .map_err(|_| "could not read Laya response before the deadline")?;
        if bytes.len() as u64 > MAX_RESPONSE_BYTES { return Err("Laya response exceeds 64 KiB".into()); }
        let response: Response = serde_json::from_slice(&bytes).map_err(|_| "invalid Laya response schema")?;
        if response.usage.truncated || response.usage.state_tokens_dropped != 0
            || !response.usage.truncated_questions.is_empty() || !response.usage.options.is_empty() {
            return Err("Laya truncated state or collapsed option descriptions".into());
        }
        if response.answers.len() != 1 { return Err("unexpected Laya answer set".into()); }
        let answer = response.answers.get("action").ok_or("Laya omitted the action answer")?;
        if answer.kind != "choice" || answer.abstention != "passed" {
            return Err("Laya abstained or did not return a gated choice".into());
        }
        if !answer.answer_confidence.is_finite() || !(0.0..=1.0).contains(&answer.answer_confidence) {
            return Err("invalid Laya answer confidence".into());
        }
        if answer.answer_confidence < self.config.min_answer_confidence {
            return Err("Laya answer confidence is below the configured cutoff".into());
        }
        if answer.probabilities.keys().ne(mapping.keys()) {
            return Err("Laya probability labels do not match the supplied candidates".into());
        }
        if answer.probabilities.values().any(|p| !p.is_finite() || !(0.0..=1.0).contains(p)) {
            return Err("invalid Laya probability".into());
        }
        // Laya rounds each probability to four decimals; tolerate only that rounding drift.
        let tolerance = mapping.len() as f64 * 0.000051;
        if (answer.probabilities.values().sum::<f64>() - 1.0).abs() > tolerance {
            return Err("Laya probabilities do not sum to one".into());
        }
        let candidate_id = mapping.get(&answer.choice).ok_or("Laya selected an unknown candidate")?;
        let choice_probability = answer.probabilities[&answer.choice];
        if answer.probabilities.values().any(|p| *p > choice_probability + 0.0001) {
            return Err("Laya choice disagrees with its probability distribution".into());
        }
        self.last_report = Some(LayaReport {
            choice_probability, answer_confidence: answer.answer_confidence,
            probabilities: answer.probabilities.iter().map(|(key, p)| (mapping[key].clone(), *p)).collect(),
            input_tokens: response.usage.input_tokens, elapsed_ms: started.elapsed().as_millis(),
        });
        Ok(candidate_id.clone())
    }
}

impl PolicyBackend for LayaPolicy {
    fn decide(&mut self, observation: &Observation) -> Result<Decision, String> {
        let candidate_id = self.query(observation, false)?;
        self.sequence = self.sequence.checked_add(1).ok_or("Laya decision sequence exhausted")?;
        Ok(Decision { decision_id: format!("laya-{}", self.sequence),
            session_id: observation.snapshot.session_id.clone(), revision: observation.snapshot.revision,
            candidate_id })
    }
}
