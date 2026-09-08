import json
import random
from pathlib import Path

from polytopia_bridge.claude_stream import PlannerError
from polytopia_bridge.planner import (PLAN_SCHEMA, TurnPlanner, action_key, annotate, depends_on, find_action,
                                      locate, resolve_plan)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_action_key_ignores_derived_fields():
    a = {"kind": "attack", "unit_id": 3, "target": [4, 5], "target_unit_id": 9, "damage": 5, "kills": True}
    b = {"kind": "attack", "unit_id": 3, "target": [4, 5], "target_unit_id": 9, "damage": 7, "kills": False}
    assert action_key(a) == action_key(b)
    # a different unit on the target tile is a different action
    c = dict(a, target_unit_id=10)
    assert action_key(a) != action_key(c)
    # peace accept vs decline differ
    assert action_key({"kind": "peace_request_response", "opponent": 2, "accept": True}) != \
        action_key({"kind": "peace_request_response", "opponent": 2, "accept": False})


def test_find_action_survives_renumbering():
    legal = load("state_midgame.json")["legal_actions"]
    shuffled = list(legal)
    random.Random(1).shuffle(shuffled)
    for a in legal:
        i = find_action(shuffled, action_key(a))
        assert i is not None and action_key(shuffled[i]) == action_key(a)
    gone = [a for a in shuffled if a["kind"] != "move"]
    move = next(a for a in legal if a["kind"] == "move")
    assert find_action(gone, action_key(move)) is None


def test_resolve_plan_reports_bad_indices_and_truncates_after_end_turn():
    legal = load("state_midgame.json")["legal_actions"]
    end = next(i for i, a in enumerate(legal) if a["kind"] == "end_turn")
    steps, problems = resolve_plan([0, 999, True, "x", end, 1, 2], legal)
    assert [s["kind"] for s in steps] == [legal[0]["kind"], "end_turn"]
    assert any("999" in p for p in problems)
    assert any("not an integer" in p for p in problems)
    assert any("after end turn" in p for p in problems)
    assert steps[0] is not legal[0]          # copies, so annotations never touch the state message
    steps, problems = resolve_plan("nope", legal)
    assert steps == [] and problems


def test_annotate_and_locate_verify_tile_occupant():
    msg = load("state_midgame.json")
    st = msg["state"]
    u = next(x for x in st["units"] if x["owner"] == st["me"]["id"])
    step = {"kind": "recover", "at": [u["x"], u["y"]]}
    annotate([step], st)
    assert step["_unit"] == u["id"]
    fresh = {"state": st, "legal_actions": [{"kind": "recover", "at": [u["x"], u["y"]]}]}
    assert locate(step, fresh) == (0, "")
    moved = json.loads(json.dumps(fresh))
    for x in moved["state"]["units"]:
        if x["id"] == u["id"]:
            x["x"] += 1
    idx, why = locate(step, moved)
    assert idx is None and "no longer at" in why


def test_depends_on_same_unit():
    failed = {"kind": "move", "unit_id": 5, "to": [1, 1]}
    assert depends_on({"kind": "attack", "unit_id": 5, "target": [2, 2]}, failed)
    assert not depends_on({"kind": "research", "tech": "Riding"}, failed)
    assert depends_on({"kind": "recover", "at": [1, 1], "_unit": 5}, failed)


def test_planner_uses_structured_output_and_counts_usage():
    msg = load("state_midgame.json")
    legal = msg["legal_actions"]
    end = next(i for i, a in enumerate(legal) if a["kind"] == "end_turn")
    prompts = []

    def fake(prompt, on_thinking, on_text):
        prompts.append(prompt)
        on_text("Rushing east. ")
        return {"is_error": False, "structured_output": {"commentary": "Rushing east.", "actions": [0, end], "notes": "go east"},
                "usage": {"input_tokens": 5, "output_tokens": 50, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0},
                "total_cost_usd": 0.01}

    seen = []
    p = TurnPlanner("claude-opus-5", runner=fake, on_commentary=seen.append)
    plan = p.plan(msg, ["research Riding -> ok"], max_attempts=2)
    assert plan.error is None and [s["kind"] for s in plan.steps] == [legal[0]["kind"], "end_turn"]
    assert plan.attempts == 1 and p.calls == 1
    assert p.notes == "go east" and abs(p.cost() - 0.01) < 1e-9
    assert p.total_usage["cache_write"] == 100
    assert seen == ["Rushing east. "]
    assert "THIS TURN SO FAR" in prompts[0] and "LEGAL ACTIONS" in prompts[0]
    assert "2 model call(s) left" in prompts[0]
    p.plan(msg, max_attempts=2, calls_left=3)
    assert "3 model call(s) left" in prompts[-1]
    assert "legend:" not in prompts[0]


def test_planner_retries_once_then_ends_turn():
    msg = load("state_midgame.json")
    calls = []

    def bad(prompt, on_thinking, on_text):
        calls.append(prompt)
        if len(calls) == 1:
            return {"structured_output": {"commentary": "", "actions": [9999], "notes": ""}, "usage": {}}
        raise PlannerError("boom")

    p = TurnPlanner("claude-opus-5", runner=bad)
    plan = p.plan(msg, max_attempts=2)
    assert plan.attempts == 2 and p.calls == 2
    assert plan.error and [s["kind"] for s in plan.steps] == ["end_turn"]
    assert "PREVIOUS ANSWER WAS INVALID" in calls[1] and "9999" in calls[1]


def test_planner_budget_of_one_does_not_retry():
    msg = load("state_midgame.json")
    n = []

    def bad(prompt, on_thinking, on_text):
        n.append(1)
        raise PlannerError("down")

    plan = TurnPlanner("claude-opus-5", runner=bad).plan(msg, max_attempts=1)
    assert len(n) == 1 and plan.attempts == 1 and plan.error


def test_empty_plan_is_valid():
    msg = load("state_midgame.json")
    plan = TurnPlanner("claude-opus-5", runner=lambda *_: {"structured_output": {"commentary": "pass", "actions": [], "notes": ""}}).plan(msg)
    assert plan.steps == [] and plan.error is None


def test_schema_puts_commentary_first():
    assert list(PLAN_SCHEMA["properties"])[0] == "commentary"


def test_codex_planner_reuses_plan_with_nullable_cost_and_meta():
    from polytopia_bridge.planner import CodexPlanner
    msg = load("state_midgame.json")

    def fake(prompt, on_thinking, on_text):
        return {"structured_output": {"commentary": "c", "actions": [0], "notes": "n"},
                "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 3},
                "total_cost_usd": None, "meta": {"streamed": False, "violations": 1, "backend": "codex"}}

    p = CodexPlanner("gpt-6-astra", "low", runner=fake, work_dir="unused")
    assert p.name == "codex-gpt-6-astra" and p.on_commentary is None and p.cost() is None
    plan = p.plan(msg, max_attempts=2)
    assert plan.cost is None and p.cost() is None
    assert plan.meta["streamed"] is False and plan.meta["violations"] == 1 and plan.meta["backend"] == "codex"
    assert p.violations == 1 and p.total_usage["cache_read"] == 3


def test_plan_meta_accumulates_across_failed_attempts():
    msg = load("state_midgame.json")
    n = []

    def flaky(prompt, on_thinking, on_text):
        n.append(1)
        if len(n) == 1:
            raise PlannerError("tools then crash", {"violations": 2, "backend": "codex"})
        return {"structured_output": {"commentary": "ok", "actions": [], "notes": ""}, "usage": {},
                "total_cost_usd": None, "meta": {"streamed": False, "violations": 1, "backend": "codex"}}

    plan = TurnPlanner("m", runner=flaky).plan(msg, max_attempts=2)
    assert plan.error is None and plan.attempts == 2 and plan.meta["violations"] == 3

    def always_bad(prompt, on_thinking, on_text):
        raise PlannerError("down", {"violations": 1})

    plan = TurnPlanner("m", runner=always_bad).plan(msg, max_attempts=2)
    assert plan.error and plan.meta["violations"] == 2 and [s["kind"] for s in plan.steps] == ["end_turn"]


def test_claude_cost_stays_a_float_and_streamed_is_recorded():
    msg = load("state_midgame.json")

    def fake(prompt, on_thinking, on_text):
        return {"structured_output": {"commentary": "c", "actions": [], "notes": ""}, "usage": {},
                "total_cost_usd": 0.02, "meta": {"streamed": True, "violations": 0, "backend": "claude-code"}}

    p = TurnPlanner("claude-opus-5", runner=fake)
    plan = p.plan(msg)
    assert abs(plan.cost - 0.02) < 1e-9 and abs(p.cost() - 0.02) < 1e-9 and plan.meta["streamed"] is True


def test_make_planner_specs(tmp_path):
    import pytest
    from polytopia_bridge.planner import CodexPlanner, make_planner
    a = make_planner("claude:claude-opus-5:low")
    assert type(a) is TurnPlanner and a.model == "claude-opus-5" and a.effort == "low" and a.name == "claude-code-claude-opus-5"
    b = make_planner("codex:gpt-6-astra", work_root=tmp_path)
    assert isinstance(b, CodexPlanner) and b.model == "gpt-6-astra" and b.effort == "medium"
    assert b.work_dir.parent == tmp_path and b.name == "codex-gpt-6-astra"
    c = make_planner("codex:gpt-6-astra", work_root=tmp_path)
    assert c is not b and c.work_dir != b.work_dir          # fresh instance per seat, per game
    assert make_planner("claude:") .model == make_planner("claude").model
    with pytest.raises(ValueError, match="unknown planner backend"):
        make_planner("gemini:x")


def test_make_planner_grok_spec(tmp_path):
    from polytopia_bridge.planner import GrokPlanner, make_planner
    g = make_planner("grok:grok-4.6:medium", work_root=tmp_path)
    assert isinstance(g, GrokPlanner) and g.model == "grok-4.6" and g.effort == "medium"
    assert g.name == "grok-grok-4.6" and g.on_commentary is None and g.work_dir.parent == tmp_path
    assert make_planner("grok").model == "grok-4.6"


def test_grok_planner_reuses_plan_with_fake_runner():
    from polytopia_bridge.planner import GrokPlanner
    msg = load("state_midgame.json")

    def fake(prompt, on_thinking, on_text):
        return {"structured_output": {"commentary": "c", "actions": [0], "notes": "n"},
                "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 3},
                "total_cost_usd": 0.004, "meta": {"streamed": False, "violations": 0, "backend": "grok", "thought": "t"}}

    p = GrokPlanner("grok-4.6", "medium", runner=fake, work_dir="unused")
    plan = p.plan(msg, max_attempts=2)
    assert plan.error is None and plan.meta["backend"] == "grok" and abs(plan.cost - 0.004) < 1e-9
    assert p.cost() is not None and plan.meta["thought"] == "t"
