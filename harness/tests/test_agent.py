import json
from pathlib import Path
from types import SimpleNamespace

from polytopia_bridge.agent import ClaudeAgent, RandomAgent

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubClient:
    """Returns canned JSON answers in order, recording the prompts it was given."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.messages = self
        self.beta = SimpleNamespace(messages=self)

    def create(self, **params):
        self.prompts.append(params["messages"][0]["content"])
        text = self.answers.pop(0)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=800),
        )


def test_claude_agent_parses_decision_and_keeps_notes():
    msg = load("state_midgame.json")
    stub = StubClient([json.dumps({"reasoning": "harvest first", "action": 9, "notes": "then capture (10,10)"})])
    agent = ClaudeAgent(model="claude-opus-5", client=stub)
    d = agent.decide(msg)
    assert d.index == 9 and d.error is None
    assert agent.notes == "then capture (10,10)"
    assert agent.total_usage["cache_read"] == 800
    assert "LEGAL ACTIONS" in stub.prompts[0]
    # second decision sees the notes and the recorded action
    agent.record(12, msg["legal_actions"][9], {"ok": True})
    stub.answers.append(json.dumps({"reasoning": "x", "action": 0, "notes": "n"}))
    agent.decide(msg)
    assert "then capture (10,10)" in stub.prompts[1] and "RECENT ACTIONS" in stub.prompts[1]


def test_claude_agent_retries_once_then_falls_back_to_end_turn():
    msg = load("state_midgame.json")
    bad = json.dumps({"reasoning": "?", "action": 999, "notes": ""})
    stub = StubClient([bad, "not json"])
    agent = ClaudeAgent(model="claude-opus-5", client=stub)
    d = agent.decide(msg)
    assert msg["legal_actions"][d.index]["kind"] == "end_turn"
    assert d.error
    assert "PREVIOUS ANSWER WAS INVALID" in stub.prompts[1]


def test_random_agent_never_disbands_and_can_end_turn():
    msg = load("state_midgame.json")
    agent = RandomAgent(seed=3, end_turn_prob=1.0)
    d = agent.decide(msg)
    assert msg["legal_actions"][d.index]["kind"] == "end_turn"
    kinds = {msg["legal_actions"][RandomAgent(seed=s, end_turn_prob=0.0).decide(msg).index]["kind"] for s in range(30)}
    assert "disband" not in kinds and kinds
