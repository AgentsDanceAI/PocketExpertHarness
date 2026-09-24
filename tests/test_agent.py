# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio

from conftest import FakeModel, call

from pocketexpert_harness.agent import Harness, project_history, repair_tool_pairs
from pocketexpert_harness.kernel.loop import Inbox, SessionLog


async def run(h, history, text, inbox=None):
    events = [ev async for ev in h.run_turn(history, text, inbox=inbox)]
    return events, events[-1]


async def test_tool_call_then_answer(settings):
    model = FakeModel([
        {"content": "先写个文件", "tool_calls": [call("write_file", {"path": "a.txt", "content": "hello"})]},
        {"content": "写好了 a.txt"},
    ])
    h = await Harness(settings, model=model).start()
    try:
        events, done = await run(h, [], "写个文件")
    finally:
        await h.close()
    kinds = [e["event"] for e in events]
    assert kinds[0] == "turn_start" and "step" in kinds and "observation" in kinds
    assert done["event"] == "done" and done["answer"] == "写好了 a.txt" and done["kind"] == "completed"
    assert (settings.workspace / "a.txt").read_text() == "hello"
    obs = next(e for e in events if e["event"] == "observation")
    assert obs["ok"] and "已写入" in obs["summary"]
    # 第二次请求里带着工具结果 (原生协议: assistant tool_calls + tool 消息)
    second = model.calls[1]["messages"]
    assert any(m.get("role") == "tool" for m in second)
    assert model.calls[0]["messages"][0]["role"] == "system" and "工作区目录" in model.calls[0]["messages"][0]["content"]


async def test_history_carries_into_next_turn(settings):
    model = FakeModel([{"content": "你好, 小明"}, lambda msgs: {"content": "你叫小明" if any("我叫小明" in (m.get("content") or "") for m in msgs) else "不知道"}])
    h = await Harness(settings, model=model).start()
    try:
        _, d1 = await run(h, [], "我叫小明")
        _, d2 = await run(h, d1["history"], "我叫什么?")
    finally:
        await h.close()
    assert d2["answer"] == "你叫小明"
    roles = [m["role"] for m in d2["history"]]
    assert roles == ["user", "assistant", "user", "assistant"]


async def test_step_cap_triggers_wrap_up(settings):
    settings.max_steps = 2
    loop_forever = [{"content": "", "tool_calls": [call("list_files", {}, f"c{i}")]} for i in range(2)]
    model = FakeModel(loop_forever + [{"content": "根据已有信息: 工作区是空的"}])
    h = await Harness(settings, model=model).start()
    try:
        events, done = await run(h, [], "看看工作区")
    finally:
        await h.close()
    assert done["kind"] == "blocked"
    assert done["answer"] == "根据已有信息: 工作区是空的"
    assert any(e["event"] == "notice" and e.get("kind") == "wrap_up" for e in events)
    assert model.calls[-1]["tools"] is None     # 收尾那次不带工具


async def test_steer_reaches_next_step(settings):
    inbox = Inbox()

    def first(msgs):
        inbox.steer("改成只列 md 文件")
        return {"content": "", "tool_calls": [call("list_files", {})]}

    def second(msgs):
        said = any("改成只列 md 文件" in (m.get("content") or "") for m in msgs)
        return {"content": "收到补充" if said else "没收到"}

    h = await Harness(settings, model=FakeModel([first, second])).start()
    try:
        events, done = await run(h, [], "列文件", inbox=inbox)
    finally:
        await h.close()
    assert any(e["event"] == "steer" for e in events)
    assert done["answer"] == "收到补充"


async def test_tool_error_is_returned_to_model(settings):
    model = FakeModel([{"content": "", "tool_calls": [call("read_file", {"path": "../../etc/passwd"})]}, {"content": "读不了"}])
    h = await Harness(settings, model=model).start()
    try:
        events, done = await run(h, [], "读 passwd")
    finally:
        await h.close()
    obs = next(e for e in events if e["event"] == "observation")
    assert not obs["ok"] and "越出工作区" in obs["summary"]
    assert done["answer"] == "读不了"


async def test_model_failure_wraps_up_or_reports(settings):
    model = FakeModel([RuntimeError("HTTP 400 bad request"), RuntimeError("HTTP 400 again")])
    h = await Harness(settings, model=model).start()
    try:
        _, done = await run(h, [], "你好")
    finally:
        await h.close()
    assert done["kind"] == "error"
    assert "收尾调用也失败了" in done["answer"]


def test_project_history_drops_nudges_and_repairs_pairs():
    log = SessionLog()
    log.append("user/message", content="问题", source="user")
    log.append("assistant/message", content="{坏输出")
    log.append("user/message", content="格式不对", source="nudge")
    log.append("assistant/message", content="", tool_call={"id": "x", "name": "t", "args": {}},
               tool_calls=[{"id": "x", "name": "t", "args": {}}, {"id": "y", "name": "t", "args": {}}])
    log.append("tool/result", call_id="x", tool="t", content="ok")
    assert repair_tool_pairs(log) == 1
    hist = project_history(log)
    assert [m["role"] for m in hist] == ["user", "assistant", "tool", "tool"]
    assert hist[3]["tool_call_id"] == "y" and "未执行" in hist[3]["content"]


async def test_cancel_propagates(settings):
    async def slow(msgs):
        await asyncio.sleep(10)
    class Slow(FakeModel):
        async def port(self, messages, route, on_delta, *, tools=None):
            await asyncio.sleep(10)
    h = await Harness(settings, model=Slow()).start()
    task = asyncio.create_task(run(h, [], "慢"))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
        raise AssertionError("应该被取消")
    except asyncio.CancelledError:
        pass
    finally:
        await h.close()


async def test_skill_autoload_injects_matching_skill(settings):
    seen = {}

    def first(msgs):
        seen["injected"] = any("调研简报" in (m.get("content") or "") and m["role"] == "user" for m in msgs)
        return {"content": "简报如下"}
    h = await Harness(settings, model=FakeModel([first])).start()
    try:
        events, done = await run(h, [], "帮我调研一下国产数据库, 出个简报")
    finally:
        await h.close()
    assert seen["injected"]
    assert any(e["event"] == "notice" and e.get("kind") == "skills_loaded" and "research-brief" in e["reason"] for e in events)
    assert not any("调研简报" in m["content"] for m in done["history"])     # 注入的技能正文不进历史


async def test_search_brake_and_duplicate_query(settings):
    import httpx
    settings.searxng_url = "http://searx.local"
    queries = ["国产数据库 市场份额", "国产数据库市场份额", "达梦 份额", "人大金仓 份额", "OceanBase 份额", "TiDB 份额", "openGauss 份额"]
    script = [{"content": "", "tool_calls": [call("web_search", {"query": q}, f"s{i}")]} for i, q in enumerate(queries)]
    braked = {}

    def last(msgs):
        braked["seen"] = any("已经搜索了" in (m.get("content") or "") for m in msgs)
        return {"content": "收尾"}
    script.append(last)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []})))
    h = await Harness(settings, model=FakeModel(script), http_client=http).start()
    try:
        events, done = await run(h, [], "查一下")
    finally:
        await h.close()
    obs = [e for e in events if e["event"] == "observation"]
    assert "几乎一样" in obs[1]["summary"]          # 第二个关键词只差一个空格, 没有真搜
    assert braked["seen"] and done["answer"] == "收尾"
