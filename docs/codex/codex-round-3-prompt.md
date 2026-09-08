Round 3 of a read-only review (do not modify files) in the polytopia-claude repository. Rounds 1-2 covered design and loop correctness (see docs/CODEX_REVIEWS.md). This round is about PLAY QUALITY and the spectator experience.

Read:
1. harness/polytopia_bridge/strategy_domination.md and rules.md (the system prompt for the planner, plus the legend from observe.py)
2. harness/polytopia_bridge/planner.py (PLAN_SCHEMA, INSTRUCTIONS, build_prompt) and observe.py (what the model sees each turn)
3. docs/sample_turn_output.txt — a real captured terminal sample from one planning call by Opus 5 on the recorded midgame state (harness/tests/fixtures/state_midgame.json), including the streamed commentary and the parsed plan
4. harness/polytopia_bridge/console.py (terminal renderer) and harness/scripts/play_domination.py

Setting: Domination, Tiny 11x11 Dryland map, Imperius vs one Normal bot, one planning call per turn (~14 s, cached system prompt), at most 3 calls per turn.

Give a numbered list (max 12) of specific improvements, each with the exact text or code change:
(a) Strategy text: what a strong Polytopia player would change for a fast, reliable Domination win vs a Normal bot on a tiny map (opening, tech order for Imperius, unit mix, siege technique, when to stop expanding). Point out any advice in the file that is wrong for Polytopia 2.17.2 rules.
(b) Prompt/observation: token waste, missing information the planner needs (e.g. distances, terrain along the path, unit support cap usage, star math for this turn), ambiguities in the instructions that would cause bad plans or wasted re-plans.
(c) Sample plan critique: in docs/sample_turn_output.txt, was the model's plan good? What would you have done, and what in the prompt caused any weakness?
(d) Terminal output: readability for someone watching live; what is missing (e.g. a per-turn summary of enemy strength, or the result of each attack), what is noise.
Be concrete; quote replacement sentences for the strategy file where you propose changes.
