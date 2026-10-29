"""Plan reviewed ordinary-minion placement; never send game input."""
import argparse
import json
from pathlib import Path
from attack_geometry import plan_geometry
from validate_review import strict_json


def plan_minion(observation, candidate_id, calibration, current_window, frame_sha256):
    return plan_geometry(observation, candidate_id, calibration, current_window, frame_sha256,
                         spell=True, minion=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    print(json.dumps(plan_minion(**strict_json(args.fixture.read_text(encoding='utf-8'))), indent=2))
