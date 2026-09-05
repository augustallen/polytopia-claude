import json
from pathlib import Path

import pytest

from polytopia_bridge.observe import estimate_tokens, render

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


if __name__ == "__main__":
    import sys
    text, legal = render(load(sys.argv[1] if len(sys.argv) > 1 else "state_midgame.json"))
    print(text)
    print(f"\n~{estimate_tokens(text)} tokens, {len(legal)} actions")
