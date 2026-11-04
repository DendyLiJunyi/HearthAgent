"""Run the real Agent loop through recorded games, with the recording playing the game's part.

The log stops at each moment the player had to act and continues only once the agent clicks.
A scripted policy repeats the recorded move, so every SendOption must confirm. This tests the
loop, the guards and the parser together on real games. It does not test click accuracy or
move quality, and game type is overridden because no recorded game was a practice game.
"""
import collections
import glob
import json
import sys

from . import loop
from .power import PowerLog


class Scripted:
    """Plays the recorded answer to each decision."""

    def __init__(self, answers, choices):
        self.answers, self.choices = answers, choices

    def choose(self, state, candidates, cards=None):
        sent = self.answers.pop(0)
        for index, candidate in enumerate(candidates):
            if all(candidate[k] == sent[k] for k in ('option', 'sub', 'target')):
                return index
        raise loop.Stop(f'recorded move is not plannable: {sent}')

    def mulligan(self, entities, cards):
        return []

    def pick_choice(self, choice, cards):
        return 0


def is_pause(line, local_name):
    return 'GameState.SendOption()' in line or 'GameState.SendChoices() - id=' in line


class Clock:
    now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def simulate(path):
    with open(path, encoding='utf-8', errors='replace') as handle:
        lines = handle.readlines()
    recorded = PowerLog()
    for line in lines:
        recorded.feed(line)
    answers = [entry['sent'] for game in recorded.games for entry in game.sends]
    chunks, current = [], []
    for line in lines:
        if is_pause(line, None):
            chunks.append(current)
            current = []
        current.append(line)
    chunks.append(current)

    clock = Clock()

    class Inputs:
        sent = 0

        def send(self, gestures):
            self.sent += 1
            release()

        def aborted(self):
            return False

    state = {'next': 0, 'buffer': []}

    def release():
        if state['next'] < len(chunks):
            state['buffer'] += chunks[state['next']]
            state['next'] += 1

    def reader():
        lines_out, state['buffer'] = state['buffer'], []
        return lines_out

    release()
    inputs = Inputs()
    agent = loop.Agent(reader, Scripted(answers, None), inputs, settle=1.0, clock=clock.time,
                       sleep=clock.sleep, log=lambda *_: None, max_actions=10 ** 6)
    statuses = collections.Counter()
    stopped = None
    idle = 0
    while state['next'] < len(chunks) or state['buffer']:
        try:
            status = agent.step()
        except loop.Stop as stop:
            stopped = str(stop)
            break
        statuses[status] += 1
        clock.now += 1.1
        # A pause the agent has no reason to answer, such as a game abandoned at a decision.
        if status == 'acted':
            idle = 0
        else:
            idle += 1
        if idle > 5 and not state['buffer']:
            statuses['released_unanswered'] += 1
            release()
            idle = 0
    return {'actions': inputs.sent, 'recorded_sends': sum(len(g.sends) for g in recorded.games),
            'statuses': dict(statuses), 'stopped': stopped, 'games': len(recorded.games)}


if __name__ == '__main__':
    loop.ALLOWED_GAME_TYPES.update({'GT_RANKED', 'GT_ARENA'})
    print(json.dumps({p: simulate(p) for p in sorted(glob.glob(sys.argv[1]))}, indent=1))
