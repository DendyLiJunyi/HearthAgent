"""Historical placement evidence through the real Rust parser, without game input."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from smoke_spell_observer import baseline, power
from ui_spell_result import assess_minion


class MinionParserIntegrationTests(unittest.TestCase):
    def test_historical_slot_preview_and_post_submission_evidence(self):
        root = Path(__file__).resolve().parents[1]
        binary = root / 'target/validation/debug/hearth-agent.exe'
        if not binary.exists(): self.skipTest('build Rust binary first')
        text = baseline().replace('CardID=EX1_144', 'CardID=TID_078')
        text = text.replace('value=SPELL', 'value=MINION')
        text = ''.join(line + '\n' for line in text.splitlines() if 'target 0' not in line)
        # The existing local minion occupies slot one; the hand card is inserted
        # into slot two. This is synthetic historical evidence, never a live gate.
        text = text.replace(power('tag=ZONE value=PLAY'),
                            power('tag=ZONE value=PLAY') + power('tag=ZONE_POSITION value=1'))
        send = ('D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 '
                'selectedTarget=0 selectedPosition=2\n')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'Power.log'

            def export(contents, command):
                log.write_text(contents, encoding='utf-8')
                args = [str(binary), command, str(log)]
                if command == 'replay': args.append('--json')
                result = subprocess.run(args, capture_output=True, check=True, timeout=5)
                return [json.loads(line) for line in result.stdout.splitlines()]

            before = export(text, 'replay')[-1]
            self.assertEqual(before['game']['card_play_preview']['candidates'], [])
            window = export(text + send, 'review-card-plays')[-1]
            self.assertTrue(window['packet_boundary_observed'])
            preview = window['action_preview']
            self.assertEqual([c['action']['PlayCard']['position'] for c in preview['candidates']], [1, 2])
            self.assertEqual(window['board'], before['game']['board'])
            before['game']['card_play_preview'] = preview
            candidate = preview['candidates'][1]['id']
            start = power('BLOCK_START BlockType=POWER Entity=10 EffectCardId= EffectIndex=0 Target=0 SubOption=-1')
            played = power('TAG_CHANGE Entity=10 tag=ZONE value=PLAY')
            placed = power('TAG_CHANGE Entity=10 tag=ZONE_POSITION value=2')
            for suffix, expected in [
                (start + played + placed + power('BLOCK_END'), 'submission_and_source_in_play_observed'),
                (start + played + placed, 'pending'),
                (start + played + power('TAG_CHANGE Entity=10 tag=ZONE_POSITION value=1') + power('BLOCK_END'),
                 'different_board_position_observed'),
                (start + played + placed + power('TAG_CHANGE Entity=10 tag=ZONE value=GRAVEYARD') + power('BLOCK_END'),
                 'pending')]:
                after = export(text + send + suffix, 'replay')[-1]
                result = assess_minion(before, after, candidate)
                self.assertEqual(result['status'], expected)
                self.assertFalse(result['execution_confirmed'])
                self.assertFalse(result['automatic_retry_allowed'])


if __name__ == '__main__': unittest.main()
