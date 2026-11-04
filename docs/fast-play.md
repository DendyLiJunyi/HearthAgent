# Fast play, staying in the game, and deck tactics — 2026-11-04

All checks here are offline. **No live game has run on these changes**, so live speed, click
reliability and playing strength are not established. Validation: 210 agent tests pass, all 98
mutation checks are caught, and recorded games ran through the real loop at fast settings.

## Where the time went

Laya was not the bottleneck. It takes about 230 ms per decision, against 8.4 s between options and the
send on the latest ranked run.

The last recorded play shows the main cost. The game had finished its animation queue at
`22:24:07.40`, and the agent sent at `22:24:14.59`: 7.2 seconds waiting for whole-board pixels to stop
changing. In that run the board check blocked 76 of 82 screen checks at one point, with
`--screen-settle 0.6`. In human games, the fastest moves came 0.18 s (1st percentile) and 0.5 s (10th
percentile) after options arrived, so the client takes input long before the board looks still.

## The fast gate

`--pace fast` is now the default. `--pace careful` keeps the earlier settings exactly.

| Step | Careful | Fast |
| --- | --- | --- |
| Opening wait | 20 s | None; the backlog covers it |
| Log quiet | 0.5 s | 0.15 s |
| Animation check | Whole board and hand still for 1.5 s | Log backlog at most 12 lines |
| Pixel check | Same as above | Patches around the gesture still for 0.12 s, giving up after 0.5 s |
| End Turn button | 3 lit reads | 2 lit reads |
| Model | After the screen is ready | During the animation, once per packet |
| Drag | 0.31 s | About 0.18 s, with a careful retry |
| Confirm timeout | 2 s | 1.2 s |

**The backlog.** `GameState` lines log when the client receives something, and `PowerTaskList` repeats
them when the client reaches them. Pending lines measure how far behind it is.

| Pending lines at the attempt | Moves that went through | Failed drags |
| --- | --- | --- |
| 0 | 106 | 3 |
| 1–5 | 58 | 1 |
| 6–12 | 9 | 0 |
| 13+ | 86 | 18 |

So failures ran 17% at 13 or more and 2.3% at 12 or fewer. All three failed drags in the game that
led to the 20-second opening wait had 42–176 pending lines. These are association counts from saved
runs, timed from the recording, not a controlled test. The wait gives up after 6 s because a few lines
are never repeated. The End Turn button still has to be lit, for up to 8 s, and then the move is tried
anyway because the send check catches failure.

**Estimated saving**, from `python -m agent.pace_report <run folder>`:

| Run | Options to send, median | Gate would open, median |
| --- | --- | --- |
| `loop-20261104-222225` (4 moves) | 8.38 s | 3.06 s |
| `loop-20261104-220207` (6 moves) | 7.92 s | 2.28 s |
| `loop-20261104-212126` (47 moves) | 4.92 s | 1.47 s |

These count the log gate only, without the button or gesture, so a real move takes longer. The same
report on a new run gives the actual numbers.

Failure slows things down automatically: after a failed drag, the next three moves use careful mouse
timing and 0.5 s more quiet time.

## Staying in the game

A stop in a game against another player forfeits on the turn timer, and stops ended many past runs:
11 for drags or clicks the game ignored, and 5 for losing focus. With `--pace fast`:

| Situation | Before | Now |
| --- | --- | --- |
| Single drag ignored three times | Stop | Cancel, drop that move, ask the policy again |
| Multi-step move ignored | Stop | Cancel, drop that move, ask the policy again |
| End Turn ignored | Stop | No more input; wait for the timer |
| Different move logged | Stop | Continue, up to 3 per game |
| Focus lost during a gesture | Stop | Pause, cancel on return, re-read the log |
| Mulligan not recognized or unanswered | Stop | No more input; the game's timer finishes it |
| Unsupported or failed choice | Stop | No more input; the game's timer finishes it |
| Screen never ready | Stop | Try anyway; the send check still applies |

Still stops: Esc, a wrong game type or format, the action limit, a new game during confirmation, a
log change and a moved window. A move is never resent after the log has changed. Each recovery goes
into `moves.jsonl` and `outcome.json`.

## Tactics

`agent/tactics.py` holds Pirate Warrior knowledge. `--no-tactics` turns it off.

- **Lethal setup:** a Charge minion or flat Pirate buff is played first when it brings the next attacks
  to exactly enough damage. Taunt or a Risky Skipper risk rules this out.
- **Buff before attacking:** if the chosen move is a Pirate attack and Southsea Captain, Blastpowder
  Engineer or Hozen Roughhouser is playable, the buff goes first. This fixes the reported habit.
  Choosing another card first is left alone.
- **The Coin:** spent only when it stops mana going unused this turn.
- **No early pass:** Laya cannot end the turn while a useful move exists.
- **Mulligan:** a table for this deck, replacing the plain cost rule.

These are judgment calls. Two first versions were narrowed after checking them against recorded play:
the Coin rule fired 99 times and matched the recorded move 8 times, and a broader buff rule disagreed
with the player's own games in 13 of 17 cases. The final buff correction changes 2 of 277 human moves.

Held-out agreement is unchanged on Warrior (31 of 61, no picks changed). The older games are Rogue and
fell from 82 to 79 of 213; that deck is not this module's target. Agreement is not win rate, and these
games were looked at while narrowing the rules, so they are validation and not a clean test.

## Known gaps

- The End Turn check, patch sizes, drag speed and 0.4 s step pause have not run live.
- Patch stability may hit its 0.5 s limit on every move if card glows move those pixels. The next run's
  `screen_blocked` counts will show this.
- Discover still takes the highest-cost offer. Multi-pick choices are left to the game's timer.
- Lethal setup does not count weapons or random damage, so it misses some real lethal.
- The replay covered part of a recording, because recorded human placement differs from the agent's.

## First live run

Start with practice, then read the timing:

```powershell
.venv/Scripts/python.exe -m agent.cli loop --games 3 --mode practice
.venv/Scripts/python.exe -m agent.pace_report .data/live/<loop folder>/001
```

If it misbehaves, `--pace careful` restores the earlier behavior.
