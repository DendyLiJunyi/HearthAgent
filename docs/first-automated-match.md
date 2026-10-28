# Route to the first automated match

Use the existing Power.log observer together with screen observations and an
external Windows input adapter. The first target is a manually opened practice
match with the fixed Rogue deck, from the opening selection through the result
screen. Queue navigation can follow after in-match control works.

The existing implementation cannot yet do this. The following stages describe
remaining implementation work, not capabilities already delivered.

1. Establish the game window, client-area geometry, physical-pixel coordinate
   space, and a session-bound screen calibration. Detect minimized, moved,
   resized, missing, or unfocused windows. Establish local identity from the
   verified practice-match UI before mulligan submission.
2. Combine fresh logs with screen state to validate one supported transaction:
   start with an end-turn click, then a targeted attack. Recheck the window,
   screen, game/session, entities, phase, and coordinates immediately before
   input. Never promote existing incomplete diagnostic snapshots to complete.
3. Observe input delivery separately from game effects. Verify the expected
   screen/log transition after each transaction, with a deadline and stop control.
   Missing evidence enters recovery; it must not cause repeated clicks. The
   existing offline turn-progression audit alone cannot confirm causation.
4. Implement hand play, target selection, board placement, hero power, mulligan,
   choices, and Tradeable transactions for this deck. Map entity IDs to current
   screen locations after each action; do not reuse old hand indices.
5. Run a deterministic rules baseline over validated supported candidates.
   Let Laya rank candidates where it passes confidence/order checks, with a
   rules fallback for abstention. Unknown state or unsupported interactions
   require recovery, not a blind end-turn fallback. Measure decisions on
   independently reviewed positions before claiming strategic quality.
6. Complete and replay one practice match, then repeat across multiple games.
   Passing one transaction or finishing by skipping every turn is not acceptance
   of full Rogue gameplay. Track interventions, unsupported mechanics, incorrect
   actions, and unconfirmed effects separately from wins/losses.

## Implemented starting point

`scripts/probe_game_window.py` enumerates visible windows whose process image is
Hearthstone.exe using limited query access. It records HWND, PID, foreground and
minimized status, DPI, and the client rectangle in physical screen coordinates.
It neither reads game-process memory nor sends input or changes focus. Its
coordinate helper supports negative monitor origins and rejects invalid points.
Calibration points still need to be obtained from a real game screen; the tool
does not invent card or button positions.

```powershell
.venv/Scripts/python.exe scripts/probe_game_window.py --output .data/game-window-probe.json
```

The desktop probe may need to run outside the Codex sandbox because desktop
enumeration is restricted there. Two geometry tests pass. After the user opened
the game, the probe found a 1920x1080 client area at DPI 96. A read-only
`scripts/capture-game-window.ps1` capture using PrintWindow also succeeded and was
visually inspected. It captures the game client area without changing focus.

```powershell
powershell.exe -NoProfile -File scripts/capture-game-window.ps1
```

A draft local calibration records the end-turn button, both heroes and hero
power, bound to the reference capture hash. It remains non-actionable and lacks
hand/minion entity mapping. Capture and calibration files remain under ignored
`.data`; no player screenshot is published in the repository. The observed
screen appeared to be a normal player match; the user confirmed it was the
intended test match. The [one-shot input experiment](one-shot-ui-test.md) was
implemented, but its first live invocation aborted on a changed turn before
dispatch. No game input has been sent.

The existing `watch --once` command performs one bounded read. A large active
log can therefore return `backlog=true`; that is not a current snapshot. Any live
adapter must consume the continuous watcher until caught up and revalidate its
session, revision, pending bytes, and screen state immediately before dispatch.

Window identity and geometry are only inputs to future validation, not an
execution permit. The probe output explicitly remains `actionable=false`.

For the input implementation, Microsoft documents that [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
inserts input events but is subject to integrity-level restrictions. Its return
value must not be treated as confirmation of a game action. This is why the
adapter needs separate observation and recovery.
