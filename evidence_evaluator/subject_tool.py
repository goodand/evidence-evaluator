#!/usr/bin/env python3
"""Public CLI bridge to the host-owned retrieval controller.

Extracted from `live_subject_tool.py` in the source experiment. This is the
one thing a Claude CLI subject is allowed to call (via `Bash`); a Codex
subject reaches the same socket indirectly through `mcp_bridge.py`. Either
way, the subject only ever sends a JSON action over a Unix socket and gets
a JSON response back -- it has no other way to touch the corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from typing import Any


SOCKET_ENV = "HANDOFF_LIVE_TOOL_SOCKET"


def request(payload: dict[str, Any]) -> dict[str, Any]:
    socket_path = os.environ.get(SOCKET_ENV)
    if not socket_path:
        raise RuntimeError(f"{SOCKET_ENV} is not set")
    message = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(socket_path)
        client.sendall(message)
        chunks = bytearray()
        while True:
            block = client.recv(65536)
            if not block:
                break
            chunks.extend(block)
    if not chunks:
        raise RuntimeError("live subject tool returned an empty response")
    return json.loads(chunks.decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    search = sub.add_parser("search")
    search.add_argument("query")

    follow = sub.add_parser("follow_link")
    follow.add_argument("path")

    sub.add_parser("expand_candidates")

    read = sub.add_parser("read_candidate")
    read.add_argument("path")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--end", type=int, default=40)

    finish = sub.add_parser("finish")
    finish.add_argument("terminal_action", choices=("answer", "abstain"))

    sub.add_parser("status")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = {"action": args.action}
    if args.action == "search":
        payload["query"] = args.query
    elif args.action == "follow_link":
        payload["path"] = args.path
    elif args.action == "read_candidate":
        payload.update(path=args.path, start=args.start, end=args.end)
    elif args.action == "finish":
        payload["terminal_action"] = args.terminal_action
    try:
        response = request(payload)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
