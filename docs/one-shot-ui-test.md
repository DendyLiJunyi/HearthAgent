# One-shot end-turn UI experiment

`scripts/test_end_turn_once.py` is an explicitly invoked integration experiment,
not a gameplay policy or the production ActionExecutor. It does not turn an
incomplete observation into an executable controller snapshot.

The caller binds it to an exact log session, game number, and turn. It requires
a stable local MAIN_ACTION phase, closed power structure, fresh option packet,
and a single end-turn option. After focusing Hearthstone it captures the window,
checks the calibrated 1920x1080/DPI-96 layout and yellow button appearance, then
rechecks geometry, focus, log length/timestamp, held mouse buttons and Escape,
and whether the click location belongs to the game window.

The yellow-pixel check is a narrow heuristic for the visually inspected layout,
not general screen recognition. It must not be used to authorize arbitrary
cards, targets, or alternate layouts. Live calibration and the independent log
checks are both required. Input can still become uncertain after validation.

Without `--execute`, it checks only the baseline. With `--execute`, it reserves
a unique session/game/turn attempt file and fsyncs it before sending exactly one
move/down/up batch. Existing reservations prevent duplicate attempts. A partial
or failed SendInput result is never retried. The tool does not certify execution
or automatically proceed to another action; the operator must inspect fresh
screen/log evidence afterward.

```powershell
.venv/Scripts/python.exe scripts/test_end_turn_once.py --session <session-directory-name> --game <game-number> --turn <turn-number>
# Only for the explicitly intended live test:
.venv/Scripts/python.exe scripts/test_end_turn_once.py --session <session-directory-name> --game <game-number> --turn <turn-number> --execute
```

The user confirmed the visible player match was the intended test match. The
first run was bound to game 4, turn 7 of session
Hearthstone_2026_10_28_23_10_27. It aborted at the initial state check because the
turn had changed before execution. **No input was sent.** This validates stale
baseline refusal, not live click delivery or completion.

Three regression tests cover exact game/turn binding, stale/incomplete/opponent
state rejection, and the Windows INPUT layout and bounded virtual-screen mouse
coordinates. Actual click delivery and post-click confirmation still need a
successful live test. The user was asked to leave a turn for that test.
