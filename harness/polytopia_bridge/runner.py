"""The state -> decision -> action loop for one game, shared by play_game.py and run_eval.py."""
from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .client import BridgeClient, BridgeClosed, GameOver
from .logger import GameLogger

GAME_STEAM_URL = "steam://rungameid/874390"


@dataclass
class GameResult:
    outcome: str                     # game_over | max_turns | timeout | closed
    final_turn: int = 0
    won: bool | None = None
    final_score: int | None = None
    scores: list[tuple[int, int]] = field(default_factory=list)   # (turn, score at start of turn)
    actions: int = 0
    rejected: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    game_over: dict[str, Any] | None = None

    def score_at(self, turn: int) -> int | None:
        return next((s for t, s in self.scores if t == turn), None)


def brief(action: dict) -> str:
    keep = ("kind", "unit_id", "to", "target", "at", "unit_type", "improvement", "tech", "reward")
    return json.dumps({k: v for k, v in action.items() if k in keep})


def play_game(bridge: BridgeClient, agent, log: GameLogger, *, max_turns: int = 0, max_actions_per_turn: int = 60,
              state_timeout: float = 900, verbose: bool = True) -> GameResult:
    """Drive the game in progress until game over (or max_turns). Raises nothing; see GameResult.outcome."""
    res = GameResult("closed")
    turn_actions = 0
    last_turn: int | None = None

    def say(s: str) -> None:
        if verbose:
            print(s, flush=True)

    try:
        while True:
            try:
                msg = bridge.wait_for_state(timeout=state_timeout)
            except socket.timeout:
                say(f"no state for {state_timeout:.0f}s; giving up")
                log.log("timeout")
                res.outcome = "timeout"
                break
            newest = bridge.drain_stale_states()
            if newest is not None:
                msg = newest

            turn = msg["turn"]
            res.final_turn = turn
            if turn != last_turn:
                me = msg["state"]["me"]
                if last_turn is not None:
                    say(f"--- turn {last_turn} done: score {res.scores[-1][1]}")
                res.scores.append((turn, me["score"]))
                res.final_score = me["score"]
                log.log("turn", turn=turn, score=me["score"], stars=me["stars"], income=me["income"],
                        cities=len([c for c in msg["state"]["cities"] if c["owner"] == me["id"]]),
                        units=len([u for u in msg["state"]["units"] if u["owner"] == me["id"]]))
                if max_turns and turn > max_turns:
                    say(f"reached max_turns {max_turns}")
                    res.outcome = "max_turns"
                    break
                last_turn = turn
                turn_actions = 0

            legal = msg["legal_actions"]
            if turn_actions >= max_actions_per_turn:
                idx = next((i for i, a in enumerate(legal) if a["kind"] == "end_turn"), 0)
                reasoning, notes, usage, latency, error = "action cap reached", "", {}, 0.0, None
            else:
                d = agent.decide(msg)
                idx, reasoning, notes, usage, latency, error = d.index, d.reasoning, d.notes, d.usage, d.latency, d.error
            action = legal[idx]
            log.log("state", turn=turn, state=msg["state"], legal_actions=legal)
            log.log("decision", turn=turn, index=idx, action=action, reasoning=reasoning, notes=notes,
                    usage=usage, latency=round(latency, 2), error=error)

            result = bridge.act(action)
            agent.record(turn, action, result)
            log.log("result", turn=turn, **result)
            turn_actions += 1
            res.actions += 1
            if not result["ok"]:
                res.rejected += 1
            status = "ok" if result["ok"] else f"REJECTED: {result['error']}"
            why = (reasoning or "").replace("\n", " ")[:110]
            say(f"t{turn} #{turn_actions} {brief(action)} -> {status}  | {why}")
    except GameOver as g:
        m = g.message
        res.outcome = "game_over"
        res.final_turn = m["turn"]
        res.won = bool(m.get("won"))
        res.final_score = m.get("score")
        res.game_over = m
        say(f"GAME OVER on turn {m['turn']}: {'WON' if m['won'] else 'lost'}; score {m.get('score')}; winner player {m.get('winner')}")
        log.log("game_over", **m)
    except BridgeClosed as ex:
        say(f"bridge closed: {ex}")
        log.log("bridge_closed", reason=str(ex))
        res.outcome = "closed"
    finally:
        res.usage = dict(agent.total_usage)
        res.cost_usd = round(agent.cost(), 4)
        log.log("summary", outcome=res.outcome, final_turn=res.final_turn, won=res.won, final_score=res.final_score,
                scores=res.scores, actions=res.actions, rejected=res.rejected, usage=res.usage, cost_usd=res.cost_usd)
        say("scores by turn: " + " ".join(f"{t}:{s}" for t, s in res.scores))
        if res.usage:
            say(f"tokens: {res.usage}  est. cost ${res.cost_usd:.2f}")
    return res


# ---------------------------------------------------------------------------- game process helpers (Windows)

def game_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Polytopia.exe"], capture_output=True, text=True).stdout
    return "Polytopia.exe" in out


def restart_game(bridge_host: str = "127.0.0.1", bridge_port: int = 9876, wait: float = 120) -> BridgeClient:
    """Kill and relaunch the game through Steam, then return a connected client (at the start screen)."""
    subprocess.run(["taskkill", "/IM", "Polytopia.exe", "/F"], capture_output=True)
    time.sleep(3)
    subprocess.run(["cmd", "/c", "start", "", GAME_STEAM_URL], capture_output=True)
    deadline = time.monotonic() + wait
    client = BridgeClient(bridge_host, bridge_port)
    client.connect(retry_for=wait)
    # the listener is up before the start screen; wait until a status call says the menu is ready
    while time.monotonic() < deadline:
        st = client.status()
        if st.get("has_game_manager") and not st.get("is_loading_game"):
            time.sleep(4)   # StartScreen.Init + backend login settle
            return client
        time.sleep(2)
    return client


def to_menu_and_new_game(client: BridgeClient, settings: dict[str, Any], settle: float = 3.0) -> dict[str, Any]:
    """Leave any game in progress, then start a new one; returns the bridge's new_game reply."""
    hello = client.hello or {}
    if hello.get("in_game") or client.status().get("has_game_state"):
        client.send({"type": "return_to_menu"})
        client.expect("ok", "error")
        for _ in range(30):
            time.sleep(1)
            if not client.status().get("has_game_state"):
                break
        time.sleep(settle)
    client.send({"type": "new_game", **settings})
    reply = client.expect("ok", "error")
    if reply["type"] != "ok":
        raise RuntimeError(f"new_game failed: {reply.get('error')}")
    client.wait_until_in_game()
    return reply
