"""Download/load one pinned model and measure synthetic inference; sends no game input."""
import argparse
import json
import statistics
import time
from runtime import ROOT, MODEL_REPO, MODEL_REVISION, MODEL_SUBFOLDER, configure_environment, synthetic_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("--runs must be 1..100")
    configure_environment()
    import laya
    import torch
    import transformers
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; use --device cpu explicitly to measure CPU")
    if args.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    agent = laya.load(MODEL_REPO, subfolder=MODEL_SUBFOLDER, revision=MODEL_REVISION, device=args.device)
    load_seconds = time.perf_counter() - started
    questions = {"action": {"type": "choice",
        "instructions": "Choose the best supplied Hearthstone action for the acting player. Use only the given state.",
        "criteria": {"c0": "Attack with entity 10 against entity 20", "c1": "End the current turn"}}}
    durations = []
    results = []
    for _ in range(args.runs):
        started = time.perf_counter()
        result = agent.predict(synthetic_state(), questions, max_len=8192, head_max_len=1024, min_confidence=0.0)
        durations.append((time.perf_counter() - started) * 1000)
        results.append(result)
    actual_device = str(next(agent.model.parameters()).device)
    report = {
        "model": MODEL_REPO, "revision": MODEL_REVISION, "subfolder": MODEL_SUBFOLDER,
        "laya_version": laya.__version__, "torch_version": torch.__version__,
        "transformers_version": transformers.__version__, "actual_device": actual_device,
        "load_seconds_including_any_download": load_seconds, "runs": args.runs,
        "latencies_ms": durations, "median_ms": statistics.median(durations),
        "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2 if args.device == "cuda" else None,
        "synthetic_expected_choice": "c0", "correct_runs": sum(r["answers"]["action"]["choice"] == "c0" for r in results),
        "last_result": results[-1], "actionable": False,
    }
    destination = ROOT / ".data" / "laya-probe.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
