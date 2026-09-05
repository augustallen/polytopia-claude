#!/usr/bin/env python3
"""Smoke test for the ClaudeBridge mod (PLAN.md phase 1, step 7).

Connect to the bridge, print every message, and drive the game with a trivial policy:

  --policy endturn   send end_turn whenever it is our turn (default): watches the bots play
  --policy random    pick a random legal action each time: exercises every command kind

The first action sent is deliberately invalid, to confirm the game's own validation error
comes back as {"ok": false, "error": ...}. Every message is appended to --log as JSONL and the
first state is written to --save-state for inspection.

Start a single-player game in Polytopia first; the bridge sends a state as soon as it is our turn.
"""
import argparse
import json
import random
import socket
import sys
from collections import Counter
from pathlib import Path

# Random play should not throw units away or start pointless wars.
RANDOM_AVOID = {"disband", "destroy", "break_peace", "resign"}


def choose(legal, policy):
    if not legal:
        return None
    if policy == "endturn":
        return next((a for a in legal if a["kind"] == "end_turn"), legal[0])
    candidates = [a for a in legal if a["kind"] not in RANDOM_AVOID]
    non_end = [a for a in candidates if a["kind"] != "end_turn"]
    # Mostly act, sometimes end the turn early so games keep moving.
    if non_end and random.random() < 0.9:
        return random.choice(non_end)
    return next((a for a in candidates if a["kind"] == "end_turn"), candidates[0] if candidates else legal[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--policy", choices=["endturn", "random"], default="endturn")
    ap.add_argument("--turns", type=int, default=3, help="stop after this many of our turns (0 = play to game over)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true", help="resume the saved single-player game if the game is at the menu")
    ap.add_argument("--log", default="smoke.jsonl")
    ap.add_argument("--save-state", default="smoke_state.json")
    args = ap.parse_args()
    random.seed(args.seed)

    sock = socket.create_connection((args.host, args.port), timeout=None)
    f = sock.makefile("rw", encoding="utf-8", newline="\n")
    log = open(args.log, "w", encoding="utf-8")

    def send(msg):
        f.write(json.dumps(msg) + "\n")
        f.flush()
        log.write(json.dumps({"dir": "out", "msg": msg}) + "\n")

    def recv():
        line = f.readline()
        if not line:
            sys.exit("bridge closed the connection")
        msg = json.loads(line)
        log.write(json.dumps({"dir": "in", "msg": msg}) + "\n")
        log.flush()
        return msg

    hello = recv()
    print("hello:", hello)
    send({"type": "ping"})
    print("ping ->", recv())
    if args.resume and not hello.get("in_game"):
        send({"type": "resume"})
        print("resume ->", recv())

    turns_seen = 0
    last_turn = None
    sent_invalid = False
    saved = False
    actions_sent = 0
    while True:
        msg = recv()
        kind = msg.get("type")
        if kind == "state":
            st, legal = msg["state"], msg["legal_actions"]
            me = st["me"]
            kinds = Counter(a["kind"] for a in legal)
            print(
                f"turn {msg['turn']} p{msg['player']} stars={me['stars']} income={me['income']} score={me['score']} "
                f"units={len(st['units'])} cities={len(st['cities'])} tiles={len(st['tiles'])} "
                f"pending={st['pending_trigger']} legal={len(legal)} {dict(kinds)}"
            )
            if not saved:
                Path(args.save_state).write_text(json.dumps(msg, indent=1), encoding="utf-8")
                saved = True
            if msg["turn"] != last_turn:
                last_turn = msg["turn"]
                turns_seen += 1
                if args.turns and turns_seen > args.turns:
                    print(f"stopping after {args.turns} turns, {actions_sent} actions sent")
                    break
            if not sent_invalid:
                sent_invalid = True
                send({"type": "action", "action": {"kind": "move", "unit_id": 999999, "to": [0, 0]}})
                continue
            action = choose(legal, args.policy)
            if action is None:
                print("  no legal actions?!")
                continue
            print("  ->", {k: v for k, v in action.items() if k in ("kind", "unit_id", "to", "target", "at", "unit_type", "improvement", "tech", "reward")})
            send({"type": "action", "action": action})
            actions_sent += 1
        elif kind == "result":
            print("  result:", "ok" if msg["ok"] else f"REJECTED: {msg['error']}")
        elif kind == "game_over":
            print("GAME OVER:", json.dumps(msg))
            break
        else:
            print(kind, msg)


if __name__ == "__main__":
    main()
