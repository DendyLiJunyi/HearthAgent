"""Read-only targeted spell geometry; no game input adapter."""
import argparse
import json
from pathlib import Path
from attack_geometry import plan_geometry
from validate_review import strict_json


def plan_spell(observation, candidate_id, calibration, current_window, frame_sha256):
    return plan_geometry(observation, candidate_id, calibration, current_window, frame_sha256, spell=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    print(json.dumps(plan_spell(**strict_json(args.fixture.read_text(encoding='utf-8'))), indent=2))
