# Plan: Have Claude play The Battle of Polytopia and measure how good it is

## Context

Goal: get Claude playing real single-player Polytopia games against the built-in bots, with exact game state in and legal actions out, so we can measure its strength (score in Perfection mode, win rate in Domination) and compare models. There is no official mod API, but the community has built enough that this is a well-trodden path rather than a research project.

## Feasibility verdict: feasible, ~1-2 weeks of part-time work, on the Windows PC

What makes it tractable (all verified by reading source, not just READMEs):

- **The game is Unity IL2CPP on Steam, and has a mature mod loader.** PolyMod (github.com/PolyModdingTeam/PolyMod, active, last release v1.2.17 in July 2026) wraps BepInEx 6 IL2CPP. Windows x64 is the only fully supported platform. macOS/Linux are "partial", and macOS ARM is explicitly unsupported (this Mac is arm64, and BepInEx only ships `Unity.IL2CPP-macos-x64`). Hence: host the game on the Windows PC.
- **The game's rules engine is a plain C# assembly (`GameLogicAssembly`, namespace `Polytopia.Data`) with exactly the API we need.** Every player action is a `CommandBase` subclass (`MoveCommand`, `AttackCommand`, `TrainCommand`, `ResearchCommand`, `BuildCommand`, `CaptureCommand`, `EndTurnCommand`, `CityRewardCommand`, ...) with `IsValid(GameState)`. Legal-move enumeration exists in-engine: `unit.GetMovementOptions`, `unit.GetAttackOptions`, `CommandUtils.GetUnitActions`, `GameLogicData.GetUnlockableTech`, `GetUnlockedImprovements`, plus `BattleHelpers.GetBattleResults` for damage previews. Execution goes through `ActionManager.ExecuteCommand(cmd, out error)`.
- **Three public projects already do the bridge we want, so we copy patterns instead of reverse-engineering:**
  - `NovaVanity/PolyZero` `bridge/PolyZeroBridge/PolyZeroBridgePlugin.cs` (Aug 2026): a PolyMod plugin that opens a TCP socket, sends JSON state on the AI player's turn, receives JSON actions, validates and executes them in the live game. This is the closest template.
  - `Willibombb/PolytopiaProject` `csharp-backend/PolyterraEnvBridge.cs`: the best reference for a complete `GetValidActions` enumeration and for constructing every command type, including city level-up reward choices (`TryGetPendingCommandTrigger`).
  - `HenBOMB/Polyfish` `polyfish-mod/`: a working PolyMod `.csproj` (net6.0, references the BepInEx `interop/` DLLs) and a full `GameState` -> JSON serializer (`PolyfishSerializer.cs`).
- **Built-in bot opponents come for free.** In a single-player game the mod controls the human seat; the game's own AI plays the other tribes at Easy/Normal/Hard/Crazy. That is the benchmark.

What does not work or is not worth it:

- **Screenshots + clicking (computer use):** viable fallback but lossy (unit HP, tech, fog state from pixels) and slow. Only if the mod route dies.
- **Headless engine without Unity:** Polyterra compiles a decompiled `GameLogicAssembly` as a normal .NET project, which would be much faster than driving the Unity client. But that source is not in the repo and IL2CPP builds do not decompile to compilable C#. Treat as a stretch goal, not the plan.
- **Open-source reimplementations** (GAIGResearch/Tribes in Java, tribes-rl in C, Polyfish's Rust engine): useful for fast iteration on the prompt, but the user asked about the real game, so these are optional.

### Terms of service

Midjiwan's ToS section 2.5 says users agree "not to use bots, scripts, automation tools ... to access or interact with Polytopia in a way not expressly permitted by Midjiwan," with no single-player carve-out. The same clause covers every mod in the PolyMod catalogue, and the community mods (including in-game AI mods) have run for years without issue, but this is the user's risk to accept. Mitigations baked into the plan: offline games only (single-player, and since 2026-09-07 the offline Pass & Play hotseat mode so two agents can share one device), never online multiplayer, the plugin refuses to activate unless `GameType` is SinglePlayer or PassAndPlay (the single-player guard is the same one `CAs-mods/polytopia-cheatmod` uses), and no Steam account automation of any kind.

## Architecture

```
Windows PC                                              Mac (or Windows)
┌──────────────────────────────────────────────┐        ┌──────────────────────────┐
│ Polytopia (Steam) + BepInEx 6 + PolyMod      │        │ harness/ (Python)        │
│  └─ ClaudeBridge.dll (our PolyMod plugin)    │ JSON   │  ├─ bridge client        │
│      • Harmony hook: on our player's turn    │◄──────►│  ├─ observation builder  │
│      • serialize GameState + legal actions   │  TCP   │  ├─ Claude agent loop    │
│      • validate + ExecuteCommand             │        │  ├─ game logger (JSONL)  │
│      • loopback by default, LAN opt-in       │        │  └─ eval / stats         │
└──────────────────────────────────────────────┘        └──────────────────────────┘
```

Protocol (newline-delimited JSON over TCP, PolyZero style, port 9876):

1. Plugin sends `{"type":"state", "turn":N, "player":id, "state":{...}, "legal_actions":[...]}` whenever it is our turn and the last action finished.
2. Harness replies with one action, e.g. `{"type":"action","action":{"kind":"move","unit_id":12,"to":[4,7]}}`.
3. Plugin builds the `CommandBase`, checks `IsValid`, executes via the client's `ActionManager`, and replies with `{"type":"result","ok":true|false,"error":"..."}` followed by a fresh `state`.
4. `end_turn` hands control to the bots. Plugin sends `{"type":"game_over", ...}` when `GameState.CurrentState` ends.

Runtime location: the mod must be built and run on Windows. The Python harness can run on the Mac over LAN (plugin binds `0.0.0.0` only when a config flag is set) or on the Windows PC on loopback. Recommendation: run Claude Code on the Windows PC for the C# work, keep the harness cross-platform so it runs from either box.

## Repository layout (new repo `polytopia-claude`, created in `~/Claude/`, pushed to GitHub, cloned on Windows)

```
polytopia-claude/
├── README.md
├── mod/ClaudeBridge/               # C# PolyMod plugin (net6.0)
│   ├── ClaudeBridge.csproj         # adapted from Polyfish's PolyfishAI.csproj
│   ├── manifest.json               # PolyMod manifest (id, name, version)
│   └── src/
│       ├── Plugin.cs               # PolyScript entry, TCP server, main-thread queue
│       ├── Hooks.cs                # Harmony patches: turn start, game over, safety guard
│       ├── StateSerializer.cs      # GameState -> JSON (from PolyfishSerializer.cs)
│       ├── LegalActions.cs         # enumerate legal commands (from PolyterraEnvBridge.GetValidActions)
│       └── ActionExecutor.cs       # JSON -> CommandBase -> IsValid -> ExecuteCommand
├── harness/                        # Python 3.11+
│   ├── pyproject.toml
│   ├── polytopia_bridge/client.py  # socket client, message framing
│   ├── polytopia_bridge/observe.py # JSON state -> compact text/ASCII map for the model
│   ├── polytopia_bridge/agent.py   # Claude tool-use loop (one tool: do_action; plus think/notes)
│   ├── polytopia_bridge/rules.md   # cached system-prompt rules reference (tech tree, units, costs)
│   ├── polytopia_bridge/logger.py  # per-game JSONL: state, prompt, reasoning, action, result
│   ├── scripts/play_game.py        # run one game end-to-end
│   ├── scripts/run_eval.py         # N games × difficulty × mode, writes results CSV
│   └── tests/                      # replay-based unit tests using recorded state JSON
└── docs/
    ├── SETUP_WINDOWS.md            # Steam, BepInEx, PolyMod, build, run
    └── PROTOCOL.md                 # message schema
```

## Phases

### Phase 0. Windows setup (half a day)

1. Install Polytopia from Steam on the Windows PC (base game, $14.99; no DLC needed). Play one game manually to confirm it runs, and to record the current game version from the settings screen.
2. Install .NET 6 SDK (PolyMod plugins target net6.0) and Git. Claude Code on Windows for the C# work.
3. Install PolyMod with its installer (`installer/main.py` in the PolyMod repo, or the release exe). It downloads `BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.785` and drops `PolyMod.dll` into `BepInEx/plugins`. Launch the game once; first launch generates `BepInEx/interop/*.dll` (this is what our `.csproj` references).
4. Install one catalogue mod to confirm the loader works, then remove it.
5. Copy `BepInEx/interop/` and `BepInEx/core/` DLL lists into `docs/SETUP_WINDOWS.md` so the build is reproducible.

### Phase 1. Bridge mod (2-4 days)

1. Scaffold `mod/ClaudeBridge` from Polyfish's csproj (fix `GamePath` for Windows, keep the post-build copy into `<game>/Mods/ClaudeBridge/`). Entry class extends `PolyMod.Api.PolyScript` with `Load()` / `Unload()`.
2. **Hooks.cs.** Detect "it is our turn and the game is idle": patch `GameManager.Update` postfix (Polyfish pattern) and check `GameManager.GameState.CurrentPlayer == localPlayerId && CurrentState == Started`; debounce until the client's action queue is empty. Patch game-over. Safety guard: bridge stays inert unless `Settings.GameType` is single-player.
3. **StateSerializer.cs.** Port `PolyfishSerializer.ExtractGameState`: settings, tiles (terrain, climate, owner, explored-by-us flag, resource, improvement, road), cities (level, population, progress, rewards, capital), units (id, type, hp, moved/attacked, effects, xp), player states (stars, income, techs, score). Export only tiles our player has explored (fog) so Claude does not cheat.
4. **LegalActions.cs.** Port `PolyterraEnvBridge.GetValidActions`: end_turn, research (with cost), moves, attacks (with `BattleHelpers` damage preview), unit actions from `CommandUtils.GetUnitActions` (capture, recover, promote, disband, abilities), builds/harvests via `GetUnlockedImprovements` + `MeetsRequirement` + `IsValid` (PolyMode's `ForceGetBuildableImprovements` is the exact loop), trains per city, pending city-reward choices (must be resolved before anything else).
5. **ActionExecutor.cs.** JSON -> command constructor table (PolyZero's `Execute*` methods cover every kind). Execute through the live client so the UI, animations, and bot turns stay consistent: prefer `GameManager.Client`'s action manager over bare `command.Execute(state)` (PolyZero's shortcut, which bypasses the client). Verify by watching the UI update in-game.
6. **Plugin.cs.** TCP server on a background thread, all game calls marshalled onto the Unity main thread via a queue drained in the `GameManager.Update` postfix (Polyfish `RunOnMainThread`). Config: port, bind address, our player id.
7. Manual smoke test with a `netcat`-style Python script: connect, receive state, send `end_turn` repeatedly, watch the bots play a whole game.

### Phase 2. Claude harness (2-3 days)

1. `client.py`: framing, reconnect, typed message dataclasses.
2. `observe.py`: turn JSON into a compact observation. ASCII map with fog, per-city lines, per-unit lines with move/attack availability, economy line (stars, income, techs), numbered legal-action list. Keep it under ~4k tokens on Tiny/Small maps.
3. `agent.py`: Claude API tool-use loop (load the `claude-api` skill before writing this; use `claude-fable-5-1` by default with model as a flag). One tool `do_action(index or structured action)` plus `end_turn`. System prompt = short rules reference in `rules.md` marked for prompt caching. Per action: send observation, get one tool call, execute, feed back result and new observation. Keep a rolling "strategy notes" scratchpad the model writes each turn so it has memory across turns without the whole transcript.
4. `logger.py`: JSONL per game (turn, observation, model reasoning, action, result, score) for post-hoc analysis and replays.
5. `play_game.py`: one game end to end, prints per-turn score and final result.

### Phase 3. Evaluation (1-2 days, then ongoing)

Game setup is done by hand in the Polytopia UI for now (new game -> tribe, map size, opponents, difficulty, mode); the harness waits for the bridge to report turn 1. Automating setup via the setup-screen classes (`GameSetupScreenView`, patched by `pyaiveoleg/polymod-logic-version-change`) is a follow-up.

Benchmarks:

| Mode | Metric | Setting |
|---|---|---|
| Perfection | score at turn 30 | Tiny/Small map, Imperius, 3 bots |
| Domination | win/loss and turn of win | Tiny/Small map, Imperius, 3 bots |

Ladder: Easy -> Normal -> Hard -> Crazy. Fixed tribe (Imperius) to remove tribe variance, as Polyfish's ladder does. Same map seed where the UI allows. Comparison points: Claude models against each other (Fable 5.1, Opus 5, Sonnet 5, Haiku 4.5), and a "random legal action" baseline, and a scripted greedy baseline if cheap. `run_eval.py` writes a CSV; a short results page comes at the end.

### Optional parallel track (Mac, no game install): simulator for fast iteration

GAIGResearch/Tribes (Java, already installed here) or tribes-rl expose the same shape of observation and legal actions. Building the observation and agent loop against a simulator first lets prompt work start before the Windows mod is done, and the `observe.py` / `agent.py` interfaces are designed to be engine-agnostic. Skip if the Windows box is available immediately.

## Key references to reuse (copy patterns, respect licenses)

- `HenBOMB/Polyfish` `polyfish-mod/PolyfishAI.csproj`, `src/PolyfishSerializer.cs`, `src/PolyfishAI.cs` (main-thread queue, Harmony `GameManager.Update` hook, `ClickButton`)
- `NovaVanity/PolyZero` `bridge/PolyZeroBridge/PolyZeroBridgePlugin.cs` (TCP protocol, command constructors)
- `Willibombb/PolytopiaProject` `csharp-backend/PolyterraEnvBridge.cs` lines ~977-1200 (`GetValidActions`), ~140-300 (`ActionManager.ExecuteCommand`)
- `LunaticDes28/PolyMode` `src/Conquest/AI_2.cs` (`ForceGetBuildableImprovements`, in-game AI written against the same API)
- `CAs-mods/polytopia-cheatmod` `CheatMod.cs` (single-player guard, minimal BepInEx plugin)
- `PolyModdingTeam/PolyMod` `src/Api/PolyScript.cs`, `installer/main.py`

## Risks

- **Game updates break the mod.** Steam auto-updates; PolyMod pins to game versions. Mitigation: set the Steam game to "only update when I launch it" and keep the BepInEx `interop/` DLLs with the repo docs so a rebuild is one command.
- **Executing commands outside the client's normal path desyncs the UI.** Mitigation: route through the client's action manager and verify visually; fall back to simulating button clicks (Polyfish `ClickButton`) only for setup screens.
- **Turn-boundary detection is flaky** (animations, bot turns, popups). Mitigation: debounce on idle frames and handle popups the way Polyfish's `HandleFailedPopup` does.
- **Cost per game.** ~10 actions/turn × 30 turns × observation size. Measure real token counts in Phase 2 before running the ladder; prompt caching on the rules block and a compact observation are the levers.
- **ToS** as above; user's call.

## Verification

1. Phase 0: game launches through BepInEx with `BepInEx/LogOutput.txt` showing PolyMod loaded.
2. Phase 1: plugin log shows "listening"; the smoke script receives a state on turn 1, `end_turn` advances the game, a `move` action visibly moves a unit in the UI, an invalid action returns `ok:false` with the game's own error string, and a multiplayer game leaves the bridge inert.
3. Phase 2: `play_game.py` completes a full 30-turn Perfection game against Easy bots unattended and writes a JSONL log; unit tests in `harness/tests` run `observe.py` and the action parser against recorded state JSON.
4. Phase 3: `run_eval.py` produces a CSV with at least 5 games per difficulty and the random baseline; results summarized in `docs/RESULTS.md`.
