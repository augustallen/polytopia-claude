import json

import pytest

from polytopia_bridge.claude_stream import CommentaryExtractor, PlannerError, build_command, consume_events


def test_extractor_streams_commentary_across_chunks_with_escapes():
    ex = CommentaryExtractor()
    out = ""
    for chunk in ['{"comm', 'entary": "Rush ', 'east\\n', 'now \\"fast\\', '" ok', '", "actions": [1, 2]']:
        out += ex.feed(chunk)
    assert out == 'Rush east\nnow "fast" ok'
    assert ex.done
    assert ex.feed('junk') == ""


def test_extractor_handles_split_unicode_escape():
    ex = CommentaryExtractor()
    out = ex.feed('{"commentary": "a\\u00')
    out += ex.feed('e9b"')
    assert out == "aéb"


def stream_line(index, delta):
    return json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "index": index, "delta": delta}})


def block_start(index, block):
    return json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "index": index, "content_block": block}})


def test_consume_events_scopes_json_to_structured_output_block():
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5"}),
        block_start(0, {"type": "thinking", "thinking": ""}),
        stream_line(0, {"type": "thinking_delta", "thinking": "", "estimated_tokens": 50}),
        block_start(1, {"type": "text", "text": ""}),
        stream_line(1, {"type": "text_delta", "text": "Let me plan."}),
        block_start(2, {"type": "tool_use", "name": "OtherTool", "input": {}}),
        stream_line(2, {"type": "input_json_delta", "partial_json": '{"commentary": "WRONG'}),
        block_start(3, {"type": "tool_use", "name": "StructuredOutput", "input": {}}),
        stream_line(3, {"type": "input_json_delta", "partial_json": '{"commentary": "Go '}),
        stream_line(3, {"type": "input_json_delta", "partial_json": 'east", "actions": [0]}'}),
        "",
        "not json",
        json.dumps({"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": {"commentary": "Go east", "actions": [0], "notes": ""},
                    "usage": {"input_tokens": 1}, "total_cost_usd": 0.02}),
    ]
    thinking, text, status = [], [], []
    res = consume_events(lines, on_thinking=lambda t, n: thinking.append((t, n)), on_text=text.append, on_status=status.append)
    assert res["structured_output"]["actions"] == [0]
    assert thinking == [("", 50)]
    assert "".join(text) == "Go east"          # plain text blocks are not forwarded
    assert status == ["model claude-opus-5"]


def test_second_structured_output_block_is_marked_as_revised():
    lines = [
        block_start(1, {"type": "tool_use", "name": "StructuredOutput", "input": {}}),
        stream_line(1, {"type": "input_json_delta", "partial_json": '{"commentary": "First try", "actions": [0]}'}),
        block_start(3, {"type": "tool_use", "name": "StructuredOutput", "input": {}}),
        stream_line(3, {"type": "input_json_delta", "partial_json": '{"commentary": "Second try", "actions": [1]}'}),
        json.dumps({"type": "result", "structured_output": {"commentary": "Second try", "actions": [1]}}),
    ]
    text = []
    res = consume_events(lines, on_text=text.append)
    assert "".join(text) == "First try\n[revised] Second try"
    assert res["structured_output"]["actions"] == [1]


def test_consume_events_without_block_start_still_streams():
    lines = [stream_line(1, {"type": "input_json_delta", "partial_json": '{"commentary": "hi"'}),
             json.dumps({"type": "result", "structured_output": {"actions": []}})]
    text = []
    consume_events(lines, on_text=text.append)
    assert text == ["hi"]


def test_consume_events_errors():
    with pytest.raises(PlannerError, match="without a result"):
        consume_events([stream_line(0, {"type": "text_delta", "text": "x"})])
    with pytest.raises(PlannerError, match="claude -p error"):
        consume_events([json.dumps({"type": "result", "is_error": True, "result": "rate limited"})])


def test_missing_executable_is_a_planner_error():
    from polytopia_bridge.claude_stream import run_claude_stream
    with pytest.raises(PlannerError, match="could not start"):
        run_claude_stream("hi", system_prompt="s", schema={}, model="m", claude_bin="definitely-not-a-real-claude-binary")


def test_build_command_flags():
    cmd = build_command(claude_bin="claude", schema={"type": "object"}, system_prompt="sys", model="claude-opus-5", effort="low")
    assert cmd[:2] == ["claude", "-p"]
    assert "--include-partial-messages" in cmd and "--verbose" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--json-schema") + 1] == '{"type": "object"}'
    assert cmd[cmd.index("--effort") + 1] == "low"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--effort" not in build_command(claude_bin="claude", schema={}, system_prompt="s", model="m", effort=None)
