import copy
import http.server
import json
import subprocess
import threading
import unittest

from board_encoding import DEFAULTS, decode, encode
from runtime import ROOT


class BoardEncodingTests(unittest.TestCase):
    def board(self):
        card = copy.deepcopy(DEFAULTS)
        card.update({'entity_id': 10, 'public_zone': False, 'attack': 0, 'exhausted': False})
        card['combat'].update({'taunt': False, 'divine_shield': True, 'attacks_this_turn': 0})
        return {'perspective': None, 'actionable': False, 'players': [
            {'hand': [card], 'in_play': [], 'graveyard': [copy.deepcopy(DEFAULTS)]}]}

    def test_roundtrip_preserves_unknown_false_zero_and_all_entities(self):
        board = self.board()
        original = copy.deepcopy(board)
        encoded = encode(board)
        self.assertEqual(decode(encoded), board)
        self.assertEqual(board, original)
        card = encoded['board']['players'][0]['hand'][0]
        self.assertEqual(card['attack'], 0)
        self.assertIs(card['combat']['taunt'], False)
        self.assertIs(card['combat']['divine_shield'], True)
        self.assertNotIn('health', card)
        self.assertEqual(encoded['board']['players'][0]['graveyard'], [{}])

    def test_schema_drift_is_rejected_instead_of_silently_dropped(self):
        for action in ('add', 'remove'):
            board = self.board()
            card = board['players'][0]['hand'][0]
            if action == 'add':
                card['new_stat'] = 4
            else:
                del card['health']
            with self.assertRaises(ValueError):
                encode(board)

    def test_defaults_are_independent_and_unknown_encoding_is_rejected(self):
        value = encode(self.board())
        value['card_defaults']['health'] = 0
        self.assertIsNone(DEFAULTS['health'])
        with self.assertRaises(ValueError):
            decode(value)

    def test_rust_cli_sends_identical_encoded_projection_to_python(self):
        binary = ROOT / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists():
            self.skipTest('build the validation binary first')
        fixture = ROOT / 'fixtures/wild-rogue-attacks.log'
        replay = json.loads(subprocess.check_output([str(binary), 'replay', str(fixture), '--json'],
                                                   text=True, encoding='utf-8', timeout=10))
        captured = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                # Return an explicit abstention; this test exercises serialization, not advice quality.
                body = json.dumps({'answers': {'action': {'type': 'choice', 'choice': 'c0',
                    'probabilities': {'c0': 0.5, 'c1': 0.5}, 'answer_confidence': 0.5,
                    'abstention': 'passed'}}, 'usage': {'input_tokens': 100, 'truncated': False,
                    'state_tokens_dropped': 0, 'truncated_questions': []}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with http.server.HTTPServer(('127.0.0.1', 0), Handler) as server:
            server.timeout = 5
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            output = subprocess.check_output([str(binary), 'advise', str(fixture),
                f'http://127.0.0.1:{server.server_port}'], text=True, encoding='utf-8', timeout=10)
            worker.join(timeout=6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['state']['board']['observation'], encode(replay['game']['board']))
        self.assertFalse(captured[0]['state']['board']['candidate_coverage_complete'])
        report = json.loads(output)
        self.assertFalse(report['actionable'])
        self.assertEqual(report['status'], 'no_advice')

    def test_rust_advice_requires_semantic_agreement_under_reversed_order(self):
        binary = ROOT / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists():
            self.skipTest('build the validation binary first')
        for consistent, command, fixture in [(agreement, command, fixture)
                for agreement in (False, True) for command, fixture in
                [('advise', 'wild-rogue-attacks.log'), ('advise-choice', 'wild-rogue-choice.log')]]:
            captured = []
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_POST(self):
                    value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    captured.append(value)
                    labels = list(value['questions']['action']['criteria'])
                    # On reversal c1 refers to the original c0 semantic action.
                    selected = 'c1' if consistent and len(captured) == 2 else 'c0'
                    body = json.dumps({'answers': {'action': {'type': 'choice', 'choice': selected,
                        'probabilities': {key: 0.9 if key == selected else 0.1 for key in labels},
                        'answer_confidence': 0.9, 'abstention': 'passed'}},
                        'usage': {'input_tokens': 100, 'truncated': False,
                                  'state_tokens_dropped': 0, 'truncated_questions': []}}).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            with http.server.HTTPServer(('127.0.0.1', 0), Handler) as server:
                server.timeout = 3
                def handle_two():
                    server.handle_request()
                    server.handle_request()
                worker = threading.Thread(target=handle_two, daemon=True)
                worker.start()
                output = subprocess.check_output([str(binary), command,
                    str(ROOT / 'fixtures' / fixture), f'http://127.0.0.1:{server.server_port}'],
                    text=True, encoding='utf-8', timeout=10)
                worker.join(timeout=7)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0]['state'], captured[1]['state'])
            self.assertNotEqual(captured[0]['questions'], captured[1]['questions'])
            report = json.loads(output)
            self.assertFalse(report['actionable'])
            self.assertFalse(report['game_input_sent'])
            self.assertEqual(report['status'], 'advice' if consistent else 'no_advice')
            if not consistent:
                self.assertIn('candidate order', report['reason'])
            if command == 'advise-choice':
                from evaluate_choices import request_choice
                replay = json.loads(subprocess.check_output([str(binary), 'replay',
                    str(ROOT / 'fixtures' / fixture), '--json'], text=True, encoding='utf-8', timeout=10))
                expected, _, _ = request_choice({'board': replay['game']['board'],
                    'choice': replay['game']['choice_preview']['choice'], 'window_ordinal': 1})
                self.assertEqual(captured[0]['state']['board'], expected['board'])
                self.assertEqual(captured[0]['state']['board']['offered_choice']['choice_id'], 7)
                self.assertIn('choice packet 7', captured[0]['questions']['action']['criteria']['c0'])
                if consistent:
                    self.assertEqual(report['advice']['candidate_id'], 'choice-7-entity-20')


if __name__ == '__main__':
    unittest.main()
