"""play_turns() against a scripted bridge and planner (no game, no CLI)."""
import copy
import io
import json
from collections import deque
from pathlib import Path

from polytopia_bridge.client import GameOver
from polytopia_bridge.console import Console
from polytopia_bridge.logger import GameLogger
from polytopia_bridge.planner import Plan
from polytopia_bridge.runner import answer_trigger, choose_reward, play_turns

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeBridge:
    """wait_for_state pops the next scripted message; act records what was sent."""

    def __init__(self, states):
        self.states = deque(states)
        self.sent = []
        self.waits = 0

    def wait_for_state(self, timeout=None):
        self.waits += 1
        if not self.states:
            raise GameOver(load("game_over.json"))
        m = self.states.popleft()
        if m.get("type") == "game_over":
            raise GameOver(m)
        return m

    def drain_stale_states(self):
        return None

    def request_state(self):
        self.requested = getattr(self, "requested", 0) + 1

    def close(self):
        self.closed = True

    def act(self, action, timeout=None, player=None):
        self.sent.append(action)
        self.sent_players = getattr(self, "sent_players", []) + [player]
        reject = getattr(self, "reject", None)
        if reject and reject(action):
            return {"ok": False, "error": getattr(self, "reject_error", "nope"), "kind": action["kind"]}
        if getattr(self, "hang", False):
            import socket
            raise socket.timeout("no result")
        return {"ok": True, "error": None, "kind": action["kind"]}


class ScriptedPlanner:
    def __init__(self, plans):
        self.plans = deque(plans)
        self.calls = 0
        self.total_usage = {}
        self.budgets = []
        self.on_commentary = None

    def plan(self, msg, turn_log=None, *, max_attempts=2, calls_left=None):
        self.calls += 1
        self.budgets.append(max_attempts)
        self.calls_left = calls_left
        steps = self.plans.popleft() if self.plans else []
        return Plan("c", "n", [copy.deepcopy(s) for s in steps], attempts=1)

    def cost(self):
        return 0.0


def run(states, plans, tmp_path, **kw):
    kw.setdefault("turn_settle", None)      # tests script exact state sequences; no turn-start refresh
    bridge = FakeBridge(states)
    planner = ScriptedPlanner(plans)
    out = io.StringIO()
    console = Console(color=False, stream=out)
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, planner, log, console, **kw)
    return bridge, planner, res, out.getvalue()


def test_turn_start_refresh_plans_from_the_settled_state(tmp_path):
    m = midgame()
    stale = copy.deepcopy(m)
    stale["state"]["me"]["stars"] = 1
    settled = midgame()                      # the real treasury after income landed
    end = legal_of("end_turn", m)
    bridge, planner, res, out = run([stale, settled], [[end]], tmp_path, turn_settle=0)
    assert bridge.requested == 1
    assert f"{settled['state']['me']['stars']} stars" in out and " 1 stars" not in out


def midgame():
    return load("state_midgame.json")


def legal_of(kind, msg, **match):
    return next(a for a in msg["legal_actions"] if a["kind"] == kind and all(a.get(k) == v for k, v in match.items()))


def test_city_reward_is_answered_without_a_model_call(tmp_path):
    reward = load("state_city_reward.json")
    bridge, planner, res, out = run([reward], [], tmp_path)
    assert planner.calls == 0
    assert bridge.sent[0]["kind"] == "city_reward" and bridge.sent[0]["reward"] == "Resources"
    assert res.outcome == "game_over" and res.won is False and res.final_turn == 19
    assert "auto" in out or "[city reward]" in out


def test_choose_reward_policy():
    offers = [{"kind": "city_reward", "reward": r} for r in ("Workshop", "Explorer")]
    assert offers[choose_reward(offers)]["reward"] == "Workshop"
    assert offers[choose_reward(offers, capital_known=False, turn=1)]["reward"] == "Explorer"
    assert offers[choose_reward(offers, capital_known=False, turn=3)]["reward"] == "Workshop"
    offers = [{"kind": "city_reward", "reward": r} for r in ("Park", "SuperUnit")]
    assert offers[choose_reward(offers)]["reward"] == "SuperUnit"
    offers = [{"kind": "city_reward", "reward": r} for r in ("PopulationGrowth", "BorderGrowth")]
    assert offers[choose_reward(offers)]["reward"] == "PopulationGrowth"
    assert choose_reward([{"kind": "end_turn"}]) is None


def test_peace_is_declined():
    msg = {"turn": 5, "state": {"me": {"id": 1}, "cities": [], "pending_trigger": {"type": "PeaceRequest"}},
           "legal_actions": [{"kind": "peace_request_response", "opponent": 2, "accept": True},
                             {"kind": "peace_request_response", "opponent": 2, "accept": False}]}
    idx, label = answer_trigger(msg)
    assert idx == 1 and "peace" in label


def test_skipped_step_consumes_no_state_and_drops_same_unit_steps(tmp_path):
    m = midgame()
    move = legal_of("move", m)
    bad_move = dict(move, to=[99, 99])
    attack_same_unit = {"kind": "attack", "unit_id": move["unit_id"], "target": [1, 1], "target_unit_id": 77}
    research = legal_of("research", m)
    end = legal_of("end_turn", m)
    # one state per act: research, end_turn -> then game over
    bridge, planner, res, out = run([m, midgame()], [[bad_move, attack_same_unit, research, end]], tmp_path)
    assert [a["kind"] for a in bridge.sent] == ["research", "end_turn"]
    assert bridge.waits == 3            # initial + after each of the 2 acts (skip read nothing)
    assert planner.calls == 1
    assert "skipped" in out and "dropped 1 later step" in out


def test_plan_without_end_turn_asks_again(tmp_path):
    m = midgame()
    research = legal_of("research", m)
    end = legal_of("end_turn", m)
    # one state per act: initial + after research; after end_turn the bridge reports game over
    bridge, planner, res, out = run([m, midgame()], [[research], [end]], tmp_path)
    assert planner.calls == 2
    assert [a["kind"] for a in bridge.sent] == ["research", "end_turn"]
    assert planner.budgets == [2, 2]     # 3-call budget: first call may retry once, second too
    assert planner.calls_left == 2       # the second call was told 2 calls remained


def test_budget_exhausted_runner_ends_the_turn(tmp_path):
    m = midgame()
    research = legal_of("research", m)
    bridge, planner, res, out = run([m, midgame()], [[research], [research]], tmp_path, max_calls_per_turn=1)
    assert planner.calls == 1 and planner.budgets == [1]
    assert [a["kind"] for a in bridge.sent] == ["research", "end_turn"]
    assert "budget" in out


def test_leftover_capture_is_swept_before_end_turn(tmp_path):
    m = midgame()
    cap = {"kind": "capture", "unit_id": 5, "at": [3, 3]}
    with_capture = copy.deepcopy(m)
    with_capture["legal_actions"].append(cap)
    end = legal_of("end_turn", m)
    bridge, planner, res, out = run([with_capture, midgame()], [[end]], tmp_path)
    assert [a["kind"] for a in bridge.sent] == ["capture", "end_turn"]
    assert "auto-capture" in out


def test_capture_not_swept_when_disabled(tmp_path):
    m = midgame()
    with_capture = copy.deepcopy(m)
    with_capture["legal_actions"].append({"kind": "capture", "unit_id": 5, "at": [3, 3]})
    end = legal_of("end_turn", m)
    bridge, planner, res, out = run([with_capture], [[end]], tmp_path, sweep_captures=False)
    assert [a["kind"] for a in bridge.sent] == ["end_turn"]


def test_turn_change_resets_plan_and_logs_scores(tmp_path):
    m = midgame()
    research = legal_of("research", m)
    end = legal_of("end_turn", m)
    t2 = copy.deepcopy(m)
    t2["turn"] = m["turn"] + 1
    t2["state"]["turn"] = t2["turn"]
    bridge, planner, res, out = run([m, midgame(), t2], [[research, end], [end]], tmp_path)
    assert [a["kind"] for a in bridge.sent] == ["research", "end_turn", "end_turn"]
    assert [t for t, _ in res.scores] == [m["turn"], t2["turn"]]
    assert f"TURN {t2['turn']}" in out and "--- turn" in out


def test_pop_growth_aliases_both_match():
    for names in (("PopGrowth", "BorderGrowth"), ("BorderGrowth", "PopulationGrowth")):
        offers = [{"kind": "city_reward", "reward": r} for r in names]
        assert offers[choose_reward(offers)]["reward"].startswith("Pop")


def test_action_cap_cuts_a_long_plan(tmp_path):
    m = midgame()
    research = legal_of("research", m)
    build = legal_of("build", m)
    end = legal_of("end_turn", m)
    # cap 2: research, build, then the runner ends the turn instead of the third planned step
    bridge, planner, res, out = run([m, midgame(), midgame()], [[research, build, research, end]], tmp_path,
                                    max_actions_per_turn=2)
    assert [a["kind"] for a in bridge.sent] == ["research", "build", "end_turn"]
    assert "action cap" in out


def test_rejected_capture_is_not_retried(tmp_path):
    m = midgame()
    with_capture = copy.deepcopy(m)
    cap = {"kind": "capture", "unit_id": 5, "at": [3, 3]}
    with_capture["legal_actions"].append(cap)
    end = legal_of("end_turn", m)
    bridge = FakeBridge([with_capture, copy.deepcopy(with_capture)])
    bridge.reject = lambda a: a["kind"] == "capture"
    planner = ScriptedPlanner([[end]])
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, planner, log, Console(color=False, stream=out), turn_settle=None)
    assert [a["kind"] for a in bridge.sent] == ["capture", "end_turn"]
    assert res.rejected == 1


def test_trigger_rejected_twice_stops_the_run(tmp_path):
    reward = load("state_city_reward.json")
    bridge = FakeBridge([reward, copy.deepcopy(reward), copy.deepcopy(reward)])
    bridge.reject = lambda a: True
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, ScriptedPlanner([]), log, Console(color=False, stream=out), turn_settle=None)
    assert res.outcome == "stuck" and len(bridge.sent) == 2 and getattr(bridge, "closed", False)


def test_action_result_timeout_ends_the_run(tmp_path):
    m = midgame()
    end = legal_of("end_turn", m)
    bridge = FakeBridge([m])
    bridge.hang = True
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, ScriptedPlanner([[end]]), log, Console(color=False, stream=out), turn_settle=None)
    assert res.outcome == "timeout" and "no result" in out.getvalue()


def test_empty_legal_list_asks_for_a_fresh_state_then_gives_up(tmp_path):
    m = midgame()
    empty = copy.deepcopy(m)
    empty["legal_actions"] = []
    bridge, planner, res, out = run([empty] + [copy.deepcopy(empty) for _ in range(4)], [], tmp_path)
    assert res.outcome == "stuck" and bridge.requested == 3 and bridge.sent == []


def test_step_rejected_by_late_trigger_is_retried_after_the_reward(tmp_path):
    m = midgame()
    move = legal_of("move", m)
    end = legal_of("end_turn", m)
    reward = load("state_city_reward.json")
    reward["turn"] = m["turn"]
    # move rejected (trigger appeared) -> reward state -> answer -> same state again -> move ok -> end
    bridge = FakeBridge([m, reward, midgame(), midgame()])
    seen = {"n": 0}

    def reject_first_move(a):
        if a["kind"] == "move":
            seen["n"] += 1
            return seen["n"] == 1
        return False

    bridge.reject = reject_first_move
    bridge.reject_error = "Pending command trigger exists"
    planner = ScriptedPlanner([[move, end]])
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        play_turns(bridge, planner, log, Console(color=False, stream=out), turn_settle=None)
    assert [a["kind"] for a in bridge.sent] == ["move", "city_reward", "move", "end_turn"]
    assert planner.calls == 1


def test_outcome_and_enemy_turn_summaries_are_printed(tmp_path):
    m = midgame()
    research = legal_of("research", m)
    end = legal_of("end_turn", m)
    after = copy.deepcopy(m)
    after["state"]["me"]["stars"] -= research["cost"]
    after["state"]["me"]["techs"].append(research["tech"])
    t2 = copy.deepcopy(after)
    t2["turn"] += 1
    t2["state"]["turn"] = t2["turn"]
    me = t2["state"]["me"]["id"]
    t2["state"]["units"] = [u for u in t2["state"]["units"] if u["owner"] == me][:1]
    bridge, planner, res, out = run([m, after, t2], [[research, end], [end]], tmp_path)
    assert f"=> stars {m['state']['me']['stars']}->{after['state']['me']['stars']}; learned {research['tech']}" in out
    assert "ENEMY TURN:" in out and ("lost " in out or " gone" in out)


def test_end_turn_rejected_by_late_trigger_is_retried(tmp_path):
    m = midgame()
    end = legal_of("end_turn", m)
    reward = load("state_city_reward.json")
    reward["turn"] = m["turn"]
    bridge = FakeBridge([m, reward, midgame()])
    seen = {"n": 0}

    def reject_first_end(a):
        if a["kind"] == "end_turn":
            seen["n"] += 1
            return seen["n"] == 1
        return False

    bridge.reject = reject_first_end
    bridge.reject_error = "Pending command trigger exists"
    planner = ScriptedPlanner([[end]])
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        play_turns(bridge, planner, log, Console(color=False, stream=out), turn_settle=None)
    assert [a["kind"] for a in bridge.sent] == ["end_turn", "city_reward", "end_turn"]
    assert planner.calls == 1


def test_max_turns_stops(tmp_path):
    m = midgame()
    bridge, planner, res, out = run([m], [], tmp_path, max_turns=m["turn"] - 1)
    assert res.outcome == "max_turns" and bridge.sent == [] and planner.calls == 0
