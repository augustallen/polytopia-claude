"""play_turns() with two seats (pass and play) over states recorded from the real bridge."""
import copy
import io
import json
import socket

from polytopia_bridge.console import Console
from polytopia_bridge.logger import GameLogger
from polytopia_bridge.runner import play_turns
from test_turn_runner import FakeBridge, ScriptedPlanner, legal_of, load, midgame, run


class NamedPlanner(ScriptedPlanner):
    def __init__(self, name, plans, cost=0.0, violations=0):
        super().__init__(plans)
        self.name = name
        self.model = name
        self._cost = cost
        self._violations = violations
        self.seen = []

    def plan(self, msg, turn_log=None, *, max_attempts=2, calls_left=None):
        p = super().plan(msg, turn_log, max_attempts=max_attempts, calls_left=calls_left)
        p.cost = self._cost
        p.meta = {"streamed": False, "violations": self._violations, "backend": "test"}
        self.seen.append(msg)
        return p

    def cost(self):
        return self._cost


def hotseat(name):
    return load(f"state_hotseat_{name}.json")


def run2(states, p1, p2, tmp_path, **kw):
    kw.setdefault("turn_settle", None)
    bridge = FakeBridge(states)
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, {1: p1, 2: p2}, log, Console(color=False, stream=out), **kw)
    records = [json.loads(line) for line in (tmp_path / "g.jsonl").read_text(encoding="utf-8").splitlines()]
    return bridge, res, out.getvalue(), records


def test_two_seats_each_get_their_own_planner_and_summaries(tmp_path):
    t0p1, t0p2, t1p1 = hotseat("t0_p1"), hotseat("t0_p2"), hotseat("t1_p1")
    sp1 = NamedPlanner("claude-a", [[legal_of("end_turn", t0p1)], [legal_of("end_turn", t1p1)]])
    sp2 = NamedPlanner("codex-b", [[legal_of("end_turn", t0p2)]], cost=None)
    bridge, res, out, records = run2([t0p1, t0p2, t1p1], sp1, sp2, tmp_path)
    assert sp1.calls == 2 and sp2.calls == 1
    assert bridge.sent_players == [1, 2, 1]
    assert [m["player"] for m in sp1.seen] == [1, 1] and [m["player"] for m in sp2.seen] == [2]
    # game_over.json says winner 2 -> codex-b won, claude-a lost
    assert res.outcome == "game_over" and res.winner == 2
    assert res.seats[1]["won"] is False and res.seats[2]["won"] is True
    assert res.seats[1]["planner"] == "claude-a" and res.seats[2]["cost_usd"] is None
    assert "WINNER codex-b (player 2)" in out
    assert "claude-a as Imperius (player 1)" in out and "codex-b as Imperius (player 2)" in out
    assert "codex-b moved:" in out               # seat 1 saw what happened between its two turns
    assert "n/a (subscription)" in out           # the codex seat's cost
    for r in records:
        if r["event"] in ("turn", "state", "plan", "decision", "result"):
            assert r["player"] in (1, 2)
    summary = next(r for r in records if r["event"] == "summary")
    assert {s["player"] for s in summary["seats"]} == {1, 2} and summary["winner"] == 2


def test_seat_change_triggers_the_settle_refresh(tmp_path):
    t0p1, t0p2 = hotseat("t0_p1"), hotseat("t0_p2")
    sp1 = NamedPlanner("a", [[legal_of("end_turn", t0p1)]])
    sp2 = NamedPlanner("b", [[legal_of("end_turn", t0p2)]])
    bridge, res, out, _ = run2([t0p1, copy.deepcopy(t0p1), t0p2, copy.deepcopy(t0p2)], sp1, sp2, tmp_path, turn_settle=0)
    assert bridge.requested == 2                 # once per seat-turn, although the turn number did not change
    assert bridge.sent_players == [1, 2]


def test_footer_belongs_to_the_outgoing_seat(tmp_path):
    t0p1, t0p2, t1p1 = hotseat("t0_p1"), hotseat("t0_p2"), hotseat("t1_p1")
    sp1 = NamedPlanner("first", [[legal_of("end_turn", t0p1)], [legal_of("end_turn", t1p1)]], cost=0.5)
    sp2 = NamedPlanner("second", [[legal_of("end_turn", t0p2)]], cost=0.25)
    _, res, out, _ = run2([t0p1, t0p2, t1p1], sp1, sp2, tmp_path)
    footers = [line for line in out.splitlines() if line.startswith("--- turn")]
    assert [f.split("(")[1].split(")")[0] for f in footers] == ["first", "second", "first"]
    assert "$0.50" in footers[0] and "$0.25" in footers[1]


def test_unexpected_player_is_stuck(tmp_path):
    bridge = FakeBridge([hotseat("t0_p2")])
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, {1: NamedPlanner("only", [])}, log, Console(color=False, stream=out), turn_settle=None)
    assert res.outcome == "stuck" and "unexpected player 2" in out.getvalue() and bridge.sent == []


def test_wrong_seat_rejection_is_stuck(tmp_path):
    t0p1 = hotseat("t0_p1")
    bridge = FakeBridge([t0p1, copy.deepcopy(t0p1)])
    bridge.reject = lambda a: True
    bridge.reject_error = "wrong seat: local player is 2, not 1"
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, {1: NamedPlanner("a", [[legal_of("end_turn", t0p1)]]), 2: NamedPlanner("b", [])},
                         log, Console(color=False, stream=out), turn_settle=None)
    assert res.outcome == "stuck" and len(bridge.sent) == 1 and getattr(bridge, "closed", False)


def test_settle_timeout_stops_the_run(tmp_path):
    class HangingBridge(FakeBridge):
        def wait_for_state(self, timeout=None):
            if self.waits >= 1:
                raise socket.timeout("nothing")
            return super().wait_for_state(timeout)

    t0p1 = hotseat("t0_p1")
    bridge = HangingBridge([t0p1])
    out = io.StringIO()
    with GameLogger(tmp_path / "g.jsonl") as log:
        res = play_turns(bridge, NamedPlanner("a", [[legal_of("end_turn", t0p1)]]), log,
                         Console(color=False, stream=out), turn_settle=0)
    assert res.outcome == "timeout" and getattr(bridge, "closed", False) and bridge.sent == []


def test_tool_use_violation_voids_the_game_but_plays_on(tmp_path):
    t0p1, t0p2, t1p1 = hotseat("t0_p1"), hotseat("t0_p2"), hotseat("t1_p1")
    sp1 = NamedPlanner("a", [[legal_of("end_turn", t0p1)], [legal_of("end_turn", t1p1)]])
    sp2 = NamedPlanner("b", [[legal_of("end_turn", t0p2)]], violations=1)
    bridge, res, out, records = run2([t0p1, t0p2, t1p1], sp1, sp2, tmp_path)
    assert res.void and res.outcome == "void" and res.winner == 2
    assert [a["kind"] for a in bridge.sent] == ["end_turn"] * 3      # played out to the end
    assert "VOID" in out and res.seats[2]["violations"] == 1 and res.seats[1]["violations"] == 0
    assert next(r for r in records if r["event"] == "summary")["void"] is True


def test_trigger_answers_are_not_budgeted_but_captures_are(tmp_path):
    reward = load("state_city_reward.json")
    m = midgame()
    reward["turn"] = m["turn"]
    with_capture = copy.deepcopy(m)
    with_capture["legal_actions"].append({"kind": "capture", "unit_id": 5, "at": [3, 3]})
    research, build, end = legal_of("research", m), legal_of("build", m), legal_of("end_turn", m)
    # cap 1: the reward answer is free; research uses the budget; build is cut; the capture is not swept at the cap
    bridge, planner, res, out = run([reward, with_capture, copy.deepcopy(with_capture)], [[research, build, end]], tmp_path,
                                    max_actions_per_turn=1)
    assert [a["kind"] for a in bridge.sent] == ["city_reward", "research", "end_turn"]


def test_single_planner_mode_is_unchanged_with_seat_fixtures(tmp_path):
    t0p1 = hotseat("t0_p1")
    bridge, planner, res, out = run([t0p1], [[legal_of("end_turn", t0p1)]], tmp_path)
    assert bridge.sent_players == [None]          # no seat on the wire in single-planner mode
    assert "TURN 0 | Domination | 2 players | Imperius (player 1)" in out
    assert res.outcome == "game_over" and res.won is False      # game_over.json: winner 2, won false


def test_seat_prompt_has_no_opponent_private_data():
    """What a seat is shown is its own fog-filtered state: the other seat's stars/techs never appear."""
    from polytopia_bridge.planner import TurnPlanner
    t0p1, t0p2 = hotseat("t0_p1"), hotseat("t0_p2")
    prompt1, _ = TurnPlanner("m", runner=lambda *a: {}).build_prompt(t0p1)
    prompt2, _ = TurnPlanner("m", runner=lambda *a: {}).build_prompt(t0p2)
    assert "player 1" in prompt1 and "YOU: Imperius (player 1)" in prompt1
    assert "YOU: Imperius (player 2)" in prompt2
    for p in (t0p1, t0p2):
        me = p["state"]["me"]["id"]
        for other in p["state"]["players"]:
            if other["id"] != me:
                assert "stars" not in other and "is_me" not in other
    # the two seats see different ground
    assert {(t["x"], t["y"]) for t in t0p1["state"]["tiles"]} != {(t["x"], t["y"]) for t in t0p2["state"]["tiles"]}


def test_states_after_an_accepted_end_turn_are_not_acted_on(tmp_path):
    t0p1, t0p2 = hotseat("t0_p1"), hotseat("t0_p2")
    sp1 = NamedPlanner("a", [[legal_of("end_turn", t0p1)]])
    sp2 = NamedPlanner("b", [[legal_of("end_turn", t0p2)]])
    # two stale copies of seat 1's state arrive after its end turn was accepted, then seat 2's state
    bridge, res, out, _ = run2([t0p1, copy.deepcopy(t0p1), copy.deepcopy(t0p1), t0p2], sp1, sp2, tmp_path)
    assert [a["kind"] for a in bridge.sent] == ["end_turn", "end_turn"] and bridge.sent_players == [1, 2]
    assert sp1.calls == 1 and "already ended" in out


def test_game_that_never_advances_after_end_turn_is_stuck(tmp_path):
    t0p1 = hotseat("t0_p1")
    states = [t0p1] + [copy.deepcopy(t0p1) for _ in range(8)]
    bridge, res, out, _ = run2(states, NamedPlanner("a", [[legal_of("end_turn", t0p1)]]), NamedPlanner("b", []), tmp_path)
    assert res.outcome == "stuck" and "did not advance" in out
    assert [a["kind"] for a in bridge.sent] == ["end_turn", "end_turn"]      # the original and one nudge


def test_reward_pending_after_end_turn_is_answered_then_turn_ends_again(tmp_path):
    t0p1, t0p2 = hotseat("t0_p1"), hotseat("t0_p2")
    reward = load("state_city_reward.json")
    reward["turn"] = t0p1["turn"]
    reward["player"] = 1
    reward["state"]["me"]["id"] = 1
    after_reward = copy.deepcopy(t0p1)
    sp1 = NamedPlanner("a", [[legal_of("end_turn", t0p1)]])
    sp2 = NamedPlanner("b", [[legal_of("end_turn", t0p2)]])
    # end turn accepted -> the engine reports a pending city reward for the same seat-turn -> answered ->
    # the same seat-turn again (end turn re-sent, no model call) -> seat 2
    bridge, res, out, _ = run2([t0p1, reward, after_reward, t0p2], sp1, sp2, tmp_path)
    assert [a["kind"] for a in bridge.sent] == ["end_turn", "city_reward", "end_turn", "end_turn"]
    assert bridge.sent_players == [1, 1, 1, 2]
    assert sp1.calls == 1 and sp2.calls == 1
