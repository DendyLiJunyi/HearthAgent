"""Summarize frozen option windows without storing raw logs or player names."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import subprocess

def visible_target_cards(window, target_ids):
    """Prefix-only evidence from our visible cards, never a deck identification."""
    board = window["board"]
    perspective = board["perspective"]
    if perspective is None:
        return []
    return sorted({card["card_id"] for player in board["players"]
                   if player["player_id"] == perspective
                   for zone in ("hand", "in_play", "graveyard")
                   for card in player[zone] if card.get("card_id") in target_ids})


def visible_hero_ids(window):
    board = window["board"]
    return sorted({card["card_id"] for player in board["players"]
                   if board["perspective"] is not None and player["player_id"] == board["perspective"]
                   for card in player["in_play"]
                   if card.get("card_type") == "HERO" and card.get("card_id")})


def review_sample(window, session, ordinal, target_ids, target_deck_code=""):
    """Only bounded, unblocked previews become unlabeled review samples."""
    preview = window["action_preview"]
    if (not window["packet_boundary_observed"] or preview["blocked_by"]
            or not preview["candidates"]):
        return None
    group = f"{session}/game-{window['game_number']}"
    payload = {"group_id": group, "window_ordinal": ordinal, "target_deck_code": target_deck_code,
               "board": window["board"], "action_preview": preview}
    sample_id = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 2, "sample_id": sample_id,
            "source": "offline_attack_review", "actionable": False, "complete": False,
            "packet_boundary_observed": True, **payload,
            "target_deck_confirmed": False,
            "visible_target_card_ids": visible_target_cards(window, target_ids),
            "annotation": {"status": "unreviewed", "preferred_candidate_ids": [],
                           "reason": None}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path)
    parser.add_argument("--binary", type=Path, default=Path("target/validation/debug/hearth-agent.exe"))
    parser.add_argument("--output", type=Path, default=Path(".data/preview-review.json"))
    parser.add_argument("--dataset", type=Path,
                        help="Write unlabelled supported windows as JSONL for human review")
    parser.add_argument("--user-target-session", action="append", default=[],
                        help="Session folder the user reports using the target deck in; not automatic per-game verification")
    args = parser.parse_args()
    paths = sorted(args.logs.glob("Hearthstone_*/Power.log"))
    if not paths:
        parser.error("no Power.log files under the supplied Logs directory")
    if set(args.user_target_session) - {path.parent.name for path in paths}:
        parser.error("user target sessions must match discovered session folders")
    reports = []
    example = None
    samples = []
    # Ask the same binary that performs review for its active profile. This avoids
    # silently pairing a new config file with an old compiled preview allowlist.
    profile_process = subprocess.run([str(args.binary.resolve()), "deck"], capture_output=True,
                                     text=True, encoding="utf-8", timeout=30, check=True)
    profile = json.loads(profile_process.stdout)["target_profile"]
    target_ids = {card["id"] for card in profile["cards"]}
    profile_hash = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if args.dataset and args.dataset.resolve() in (args.output.resolve(), args.output.with_suffix(".example.json").resolve()):
        parser.error("dataset and report output paths must differ")
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
                "review_samples": 0, "visible_target_card_ids": [], "observed_local_hero_ids": [],
                "target_deck_confirmed": False, "blocked_by": Counter(), "omitted": Counter()})
            preview = window["action_preview"]
            count = len(preview["candidates"])
            game["windows"] += 1
            game["windows_with_attacks"] += bool(count)
            game["attack_candidates"] += count
            game["blocked_by"].update(preview["blocked_by"])
            game["omitted"].update(preview["omitted"])
            game["visible_target_card_ids"] = sorted(set(game["visible_target_card_ids"])
                | set(visible_target_cards(window, target_ids)))
            game["observed_local_hero_ids"] = sorted(set(game["observed_local_hero_ids"])
                | set(visible_hero_ids(window)))
            sample = review_sample(window, path.parent.name, game["windows"], target_ids, profile["deck_code"])
            if sample:
                sample["user_reported_target_session"] = path.parent.name in args.user_target_session
                game["review_samples"] += 1
                if args.dataset:
                    samples.append(sample)
            if count and example is None:
                example = window
        reports.append({"session": path.parent.name,
                        "user_reported_target_session": path.parent.name in args.user_target_session,
                        "games": list(games.values())})
    all_games = [game for report in reports for game in report["games"]]
    report = {"source": "offline_option_windows", "actionable": False,
              "target_deck": {"name": profile["name"], "class": profile["class"],
                              "deck_code": profile["deck_code"], "profile_sha256": profile_hash},
              "note": "Counts describe observed prefixes, not legal-action coverage or game success.",
              "totals": {key: sum(game[key] for game in all_games)
                         for key in ["windows", "windows_with_attacks", "attack_candidates", "review_samples"]},
              "sessions": reports}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if example:
        args.output.with_suffix(".example.json").write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    else:
        # Replace a previous run's example so it cannot masquerade as current evidence.
        args.output.with_suffix(".example.json").write_text("null\n", encoding="utf-8")
    if args.dataset:
        args.dataset.parent.mkdir(parents=True, exist_ok=True)
        args.dataset.write_text("".join(json.dumps(sample, sort_keys=True) + "\n"
                                        for sample in samples), encoding="utf-8")
    print(json.dumps(report["totals"]))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
