"""BridgeClient against a scripted local TCP server, and to_menu_and_new_game against a fake client."""
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from polytopia_bridge.client import BridgeClient
from polytopia_bridge.runner import to_menu_and_new_game

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Server:
    """Accepts one client, sends `script` messages (a float means sleep), records what it receives."""

    def __init__(self, script):
        self.script = script
        self.received = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("rw", encoding="utf-8", newline="\n")
        try:
            f.write(json.dumps({"type": "hello", "in_game": False}) + "\n")
            f.flush()
            for item in self.script:
                if isinstance(item, (int, float)):
                    time.sleep(item)
                elif item == "READ":
                    self.received.append(json.loads(f.readline()))
                else:
                    f.write(json.dumps(item) + "\n")
                    f.flush()
            time.sleep(0.5)
        except OSError:
            pass            # the client closed first; fine
        finally:
            conn.close()


def test_expect_deadline_is_absolute_under_a_warning_stream():
    warning = {"type": "warning", "reason": "handoff stalled", "where": "overlay"}
    server = Server([0.2, warning, 0.2, warning, 0.2, warning, 0.2, warning, 0.2, warning, 0.2, warning, 0.2, warning])
    seen = []
    with BridgeClient("127.0.0.1", server.port) as c:
        c.connect()
        c.on_warning = seen.append
        t0 = time.monotonic()
        with pytest.raises(socket.timeout):
            c.expect("state", timeout=0.7)
        assert time.monotonic() - t0 < 1.5           # not restarted per message
        assert seen and all(w["type"] == "warning" for w in seen)
        assert len(c.warnings) == len(seen)


def test_act_envelope_carries_the_seat():
    server = Server(["READ", {"type": "result", "ok": True, "error": None, "kind": "end_turn"},
                     "READ", {"type": "result", "ok": True, "error": None, "kind": "end_turn"}])
    with BridgeClient("127.0.0.1", server.port) as c:
        c.connect()
        c.act({"kind": "end_turn"}, player=2)
        c.act({"kind": "end_turn"})
    server.thread.join(timeout=3)
    assert server.received[0] == {"type": "action", "player": 2, "action": {"kind": "end_turn"}}
    assert "player" not in server.received[1]


class FakeClient:
    def __init__(self, first, hello=None):
        self.first = first
        self.hello = hello or {"in_game": False}
        self.sent = []

    def status(self):
        return {"has_game_state": False}

    def send(self, m):
        self.sent.append(m)

    def expect(self, *types, timeout=None):
        return {"type": "ok", "command": "new_game"}

    def discard(self, *types):
        return 0

    def wait_until_in_game(self, timeout=None):
        return self.first


def test_new_game_validates_hotseat_roster_and_returns_seat_info():
    first = load("state_hotseat_t0_p1.json")
    settings = {"game_type": "PassAndPlay", "mode": "Domination", "players": 2, "bots": 0, "map_size": 11,
                "tribes": ["Imperius", "Imperius"]}
    reply = to_menu_and_new_game(FakeClient(first), settings, settle=0)
    assert reply["first_player"] == 1 and [p["id"] for p in reply["roster"]] == [1, 2]
    with pytest.raises(RuntimeError, match="tribes"):
        to_menu_and_new_game(FakeClient(first), dict(settings, tribes=["Bardur", "Imperius"]), settle=0)
    with pytest.raises(RuntimeError, match="human seats"):
        to_menu_and_new_game(FakeClient(first), dict(settings, players=3), settle=0)
    with pytest.raises(RuntimeError, match="expected SinglePlayer"):
        to_menu_and_new_game(FakeClient(first), {"mode": "Domination", "opponents": 0}, settle=0)
    with pytest.raises(RuntimeError, match="map"):
        to_menu_and_new_game(FakeClient(first), dict(settings, map_size=16), settle=0)
