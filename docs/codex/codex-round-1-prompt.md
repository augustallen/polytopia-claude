You are reviewing a design before it is implemented. Read-only; do not modify files.

Repository: this directory (polytopia-claude). Read, in this order:
1. The plan file at the path given below (the design under review).
2. harness/polytopia_bridge/runner.py, agent.py, observe.py, client.py, rules.md
3. harness/scripts/play_game.py, harness/tests/test_agent.py, harness/tests/fixtures/state_midgame.json (skim), harness/tests/fixtures/state_city_reward.json
4. docs/PROTOCOL.md, mod/ClaudeBridge/src/LegalActions.cs, mod/ClaudeBridge/src/Plugin.cs (lines 440-620)

Goal of the rebuild: the Python harness plays a new 1v1 Domination game (Tiny map, Normal bot) through the ClaudeBridge mod, driven by Opus 5 via the headless Claude Code CLI (`claude -p`), rushing the enemy capital, using FEW model calls per turn (one planning call returning an ordered list of legal-action indices, executed sequentially with re-matching against re-numbered legal lists), and streaming reasoning/actions live to the terminal.

Please give concrete, prioritised feedback as a numbered list (max 15 items), each with file:line references where relevant and a specific suggested change. Focus on:
- The action-key matching approach (kind, unit_id, to, target, at, unit_type, improvement, tech, reward) and cases where it silently does the wrong thing.
- The re-plan rules: omit end_turn = "ask again", cap of 3 calls/turn, discard plan after two consecutive skips, pending_trigger interrupting mid-plan, auto-capture before consulting the model, auto city-reward policy (Explorer if capital unknown else Workshop; Resources; Population Growth; Super Unit), decline peace.
- Game-rule assumptions that are wrong for Polytopia 2.17.2 (capture timing, dash, kill-and-advance, unit support caps, Domination win condition).
- Domination-rush strategy text: what a strong human would do differently on a Tiny map vs a Normal bot.
- Anything in the existing runner/client that the new play_turns() loop would break (stale states, GameOver handling, drain_stale_states, wait_until_in_game).
- Windows-specific pitfalls with subprocess + stream-json from `claude -p`.
Say explicitly which of the plan's ideas you would drop as unnecessary.
Plan file path: /c/Users/augus/AppData/Local/Temp/claude/C--Users-augus-polytopia-claude/605af408-cb34-4ae0-8c82-9c685876caa1/scratchpad/plan.md
