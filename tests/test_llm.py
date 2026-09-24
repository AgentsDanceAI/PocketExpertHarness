# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

import httpx
import pytest

from pocketexpert_harness.llm import ChatModel, LLMError


def sse(*chunks) -> bytes:
    return b"".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def model_with(settings, handler):
    return ChatModel(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_streams_content_and_assembles_tool_calls(settings):
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        body = sse(
            {"choices": [{"delta": {"content": "我先"}}]},
            {"choices": [{"delta": {"content": "搜一下"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "web_search", "arguments": "{\"que"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ry\": \"天气\"}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    m = model_with(settings, handler)
    deltas = []
    res = await m.port([{"role": "user", "content": "hi"}], m.route, deltas.append, tools=[{"type": "function"}])
    assert "".join(deltas) == "我先搜一下"
    assert res["content"] == "我先搜一下"
    assert res["tool_calls"] == [{"id": "call_1", "name": "web_search", "args": {"query": "天气"}}]
    assert res["finish_reason"] == "tool_calls"
    assert seen["auth"] == "Bearer k" and seen["body"]["stream"] is True and seen["body"]["tool_choice"] == "auto"
    assert m.usage["prompt_tokens"] == 10
    assert "api_key" not in json.dumps(m.route) and "k" not in m.route.values()


async def test_truncated_arguments_become_malformed(settings):
    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "write_file", "arguments": "{\"path\": \"a"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]}))
    m = model_with(settings, handler)
    res = await m.port([], m.route, lambda _t: None, tools=[{}])
    assert res.get("malformed") and "write_file" in res["nudge"] and res["tool_calls"] == []


async def test_non_stream_json_fallback(settings):
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "整包回复"}, "finish_reason": "stop"}]})
    m = model_with(settings, handler)
    out = []
    res = await m.port([], m.route, out.append)
    assert res["content"] == "整包回复" and out == ["整包回复"]


async def test_http_error_carries_status_for_retry_hook(settings):
    m = model_with(settings, lambda req: httpx.Response(429, text="rate limited"))
    with pytest.raises(LLMError, match="429"):
        await m.port([], m.route, lambda _t: None)


async def test_extra_body_and_temperature_are_sent(settings):
    settings.extra_body = {"enable_thinking": False}
    settings.temperature = 0.2
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    m = model_with(settings, handler)
    assert await m.complete([{"role": "user", "content": "x"}]) == "ok"
    assert seen["enable_thinking"] is False and seen["temperature"] == 0.2 and seen["stream"] is False
