import json
from pathlib import Path

import pytest

from polytopia_bridge.observe import estimate_tokens, render, render_map

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_midgame_renders_every_action_with_an_index():
    msg = load("state_midgame.json")
    text, legal = render(msg)
    for i, a in enumerate(legal):
        assert f"[{i}]" in text, f"action {i} ({a['kind']}) missing from observation"
    assert "TURN" in text and "YOUR UNITS" in text and "LEGAL ACTIONS" in text


def test_midgame_is_compact():
    text, _ = render(load("state_midgame.json"))
    assert estimate_tokens(text) < 4000, f"observation too big: ~{estimate_tokens(text)} tokens"


def test_city_reward_pending_is_flagged():
    text, legal = render(load("state_city_reward.json"))
    assert "PENDING CityLevelUp" in text
    assert all(a["kind"] == "city_reward" for a in legal)
    assert "city reward: Explorer" in text or "city reward:" in text


def test_notes_are_included():
    text, _ = render(load("state_midgame.json"), notes="expand east")
    assert "expand east" in text


def test_domination_objective_without_known_capital():
    msg = load("state_midgame.json")
    msg["state"]["settings"]["game_mode"] = "Domination"
    text, _ = render(msg)
    assert "OBJECTIVE: Domination" in text and "NOT FOUND YET" in text


def test_domination_objective_with_known_capital_and_distances():
    msg = load("state_midgame.json")
    st = msg["state"]
    st["settings"]["game_mode"] = "Domination"
    st["cities"].append({"x": 13, "y": 7, "name": "Enemyville", "owner": 2, "level": 2, "population": 0,
                         "population_total": 3, "population_to_level": 3, "production": 3, "border_size": 1,
                         "is_capital": True, "connected_to_capital": True, "walls": True, "rewards": []})
    st["tiles"].append({"x": 13, "y": 7, "terrain": "Field", "owner": 2, "improvement": "City"})
    text, _ = render(msg)
    assert "Enemy capital Enemyville at (13,7)" in text and "walls" in text
    assert "Enemyville (13,7) player 2 level 2 CAPITAL walls" in text
    assert "straight-line" in text and "to capital" in text
    assert "*" in render_map(msg)


def test_domination_objective_after_capital_is_taken():
    msg = load("state_midgame.json")
    st = msg["state"]
    st["settings"]["game_mode"] = "Domination"
    st["cities"].append({"x": 13, "y": 7, "name": "Outpost", "owner": 2, "level": 1, "population": 0,
                         "population_total": 1, "population_to_level": 2, "production": 1, "border_size": 1,
                         "is_capital": False, "connected_to_capital": False, "walls": False, "rewards": []})
    text, _ = render(msg)
    assert "NOT FOUND YET" not in text
    assert "Remaining known enemy cities: Outpost (13,7)" in text


def test_monument_builds_are_grouped_into_one_line():
    msg = load("state_midgame.json")
    n = len(msg["legal_actions"])
    msg["legal_actions"].append({"kind": "build", "improvement": "Monument7", "at": [2, 4], "cost": 0, "population": 3})
    msg["legal_actions"].append({"kind": "build", "improvement": "Monument7", "at": [2, 6], "cost": 0, "population": 3})
    text, legal = render(msg)
    assert text.count("Monument7") == 1
    assert f"ONE placement, pick one tile) at: (2,4)[{n}] (2,6)[{n + 1}]" in text


def test_city_line_has_support_and_occupant_and_enemy_city_uses_E():
    msg = load("state_midgame.json")
    st = msg["state"]
    st["cities"].append({"x": 13, "y": 7, "name": "Enemyville", "owner": 2, "level": 2, "population": 0,
                         "population_total": 3, "population_to_level": 3, "production": 3, "border_size": 1,
                         "is_capital": False, "connected_to_capital": True, "walls": False, "rewards": []})
    st["tiles"].append({"x": 13, "y": 7, "terrain": "Field", "owner": 2, "improvement": "City"})
    text, _ = render(msg)
    assert "supports " in text and "units, city tile " in text
    assert ".E" in render_map(msg)


def test_summarize_change_reports_units_cities_and_stars():
    from polytopia_bridge.observe import summarize_change
    msg = load("state_midgame.json")
    before = msg["state"]
    after = json.loads(json.dumps(before))
    me = after["me"]["id"]
    after["me"]["stars"] -= 3
    own = next(u for u in after["units"] if u["owner"] == me)
    own["hp"] -= 4
    own["x"] += 1
    enemy = next(u for u in after["units"] if u["owner"] != me)
    after["units"].remove(enemy)
    after["units"].append({"id": 999, "type": "Rider", "owner": me, "x": 1, "y": 1, "hp": 10, "max_hp": 10,
                           "attack": 2, "defence": 1, "movement": 2, "range": 1})
    s = summarize_change(before, after)
    assert f"stars {before['me']['stars']}->{after['me']['stars']}" in s
    assert f"{own['type']}#{own['id']} hp" in s
    assert f"enemy {enemy['type']}#{enemy['id']} gone" in s
    assert "new Rider#999 at (1,1)" in s
    assert summarize_change(before, before, enemy_turn=True) == "nothing visible changed"


def test_legend_can_be_left_out():
    msg = load("state_midgame.json")
    assert "legend:" in render(msg)[0]
    assert "legend:" not in render(msg, legend=False)[0]


def test_perfection_has_no_objective_line():
    text, _ = render(load("state_midgame.json"))
    assert "OBJECTIVE" not in text


if __name__ == "__main__":
    import sys
    text, legal = render(load(sys.argv[1] if len(sys.argv) > 1 else "state_midgame.json"))
    print(text)
    print(f"\n~{estimate_tokens(text)} tokens, {len(legal)} actions")
