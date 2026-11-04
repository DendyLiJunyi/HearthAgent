"""Read-only policy bridge to Rust's existing confidence/order-gated Laya client."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from validate_review import strict_json


class LayaAdvicePolicy:
    def __init__(self, binary=Path('target/validation/debug/hearth-agent.exe'),
                 endpoint='http://127.0.0.1:8791', timeout=12, runner=subprocess.run):
        self.binary, self.endpoint = Path(binary).resolve(), endpoint
        self.timeout, self.runner = timeout, runner
        self.last_status = None

    def __call__(self, observation):
        snapshot = observation['snapshot']
        payload = copy.deepcopy(observation)
        payload['snapshot']['complete'] = False
        with tempfile.TemporaryDirectory(prefix='hearth-offline-advice-') as directory:
            path = Path(directory) / 'observation.json'
            path.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
            completed = self.runner([str(self.binary), 'advise-observation', str(path), self.endpoint],
                                    capture_output=True, check=True, timeout=self.timeout)
        if len(completed.stdout) > 65536: raise ValueError('oversized advice response')
        report = strict_json(completed.stdout.decode('utf-8'))
        if (report.get('source') != 'saved_observation_advice' or report.get('actionable') is not False
                or report.get('game_input_sent') is not False
                or report.get('session_id') != snapshot['session_id'] or report.get('revision') != snapshot['revision']):
            raise ValueError('advice identity mismatch')
        self.last_status = report['status']
        if report['status'] == 'no_advice': return None
        if report['status'] != 'advice': raise ValueError('unexpected advice status')
        candidate = report['candidate_id']
        if sum(c['id'] == candidate for c in observation['candidates']) != 1:
            raise ValueError('advice candidate is unavailable')
        return {**{k: snapshot[k] for k in ('session_id', 'game_number', 'revision')}, 'candidate_id': candidate}
