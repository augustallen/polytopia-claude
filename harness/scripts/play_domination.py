#!/usr/bin/env python3
"""Start a new Domination game against one bot and let Claude rush it, with live terminal commentary.

    play_domination.py                          # new Tiny Domination game vs 1 Normal bot, Opus 5 via Claude Code
    play_domination.py --difficulty Easy --map-preset Pangea
    play_domination.py --model claude-sonnet-5 --effort low     # faster, weaker
    play_domination.py --attach                 # play the game already in progress instead of starting one

One model call plans a whole turn (an ordered list of actions); bounded re-plans happen only when the
model asks for them. Everything is also written to --log-dir/<timestamp>-domination-<model>.jsonl.
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
from polytopia_bridge.planner import DEFAULT_MODEL, TurnPlanner  # noqa: E402
from polytopia_bridge.runner import play_turns, to_menu_and_new_game  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Claude Code model (runs on your subscription)")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--attach", action="store_true", help="do not start a new game; play the one in progress")
    ap.add_argument("--mode", default="Domination")
    ap.add_argument("--difficulty", default="Normal")
    ap.add_argument("--opponents", type=int, default=1)
    ap.add_argument("--map-size", type=int, default=11, help="11 tiny, 14 small, 16 normal (0 = game default)")
    ap.add_argument("--map-preset", default="Dryland", help="Dryland/Lakes/Continents/Archipelago/WaterWorld/Pangea")
    ap.add_argument("--tribe", default="Imperius")
    ap.add_argument("--max-turns", type=int, default=0, help="stop after this turn number (0 = play to game over)")
    ap.add_argument("--max-calls-per-turn", type=int, default=3, help="model calls per turn, retries included")
    ap.add_argument("--max-actions-per-turn", type=int, default=60)
    ap.add_argument("--state-timeout", type=float, default=900)
    ap.add_argument("--call-timeout", type=float, default=300, help="seconds to wait for one model call")
    ap.add_argument("--no-sweep-captures", action="store_true", help="do not auto-capture before ending a turn")
    ap.add_argument("--turn-settle", type=float, default=1.5,
                    help="seconds to wait at each turn start before re-requesting a settled state (0 = off)")
    ap.add_argument("--no-thinking", action="store_true", help="hide the thinking progress line")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="also print the model's notes and per-action timing")
    ap.add_argument("--log-dir", default="logs")
    args = ap.parse_args()

    console = Console(color=not args.no_color, show_thinking=not args.no_thinking, verbose=args.verbose)
    planner = TurnPlanner(args.model, args.effort, timeout=args.call_timeout,
                          on_thinking=console.thinking, on_commentary=console.commentary)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", args.model)
    log_path = Path(args.log_dir) / f"{stamp}-domination-{safe_model}.jsonl"

    with GameLogger(log_path) as log, BridgeClient(args.host, args.port) as bridge:
        hello = bridge.connect(retry_for=60)
        log.log("hello", **hello, agent=planner.name, effort=args.effort)
        console.banner(f"connected to Polytopia {hello.get('game_version')} | model {args.model} ({args.effort}) | log {log_path}")
        if not args.attach:
            settings = {"mode": args.mode, "difficulty": args.difficulty, "opponents": args.opponents,
                        "map_preset": args.map_preset, "tribe": args.tribe}
            if args.map_size:
                settings["map_size"] = args.map_size
            console.note(f"starting a new game: {settings}")
            reply = to_menu_and_new_game(bridge, settings)
            log.log("new_game", **settings, reply=reply)
            console.note(f"game created: {reply}")
        res = play_turns(bridge, planner, log, console, max_turns=args.max_turns,
                         max_calls_per_turn=args.max_calls_per_turn, max_actions_per_turn=args.max_actions_per_turn,
                         state_timeout=args.state_timeout, sweep_captures=not args.no_sweep_captures,
                         turn_settle=args.turn_settle if args.turn_settle > 0 else None)
    return {"game_over": 0, "max_turns": 0, "timeout": 2, "closed": 3, "stuck": 4}[res.outcome]


if __name__ == "__main__":
    sys.exit(main())
