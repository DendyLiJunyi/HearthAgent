"""Corpus export integrity tests; model/GPU not required."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_corpus", ROOT / "scripts/review-corpus.py")
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)


def window():
    return {"game_number": 1, "packet_boundary_observed": True,
            "board": {"perspective": 1, "players": [
                {"player_id": 1, "hand": [{"card_id": "OURS"}], "in_play": [], "graveyard": []},
                {"player_id": 2, "hand": [{"card_id": "THEIRS"}], "in_play": [], "graveyard": []}]},
            "action_preview": {"blocked_by": [], "candidates": [{"id": "attack"}]}}


class CorpusTests(unittest.TestCase):
    def test_evidence_uses_only_our_prefix_visible_cards(self):
        value = window()
        self.assertEqual(corpus.visible_target_cards(value, {"OURS", "THEIRS"}), ["OURS"])
        value["board"]["perspective"] = None
        self.assertEqual(corpus.visible_target_cards(value, {"OURS", "THEIRS"}), [])

    def test_hero_evidence_respects_perspective(self):
        value = window()
        for player in value["board"]["players"]:
            player["in_play"] = [{"card_id": f"HERO_{player['player_id']}", "card_type": "HERO"}]
        self.assertEqual(corpus.visible_hero_ids(value), ["HERO_1"])
        value["board"]["perspective"] = None
        self.assertEqual(corpus.visible_hero_ids(value), [])

    def test_identity_scopes_reused_option_ids_and_tracks_content(self):
        value = window()
        sample = corpus.review_sample(value, "session", 1, {"OURS"})
        self.assertEqual(sample, corpus.review_sample(value, "session", 1, {"OURS"}))
        for session, ordinal in (("other", 1), ("session", 2)):
            self.assertNotEqual(sample["sample_id"], corpus.review_sample(value, session, ordinal, set())["sample_id"])
        changed = copy.deepcopy(value)
        changed["board"]["turn"] = 5
        self.assertNotEqual(sample["sample_id"], corpus.review_sample(changed, "session", 1, set())["sample_id"])
        self.assertFalse(sample["target_deck_confirmed"])
        self.assertFalse(sample["actionable"])
        self.assertEqual(sample["annotation"]["status"], "unreviewed")
        self.assertEqual(sample["annotation"]["preferred_candidate_ids"], [])
        different_deck = corpus.review_sample(value, "session", 1, {"OURS"}, "new-deck-code")
        self.assertNotEqual(sample["sample_id"], different_deck["sample_id"])

    def test_partial_blocked_and_empty_windows_are_excluded(self):
        for kind in ("partial", "blocked", "empty"):
            value = window()
            if kind == "partial":
                value["packet_boundary_observed"] = False
            elif kind == "blocked":
                value["action_preview"]["blocked_by"] = ["invalid_observation"]
            else:
                value["action_preview"]["candidates"] = []
            self.assertIsNone(corpus.review_sample(value, "session", 1, set()))

    def test_cli_exports_real_parser_window_and_clears_previous_run(self):
        binary = ROOT / "target/validation/debug/hearth-agent.exe"
        if not binary.exists():
            self.skipTest("build Rust CLI with --target-dir target/validation first")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "Hearthstone_synthetic"
            session.mkdir()
            fixture = (ROOT / "fixtures/wild-rogue-attacks.log").read_text(encoding="utf-8")
            log = session / "Power.log"
            log.write_text(fixture + "D 0 GameState.DebugPrintPower() - TAG_CHANGE Entity=10 tag=ATK value=9\n", encoding="utf-8")
            report, dataset = root / "report.json", root / "samples.jsonl"
            command = [sys.executable, str(ROOT / "scripts/review-corpus.py"), str(root),
                       "--binary", str(binary), "--output", str(report), "--dataset", str(dataset),
                       "--user-target-session", session.name]
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            samples = [json.loads(line) for line in dataset.read_text().splitlines()]
            self.assertEqual(len(samples), 1)
            self.assertEqual(len(samples[0]["action_preview"]["candidates"]), 2)
            self.assertTrue(samples[0]["user_reported_target_session"])
            self.assertFalse(samples[0]["target_deck_confirmed"])
            self.assertEqual(samples[0]["schema_version"], 2)
            self.assertEqual(json.loads(report.read_text())["target_deck"]["class"], "ROGUE")
            self.assertEqual(samples[0]["target_deck_code"], json.loads(report.read_text())["target_deck"]["deck_code"])
            self.assertEqual(json.loads(report.read_text())["totals"]["review_samples"], 1)
            # EOF packet remains available as a diagnostic example, but isn't a review sample.
            log.write_text(fixture, encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            self.assertEqual(dataset.read_text(), "")
            log.write_text("", encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            self.assertIsNone(json.loads(report.with_suffix(".example.json").read_text()))


if __name__ == "__main__":
    unittest.main()
