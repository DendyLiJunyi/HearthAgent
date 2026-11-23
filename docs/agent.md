# Live agent (`agent/`)

[Current status](current-status.md) is the authoritative capability summary.
See [fast play](fast-play.md) for the latest offline-tested pace, recovery and tactics changes, and
[reliability improvements](reliability-improvements.md) for the batch before it;
historical experiments below predate those changes.

Match-failure review, corrected-example training and the Patches mulligan fix are described in
[Learning from failed matches](learning.md).

## Ranked Wild loop (2026-11-04)

The menu loop now defaults to **Ranked Wild**, using the player's 海盗战 deck (ID `9567872927`).
It opens constructed play, switches Standard/Casual to Wild through the format picker when needed,
selects the calibrated Warrior tile, queues, plays, dismisses the result and repeats for the requested count.
Menu recognition requires the Chinese 1920×1080 layout, with 海盗战 in the first slot.
An unrecognized menu stops the run. Matchmaking may take up to 180 seconds.

```powershell
.venv/Scripts/python.exe -m agent.cli loop --games 3
.venv/Scripts/python.exe -m agent.cli loop --games 3 --mode practice
.venv/Scripts/python.exe -m agent.cli play --execute --mode wild
```

Switching to another app now pauses gameplay and menu input; returning to Hearthstone resumes it
after re-reading the log and rechecking the screen. With `--pace careful`, a focus change during a gesture
still stops the run; the default fast pace pauses and re-reads the log instead. Hold Esc to stop; Esc requires a new run.
Wild mode requires both `GT_RANKED` and `FT_WILD` in Power.log before any gameplay input.
Standard, Casual, missing formats and other game types are refused, even with `--friend-agreed`.
The deck-ID check, fresh-state checks, move confirmations and bounded retries remain in force.
`play` still defaults to practice; pass `--mode wild` to resume an online Wild game.
Runs save their selected mode and outcomes under `.data/live/loop-*/`.

Validation: 117 agent tests pass, and all 60 mutation checks were caught. One recorded run started
from Standard, switched to Wild, selected 海盗战, queued a Ranked Wild match, made 17 actions and lost, and returned to `TOURNAMENT` without a stop. Evidence is saved at
`.data/live/loop-20261104-181707/summary.json` and its `001/Power.log`.
This verifies one complete cycle; it does not establish playing strength or long-run reliability.

A later run stopped on its second game's first turn: the button was lit while start-of-game effects
and the opening draw were still animating, so all three drags were ignored. Live play now waits at
least 20 seconds after first seeing opening options, then applies the existing screen and log guards.
This is a conservative timing buffer, not a general animation detector. Resuming after turn two skips it.
Evidence: `.data/live/loop-20261104-184013/002/`.

Menu calibration frames are saved locally under `.data/wild-calibration/`. To rebuild the Wild
references from the saved `wild-ready.png` and `formats.png`, run
`python scripts/capture_wild_calibration.py --build-refs`. Practice calibration preserves these entries.

The older practice-only descriptions below describe the original implementation.

An earlier practice game required seven restarts.
No reliable win-rate estimate exists.

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
To play a friend who knows a bot is playing:

```powershell
.venv/Scripts/python.exe -m agent.cli friend --friend-agreed
.venv/Scripts/python.exe -m agent.cli friend --friend-agreed --games 3
```

Open Hearthstone, then send or accept the challenge and pick your deck yourself. The agent plays each
game and clicks past the end screen, then waits for the next challenge until Esc or `--games`. It acts
only in a friendly game and refuses anything else. If both players' names are in the log, it identifies
you by whose hand the client can read. This command has not yet run live.

`play --friend-agreed` also acts in a friendly challenge, but it plays one game and also allows AI games.
Practice mode refuses Ranked, Casual and Arena; `--mode wild` permits Ranked Wild only. The friendly game type name comes from the
game's known values and has not yet been seen in a log, so an unexpected name is refused too.

Hold **Esc** to stop. To check positions by eye,
capture a frame with `scripts/capture-game-window.ps1`, then run
`agent.cli preview <frame.png> <output.svg>` and open the SVG in a browser.

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
3. `policy.py` ranks the offered actions using rules and deck tactics.
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

## Known gaps

**Needs a live game to settle:**

- Measured from one capture: heroes, hero power, End Turn and a six-card hand.
- Estimated and unverified: other hand sizes, minion rows, drop slots, mulligan cards and button,
  Discover cards, and Choose One cards.
- Whether a drag at this speed registers in the game.
- Whether 1.5 seconds is long enough for animations to finish.

**Abilities (Titan, Old God):** the order and positions come from one capture of N'Zoth with four
abilities. Whether a used ability keeps its slot, and other Titans' layouts, are unverified. Rules
use abilities first and score their targets with heuristics.

**Not implemented, so the agent stops or never offers the move:**

- `TARGET` choices, and choices with more than one pick.
- Moves that target a card in hand. Only Agent of the Old Ones did this, and it is not in either deck.
- Tradeable as a separate action. No Tradeable option appeared in these logs, so the log format is
  unknown. Those cards are still played normally.
- New minions always go on the far right.
- Handling unrecognized menu dialogs or a Warrior deck moved away from its calibrated first slot.

**Weak decisions to expect:**

- Rules pick the highest-cost Discover offer and mulligan anything costing over 3.
- There is no deck plan, including for Preparation, Shadowstep, Combo or N'Zoth.

## Speed changes (not yet tested live)

In the last timed game, 190 of 205 seconds were spent between the game offering moves and the agent sending one,
median 5.8 seconds a move. The game answered a sent move in about 0.35 seconds.
Most of the rest was four PowerShell captures at about 0.54 seconds each, a 1.5 second settle wait and about 1.45
seconds of mouse timing. Live play now reads the button in process (about 25 ms, same color as the script on one
comparison), saves frames only for failed clicks or with `--frames`, settles for 0.5 seconds and uses faster mouse
timing. A failed single-gesture move is retried at the old speed. `cli watch` records clicks and the frame before each
one, read-only, to measure the menus.

## Play fixes from the 25-game baseline (not yet tested live)

`loop-20261105-100034` went 22-3 against the practice AI, always Warrior: 13-0 going first, 9-3 going second, and 4-3 in games
past turn 15. That is too close to the ceiling to compare versions by win rate, so `python -m agent.play_report <loop folder>`
counts events instead. Baseline: 11 wrong cards (10 of 105 plays from the leftmost card, 1 of 198 from the others), 85 drags the
game did not take, 17 wasted attacks, and 13 turns ended holding a Coin that could pay for a card.

- **Wrong card:** the leftmost card of five or more is now aimed 15 px further left. The cause was not found. Resting frames
  show the old point inside the card, and the cursor's starting position made no difference, so this is a guess to test live.
  A wrong card now saves a frame, taken after the move has gone through.
- **Wasted attacks:** the rules skip a minion attack that loses the minion and kills nothing, unless the target has Taunt
  or other legal attacks can finish it. The hero skips a hit of 4 or more that kills nothing, except on a Taunt, and never
  attacks into its own death. The policy then takes the highest-scoring remaining move.
- **The Coin:** about to end the turn, it spends The Coin if that pays for a minion or weapon, logged as
  `tactics:coin_before_passing`. Risky Skipper and spells do not count.

## Restarting during a long run

`loop --restart-every 5,6,7` closes and reopens Hearthstone between games, picking 5, 6 or 7 games at random for each
stretch. It closes only after the end screens have gone, and never in the game scene. It posts `WM_CLOSE`, waits up to
30 s for the process to exit, and only then forces it. The game reopens through the same Battle.net path as a cold start,
and the window, screen, input and logs are rebuilt for the new client. A failed restart stops the run and saves its summary.

Seen live: 4 restarts across 28 practice games (`loop-20261105-094404` and `loop-20261105-100034`), and both runs ended only
when stopped from the terminal. If Windows refuses to bring the new window forward, menu input waits until the game is clicked.

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


First opening from closed (2026-11-04 16:54, Battle.net log `battle.net-20261104T085429`): Battle.net received `--exec=launch WTCG` and logged in after 6 seconds, then logged no launch in the 90 seconds before it was closed. Clicking Play logs `LaunchBinary: uid=hs_beta`. The loop now reads that log and repeats the request once logged in, every 15 seconds and up to 4 requests in all, stopping as soon as a launch is logged. Tested offline only. The second live opening (17:00) confirmed it: the repeated request was obeyed and the game started about 15 seconds after the first request.

That run then waited at the entrance door, which needs a click (点击开始) and is still scene LOGIN, so the walker never clicked. The door is now a menu screen with two regions taken from that run's frame (`entrance.png` in the recording folder), and scene LOGIN gets no other click. Tested offline against that frame. The click itself, and anything between the door and the main menu, has not been seen live.

## Mulligan and wasted mana (not yet tested live)

The general mulligan rule keeps cards costing up to 2 instead of 3, based on the player's
own habit. On 26 held-out mulligan cards it agrees with the player on 15 instead of 13, and on 50 training cards both rules
agree on 37, so this is weak evidence. It does not look at which cards work together.

A new rule refuses a card that cannot be part of any set spending the most mana this turn. The pre-set pass rule was a fall
of at most 3 points in match on each held-out set: Warrior went from 31 to 30 of 61 (down 1.6 points) and older stayed at 80
of 213. On replay it changes the Hogger plays on turns 15, 17 and 21 of a lost game. It also refuses some of the player's
own moves: 32 of 519 in training games.
