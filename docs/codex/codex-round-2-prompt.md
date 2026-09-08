Round 2 of a code review (read-only; do not modify files). This is the polytopia-claude repository. Your round-1 design feedback was applied; the implementation now exists. Review it for correctness bugs, dead or unreachable states, and Windows pitfalls.

Read, in this order (all under harness/):
1. polytopia_bridge/planner.py (new), polytopia_bridge/claude_stream.py (new), polytopia_bridge/console.py (new)
2. polytopia_bridge/runner.py — the new `play_turns()`, `choose_reward`, `answer_trigger`, and the changed `to_menu_and_new_game`
3. polytopia_bridge/observe.py (rewritten: objective line, enemy capital, unit status), polytopia_bridge/client.py (`act` timeout)
4. scripts/play_domination.py (new launcher)
5. tests/test_planner.py, tests/test_claude_stream.py, tests/test_turn_runner.py (all passing)
6. For protocol facts: docs/PROTOCOL.md, mod/ClaudeBridge/src/Plugin.cs lines 440-620 (state push / idle rules), mod/ClaudeBridge/src/LegalActions.cs.

Context: `play_turns` keys everything off one current `state` message; a planned step is re-located in the fresh legal list by `action_key`; a skip reads no new state (`reuse`); every sent action expects a `result` then a new `state` (the bridge pushes one after every action, also after rejections); `game_over` arrives as an exception from `wait_for_state`. Claude Code CLI facts (verified today): stream-json emits `content_block_start` for a `tool_use` block named `StructuredOutput`, then `input_json_delta` chunks; thinking deltas carry empty text and only `estimated_tokens`; the final `result` event has `structured_output`, `usage`, `total_cost_usd`, `is_error`.

Give a numbered list (max 12) of concrete defects or risks, each with file:line and a specific fix. Priorities: (a) anything that can stall the loop forever or desync it from the bridge (e.g. a path where no action is sent and no state is awaited, or one that waits for a state that will never come); (b) mistakes in the step-matching/dependency logic; (c) subprocess/stream handling on Windows (pipes, encoding, kill on timeout, prompt via stdin); (d) the reward/trigger policy; (e) anything the tests do not cover that should be. Say explicitly if you find nothing serious in an area.
