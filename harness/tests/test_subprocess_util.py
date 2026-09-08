import sys

import pytest

from polytopia_bridge.subprocess_util import PlannerError, run_streaming_cli


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def collect(lines):
    return [line.rstrip("\n") for line in lines]


def test_returns_after_exit_with_returncode_and_stderr_tail():
    run = run_streaming_cli(py("import sys; print('a'); print('b'); print('bad thing', file=sys.stderr); sys.exit(3)"),
                            "", timeout=30, consume=collect, label="fake")
    assert run.result == ["a", "b"]
    assert run.returncode == 3
    assert "bad thing" in run.stderr_tail
    assert run.error is None and not run.timed_out


def test_stdin_is_delivered_without_deadlocking_on_large_output():
    code = "import sys; d = sys.stdin.read(); print(len(d)); print('x' * 300000)"
    run = run_streaming_cli(py(code), "p" * 120000, timeout=60, consume=collect, label="fake")
    assert run.result[0] == "120000" and len(run.result[1]) == 300000 and run.returncode == 0


def test_timeout_kills_the_process_and_labels_the_error():
    def consume(lines):
        for _ in lines:
            pass
        raise PlannerError("stream ended without a result", {"violations": 2})

    run = run_streaming_cli(py("import time; time.sleep(30)"), "", timeout=1.5, consume=consume, label="fake cli")
    assert run.timed_out
    assert run.error is not None and "fake cli timed out" in str(run.error)
    assert run.error.meta == {"violations": 2}          # metadata survives the rewrap


def test_consume_error_gets_stderr_context():
    def consume(lines):
        for _ in lines:
            pass
        raise PlannerError("no result")

    run = run_streaming_cli(py("import sys; print('oops', file=sys.stderr); sys.exit(1)"), "", timeout=30,
                            consume=consume, label="fake")
    assert run.error is not None and "no result" in str(run.error) and "oops" in str(run.error)
    assert run.returncode == 1


def test_missing_executable_is_a_planner_error():
    with pytest.raises(PlannerError, match="could not start"):
        run_streaming_cli(["definitely-not-a-real-binary-xyz"], "", timeout=5, consume=collect, label="fake")
