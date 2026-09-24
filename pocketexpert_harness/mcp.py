# SPDX-License-Identifier: Apache-2.0
"""MCP 客户端: stdio 与 Streamable HTTP 两种传输, 把服务端的工具挂进工具注册表。

配置沿用常见的 mcp.json 写法 (与 Claude Desktop / Cursor 相同), 值里可以写 ${ENV_NAME} 引用环境变量:

    {"mcpServers": {
        "fs":     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]},
        "remote": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}
    }}

工具在模型眼里叫 ``mcp__<服务名>__<工具名>``。stdio 子进程只继承 PATH/HOME 这类基础环境变量加上配置里写的 env,
不会把模型的 API Key 带过去。旧式 SSE 传输 (2024-11-05 版的 /sse 端点) 不支持。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from pocketexpert_harness import __version__
from pocketexpert_harness.kernel.loop import ToolResult
from pocketexpert_harness.tools import Tool

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "pocketexpert-harness", "version": __version__}
MAX_TOOL_PAGES = 20
STDIO_ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL", "TMPDIR", "TZ",
                  "APPDATA", "LOCALAPPDATA", "USERPROFILE", "SYSTEMROOT", "PROGRAMFILES", "NODE_PATH", "NVM_DIR")
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MCPError(RuntimeError):
    pass


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def _rpc_error(msg: dict) -> MCPError:
    err = msg.get("error") or {}
    return MCPError(f"MCP 错误 {err.get('code')}: {str(err.get('message') or err)[:300]}")


# ── 传输 ────────────────────────────────────────────────────────────────

class StdioTransport:
    def __init__(self, command: str, args: list[str], env: dict[str, str], cwd: Optional[str] = None):
        self.command, self.args, self.env, self.cwd = command, args, env, cwd
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._next = 0
        self._tasks: list[asyncio.Task] = []
        self._write_lock = asyncio.Lock()
        self.stderr_tail: list[str] = []

    async def start(self) -> None:
        env = {k: os.environ[k] for k in STDIO_ENV_KEEP if k in os.environ}
        env.update({k: str(v) for k, v in self.env.items()})
        self.proc = await asyncio.create_subprocess_exec(
            self.command, *self.args, cwd=self.cwd, env=env, limit=16 << 20,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self._tasks = [asyncio.create_task(self._read_loop()), asyncio.create_task(self._drain_stderr())]

    async def _send(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        async with self._write_lock:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            await self.proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("mcp stdio 非 JSON 输出: %s", line[:200])
                    continue
                for m in msg if isinstance(msg, list) else [msg]:
                    await self._dispatch(m)
        finally:
            tail = " | ".join(self.stderr_tail[-5:])
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(MCPError(f"MCP 进程已退出{': ' + tail if tail else ''}"))

    async def _dispatch(self, m: dict) -> None:
        if not isinstance(m, dict):
            return
        if "method" in m and "id" in m:           # 服务端发来的请求
            await self._send(_answer_server_request(m))
        elif "id" in m:
            fut = self._pending.pop(str(m["id"]), None)
            if fut and not fut.done():
                fut.set_result(m)

    async def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            self.stderr_tail = (self.stderr_tail + [text])[-20:]
            logger.debug("mcp stderr: %s", text)

    async def request(self, method: str, params: Optional[dict], timeout: float) -> dict:
        self._next += 1
        rid = str(self._next)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": self._next, "method": method, **({"params": params} if params is not None else {})})
        try:
            msg = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)
        if "error" in msg:
            raise _rpc_error(msg)
        return msg.get("result") or {}

    async def notify(self, method: str, params: Optional[dict] = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.proc and self.proc.returncode is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass


def _answer_server_request(m: dict) -> dict:
    method = m.get("method")
    if method == "ping":
        return {"jsonrpc": "2.0", "id": m["id"], "result": {}}
    if method == "roots/list":
        return {"jsonrpc": "2.0", "id": m["id"], "result": {"roots": []}}
    return {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": f"客户端不支持 {method}"}}


def iter_sse(text_lines: list[str]):
    """把 SSE 行切成事件的 data (多行 data 拼接)。"""
    data: list[str] = []
    for line in text_lines + [""]:
        if line == "":
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())


class HttpTransport:
    def __init__(self, url: str, headers: dict[str, str], client: Optional[httpx.AsyncClient] = None):
        self.url, self.headers = url, headers
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
        self._own_client = client is None
        self.session_id = ""
        self.protocol = ""
        self._next = 0

    async def start(self) -> None:
        return None

    def _h(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    async def _post(self, msg: dict, timeout: float) -> Optional[dict]:
        rid = msg.get("id")
        async with self.client.stream("POST", self.url, headers=self._h(), json=msg, timeout=timeout) as r:
            if r.headers.get("mcp-session-id"):
                self.session_id = r.headers["mcp-session-id"]
            if r.status_code == 202 or rid is None:
                return None
            if r.status_code >= 400:
                body = (await r.aread()).decode("utf-8", "replace")[:300]
                raise MCPError(f"MCP HTTP {r.status_code}: {body}")
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" in ctype:
                lines: list[str] = []
                async for line in r.aiter_lines():
                    if line == "" and lines:
                        for data in iter_sse(lines):
                            found = await self._sse_message(data, rid)
                            if found is not None:
                                return found
                        lines = []
                    else:
                        lines.append(line)
                for data in iter_sse(lines):
                    found = await self._sse_message(data, rid)
                    if found is not None:
                        return found
                raise MCPError("MCP 流结束了还没收到响应")
            payload = json.loads((await r.aread()).decode("utf-8", "replace"))
            for m in payload if isinstance(payload, list) else [payload]:
                if isinstance(m, dict) and m.get("id") == rid:
                    return m
            raise MCPError("MCP 响应里没有对应的 id")

    async def _sse_message(self, data: str, rid: Any) -> Optional[dict]:
        try:
            m = json.loads(data)
        except json.JSONDecodeError:
            return None
        for one in m if isinstance(m, list) else [m]:
            if not isinstance(one, dict):
                continue
            if "method" in one and "id" in one:
                try:
                    await self._post(_answer_server_request(one), timeout=10)
                except Exception:       # noqa: BLE001
                    pass
            elif one.get("id") == rid:
                return one
        return None

    async def request(self, method: str, params: Optional[dict], timeout: float) -> dict:
        self._next += 1
        msg = await self._post({"jsonrpc": "2.0", "id": self._next, "method": method,
                                **({"params": params} if params is not None else {})}, timeout)
        if msg is None:
            raise MCPError("MCP 服务没有返回")
        if "error" in msg:
            raise _rpc_error(msg)
        return msg.get("result") or {}

    async def notify(self, method: str, params: Optional[dict] = None) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}, 15)

    async def close(self) -> None:
        if self.session_id:
            try:
                await self.client.delete(self.url, headers=self._h(), timeout=5)
            except Exception:       # noqa: BLE001
                pass
        if self._own_client:
            await self.client.aclose()


# ── 服务端与管理器 ──────────────────────────────────────────────────────

def tool_name(server: str, tool: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")
    return name[:64]


def format_call_result(result: dict) -> ToolResult:
    parts: list[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind}: {item.get('mimeType', '')}, {len(str(item.get('data') or '')) * 3 // 4} 字节]")
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(str(res.get("text") or f"[资源 {res.get('uri', '')}]"))
        elif kind == "resource_link":
            parts.append(f"[资源链接 {item.get('name', '')}: {item.get('uri', '')}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(p for p in parts if p) or "(工具没有返回内容)"
    return ToolResult(ok=not result.get("isError"), obs=text)


class MCPServer:
    def __init__(self, name: str, spec: dict, *, http_client: Optional[httpx.AsyncClient] = None):
        self.name, self.spec = name, spec
        self.tools: list[dict] = []
        self.status = "stopped"
        self.error = ""
        self.server_info: dict = {}
        spec = expand_env(spec)
        if spec.get("command"):
            self.transport: Any = StdioTransport(str(spec["command"]), [str(a) for a in spec.get("args") or []],
                                                 dict(spec.get("env") or {}), spec.get("cwd"))
        elif spec.get("url"):
            if str(spec.get("type") or spec.get("transport") or "").lower() == "sse":
                raise MCPError("旧式 SSE 传输不支持, 请换用服务端的 Streamable HTTP 地址 (一般以 /mcp 结尾)")
            self.transport = HttpTransport(str(spec["url"]), dict(spec.get("headers") or {}), http_client)
        else:
            raise MCPError("需要 command (stdio) 或 url (HTTP)")

    async def connect(self, timeout: float = 30.0) -> None:
        self.status = "starting"
        await self.transport.start()
        init = await self.transport.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}, timeout)
        self.server_info = init.get("serverInfo") or {}
        if isinstance(self.transport, HttpTransport):
            self.transport.protocol = str(init.get("protocolVersion") or PROTOCOL_VERSION)
        await self.transport.notify("notifications/initialized")
        cursor, tools = None, []
        for _ in range(MAX_TOOL_PAGES):
            page = await self.transport.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            tools += [t for t in page.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        self.tools = tools
        self.status = "ready"

    async def call(self, tool: str, args: dict, timeout: float = 120.0) -> ToolResult:
        result = await self.transport.request("tools/call", {"name": tool, "arguments": args or {}}, timeout)
        return format_call_result(result)

    async def close(self) -> None:
        try:
            await self.transport.close()
        finally:
            self.status = "stopped"


class MCPManager:
    def __init__(self, config_path: Optional[Path] = None, *, http_client: Optional[httpx.AsyncClient] = None):
        self.config_path = config_path
        self.servers: dict[str, MCPServer] = {}
        self.failed: dict[str, str] = {}
        self._http_client = http_client

    def load(self) -> dict:
        if not self.config_path or not Path(self.config_path).is_file():
            return {}
        data = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
        return {k: v for k, v in (data.get("mcpServers") or {}).items() if isinstance(v, dict) and not v.get("disabled")}

    async def start(self, timeout: float = 30.0) -> None:
        specs = self.load()

        async def _one(name: str, spec: dict) -> None:
            try:
                srv = MCPServer(name, spec, http_client=self._http_client)
            except MCPError as e:
                self.failed[name] = str(e)
                return
            try:
                await asyncio.wait_for(srv.connect(timeout), timeout=timeout + 5)
                self.servers[name] = srv
            except Exception as e:      # noqa: BLE001 — 一个服务起不来不影响别的
                self.failed[name] = f"{type(e).__name__}: {str(e)[:300]}"
                logger.warning("MCP 服务 %s 启动失败: %s", name, e)
                await srv.close()

        await asyncio.gather(*(_one(n, s) for n, s in specs.items()))

    def tools(self) -> list[Tool]:
        out = []
        for srv in self.servers.values():
            for t in srv.tools:
                name = t["name"]

                async def _call(args: dict, _srv=srv, _name=name) -> ToolResult:
                    return await _srv.call(_name, args)
                schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
                out.append(Tool(name=tool_name(srv.name, name), handler=_call, obs_cap=10000, timeout=150,
                                description=f"[MCP:{srv.name}] {str(t.get('description') or name)[:1000]}",
                                parameters=schema or {"type": "object", "properties": {}},
                                meta={"mcp_server": srv.name, "mcp_tool": name}))
        return out

    def status(self) -> list[dict]:
        rows = [{"name": n, "status": s.status, "tools": len(s.tools), "server": s.server_info.get("name", "")}
                for n, s in self.servers.items()]
        rows += [{"name": n, "status": "failed", "error": e, "tools": 0} for n, e in self.failed.items()]
        return rows

    async def close(self) -> None:
        await asyncio.gather(*(s.close() for s in self.servers.values()), return_exceptions=True)
        self.servers.clear()
