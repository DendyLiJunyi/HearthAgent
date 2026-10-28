use hearth_agent::controller::{ControlError, Controller, ExecutionWindow};
use hearth_agent::executor::{ExecutionOutcome, RecordingExecutor};
use hearth_agent::protocol::*;
use std::time::Duration;

#[test]
fn actions_are_restricted_to_their_exact_interaction_phase() {
    let cases = [
        (Action::Mulligan { choice_id: 1, replace: vec![] }, Phase::Mulligan),
        (Action::ChooseOptions { choice_id: 2, entities: vec![10, 11] }, Phase::Choosing),
        (Action::PlayCard { source: 10, target: Some(20), position: Some(2) }, Phase::OurTurn),
        (Action::Attack { source: 10, target: 20 }, Phase::OurTurn),
        (Action::HeroPower { target: None }, Phase::OurTurn),
        (Action::EndTurn, Phase::OurTurn),
    ];
    for (action, expected) in cases {
        for phase in [Phase::Mulligan, Phase::Choosing, Phase::OurTurn, Phase::OpponentTurn, Phase::Animating, Phase::Finished] {
            assert_eq!(action.allowed_in(&phase), phase == expected, "{action:?} / {phase:?}");
        }
    }
}

#[test]
fn invalid_shapes_are_rejected_before_recording() {
    let cases = [
        (Action::PlayCard { source: 10, target: None, position: Some(0) }, Phase::OurTurn),
        (Action::PlayCard { source: 0, target: None, position: None }, Phase::OurTurn),
        (Action::Attack { source: 10, target: 0 }, Phase::OurTurn),
        (Action::HeroPower { target: Some(0) }, Phase::OurTurn),
        (Action::ChooseOptions { choice_id: 7, entities: vec![10, 10] }, Phase::Choosing),
        (Action::ChooseOptions { choice_id: 7, entities: (1..=33).collect() }, Phase::Choosing),
        (Action::Mulligan { choice_id: 1, replace: vec![0] }, Phase::Mulligan),
    ];
    for (action, phase) in cases {
        let current = Observation { snapshot: Snapshot { session_id: "protocol".into(), revision: 1, phase, complete: true },
            candidates: vec![Candidate { id: "candidate".into(), action }] };
        let decision = Decision { session_id: "protocol".into(), revision: 1, decision_id: "decision".into(), candidate_id: "candidate".into() };
        let window = ExecutionWindow::new(&current.snapshot, Duration::from_secs(10)).unwrap();
        let mut executor = RecordingExecutor::default();
        assert_eq!(Controller::default().execute(&current, &decision, &window, &mut executor), Err(ControlError::InvalidAction));
        assert!(executor.records.is_empty());
    }
}

#[test]
fn keep_all_mulligan_and_multi_entity_choices_retain_packet_identity() {
    for (action, phase) in [
        (Action::Mulligan { choice_id: 17, replace: vec![] }, Phase::Mulligan),
        (Action::ChooseOptions { choice_id: 23, entities: vec![10, 11] }, Phase::Choosing),
    ] {
        let current = Observation { snapshot: Snapshot { session_id: "protocol".into(), revision: 1, phase, complete: true },
            candidates: vec![Candidate { id: "candidate".into(), action: action.clone() }] };
        let decision = Decision { session_id: "protocol".into(), revision: 1, decision_id: "decision".into(), candidate_id: "candidate".into() };
        let window = ExecutionWindow::new(&current.snapshot, Duration::from_secs(10)).unwrap();
        let mut executor = RecordingExecutor::default();
        assert_eq!(Controller::default().execute(&current, &decision, &window, &mut executor), Ok(ExecutionOutcome::Recorded));
        assert_eq!(executor.records[0].1.action, action);
        assert!(serde_json::to_string(&action).unwrap().contains("choice_id"));
    }
}
