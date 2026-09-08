#!/usr/bin/env python3
"""Claude vs Codex: one offline Pass & Play Domination game on a tiny map, each seat driven by its own model.

    play_deathmatch.py                                         # Opus 5 (Claude Code) vs gpt-6-astra (Codex), Claude moves first
    play_deathmatch.py --first p2                              # Codex moves first
    play_deathmatch.py --p1 claude:claude-sonnet-5:low --p2 codex:gpt-6-astra:low --max-turns 3   # smoke game
    play_deathmatch.py --p1 claude:claude-opus-5 --p2 claude:claude-sonnet-5                        # Claude vs Claude

Fairness rules (both seats): the same game instructions (rules.md + strategy_domination.md; Claude as the
system prompt, Codex as AGENTS.md in an isolated directory), the same observation text and plan schema, the
same budgets (--max-calls-per-turn model calls per turn including retries, --max-actions-per-turn budgeted
actions; trigger answers and end turn are free), the same fixed reward/peace policy, the same tribe, and no
tools (Claude runs with --tools ""; Codex with its tool features disabled and a violation monitor: any tool
use voids the game). Neither planner sees the other's notes, commentary or state. The engine's opening player
takes the --first planner; the other seat takes the other planner. A planner that times out or answers
invalidly ends its turn; it does not forfeit. Exit code: 0 p1 won, 1 p2 won, 2 undecided, 3 void, 4 error.
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polytopia_bridge import BridgeClient  # noqa: E402
from polytopia_bridge.console import Console  # noqa: E402
from polytopia_bridge.logger import GameLogger  # noqa: E402
from polytopia_bridge.planner import fmt_cost, make_planner  # noqa: E402
from polytopia_bridge.runner import play_turns, to_menu_and_new_game  # noqa: E402

EXIT = {"p1": 0, "p2": 1, "undecided": 2, "void": 3, "error": 4}


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--p1", default="claude:claude-opus-5:medium", help="backend:model[:effort] for planner 1")
    ap.add_argument("--p2", default="codex:gpt-6-astra:medium", help="backend:model[:effort] for planner 2")
    ap.add_argument("--first", default="p1", choices=["p1", "p2"], help="which planner takes the engine's opening seat")
    ap.add_argument("--mode", default="Domination")
    ap.add_argument("--map-size", type=int, default=11, help="11 tiny, 14 small, 16 normal")
    ap.add_argument("--map-preset", default="Dryland", help="Dryland/Lakes/Continents/Archipelago/WaterWorld/Pangea")
    ap.add_argument("--tribes", default="Imperius,Imperius", help="tribe for the opening seat, tribe for the other seat")
    ap.add_argument("--bots", type=int, default=0, help="built-in bots added to the game (default none)")
    ap.add_argument("--difficulty", default="Normal", help="bot difficulty, only if --bots > 0")
    ap.add_argument("--max-turns", type=int, default=0, help="stop after this turn number (0 = play to game over)")
    ap.add_argument("--max-calls-per-turn", type=int, default=3, help="model calls per seat-turn, retries included")
    ap.add_argument("--max-actions-per-turn", type=int, default=60)
    ap.add_argument("--state-timeout", type=float, default=900)
    ap.add_argument("--call-timeout", type=float, default=300, help="seconds to wait for one model call")
    ap.add_argument("--no-sweep-captures", action="store_true", help="do not auto-capture before ending a turn")
    ap.add_argument("--turn-settle", type=float, default=1.5,
                    help="seconds to wait at each seat-turn start before re-requesting a settled state (0 = off)")
    ap.add_argument("--no-thinking", action="store_true", help="hide the thinking progress line")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="also print the model's notes and per-action timing")
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--work-dir", default=None, help="parent directory for the Codex seat's isolated working directory")
    args = ap.parse_args()

    console = Console(color=not args.no_color, show_thinking=not args.no_thinking, verbose=args.verbose)
    tribes = [t.strip() for t in args.tribes.split(",") if t.strip()]
    while len(tribes) < 2:
        tribes.append(tribes[0] if tribes else "Imperius")

    # fresh instances per game: notes, usage and cost live on the planner
    planners = {"p1": make_planner(args.p1, timeout=args.call_timeout, on_thinking=console.thinking,
                                   on_commentary=console.commentary, work_root=args.work_dir),
                "p2": make_planner(args.p2, timeout=args.call_timeout, on_thinking=console.thinking,
                                   on_commentary=console.commentary, work_root=args.work_dir)}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(args.log_dir) / f"{stamp}-deathmatch-{safe(planners['p1'].name)}-vs-{safe(planners['p2'].name)}.jsonl"

    with GameLogger(log_path) as log, BridgeClient(args.host, args.port) as bridge:
        hello = bridge.connect(retry_for=60)
        bridge.on_warning = lambda m: console.warn(f"bridge warning: {m.get('reason')} ({m.get('where')}, {m.get('stalled_seconds')}s)")
        log.log("hello", **hello, p1=planners["p1"].name, p2=planners["p2"].name, first=args.first)
        console.banner(f"connected to Polytopia {hello.get('game_version')} | p1 {planners['p1'].name} vs p2 {planners['p2'].name} | log {log_path}")
        settings = {"game_type": "PassAndPlay", "mode": args.mode, "players": 2, "bots": args.bots,
                    "difficulty": args.difficulty, "map_preset": args.map_preset, "map_size": args.map_size,
                    "tribes": tribes[:2]}
        console.note(f"starting a new game: {settings}")
        reply = to_menu_and_new_game(bridge, settings)
        log.log("new_game", **settings, reply=reply)
        roster = reply.get("roster") or []
        humans = [p["id"] for p in roster if not p.get("is_bot")]
        opening = reply.get("first_player")
        if opening not in humans or len(humans) != 2:
            console.warn(f"unexpected roster {roster} / opening player {opening}; cannot bind seats")
            return EXIT["error"]
        other = next(p for p in humans if p != opening)
        first, second = (args.first, "p2" if args.first == "p1" else "p1")
        seats = {opening: planners[first], other: planners[second]}
        by_id = {p["id"]: p for p in roster}
        console.note(f"{first} = {planners[first].name} plays player {opening} ({by_id[opening]['tribe']}), moves first; "
                     f"{second} = {planners[second].name} plays player {other} ({by_id[other]['tribe']}), moves second")
        log.log("seats", **{str(pid): pl.name for pid, pl in seats.items()})

        res = play_turns(bridge, seats, log, console, max_turns=args.max_turns,
                         max_calls_per_turn=args.max_calls_per_turn, max_actions_per_turn=args.max_actions_per_turn,
                         state_timeout=args.state_timeout, sweep_captures=not args.no_sweep_captures,
                         turn_settle=args.turn_settle if args.turn_settle > 0 else None)

    for pid, summary in res.seats.items():
        console.note(f"player {pid} {summary['planner']}: won={summary['won']} calls={summary['calls']} "
                     f"actions={summary['actions']} violations={summary['violations']} cost={fmt_cost(summary['cost_usd'])}")
    if res.outcome == "void":
        console.warn("result: VOID (tool-use violation); not scored")
        return EXIT["void"]
    if res.outcome != "game_over":
        console.warn(f"result: {res.outcome} at turn {res.final_turn}; not scored")
        return EXIT["undecided"] if res.outcome == "max_turns" else EXIT["error"]
    winner_seat = next((tag for tag, pl in planners.items() if any(s.get("won") and s["planner"] == pl.name for s in res.seats.values())), None)
    console.banner(f"result: {winner_seat or 'no winner'} ({planners[winner_seat].name if winner_seat else '-'}) on turn {res.final_turn}")
    return EXIT[winner_seat] if winner_seat else EXIT["undecided"]


if __name__ == "__main__":
    sys.exit(main())
