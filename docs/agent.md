# Live agent (`agent/`)

Written 2026-11-04. One practice game has been run live, on the rules policy with 7 restarts.
No game has been completed unattended, Laya has not played live, and no win rate exists.

## First live test (2026-11-04)

Of 25 agent moves, 18 reached the game as planned, 7 sent nothing and none became a wrong move.

- Hand sizes other than six, minion rows, the board drop and the mulligan all worked at least once.
- Two stops were N'Zoth: the agent opened the ability picker and never picked. Fixed, untested live.
- Four were the first move of a turn, and the same move worked after a restart. The cause is unknown.
  The agent now hovers longer and resends single-gesture moves up to twice, but only if the log shows
  nothing changed. Untested live.
- One was the game losing focus.

## Run it

Open a practice game in a 16:9 window at the game's normal layout, then from `D:\HearthAgent`:

```powershell
.venv/Scripts/python.exe -m agent.cli status                # read-only
.venv/Scripts/python.exe -m agent.cli play                  # plan one move, sends nothing
.venv/Scripts/python.exe -m agent.cli play --execute        # real mouse input
```

After launching, click the game window within 60 seconds. Each live run saves a frame and plan per
move, the outcome and a copy of the log to `.data/live/<time>/`.

Add `--aggressive` to make any attacker that can reach the enemy hero hit face instead of trading.
Add `--friend-agreed` to also act in a friendly challenge, only when your opponent knows a bot is
playing. Ranked, casual and arena are always refused. The friendly game type name comes from the
game's known values and has not yet been seen in a log, so an unexpected name is refused too.

Hold **Esc** to stop. Add `--policy rules` to run without the model. To check positions by eye,
capture a frame with `scripts/capture-game-window.ps1`, then run
`agent.cli preview <frame.png> <output.svg>` and open the SVG in a browser.

## Which policy has played

As of this note, every live game has been played by the rules policy, including the one that looked
like Laya's: all 17 real decisions in that game matched rules, and Laya would have differed on 7.
Laya first played live on 2026-11-04 with the Warrior deck and won one game against the Innkeeper, with
one restart. That is a single game against the built-in AI and says little about strength. Replaying the
earlier Rogue game offline, it would have aimed Serrated Bone
Spike at its own minion and ended the turn with a ready 3/3 that could hit face.

Blunder checks were added from those examples, but they are not a cure. On the 5 held-out games they
changed only 2 of Laya's 213 picks and left its match score at 28.2%, so most of its weakness is
strategic. They also flag 8 of the player's own 213 moves, so they are too blunt to treat as a measure
of good play. The likely real fix is more training data, especially from the deck being played.

## Why first moves of a turn failed

The log reports a new turn well before the screen catches up. Captures taken about 5 seconds after a
failed drag still showed the Your Turn banner and a grey End Turn button, so the game was ignoring
input. From the player's seat, this looks like the agent trying to use a card it cannot use, but every
such move was legal and was accepted once the screen caught up. Live moves now wait for the button
to light up. One live run still dragged a card while the opponent's turn was on screen, with a grey
button in the frame taken just before the click. The earlier reading was not saved, so the cause is
unknown. The agent now needs two lit readings in a row and reads again right before input. These
additions have not been tested live.

## How a move happens

1. `power.py` reads `Power.log` incrementally. Only `GameState` lines change state.
2. Legal moves come from the game's own option packets, not from a rules engine.
3. `policy.py` picks one. Fine-tuned Laya ranks moves, averaged over 4 option orders. Rules first
   remove plain blunders, and they handle lethal, abilities, mulligan and choices, and take over if
   the model fails. Each run prints and saves which policy played.
4. `geometry.py` turns the move into clicks and drags, using each entity's logged slot.
5. `loop.py` re-reads the log, sends the input, then requires a matching `SendOption`.

## Safety rules

Each rule below is removed in turn by `python -m agent.mutation_check`, which confirms a test fails.

- Acts only in `GT_VS_AI` games. Ranked, arena and casual are refused.
- Waits for the log to be quiet for 1.5 seconds before acting.
- Cancels if the state or packet changed while deciding.
- Treats a packet followed by newer state lines as stale and waits.
- Stops if the logged move differs from the plan.
- If no move appears within 5 seconds, resends a single-gesture move at most twice, only if nothing
  changed in the log. Multi-step moves are never resent.
- Stops on Esc, at the action limit, and when the game is over.
- `windows_input.py` also stops if the game loses focus or the window moves, and always releases
  the mouse button. These three checks need a real window and have no automated test.

## Evidence

| Check | Result |
| --- | --- |
| Agent tests | 98 pass |
| Safety rules removed and caught by a test | 57 of 57 |
| Recorded games parsed | 17 games, 714 of 714 moves match a legal option, 0 malformed |
| Moves with no state lines between packet and send | 714 of 714 |
| Real loop driven through recorded games | Completes 3 of 4 logs, with the 4th stopping on an unsupported `TARGET` choice |
| Ranked log cut off mid-game | Refused with 0 actions |

The loop test overrides the game-type gate, because no recorded game was a practice game.

## Move quality

From `experiments/imitation/`. This measures how often a method's top pick matched the move played
in 5 held-out games, across 213 decisions with at least 2 options. **Matching a player is not
playing strength.** Random would score 17.5%.

| Method (averaged over 4 orders unless noted) | Match |
| --- | --- |
| Always first option, no averaging | 10.3% |
| Laya with entity-ID inputs, as the project previously sent | 17.4% |
| Plain rules | 24.9% |
| Laya with readable inputs | 24.9% |
| Laya with readable inputs, fine-tuned | 29.6% |
| Deployed `LayaPolicy`, through the agent's parser | 28.2% |

Resampling whole games gives these 95% intervals:

- Readable over ID inputs: +7.5 points (1.1 to 15.8).
- Fine-tuned over rules: +4.7 points (1.5 to 8.4). Decision by decision this is 34 vs 24, which alone
  is not significant, and five games is too few for the interval to be trusted closely.

The fine-tuned model still changes its pick on 63.9% of decisions when the single-order option
order changes, which is why averaging stays on. The 3-decision gap between 29.6% and 28.2% has not
been traced. The shuffled orders and the parser differ slightly between the two paths.

**Limits of the training data:**

- Only 3 of the 17 games are Rogue, and none of the three was won.
- That Rogue is a Pirate/Yogg list, not either target deck. The model has seen neither target deck.
- The logged moves are the user's own, confirmed by the user on 2026-11-04.
- All 17 games came from one day, 16 of them had decisions, and the checkpoint uses only the 11 of those outside the test set.

Raw logs are kept in `.data/logs/` because the game deletes old sessions. The October 28 logs behind
earlier Rogue evidence were already gone, and only their derived files remain.

## Known gaps

**Needs a live game to settle:**

- Measured from one capture: heroes, hero power, End Turn and a six-card hand.
- Estimated and unverified: other hand sizes, minion rows, drop slots, mulligan cards and button,
  Discover cards, and Choose One cards.
- Whether a drag at this speed registers in the game.
- Whether 1.5 seconds is long enough for animations to finish.

**Abilities (Titan, Old God):** the order and positions come from one capture of N'Zoth with four
abilities. Whether a used ability keeps its slot, and other Titans' layouts, are unverified. Rules
use abilities first and pick by simple heuristics, because the model has never seen them.

**Not implemented, so the agent stops or never offers the move:**

- `TARGET` choices, and choices with more than one pick.
- Moves that target a card in hand. Only Agent of the Old Ones did this, and it is not in either deck.
- Tradeable as a separate action. No Tradeable option appeared in these logs, so the log format is
  unknown. Those cards are still played normally.
- New minions always go on the far right.
- Queueing, restarting and moving on to the next game.

**Weak decisions to expect:**

- Rules pick the highest-cost Discover offer and mulligan anything costing over 3.
- There is no deck plan, including for Preparation, Shadowstep, Combo or N'Zoth.

## Relation to the older code

The agent is separate Python, so it duplicates some of the Rust parser. The Rust and script safeguards
were not reused because they are built around partial candidate lists and one action at a time.
Merging or retiring them is an open decision.

## Retraining on Warrior games (2026-11-04)

A retrained checkpoint in `.data/imitation/laya-warrior` used the player's moves, with 114 Warrior decisions counted three times. It failed the switch rule set beforehand, so `.data/imitation/laya-finetuned` stays in use.

| Method | Warrior test (61 decisions, 2 games) | Older test (213 decisions, 5 games) |
| --- | --- | --- |
| Random | 23.7% | 17.5% |
| Current Laya | 47.5% | 28.2% |
| Retrained Laya | 37.7% | 28.2% |
| Plain rules | 49.2% | 25.8% |

The two models disagree on 37 Warrior picks, and each changes its pick on 29 of the 61 when the option order is reversed. Two games are too few to explain the drop, and tripling a small sample may have caused overfitting. This has not been tested.

## Combo lessons (2026-11-04)

`.data/imitation/laya-combo` is now the default checkpoint. It trained on the player's moves plus 420 lessons built from real Warrior training boards, where a combo's first step is labelled correct. Those labels are a stated opinion about card order, not the player's moves. `.data/imitation/laya-finetuned` is kept as a backup.

| Measure | Previous model | Combo model | Plain rules | Random |
| --- | --- | --- | --- | --- |
| Starts the combo, 120 lessons on held-out boards | 43.3% | 90.0% | 30.0% | 13.4% |
| Starts the combo, 8 real held-out positions | 4 of 8 | 8 of 8 | not measured | not measured |
| Matches the player, 61 held-out Warrior decisions | 47.5% | 50.8% | 49.2% | 23.7% |
| Matches the player, 213 older held-out decisions | 28.2% | 37.6% | 25.8% | 17.5% |

The lesson test uses the same lesson generator on unseen boards, so it shows these patterns were learned, not that the model can find new combos. Attack buffs before attacking are the weakest type, at 17 of 25. The model has not played live.

## First live run of the combo model (2026-11-04)

Practice game against the Innkeeper, session `.data/live/20261104-145903`, normal mode, 35 moves and no model
fallbacks. It stopped unfinished on turn 15 because four-card choices were clicked with the wrong spacing, so the
click landed between cards. The spacing is now 373 pixels, measured from that frame and covered by a test, but not
yet used live. Five-card spacing has still never been measured.

- Timing: all 31 option moves came on Laya's own turn, with the End Turn button lit or green in the frame saved just
  before input. One drag on turn 1 did not register and the retry worked.
- Combos: the game had one recognised combo position (turn 3) and Laya started it. One position is not evidence of
  a general improvement.

Restarting in the same game (session `.data/live/20261104-150635`) confirmed the four-card choice fix. It then stopped on
turn 17: with ten cards in hand the drag picked the card next to the planned one, and the sent-action check caught it.
Both were identical copies, so the game itself was unaffected. Hand positions for nine and ten cards now come from live
frames, and eight is still an estimate. These new positions have not been used live.

A third launch finished that game and won it (session `.data/live/20261104-151244`): 20 moves, no failed clicks, no
fallbacks. It played from nine- and eight-card hands without error. The game needed three launches, so this is not yet
a clean run from start to finish.

The next practice game ran from mulligan to win on one launch (session `.data/live/20261104-154036`): won on turn 9 at 30
health, 24 actions, no fallbacks. One drag on turn 1 did not register and the retry worked, the same thing seen in the
previous game's first move. Hands never went above four cards, so the large-hand positions were not exercised. Two wins
against the Innkeeper do not measure strength against real players.

## Speed changes (not yet tested live)

In the last timed game, 190 of 205 seconds were spent between the game offering moves and the agent sending one,
median 5.8 seconds a move. The game answered a sent move in about 0.35 seconds, and the model took about 0.1 seconds.
Most of the rest was four PowerShell captures at about 0.54 seconds each, a 1.5 second settle wait and about 1.45
seconds of mouse timing. Live play now reads the button in process (about 25 ms, same color as the script on one
comparison), saves frames only for failed clicks or with `--frames`, settles for 0.5 seconds and uses faster mouse
timing. A failed single-gesture move is retried at the old speed. `cli watch` records clicks and the frame before each
one, read-only, to measure the menus.

## First fast game: a loss, and what it showed

Session `.data/live/20261104-155440`. Ordinary moves took about 1.2 seconds, with no failed clicks. Laya lost, going second
for the first time with this model. Replaying 91 decisions from this game and three slower sessions gave the same choice
every time, so timing does not enter the choice. That is one fast game, so it does not show that speed has no effect on results.

- Going-second mulligan bug, fixed: the log lists four cards and The Coin, the screen shows four cards in a different
  layout, and the clicks missed. It kept two 4-cost cards it meant to replace and swapped a 3-cost card. Positions now come
  from a live frame, but have not been used live.
- Spare hero power, added: the turn cannot end with an untargeted hero power available. No held-out decision changed.
- The Coin, not fixed: Laya held it until turn 16. A rule that forced it lowered agreement with the player (Warrior 31 to
  29 of 61, older 80 to 76 of 213), so it was removed and not tuned on those games. In training games the player used it
  on only 5 of 59 decisions where it was available, with no clear pattern, which is too little to write a rule from.

## Automatic practice loop (not yet tested live)

`python -m agent.cli loop --games N` sends real input from the menus onward. It opens Hearthstone through Battle.net if
needed, walks to Practice, Expert, the player's deck and the Warrior opponent, plays, clicks past the end screens and
repeats. A menu click needs both the scene from `LoadingScreen.log` and screen regions compared with a recording of the
player's route (`agent/menu_refs.json`, rebuilt with `agent.menu.calibrate`). Unknown screens get no click. The game
must then report the expected deck ID in `Decks.log`, and the practice-only gate in the play loop still applies.

On the recording, each menu frame was identified as its screen or left alone, and no in-game frame read as a menu. Only a
loss was recorded, so the victory screen and any rewards after it are unseen. The launch path and login screens are also
unseen. Latest checks: 98 agent tests pass, and removing each of 57 safety rules is caught.

First live loop run (`.data/live/loop-20261104-161448`): game 1 won, the victory screen took 7 clicks, and the menu route
started game 2 by itself. Game 2 stopped on turn 9. An attack sent during the previous attack's animation left the
targeting arrow up, and every retry failed the same way. Retries now right-click to cancel first, not yet tested live.

Second live loop run (`.data/live/loop-20261104-162536`): the resumed game was lost, the next game was won going second, and
the run then stopped when the game lost focus before a Start click. Across both runs the loop finished 3 games against the
expert Warrior, 2 won and 1 lost, one of them resumed partway. Retries recovered every failed click in this run. A move
inside a turn took a median of about 1.6 seconds. Stop messages now name the window that took focus, and the loop waits
through login screens. Opening the game from closed has still never run.

## Mulligan and wasted mana (not yet tested live)

The mulligan has never used the model. It is a rule, now keeping cards costing up to 2 instead of 3, based on the player's
own habit. On 26 held-out mulligan cards it agrees with the player on 15 instead of 13, and on 50 training cards both rules
agree on 37, so this is weak evidence. It does not look at which cards work together.

A new rule refuses a card that cannot be part of any set spending the most mana this turn. The pre-set pass rule was a fall
of at most 3 points in match on each held-out set: Warrior went from 31 to 30 of 61 (down 1.6 points) and older stayed at 80
of 213. On replay it changes the Hogger plays on turns 15, 17 and 21 of a lost game. It also refuses some of the player's
own moves: 32 of 519 in training games.
