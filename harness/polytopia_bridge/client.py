"""Socket client for the ClaudeBridge mod: newline-delimited JSON over TCP.

The bridge pushes `state` messages on its own schedule (whenever it is our turn and the
engine is idle) and answers each request with exactly one reply, so the client keeps a small
queue of unsolicited messages and lets callers wait for the kind they need.
"""
from __future__ import annotations

import json
import socket
import time
from collections import deque
from typing import Any

Message = dict[str, Any]


class BridgeClosed(ConnectionError):
    """The bridge closed the socket (game quit, or another client connected)."""


class GameOver(Exception):
    """Raised by wait_for_state when the bridge reports game_over instead."""

    def __init__(self, message: Message):
        super().__init__(f"game over on turn {message.get('turn')}")
        self.message = message


class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9876, connect_timeout: float = 10.0):
        self.host, self.port = host, port
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._file = None
        self._queue: deque[Message] = deque()
        self.hello: Message | None = None
        self.on_message = None  # optional callback(direction, message) for logging
        self.on_warning = None  # optional callback(message) for the bridge's `warning` messages
        self.warnings: deque[Message] = deque(maxlen=20)

    # ------------------------------------------------------------------ lifecycle

    def connect(self, retry_for: float = 0.0) -> Message:
        """Connect and return the bridge's hello. Retries for `retry_for` seconds if the game is not up yet."""
        deadline = time.monotonic() + retry_for
        while True:
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=self._connect_timeout)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1.0)
        self._sock.settimeout(None)
        self._file = self._sock.makefile("rw", encoding="utf-8", newline="\n")
        self.hello = self.expect("hello")
        return self.hello

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = self._file = None

    def __enter__(self) -> "BridgeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ raw I/O

    def send(self, message: Message) -> None:
        if self._file is None:
            raise BridgeClosed("not connected")
        self._file.write(json.dumps(message) + "\n")
        self._file.flush()
        if self.on_message:
            self.on_message("out", message)

    def recv(self, timeout: float | None = None) -> Message:
        """Next message, queued ones first. Blocks; `timeout` seconds raises socket.timeout."""
        if self._queue:
            return self._queue.popleft()
        if self._file is None or self._sock is None:
            raise BridgeClosed("not connected")
        self._sock.settimeout(timeout)
        try:
            line = self._file.readline()
        finally:
            self._sock.settimeout(None)
        if not line:
            self.close()
            raise BridgeClosed("bridge closed the connection")
        message = json.loads(line)
        if self.on_message:
            self.on_message("in", message)
        return message

    def expect(self, *types: str, timeout: float | None = None) -> Message:
        """Wait for a message of one of `types`; anything else is queued for later.

        `timeout` is an absolute deadline for the whole wait, not per message, so a stream of unrelated
        messages (the bridge's hotseat `warning`s, say) cannot keep a wait alive forever. Warnings are
        handed to `on_warning` and remembered in `warnings`; they are never queued."""
        skipped: list[Message] = []
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._queue.extendleft(reversed(skipped))
                    raise socket.timeout(f"no {'/'.join(types)} within {timeout:.0f}s")
            message = self.recv(remaining)
            if message.get("type") in types:
                self._queue.extendleft(reversed(skipped))
                return message
            if message.get("type") == "warning":
                self.warnings.append(message)
                if self.on_warning:
                    self.on_warning(message)
                continue
            skipped.append(message)

    # ------------------------------------------------------------------ protocol

    def ping(self) -> None:
        self.send({"type": "ping"})
        self.expect("pong")

    def status(self) -> Message:
        self.send({"type": "status"})
        return self.expect("status")

    def resume(self) -> Message:
        """Press the menu's Resume button for the saved single-player game. Returns {"type": "ok"} or an error."""
        self.send({"type": "resume"})
        return self.expect("ok", "error")

    def request_state(self) -> None:
        """Ask the bridge to (re)send the state once it is our turn; use wait_for_state to receive it."""
        self.send({"type": "get_state"})

    def act(self, action: Message, timeout: float | None = 120, *, player: int | None = None) -> Message:
        """Send one action and return its result ({"ok": bool, "error": str|None, "kind": str}).
        `player` names the seat acting (pass-and-play); the bridge rejects it if another seat is at the
        keyboard. Raises socket.timeout if no result arrives within `timeout` seconds."""
        envelope: Message = {"type": "action", "action": action}
        if player is not None:
            envelope["player"] = int(player)
        self.send(envelope)
        return self.expect("result", timeout=timeout)

    def wait_for_state(self, timeout: float | None = None) -> Message:
        """Block until the next state. Raises GameOver when the game ends first."""
        message = self.expect("state", "game_over", "left_game", timeout=timeout)
        if message["type"] == "game_over":
            raise GameOver(message)
        if message["type"] == "left_game":
            raise BridgeClosed("the game returned to the menu")
        return message

    def discard(self, *types: str) -> int:
        """Drop queued messages of the given types (e.g. a stale left_game after return_to_menu)."""
        before = len(self._queue)
        self._queue = deque(m for m in self._queue if m.get("type") not in types)
        return before - len(self._queue)

    def push_back(self, message: Message) -> None:
        """Return a message to the front of the queue so the next recv() yields it again."""
        self._queue.appendleft(message)

    def wait_until_in_game(self, timeout: float | None = 120) -> Message:
        """After new_game/resume: block until the first state arrives, ignoring left_game notices
        from the previous game, and leave that state queued for the game loop."""
        self.discard("left_game")
        while True:
            message = self.expect("state", "game_over", "left_game", "error", timeout=timeout)
            if message["type"] == "left_game":
                continue
            if message["type"] == "error":
                raise RuntimeError(message.get("error"))
            self.push_back(message)
            return message

    def drain_stale_states(self) -> Message | None:
        """Drop queued states, returning only the newest (states supersede each other)."""
        newest = None
        keep: deque[Message] = deque()
        while self._queue:
            m = self._queue.popleft()
            if m.get("type") == "state":
                newest = m
            else:
                keep.append(m)
        self._queue = keep
        return newest
