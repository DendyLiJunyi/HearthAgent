# Hearth Agent

An agent that plays Hearthstone on Windows. It reads the game state from Hearthstone's own log files,
chooses moves with deterministic rules, and plays them with mouse input. It does not read
game memory or change the game client.

It can play:

| Game | Command | You do | The agent does |
| --- | --- | --- | --- |
| Against a friend | `friend` | Send or accept the challenge, pick the deck | Plays each game, waits for the next challenge |
| Practice against the AI | `loop --mode practice` | Start the command | Opens the game, goes through the menus, plays, repeats |
| Ranked Wild | `loop` | Start the command | Opens the game, goes through the menus, plays, repeats |
| One game already open | `play --execute` | Start the game, click its window | Plays that game |

The tactics were tuned for Pirate Warrior, so expect weaker play with other decks.

> **Account risk:** Blizzard's terms restrict bots and automation, so using this on a Ranked account puts
> that account at risk, and Ranked opponents are real people who have not agreed to play a bot. Use
> `friend` only when your opponent knows a bot is playing.

## Use it

### Windows control panel

Double-click `控制台.cmd` in the project folder, or run:

```powershell
.venv/Scripts/python.exe -X utf8 -m agent.control_panel
```

Use **接管当前对局** to control a game you already started, or **循环对局** to start and play a set
of games. Both use the rules policy. **检测 MAKCU** checks the serial handshake and **查询对局**
reads the latest match state. Use **停止任务** to stop a running task and wait for it to release
mouse input before starting another one.

Click **保存设置** to restore the current form automatically the next time the control panel opens.
The saved form is stored in `.data/control-panel.json`.

**胜率记录** shows today's and all-time results for the selected mode and updates after each saved game.
Enter an inclusive date range in `YYYY-MM-DD` format and click **刷新** to view results for that period.
Either date may be left blank for an open-ended range. Clearing both returns to the default view.
Win rate is wins divided by completed games, including draws.

### PowerShell commands

Run these from the project folder in PowerShell. If you made `config/agent.json` during setup, add
`--config config/agent.json` straight after `agent.cli`.

### Play a friend

```powershell
.venv/Scripts/python.exe -m agent.cli friend --friend-agreed             # until you hold Esc
.venv/Scripts/python.exe -m agent.cli friend --friend-agreed --games 3
```

1. Open Hearthstone and start the command.
2. Send or accept the challenge and pick your deck.
3. The agent plays and clicks past the end screen. Then it waits for your next challenge, for as long as you like.

It refuses any game that isn't a friendly challenge. This command has not yet run in a real friend match,
so start with `--games 1`.

### Practice or Ranked Wild

Standard Ranked with the supplied 火炮战 deck is also supported. See
[ranked modes and deck calibration](docs/ranked-modes.md) for import, setup and
restart commands. Standard loops require the imported deck ID and a calibrated menu profile.

```powershell
.venv/Scripts/python.exe -m agent.cli loop --games 3 --mode practice
.venv/Scripts/python.exe -m agent.cli loop --games 3                     # Ranked Wild
```

For a long run, add `--restart-every` to close and reopen the game between games:

```powershell
.venv/Scripts/python.exe -m agent.cli loop --games 40 --mode practice --restart-every 5,6,7
```

With several numbers, it picks one at random each time, so this restarts after 5, 6 or 7 games. A single number,
such as `--restart-every 6`, keeps it fixed. It only closes the game between games, and asks it to close before
forcing it. Keep Battle.net logged in. It has run live: 4 restarts across 28 practice games.

If Hearthstone is closed, the agent opens it through Battle.net. Click the game window within 60 seconds of
the prompt. It stops if a menu looks unfamiliar, or if the game starts with a different deck from the one set up.
The recorded Chinese “error starting game” and “opponent could not connect” dialogs are dismissed automatically before other menu clicks.
The loop waits two minutes before trying again, with at most three recoveries per game search.
Other dialogs remain unrecognized. Escape still stops the loop during the wait.

### One game

```powershell
.venv/Scripts/python.exe -m agent.cli play --execute                     # practice game
.venv/Scripts/python.exe -m agent.cli play --execute --mode wild         # Ranked Wild game
.venv/Scripts/python.exe -m agent.cli play                               # dry run: prints the plan, sends nothing
```

### Connect MAKCU for live play

`play --execute`, `loop`, and `friend` require a MAKCU. Connect the box's USB1 and USB2 ports to the
Windows PC running the agent, and connect your mouse to USB3. Install the CH343 driver if Windows
does not show a serial port. Run `scripts/setup-runtime.ps1` again if you installed the runtime before
MAKCU support was added. See the [MAKCU setup guide](https://makcu.com/en/setup).

The agent looks for one compatible CH343 serial port and checks its MAKCU identity. If automatic
detection finds no port or more than one, use the COM name shown in Device Manager. For example,
open a practice match and run:

```powershell
.venv/Scripts/python.exe -m agent.cli play --execute --mode practice --makcu-port COM3
```

The agent tries 115200 and 4000000 baud by default. Use `--makcu-baud 115200` or
`--makcu-baud 4000000` to use a known rate. If the port is busy, close the MAKCU configurator or
other software using the port. If the cursor repeatedly misses its target, try disabling **Enhance
pointer precision** in Windows mouse settings. Preview, status, watch, and dry runs do not open the
serial port.

### While it plays

- **To stop:** hold **Esc**, or press Ctrl+C in the terminal.
- **To pause:** switch to another app. Input pauses until Hearthstone is back in front, but the game's turn timer keeps running.
- **Don't use the mouse in the game:** the agent is using it.

### Useful options

| Option | Commands | Effect |
| --- | --- | --- |
| `--aggressive` | all | Attack the enemy hero whenever possible |
| `--no-tactics` | all | Turn off the Pirate Warrior tactics |
| `--pace careful` | all | Play slower, and stop on a failure instead of recovering |
| `--frames` | all | Save a screenshot before every move (slower) |
| `--deck-id <id>` | `loop` | Expect a different deck |
| `--restart-every <n,...>` | `loop` | Close and reopen the game between games |

### After a game

Each run is saved in `.data/live/<run>/`. There's a `summary.json` for `loop` and `friend`, and for each game:

| File | Contents |
| --- | --- |
| `outcome.json` | Result, and any recoveries or stop reason |
| `moves.jsonl` | Every move, with the state and the End Turn button reading |
| `lessons.md` | Review of the agent's decisions |
| `Power.log` | Copy of the game log |

```powershell
.venv/Scripts/python.exe -m agent.cli status                             # what the current log shows
.venv/Scripts/python.exe -m agent.pace_report .data/live/<run>/001       # how fast the moves were
.venv/Scripts/python.exe -m agent.play_report .data/live/<loop folder>   # record and play mistakes across a run
```

To teach the agent from its mistakes, see [Learning from failed matches](docs/learning.md).

## Set up on a new computer

### What you need

- Windows 10 or 11, 64-bit
- Disk space for Python, card data and saved recordings
- Git, Battle.net and Hearthstone
- A copy of the card data from step 3

These steps have not yet been run from scratch on a second computer.

### 1. Get the code

On the old computer, commit and push any work first, because only pushed work will reach the new one. Then:

```powershell
git clone https://github.com/DendyLiJunyi/HearthAgent.git
cd HearthAgent
```

### 2. Install Python and the dependencies

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-runtime.ps1
```

This downloads `uv`, Python 3.12.16 and pyserial into the project folder (`.tools/` and `.venv/`). Nothing is installed system-wide.

### 3. Copy the card data

Copy `.data/cards-enUS.json` from the old computer to the same path in the new project folder.

### 4. Turn on Hearthstone's logs

Create or edit `%LOCALAPPDATA%\Blizzard\Hearthstone\log.config` so it contains these sections:

```ini
[Power]
LogLevel=1
FilePrinting=true
ConsolePrinting=false
ScreenPrinting=false
Verbose=true

[LoadingScreen]
LogLevel=1
FilePrinting=true
ConsolePrinting=false
ScreenPrinting=false
Verbose=true

[Decks]
LogLevel=1
FilePrinting=true
ConsolePrinting=false
ScreenPrinting=false
Verbose=false
```

Restart Hearthstone afterwards. Logs then appear in `<Hearthstone folder>\Logs\Hearthstone_<time>\`.

### 5. Point the agent at your install

The built-in paths are `D:\Hearthstone` and `D:\Battle.net\Battle.net.exe`. If yours differ, or you use a
different deck, copy `config/agent.example.json` to `config/agent.json` and edit it:

```json
{
  "install": "C:/Program Files (x86)/Hearthstone",
  "battle_net": "C:/Program Files (x86)/Battle.net/Battle.net.exe",
  "deck_id": "9567872927"
}
```

Then pass it before the command name, every time:

```powershell
.venv/Scripts/python.exe -m agent.cli --config config/agent.json friend --friend-agreed
```

Relative paths are measured from the config file's folder. To find a `deck_id`, start a game with the deck,
then look in that session's `Decks.log` for the `# Deck ID:` line after `Finding Game With Deck`.

### 6. Set up the game

- **Game area:** exactly 1920×1080. Click positions are fixed to this size, and the End Turn check won't run at any other.
- **Language:** Chinese client. The agent recognizes the mulligan and menu screens by comparing them with recordings of that client. In another language, `loop` stops at the menus, and the other commands leave each mulligan to the game's timer, so you keep your opening hand.
- **Deck, for `loop` only:** your deck in the first slot.

### 7. Check it works

Nothing here sends input to the game.

```powershell
# Tests
.venv/Scripts/python.exe -m unittest discover -s agent -p "test_*.py" -t .

# Log files, after opening Hearthstone once
.venv/Scripts/python.exe -m agent.cli status
```

Then try a practice game with `play --execute` before anything else.

## Troubleshooting

| Message or symptom | Likely cause | Fix |
| --- | --- | --- |
| `no Hearthstone log session found` | Wrong install path, or logs are off | Check steps 4 and 5, then restart Hearthstone |
| `screen checks require 1920x1080` | Wrong game area size | Change the game's resolution (step 6) |
| `the game window never got focus` | Game window wasn't clicked within 60 seconds | Click it sooner after the prompt |
| `the game started with deck ..., not ...` | A different deck was used | Set `deck_id` or pass `--deck-id` |
| `refusing to act in ...` | This command doesn't allow that game type | Use the matching command |
| `cannot tell which player is local` | Couldn't work out which player is you | Keep that run's `Power.log` for debugging, and restart at the next game |
| A menu is `unrecognized`, or the loop stops at a menu | Layout differs from the recordings | Start the game yourself and use `play` or `friend` |
| Moves pause with nothing happening | Another app is in front | Click Hearthstone |
| After a restart, the game opens but nothing clicks | Windows kept another app in front | Click Hearthstone once |

## More detail

- [Current status](docs/current-status.md): what has been verified and what hasn't
- [Live agent](docs/agent.md): safety rules, evidence and history
- [Fast play](docs/fast-play.md): pacing, recovery and tactics
- [Reliability improvements](docs/reliability-improvements.md)
- [Learning from failed matches](docs/learning.md)
