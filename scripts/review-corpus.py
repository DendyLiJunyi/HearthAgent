"""Summarize frozen option windows without storing raw logs or player names."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path)
    parser.add_argument("--binary", type=Path, default=Path("target/validation/debug/hearth-agent.exe"))
    parser.add_argument("--output", type=Path, default=Path(".data/preview-review.json"))
    args = parser.parse_args()
    paths = sorted(args.logs.glob("Hearthstone_*/Power.log"))
    if not paths:
        parser.error("no Power.log files under the supplied Logs directory")
    reports = []
    example = None
    for path in paths:
        process = subprocess.run([str(args.binary.resolve()), "review", str(path)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=180)
        if process.returncode:
            raise RuntimeError(f"Review failed for {path.parent.name}: {process.stderr}")
        games = {}
        for line in process.stdout.splitlines():
            window = json.loads(line)
            number = window["game_number"]
            game = games.setdefault(number, {"game_number": number, "windows": 0,
                "windows_with_attacks": 0, "attack_candidates": 0,
                "blocked_by": Counter(), "omitted": Counter()})
            preview = window["action_preview"]
            count = len(preview["candidates"])
            game["windows"] += 1
            game["windows_with_attacks"] += bool(count)
            game["attack_candidates"] += count
            game["blocked_by"].update(preview["blocked_by"])
            game["omitted"].update(preview["omitted"])
            if count and example is None:
                example = window
        reports.append({"session": path.parent.name, "games": list(games.values())})
    all_games = [game for report in reports for game in report["games"]]
    report = {"source": "offline_option_windows", "actionable": False,
              "note": "Counts describe observed prefixes, not legal-action coverage or game success.",
              "totals": {key: sum(game[key] for game in all_games)
                         for key in ["windows", "windows_with_attacks", "attack_candidates"]},
              "sessions": reports}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if example:
        args.output.with_suffix(".example.json").write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"]))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
