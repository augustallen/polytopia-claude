#!/usr/bin/env python3
"""Run the evaluation ladder (PLAN.md phase 3): N games x difficulty x agent, one CSV row per game.

    run_eval.py --games 5 --difficulties Easy,Normal --agents random,claude:claude-fable-5-1
    run_eval.py --games 1 --difficulties Easy --agents random --max-turns 3   # quick cycle test

Each game is started through the bridge (new_game), played to the end, then the game returns to
the menu for the next one. If the game process dies mid-game, it is relaunched through Steam and
that game is recorded with outcome "closed". Per-game JSONL logs go to --log-dir; the CSV is
appended to as games finish, so a run can be stopped and resumed.
"""
import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polytopia_bridge import BridgeClient, BridgeClosed  # noqa: E402
from polytopia_bridge.agent import ClaudeAgent, ClaudeCodeAgent, RandomAgent  # noqa: E402
from polytopia_bridge.logger import GameLogger  # noqa: E402
from polytopia_bridge.runner import play_game, restart_game, to_menu_and_new_game  # noqa: E402

COLUMNS = ["timestamp", "agent", "model", "effort", "mode", "difficulty", "opponents", "map_size", "tribe", "seed",
           "outcome", "final_turn", "won", "final_score", "score_turn_10", "score_turn_20", "score_turn_30",
           "actions", "rejected", "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd", "log"]


def make_agent(spec: str, effort: str, seed: int):
    if spec == "random":
        return RandomAgent(seed), "random", "", ""
    if spec.startswith("claude-code"):
        model = spec.split(":", 1)[1] if ":" in spec else "claude-sonnet-5"
        return ClaudeCodeAgent(model), "claude-code", model, ""
    if spec.startswith("claude"):
        model = spec.split(":", 1)[1] if ":" in spec else ClaudeAgent.__init__.__defaults__[0]
        return ClaudeAgent(model, effort), "claude", model, effort
    raise SystemExit(f"unknown agent spec {spec!r} (use random, claude:<model> or claude-code:<model>)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--games", type=int, default=5, help="games per (agent, difficulty) cell")
    ap.add_argument("--difficulties", default="Easy", help="comma-separated: Easy,Normal,Hard,Crazy")
    ap.add_argument("--agents", default="random", help="comma-separated: random, claude:<model>")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--mode", default="Perfection")
    ap.add_argument("--opponents", type=int, default=3)
    ap.add_argument("--map-size", type=int, default=0)
    ap.add_argument("--map-preset", default="Continents")
    ap.add_argument("--tribe", default="Imperius")
    ap.add_argument("--max-turns", type=int, default=0)
    ap.add_argument("--state-timeout", type=float, default=900)
    ap.add_argument("--out", default="results/results.csv")
    ap.add_argument("--log-dir", default="results/logs")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    csv_f = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_f, fieldnames=COLUMNS)
    if new_file:
        writer.writeheader()

    bridge = BridgeClient(args.host, args.port)
    try:
        bridge.connect(retry_for=60)
    except OSError:
        print("game not reachable; launching it")
        bridge = restart_game(args.host, args.port)

    for difficulty in [d.strip() for d in args.difficulties.split(",") if d.strip()]:
        for spec in [s.strip() for s in args.agents.split(",") if s.strip()]:
            for game_no in range(args.games):
                seed = game_no
                agent, kind, model, effort = make_agent(spec, args.effort, seed)
                settings = {"mode": args.mode, "difficulty": difficulty, "opponents": args.opponents,
                            "map_preset": args.map_preset, "tribe": args.tribe}
                if args.map_size:
                    settings["map_size"] = args.map_size
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                log_path = Path(args.log_dir) / f"{stamp}-{difficulty}-{agent.name}-{seed}.jsonl"
                print(f"\n=== {difficulty} | {spec} | game {game_no + 1}/{args.games} | log {log_path}")
                with GameLogger(log_path) as log:
                    try:
                        reply = to_menu_and_new_game(bridge, settings)
                        log.log("new_game", **reply)
                        res = play_game(bridge, agent, log, max_turns=args.max_turns, state_timeout=args.state_timeout,
                                        verbose=not args.quiet)
                    except (BridgeClosed, OSError, RuntimeError) as ex:
                        print(f"game aborted: {ex}; relaunching the game")
                        log.log("aborted", reason=str(ex))
                        from polytopia_bridge.runner import GameResult
                        res = GameResult("closed")
                        try:
                            bridge.close()
                        except Exception:
                            pass
                        bridge = restart_game(args.host, args.port)
                usage = res.usage or {}
                writer.writerow({
                    "timestamp": stamp, "agent": kind, "model": model, "effort": effort, "mode": args.mode,
                    "difficulty": difficulty, "opponents": args.opponents, "map_size": settings.get("map_size", ""),
                    "tribe": args.tribe, "seed": seed, "outcome": res.outcome, "final_turn": res.final_turn,
                    "won": res.won, "final_score": res.final_score, "score_turn_10": res.score_at(10),
                    "score_turn_20": res.score_at(20), "score_turn_30": res.score_at(30), "actions": res.actions,
                    "rejected": res.rejected, "input_tokens": usage.get("input", 0), "output_tokens": usage.get("output", 0),
                    "cache_read_tokens": usage.get("cache_read", 0), "cost_usd": res.cost_usd, "log": str(log_path),
                })
                csv_f.flush()
                time.sleep(2)
    csv_f.close()
    bridge.close()
    print(f"\nresults appended to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
