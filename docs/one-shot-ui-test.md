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
or automatically proceed to another action. After a full input insertion it now
performs bounded read-only checks described below; screen confirmation remains
an operator task.

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

## Post-input evidence checks (2026-10-29)

The user deferred live testing; this addition was built and tested offline only.
After a full three-event input insertion, the one-shot tool observes for at most
eight seconds, bounding each Rust replay subprocess by the remaining budget.
It requires exactly one new submission with the expected selection and prior
packet ID, followed by the next turn's stable MAIN_ACTION phase with the other
known player active. This reports `submission_and_handoff_observed`, not causal
execution confirmation. Existing incomplete observations remain incomplete.

Different or multiple submissions, game/session changes, a changed perspective,
invalid state, or unexpected turn/player stop the check. Partial or unfinished
prefixes remain pending until timeout. Results arriving at or after the deadline
are discarded. File replacement or truncation fails observation. No failure
triggers another input or clears the attempt reservation.

The result is saved in the attempt file with `execution_confirmed=false` and
`automatic_retry_allowed=false`. Seven new tests cover success-shaped evidence,
conflicting evidence, unfinished prefixes, deadline handling, session/read/schema
failures, and integration with the actual Rust replay JSON on a synthetic log.
No live clicks were performed for this update.

## Offline dispatch rehearsal

The live experiment now shares `ui_attempt.run_attempt` with offline tests.
Reservations are exclusive and fsynced before dispatch; receipt updates use an
fsynced temporary file and atomic replacement. An existing reservation blocks a
repeat regardless of its recorded outcome. The tool rechecks preconditions
after persisting dispatch intent, immediately before the input call.

Preflight failures and dispatch exceptions produce stable status codes rather
than exposing adapter error text. Partial input insertion skips evidence
collection and never retries. Evidence cannot grant execution confirmation or
permission to retry. A receipt-write failure before dispatch prevents input;
failure after dispatch leaves the existing reservation blocking another attempt.

Run the synthetic rehearsal without opening or controlling Hearthstone:

```powershell
.venv/Scripts/python.exe scripts/ui_attempt.py
```

The rehearsal exercises a full simulated batch followed by evidence timeout,
a partial batch, and a failed batch. Five regression tests also cover duplicate
reservation refusal, preflight changes during persistence, dispatch exceptions,
disk-write failure and invalid evidence claims. These validate orchestration,
not Windows input delivery. Live testing remains deferred.
