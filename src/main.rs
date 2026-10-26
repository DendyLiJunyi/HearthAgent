use hearth_agent::controller::Controller;
use hearth_agent::executor::RecordingExecutor;
use hearth_agent::policy::{FirstCandidatePolicy, PolicyBackend};
use hearth_agent::protocol::{Action, Candidate, Observation, Phase, Snapshot};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args != ["demo"] {
        println!("Hearth Agent 0.1.0\nUsage: cargo run -- demo\nOffline demo only. Game and model adapters are not connected.");
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
