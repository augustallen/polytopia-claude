# Results

## Domination rush, turn planner (`play_domination.py`)

| Date | Setup | Model | Result | Turns | Model calls | Wall time | Est. list cost | Log |
|---|---|---|---|---|---|---|---|---|
| 2026-09-05 | Tiny 11x11 Dryland, Imperius vs 1 **Normal** bot (Hoodrick) | claude-opus-5 (medium) via Claude Code | **WON** (Domination) | 26 | 37 (18 turns x1, 8 x2, 1 x3) | 36 min | $4.12 | `harness/logs/20260905-155237-domination-claude-opus-5.jsonl`, transcript `docs/samples/game1-domination-normal-opus5.txt` |

| 2026-09-05 | Tiny 11x11 Dryland, Imperius vs 1 **Normal** bot (Bardur) | claude-opus-5 (medium) via Claude Code, round-4 prompts | **LOST** (eliminated) | 26 | 34 (21 turns x1, 5 x2, 1 x3) | 35 min | $3.89 | `harness/logs/20260905-170843-domination-claude-opus-5.jsonl`, transcript `docs/samples/game2-domination-normal-opus5.txt` |

Game 2 notes:
- Enemy capital Tofork (level 3, walls) sat 5 tiles south of ours and was located on turn 9. Riders staged around it from turn 10 with nothing able to kill the walled garrison; the bot answered with Swordsmen and Defenders, retook the eastern forward cities twice, and grew to 5 cities and a level-5 capital with a Giant.
- The first Catapult (turn 15) died the same enemy turn to a Swordsman two tiles away; a protection rule was added to the strategy afterwards.
- Passive play: 34 recover actions vs 26 attacks (game 1: 17 vs 56); stars banked from 26 (turn 19) to 54 (turn 24) while cities were lost.
- Loop mechanics were clean: 203 planned steps, 1 skipped, 0 rejections.

Game 1 notes:
- Explorer at turn 0 revealed the map; the enemy capital Wegoth (level 3, walls) was located on turn 6, a forward village next to it captured on turn 9.
- 314 planned steps, 297 executed, 17 skipped (5%), 1 rejection (a level-up reward registered after the state was sent; the runner now retries the step after answering the reward).
- Median 18.7 s per planning call (min 8, max 45); the bridge side adds roughly 1-3 s per action.
- Turns 14-21 were spent chipping the walled capital with archers before Forestry -> Mathematics -> Catapults broke the garrison; Wegoth fell on turn 22, the last city Gory on turn 26.
- Weakness: stars banked from 21 (turn 14) to 114 (turn 26) while income was 16-31/turn; the round-3 prompt revisions target spending toward a named purchase.

Earlier per-action harness runs (Perfection, `play_game.py`) are not tabulated here; see `results/results.csv` when the ladder is run.

## Deathmatch: Claude vs Codex, one Pass & Play Domination game (`play_deathmatch.py`)

Rules for every row: tiny 11x11 Dryland, two human seats, no bots, both Imperius, same instructions/observation/
schema/budgets/reward policy for both seats, no tools. The Codex seat runs on the ChatGPT subscription (tokens
only); the Claude seat on the Claude subscription (list price shown). Known asymmetry: Claude gets the
instructions as a system prompt, Codex as AGENTS.md.

| Date | Moves first | Seat 1 | Seat 2 | Result | Turns | Calls (s1 / s2) | Tool-use violations | Wall time | Log |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-07 | Claude | claude-sonnet-5 (low, Claude Code) | gpt-6-astra (low, Codex) | smoke test, stopped at the turn cap (undecided) | 0-2 | 3 / 3 | 0 | 2 min | `harness/logs/20260907-195926-deathmatch-claude-code-claude-sonnet-5-vs-codex-gpt-6-astra.jsonl` |
| 2026-09-07 | Claude | claude-opus-5 (medium, Claude Code) | gpt-6-astra (medium, Codex) | **Codex won** (Claude eliminated) | 18 | 30 / 39 | 0 | 30 min | `harness/logs/20260907-202029-deathmatch-claude-code-claude-opus-5-vs-codex-gpt-6-astra.jsonl`, transcript `docs/samples/game3-deathmatch-opus5-vs-gpt6astra.txt` |

Game 3 notes (Opus 5 vs gpt-6-astra):
- Claude expanded faster (3 cities and +11 income by turn 7, three villages captured) and built an Archer line; Codex stayed
  on one city until turn 8 but reached a level-4 capital and a Giant by turn 9, then Catapults, and grew to +20 income.
- From turn 10 Codex's Giant/Catapult/Archer stack ground down Claude's Archers and Defenders; Claude lost its forward
  city on turn 16, its last units on turn 17, and was eliminated on turn 18.
- Loop mechanics: 345 actions, 4 rejections, 1 skipped step, 0 tool-use violations, every seat handoff handled by the
  bridge (overlay, recap wait, seat switch); one earlier attempt of this match stalled on a reward prompt that arrived
  after end turn (fixed in the runner before this game).
- Cost: Claude seat $2.32 list price (30 calls); Codex seat 541k input / 16k output tokens on the subscription (39 calls).
| 2026-09-07 | Claude | claude-fable-5-1 (medium, Claude Code) | gpt-6-astra (medium, Codex) | **Codex won** (Claude eliminated) | 14 | 26 / 33 | 0 | 24 min | `harness/logs/20260907-210750-deathmatch-claude-code-claude-fable-5-1-vs-codex-gpt-6-astra.jsonl`, transcript `docs/samples/game4-deathmatch-fable51-vs-gpt6astra.txt` (the screen recording of this game came out as one frozen frame; see game 5) |

Game 4 notes (Fable 5.1 vs gpt-6-astra, screen-recorded):
- Fable took a village on turn 3 and led briefly (two cities, +7 income by turn 4); Astra matched it on turn 4, took two
  more villages on turn 7 and pulled away to four cities and +13 income by turn 10.
- Fable lost both Riders around turn 6-7 and never rebuilt a field army; Astra's Archer line (six by turn 11) plus
  Riders and a Swordsman killed everything Fable trained, took its second city on turn 13 and its capital on turn 14.
- Cost: Fable seat $3.76 list price (26 calls, median 16 s); Astra 344k input / 11k output tokens (33 calls, median 22 s).
- The game has no replay for offline games (replays are fetched from Midjiwan's servers for online matches only), so
  `scripts/record_match.py` screen-recorded the match. This first recording used gdigrab's window-title capture, which
  froze on the first frame (the Unity DirectX surface never repaints through GDI); the recorder now captures the screen
  region under the game window instead.
| 2026-09-07 | Claude | claude-fable-5-1 (medium, Claude Code) | gpt-6-astra (medium, Codex) | **Codex won** (Claude eliminated) | 14 | 26 / 32 | 0 | 23 min | `harness/logs/20260907-213529-deathmatch-claude-code-claude-fable-5-1-vs-codex-gpt-6-astra.jsonl`, transcript `docs/samples/game5-deathmatch-fable51-vs-gpt6astra.txt`, **video** `harness/recordings/game5-fable51-vs-gpt6astra.mp4` (22:55, 111 MB, 1920x2052 at 10 fps) |

Game 5 notes (Fable 5.1 vs gpt-6-astra, screen-recorded with the fixed capture):
- Fable never captured a village: it stayed on one city at +4 income for the whole game while Astra took villages on
  turns 3, 7, 8, 10 and 11 (six cities, +18 income by turn 13) and added a Giant on turn 11.
- Fable's units died piecemeal (11 losses); it was reduced to a Defender and a Rider by turn 10, and Astra took the
  capital on turn 14. Final score 4,480 to 1,640.
- Cost: Fable seat $3.41 list price (26 calls, median 15 s); Astra 331k input / 11k output tokens (32 calls, median 22 s).
- Stats card for posting: `docs/samples/game5-card.png`, rendered from the log by `harness/scripts/match_card.py`
  (works for any deathmatch log: `python scripts/match_card.py logs/<game>.jsonl --out <png>`).
- Running tally, Claude vs Codex deathmatch: Codex 3, Claude 0 (games 3, 4, 5), all with Claude moving first.
| 2026-09-07 | Grok | grok-4.6 (medium, Grok Build CLI) | gpt-6-astra (medium, Codex) | **Codex won** (Grok eliminated) | 10 | 24 / 25 | 0 | 53 min | `harness/logs/20260907-231239-deathmatch-grok-grok-4.6-vs-codex-gpt-6-astra.jsonl`, transcript `docs/samples/game6-deathmatch-grok46-vs-gpt6astra.txt`, video `harness/recordings/game6-grok46-vs-gpt6astra.mp4` (53 min, 107 MB; 4x cut `-4x.mp4`, 13 min, 25 MB), card `docs/samples/game6-card.png` |

Game 6 notes (Grok 4.6 vs gpt-6-astra, first game with the xAI Grok Build CLI seat):
- Grok opened with two Riders and took two villages on turn 6 (three cities, score lead 2,040 to 1,415 at the start of
  turn 7), but Astra's four Riders and two Warriors retook both on turns 7-8, killed Grok's units piecemeal, and took the
  capital on turn 10. Final score 2,710 to 1,360; Astra 4 kills, Grok 1.
- Grok's planning calls were slow: median 102 s, max 228 s at medium effort (about 5,500 reasoning tokens per call);
  Astra's median was 19 s. Wall time 53 min for 10 turns, most of it Grok thinking.
- Fairness: both seats had the same instructions, observation, schema and budgets; Grok got the instructions as a
  system-prompt override (like the Claude seat), every built-in tool removed, one agent turn per call, zero violations.
  `grok-4.6` accepts `--reasoning-effort medium`, so medium was real. The Grok CLI's list-price estimate was $0.21 for the
  game; the subscription paid for it.
- Running tally, deathmatch vs Codex gpt-6-astra: Codex 4, Claude 0, Grok 0 (games 3-6), all with the non-Codex seat
  moving first.
