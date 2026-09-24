# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from pocketexpert_harness.kernel.loop import ToolCall
from pocketexpert_harness.mcp import MCPError, MCPManager, MCPServer, expand_env, tool_name
from pocketexpert_harness.tools import ToolRegistry

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


async def test_stdio_server_lists_paginated_tools_and_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-leak-check")
    monkeypatch.setenv("FAKE_ARG", "x")
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "calc": {"command": sys.executable, "args": [FAKE]},
        "broken": {"command": "/nonexistent/binary"},
        "off": {"command": "x", "disabled": True}}}))
    mgr = MCPManager(cfg)
    await mgr.start(timeout=10)
    try:
        assert set(mgr.servers) == {"calc"} and "broken" in mgr.failed and "off" not in mgr.failed
        tools = mgr.tools()
        assert [t.name for t in tools] == ["mcp__calc__add", "mcp__calc__fail"]
        reg = ToolRegistry()
        for t in tools:
            reg.add(t)
        res = [ev async for ev in reg.port(ToolCall(id="1", name="mcp__calc__add", args={"a": 2, "b": 3}), 1)][-1]
        assert res.ok and res.obs.startswith("5") and "sk-leak-check" not in res.obs
        res = [ev async for ev in reg.port(ToolCall(id="2", name="mcp__calc__fail", args={}), 1)][-1]
        assert not res.ok and res.obs == "出错了"
        status = {r["name"]: r["status"] for r in mgr.status()}
        assert status == {"calc": "ready", "broken": "failed"}
    finally:
        await mgr.close()


def http_server(sse: bool):
    state = {"session": None, "calls": []}

    def handler(req: httpx.Request):
        if req.method == "DELETE":
            return httpx.Response(200)
        msg = json.loads(req.content)
        state["calls"].append({"method": msg.get("method"), "session": req.headers.get("mcp-session-id"),
                               "proto": req.headers.get("mcp-protocol-version"), "auth": req.headers.get("authorization")})
        if "id" not in msg:
            return httpx.Response(202)
        method = msg["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "remote"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "回声", "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": "echo:" + json.dumps(msg["params"]["arguments"], ensure_ascii=False)}]}
        body = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        headers = {"mcp-session-id": "sess-1"} if method == "initialize" else {}
        if sse:
            data = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {}})}\n\n" \
                   f"event: message\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
            return httpx.Response(200, content=data.encode(), headers={**headers, "content-type": "text/event-stream"})
        return httpx.Response(200, json=body, headers=headers)
    return handler, state


@pytest.mark.parametrize("sse", [False, True])
async def test_streamable_http_server(sse, monkeypatch):
    monkeypatch.setenv("REMOTE_TOKEN", "t0k")
    handler, state = http_server(sse)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    srv = MCPServer("remote", {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}},
                    http_client=client)
    await srv.connect(timeout=5)
    try:
        assert [t["name"] for t in srv.tools] == ["echo"]
        res = await srv.call("echo", {"x": "你好"})
        assert res.ok and res.obs == 'echo:{"x": "你好"}'
    finally:
        await srv.close()
        await client.aclose()
    first, later = state["calls"][0], state["calls"][1:]
    assert first["session"] is None and first["auth"] == "Bearer t0k"
    assert all(c["session"] == "sess-1" and c["proto"] == "2025-06-18" for c in later)


def test_legacy_sse_rejected_and_helpers():
    with pytest.raises(MCPError, match="SSE"):
        MCPServer("old", {"url": "https://x/sse", "type": "sse"})
    with pytest.raises(MCPError):
        MCPServer("empty", {})
    assert tool_name("my server", "do.thing") == "mcp__my_server__do_thing"
    assert len(tool_name("s" * 50, "t" * 50)) == 64
    assert expand_env({"a": ["${NOPE_NOT_SET}"]}) == {"a": [""]}
