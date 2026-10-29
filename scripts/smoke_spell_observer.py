"""Run the real Rust replay and spell observer against synthetic appended logs."""
import argparse
import json
from pathlib import Path
import tempfile
from observe_spell import LogObserver
from ui_spell_result import wait_for_spell


def power(text): return f'D 0 GameState.DebugPrintPower() - {text}\n'


def baseline():
    lines = ['CREATE_GAME', 'GameEntity EntityID=1', 'tag=STATE value=RUNNING',
             'tag=STEP value=MAIN_ACTION', 'Player EntityID=2 PlayerID=1', 'tag=CURRENT_PLAYER value=1',
             'Player EntityID=3 PlayerID=2', 'tag=CURRENT_PLAYER value=0',
             'FULL_ENTITY - Creating ID=10 CardID=EX1_144', 'tag=ZONE value=HAND',
             'tag=CARDTYPE value=SPELL', 'tag=CONTROLLER value=1',
             'FULL_ENTITY - Creating ID=20 CardID=LOOT_412', 'tag=ZONE value=PLAY',
             'tag=CARDTYPE value=MINION', 'tag=CONTROLLER value=1']
    text = ''.join(map(power, lines))
    text += 'D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget=0 selectedPosition=0\n'
    for line in ['id=7', 'option 0 type=POWER mainEntity=10 error=NONE errorParam=',
                 'target 0 entity=20 error=NONE errorParam=']:
        text += f'D 0 GameState.DebugPrintOptions() - {line}\n'
    return text


def smoke(binary):
    rows = []
    for label, target, terminate in [('matching', 20, True), ('wrong_target', 99, True),
                                      ('unfinished_block', 20, False)]:
        with tempfile.TemporaryDirectory(prefix='hearth-spell-smoke-') as directory:
            log = Path(directory) / 'Hearthstone_2026_01_01_00_00_00' / 'Power.log'
            log.parent.mkdir()
            log.write_text(baseline(), encoding='utf-8')
            observe = LogObserver(log, binary)
            session, before = observe(5)
            candidates = before['game']['card_play_preview']['candidates']
            if len(candidates) != 1: raise AssertionError('synthetic spell baseline is unavailable')
            suffix = f'D 0 GameState.SendOption() - selectedOption=0 selectedSubOption=-1 selectedTarget={target} selectedPosition=0\n'
            suffix += power(f'BLOCK_START BlockType=POWER Entity=10 EffectCardId= EffectIndex=0 Target={target} SubOption=-1')
            suffix += power('TAG_CHANGE Entity=10 tag=ZONE value=GRAVEYARD')
            if terminate: suffix += power('BLOCK_END')
            with log.open('a', encoding='utf-8') as output: output.write(suffix)
            # Fake only the wait clock. Every observation still runs real Rust
            # replay with its real subprocess deadline against a temporary log.
            ticks = [0.0]
            def sleep(seconds): ticks[0] += seconds
            result = wait_for_spell(before, candidates[0]['id'], session, observe, timeout=1,
                                    clock=lambda: ticks[0], sleep=sleep)
            expected = {'matching': 'submission_and_source_graveyard_observed',
                        'wrong_target': 'different_submission_observed',
                        'unfinished_block': 'evidence_timeout'}[label]
            if result['status'] != expected: raise AssertionError(f'{label}: {result}')
            rows.append({'scenario': label, 'result': result, 'game_input_sent': False})
    return {'source': 'synthetic_spell_observer_smoke', 'scenarios': rows, 'game_input_sent': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('target/validation/debug/hearth-agent.exe'))
    args = parser.parse_args()
    print(json.dumps(smoke(args.binary), indent=2))
