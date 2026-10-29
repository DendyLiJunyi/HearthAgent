"""Download/load one pinned model and measure synthetic inference; sends no game input."""
import argparse
import json
import math
import statistics
import time
from runtime import ROOT, MODEL_REPO, MODEL_REVISION, MODEL_SUBFOLDER, configure_environment, synthetic_state


def latency_summary(durations):
    """Nearest-rank p95, calculated only from measured warm requests."""
    if not durations or any(not math.isfinite(x) or x < 0 for x in durations):
        raise ValueError("latencies must be a nonempty sequence of finite nonnegative values")
    return {
        "median_ms": statistics.median(durations),
        "p95_ms": sorted(durations)[math.ceil(0.95 * len(durations)) - 1],
    }


def demo_state():
    # serde_json uses sorted object keys. Laya renders objects as text, so key
    # order changes model input even when the JSON objects are equivalent.
    return json.loads(json.dumps({
        "session_id": "synthetic-laya-demo", "revision": 1, "board": synthetic_state(),
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--offline", action="store_true", help="Use cached checkpoint files only")
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("--runs must be 1..100")
    configure_environment()
    if args.offline:
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
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
    # Match the Rust demo's state envelope, including its snapshot identity.
    state = demo_state()

    def predict_timed():
        if args.device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        result = agent.predict(state, questions, max_len=8192, head_max_len=1024, min_confidence=0.0)
        if args.device == "cuda":
            torch.cuda.synchronize()
        return result, (time.perf_counter() - started) * 1000

    cold_result, first_inference_ms = predict_timed()
    for _ in range(args.runs):
        result, elapsed_ms = predict_timed()
        durations.append(elapsed_ms)
        results.append(result)
    actual_device = str(next(agent.model.parameters()).device)
    report = {
        "model": MODEL_REPO, "revision": MODEL_REVISION, "subfolder": MODEL_SUBFOLDER,
        "laya_version": laya.__version__, "torch_version": torch.__version__,
        "transformers_version": transformers.__version__, "actual_device": actual_device,
        "load_seconds_including_any_download": load_seconds, "runs": args.runs,
        "first_inference_ms": first_inference_ms,
        "first_inference_result": cold_result,
        "latencies_ms": durations, **latency_summary(durations),
        "latency_scope": "warm direct predict calls; excludes model load and first inference",
        "percentile_method": "nearest_rank", "offline": args.offline,
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
