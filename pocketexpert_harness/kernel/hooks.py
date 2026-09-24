# SPDX-License-Identifier: Apache-2.0
# 由口袋专家 AI 私有仓原样导出 (turn_hooks.py), 请勿在此修改 —— 改动请提 issue, 上游改完后重新导出。
"""回合钩子 (2026-09-03, 三个挂载点: 步前、请求、请求出错 —— agent/pre-step、agent/request、agent/request-error、
agent/turn-stopping 四个事件)。

把"这一步进不进"、"发给模型什么"、"用哪个模型"、"失败要不要重试"、"模型停了还要不要继续"
都做成插件事件, 内核里没有硬编码的预算。我们同样, 四张注册表, agent_loop.ReactLoop 每一步调用:
  · PRE_STEP      (ctx, messages) -> messages | PreStepDecision | None   瀑布: 改写本步认领的消息, 或 reject 拦下
                   (预算/步数/时长就在这里 reject — 对应 blocked 结局)
  · REQUEST       (ctx, route)    -> route                              瀑布: 换本步的模型路由 {url, model, key}
  · REQUEST_ERROR (ctx, failure)  -> "retry" | None                     瀑布: 模型调用失败要不要重试
  · TURN_STOPPING (ctx, inbox)    -> None                               串行: 模型自己停了 (没有工具调用) 且收件箱空时
                   最后插一次话 — 想让它继续就往 inbox 放消息 (inject), 什么都不放就结束
默认插件: 步数 / 时长 (AGENT_TURN_WALL_S, 默认 3600) 两个 pre-step 拦截, 与一个瞬时错误重试
(超时/5xx/429/连接, 最多 2 次)。都是"能力", 不是"判定" — 判定归模型。

⛔ **没有费用闸**: 按 tokens × 牌价估出来的回合费用上限, 实践中拦下的全是合法的长任务
(如逐段生成的媒体任务), 没有一次是真的跑飞; 而且估算口径与真实计费往往对不上。
管钱放在真正花钱的地方 (调用方的审批、余额、平台熔断); 跑飞由步数与时长两道挡。
插件抛异常 = 让路, 回合不因钩子坏了而崩。
每次运行还可以带**局部插件** (run_* 的 extra 参数): 引擎把只对这次任务成立的守卫 (如"目标要求发邮件、
还没登记就想收口") 挂上去, 不进全局表。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class TurnContext:
    tenant_id: str = ""
    task_id: str = ""
    turn: int = 1
    step: int = 0                       # 即将开始 / 正在进行的这一步
    max_steps: int = 0
    started_at: float = field(default_factory=time.time)
    metrics: dict = field(default_factory=dict)     # 引擎的用量埋点 (tokens/llm_calls…)
    model: str = ""
    extra: dict = field(default_factory=dict)       # 引擎塞给插件看的运行态 (goal / workspace / steps_log …)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at



@dataclass
class PreStepDecision:
    kind: str = "enter"                 # enter | reject
    messages: list = field(default_factory=list)
    reason: str = ""


def reject(reason: str) -> PreStepDecision:
    return PreStepDecision(kind="reject", reason=str(reason or "被插件拦下"))


PreStep = Callable[[TurnContext, list], Awaitable[Any]]
Request = Callable[[TurnContext, dict], Awaitable[dict]]
RequestError = Callable[[TurnContext, dict], Awaitable[Optional[str]]]
Stopping = Callable[[TurnContext, Any], Awaitable[None]]

PRE_STEP: list[tuple[str, PreStep]] = []
REQUEST: list[tuple[str, Request]] = []
REQUEST_ERROR: list[tuple[str, RequestError]] = []
TURN_STOPPING: list[tuple[str, Stopping]] = []


def _reg(table: list, name: str):
    def _wrap(fn):
        table[:] = [(n, f) for n, f in table if n != name] + [(name, fn)]
        return fn
    return _wrap


def pre_step(name: str):
    return _reg(PRE_STEP, name)


def request(name: str):
    return _reg(REQUEST, name)


def request_error(name: str):
    return _reg(REQUEST_ERROR, name)


def turn_stopping(name: str):
    return _reg(TURN_STOPPING, name)


def _named(extra: Iterable) -> list[tuple[str, Callable]]:
    out = []
    for item in extra or ():
        if isinstance(item, tuple) and len(item) == 2:
            out.append((str(item[0]), item[1]))
        elif callable(item):
            out.append((getattr(item, "__name__", "local"), item))
    return out


async def run_pre_step(ctx: TurnContext, messages: list, extra: Iterable = ()) -> PreStepDecision:
    for name, fn in list(PRE_STEP) + _named(extra):
        try:
            out = await fn(ctx, messages)
        except Exception:
            logger.exception("[turn-hooks] pre_step 插件 %s 异常, 让路", name)
            continue
        if isinstance(out, PreStepDecision):
            if out.kind == "reject":
                return PreStepDecision(kind="reject", reason=f"{out.reason or '被插件拦下'} ({name})")
            messages = out.messages
        elif isinstance(out, list):
            messages = out
    return PreStepDecision(kind="enter", messages=messages)


async def run_request(ctx: TurnContext, route: dict, extra: Iterable = ()) -> dict:
    for name, fn in list(REQUEST) + _named(extra):
        try:
            out = await fn(ctx, dict(route))
            if isinstance(out, dict) and out.get("url") and out.get("model"):
                route = out
        except Exception:
            logger.exception("[turn-hooks] request 插件 %s 异常, 让路", name)
    return route


async def run_request_error(ctx: TurnContext, failure: dict, extra: Iterable = ()) -> Optional[str]:
    for name, fn in list(REQUEST_ERROR) + _named(extra):
        try:
            action = await fn(ctx, dict(failure))
        except Exception:
            logger.exception("[turn-hooks] request_error 插件 %s 异常, 让路", name)
            continue
        if action == "retry":
            return "retry"
    return None


async def run_turn_stopping(ctx: TurnContext, inbox: Any, extra: Iterable = ()) -> None:
    for name, fn in list(TURN_STOPPING) + _named(extra):
        try:
            await fn(ctx, inbox)
        except Exception:
            logger.exception("[turn-hooks] turn_stopping 插件 %s 异常, 让路", name)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key) or default)
    except (TypeError, ValueError):
        return default


@pre_step("step_cap")
async def _step_cap(ctx: TurnContext, messages: list):
    if ctx.max_steps and ctx.step > ctx.max_steps:
        return reject(f"步数到上限 {ctx.max_steps}")
    return None



@pre_step("wall_cap")
async def _wall_cap(ctx: TurnContext, messages: list):
    # 默认 3600 秒 (原先 900): 多段媒体生成 + 拼接这类长任务本来就要跑半小时以上, 900 秒会误伤。
    # 这道闸防的是"永远挂着" (用户等不到结果、槽位占着), 不是为了控成本。
    cap = _env_float("AGENT_TURN_WALL_S", 3600.0)
    if cap > 0 and ctx.elapsed >= cap:
        return reject(f"本轮耗时 {int(ctx.elapsed)}s 到上限 {int(cap)}s")
    return None


_TRANSIENT_RE = re.compile(r"timeout|timed out|read operation|connect|reset by peer|502|503|504|429|rate ?limit|overloaded", re.I)
_MAX_RETRIES = 2


@request_error("transient_retry")
async def _transient_retry(ctx: TurnContext, failure: dict) -> Optional[str]:
    """瞬时错误 (超时/网关 5xx/限流/连接) 重试最多 2 次, 退避 1s·2s; 其它错误 (4xx 参数错/鉴权) 不重试。
    一次读超时不该废掉整条任务连同已经做完的规划, 而这类超时多半是上游一次性拥塞。"""
    attempt = int(failure.get("attempt") or 1)
    if attempt > _MAX_RETRIES:
        return None
    if not _TRANSIENT_RE.search(f"{failure.get('type') or ''} {failure.get('message') or ''}"):
        return None
    await asyncio.sleep(float(attempt))
    return "retry"


_NARRATION_RE = re.compile(
    r"(信息足够|资料足够|数据齐了|现在(我)?(开始|来|可以)?(成文|撰写|写|整理|作答|回答|给出)|接下来(我)?(将|会|来)|我(将|会|来)(为你|给你)?(写|整理|成文|输出|给出)"
    r"|开始(成文|撰写|写作|整理)|直接照它执行|先加载|即将(成文|输出)|下面(我)?(开始|来)|let me (write|draft|compose)|i('ll| will) (now )?(write|draft|compose)"
    # 自言自语式收尾: 用户要两个数字, 收到的「答案」是「…多源完全一致。事实已足够，收口。」
    # 加一串参考文献, 数字一个没给 —— 这是模型写给自己的查证小结, 不是给用户的正文。
    r"|(事实|信息|资料|证据|数据|依据)(已经?|都|均|基本)?(足够|够了|够用|齐全|充分)"
    r"|收口|就此打住|到此为止|查证完毕|核实完毕|可以结束了"
    r"|(足以|已经可以|已可)(作答|回答|下结论|给出结论|成文|交付)"
    r"|(enough|sufficient) (info|information|evidence|data)|wrap(ping)? (this |it )?up|done (researching|verifying))",
    re.I)
_NARRATION_MAX_CHARS = 400


@turn_stopping("narration_guard")
async def _narration_guard(ctx: TurnContext, inbox: Any) -> None:
    """过渡语不是答案: 模型在一次失败的工具调用之后回了一句「…信息足够成文了。」而没调工具,
    驱动器会把它当成最终答案, 用户只收到两行元叙述加参考文献。模型停了但最后一条很短且像"我接下来要…"
    → 往收件箱放一句让它直接输出正文; 一个回合只催一次, 催完还这样就随它 (别死循环)。"""
    ans = str(ctx.extra.get("last_answer") or "").strip()
    if not ans or len(ans) > _NARRATION_MAX_CHARS or ctx.extra.get("narration_nudged"):
        return
    if "\n#" in ans or ans.startswith("#"):
        return                       # 已经是带标题的正文
    if not _NARRATION_RE.search(ans):
        return
    ctx.extra["narration_nudged"] = True
    inbox.inject("你上一条是过渡语 (说你要做什么), 不是给用户的正文。现在直接输出给用户的最终回答完整正文 — 不要描述你要做什么, 不要客套。")
    logger.info("[turn-hooks] task=%s 过渡语不是答案, 催正文: %s", ctx.task_id, ans[:60])


def describe() -> dict:
    return {"pre_step": [n for n, _ in PRE_STEP], "request": [n for n, _ in REQUEST],
            "request_error": [n for n, _ in REQUEST_ERROR], "turn_stopping": [n for n, _ in TURN_STOPPING]}
