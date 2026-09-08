"""The state -> decision -> action loop for one game, shared by play_game.py and run_eval.py."""
from __future__ import annotations

import json
import socket
import subprocess
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .client import BridgeClient, BridgeClosed, GameOver
from .logger import GameLogger

GAME_STEAM_URL = "steam://rungameid/874390"


@dataclass
class GameResult:
    outcome: str                     # game_over | max_turns | timeout | closed | stuck | void
    final_turn: int = 0
    won: bool | None = None
    final_score: int | None = None
    scores: list[tuple[int, int]] = field(default_factory=list)   # (turn, score at start of turn)
    actions: int = 0
    rejected: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = 0.0
    game_over: dict[str, Any] | None = None
    winner: int | None = None
    roster: list[dict[str, Any]] | None = None
    seats: dict[int, dict[str, Any]] = field(default_factory=dict)   # player id -> per-seat summary
    void: bool = False               # a tool-use violation happened: played out, not scored

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
    """Leave any game in progress, then start a new one; returns the bridge's new_game reply, extended with
    `first_player` and `roster` from the first state.

    Messages from the old game (a `state` pushed on connect, a `game_over`) are discarded at the menu
    boundary so they cannot be mistaken for the new game's first state, and the first new state is
    checked against the request: mode and opponent count for single-player; game type, map size, human
    and bot counts and tribes for a pass-and-play game (an `ok` only echoes the request)."""
    hello = client.hello or {}
    if hello.get("in_game") or client.status().get("has_game_state"):
        client.send({"type": "return_to_menu"})
        client.expect("ok", "error")
        for _ in range(30):
            time.sleep(1)
            if not client.status().get("has_game_state"):
                break
        time.sleep(settle)
    client.discard("state", "game_over", "left_game")
    client.send({"type": "new_game", **settings})
    reply = client.expect("ok", "error")
    if reply["type"] != "ok":
        raise RuntimeError(f"new_game failed: {reply.get('error')}")
    first = client.wait_until_in_game()
    if first.get("type") == "state":
        got = first["state"]["settings"]
        want_mode = str(settings.get("mode", "")).lower()
        if want_mode and str(got.get("game_mode", "")).lower() != want_mode:
            raise RuntimeError(f"new game is {got.get('game_mode')}, expected {settings.get('mode')}")
        if "opponents" in settings and got.get("opponents") != settings["opponents"]:
            raise RuntimeError(f"new game has {got.get('opponents')} opponents, expected {settings['opponents']}")
        want_type_name = str(settings.get("game_type") or "SinglePlayer")
        want_type = want_type_name.lower()
        if str(got.get("game_type", "")).lower() != want_type:
            raise RuntimeError(f"new game is {got.get('game_type')}, expected {want_type_name}")
        if "map_size" in settings and got.get("map_width") != settings["map_size"]:
            raise RuntimeError(f"new game map is {got.get('map_width')} wide, expected {settings['map_size']}")
        roster = first.get("roster") or []
        if want_type == "passandplay":
            humans = [p for p in roster if not p.get("is_bot")]
            bots = [p for p in roster if p.get("is_bot")]
            if "players" in settings and len(humans) != settings["players"]:
                raise RuntimeError(f"new game has {len(humans)} human seats, expected {settings['players']}")
            if "bots" in settings and len(bots) != settings["bots"]:
                raise RuntimeError(f"new game has {len(bots)} bots, expected {settings['bots']}")
            want_tribes = [str(t).lower() for t in settings.get("tribes") or []]
            got_tribes = [str(p.get("tribe", "")).lower() for p in humans]
            if want_tribes and got_tribes[:len(want_tribes)] != want_tribes:
                raise RuntimeError(f"new game tribes are {got_tribes}, expected {want_tribes}")
        reply = dict(reply, first_player=first.get("player"), roster=roster)
    return reply


# ---------------------------------------------------------------------------- turn planner loop

TRIGGER_KINDS = {"city_reward", "peace_request_response"}
# prefixes, matched against the lower-cased engine name: "pop" covers PopulationGrowth and PopGrowth
REWARD_PRIORITY = ("workshop", "resources", "pop", "super", "border", "citywall", "explorer", "park")
# actions that count against the per-turn action budget (mandatory trigger answers and end turn do not)
BUDGETED_SOURCES = ("plan", "auto-capture")


class _Stuck(Exception):
    """The loop cannot make progress (action result never came, or the bridge keeps rejecting a forced action)."""

    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome = outcome


def choose_reward(legal: list[dict[str, Any]], *, capital_known: bool = True, turn: int = 0) -> int | None:
    """Fixed rush policy for city level-up rewards (no model call). Matches reward names by prefix so
    PopulationGrowth/PopGrowth, SuperUnit etc. all resolve."""
    offers = [(i, str(a.get("reward", "")).lower()) for i, a in enumerate(legal) if a.get("kind") == "city_reward"]
    if not offers:
        return None
    priority = REWARD_PRIORITY
    if not capital_known and turn <= 2:
        # first level-up only: on a small map the Explorer usually reveals villages and the enemy right away
        priority = ("explorer",) + tuple(p for p in REWARD_PRIORITY if p != "explorer")
    for want in priority:
        for i, name in offers:
            if name.startswith(want):
                return i
    return offers[0][0]


def answer_trigger(msg: dict[str, Any]) -> tuple[int | None, str]:
    """Deterministic answer for a pending trigger: (legal index, label). Unknown triggers take the first option."""
    from .observe import enemy_capital

    legal = msg["legal_actions"]
    kinds = {a.get("kind") for a in legal}
    if "city_reward" in kinds:
        idx = choose_reward(legal, capital_known=enemy_capital(msg["state"]) is not None, turn=int(msg.get("turn", 0)))
        return idx, "city reward"
    if "peace_request_response" in kinds:
        idx = next((i for i, a in enumerate(legal) if a.get("kind") == "peace_request_response" and not a.get("accept")), None)
        if idx is None:
            idx = next(i for i, a in enumerate(legal) if a.get("kind") == "peace_request_response")
        return idx, "decline peace"
    return (0 if legal else None), "unknown trigger, first option"


@dataclass
class SeatState:
    """Everything the loop keeps per player: its planner, the plan in progress, and its accounting."""
    player: int
    planner: Any
    steps: deque = field(default_factory=deque)
    turn_log: list[str] = field(default_factory=list)
    failed_auto: dict[tuple, int] = field(default_factory=dict)    # auto actions rejected this turn
    prev_msg: dict[str, Any] | None = None                          # the state the last action was sent from
    turn_actions_total: int = 0
    turn_actions_budgeted: int = 0
    turn_calls: int = 0
    turn_latency: float = 0.0
    turn_cost: float | None = 0.0
    turn_t0: float = 0.0
    turns: int = 0
    scores: list[tuple[int, int]] = field(default_factory=list)
    final_score: int | None = None
    actions: int = 0
    rejected: int = 0
    violations: int = 0
    won: bool | None = None
    ended_key: tuple[int, int] | None = None     # (turn, player) whose end turn was accepted
    stale_after_end: int = 0                     # states seen for that same seat-turn since

    @property
    def name(self) -> str:
        return str(getattr(self.planner, "name", f"player {self.player}"))

    def begin_turn(self) -> None:
        self.turn_actions_total = self.turn_actions_budgeted = self.turn_calls = 0
        self.turn_latency = 0.0
        self.turn_cost = 0.0
        self.turn_t0 = time.monotonic()
        self.turns += 1
        self.steps.clear()
        self.turn_log = []
        self.failed_auto.clear()
        self.ended_key = None
        self.stale_after_end = 0

    def summary(self) -> dict[str, Any]:
        cost = self.planner.cost()
        return {"player": self.player, "planner": self.name, "model": getattr(self.planner, "model", None),
                "won": self.won, "turns": self.turns, "calls": getattr(self.planner, "calls", None),
                "actions": self.actions, "rejected": self.rejected, "violations": self.violations,
                "usage": dict(getattr(self.planner, "total_usage", {}) or {}),
                "cost_usd": None if cost is None else round(cost, 4),
                "final_score": self.final_score, "scores": list(self.scores)}


def play_turns(bridge: BridgeClient, planner, log: GameLogger, console, *, max_turns: int = 0,
               max_calls_per_turn: int = 3, max_actions_per_turn: int = 60, state_timeout: float = 900,
               sweep_captures: bool = True, turn_settle: float | None = 1.5) -> GameResult:
    """Drive the game with one planning call per turn (plus bounded re-plans). See planner.py for the
    plan/step conventions. Never raises; see GameResult.outcome.

    `planner` is one planner (single-player: whichever seat the bridge serves) or a mapping
    {player id: planner} for a pass-and-play game where each state's `player` picks the seat. Every seat
    gets the same budgets: at most `max_calls_per_turn` model calls per turn (retries included) and
    `max_actions_per_turn` budgeted actions (planned steps and capture sweeps; mandatory trigger answers
    and the final end turn always run). A tool-use violation reported by a planner voids the game.

    `turn_settle`: the bridge can push the first state of a turn before the engine has applied income and
    population (game 2 planned turns 1 and 10 believing it had 1 star). When set, the runner waits that many
    seconds at each seat-turn start, asks for a fresh state and plans from it. None disables the refresh."""
    from .console import describe
    from .observe import render_map, summarize_change
    from .planner import action_key, add_cost, depends_on, end_turn_index, locate

    mapping = isinstance(planner, Mapping)
    res = GameResult("closed")
    seats: dict[int, SeatState] = {}
    names: dict[int, str] = {pid: str(getattr(p, "name", f"player {pid}")) for pid, p in planner.items()} if mapping else {}
    last_key: tuple[int, int] | None = None
    last_seat: SeatState | None = None
    cur: SeatState | None = None
    reuse: dict[str, Any] | None = None
    empty_states = 0

    def pid_of(msg: dict[str, Any]) -> int:
        return int(msg.get("player", msg["state"]["me"]["id"]))

    def seat_for(pid: int) -> SeatState:
        if pid in seats:
            return seats[pid]
        if mapping:
            if pid not in planner:
                raise _Stuck("stuck", f"state for unexpected player {pid} (seats: {sorted(planner)})")
            seats[pid] = SeatState(pid, planner[pid])
        else:
            if seats:
                return next(iter(seats.values()))     # single-planner mode: one seat, whatever the bridge says
            seats[pid] = SeatState(pid, planner)
        return seats[pid]

    def other_name(seat: SeatState) -> str | None:
        if not mapping:
            return None
        others = [n for p, n in names.items() if p != seat.player]
        return ", ".join(others) if others else None

    def act(turn: int, action: dict[str, Any], source: str) -> dict[str, Any]:
        assert cur is not None
        t0 = time.monotonic()
        try:
            result = bridge.act(action, player=cur.player) if mapping else bridge.act(action)
        except socket.timeout:
            # the connection's buffered reader is unusable after a timeout; stop rather than desync
            raise _Stuck("timeout", f"no result for {describe(action)} from the bridge in time") from None
        dt = time.monotonic() - t0
        log.log("decision", turn=turn, player=cur.player, planner=cur.name, source=source, action=action)
        log.log("result", turn=turn, player=cur.player, **result)
        cur.turn_actions_total += 1
        if source in BUDGETED_SOURCES and action.get("kind") != "end_turn":
            cur.turn_actions_budgeted += 1
        cur.actions += 1
        res.actions += 1
        if not result.get("ok"):
            cur.rejected += 1
            res.rejected += 1
            if "wrong seat" in str(result.get("error", "")).lower():
                raise _Stuck("stuck", f"the bridge and the harness disagree about the seat: {result.get('error')}")
        elif action.get("kind") == "end_turn" and cur.ended_key != (turn, cur.player):
            cur.ended_key = (turn, cur.player)
            cur.stale_after_end = 0
        console.step(action, result, dt, source)
        cur.turn_log.append(f"{describe(action)} -> {'ok' if result.get('ok') else 'REJECTED: ' + str(result.get('error'))}")
        return result

    def drop_dependents(failed: dict[str, Any]) -> None:
        assert cur is not None
        kept = [s for s in cur.steps if not depends_on(s, failed)]
        dropped = len(cur.steps) - len(kept)
        cur.steps.clear()
        cur.steps.extend(kept)
        if dropped:
            console.note(f"dropped {dropped} later step(s) that used the same unit")
            cur.turn_log.append(f"(dropped {dropped} planned step(s) that depended on it)")

    def leftover_capture(legal: list[dict[str, Any]]) -> dict[str, Any] | None:
        assert cur is not None
        if not sweep_captures or cur.turn_actions_budgeted >= max_actions_per_turn:
            return None
        return next((a for a in legal if a.get("kind") == "capture" and action_key(a) not in cur.failed_auto), None)

    def auto(turn: int, action: dict[str, Any], source: str, *, mandatory: bool) -> None:
        """Send a runner-chosen action; remember rejections so the same one is not retried forever."""
        assert cur is not None
        result = act(turn, action, source)
        if not result.get("ok"):
            key = action_key(action)
            cur.failed_auto[key] = cur.failed_auto.get(key, 0) + 1
            if mandatory and cur.failed_auto[key] >= 2:
                raise _Stuck("stuck", f"the bridge keeps rejecting {describe(action)}: {result.get('error')}")

    def finish_turn(turn: int, legal: list[dict[str, Any]]) -> None:
        assert cur is not None
        cur.steps.clear()
        cap = leftover_capture(legal)
        if cap is not None:
            auto(turn, cap, "auto-capture", mandatory=False)
            return
        end = end_turn_index(legal)
        if end is None:
            console.warn("no end-turn action available; taking the first legal action")
            auto(turn, legal[0], "fallback", mandatory=True)
        else:
            auto(turn, legal[end], "end turn", mandatory=True)

    def footer(seat: SeatState, turn: int) -> None:
        console.turn_footer(turn, seat.turn_actions_total, seat.turn_calls, seat.turn_latency,
                            time.monotonic() - seat.turn_t0, seat.turn_cost, seat.planner.cost(),
                            who=seat.name if mapping else None, violations=seat.violations)

    try:
        while True:
            if reuse is not None:
                msg, reuse = reuse, None
            else:
                try:
                    msg = bridge.wait_for_state(timeout=state_timeout)
                except socket.timeout:
                    console.warn(f"no state for {state_timeout:.0f}s; giving up")
                    log.log("timeout")
                    res.outcome = "timeout"
                    break
                newest = bridge.drain_stale_states()
                if newest is not None:
                    msg = newest
                if (msg["turn"], pid_of(msg)) != last_key and turn_settle is not None:
                    # seat-turn start: let income/population land, then plan from a settled state
                    time.sleep(turn_settle)
                    bridge.request_state()
                    try:
                        settled = bridge.wait_for_state(timeout=15)
                    except socket.timeout:
                        # the buffered reader is unusable after a timeout; stop rather than desync
                        raise _Stuck("timeout", "no settled state arrived after the turn-start refresh") from None
                    latest = bridge.drain_stale_states()
                    msg = latest if latest is not None else settled
                cur = seat_for(pid_of(msg))
                if cur.prev_msg is not None and msg["turn"] == cur.prev_msg["turn"]:
                    # what the last action actually did, now that the engine has processed it
                    outcome = summarize_change(cur.prev_msg["state"], msg["state"])
                    if outcome:
                        console.outcome(outcome)
                        if cur.turn_log:
                            cur.turn_log[-1] += f" => {outcome}"
                elif cur.prev_msg is not None:
                    console.enemy_turn(summarize_change(cur.prev_msg["state"], msg["state"], enemy_turn=True),
                                       who=other_name(cur))
                cur.prev_msg = msg
            assert cur is not None

            turn = msg["turn"]
            res.final_turn = turn
            key = (turn, cur.player)
            if cur.ended_key == key:
                # this seat-turn was already ended: the engine has not moved on yet (or the bridge re-sent
                # the state). Never plan on it again; wait for the next state, nudge once, then give up.
                legal_now = msg["legal_actions"]
                if msg["state"].get("pending_trigger") or (legal_now and all(a.get("kind") in TRIGGER_KINDS for a in legal_now)):
                    # a level-up registered as the turn ended (a harvest just before end turn): the engine
                    # holds the end turn until the reward is chosen. Answer it, then end the turn again.
                    idx, label = answer_trigger(msg)
                    if idx is None:
                        raise _Stuck("stuck", "pending trigger with no legal answer")
                    auto(turn, legal_now[idx], label, mandatory=True)
                    cur.ended_key = None
                    cur.steps.clear()
                    cur.steps.append({"kind": "end_turn"})
                    continue
                cur.stale_after_end += 1
                if cur.stale_after_end >= 6:
                    raise _Stuck("stuck", f"the game did not advance after {cur.name} ended turn {turn}")
                if cur.stale_after_end == 3:
                    end = end_turn_index(msg["legal_actions"])
                    if end is not None:
                        console.note("still the same seat-turn after end turn; sending end turn once more")
                        act(turn, msg["legal_actions"][end], "end turn")
                        continue
                console.note("state for a seat-turn that already ended; waiting for the next one")
                continue
            if key != last_key:
                if last_key is not None and last_seat is not None:
                    footer(last_seat, last_key[0])
                me = msg["state"]["me"]
                cur.scores.append((turn, me["score"]))
                cur.final_score = me["score"]
                log.log("turn", turn=turn, player=cur.player, planner=cur.name, score=me["score"], stars=me["stars"],
                        income=me["income"],
                        cities=len([c for c in msg["state"]["cities"] if c["owner"] == me["id"]]),
                        units=len([u for u in msg["state"]["units"] if u["owner"] == me["id"]]))
                if max_turns and turn > max_turns:
                    console.note(f"reached max_turns {max_turns}")
                    res.outcome = "max_turns"
                    break
                last_key = key
                last_seat = cur
                cur.begin_turn()
                console.turn_header(msg, who=cur.name if mapping else None)
                console.map(render_map(msg))

            legal = msg["legal_actions"]
            st = msg["state"]
            if not legal:
                # the bridge only pushes a state when something changed, so waiting passively could hang
                empty_states += 1
                if empty_states > 3:
                    raise _Stuck("stuck", "the bridge keeps sending states with no legal actions")
                console.warn("state has no legal actions; asking the bridge for a fresh one")
                time.sleep(2)
                bridge.request_state()
                continue
            empty_states = 0

            # 1. pending trigger (city reward, peace request): deterministic, no model call, not budgeted
            if st.get("pending_trigger") or all(a.get("kind") in TRIGGER_KINDS for a in legal):
                idx, label = answer_trigger(msg)
                if idx is None:
                    raise _Stuck("stuck", "pending trigger with no legal answer")
                auto(turn, legal[idx], label, mandatory=True)
                continue

            # 2. need a plan?
            if not cur.steps:
                if cur.turn_calls >= max_calls_per_turn or cur.turn_actions_budgeted >= max_actions_per_turn:
                    console.note("call/action budget for this turn is used up; ending the turn")
                    finish_turn(turn, legal)
                    continue
                log.log("state", turn=turn, player=cur.player, state=st, legal_actions=legal)
                console.plan_start(cur.turn_calls + 1, max_calls_per_turn)
                remaining = max_calls_per_turn - cur.turn_calls
                p = cur.planner.plan(msg, cur.turn_log, max_attempts=min(2, remaining), calls_left=remaining)
                cur.turn_calls += max(1, p.attempts)
                cur.turn_latency += p.latency
                cur.turn_cost = add_cost(cur.turn_cost, p.cost)
                bad = int((p.meta or {}).get("violations") or 0)
                if bad:
                    cur.violations += bad
                    res.void = True
                    console.warn(f"{cur.name} used tools {bad} time(s) during planning: the game is VOID (played out, not scored)")
                log.log("plan", turn=turn, player=cur.player, planner=cur.name, attempts=p.attempts, commentary=p.commentary,
                        actions=[brief(s) for s in p.steps], problems=p.problems, notes=p.notes,
                        usage=p.usage, latency=round(p.latency, 2), cost=p.cost, error=p.error, meta=p.meta)
                console.plan(p, streamed=bool((p.meta or {}).get("streamed", getattr(cur.planner, "on_commentary", None) is not None)))
                if not p.steps:
                    finish_turn(turn, legal)
                    continue
                cur.steps.extend(p.steps)

            # 3. execute the next step against the current state
            step = cur.steps[0]
            if step.get("kind") == "end_turn":
                cap = leftover_capture(legal)
                if cap is not None:
                    auto(turn, cap, "auto-capture", mandatory=False)
                    continue
            elif cur.turn_actions_budgeted >= max_actions_per_turn:
                console.note(f"action cap {max_actions_per_turn} reached mid-plan; ending the turn")
                finish_turn(turn, legal)
                continue
            cur.steps.popleft()
            idx, why = locate(step, msg)
            if idx is None:
                console.skipped(step, why)
                cur.turn_log.append(f"SKIPPED {describe(step)} ({why})")
                drop_dependents(step)
                reuse = msg          # nothing was sent, so no new state is coming
                continue
            result = act(turn, legal[idx], "plan")
            if not result.get("ok"):
                if "pending command trigger" in str(result.get("error", "")).lower() and step.get("_retried") is None:
                    # a level-up reward registered after the state we planned from; answer it, then retry this step
                    step["_retried"] = True
                    cur.steps.appendleft(step)
                    console.note("a city reward is pending; will retry that step after answering it")
                else:
                    drop_dependents(step)
            if step.get("kind") == "end_turn" and result.get("ok"):
                cur.steps.clear()
    except GameOver as g:
        m = g.message
        res.outcome = "game_over"
        res.final_turn = m["turn"]
        res.game_over = m
        res.winner = m.get("winner")
        res.roster = m.get("roster")
        for s in seats.values():
            s.won = (res.winner == s.player) if mapping else bool(m.get("won"))
        res.won = next(iter(seats.values())).won if seats else bool(m.get("won"))
        res.final_score = m.get("score")
        if last_key is not None and last_seat is not None:
            footer(last_seat, last_key[0])
        console.game_over(m, names=names if mapping else None)
        log.log("game_over", **m)
    except BridgeClosed as ex:
        console.warn(f"bridge closed: {ex}")
        log.log("bridge_closed", reason=str(ex))
        res.outcome = "closed"
    except _Stuck as ex:
        console.warn(f"stopping: {ex}")
        log.log(ex.outcome, reason=str(ex))
        res.outcome = ex.outcome
        try:
            bridge.close()
        except Exception:
            pass
    finally:
        if res.void and res.outcome in ("game_over", "max_turns"):
            res.outcome = "void"
        first = next(iter(seats.values()), None)
        if first is not None:
            res.scores = list(first.scores)
            res.final_score = first.final_score if res.final_score is None or mapping else res.final_score
            res.usage = dict(getattr(first.planner, "total_usage", {}) or {})
            c = first.planner.cost()
            res.cost_usd = None if c is None else round(c, 4)
        res.seats = {s.player: s.summary() for s in seats.values()}
        log.log("summary", outcome=res.outcome, final_turn=res.final_turn, won=res.won, final_score=res.final_score,
                scores=res.scores, actions=res.actions, rejected=res.rejected, usage=res.usage, cost_usd=res.cost_usd,
                calls=getattr(first.planner, "calls", None) if first is not None else None,
                winner=res.winner, void=res.void, seats=list(res.seats.values()))
        for s in seats.values():
            tag = f"{s.name}: " if mapping else ""
            console.note(f"{tag}scores by turn: " + " ".join(f"{t}:{sc}" for t, sc in s.scores))
            usage = getattr(s.planner, "total_usage", None)
            if usage:
                from .planner import fmt_cost
                console.note(f"{tag}tokens: {dict(usage)}  model calls: {getattr(s.planner, 'calls', '?')}  "
                             f"est. cost {fmt_cost(s.planner.cost())}"
                             + (f"  tool-use violations: {s.violations}" if s.violations else ""))
    return res
