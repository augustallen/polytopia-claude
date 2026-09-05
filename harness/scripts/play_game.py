#!/usr/bin/env python3
"""Play one Polytopia game end to end through the bridge (PLAN.md phase 2, step 5).

    play_game.py                       # Claude (claude-fable-5-1) plays the game in progress
    play_game.py --resume              # resume the saved game first if the game is at the menu
    play_game.py --new --difficulty Normal --opponents 3 --tribe Imperius   # start a fresh game
    play_game.py --model claude-opus-5 --effort medium
    play_game.py --agent random        # the random-legal-action baseline

The script waits for the first state, then loops state -> decision -> action -> result, printing
one line per action and the score each turn. Everything is written to --log-dir/<timestamp>-<agent>.jsonl.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polytopia_bridge import BridgeClient  # noqa: E402
from polytopia_bridge.agent import DEFAULT_MODEL, ClaudeAgent, ClaudeCodeAgent, RandomAgent  # noqa: E402
from polytopia_bridge.logger import GameLogger  # noqa: E402
from polytopia_bridge.runner import play_game, to_menu_and_new_game  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--agent", choices=["claude", "claude-code", "random"], default="claude",
                    help="claude = Anthropic API (needs ANTHROPIC_API_KEY); claude-code = headless Claude Code on your subscription")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--resume", action="store_true", help="resume the saved single-player game if at the menu")
    ap.add_argument("--new", action="store_true", help="start a new game (leaves any game in progress)")
    ap.add_argument("--mode", default="Perfection")
    ap.add_argument("--difficulty", default="Easy")
    ap.add_argument("--opponents", type=int, default=3)
    ap.add_argument("--map-size", type=int, default=0, help="11 tiny, 14 small, 16 normal, ... (0 = game default)")
    ap.add_argument("--map-preset", default="Continents")
    ap.add_argument("--tribe", default="Imperius")
    ap.add_argument("--max-turns", type=int, default=0, help="stop after this turn number (0 = play to game over)")
    ap.add_argument("--max-actions-per-turn", type=int, default=60)
    ap.add_argument("--state-timeout", type=float, default=900)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log-dir", default="logs")
    args = ap.parse_args()

    if args.agent == "random":
        agent = RandomAgent(args.seed)
    elif args.agent == "claude-code":
        agent = ClaudeCodeAgent(args.model)
    else:
        agent = ClaudeAgent(args.model, args.effort)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(args.log_dir) / f"{stamp}-{agent.name}.jsonl"

    with GameLogger(log_path) as log, BridgeClient(args.host, args.port) as bridge:
        hello = bridge.connect(retry_for=60)
        log.log("hello", **hello, agent=agent.name, effort=getattr(agent, "effort", None))
        print(f"connected: game {hello['game_version']}, agent {agent.name}, log {log_path}")
        if args.new:
            settings = {"mode": args.mode, "difficulty": args.difficulty, "opponents": args.opponents,
                        "map_preset": args.map_preset, "tribe": args.tribe}
            if args.map_size:
                settings["map_size"] = args.map_size
            print("new_game ->", to_menu_and_new_game(bridge, settings))
            log.log("new_game", **settings)
        elif args.resume and not hello.get("in_game"):
            print("resume ->", bridge.resume())

        res = play_game(bridge, agent, log, max_turns=args.max_turns, max_actions_per_turn=args.max_actions_per_turn,
                        state_timeout=args.state_timeout)
    return {"game_over": 0, "max_turns": 0, "timeout": 2, "closed": 3}[res.outcome]


if __name__ == "__main__":
    sys.exit(main())
