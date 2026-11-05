# Hearth Agent

An agent that plays Hearthstone on Windows. It reads the game state from Hearthstone's own log files,
chooses moves with a fine-tuned Laya model and rules, and plays them with mouse input. It does not read
game memory or change the game client.

It can play:

| Game | Command | You do | The agent does |
| --- | --- | --- | --- |
| Against a friend | `friend` | Send or accept the challenge, pick the deck | Plays each game, waits for the next challenge |
| Practice against the AI | `loop --mode practice` | Start the command | Opens the game, goes through the menus, plays, repeats |
| Ranked Wild | `loop` | Start the command | Opens the game, goes through the menus, plays, repeats |
| One game already open | `play --execute` | Start the game, click its window | Plays that game |

The model and tactics were tuned for Pirate Warrior, so expect weaker play with other decks.

> **Account risk:** Blizzard's terms restrict bots and automation, so using this on a Ranked account puts
> that account at risk, and Ranked opponents are real people who have not agreed to play a bot. Use
> `friend` only when your opponent knows a bot is playing.

## Use it

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

### One game

```powershell
.venv/Scripts/python.exe -m agent.cli play --execute                     # practice game
.venv/Scripts/python.exe -m agent.cli play --execute --mode wild         # Ranked Wild game
.venv/Scripts/python.exe -m agent.cli play                               # dry run: prints the plan, sends nothing
```

### While it plays

- **To stop:** hold **Esc**, or press Ctrl+C in the terminal.
- **To pause:** switch to another app. Input pauses until Hearthstone is back in front, but the game's turn timer keeps running.
- **Don't use the mouse in the game:** the agent is using it.

### Useful options

| Option | Commands | Effect |
| --- | --- | --- |
| `--policy rules` | all | Use the rules without the model, so no GPU is needed |
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
```

To teach the agent from its mistakes, see [Learning from failed matches](docs/learning.md).

## Set up on a new computer

### What you need

- Windows 10 or 11, 64-bit
- An NVIDIA GPU for the model (it has run on an RTX 4060 with 8 GB). `--policy rules` works without one.
- About 8 GB of disk space, mostly for the Python environment
- Git, Battle.net and Hearthstone
- The old computer, or a copy of its files, because the two items in step 3 are not in Git

These steps have not yet been run from scratch on a second computer.

### 1. Get the code

On the old computer, commit and push any work first, because only pushed work will reach the new one. Then:

```powershell
git clone https://github.com/DendyLiJunyi/HearthAgent.git
cd HearthAgent
```

### 2. Install Python and the dependencies

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-laya.ps1
```

This downloads `uv`, Python 3.12.16 and the pinned packages, including PyTorch with CUDA, into the project
folder (`.tools/` and `.venv/`). Nothing is installed system-wide. Ignore the message about `probe.py`: the agent doesn't need it.

### 3. Copy the model and card data

Copy these from the old computer to the same paths in the new project folder:

| Path | Size | Contents |
| --- | --- | --- |
| `.data/imitation/laya-combo/` | 650 MB | The trained model, which can't be downloaded |
| `.data/cards-enUS.json` | 10 MB | Card data, needed even with `--policy rules` |

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
  "deck_id": "9567872927",
  "checkpoint": "../.data/imitation/laya-combo"
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

# Model and GPU
.venv/Scripts/python.exe -c "from agent.policy import LayaPolicy, load_cards; print('model ready:', LayaPolicy.load(load_cards()).checkpoint)"

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
| CUDA or model error at launch | No NVIDIA GPU or driver, or step 3 is incomplete | Update the driver, check the copied files, or use `--policy rules` |
| Moves pause with nothing happening | Another app is in front | Click Hearthstone |
| After a restart, the game opens but nothing clicks | Windows kept another app in front | Click Hearthstone once |

## More detail

- [Current status](docs/current-status.md): what has been verified and what hasn't
- [Live agent](docs/agent.md): safety rules, evidence and history
- [Fast play](docs/fast-play.md): pacing, recovery and tactics
- [Reliability improvements](docs/reliability-improvements.md)
- [Learning from failed matches](docs/learning.md)
- [Design](docs/design.md) and [roadmap](docs/roadmap.md) for the older Rust code
- [Laya](docs/laya.md): model setup and results

## Older Rust tools

`src/` holds an earlier read-only observer and adviser. The agent above doesn't use it, and it's only needed
for log inspection or Rust development. It needs a Rust toolchain; run `cargo fetch` once before using `--offline`.

```powershell
cargo run --offline -- inspect D:\Hearthstone
cargo run --offline -- watch D:\Hearthstone
cargo run --offline -- replay <Power.log> --json
cargo test --offline
```
