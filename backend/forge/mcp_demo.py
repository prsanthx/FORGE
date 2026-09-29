"""Tiny stdio MCP server used by the Studio "local demo" button.

Speaks Content-Length framed JSON-RPC. The tools are reminders only.
They do not read the benchmark oracles or the workspace.
"""

from __future__ import annotations

import json
import re
import sys

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "repo_notes",
        "description": "Reminder to inspect the checkout with the workspace tools before editing.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_oracle",
        "description": "Ask whether a hidden answer key is mounted for this run.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "additionalProperties": False,
        },
    },
]


def read_message(stream) -> dict | None:
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
        if len(header) > 65536:
            return None
    match = re.search(rb"Content-Length:\s*(\d+)", header, flags=re.IGNORECASE)
    if not match:
        return None
    length = int(match.group(1))
    body = stream.read(length)
    if len(body) < length:
        return None
    payload = json.loads(body)
    return payload if isinstance(payload, dict) else None


def write_message(stream, payload: dict) -> None:
    raw = json.dumps(payload).encode()
    stream.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
    stream.flush()


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def handle(message: dict) -> dict | None:
    method = str(message.get("method") or "")
    if "id" not in message:
        return None
    msg_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "forge-demo", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = str(params.get("name") or "")
        if name == "repo_notes":
            result = _text(
                "Open the files you plan to change with read_file, and use search before guessing a path."
            )
        elif name == "ask_oracle":
            result = _text(
                "No hidden answer key is mounted. Check the behavior by running the project's own tests."
            )
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": f"unknown tool {name}"},
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        message = read_message(stdin)
        if message is None:
            return
        reply = handle(message)
        if reply is not None:
            write_message(stdout, reply)


if __name__ == "__main__":
    main()
