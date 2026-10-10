# SPDX-License-Identifier: Apache-2.0
# 由口袋专家 AI 私有仓原样导出 (loop.py), 请勿在此修改 —— 改动请提 issue, 上游改完后重新导出。
"""ReAct 回合驱动器。

全模块只有这一个类带"具体循环逻辑": 一个智能体一个实例, 把一条会话从头驱动到尾。
不判断"聊天还是干活", 不预设步数预算, 不做意图分类 —— 下一步做什么全部交给模型的
工具选择。程序不替模型派活 (没有强制首搜、自动读页之类的固定流程)。

结构:
  Inbox                     收件箱: 追问 / 运行中插话 / 系统注入三类消息
  SessionLog                会话日志 = 唯一事实源; derive_messages 每次请求重新推导消息
  ReactLoop.run             回合驱动: 起始 → 逐步 preStep/step → 收尾判定 → 回合结束
  ReactLoop 的步前段         认领收件箱 → 组装系统提示 → 步前钩子瀑布 (放行 / 拒绝)
  ReactLoop._step           构造请求 → 流式 → 出错钩子瀑布 (退避重试) → 助手消息 → 工具调用
  agent_turn_hooks.REQUEST  请求钩子: 可改写本步的模型路由
  agent_turn_hooks.TURN_STOPPING  收尾钩子: 模型停了让插件最后插一次话, 往收件箱放话就继续
  SessionLog.log_header     请求头只在第一次或变了才记
  SessionLog.compact        压缩 = 步前把会话原地改写成检查点
  TurnEnd.kind              回合结局: completed / max-tokens / blocked / aborted / error
  ToolResult.concluded      收口工具 (如 finish): 执行即回合完成; 工具也可借它代写一句答复 (ToolResult.answer)

引擎只提供三个端口:
  llm(messages, route, on_delta) -> {content, tool_calls, finish_reason, raw, malformed}  模型调用
  tools(call, n) -> async generator                                   工具执行: 中途 yield 进度事件, 末尾 yield ToolResult
  assemble(ctx) -> str                                                每步重装配的系统提示 (底稿 + 运行时段)
事件以 dict 产出 ({"event": …, …}); 原样 SSE 串 (上层的多智能体接力等) 直接透传; PING 是保活帧。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional

from pocketexpert_harness.kernel import hooks

logger = logging.getLogger("agentsdance.agent_loop")

NEXT_STEP = "next_step"
NEXT_TURN = "next_turn"
PING = ": ping\n\n"

STEER_PREFIX = "用户中途补充 (以此为准, 据此调整后续动作): "
# 端口报 malformed 却没附自己的 nudge 时的兜底纠正语。malformed 只剩一种含义: 工具调用的参数不是合法 JSON (多半被截断);
# 「正文长得像动作 JSON」那种猜测 2026-10-05 已删 —— 原生 function calling 下正文就是正文。
FORMAT_NUDGE = "你上一条回复里的工具调用参数不是合法 JSON (可能被截断)。请重新调用该工具, 参数写短一点。"
REPEAT_NUDGE = "输出与上一轮完全相同。请换一个策略, 或用 finish 进入总结。"
MAX_PARSE_FAILS = 4          # 连续工具参数格式错误的容忍次数, 超过按"没有答案"收口
MAX_DUP_RAWS = 2             # 连续一模一样的输出: 先提醒, 再犯强退 (卡死检测)
CONCLUDING_TOOLS = frozenset({"finish", "final", "done"})
OBSERVATION_SSE_CHARS = 600
MAX_CALLS_PER_STEP = 10      # 一步里最多执行的工具调用数 (默认 10; 这里按串行档逐个跑)


# ── 收件箱 ─────────────────────────────────────────────────────────────────

class Inbox:
    """两个队列: next_turn (下一轮开头才看) 与 next_step (下一步开始前就看)。
    followup = 下一轮; steer = 下一步 (用户插话, 前端行内可见); inject = 下一步 (后台上下文, 静默)。
    单次运行里泵一直在跑, 没有"唤醒"这个动作, 三者只差进哪个队列与来源标记。
    drain_external 是跨 worker 送达的收件箱 (agent_steer), claim 时先把它拉进来。"""

    def __init__(self, drain_external: Optional[Callable[[], list]] = None):
        self.next_step: list[dict] = []
        self.next_turn: list[dict] = []
        self._drain_external = drain_external

    def send(self, message: dict, target: str = NEXT_STEP) -> None:
        (self.next_turn if target == NEXT_TURN else self.next_step).append(dict(message))

    def followup(self, text: str) -> None:
        self.send({"kind": "user", "content": str(text)}, NEXT_TURN)

    def steer(self, text: str) -> None:
        self.send({"kind": "steer", "content": STEER_PREFIX + str(text), "raw": str(text)}, NEXT_STEP)

    def inject(self, text: str) -> None:
        self.send({"kind": "inject", "content": str(text)}, NEXT_STEP)

    def pull_external(self) -> int:
        if self._drain_external is None:
            return 0
        try:
            texts = list(self._drain_external() or [])
        except Exception:
            logger.exception("[loop] 外部收件箱读取失败, 忽略")
            texts = []
        for t in texts:
            self.steer(str(t))
        return len(texts)

    def claim(self, target: str) -> list[dict]:
        """认领: next-turn 目标把两个队列都取走 (回合开头), next-step 只取下一步队列。"""
        self.pull_external()
        if target == NEXT_TURN:
            out = self.next_turn + self.next_step
            self.next_turn, self.next_step = [], []
        else:
            out, self.next_step = self.next_step, []
        return out

    def has_next_step(self) -> bool:
        self.pull_external()
        return bool(self.next_step)

    @property
    def has_pending(self) -> bool:
        return bool(self.next_step or self.next_turn)


# ── 会话日志 ───────────────────────────────────────────────────────────────

_BODY_KINDS = ("user/message", "assistant/message", "tool/result")

#: 会话日志越过这个字数才压缩: 上下文窗口 200K 量级的模型留出余量, 150K 起压。
#: 调用方若在入口按字数截断跨轮历史, 两处**必须同值** —— 入口放进 150K、屋里却在 90K 就压,
#: 等于种进来的历史当场被压掉一半。调用方从这里取值, 别各写一个默认值 (改一处就漂)。
DEFAULT_CHECKPOINT_CHARS = 150_000

# ── 摘要式压缩 (2026-09-05) ──
# 摘要指令作为**最后一条 user 消息**接在被压缩的前缀后面 (不是另起一套系统提示): 这次辅助调用是最近一次
# 请求的真前缀, 供应商的 KV 缓存能复用。产出结构化检查点, 用标签包住替换掉前缀; 尾巴原样保留。
SUMMARY_OPEN_TAG, SUMMARY_CLOSE_TAG = "<compacted-summary>", "</compacted-summary>"
COMPACTION_INSTRUCTION = (
    "你现在是这段对话的压缩引擎。把**上面**的对话浓缩成一份结构化检查点, 让另一个模型据此无损接着干。\n\n"
    "严格按下面的 Markdown 结构输出, 每一节都保留、顺序不变, 用短要点不用长段落, 空的一节写「(无)」:\n\n"
    "## 用户的目标与演变\n- [最初与后来的要求; 原话重要的地方原样引用]\n\n"
    "## 已查到的事实、数据与来源\n- [保留原文数字、专名、日期、链接与引用编号]\n\n"
    "## 已交付的产出\n- [标题、结构与关键内容; 成品全文若很长只留要点]\n\n"
    "## 出过的错与处理\n- [错误: 怎么解决的, 以及用户的反馈]\n\n"
    "## 未完成的事\n- [用户明确要过但还没做完的]\n\n"
    "## 当前进展\n- [到这个检查点为止正在做什么]\n\n"
    "## 下一步\n- [紧接最近一条要求的那一个动作, 或「(无)」]\n\n"
    "## 关键约束与用户偏好\n- [拍板与理由、口径、偏好、待定问题、继续所需的数据]\n\n"
    "规则:\n- 用简洁的中文; 文件路径、命令、报错原文、标识符、数字、函数签名原样保留。\n"
    "- 忠实记录用户的反馈与明确指令, 尤其是纠正。\n- 不要提这次压缩本身。\n- 只输出检查点正文: 不要调用工具, 不要做别的动作。\n"
    f"- 如果上面已经有 {SUMMARY_OPEN_TAG} 块, 那是更早的检查点: 不要原样照抄, 保留仍成立的事实, 丢掉过时的, 并入新信息。")
CHECKPOINT_PREAMBLE = ("这是一份自动生成的检查点, 浓缩了这段对话更早的部分以腾出上下文。把其中的内容当作已确立的背景, "
                       "在它的基础上继续; 后面的消息是之后真实发生的。")


class SessionLog:
    """会话日志 = 唯一事实源: 每个请求的消息都由它当场推导, 不复用上一次的结果。
    引擎不再手工维护 messages 列表; 每一步发给模型的消息都由 derive_messages 从日志推导。

    工具调用一律走原生 function calling, 日志只有这一套渲染。"""

    def __init__(self, checkpoint_chars: int = 0):
        self.events: list[dict] = []
        # 轨迹 = 只追加、不压缩的副本 (每条事件的浅拷贝): 压缩会原地截短 / 替换 events 里的前缀, 轨迹不受影响,
        # 回合结束后原样落库, 供轨迹视图与会话日志导出。derive_messages 只读 events, 与它无关。
        self.trace: list[dict] = []
        self._last_system: Optional[str] = None
        self.threshold = int(checkpoint_chars or os.environ.get("AGENT_TRIM_CHECKPOINT_CHARS", "")
                             or DEFAULT_CHECKPOINT_CHARS)
        self.compactions = 0

    def append(self, kind: str, **payload) -> dict:
        ev = {"kind": kind, "at": time.time(), **payload}
        self.events.append(ev)
        self.trace.append(dict(ev))
        return ev

    def log_system(self, system: str) -> bool:
        """系统提示只在第一次或变了才进轨迹 (request/system, 带全文): 平常整个回合只有一份。
        不是 body 事件, 不参与推导与压缩。"""
        if system == self._last_system:
            return False
        first = self._last_system is None
        self._last_system = system
        ev = {"kind": "request/system", "at": time.time(), "reason": "initial" if first else "change",
              "chars": len(system or ""), "content": system or ""}
        self.trace.append(ev)
        return True

    def body(self) -> list[dict]:
        return [ev for ev in self.events if ev["kind"] in _BODY_KINDS]

    def total_chars(self) -> int:
        return sum(len(str(ev.get("content") or "")) for ev in self.body())

    def last_header(self) -> Optional[dict]:
        for ev in reversed(self.events):
            if ev["kind"] == "request/header":
                return ev
        return None

    def log_header(self, header: dict) -> bool:
        """request/header 只在第一次或变了才写 (首次 / 变更), 让任何一步的请求都能从日志重放。
        ⚠️ 调用方别把密钥放进 header。"""
        last = self.last_header()
        if last is not None and {k: v for k, v in last.items() if k not in ("kind", "at", "reason")} == header:
            return False
        self.append("request/header", reason="initial" if last is None else "change", **header)
        return True

    def seed(self, messages: list[dict]) -> None:
        """把历史消息 (由早到近) 直接写进日志 — 跨轮会话的前缀。
        一场对话对应**一份**会话日志, 消息由它推导; 我们每轮是一个独立任务,
        所以开工前把上几轮投影成真消息补进来, 而不是把对话改写成散文塞进第一条 user。"""
        for m in messages or []:
            role, content = str(m.get("role") or ""), str(m.get("content") or "")
            calls = [c for c in (m.get("tool_calls") or []) if isinstance(c, dict)]
            if role == "user" and content:
                self.append("user/message", content=content, seeded=True)
            elif role == "assistant" and (content or calls):
                if calls:   # 上一轮的工具轨迹 (2026-09-05): 原生协议下一条 assistant 配它的 tool 结果
                    self.append("assistant/message", content=content, seeded=True,
                                tool_call={"id": str(calls[0].get("id") or ""), "name": str(calls[0].get("name") or ""), "args": calls[0].get("args") or {}},
                                tool_calls=[{"id": str(c.get("id") or ""), "name": str(c.get("name") or ""), "args": c.get("args") or {}} for c in calls])
                else:
                    self.append("assistant/message", content=content, seeded=True)
            elif role == "tool" and content:
                self.append("tool/result", call_id=str(m.get("tool_call_id") or ""), tool=str(m.get("tool") or ""),
                            content=content, seeded=True)

    def derive_messages(self, system: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for ev in self.events:
            k = ev["kind"]
            if k == "user/message":
                msgs.append({"role": "user", "content": str(ev.get("content") or "")})
            elif k == "assistant/message":
                call = ev.get("tool_call")
                calls_ = ev.get("tool_calls") or ([call] if call else [])   # 一步多个调用 (2026-09-05); 老事件只有 tool_call
                content = str(ev.get("content") or "")
                if calls_:
                    msgs.append({"role": "assistant", "content": content or None,
                                 "tool_calls": [{"id": str(c.get("id") or ""), "type": "function",
                                                 "function": {"name": str(c.get("name") or ""),
                                                              "arguments": json.dumps(c.get("args") or {}, ensure_ascii=False)}}
                                                for c in calls_]})
                else:
                    msgs.append({"role": "assistant", "content": content})
            elif k == "tool/result":
                msgs.append({"role": "tool", "tool_call_id": str(ev.get("call_id") or ""),
                             "content": str(ev.get("content") or "")})
        return msgs

    def summary_cut(self, keep_recent: int = 16) -> int:
        """摘要式压缩的切点: body 里保留最近 keep_recent 条, 切点不落在 assistant(tool_call) 与它的 tool 结果之间
        (工具调用与结果必须成对)。返回 self.events 里的下标; 0 = 不切。"""
        body = self.body()
        if len(body) <= keep_recent + 2:
            return 0
        cut_ev = body[-keep_recent]
        i = self.events.index(cut_ev)
        # 往前退到不是 tool/result 的地方, 再把它前面配对的 assistant(tool_call) 一起归到尾巴
        while i > 0 and self.events[i]["kind"] == "tool/result":
            i -= 1
        if self.events[i]["kind"] == "assistant/message" and self.events[i].get("tool_call"):
            pass   # 这条 assistant 连同其后的 tool 结果都在尾巴里 — 正确
        return i

    def compact_with_summary(self, summary: str, keep_recent: int = 16) -> bool:
        """用一段摘要替换 body 前缀 (替换语义, 非追加): 非 body 事件 (请求头) 保留,
        被压掉的范围换成一条 user/message 检查点, 尾巴原样。"""
        i = self.summary_cut(keep_recent)
        summary = (summary or "").strip()
        if i <= 0 or len(summary) < 40:
            return False
        first_body = next((k for k, ev in enumerate(self.events) if ev["kind"] in _BODY_KINDS), None)
        if first_body is None or first_body >= i:
            return False
        removed = sum(len(str(ev.get("content") or "")) for ev in self.events[first_body:i] if ev["kind"] in _BODY_KINDS)
        if len(summary) >= removed:
            return False   # 没缩, 不算压缩
        checkpoint = {"kind": "user/message", "at": time.time(), "compacted": True,
                      "content": f"{CHECKPOINT_PREAMBLE}\n\n{SUMMARY_OPEN_TAG}\n{summary}\n{SUMMARY_CLOSE_TAG}"}
        keep_head = [ev for ev in self.events[:i] if ev["kind"] not in _BODY_KINDS]
        self.events = keep_head + [checkpoint] + self.events[i:]
        self.compactions += 1
        self.threshold = max(self.threshold, int(self.total_chars() * 1.5))
        return True

    def compact(self, keep_recent: int = 16, clip: int = 1000, head_clip: int = 3000) -> bool:
        """检查点式压缩 (压缩发生在步前, 由插件原地改写会话; 口径沿用 _cache_friendly_trim):
        总量越过阈值才做一次, **原地改写日志** — 之后的推导在稳定前缀上生长 (前缀缓存友好),
        并把阈值抬到压后的 1.5 倍, 每个检查点只付一次缓存失效。
        保留: 首条用户消息 (深水区截到 head_clip) + 最近 keep_recent 条全文; 中间较早的返回截到 clip。"""
        if self.total_chars() <= self.threshold:
            return False
        body = self.body()
        if len(body) <= 1 + keep_recent:
            return False
        deep = len(body) > 1 + keep_recent * 2
        head = body[0]
        if deep and head["kind"] == "user/message":
            c = str(head.get("content") or "")
            if len(c) > head_clip and not head.get("clipped"):
                head["content"] = c[:head_clip] + "\n…(任务开头的背景材料已截短; 完整底稿会在成文阶段重新给你)"
                head["clipped"] = True
        for ev in body[1:-keep_recent]:
            c = str(ev.get("content") or "")
            # 带 tool_call 的 assistant 消息不能截 (原生协议下要和 tool/result 配对);
            # 纯文本的 assistant 消息可以 — 种进来的历史正文一条就上万字, 不截等于没压。
            _clippable = ev["kind"] in ("tool/result", "user/message") or (
                ev["kind"] == "assistant/message" and not ev.get("tool_call"))
            if _clippable and len(c) > clip and not ev.get("clipped"):
                ev["content"] = c[:clip] + (
                    "\n…(这一轮更早的产出已截短; 若本次要改它, 先说一声让用户把它重新给你)"
                    if ev["kind"] == "assistant/message" else
                    "\n…(较早步骤的返回已截短, 关键信息在你当时的思考里)")
                ev["clipped"] = True
        self.compactions += 1
        self.threshold = max(self.threshold, int(self.total_chars() * 1.5))
        return True


def repetition_cut(s: str, *, probe: int = 64, min_period: int = 40, min_span: int = 1200, min_reps: int = 5) -> Optional[str]:
    """正文尾巴在复读就返回截掉复读后的正文 (留第一遍), 否则 None。
    判据: 末尾一段 (probe 字) 往前隔一个周期 (≥ min_period 字) 又出现, 且最后两个周期一字不差; 再顺着往前找
    它的每一次出现 (相邻两次隔 ≤ 3 个周期 —— 模型复读时会时不时插一句「我需要停止这个循环」), 串起来 ≥ min_reps 次、
    跨度 ≥ min_span 字才算复读。截在第二遍开头。
    门槛定得高是为了放过正常的重复: 空白表格模板几行一样的行、代码里几行一样的初始化, 都远到不了。"""
    n = len(s)
    if n < probe + min_span:
        return None
    tail = s[-probe:]
    j = s.rfind(tail, 0, n - 1)
    if j < 0:
        return None
    period = n - probe - j
    if period < min_period or s[n - 2 * period:n - period] != s[n - period:]:
        return None
    hits = [n - probe, j]
    while True:
        k = s.rfind(tail, max(0, hits[-1] - 3 * period), hits[-1] + probe - 1)
        if k < 0:
            break
        hits.append(k)
    first, second = hits[-1], hits[-2]
    if len(hits) < min_reps or n - first < min_span:
        return None
    back = 0                                        # 第一遍从哪开始: 两遍往前逐字对, 对不上的地方就是开头
    while back < second - first and first - back > 0 and s[first - back - 1] == s[second - back - 1]:
        back += 1
    kept = s[:second - back].rstrip()
    # 头几遍常有一两个字的出入 (「加了」/「添加了」), 对出来的开头会落在半句上 —— 退到上一个句末
    end = max(kept.rfind(c, len(kept) - period) for c in "。！？!?\n")
    return kept[:end + 1].rstrip() if end >= 0 else kept


class _RepeatWatch:
    """流式复读熔断: 模型偶尔陷进同一段话一直重复 (2026-10-10 提示词专家实录: 一段 150 字的收尾在一次调用里
    重复到输出上限, 正文 25 万字、这一步跑了 14 分钟)。每多 ~1000 字查一次尾巴, 判定复读就停掉这次调用。"""
    EVERY = 1000

    def __init__(self):
        self.parts: list[str] = []
        self.n = self.checked = 0
        self.cut: Optional[str] = None

    def feed(self, piece: str):
        if self.cut is not None or not piece:
            return
        self.parts.append(piece)
        self.n += len(piece)
        if self.n - self.checked >= self.EVERY:
            self.checked = self.n
            text = "".join(self.parts)
            self.parts = [text]
            self.cut = repetition_cut(text)

    def text(self) -> str:
        return "".join(self.parts)


def _tee(*sinks: Callable[[str], Any]) -> Callable[[str], None]:
    def _cb(piece: str):
        for f in sinks:
            f(piece)
    return _cb


class _CallMeter:
    """一次模型调用的计量 (轨迹用): 发请求的时刻、第一个字 (思考或正文) 到达的时刻、思考全文、上游回报的用量。
    只写 log.trace (model/call), 不进 events —— 发给模型的消息与它无关。"""
    REASONING_CAP = 20000

    def __init__(self):
        self.t0 = time.time()
        self.first: Optional[float] = None
        self.reasoning: list[str] = []

    def wrap(self, sink: Callable[[str], Any], *, reasoning: bool = False) -> Callable[[str], Any]:
        def _cb(piece: str):
            if self.first is None and piece:
                self.first = time.time()
            if reasoning and piece:
                self.reasoning.append(piece)
            return sink(piece)
        return _cb

    def record(self, log: "SessionLog", *, step: int, route: dict, res: Optional[dict], failure: Optional[BaseException],
               attempt: int, phase: str = "step") -> dict:
        now = time.time()
        u = (res or {}).get("usage") if isinstance(res, dict) else None
        u = u if isinstance(u, dict) else {}
        _d = u.get("prompt_tokens_details")
        ev = {"kind": "model/call", "at": now, "step": step, "phase": phase, "attempt": attempt,
              "model": str(route.get("model") or ""), "t0": self.t0, "dur": round(now - self.t0, 3),
              "ttft": round(self.first - self.t0, 3) if self.first else None,
              "prompt_tokens": int(u.get("prompt_tokens") or 0), "completion_tokens": int(u.get("completion_tokens") or 0),
              "cached_tokens": int((_d or {}).get("cached_tokens") or 0) if isinstance(_d, dict) else 0,
              "finish": str((res or {}).get("finish_reason") or "") if isinstance(res, dict) else "",
              "tool_calls": len((res or {}).get("tool_calls") or []) if isinstance(res, dict) else 0,
              "reasoning": "".join(self.reasoning)[:self.REASONING_CAP],
              "ok": failure is None and isinstance(res, dict)}
        if failure is not None:
            ev["error"] = str(failure)[:300]
        log.trace.append(ev)
        return ev


# ── 结局与端口类型 ─────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    thought: str = ""


@dataclass
class ToolResult:
    ok: bool = True
    obs: str = ""
    data: Any = None
    concluded: bool = False              # 收口工具: 这一步完成 = 回合完成
    answer: str = ""                     # 收口时平台代写的答复 (只在 concluded 时生效): 工具判定本轮到此为止,
                                         # 且原因必须原话交给用户 —— 不再交给模型转述 (如余额不足之类的硬拦截)
    speaker: Optional[dict] = None       # 署名: 多智能体协作时这一步是谁做的 (前端按它显示头像)


@dataclass
class StepEnd:
    kind: str = ""                       # "" = 工具已执行、回合继续; completed | max_tokens | error
    answer: str = ""
    reason: str = ""


@dataclass
class ThinkingDelta:
    """模型自己的思考增量 (reasoning_content, 思考开着时才有): 引擎按无事件名的 {thinking} 帧发给前端, 四端都当可见思考流。"""
    text: str = ""
    n: int = 0


@dataclass
class TurnEnd:
    kind: str = ""                       # completed | max_tokens | blocked | aborted | error
    reason: str = ""
    answer: str = ""                     # 最后一步没有工具调用时的自然语言回复 = 答案
    steps: int = 0
    max_tokens_hit: bool = False         # 粘性: 任一步撞过输出上限就记着, 回合级不清零


LlmPort = Callable[[list, dict, Callable[[str], None]], Awaitable[dict]]
ToolPort = Callable[[ToolCall, int], AsyncIterator[Any]]
Assemble = Callable[[hooks.TurnContext], str]


def _drain(buf: list) -> str:
    """取走缓冲里已有的增量并清掉这几块 —— 必须在 yield **之前**取。
    模型调用在 heartbeat 里是独立任务: yield 挂起 (消费方在写 SSE / 落库) 时它还在往 buf 里追加,
    原来「yield join(buf) → 恢复后 buf.clear()」会把挂起期间到的那几块一并清掉 (2026-10-10 实跑:
    落库思考里 "12.5" 丢了、"不得增加" 丢了)。按长度切, 回调即使从别的线程追加也不丢。"""
    n = len(buf)
    text = "".join(buf[:n])
    del buf[:n]
    return text


async def heartbeat(awaitable, tick: float = 0.5, ping_every: float = 10.0):
    """把耗时 await 变成节拍序列: 每 tick 秒 ("tick", 已等秒数) — 调用方借它冲刷流式增量;
    每 ping_every 秒一帧 ("ping", …) 喂 SSE 保活; 最后 ("done", 结果)。异常从 result() 原样抛。
    消费方中途关闭 (客户端断流) 时取消底下的任务, 别让模型调用在后台白跑。"""
    task = asyncio.ensure_future(awaitable)
    waited = since_ping = 0.0
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=tick)
            if done:
                break
            waited += tick
            since_ping += tick
            yield ("tick", waited)
            if since_ping >= ping_every:
                since_ping = 0.0
                yield ("ping", waited)
        yield ("done", task.result())
    finally:
        if not task.done():
            task.cancel()


def _as_message(m: dict) -> dict:
    kind = str(m.get("kind") or "user")
    return {"kind": kind, "content": str(m.get("content") or ""), "raw": str(m.get("raw") or m.get("content") or "")}


# ── 驱动器 ─────────────────────────────────────────────────────────────────

class ReactLoop:
    """一次运行 = 一个回合 (turn)。run() 是 async generator: 产出事件, 结束后 self.end 是回合结局。"""

    def __init__(self, *, ctx: hooks.TurnContext, log: SessionLog, inbox: Inbox,
                 llm: LlmPort, tools: ToolPort, assemble: Assemble,
                 tool_names: Iterable[str], route: dict,
                 steps_log: Optional[list] = None,
                 obs_cap: Optional[Callable[[str], int]] = None,
                 pre_step: Iterable = (), turn_stopping: Iterable = (),
                 concluding: Iterable[str] = CONCLUDING_TOOLS,
                 tick: float = 0.5, ping_every: float = 10.0,
                 speaker: Optional[dict] = None,
                 parallel: Iterable[str] = (),
                 summarizer: Optional[Callable[[list[dict]], Awaitable[str]]] = None):
        self.ctx, self.log, self.inbox = ctx, log, inbox
        self.summarizer = summarizer      # 摘要式压缩 (None = 机械截短)
        self.llm, self.tools, self.assemble = llm, tools, assemble
        self.tool_names = set(tool_names)
        self.route = dict(route)
        self.steps_log = steps_log if steps_log is not None else []
        self.obs_cap = obs_cap or (lambda _t: 1800)
        self.pre_step_plugins = list(pre_step)
        self.turn_stopping_plugins = list(turn_stopping)
        self.concluding = set(concluding)
        # 可以同时跑的工具 (如请几位专家): 同一步里连着发的几个一起开工, 其余照旧按顺序逐个跑
        self.parallel = set(parallel)
        # 这个回合的默认署名: 多智能体协作时每一步都要看得出是谁在做事 —— 编排者的回合署编排者,
        # 成员子回合署那位成员。工具自己带回来的 speaker 更具体, 优先它。
        self.speaker = dict(speaker) if speaker else None
        self.tick, self.ping_every = tick, ping_every
        self.end = TurnEnd()
        self.parse_fails = 0
        self.dup_raws = 0
        self.last_raw = ""
        self.max_tokens_hit = False

    # ── 回合 ──
    async def run(self) -> AsyncIterator[Any]:
        ctx, log, inbox = self.ctx, self.log, self.inbox
        log.append("turn/start", turn=ctx.turn)
        ctx.extra.pop("narration_nudged", None)
        target = NEXT_TURN
        turn_ends: Optional[StepEnd] = None
        step = 0
        try:
            while True:
                step += 1
                ctx.step = step
                # ── preStep: 认领收件箱 → 装配系统提示 → 压缩 → pre-step 瀑布 (enter / reject) ──
                claimed = [_as_message(m) for m in inbox.claim(target)]
                # 用户跑到一半插的话 (steer) 就在 claimed 里, 下面原样进会话日志, 由模型这一步自己读
                system = self.assemble(ctx)
                await self._compact(system, step)
                decision = await hooks.run_pre_step(ctx, claimed, extra=self.pre_step_plugins)
                if decision.kind == "reject":
                    turn_ends = StepEnd(kind="blocked", reason=decision.reason)
                    yield {"event": "notice", "kind": "turn_stopping", "n": step, "reason": decision.reason}
                    logger.info("[loop] task=%s 第 %d 步前被插件拦下: %s", ctx.task_id, step, decision.reason)
                    break
                incoming = [m for m in decision.messages if str(m.get("content") or "").strip()]
                if turn_ends is not None and not incoming:
                    break
                if step == 1 and not incoming:
                    # 撤回了的首条消息 / 被插件改空: 回合成立但不花一次模型调用
                    turn_ends = StepEnd(kind="completed", reason="empty")
                    break
                log.append("step/start", step=step)
                for m in incoming:
                    log.append("user/message", content=m["content"], source=m["kind"])
                    if m["kind"] == "steer":
                        # 落一条 steer 步骤供前端行内显示 (n-0.5 行) 与回放
                        self.steps_log.append({"n": step, "thought": m["raw"], "tool": "steer", "args": {},
                                               "ok": True, "observation": "已并入下一步", "data": None, "steer": True})
                        yield {"event": "steer", "n": step, "text": m["raw"]}
                        logger.info("[steer] task=%s 第 %d 步前并入用户补充 (%d 字)", ctx.task_id, step, len(m["raw"]))
                yield PING
                step_end: Optional[StepEnd] = None
                try:
                    async for ev in self._step(step, system):
                        if isinstance(ev, StepEnd):
                            step_end = ev
                        else:
                            yield ev
                finally:
                    log.append("step/end", step=step)
                if step_end is None:
                    step_end = StepEnd(kind="error", reason="步骤没有结局")
                if step_end.kind == "error":
                    turn_ends = step_end
                    break
                turn_ends = step_end if step_end.kind else None
                # ── 模型停了 (没有工具调用) 且收件箱空: 让插件最后插一次话; 放了话就继续 ──
                if turn_ends is not None and not inbox.has_next_step():
                    ctx.extra["last_answer"] = turn_ends.answer
                    ctx.extra["last_kind"] = turn_ends.kind
                    ctx.extra["steps_used"] = len(self.steps_log)
                    await hooks.run_turn_stopping(ctx, inbox, extra=self.turn_stopping_plugins)
                if turn_ends is not None and not inbox.has_next_step():
                    break
                target = NEXT_STEP
        except (GeneratorExit, asyncio.CancelledError):
            log.append("turn/end", turn=ctx.turn, reason="aborted")
            self.end = TurnEnd(kind="aborted", steps=step, max_tokens_hit=self.max_tokens_hit)
            raise
        except Exception as e:
            # 驱动器自身的异常包在回合边界: 引擎带着已有观察去成文, 不让整条任务 500
            logger.exception("[loop] task=%s 回合异常", ctx.task_id)
            log.append("turn/end", turn=ctx.turn, reason="error")
            self.end = TurnEnd(kind="error", reason=str(e)[:300], steps=step, max_tokens_hit=self.max_tokens_hit)
            return
        turn_ends = turn_ends or StepEnd(kind="completed")
        log.append("turn/end", turn=ctx.turn, reason=turn_ends.kind)
        self.end = TurnEnd(kind=turn_ends.kind, reason=turn_ends.reason, answer=turn_ends.answer,
                           steps=step, max_tokens_hit=self.max_tokens_hit)

    # ── 一步 ──
    async def _compact(self, system: str, step: int) -> None:
        """超阈值时先试摘要式压缩, 摘要拿不到/没缩就退回机械截短。"""
        log = self.log
        if log.total_chars() <= log.threshold:
            return
        if self.summarizer is not None:
            i = log.summary_cut()
            if i > 0:
                try:
                    prefix = [ev for ev in log.events[:i] if ev["kind"] in _BODY_KINDS]
                    tmp = SessionLog(); tmp.events = list(prefix)
                    msgs = tmp.derive_messages(system) + [{"role": "user", "content": COMPACTION_INSTRUCTION}]
                    summary = await self.summarizer(msgs)
                    if log.compact_with_summary(summary):
                        logger.info("[loop] task=%s 第 %d 步前摘要式压缩: 前缀 %d 条 → 检查点 %d 字",
                                    self.ctx.task_id, step, len(prefix), len(summary))
                        return
                except Exception:
                    logger.warning("[loop] task=%s 摘要式压缩失败, 退回机械截短", self.ctx.task_id, exc_info=True)
        log.compact()

    def _parallel_width(self, batch: list, k: int) -> int:
        """从第 k 个调用起, 连着几个可以一起跑 (都在 parallel 里、都是在场工具); 不足两个返回 1。"""
        w = 0
        while k + w < len(batch) and batch[k + w].name in self.parallel and batch[k + w].name in self.tool_names:
            w += 1
        return max(1, w)

    async def _run_parallel(self, step: int, k0: int, group: list, remain_note: str, results: list) -> AsyncIterator[Any]:
        """同一步里连着的几个可并行调用一起跑。开工帧一次发齐; 进度帧按到达顺序转出 (各带自己的号);
        谁先跑完谁先出观察。工具结果写回会话时仍按调用顺序 —— 与 tool_calls 的顺序一致。
        结果按下标写进 results。某个调用抛错只算它这一个失败 (结果交回模型), 其余的照常跑完;
        整个回合被取消 (用户停止) 时一起取消。"""
        log = self.log
        ns = [step if k0 + j == 0 else round(step + (k0 + j) / 20, 2) for j in range(len(group))]
        for call, n in zip(group, ns):
            log.trace.append({"kind": "tool/start", "at": time.time(), "n": n, "call_id": call.id, "tool": call.name})
            yield {"event": "step", "n": n, "thought": call.thought, "tool": call.name, "args": call.args,
                   **({"speaker": self.speaker} if self.speaker else {})}
        queue: asyncio.Queue = asyncio.Queue()

        async def _one(j: int, call: ToolCall, n: float) -> None:
            res: Optional[ToolResult] = None
            try:
                async for ev in self.tools(call, n):
                    if isinstance(ev, ToolResult):
                        res = ev
                    else:
                        await queue.put((j, "ev", ev))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — 一个出错不拖垮同组的其他调用
                logger.exception("[loop] task=%s 并行调用 %s 出错", self.ctx.task_id, call.name)
                res = ToolResult(ok=False, obs=f"工具 {call.name} 执行出错: {str(e)[:300]}")
            await queue.put((j, "done", res or ToolResult(ok=False, obs=f"工具 {call.name} 没有返回结果")))

        tasks = [asyncio.create_task(_one(j, c, n)) for j, (c, n) in enumerate(zip(group, ns))]
        left = len(tasks)
        try:
            while left:
                j, kind, item = await queue.get()
                if kind == "ev":
                    yield item
                    continue
                left -= 1
                call, n, result = group[j], ns[j], item
                results[j] = result
                cap = int(self.obs_cap(call.name) or 1800)
                self.steps_log.append({"n": n, "thought": call.thought, "tool": call.name, "args": call.args,
                                       "ok": result.ok, "observation": result.obs[:cap], "data": result.data,
                                       **({"speaker": result.speaker or self.speaker}
                                          if (result.speaker or self.speaker) else {})})
                yield {"event": "observation", "n": n, "tool": call.name, "ok": result.ok,
                       "summary": result.obs[:OBSERVATION_SSE_CHARS], "data": result.data}
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        for call, result in zip(group, results):
            cap = int(self.obs_cap(call.name) or 1800)
            log.append("tool/result", call_id=call.id, tool=call.name, content=f"{result.obs[:cap]}{remain_note}")

    async def _step(self, step: int, system: str) -> AsyncIterator[Any]:
        ctx, log = self.ctx, self.log
        # buildRequest: request 瀑布定本步路由 (换了就沿用), header 变了才记, 消息从日志推导
        route = await hooks.run_request(ctx, dict(self.route))
        self.route = dict(route)
        log.log_header({"model": str(route.get("model") or ""), "url": str(route.get("url") or ""),
                        "system_chars": len(system), "tools": len(self.tool_names)})
        log.log_system(system)
        messages = log.derive_messages(system)
        call_route = route
        attempt = 0
        res: Optional[dict] = None
        while True:
            attempt += 1
            deltas: list[str] = []
            thinks: list[str] = []
            failure: Optional[BaseException] = None
            res = None
            meter = _CallMeter()
            said, mused = _RepeatWatch(), _RepeatWatch()
            beats = heartbeat(self.llm(messages, {**call_route, "on_thinking": meter.wrap(_tee(thinks.append, mused.feed), reasoning=True)},
                                       meter.wrap(_tee(deltas.append, said.feed))),
                              tick=self.tick, ping_every=self.ping_every)
            try:
                async for kind, val in beats:
                    if kind == "done":
                        res = val
                    else:
                        if thinks:
                            yield ThinkingDelta(text=_drain(thinks), n=step)
                        if deltas:
                            yield {"event": "assistant_delta", "n": step, "text": _drain(deltas)}
                    if kind == "ping":
                        yield PING
                    if res is None and (said.cut is not None or mused.cut is not None):
                        # 复读熔断: 停掉这次调用 (heartbeat 关闭时取消底下的请求), 正文截到第一遍, 当这一步写完了。
                        # 思考在复读时正文多半还没开始 —— 拿到多少算多少, 空答由收口补答兜底。
                        await beats.aclose()
                        res = {"content": said.cut if said.cut is not None else said.text(), "finish_reason": "repetition"}
                        logger.warning("[loop] task=%s 第 %d 步%s复读, 已停掉这次调用 (正文 %d 字 → %d 字)", ctx.task_id, step,
                                       "正文" if said.cut is not None else "思考", said.n, len(res["content"]))
                        break
            except (GeneratorExit, asyncio.CancelledError):
                raise
            except Exception as e:      # noqa: BLE001 — 失败交给 request-error 瀑布定重试
                failure = e
            if thinks:
                yield ThinkingDelta(text=_drain(thinks), n=step)
            if deltas:
                yield {"event": "assistant_delta", "n": step, "text": _drain(deltas)}
            meter.record(log, step=step, route=route, res=res, failure=failure, attempt=attempt)
            if failure is None and isinstance(res, dict):
                break
            fail = {"message": str(failure)[:300] if failure else "模型没有返回", "type": type(failure).__name__ if failure else "Empty",
                    "attempt": attempt, "model": str(route.get("model") or "")}
            action = await hooks.run_request_error(ctx, fail)
            if action == "retry":
                yield {"event": "notice", "kind": "request_retry", "n": step, "reason": f"模型调用失败, 重试第 {attempt} 次: {fail['message'][:120]}"}
                continue
            logger.warning("[loop] task=%s 模型调用失败, 带着已有观察收口: %s", ctx.task_id, fail["message"])
            yield StepEnd(kind="error", reason=fail["message"])
            return
        content = str(res.get("content") or "").strip()
        calls = res.get("tool_calls") or []
        # 重复判定的指纹: 端口给了 raw 就用 raw, 否则 内容 + 工具调用 (同一句 thought 配不同调用不算重复)
        raw = str(res.get("raw") or "") or (content + (json.dumps(calls, ensure_ascii=False, sort_keys=True) if calls else ""))
        if res.get("malformed"):
            # 工具参数解析不出 (截断/多余字段): 不是答案, 走格式纠正; 连错 4 次按"没有答案"收口
            self.parse_fails += 1
            if self.parse_fails >= MAX_PARSE_FAILS:
                yield StepEnd(kind="completed", reason="malformed")
                return
            log.append("assistant/message", content=raw[:400])
            log.append("user/message", content=str(res.get("nudge") or FORMAT_NUDGE), source="nudge")
            yield StepEnd()
            return
        self.parse_fails = 0
        if raw and raw == self.last_raw:
            self.dup_raws += 1
            if self.dup_raws >= MAX_DUP_RAWS:
                yield StepEnd(kind="completed", reason="stuck")
                return
            log.append("assistant/message", content=raw[:400])
            log.append("user/message", content=REPEAT_NUDGE, source="nudge")
            yield StepEnd()
            return
        self.last_raw = raw
        if not calls:
            # 没有工具调用 = 这一步完成, 回复就是答案
            _cut = repetition_cut(content)
            if _cut is not None:
                # 整段一次到手 (非流式) 或复读只在最后一截: 同一道熔断, 截到第一遍; 撞上限是复读撞的, 不算截断
                logger.warning("[loop] task=%s 第 %d 步正文尾巴在复读, 截掉 (%d 字 → %d 字)", ctx.task_id, step, len(content), len(_cut))
                content, res = _cut, {**res, "finish_reason": "repetition"}
            log.append("assistant/message", content=content)
            if str(res.get("finish_reason") or "") == "length":
                self.max_tokens_hit = True
                yield {"event": "notice", "kind": "max_tokens", "n": step, "reason": "回复被输出上限截断"}
                yield StepEnd(kind="max_tokens", answer=content)
                return
            yield StepEnd(kind="completed", answer=content)
            return
        # 一步里的全部工具调用都执行 (2026-09-05; 按串行档 =1 逐个跑):
        # 原先只取 calls[0] —— 模型一步发三个搜索, 两个静默丢掉, 而且没人告诉它。
        batch: list[ToolCall] = []
        for k, c in enumerate(calls[:MAX_CALLS_PER_STEP]):
            if isinstance(c, dict):
                batch.append(ToolCall(id=str(c.get("id") or f"call_{step}_{k}"), name=str(c.get("name") or "").strip(),
                                      args=c.get("args") if isinstance(c.get("args"), dict) else {}, thought=content[:300]))
        if not batch:
            log.append("assistant/message", content=content)
            yield StepEnd(kind="completed", answer=content)
            return
        log.append("assistant/message", content=batch[0].thought,
                   tool_call={"id": batch[0].id, "name": batch[0].name, "args": batch[0].args},
                   tool_calls=[{"id": c.id, "name": c.name, "args": c.args} for c in batch])
        remain_note = f"\n\n(剩余可用步数 {max(0, ctx.max_steps - step)})" if ctx.max_steps else ""
        ran_to = 0      # 并行的一组已经跑到哪 (组里后面几个不再单独跑)
        for k, call in enumerate(batch):
            if k < ran_to:
                continue
            width = self._parallel_width(batch, k)
            if width > 1:
                group, ran_to = batch[k:k + width], k + width
                results: list = [None] * width
                async for ev in self._run_parallel(step, k, group, remain_note, results):
                    yield ev
                done = next((r for r in results if r is not None and r.concluded), None)
                if done is not None:
                    for rest in batch[ran_to:]:
                        log.append("tool/result", call_id=rest.id, tool=rest.name, content="未执行: 回合已收口。")
                    yield StepEnd(kind="completed", answer=done.answer, reason="concluded")
                    return
                continue
            # 同一步的第 k 个调用各自一个号: 前端按 n 匹配 step/observation, 同号会互相覆盖
            # (小数位 k/20 与 notice/steer 用的 ±0.25/0.5 不撞)
            n = step if k == 0 else round(step + k / 20, 2)
            if call.name not in self.tool_names:
                log.append("tool/result", call_id=call.id, tool=call.name,
                           content=f"没有名为 {call.name} 的工具, 可用: {', '.join(sorted(self.tool_names))}。请重新选择。")
                continue
            concluding = call.name in self.concluding
            log.trace.append({"kind": "tool/start", "at": time.time(), "n": n, "call_id": call.id, "tool": call.name})
            if not concluding:
                yield {"event": "step", "n": n, "thought": call.thought, "tool": call.name, "args": call.args,
                       **({"speaker": self.speaker} if self.speaker else {})}
            result: Optional[ToolResult] = None
            async for ev in self.tools(call, n):
                if isinstance(ev, ToolResult):
                    result = ev
                else:
                    yield ev
            if result is None:
                result = ToolResult(ok=False, obs=f"工具 {call.name} 没有返回结果")
            cap = int(self.obs_cap(call.name) or 1800)
            log.append("tool/result", call_id=call.id, tool=call.name, content=f"{result.obs[:cap]}{remain_note}")
            if not concluding:
                self.steps_log.append({"n": n, "thought": call.thought, "tool": call.name, "args": call.args,
                                       "ok": result.ok, "observation": result.obs[:cap], "data": result.data,
                                       **({"speaker": result.speaker or self.speaker}
                                          if (result.speaker or self.speaker) else {})})
                yield {"event": "observation", "n": n, "tool": call.name, "ok": result.ok,
                       "summary": result.obs[:OBSERVATION_SSE_CHARS], "data": result.data}
            if result.concluded:
                # 收口工具结束回合; 同批后面的不再执行, 但各留一条结果 — 原生协议里每个 tool_call 都得有配对的 tool 消息
                for rest in batch[k + 1:]:
                    log.append("tool/result", call_id=rest.id, tool=rest.name, content=f"未执行: 回合已由 {call.name} 收口。")
                yield StepEnd(kind="completed", answer=result.answer, reason="concluded")
                return
        yield StepEnd()
