"""Run an owned offline Laya server and exercise Rust advice end to end, then stop it."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from runtime import ROOT, MODEL_REVISION


def health(url):
    with urllib.request.urlopen(url + '/health', timeout=2) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/validation/debug/hearth-agent.exe')
    args = parser.parse_args()
    if not args.binary.is_file():
        parser.error('build the Rust validation binary first')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    data = ROOT / '.data'
    data.mkdir(exist_ok=True)
    output = data / 'laya-http-smoke.json'
    report = {'source': 'offline_rust_laya_http_smoke', 'actionable': False,
              'game_input_sent': False, 'status': 'starting', 'rows': []}
    with (data / 'laya-http-smoke-server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(ROOT / 'services/laya/run_server.py'),
            '--device', args.device, '--port', str(port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 90
            while True:
                if process.poll() is not None:
                    raise RuntimeError('owned Laya server exited during startup; inspect its log')
                try:
                    before = health(url)
                    if before.get('status') == 'ok' and 'multilingual' in before.get('loaded', []):
                        break
                except (OSError, urllib.error.URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Laya startup exceeded 90 seconds')
                time.sleep(0.25)
            if before['revisions'].get('multilingual') != MODEL_REVISION:
                raise RuntimeError('service model revision mismatch')
            if not before['checkpoint_devices'].get('multilingual', '').startswith(args.device):
                raise RuntimeError('service actual device mismatch')
            report['health_before'] = before
            for command, fixture in [('advise', 'wild-rogue-attacks.log'),
                                     ('advise-choice', 'wild-rogue-choice.log')]:
                result = subprocess.run([str(args.binary.resolve()), command,
                    str(ROOT / 'fixtures' / fixture), url], cwd=ROOT, capture_output=True,
                    text=True, encoding='utf-8', timeout=30, check=True)
                row = json.loads(result.stdout)
                if (row['game_input_sent'] is not False or row['actionable'] is not False
                        or row['complete'] is not False or row['model_query_attempted'] is not True):
                    raise RuntimeError('CLI did not preserve the read-only smoke contract')
                if row['status'] == 'no_advice':
                    expected = ('below the configured cutoff', 'abstained', 'candidate order', 'truncated')
                    if not any(reason in row.get('reason', '') for reason in expected):
                        raise RuntimeError('CLI failure was not a model-validation abstention')
                elif row['status'] != 'advice':
                    raise RuntimeError('unexpected CLI advice status')
                report['rows'].append({'command': command, 'fixture': fixture, 'result': row})
            after = health(url)
            if after['cpu_fallbacks'].get('multilingual', {}).get('count', 0):
                raise RuntimeError('model used CPU fallback')
            report['health_after'] = after
            report['status'] = 'passed_transport_and_gating'
        except Exception as error:
            report['status'] = 'failed'
            report['error_type'] = type(error).__name__
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            report['owned_server_stopped'] = process.poll() is not None
            output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(output), 'status': report['status'],
        'commands': [{ 'command': row['command'], 'status': row['result']['status'],
                      'reason': row['result'].get('reason')} for row in report['rows']],
        'owned_server_stopped': report['owned_server_stopped']}, indent=2))


if __name__ == '__main__':
    main()
