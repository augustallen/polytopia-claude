# polytopia-claude

Have Claude play *The Battle of Polytopia* (single-player, against the game's built-in bots) with
exact game state in and legal actions out, and measure how well it does. See `PLAN.md` for the
full plan and rationale.

```
Polytopia (Steam, Windows) + BepInEx 6 + PolyMod      harness/ (Python 3.11+)
  └─ mod/ClaudeBridge  ── JSON over TCP :9876 ──►    client → observe → agent (Claude) → logger
       state + legal actions  ◄── action ──          play_game.py / run_eval.py
```

| Part | What | Status |
|---|---|---|
| `mod/ClaudeBridge` | PolyMod plugin: serializes the fog-filtered `GameState` and every legal command, executes actions through the game's own client path, handles popups, can resume/start games | working (2.17.2) |
| `harness/polytopia_bridge` | `client.py` (socket), `observe.py` (state → ~900-token text), `agent.py` (Claude per-action decision with rolling notes; random baseline), `runner.py`, `logger.py` | working |
| `harness/scripts` | `play_game.py` (one game), `run_eval.py` (ladder → CSV), `smoke.py`, `bridgectl.py` | working |
| `docs/` | `SETUP_WINDOWS.md` (install/build/run), `PROTOCOL.md` (message schema) | |

## Quick start (Windows box with the game installed)

```powershell
# one-time: docs/SETUP_WINDOWS.md (BepInEx + PolyMod, .NET 6 SDK, build the mod, portable Python)
cd harness
python -m pytest -q                                   # offline tests against recorded states
python scripts/play_game.py --new --agent random --opponents 1 --map-size 11 --max-turns 5
# Claude via your Claude subscription (headless Claude Code, ~10 s/decision, no API key):
python scripts/play_game.py --new --agent claude-code --model claude-sonnet-5
# Claude via the API (needs ANTHROPIC_API_KEY; faster, effort knob, exact token accounting):
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python scripts/play_game.py --new --model claude-fable-5-1 --effort medium
python scripts/run_eval.py --games 5 --difficulties Easy,Normal --agents random,claude-code:claude-opus-5
```

The game window must be open (the bridge lives inside it); `--new` starts a game from the menu,
`--resume` continues the saved one. Per-game JSONL logs hold every state, prompt decision and
result; `results/results.csv` accumulates the ladder.

## Scope / safety

Single-player only: the bridge refuses to act in any other `GameType`, never touches multiplayer,
and there is no Steam-account automation. Midjiwan's ToS (2.5) covers automation broadly; this is
the user's own offline use.
