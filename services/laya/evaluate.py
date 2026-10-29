"""Small synthetic capability/order audit. Offline by default; never executes actions."""
import argparse
import copy
import hashlib
import itertools
import json
import os
import time

from probe import demo_state, latency_summary
from runtime import ROOT, MODEL_REPO, MODEL_REVISION, MODEL_SUBFOLDER, configure_environment


def cases():
    lethal = demo_state()
    armored = copy.deepcopy(lethal)
    armored["board"]["opponent_hero"]["armor"] = 2
    armored["board"]["our_minions"].append(
        {"entity_id": 11, "attack": 5, "health": 5, "can_attack": True})
    armored["board"]["rules"] = (
        "Both attacks are legal and deal their attack value. Armor absorbs damage first. "
        "Reducing enemy hero health to 0 wins immediately.")
    target = copy.deepcopy(lethal)
    target["board"]["opponent_minions"] = [
        {"entity_id": 21, "attack": 0, "health": 5, "taunt": False}]
    target["board"]["rules"] = (
        "Both attacks are legal and deal 3 damage. Reducing enemy hero health to 0 wins immediately.")
    end = copy.deepcopy(lethal)
    end["board"]["fixture"] = "synthetic no available moves; no live game data"
    end["board"]["our_minions"] = []
    end["board"]["rules"] = "No attacks, playable cards, or hero powers are available."
    attack = ("attack", "Attack with entity 10 against entity 20")
    finish = ("end", "End the current turn")
    return [
        ("lethal", lethal, [attack, finish], "attack"),
        ("armor", armored, [attack, ("lethal", "Attack with entity 11 against entity 20"), finish], "lethal"),
        ("target", target, [attack, ("trade", "Attack with entity 10 against entity 21"), finish], "attack"),
        ("only_end", end, [finish], "end"),
    ]


def ordered(value, reverse=False):
    if isinstance(value, dict):
        return {key: ordered(value[key], reverse) for key in sorted(value, reverse=reverse)}
    if isinstance(value, list):
        return [ordered(item, reverse) for item in value]
    return value


def trials():
    for case_id, state, candidates, expected in cases():
        for permutation, items in enumerate(itertools.permutations(candidates)):
            for reverse in (False, True):
                mapping = {f"c{i}": candidate for i, (candidate, _) in enumerate(items)}
                questions = {"action": {"type": "choice", "instructions":
                    "Choose the best supplied Hearthstone action for the acting player. Use only the given state.",
                    "criteria": {f"c{i}": description for i, (_, description) in enumerate(items)}}}
                yield {"case": case_id, "permutation": permutation,
                       "field_order": "reverse" if reverse else "rust_sorted",
                       "state": ordered(state, reverse), "questions": questions,
                       "mapping": mapping, "expected": expected}


def score(result, trial):
    """Reject malformed/truncated responses rather than counting them as evidence."""
    answer = result["answers"]["action"]
    usage = result["usage"]
    probs = answer["probabilities"]
    labels = trial["mapping"]
    confidence = answer["answer_confidence"]
    if (usage["truncated"] or usage["state_tokens_dropped"] != 0
            or usage["truncated_questions"] or usage.get("options")
            or answer["type"] != "choice" or answer["choice"] not in labels
            or set(probs) != set(labels)
            or any(not isinstance(p, (float, int)) or not 0 <= p <= 1 for p in probs.values())
            or abs(sum(probs.values()) - 1) > len(labels) * 0.000051
            or not isinstance(confidence, (float, int)) or not 0 <= confidence <= 1
            or max(probs.values()) > probs[answer["choice"]] + 0.0001):
        raise ValueError("invalid or truncated evaluation response")
    choice = labels[answer["choice"]]
    return {"choice": choice, "correct": choice == trial["expected"],
            "accepted_at_0_8": answer["abstention"] == "passed" and confidence >= 0.8,
            "first_candidate_correct": labels["c0"] == trial["expected"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error("--runs must be 1..20")
    configure_environment()
    os.environ["HF_HUB_OFFLINE"] = "1"
    import laya
    import torch
    import transformers
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; choose --device cpu explicitly")
    suite = list(trials())
    agent = laya.load(MODEL_REPO, subfolder=MODEL_SUBFOLDER,
                      revision=MODEL_REVISION, device=args.device)

    def predict(trial):
        return agent.predict(trial["state"], trial["questions"], max_len=8192,
                             head_max_len=1024, min_confidence=0.0)

    score(predict(suite[0]), suite[0])  # Untimed warmup; fail on invalid output.
    rows = []
    for trial in suite:
        for repeat in range(args.runs):
            if args.device == "cuda":
                torch.cuda.synchronize()
            start = time.perf_counter()
            response = predict(trial)
            if args.device == "cuda":
                torch.cuda.synchronize()
            elapsed = (time.perf_counter() - start) * 1000
            rows.append({**{k: trial[k] for k in ("case", "permutation", "field_order", "expected")},
                         "repeat": repeat, **score(response, trial), "elapsed_ms": elapsed,
                         "response": response})
    summaries = {}
    for case_id, *_ in cases():
        group = [row for row in rows if row["case"] == case_id]
        accepted = [row for row in group if row["accepted_at_0_8"]]
        summaries[case_id] = {"trials": len(group), "correct": sum(r["correct"] for r in group),
            "accepted_at_0_8": len(accepted), "accepted_correct": sum(r["correct"] for r in accepted),
            "first_candidate_correct": sum(r["first_candidate_correct"] for r in group),
            "semantic_choices": sorted({r["choice"] for r in group}),
            "all_variants_correct": all(r["correct"] for r in group)}
    report = {"model": MODEL_REPO, "revision": MODEL_REVISION, "subfolder": MODEL_SUBFOLDER,
        "laya_version": laya.__version__, "torch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "actual_device": str(next(agent.model.parameters()).device),
        "suite_sha256": hashlib.sha256(json.dumps(suite).encode()).hexdigest(),
        "suite": suite, "repeats": args.runs, "summaries": summaries,
        "latency_scope": "warm direct predict calls; excludes load and warmup",
        **latency_summary([r["elapsed_ms"] for r in rows]), "rows": rows,
        "actionable": False, "scope": "four synthetic positions, not independent game samples; "
        "threshold-zero ranking diagnostic with a post-hoc 0.8 confidence filter, not Rust acceptance"}
    destination = ROOT / ".data" / "laya-evaluation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "summaries": summaries}, indent=2))


if __name__ == "__main__":
    main()
