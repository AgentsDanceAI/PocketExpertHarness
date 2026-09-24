# SPDX-License-Identifier: Apache-2.0
"""Harness: 把内核 (kernel.loop.ReactLoop) 的三个端口接上 —— 模型、工具、系统提示。

一个进程一个 Harness; 每一轮对话新建一个内核回合: 用会话历史播种会话日志, 把用户这句话放进收件箱, 跑到模型停下。
回合结束后把 (可能已被压缩的) 会话日志投影回历史存起来, 下一轮接着用。
"""
from __future__ import annotations

import functools
import logging
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

from pocketexpert_harness.config import Settings
from pocketexpert_harness.kernel import hooks
from pocketexpert_harness.kernel.loop import PING, Inbox, ReactLoop, SessionLog, heartbeat
from pocketexpert_harness.llm import ChatModel
from pocketexpert_harness.mcp import MCPManager
from pocketexpert_harness.memory import Memory
from pocketexpert_harness.prompt import build_system_prompt
from pocketexpert_harness.skills import catalog_text, discover, match
from pocketexpert_harness.skills import make_tool as make_skill_tool
from pocketexpert_harness.tools import ToolRegistry, turn_state
from pocketexpert_harness.tools import local as local_tools
from pocketexpert_harness.tools import web as web_tools

logger = logging.getLogger(__name__)

#: 回合没给出答案 (步数/时长到上限、连续格式错、卡住) 时, 带着已有信息再要一次最终回答
WRAP_UP = ("到这里先停止调用工具。根据上面已经拿到的信息, 直接给用户完整的最终回答;"
           "没查到或没做完的部分如实说明。")
_NO_ANSWER_REASONS = {"malformed", "stuck", "empty"}
#: 一轮里搜索满这么多次, 提醒一次"用已有信息收尾" (模型常常为一个查不到的数字换着说法搜几十次)
SEARCH_BRAKE_AT = 6


def skill_autoload(skills: dict):
    """步前插件: 第一步开始前, 用户这句话命中技能触发词, 就把技能全文作为背景注入 —— 不等模型想起来去读。"""
    async def plugin(ctx: hooks.TurnContext, messages: list):
        if ctx.step != 1 or not skills:
            return None
        picked = match(str(ctx.extra.get("goal") or ""), skills)
        if not picked:
            return None
        ctx.extra["skills_loaded"] = [sk.name for sk in picked]
        body = "\n\n".join(f"## 技能: {sk.name}\n{sk.body}" for sk in picked)
        return list(messages) + [{"kind": "inject", "raw": "", "content":
                                  f"这一轮的请求匹配到下面的技能, 按它的做法和交付格式来 (与用户的明确要求冲突时以用户为准):\n\n{body}"}]
    return plugin


def search_brake(steps_log: list, limit: int = SEARCH_BRAKE_AT):
    """步前插件: 这一轮搜索次数到 limit, 提醒一次收尾。只提醒, 不拦 —— 真缺关键事实时模型还可以接着搜。"""
    async def plugin(ctx: hooks.TurnContext, messages: list):
        if ctx.extra.get("search_braked"):
            return None
        n = sum(1 for st in steps_log if st.get("tool") == "web_search")
        if n < limit:
            return None
        ctx.extra["search_braked"] = True
        return list(messages) + [{"kind": "inject", "raw": "", "content":
                                  f"你这一轮已经搜索了 {n} 次。除非还缺一个决定性的事实, 否则停止搜索, 用已有信息给出最终回答,"
                                  "查不到的部分如实说明。"}]
    return plugin


def project_history(log: SessionLog) -> list[dict]:
    """会话日志 → 可再次播种的历史。丢掉内核的纠正提示 (nudge) 与后台注入 (inject), 以及被纠正的那条输出。"""
    events = log.events
    out: list[dict] = []
    for i, ev in enumerate(events):
        kind = ev["kind"]
        if kind == "user/message":
            if ev.get("source") in ("nudge", "inject"):
                continue
            out.append({"role": "user", "content": str(ev.get("content") or "")})
        elif kind == "assistant/message":
            nxt = next((e for e in events[i + 1:] if e["kind"] in ("user/message", "assistant/message", "tool/result")), None)
            if nxt and nxt["kind"] == "user/message" and nxt.get("source") == "nudge":
                continue
            calls = ev.get("tool_calls") or ([ev["tool_call"]] if ev.get("tool_call") else [])
            msg: dict[str, Any] = {"role": "assistant", "content": str(ev.get("content") or "")}
            if calls:
                msg["tool_calls"] = [{"id": c.get("id", ""), "name": c.get("name", ""), "args": c.get("args") or {}} for c in calls]
            out.append(msg)
        elif kind == "tool/result":
            out.append({"role": "tool", "tool_call_id": str(ev.get("call_id") or ""), "tool": str(ev.get("tool") or ""),
                        "content": str(ev.get("content") or "")})
    return out


def repair_tool_pairs(log: SessionLog) -> int:
    """原生工具协议要求每个 tool_call 都有配对的 tool 结果。回合中途出错时可能缺, 缺了下一次请求会被服务端拒绝 ——
    就地补一条"未执行"的结果。返回补了几条。"""
    fixed, i, events = 0, 0, log.events
    while i < len(events):
        ev = events[i]
        calls: list = []
        if ev["kind"] == "assistant/message":
            calls = ev.get("tool_calls") or ([ev["tool_call"]] if ev.get("tool_call") else [])
        if calls:
            j = i + 1
            seen = set()
            while j < len(events) and events[j]["kind"] not in ("assistant/message", "user/message"):
                if events[j]["kind"] == "tool/result":
                    seen.add(events[j].get("call_id"))
                j += 1
            missing = [c for c in calls if c.get("id") not in seen]
            for k, c in enumerate(missing):
                events.insert(j + k, {"kind": "tool/result", "at": ev.get("at"), "call_id": c.get("id", ""),
                                      "tool": c.get("name", ""), "content": "(未执行: 回合中途结束)"})
            fixed += len(missing)
            i = j + len(missing)
            continue
        i += 1
    return fixed


class Harness:
    def __init__(self, settings: Settings, *, model: Optional[ChatModel] = None,
                 http_client: Optional[httpx.AsyncClient] = None,
                 confirm_python: Optional[Callable[[dict], Awaitable[bool]]] = None):
        self.s = settings
        self.model = model or ChatModel(settings)
        self.http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self.memory = Memory(settings.home)
        self.mcp = MCPManager(settings.mcp_config)
        self.skills: dict = {}
        self.registry = ToolRegistry()
        self._confirm_python = confirm_python
        self.started = False

    async def start(self) -> "Harness":
        self.s.ensure_dirs()
        await self.mcp.start()
        self.skills = discover(self.s.skills_dirs)
        self.rebuild_tools()
        self.started = True
        return self

    def rebuild_tools(self) -> None:
        reg = ToolRegistry()
        for t in web_tools.make_tools(self.s, self.http):
            reg.add(t)
        for t in local_tools.make_tools(self.s, confirm_python=self._confirm_python):
            reg.add(t)
        if self.skills:
            reg.add(make_skill_tool(self.skills))
        reg.add(self.memory.tool())
        for t in self.mcp.tools():
            reg.add(t)
        self.registry = reg

    async def close(self) -> None:
        await self.mcp.close()
        await self.model.aclose()
        await self.http.aclose()

    def system_prompt(self, ctx: hooks.TurnContext) -> str:
        return build_system_prompt(name=self.s.agent_name, has_web="web_search" in self.registry.names,
                                   skills_text=catalog_text(self.skills), memory_text=self.memory.render(),
                                   workspace=str(self.s.workspace), tool_names=self.registry.names)

    async def run_turn(self, history: list[dict], message: str, *, inbox: Optional[Inbox] = None,
                       task_id: str = "") -> AsyncIterator[dict]:
        """跑一轮。产出内核事件 (dict), 最后一个是 {"event": "done", answer, kind, history, ...}。
        想中途插话: 自己建一个 Inbox 传进来, 跑的过程中调 inbox.steer("...")。"""
        if not self.started:
            await self.start()
        ctx = hooks.TurnContext(task_id=task_id or uuid.uuid4().hex[:12], max_steps=self.s.max_steps,
                                model=self.s.model, extra={"goal": message})
        log = SessionLog()
        log.seed(history or [])
        inbox = inbox or Inbox()
        inbox.followup(message)
        turn_state.set({})
        steps_log: list = []
        loop = ReactLoop(ctx=ctx, log=log, inbox=inbox, steps_log=steps_log,
                         pre_step=[("skill_autoload", skill_autoload(self.skills)), ("search_brake", search_brake(steps_log))],
                         llm=functools.partial(self.model.port, tools=self.registry.schemas() or None),
                         tools=self.registry.port, assemble=self.system_prompt,
                         tool_names=self.registry.names, route=self.model.route,
                         obs_cap=self.registry.obs_cap, summarizer=self.model.complete)
        yield {"event": "turn_start", "task_id": ctx.task_id}
        async for ev in loop.run():
            if ev == PING or isinstance(ev, str):
                continue
            yield ev
            if ctx.extra.get("skills_loaded") and not ctx.extra.get("_skills_announced"):
                ctx.extra["_skills_announced"] = True
                yield {"event": "notice", "kind": "skills_loaded", "reason": "用上技能: " + ", ".join(ctx.extra["skills_loaded"])}
        end = loop.end
        repair_tool_pairs(log)
        answer = end.answer.strip()
        if not answer and (end.kind in ("blocked", "error", "max_tokens") or end.reason in _NO_ANSWER_REASONS):
            yield {"event": "notice", "kind": "wrap_up", "reason": end.reason or end.kind}
            messages = log.derive_messages(self.system_prompt(ctx)) + [{"role": "user", "content": WRAP_UP}]
            buf: list[str] = []
            try:
                async for kind, val in heartbeat(self.model.port(messages, self.model.route, buf.append, tools=None), tick=0.2):
                    if buf:
                        yield {"event": "assistant_delta", "n": "final", "text": "".join(buf)}
                        buf.clear()
                    if kind == "done":
                        answer = str(val.get("content") or "").strip()
            except Exception as e:      # noqa: BLE001
                logger.warning("wrap-up failed: %s", e)
                answer = f"(没能给出回答: {end.reason or end.kind}; 收尾调用也失败了: {str(e)[:200]})"
            log.append("assistant/message", content=answer)
        yield {"event": "done", "answer": answer, "kind": end.kind, "reason": end.reason, "steps": end.steps,
               "history": project_history(log), "usage": dict(self.model.usage)}
