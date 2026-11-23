# Reviewing failed matches

After a match, the agent writes `lessons.json` and `lessons.md` beside `moves.jsonl` and `Power.log`.
A completed loss produces review cases only for the agent's own planned actions that match a
confirmed `SendOption`. Failed gestures, stopped games, unrelated games in the same log and later
human moves are excluded. Wins are retained as recordings but do not create loss cases.
Copied decisions deduplicate by the contents of the state, candidates and chosen action.

The review includes card names, all executable alternatives, the chosen move and heuristic hints.
Hints are suggestions for human review. For example, a general hint to play an attack buffer can be wrong
when summoning it triggers Risky Skipper and kills the attacker. Losing does not establish that
every move was wrong, either.

Collect recordings and preserve existing corrections:

```powershell
.venv/Scripts/python.exe -m agent.learn collect
```

This writes `.data/learning/cases.jsonl`, `summary.json` and an initial `labels.json`. Read the
per-session `lessons.md`, then record a specific correction with its case ID and candidate number:

```powershell
.venv/Scripts/python.exe -m agent.learn label --id <case-id> --corrected <index> --reason "Why this move is better"
```

Corrections require a reason, reviewer identity, a different legal action and unchanged case contents.
The first five saved corrections are assistant board-review judgments, not user demonstrations or
proven optimal actions. They cover a survival Taunt, unsupported synergy minions, summoning
Parachute Brigand for free and ordering Risky Skipper before a follow-up minion.
