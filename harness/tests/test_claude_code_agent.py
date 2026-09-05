import json
from pathlib import Path

from polytopia_bridge.agent import ClaudeCodeAgent

FIXTURES = Path(__file__).parent / "fixtures"


def test_claude_code_agent_uses_structured_output_and_cost():
    msg = json.loads((FIXTURES / "state_midgame.json").read_text(encoding="utf-8"))
    seen = []

    def fake_cli(prompt):
        seen.append(prompt)
        # shape of `claude -p --output-format json --json-schema ...`
        return {
            "is_error": False,
            "result": '{"reasoning":"x","action":9,"notes":"harvest then expand"}',
            "structured_output": {"reasoning": "x", "action": 9, "notes": "harvest then expand"},
            "usage": {"input_tokens": 2, "output_tokens": 140, "cache_creation_input_tokens": 1060, "cache_read_input_tokens": 0},
            "total_cost_usd": 0.0066,
        }

    agent = ClaudeCodeAgent("claude-sonnet-5", runner=fake_cli)
    d = agent.decide(msg)
    assert d.index == 9 and d.error is None
    assert agent.notes == "harvest then expand"
    assert agent.total_usage["cache_write"] == 1060
    assert abs(agent.cost() - 0.0066) < 1e-9
    assert "LEGAL ACTIONS" in seen[0]
