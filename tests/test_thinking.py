# SPDX-License-Identifier: Apache-2.0
"""思考模式: 按服务商打开思考、接住思考流、服务端不认就去掉重发、DeepSeek 同一轮回传思考、网页记录与展示。"""
from __future__ import annotations

import json

import httpx
from conftest import FakeModel, call
from fastapi.testclient import TestClient

from pocketexpert_harness.agent import Harness
from pocketexpert_harness.llm import ChatModel, LLMError
from pocketexpert_harness.server import create_app


def sse(*chunks) -> bytes:
    return b"".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def stream(*chunks) -> httpx.Response:
    return httpx.Response(200, content=sse(*chunks), headers={"content-type": "text/event-stream"})


def model_with(settings, handler):
    return ChatModel(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_thinking_body_per_provider(settings):
    cases = {
        "https://api.deepseek.com/v1": {"thinking": {"type": "enabled"}},
        "https://dashscope.aliyuncs.com/compatible-mode/v1": {"enable_thinking": True},
        "https://api.siliconflow.cn/v1": {"enable_thinking": True},
        "https://openrouter.ai/api/v1": {"reasoning": {"enabled": True}},
        "http://localhost:11434/v1": {},            # 认不出写法: auto 不开
    }
    for url, want in cases.items():
        settings.base_url, settings.thinking_mode = url, "auto"
        assert settings.thinking_body() == want, url
    settings.base_url, settings.thinking_mode = "http://my-gateway.local/v1", "on"
    assert settings.thinking_body() == {"enable_thinking": True}, "on: 认不出的服务也按百炼的写法试"
    settings.base_url, settings.thinking_mode = "https://api.deepseek.com/v1", "off"
    assert settings.thinking_body() == {}


async def test_reasoning_streams_to_on_thinking_and_body_asks_for_it(settings):
    settings.base_url, settings.thinking_mode = "https://dashscope.aliyuncs.com/compatible-mode/v1", "auto"
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return stream({"choices": [{"delta": {"reasoning_content": "先想想"}}]},
                      {"choices": [{"delta": {"reasoning_content": ", 要算一下"}}]},
                      {"choices": [{"delta": {"content": "答案是 391"}, "finish_reason": "stop"}]})

    m = model_with(settings, handler)
    thoughts, deltas = [], []
    res = await m.port([{"role": "user", "content": "17×23"}], {**m.route, "on_thinking": thoughts.append}, deltas.append)
    assert seen["body"]["enable_thinking"] is True
    assert "".join(thoughts) == "先想想, 要算一下" and "".join(deltas) == "答案是 391"
    assert res["content"] == "答案是 391", "思考不能混进正文"


async def test_openrouter_style_reasoning_field_is_read_too(settings):
    def handler(req):
        return stream({"choices": [{"delta": {"reasoning": "嗯"}}]}, {"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]})

    m = model_with(settings, handler)
    got = []
    await m.port([{"role": "user", "content": "x"}], {**m.route, "on_thinking": got.append}, lambda _t: None)
    assert got == ["嗯"]


async def test_rejected_thinking_param_is_dropped_and_retried_once(settings):
    settings.base_url, settings.thinking_mode = "https://dashscope.aliyuncs.com/compatible-mode/v1", "auto"
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "enable_thinking" in body:     # 百炼 qwen-vl-max 的真实报错
            return httpx.Response(400, json={"error": {"message": "<400> InternalError.Algo.InvalidParameter: The thinking_budget "
                                                                  "parameter must be a positive integer and not greater than 0"}})
        return stream({"choices": [{"delta": {"content": "看到了"}, "finish_reason": "stop"}]})

    m = model_with(settings, handler)
    res = await m.port([{"role": "user", "content": "x"}], m.route, lambda _t: None)
    assert res["content"] == "看到了" and len(bodies) == 2 and "enable_thinking" not in bodies[1]
    assert m.thinking_rejected and not m.thinking_on
    await m.port([{"role": "user", "content": "y"}], m.route, lambda _t: None)
    assert len(bodies) == 3 and "enable_thinking" not in bodies[2], "认定不支持之后不再发, 省一次 400"


async def test_unrelated_400_is_not_swallowed(settings):
    settings.base_url, settings.thinking_mode = "https://dashscope.aliyuncs.com/compatible-mode/v1", "auto"
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(400, json={"error": {"message": "Model not exist"}})

    m = model_with(settings, handler)
    try:
        await m.port([{"role": "user", "content": "x"}], m.route, lambda _t: None)
        raise AssertionError("应当报错")
    except LLMError as e:
        assert e.status == 400 and len(n) == 1 and not m.thinking_rejected


async def test_deepseek_gets_reasoning_back_within_the_turn_only(settings):
    settings.base_url, settings.thinking_mode = "https://api.deepseek.com/v1", "auto"
    bodies = []
    replies = [
        stream({"choices": [{"delta": {"reasoning_content": "需要算"}}]},
               {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "function": {"name": "run_python", "arguments": "{}"}}]},
                             "finish_reason": "tool_calls"}]}),
        stream({"choices": [{"delta": {"content": "391"}, "finish_reason": "stop"}]}),
        stream({"choices": [{"delta": {"content": "新问题的回答"}, "finish_reason": "stop"}]}),
    ]

    def handler(req):
        bodies.append(json.loads(req.content))
        return replies[len(bodies) - 1]

    m = model_with(settings, handler)
    first = await m.port([{"role": "user", "content": "17×23"}], m.route, lambda _t: None)
    history = [{"role": "user", "content": "17×23"},
               {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call_9", "type": "function", "function": {"name": "run_python", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "call_9", "content": "391"}]
    assert first["tool_calls"][0]["id"] == "call_9"
    await m.port(history, m.route, lambda _t: None)
    assert bodies[1]["messages"][1]["reasoning_content"] == "需要算", "同一轮工具调用过程中要把思考回传给 DeepSeek"
    m.new_turn()
    await m.port(history + [{"role": "user", "content": "下一个问题"}], m.route, lambda _t: None)
    assert "reasoning_content" not in bodies[2]["messages"][1], "新一轮不再回传上一轮的思考"


async def test_bailian_also_gets_reasoning_back(settings):
    settings.base_url, settings.thinking_mode = "https://dashscope.aliyuncs.com/compatible-mode/v1", "auto"
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        if len(bodies) == 1:
            return stream({"choices": [{"delta": {"reasoning_content": "想"}}]},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "t", "arguments": "{}"}}]},
                                        "finish_reason": "tool_calls"}]})
        return stream({"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]})

    m = model_with(settings, handler)
    await m.port([{"role": "user", "content": "x"}], m.route, lambda _t: None)
    msgs = [{"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}]
    await m.port(msgs, m.route, lambda _t: None)
    assert bodies[1]["messages"][0]["reasoning_content"] == "想", "百炼实测: 回传后更快更稳"


async def test_unverified_providers_never_get_reasoning_in_messages(settings):
    settings.base_url, settings.thinking_mode = "https://openrouter.ai/api/v1", "auto"
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        if len(bodies) == 1:
            return stream({"choices": [{"delta": {"reasoning_content": "想"}}]},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "t", "arguments": "{}"}}]},
                                        "finish_reason": "tool_calls"}]})
        return stream({"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]})

    m = model_with(settings, handler)
    await m.port([{"role": "user", "content": "x"}], m.route, lambda _t: None)
    msgs = [{"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}]
    await m.port(msgs, m.route, lambda _t: None)
    assert "reasoning_content" not in bodies[1]["messages"][0]


async def test_summaries_never_ask_for_thinking(settings):
    settings.base_url, settings.thinking_mode = "https://api.deepseek.com/v1", "auto"
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    m = model_with(settings, handler)
    await m.complete([{"role": "user", "content": "x"}])
    assert "thinking" not in seen["body"], "压缩摘要这种后台调用不开思考, 省时省钱"


async def test_run_turn_emits_thinking_before_each_step(settings):
    fake = FakeModel([{"thinking": "要先算一下", "tool_calls": [call("list_files")]},
                      {"thinking": "结果够了, 可以答", "content": "工作区是空的"}])
    h = Harness(settings, model=fake)
    evs = [ev async for ev in h.run_turn([], "工作区里有什么")]
    kinds = [e["event"] for e in evs]
    first_think, first_step = kinds.index("thinking"), kinds.index("step")
    assert first_think < first_step, kinds
    texts = [e["text"] for e in evs if e["event"] == "thinking"]
    assert "".join(texts) == "要先算一下结果够了, 可以答"
    assert evs[-1]["event"] == "done" and evs[-1]["answer"] == "工作区是空的"
    assert all("要先算一下" not in json.dumps(m, ensure_ascii=False) for m in evs[-1]["history"]), "思考不进给模型的历史"
    await h.close()


def test_web_records_thinking_per_step_and_before_answer(settings):
    fake = FakeModel([{"thinking": "先看看有哪些文件", "tool_calls": [call("list_files")]},
                      {"thinking": "可以回答了", "content": "工作区是空的"}])
    app = create_app(settings, harness=Harness(settings, model=fake))
    with TestClient(app) as c:
        sid = c.post("/api/sessions").json()["id"]
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "工作区里有什么"})
        evs = [json.loads(line[5:]) for line in r.text.split("\n") if line.startswith("data:")]
        assert [e["event"] for e in evs].count("thinking") == 2
        rec = c.get(f"/api/sessions/{sid}").json()["transcript"][1]
        assert rec["steps"][0]["thinking"] == "先看看有哪些文件"
        assert rec["thinking"] == "可以回答了" and rec["text"] == "工作区是空的"
        assert c.get("/api/info").json()["thinking"] is False, "假模型没有思考开关"
