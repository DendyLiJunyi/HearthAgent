# Ranked modes and restarting

Wild uses the existing menu route and refresher. For example:

```powershell
.venv/Scripts/python.exe -m agent.cli loop --games 40 --mode wild --restart-every 5,6,7
```

Each interval is chosen again after reopening. Only completed games count; there
is no restart after the final requested game. Esc stops the run. Restart failures
save the games already completed. Both ranked modes reacquire the window, screen,
input handler, current log session and menu walker after reopening.

## Standard Warrior setup

Import the code in [the Standard profile](../config/decks/standard-warrior-cannon.json)
into Hearthstone yourself. Missing cards must be resolved in the game. Keep the
saved deck name and position stable. This profile is separate from Wild decks;
Standard automatically uses its mulligan and tactical rules unless `--no-tactics`
is supplied. `--deck-profile PATH` explicitly selects another metadata profile.
Profiles do not change observed card costs or generate legal actions.

For a game you start manually:

```powershell
.venv/Scripts/python.exe -m agent.cli play --execute --mode standard
```

This command checks the ranked format but does not select or verify a saved deck;
choose the imported Warrior yourself. Loops additionally require a saved deck ID
and calibrated menu profile. Find the ID in the current session's `Decks.log`
after selecting the deck (`# Deck ID:`). Do not reuse the Wild ID for another deck.

## Offline menu calibration

At 1920×1080, manually select Standard Ranked and the imported deck, with Play
enabled. Save an unfiltered RGB project screenshot using `GameScreen.save` (the
existing `scripts/capture_wild_calibration.py standard` capture command also
works and saves `.data/wild-calibration/standard.png`). This only captures the screen.
Inspect the screenshot to confirm the format, deck and Play state.

Create a separate profile from that image; substitute the actual saved deck ID,
tile text rectangle and tile center. Coordinates below illustrate the first tile:

```powershell
.venv/Scripts/python.exe -m agent.menu_profile --ready .data/standard-ready.png --deck-id YOUR_ID --deck-box 383 282 465 309 --deck-click 480 280 --output .data/standard-menu.json
.venv/Scripts/python.exe -m agent.cli loop --games 40 --mode standard --deck-id YOUR_ID --menu-profile .data/standard-menu.json --restart-every 5,6,7
```

The calibration reads a file and writes JSON; it sends no input. It samples the
format title, deck tile text, selected deck name and enabled Play button. Shared
startup and format-picker references come from existing recorded screens.
Calibration is an explicit assertion that the image shows the intended ranked
format and deck; it does not OCR the deck or establish Standard card legality.
Recalibrate if the deck moves, its name changes, or game UI changes. An incomplete
profile is rejected before opening the game. Unrecognized screens stop navigation.
The logged deck ID is checked again when the game starts; mismatch stops input.

Wild can also use `--menu-profile` calibrated with `--mode wild` for a changed tile.
Without one, it retains its existing menu references and deck ID default.

## Gameplay and verification limits

Both modes require Ranked and their exact format in the log before gameplay
input. The Standard rules keep Cannonmaster, Sky Raider, Living Flame, Engineer
and Hook n' Heave; keep Depths or Hand Cannon with an opener. Other cards are
returned. Shared rules handle Pirate buffs, Coin, attacks and visible lethal.
Standard rules prefer a remaining offered weapon swing before replacement,
avoid friendly removal targets, avoid lethal-to-friendly Depths activations,
and avoid Land Ho! when its second draw would overflow the hand. Discover and
unreviewed interactions retain the general policy. Random cannon and Volcano
damage, Dark Gifts and hidden triggers are not fully simulated.

Captain Crowley has explicit setup priority over ordinary draw/value plays and
hero weapon swings when affordable and there is space for his summons or existing
Cannoneers to buff. Guaranteed visible lethal stays first. A full board, an active
Risky Skipper, or an available survival Taunt under visible lethal pressure prevents
forcing this setup.

Timeline choices use the recorded bottom-left buttons, mapped by `TIME_000ta`
(Keep) and `TIME_000tb` (Rewind), independent of offer order. Stadium Announcer
rerolls when the opponent's observed weapon attack is at least 3 higher, reaches
your hero's remaining health plus armor, or your own weapon attack is at most 1.
Otherwise it keeps. Unknown Rewind sources/results keep by default; their effects
are not inferred from a zero-mana tie. Choice recordings include visible state,
source and decision reason. This is a narrow heuristic, not random-pool simulation.

Offline regressions cover the ranked guards, navigation, deck metadata, tactics,
restart intervals, fresh windows/logs and stop/failure handling. Live ranked
strength and live restart success are not established by these tests. No live
ranked games were started during this implementation. A later live acceptance
run should cross a restart boundary in each mode and confirm the intended deck.
