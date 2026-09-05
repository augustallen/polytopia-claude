#!/usr/bin/env python3
"""Send one or more control messages to the bridge and print the replies.

    bridgectl.py status
    bridgectl.py resume --wait 12 status
    bridgectl.py kick:start_processing status
    bridgectl.py '{"type":"action","action":{"kind":"end_turn"}}'

Tokens are message types (`status`, `resume`, `ping`, `get_state`), `kick:<method>`, raw JSON
objects, or `--wait N` to pause N seconds between messages. `get_state` waits for the next state.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polytopia_bridge import BridgeClient  # noqa: E402


def main(argv):
    host, port = "127.0.0.1", 9876
    with BridgeClient(host, port) as c:
        print("hello:", json.dumps(c.hello or c.connect()))
        i = 0
        while i < len(argv):
            tok = argv[i]
            i += 1
            if tok == "--wait":
                import time
                time.sleep(float(argv[i]))
                i += 1
                continue
            if tok.startswith("{"):
                msg = json.loads(tok)
            elif tok.startswith("kick:"):
                msg = {"type": "kick", "method": tok[5:]}
            else:
                msg = {"type": tok}
            c.send(msg)
            if msg["type"] == "get_state":
                reply = c.wait_for_state(timeout=60)
                st = reply["state"]
                print(f"state: turn={reply['turn']} stars={st['me']['stars']} units={len(st['units'])} legal={len(reply['legal_actions'])}")
            elif msg["type"] == "action":
                print("result:", json.dumps(c.expect("result")))
            else:
                print(f"{msg['type']}:", json.dumps(c.recv(timeout=30)))


if __name__ == "__main__":
    main(sys.argv[1:])
