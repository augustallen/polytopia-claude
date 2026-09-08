# Plan: Grok vs Astra deathmatch (Grok Build CLI on the SuperGrok subscription)

> Status 2026-09-08: executed. `grok_stream.py`, `GrokPlanner`, the `grok:` spec, tests and the card colour are in;
> the first Grok 4.6 vs gpt-6-astra match is recorded in `docs/RESULTS.md` (game 6). Verified CLI facts: grok 1.0.13,
> flags `--prompt-file`, `--json-schema` (schema-enforced output), `--system-prompt-override`, `--reasoning-effort`
> (grok-4.6 accepts low/medium/high/xhigh, default high), `--disallowed-tools`, `--max-turns 1`; json output carries
> Anthropic-style usage plus `total_cost_usd` and a `thought` summary. Medium effort took ~95 s per planning call.

A runbook for a fresh Claude Code session on this Windows box. Goal: add an xAI Grok seat to the existing
Claude-vs-Codex deathmatch harness using xAI's official terminal agent **Grok Build** (the `grok` CLI) on
the user's Grok subscription, no API billing; then play one recorded Pass & Play Domination game, Grok vs
Codex `gpt-6-astra` ("Astra"), both at medium reasoning where the model allows it, and produce the stats card.

Read first: `README.md` (Claude vs Codex deathmatch section), `docs/PROTOCOL.md` (hotseat handoff),
`docs/RESULTS.md` (games 3-5), and the auto-memory notes (`windows-box-tooling`, `bridge-quirks`,
`project-status`) that load with the session. Nothing in the mod or the turn loop needs to change: the
bridge already serves two human seats and `play_deathmatch.py` accepts any planner spec that
`planner.make_planner()` understands. The job is a third planner backend plus bookkeeping.

## Facts about Grok Build (verified 2026-09-07 from xai-org/grok-build docs and docs.x.ai/build)

- Official, open source (Apache 2.0), repo `github.com/xai-org/grok-build`; docs at `docs.x.ai/build/overview`
  and in the repo under `crates/codegen/xai-grok-pager/docs/user-guide/` (14-headless-mode.md,
  22-permissions-and-safety.md, 26-config-reference.md, 12-project-rules.md, 02-authentication.md).
- Install on Windows: `irm https://x.ai/cli/install.ps1 | iex`, then `grok --version`.
- Auth: `grok login` opens the browser (SpaceXAI OAuth at grok.com); `grok login --device-auth` prints a URL
  and code instead. Tokens live in `%USERPROFILE%\.grok\auth.json` and refresh automatically. The CLI
  requires an active SuperGrok or X Premium+ subscription (all tiers of SuperGrok since May 2026); an
  `XAI_API_KEY` is only a fallback and is not wanted here. Note: third-party OAuth clients have reported 403s
  for some tiers, so the first login test below is the gate.
- Headless: `grok -p "<prompt>" -m grok-4.6 --output-format json` runs one prompt with a fresh session and
  exits 0/1. `json` gives one object: `text`, `stopReason`, `usage` (uncached, cache hits, outputs),
  `modelUsage` (per-model, with `costUSD`), `total_cost_usd`, `sessionId`. `streaming-json` gives
  newline-delimited events `text`, `tool_call`, `usage`, `end`. Default model is `grok-4.6`.
- Tools: `--tools "<allowlist>"`, `--disallowed-tools "<list>"`, `--allow`/`--deny` permission rules (deny
  always wins), permission modes (`--permission-mode`, `--always-approve` / `--yolo`). Config keys:
  `disable_web_search = true`, `features.web_fetch = false`, `disabled_mcp_servers`.
- Instructions: `--system-prompt-override <text>` (alias `--system-prompt`) replaces the whole system prompt;
  `--rules` (alias `--append-system-prompt`) appends. It also auto-loads `AGENTS.md`, `CLAUDE.md`, `.grok/rules/*.md`
  from the working directory and home (`~/.claude/rules/` too), so run it from an empty directory.
- Reasoning effort: config keys `models.default_reasoning_effort` and `model.<id>.reasoning_efforts`
  (allowed values per model). No JSON-schema output flag is documented; structured output must be asked for
  in the prompt and parsed from `text`.
- "Grok Bot" is a different product (a cloud "AI teammate" driven from the apps), not a CLI; ignore it.

## What exists (do not rebuild)

| Piece | Where | Notes |
|---|---|---|
| Two-seat turn loop | `harness/polytopia_bridge/runner.py` `play_turns(bridge, {pid: planner}, ...)` | per-seat budgets, void on tool use, stale-state guards |
| Planner contract | `harness/polytopia_bridge/planner.py` `TurnPlanner`, `CodexPlanner`, `make_planner(spec)` | a backend is `_run_cli(prompt, on_thinking, on_text) -> dict` with `structured_output` (or a JSON `result` string), `usage` (Anthropic key names), `total_cost_usd` (float or None), `meta` {streamed, violations, backend}; failures raise `PlannerError(msg, meta)` |
| Codex backend (reference) | `harness/polytopia_bridge/codex_stream.py` + `subprocess_util.run_streaming_cli` | the closest analogue: a subscription CLI, prompt on stdin, JSONL events, tool-use violation counting |
| Match script | `harness/scripts/play_deathmatch.py --p1 <spec> --p2 <spec> [--first p2]` | binds `--first` to the engine's opening seat; exit codes 0/1/2/3 |
| Recorder | `harness/scripts/record_match.py -- <script> ...` | ffmpeg screen-region capture of the game window |
| Stats card | `harness/scripts/match_card.py <log> --out <png>` | `display_name()` and `SERIES` need a Grok entry |
| Tests | `harness/tests/` (90 passing); `test_codex_stream.py` uses a fake `.cmd` executable | template for the Grok test |
| Tooling | portable Python `%USERPROFILE%\tools\python312\tools\python.exe` (matplotlib installed), ffmpeg under `%USERPROFILE%\tools\ffmpeg`, Josefin Sans in `%USERPROFILE%\tools\fonts` | `python` is not on the PowerShell tool's PATH; use the full path |

## Step 0: install, log in, probe (needs the user once)

1. `irm https://x.ai/cli/install.ps1 | iex` in the PowerShell tool (network: run with the sandbox off), then
   `grok --version`. Find the installed binary path (`Get-Command grok`) and record it; the harness should
   call the executable directly (a `.cmd`/`.ps1` shim would mangle quoting the way `codex.cmd` did).
2. Ask the user to run `grok login` themselves (browser sign-in with the account that holds the Grok
   subscription; `grok login --device-auth` if the browser flow fails). Confirm `%USERPROFILE%\.grok\auth.json`
   exists afterwards. Do not set `XAI_API_KEY`.
3. Read `grok --help` and `grok -p --help` (or the equivalent) and record the exact spelling of: the prompt
   flag, `--output-format`, `-m`, `--tools`, `--disallowed-tools`, `--deny`, `--system-prompt-override`,
   any `--reasoning-effort` / effort flag, any no-session or ephemeral flag, and the built-in tool names
   (needed for the blocklist). Docs and flags may have moved since this runbook was written; the help
   output wins.
4. First real call from an empty scratch directory:
   `grok -p "Reply with the single word ok." -m grok-4.6 --output-format json`
   Expect exit 0 and a JSON object with `text`, `usage`, `total_cost_usd`. If it returns 401/403 or a
   subscription error, stop and report: the subscription tier does not cover the CLI, and the only
   alternative is API billing (previous version of this plan), which the user declined.
5. Effort probe: `grok inspect` / `--help` / the config reference for the effort setting on `grok-4.6`.
   If `models.default_reasoning_effort` (or a flag) accepts `medium`, use it; otherwise record that Grok
   ran at its default reasoning. Write the choice into RESULTS.md.
6. Tool-lockdown probe: run the same prompt with the planned lockdown flags (step 1 below) plus
   `--output-format streaming-json` and a prompt that asks the model to list the current directory. The
   stream must contain no `tool_call` event and the answer must not contain a listing. If `--tools ""` is
   rejected, use `--disallowed-tools` with every built-in tool name from the help output, plus `--deny`
   rules for `Bash(*)`, `Read(*)`, `Edit(*)`, `Write(*)`, `Grep(*)`, `WebFetch(*)`, `WebSearch(*)` (deny
   always wins, even over always-approve), and the config keys `disable_web_search = true`,
   `features.web_fetch = false` in a per-run `--config`/`.grok/config.toml` inside the scratch directory.

## Step 1: Grok backend (`harness/polytopia_bridge/grok_stream.py`, new, ~180 lines)

Model it on `codex_stream.py`; reuse `subprocess_util.run_streaming_cli` (prompt on stdin if the CLI reads
stdin when `-p -` or no prompt is given; otherwise pass the prompt as the `-p` argument, which is fine for
argv length since the prompt is ~6 KB).

`run_grok(prompt, *, instructions, schema, model, effort, grok_bin, work_dir, timeout, on_status) -> dict`:
- Working directory: an empty per-game directory under the scratchpad (nothing to auto-load). Also pass
  `--system-prompt-override <instructions>` so Grok gets the game instructions as its system prompt
  (system-message placement, like Claude). If the override flag is missing or capped, fall back to writing
  the instructions as `AGENTS.md` in that directory (project-rules placement, like Codex) and record which.
- Structured output: no schema flag, so append to the user prompt: "Reply with ONLY a JSON object, no
  prose, no code fence, with exactly these keys: commentary (string), actions (array of integers), notes
  (string)." Parse `text` from the `json` output: strip a ```json fence if present, `json.loads`, verify
  the three keys. Invalid -> `PlannerError` (the planner retries once with "YOUR PREVIOUS ANSWER WAS
  INVALID" and then falls back to end turn, same as the other seats).
- Command: `<grok.exe> -p <prompt> -m <model> --output-format streaming-json <lockdown flags> [<effort
  flag>]`. Use `streaming-json` so `tool_call` events can be counted as violations while the game plays;
  the final `usage`/`end` events carry totals. (If streaming proves flaky, switch to `json` and count
  violations from `stopReason`/`modelUsage` as available; note it in `meta["stream"]`.)
- Result contract: `structured_output` (parsed plan), `usage` mapped to Anthropic keys (`input_tokens` =
  uncached input, `cache_read_input_tokens` = cache hits, `output_tokens`, `cache_creation_input_tokens` =
  0), `total_cost_usd` = the CLI's `total_cost_usd` if present else `None` (the subscription pays either
  way; the footer shows "n/a (subscription)" for None), `result` = raw text, `meta` = {streamed False,
  violations = number of `tool_call` events, backend "grok", tool_calls = their names}.
- Errors: launch failure, non-zero exit, timeout, no `end`/`usage`, empty text -> `PlannerError(msg, meta)`.
- Sessions: each headless call is a fresh session by default; if a no-session flag exists, use it so
  `~/.grok/sessions` does not fill up with one file per planning call.

## Step 2: planner and script wiring

- `planner.py`: `class GrokPlanner(TurnPlanner)` mirroring `CodexPlanner` (name `grok-<model>`,
  `on_commentary=None`, `_run_cli` -> `run_grok`); `make_planner` gains the `grok:<model>[:<effort>]` spec
  (default model `grok-4.6`). Fresh instance per game.
- `match_card.py`: `display_name()` maps `grok-<model>` -> `("Grok <model>", "grok")`; `SERIES["grok"]`
  needs a validated colour next to Codex blue `#2a78d6` on the cream surface: try the dataviz skill's slot
  3 aqua `#1baf7a` with `node scripts/validate_palette.js "#2a78d6,#1baf7a" --mode light` (run from the
  skill's directory); if it fails, slot 7 violet `#4a3aa7`.
- `README.md` deathmatch section: add the `grok:` spec and the login requirement; `docs/RESULTS.md`: a row.

## Step 3: tests (`harness/tests/test_grok_stream.py`, plus two lines in `test_planner.py`)

- Record one real `grok -p ... --output-format streaming-json` run into `tests/fixtures/grok_stream_sample.jsonl`
  and one `--output-format json` answer into `tests/fixtures/grok_json_sample.json` (from the step 0 probes).
- A fake `grok.cmd` (pattern from `test_codex_stream.py`) that echoes the fixture: parse plan from `text`
  (with and without a code fence), usage mapping, `total_cost_usd` passthrough, `tool_call` events counted
  as violations, non-zero exit and empty text -> `PlannerError`, missing executable -> `PlannerError`.
- `build_command` flags: prompt, model, output format, lockdown flags present, no quotes in argv.
- `make_planner("grok:grok-4.6:medium")` -> `GrokPlanner`, name `grok-grok-4.6`, `on_commentary is None`.
- Full suite still passes: `python -m pytest -q` from `harness/`.

## Step 4: live checks, then the match

1. Game window open at the menu (`python scripts/bridgectl.py status` -> `has_game_state: false`; a finished
   game left open is fine, `to_menu_and_new_game` returns to the menu). If the game is not running:
   `Start-Process "steam://rungameid/874390"`, wait for `StartScreen.Init` and `listening on` in
   `<game>\BepInEx\LogOutput.log` (about 90 s).
2. One real planning call: build `GrokPlanner` and call `plan()` on `tests/fixtures/state_midgame.json` with
   `game_mode` set to `Domination`; check legal indices, usage, violations 0, and latency (Claude ~15 s,
   Codex ~22 s per call; set `--call-timeout` higher if Grok is slower).
3. Smoke game, two turns, recorded:
   `python scripts\record_match.py --out recordings\smoke-grok.mp4 -- scripts\play_deathmatch.py --p1 grok:grok-4.6:medium --p2 codex:gpt-6-astra:medium --max-turns 2 --no-color --no-thinking`
   Both seats must alternate in the console, `violations=0` in the per-seat summary, and the video must have
   changing frames (extract two frames with ffmpeg, compare hashes).
4. The match (Grok moves first, mirroring games 3-5):
   `python scripts\record_match.py --out recordings\game6-grok46-vs-gpt6astra.mp4 -- scripts\play_deathmatch.py --p1 grok:grok-4.6:medium --p2 codex:gpt-6-astra:medium --max-turns 60 --no-color --no-thinking`
   Launch detached with `Start-Process` (a tool call is capped at 10 minutes; a game takes 25-40),
   stdout to `logs\match6-console.txt`, and watch it with a Monitor grepping
   `^=== TURN|GAME OVER|WINNER|result:|stopping:|Traceback|VOID|recording stopped`. Subscription rate
   limits: Grok Build has weekly/hourly allowances per tier; if a call fails with a quota message, the
   planner's fallback ends that turn, so watch for repeated "plan error" lines and stop the run rather than
   let Grok forfeit turns.
5. Afterwards: copy the console output to `docs/samples/game6-deathmatch-grok46-vs-gpt6astra.txt`, render
   the card `python scripts\match_card.py logs\<game6>.jsonl --out ..\docs\samples\game6-card.png` and look
   at the PNG (Read tool), add the RESULTS.md row and notes, make the 4x cut
   (`ffmpeg -i in.mp4 -vf setpts=0.25*PTS -r 30 -c:v libx264 -crf 22 -pix_fmt yuv420p -movflags +faststart -an out.mp4`),
   and send the card and the cut to the user with SendUserFile.
6. Optionally a second game with `--first p2` (Codex moves first).

## Fairness notes to record with the result

- Same instructions text, observation, schema, budgets (3 calls and 60 actions per seat-turn), fixed
  reward/peace policy, same tribe, no tools for either seat.
- Placement: Grok gets the instructions via `--system-prompt-override` (system message, like Claude) or as
  `AGENTS.md` (like Codex); say which. Structured output is prompt-enforced for Grok, schema-enforced for the
  others; invalid answers cost a retry under the same 3-call budget.
- Effort: whether `medium` applied or the model's default reasoning was used.
- Cost: both seats on subscriptions; report tokens (and the CLI's cost estimate if it prints one).

## Pitfalls already solved (do not re-debug)

- Shims mangle quotes: call the real executable, keep prompts free of double quotes or pass on stdin.
- The bridge waits out the hotseat recap (`HasTargetState`), switches seats itself after 1.5 s idle, ignores
  states for a seat-turn already ended, and answers a reward that lands after end turn before re-sending it.
  All covered by tests; on a stall read `docs/CODEX_REVIEWS.md` "What the spikes found".
- Heredocs with quotes break in the Bash tool on this box: write Python helpers with the Write tool and run
  them, or use PowerShell.
- Keep the game window on screen and not minimized while recording; capture is the screen region under its
  client rectangle (window-title capture freezes on Unity's DirectX surface).
- Nothing is committed in this repo beyond the first three commits; ask the user before committing.
