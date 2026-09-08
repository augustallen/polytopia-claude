# Bridge protocol

Newline-delimited JSON over TCP. The mod listens on `127.0.0.1:9876` by default
(`<game>/BepInEx/config/ClaudeBridge.json`: `{"port": 9876, "bind": "127.0.0.1"}`; set `bind` to
`0.0.0.0` to accept LAN connections). One client at a time; a new connection replaces the old one.

The bridge only ever acts in **offline** games: `GameSettings.GameType == SinglePlayer`, or `PassAndPlay` (the
game's hotseat mode, several human seats on this device; used to let two agents play each other). In any other
game type (Multiplayer, Matchmaking, Competitive, WeeklyChallenge) it answers with an error and stays inert.

## Messages from the harness

| Message | Meaning |
|---|---|
| `{"type": "ping"}` | Liveness check, answered with `{"type": "pong"}`. |
| `{"type": "get_state"}` | Ask for a fresh `state`. It is sent once the client is idle and it is our turn; outside a game the reply is an `error`. |
| `{"type": "status"}` | Debug: every gate the turn watcher looks at (`in_game`, `current_state`, `is_local_turn`, `is_waiting_for_command`, `popup`, …). Answered immediately, in or out of a game. |
| `{"type": "resume"}` | Press the menu's Resume for the saved single-player game (`GameManager.ResumeSingleplayerGame`). Replies `{"type": "ok"}` or an `error` (already in a game). No clicking needed after a game restart. |
| `{"type": "new_game", "mode": "Perfection", "difficulty": "Easy", "opponents": 3, "map_size": 16, "map_preset": "Continents", "tribe": "Imperius", "name": "..."}` | Start a new single-player game from the start screen, exactly like the setup screen's Continue button. All fields optional (defaults shown except `map_size`, which follows the opponent count). `mode`: Perfection/Domination/Glory/Might; `difficulty`: Easy/Normal/Hard/Crazy; `map_preset`: Dryland/Lakes/Continents/Archipelago/WaterWorld/Pangea; `map_size`: 11 (tiny) 14 16 18 20 30. Replies `ok` with the settings used; the first `state` follows once the level is loaded. |
| `{"type": "new_game", "game_type": "PassAndPlay", "players": 2, "bots": 0, "tribes": ["Imperius", "Imperius"], "mode": "Domination", "map_size": 11, ...}` | Start an offline **Pass & Play** (hotseat) game with `players` human seats (default 2) and `bots` built-in bots (default 0; `opponents` is an alias), one tribe per seat (defaults to `tribe`). Mirrors the player picker + tribe picker + setup screen (`GameManager.CreateHotseatGame`). The `ok` reply echoes the request; the first `state` (for the opening seat) carries the actual `roster`, which the harness validates. |
| `{"type": "return_to_menu"}` | Leave the current game (`GameManager.ReturnToMenu`), e.g. after `game_over`, so `new_game` can be sent. |
| `{"type": "kick", "method": "start_processing"}` | Diagnostics only: poke the client (`start_processing`, `stop_processing`, `skip_recap`, `force_update`, …). |
| `{"type": "action", "action": {...}, "player": 2}` | Execute one command. Always answered with a `result`, followed by a fresh `state` once the game has finished processing (or by `game_over`). `player` is optional: the seat the sender is acting for; in a hotseat game the bridge answers `wrong seat: local player is N, not M` when another seat is at the keyboard (the harness treats that as a desync and stops). |

## Messages from the bridge

### `hello`
Sent on connect: `{"type": "hello", "bridge_version": "0.1.0", "game_version": "2.17.2.16299", "in_game": false}`.

### `state`
Sent whenever it is the local player's turn, the client has finished animating, and something
changed since the last `state` (turn, command count or pending trigger), or after every `action`.

```json
{
  "type": "state", "turn": 3, "player": 1,
  "roster": [{"id": 1, "tribe": "Imperius", "name": "Player 1", "is_bot": false, "alive": true}, ...],
  "state": {
    "turn": 3,
    "settings": {"map_width": 11, "map_height": 11, "map_size": 11, "game_mode": "Perfection",
                 "game_type": "SinglePlayer", "difficulty": "Easy", "opponents": 3,
                 "turn_limit": 30, "score_limit": 0},
    "me": {"id": 1, "tribe": "Imperius", "stars": 7, "income": 4, "score": 950, "techs": ["Organization", "Basic"]},
    "players": [{"id": 1, "tribe": "Imperius", "name": "...", "is_bot": false, "score": 950, "cities": 1,
                 "kills": 0, "killed_turn": 0, "alive": true, "known": true, "is_me": true, "stars": 7},
                {"id": 2, "tribe": "Bardur", "is_bot": true, "score": 900, "known": false, "relation": "Neutral", ...}],
    "tiles":  [{"x": 4, "y": 5, "terrain": "Forest", "owner": 1, "resource": "Game", "improvement": "LumberHut",
                "road": true, "city": [4, 4], "effects": ["Flooded"], "village": true}, ...],
    "cities": [{"x": 4, "y": 4, "name": "Lux", "owner": 1, "level": 2, "population": 1, "population_total": 3,
                "population_to_level": 3, "production": 3, "border_size": 1, "is_capital": true,
                "connected_to_capital": true, "walls": false, "rewards": ["Workshop"]}, ...],
    "units":  [{"id": 12, "type": "Warrior", "owner": 1, "x": 4, "y": 5, "hp": 10, "max_hp": 10, "attack": 2,
                "defence": 2, "movement": 1, "range": 1, "veteran": false, "kills": 0,
                "moved": false, "attacked": false, "can_move": true, "can_attack": true, "home": [4, 4],
                "effects": ["Poisoned"], "abilities": ["Dash", "Fortify"], "passenger": "Warrior"}, ...],
    "pending_trigger": null
  },
  "legal_actions": [ ...see below... ]
}
```

Only tiles the local player has explored are included (Polytopia has no re-fogging: explored tiles show
their live contents). Enemy units that are invisible to us (cloaks) are omitted. `moved`/`attacked`/
`can_move`/`can_attack`/`home` are only present on our own units. `stars` is only reported for ourselves.
`pending_trigger` is `{"type": "CityLevelUp", "at": [x, y], "opponent": 0}` when a city reward (or peace
request) must be answered before anything else; `legal_actions` then contains only those choices.

Unit `hp`/`max_hp`/`attack`/`defence` are the in-game numbers (a fresh Warrior is 10/10/2/2; the engine
stores health in tenths and attack/defence in hundredths, the bridge divides them back). `defence` includes
terrain/city bonuses. Player ids are 1-based; owner `0` means unowned.

A `state` is sent when it is our turn and the client has been idle for 5 frames — idle meaning
`ClientBase.IsWaitingForCommand`, or the action loop stopped altogether (that is the state after a
mid-game resume, until the first command restarts it). Before that, the bridge closes any popup the way a
tap would ("You got a new technology!", "Xi level up!", "You meet Oumaji", task popups): skippable ones via
`PopupManager.HideCurrentPopup`, unskippable ones by pressing their primary button, after letting the popup
settle for 1 s (closing "You meet <tribe>" early crashes the game). Popups are left alone while a city
reward / peace request is pending — that choice is the agent's, answered with a command.
After an accepted `action` the bridge waits until the engine has consumed the command (turn/command counters
move) before sending the next `state`, so the harness always sees the post-action state; if nothing changes
within 5 s it logs a warning and sends the state anyway.

`roster` (on `state`, `game_over` and `status`) is the seat-neutral list of players: the same list whichever
seat is local, with `is_bot` false for human seats.

### Hotseat handoff (Pass & Play)

In a `PassAndPlay` game `player` changes from state to state: each `state` is serialized for the seat whose
turn it is (its own fog, stars, techs and legal actions), and only when the client agrees that seat is local.
The bridge handles the seat switch itself, in this order every frame: game ended -> `game_over`; the
"pass the device to player N" overlay (`HotSeatOverlay`) showing -> press its Continue after a 1 s settle
(the very first overlay is what starts the game); game not running yet -> wait; informational popups ->
dismissed as in single-player; the client replaying (after the overlay's Continue the client rewinds to
the start of the turn and replays the other seat's commands as a recap; `ClientBase.HasTargetState()` is
true until the replay has caught up, and GameState is a rewound snapshot meanwhile) -> wait;
`GameManager.LocalPlayer` not yet the current player -> wait. Commands sent through the bridge bypass the
HUD path that normally shows the overlay between turns, so when the engine has moved on to the next player
and is idle for 1.5 s with no overlay and no replay, the bridge calls the client's own
`SetNewLocalPlayerTurnForPassAndPlay(current player)`, which is what the overlay's Continue does. After
that switch the client's action loop is stopped, so commands are applied synchronously (the bridge notices
the command counter has already moved and does not wait for it). The `StateKey` de-duplication includes
the player, so the first state of each seat is always sent. `IsRecap`/`isRecapping` are not usable as
"replay in progress" signals: they stay true for a whole human turn in a hotseat game.

If a handoff stalls for more than 10 s the bridge sends `{"type": "warning", "reason": "handoff stalled",
"where": "...", "stalled_seconds": N, ...status fields}` at most every 10 s. Warnings are informational; the
harness prints them and its state deadline keeps running (the client's `expect()` uses an absolute deadline).
`status` additionally reports `is_hotseat`, `client_local_player`, `current_local_player_index`, `ui_screen`,
`hotseat_overlay_showing`, `handoff_stalled_seconds` and `roster`.

Hotseat `resume` is not implemented: a deathmatch always starts with `new_game`.

### `legal_actions`
Every command the engine will currently accept, produced from the game's own option generators plus
each command's `IsValid`. Each entry is a ready-to-send `action` object with extra read-only annotations.

| `kind` | Fields | Annotations |
|---|---|---|
| `end_turn` | – | – |
| `research` | `tech` | `cost`, `unlocks_units`, `unlocks_improvements`, `unlocks_techs` |
| `move` | `unit_id`, `to` (`from` informational) | – |
| `attack` | `unit_id`, `target` (`from` informational) | `target_unit_id`, `target_type`, `target_hp`, `damage`, `retaliation`, `kills` |
| `capture` | `unit_id`, `at` | – |
| `train` | `unit_type`, `at` (city tile) | `cost`, `hp`, `attack`, `defence`, `movement`, `range`, `abilities` |
| `upgrade` | `unit_type` (target type), `at` | – |
| `build` | `improvement`, `at` — also harvests (`HarvestFruit`, `Hunting`, `Fishing`, …) and terrain actions (`ClearForest`, `BurnForest`, …) | `cost`, `population`, `stars` |
| `city_reward` | `reward`, `at` | – |
| `recover`, `promote`, `disband`, `examine_ruins`, `heal_others`, `explode`, `swarm`, `freeze_area`, `break_ice`, `boost`, `decompose`, `destroy`, `hide`, `disembark`, `flood`, `stay` | `at` (or `unit_id`) | – |
| `peace_request_response` | `opponent`, `accept` | – |
| `peace_treaty`, `establish_embassy`, `destroy_embassy`, `break_peace` | `opponent`, `at` | – |
| `clear_tile_effect` | `at`, `effect` | – |

Coordinates are `[x, y]` (`{"x":..,"y":..}` is also accepted on input). Enum names are the engine's
(`UnitData.Type`, `ImprovementData.Type`, `TechData.Type`, `CityReward`, …), case-insensitive on input.
`kind` is the engine's `CommandType` in snake_case, so new command types need no bridge changes to be
*encoded*; decoding needs a constructor mapping in `CommandCodec.Decode`.

### `result`
`{"type": "result", "ok": true, "error": null, "kind": "move"}` or
`{"type": "result", "ok": false, "error": "<engine validation string or bridge message>", "kind": "move"}`.
The bridge validates with `CommandBase.IsValid(state, out error)` and only then hands the command to the
client (`ClientBase.SendCommand`), the same path the UI uses. Bridge-side rejections include
`not your turn`, `wrong seat: local player is N, not M`, `game is still processing the previous action`,
`unit N is not yours`, `unknown kind`.

### `game_over`
`{"type": "game_over", "turn": 30, "player": 1, "winner": 1, "won": true, "score": 12345, "roster": [...], "players": [...]}`
when `GameState.CurrentState` becomes `Ended`. `won` and `score` are for the seat that is local at that moment;
in a hotseat game the harness derives each seat's result from `winner` instead.

### `left_game`, `error`
`left_game` when the level unloads (back to menu). `error` for malformed messages or non-single-player games.

## Turn loop (harness side)

```
connect → hello
loop:
  wait for state (or game_over)
  pick an action from legal_actions
  send action → result
  (a new state follows automatically; after end_turn it arrives when the bots are done)
```
