# Codex review rounds for the Domination rebuild

Each round runs `codex exec` read-only against the repo; every point is applied or declined with a reason.

## Round 1 (design review, 2026-09-05)

| # | Codex point | Disposition |
|---|---|---|
| 1 | Domination is won by eliminating opponents (all their cities), not by taking the capital | **Applied**: rules.md goal, strategy text, objective line (capital first, then remaining cities); the runner only stops on `game_over` |
| 2 | Action key must include `accept`, `opponent`, `effect` (peace accept/decline had identical keys) | **Applied**: `KEY_FIELDS` in planner.py |
| 3 | Tile-addressed unit actions (recover/promote/disband/upgrade) can hit the wrong unit; keep `target_unit_id` for attacks | **Applied**: `annotate()` records the plan-time occupant, `locate()` verifies it; `target_unit_id` is part of the key |
| 4 | "Two consecutive skips" is unsafe; invalidate dependents after the first failure | **Applied in a lighter form**: after a skip or rejection, later steps using the same unit are dropped; independent steps continue. Discarding the whole plan every time would burn the call budget on benign skips |
| 5 | Spell out the snapshot-index limits and expose remaining calls in the prompt | **Applied**: INSTRUCTIONS text and strategy "Planning" bullet; `calls_left` is in every prompt |
| 6 | One invocation budget per turn including retries and trigger calls; reject booleans | **Applied**: `TurnPlanner.plan(max_attempts=)` charges every CLI attempt; the runner passes the remaining budget; `type(i) is int` |
| 7 | Triggers: dispatch on legal-action kinds; deterministic fallback; count auto actions | **Applied**: `answer_trigger` looks at kinds; unknown trigger takes the first legal option and is logged; auto actions count toward the action cap. Plan is kept after a reward (steps are re-validated anyway) |
| 8 | State freshness: bound `act()`, use the newest state, detect unchanged states | **Applied**: `act()` has a timeout; the loop keys everything off one current state; skips read nothing. Unchanged-state detection is left to the bridge's own 5 s guard |
| 9 | Stale `state`/`game_over` from the old game can satisfy startup after `return_to_menu` | **Applied**: `to_menu_and_new_game` discards queued `state`/`game_over` at the menu boundary and checks the first new state's mode/opponents |
| 10 | Blanket auto-capture wrecks research-before-capture ordering | **Applied**: captures are the model's to order; the runner only sweeps captures the model left unplanned right before ending the turn |
| 11 | Mechanics errors in rules.md (capture timing, dash, attack ends the turn, support cap); render abilities/can_move/can_attack | **Applied**: rules.md rewritten; unit lines show abilities and can-move/can-attack state |
| 12 | Resources gives +5 stars; Explorer only when useful | **Applied**: rules text fixed; Explorer only if the capital is unknown and it is turn <= 6 |
| 13 | No rigid tech path or HP thresholds; separate Domination prompt from shared rules.md | **Applied**: `strategy_domination.md` (planner) and `strategy_perfection.md` (old agent) on top of a mechanics-only rules.md |
| 14 | Subprocess: kill the process tree on timeout; resolved exe; sanitize log filename (colon) | **Applied**: `taskkill /T /F` on Windows, `shutil.which`, log name uses `claude-code-<model>` |
| 15 | Scope streaming to the StructuredOutput block; don't rely on property order | **Applied**: `consume_events` tracks the tool block index. Property order is still used as a hint (verified to work with the current CLI); the plan is only executed from the final `structured_output` |
| drop | Sandbox doc note, mod-speed stretch work | **Dropped** as suggested |

## Round 2 (code review of planner/stream/runner, 2026-09-05)

| # | Codex point | Disposition |
|---|---|---|
| 1 | Turning an action-result timeout into a synthetic rejection continues on a broken buffered socket | **Applied**: the run stops with outcome `timeout` and closes the connection |
| 2 | Auto actions (captures, trigger answers) can retry forever after rejections | **Applied**: rejected captures are not retried in the same turn; a mandatory action rejected twice stops the run with outcome `stuck` |
| 3 | An empty legal list waits for a state that may never come | **Applied**: the runner asks for a fresh state (up to 3 times) then stops with `stuck` |
| 4 | The action cap only applied when a plan was empty | **Applied**: checked before every planned step |
| 5 | `Popen` launch errors escape the planner fallback | **Applied**: translated to `PlannerError`; test with a missing executable |
| 6 | Timeout kill not guaranteed to unblock pipes | **Applied**: bounded `taskkill`, `proc.kill()` fallback, reap, close pipes |
| 7 | Writing stdin before draining stdout can deadlock | **Applied**: stdin is written from a worker thread |
| 8 | Empty plan vs "ask again" convention was ambiguous | **Applied**: prompt states an empty list means "end the turn" |
| 9 | `PopGrowth` would not match the `population` prefix | **Applied**: prefix is `pop`; tests cover both spellings and orders |
| 10 | After the capital is captured the objective says "not found yet" | **Applied**: with enemy cities visible but no capital, the objective lists the remaining cities |

## Round 3 (play quality and spectator output, 2026-09-05)

| # | Codex point | Disposition |
|---|---|---|
| 1 | Precise Imperius opening; stop auto-Explorer whenever the capital is unknown | **Applied** (opening text). **Partially declined** on Explorer: the first live game found the capital by turn 6 thanks to it, so Explorer stays for the first level-up only (turn <= 2), Workshop afterwards |
| 2 | Purchase conditions instead of "Riding first" and a turn-12 threshold; role-based unit mix | **Applied** in strategy_domination.md |
| 3 | Easiest useful conquest first; expansion stopping condition; capital tile kept empty | **Applied** |
| 4 | Siege text: plan kill and occupation together, ranged kills leave the tile empty, no fortify for besiegers, Escape rules | **Applied** |
| 5 | Monuments are free +3 pop; do not ban them | **Applied**: ban removed; monument placements are grouped on one line ("ONE placement") so the model does not queue six of them as it did in the live game |
| 6 | Mechanics: retaliation depends on defender range, forest ends movement, drop pre-rework naval text | **Applied** in rules.md |
| 7 | One authoritative planner instruction; calls-left miscount (2 shown when 3 remained) | **Applied**: new INSTRUCTIONS; plan(calls_left=) separated from the retry allowance |
| 8 | Support capacity, city-tile occupant, star math, enemy unit move/range; drop the misread production label | **Applied** in observe.py |
| 9 | Legend collision (enemy city vs crop both c); roads and enemy-territory lines; rename distance; shorter territory prose | **Applied**: enemy city is E; ROADS / ENEMY TERRITORY lines; "straight-line N to capital"; territory lists only resources and improvements |
| 10 | Sample plan critique; label the sample fixture | **Applied**: sample labelled; the prompt and strategy fixes above address the spending bias |
| 11 | Show actual outcomes (state diff) after each action and an enemy-turn summary | **Applied**: summarize_change(); the runner prints "=> ..." after each action and "ENEMY TURN: ..." on turn change; the same text feeds the planner turn log |
| 12 | Tighter commentary spec; compact plan line; TTY-gated ANSI; two-line header with reported vs located cities; --verbose | **Applied** (notes and per-action timing behind --verbose) |

## Round 4 (post-game review of game 1, 2026-09-05)

| # | Codex point | Disposition |
|---|---|---|
| 1 | Stars banked because nothing required converting surplus into siege power; support caps were not the cause | **Applied**: economy bullet now demands naming the purchase that most shortens the next capture before ending the turn, and saving only for a named purchase |
| 2 | Vague siege tech advice; give a conditional Catapult / Giant / Swordsman comparison | **Applied** in the Technology bullet |
| 3 | Complete affordable research chains and recruit within the remaining calls (turn 17 had 50 stars for Forestry+Mathematics+Catapult) | **Applied** in INSTRUCTIONS |
| 4 | Name and reserve the occupier before firing at a city (garrison died three turns before occupation) | **Applied** in the Siege bullet |
| 5 | Plan-conflict check (one recruit per city, one move per unit, one placement per monument); keep harmless overkill skips | **Applied** in INSTRUCTIONS |
| 6 | Re-queued end turn was discarded by the unconditional steps.clear() | **Applied**: cleared only when end turn succeeded; regression test added |
| 7 | Commentary claims archers never take retaliation; notes record planned outcomes as facts | **Applied**: schema descriptions for commentary and notes |
| 8 | Duplicate commentary paragraphs (plain text block forwarded too); header says "not located" after the capital fell | **Applied**: text deltas ignored; header shows "remaining targets: ..." |
| 9 | Delete redundant bullets (Early expansion, Notes, group of 3-5, never disband, no walls) | **Applied** (village-claiming sentence folded into the opening bullet) |

## Round 5 (post-mortem of game 2, a loss, 2026-09-05)

Raw prompts and replies for every round are archived in docs/codex/.

| # | Codex point | Disposition |
|---|---|---|
| 1 | A stalled siege must trigger a change of objective; staging beside a walled capital lost three Riders and the forward cities | **Applied**: new objective bullet and siege wording ("proximity alone is not progress") |
| 2 | Saving threatened cities outranks siege damage (turn 23: catapults had a kill sequence on the Defender inside our capital and shot elsewhere) | **Applied**: Defence bullet rewritten around inspecting every owned city before offensive moves |
| 3 | Capture-only spending sentence; "for replacements" reserves were aspirations | **Applied**: fund the immediate operation; a reserve must name purchase, cost, city and turn |
| 4 | Recovery became a holding pattern (34 recover actions); evaluate against the enemy reply | **Applied**: Fighting bullet rewritten; INSTRUCTIONS checks before recover/idle |
| 5 | Field battle needs Archers/Defenders independent of the siege; no Riders for a stationary siege | **Applied** in Army and Technology bullets |
| 6 | Do not mandate a blind turn-5 all-in; split scouting; check the assault before committing | **Applied** in the Opening bullet |
| 7 | Catapult protection must cover ranged reach and opened approaches, not just adjacent melee | **Applied** (replaces the post-game sentence) |
| 8 | "def 12" was real (walled Defender); clarify displayed defence is positional | **Applied**: rules.md damage paragraph; unit lines say def-now |
| 9 | population_to_level is REMAINING population, rendered as a denominator ("pop 3/1") | **Applied**: city line now "population N, needs M more pop to level up" |
| 10 | The first state of a turn can precede income/pop being applied (turns 1 and 10 planned with 1 star) | **Applied**: runner waits turn_settle (1.5 s), re-requests a state and plans from the settled one; header wording and budget instruction updated |

## Deathmatch design reviews (Claude vs Codex in one Pass & Play game, 2026-09-07)

The plan for letting two agents play each other (offline hotseat game, one seat per model) was reviewed by
Codex (model `gpt-6-astra`) twice before implementation, plus one internal architecture pass. Prompts were
the plan text itself.

### Round 1 (design review)

| # | Codex point | Disposition |
|---|---|---|
| 1 | A read-only Codex sandbox does not isolate the Codex seat: it can still run commands and read any file; also system-prompt placement differs | **Applied**: Codex runs in an empty directory holding only AGENTS.md (the game instructions) and the schema, with its shell/browser/computer-use/image/skill tool features disabled and the user config ignored; every tool item in its event stream counts as a violation. Placement asymmetry (system prompt vs AGENTS.md) is documented in the script and RESULTS.md |
| 2 | The hotseat handoff must be an explicit state machine, overlay before the idle gate | **Applied**: `Plugin.cs` WatchGame order: ended -> overlay -> running-state gate -> popups -> replay wait -> seat check -> idle -> state; the spike then found the recap/replay step and the synchronous-command case |
| 3 | Validate the real roster and bind planners to verified ids; an `ok` only echoes the request | **Applied**: every `state` carries `roster`; `to_menu_and_new_game` checks game type, map size, human/bot counts and tribes and returns the opening player; the script binds `--first` to that player |
| 4 | The seat must travel the whole transport path (client envelope, plugin, executor) | **Applied**: `BridgeClient.act(player=)`, `HandleLine` reads it, `ActionExecutor.Execute(action, seat)` rejects `wrong seat`; tested on the wire and against the real bridge |
| 5 | The turn-start settle refresh swallows a socket timeout on a now-unusable reader | **Applied**: the run stops with outcome `timeout` and closes the connection; regression test |
| 6 | Stated budgets differed from the inherited behaviour | **Applied**: per seat-turn, 3 model calls including retries, 60 *budgeted* actions (planned steps and capture sweeps); trigger answers and end turn are free; both sweep paths check the budget |
| 7 | Define the Codex result contract before building streaming and accounting | **Applied**: recorded a real `codex exec --json` run first (fixtures); `-o` file is the answer of record, no text fallback; usage separates cached tokens; no cost for Codex (shown as n/a, no price estimate); no delta streaming (Codex emits whole items) |
| 8 | Synthetic seat fixtures are inconsistent; fresh planners per game | **Applied**: hotseat fixtures are recorded from the real bridge (turn 0 both seats, turn 1); `make_planner` always builds a new instance |

### Round 2 (revised plan)

| # | Codex point | Disposition |
|---|---|---|
| 1 | Violation reporting alone still lets a compromised match be scored | **Applied**: verified tool disabling is the prerequisite; any violation marks the game `void` (played out, not scored, exit code 3) |
| 2 | The watchdog missed hangs in the overlay/popup branches, and warnings restarted the client's receive timeout | **Applied**: the handoff timer runs across every unready branch, warnings are throttled to one per 10 s, `BridgeClient.expect()` uses an absolute deadline and never queues warnings |
| 3 | Backend metadata (streamed, violations) had no path through `Plan.raw` and was lost on failed attempts | **Applied**: `Plan.meta`, accumulated across attempts; `PlannerError.meta` |
| 4 | "Cost n/a" needs nullable cost end to end | **Applied**: `Plan.cost`, `TurnPlanner.cost()`, seat and game totals are `float | None`; `add_cost`/`fmt_cost` |
| 5 | The outgoing seat's footer would be charged to the incoming seat | **Applied**: `footer(seat, turn)`; the previous seat is finalized before the new one is bound; test |
| 6 | Both capture-sweep paths ignored the action cap, and trigger answers were counted | **Applied**: `turn_actions_total` vs `turn_actions_budgeted`; test at the cap boundary |
| 7 | `--first` must bind to the engine's actual opening player | **Applied**: the script binds the `--first` planner to the first state's `player`, the other to the remaining human id; p1/p2 stay CLI identities |

Round 2 did not answer the direct questions about tool-disabling config keys and the `-o` channel; the
recording spike settled both (`--disable shell_tool …` flags exist and are accepted; `-o` holds the
schema-conformant JSON).

### What the spikes found that no review predicted

- The hotseat overlay's Continue makes the client rewind to the start of the turn and replay the previous
  seat's commands as a recap; `GameState` is a rewound snapshot meanwhile (`HasTargetState()` is the signal;
  `IsRecap`/`isRecapping` are true for the whole human turn and useless). The bridge waits it out.
- Commands sent through the bridge bypass the HUD path that shows the overlay between seats, so after the
  engine has moved to the next player the bridge calls `SetNewLocalPlayerTurnForPassAndPlay` itself.
- After that switch the action loop is stopped and commands apply synchronously; `CommandStack.Count` grows on
  queueing, `CurrentCommand` on application, so "consumed?" must look at the latter only.
- The runner must never act again on a seat-turn whose end turn was accepted (the bridge can re-send that
  state before the seat changes); it waits, nudges once, then stops.
