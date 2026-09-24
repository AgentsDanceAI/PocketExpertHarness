# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os

import httpx
import pytest

from pocketexpert_harness.kernel.loop import ToolCall, ToolResult
from pocketexpert_harness.tools import Tool, ToolRegistry
from pocketexpert_harness.tools import local, web


async def exec_tool(tools, name, args):
    reg = ToolRegistry()
    for t in tools:
        reg.add(t)
    out = [ev async for ev in reg.port(ToolCall(id="1", name=name, args=args), 1)]
    assert isinstance(out[-1], ToolResult)
    return out[-1]


def test_resolve_in_blocks_escape(tmp_path):
    assert local.resolve_in(tmp_path, "a/b.txt") == (tmp_path / "a/b.txt").resolve()
    for bad in ("../x", "/etc/passwd", "a/../../x"):
        with pytest.raises(PermissionError):
            local.resolve_in(tmp_path, bad)


async def test_file_tools_roundtrip(settings):
    tools = local.make_tools(settings)
    r = await exec_tool(tools, "write_file", {"path": "notes/a.md", "content": "# 标题"})
    assert r.ok
    assert (await exec_tool(tools, "read_file", {"path": "notes/a.md"})).obs == "# 标题"
    assert "notes/a.md" in (await exec_tool(tools, "list_files", {"recursive": True})).obs


async def test_run_python_output_env_and_timeout(settings, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
    code, out = await local.run_python("import os\nprint(6*7)\nprint(os.environ.get('LLM_API_KEY'))", settings.workspace)
    assert code == 0 and "42" in out and "sk-should-not-leak" not in out and "None" in out
    code, out = await local.run_python("import time\ntime.sleep(5)", settings.workspace, timeout=0.5)
    assert code == -9 and "超时" in out
    assert not [p for p in os.listdir(settings.workspace) if p.startswith(".peh_")]


async def test_python_tool_off_and_ask(settings):
    settings.python_mode = "off"
    assert "run_python" not in [t.name for t in local.make_tools(settings)]
    settings.python_mode = "ask"

    async def deny(_args):
        return False
    tools = local.make_tools(settings, confirm_python=deny)
    r = await exec_tool(tools, "run_python", {"code": "print(1)"})
    assert not r.ok and "没有同意" in r.obs


async def test_tool_exception_and_timeout_are_observations():
    async def boom(_a):
        raise ValueError("坏了")

    async def slow(_a):
        import asyncio
        await asyncio.sleep(5)
    r = await exec_tool([Tool("boom", "", {}, boom)], "boom", {})
    assert not r.ok and "坏了" in r.obs
    r = await exec_tool([Tool("slow", "", {}, slow, timeout=0.2)], "slow", {})
    assert not r.ok and "超时" in r.obs


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
                                 "http://10.0.0.5/", "file:///etc/passwd", "ftp://example.com/"])
async def test_check_url_rejects_private_and_non_http(url):
    with pytest.raises(web.UnsafeURL):
        await web.check_url(url)


async def test_check_url_allows_private_when_opted_in():
    await web.check_url("http://127.0.0.1:8080/", allow_private=True)


async def test_redirect_to_private_is_blocked(monkeypatch):
    async def fake_check(url, *, allow_private=False):
        if "127.0.0.1" in url:
            raise web.UnsafeURL("拒绝访问内网地址")

    monkeypatch.setattr(web, "check_url", fake_check)

    def handler(req):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(web.UnsafeURL):
            await web.fetch_text(c, "https://example.com/")


async def test_fetch_text_extracts_article(monkeypatch):
    async def ok(url, *, allow_private=False):
        return None
    monkeypatch.setattr(web, "check_url", ok)
    html = "<html><head><title>标题页</title><style>.x{}</style></head><body><script>evil()</script><h1>大标题</h1><p>第一段</p><ul><li>甲</li></ul></body></html>"

    def handler(req):
        return httpx.Response(200, content=html.encode(), headers={"content-type": "text/html; charset=utf-8"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        final, title, text = await web.fetch_text(c, "https://example.com/a")
    assert title == "标题页" and "# 大标题" in text and "第一段" in text and "- 甲" in text and "evil" not in text


async def test_searxng_search(settings):
    settings.searxng_url = "http://searx.local"

    def handler(req):
        assert req.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://a.com", "content": "摘要"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        tools = web.make_tools(settings, c)
        r = await exec_tool(tools, "web_search", {"query": "测试"})
    assert r.ok and "https://a.com" in r.obs and "[1]" in r.obs


def test_no_search_backend_no_tool(settings):
    names = [t.name for t in web.make_tools(settings, httpx.AsyncClient())]
    assert names == ["open_url"]
