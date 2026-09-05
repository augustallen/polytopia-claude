"""Python side of the ClaudeBridge protocol (see docs/PROTOCOL.md)."""

from .client import BridgeClient, BridgeClosed, GameOver

__all__ = ["BridgeClient", "BridgeClosed", "GameOver"]
