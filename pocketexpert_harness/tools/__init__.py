# SPDX-License-Identifier: Apache-2.0
"""工具注册表 → 内核的 tools 端口。

一个工具 = 名字 + 说明 + JSON Schema 参数 + 异步处理函数。处理函数返回字符串 (观察) 或 ToolResult;
抛异常会被包成失败的观察交还模型, 回合不因一个工具坏了而崩。
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from pocketexpert_harness.kernel.loop import ToolCall, ToolResult

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[Any]]

#: 这一轮的临时状态 (如已经搜过的关键词), Harness.run_turn 开头重置; 工具据此做轮内去重
turn_state: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("peh_turn_state", default=None)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Handler
    obs_cap: int = 6000                  # 观察写回会话的字数上限
    timeout: float = 120.0
    confirm: Optional[Callable[[dict], Awaitable[bool]]] = None   # 执行前确认 (命令行里跑代码前问一句)
    meta: dict = field(default_factory=dict)

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def obs_cap(self, name: str) -> int:
        t = self._tools.get(name)
        return t.obs_cap if t else 2000

    async def port(self, call: ToolCall, n: int) -> AsyncIterator[Any]:
        """内核的 tools 端口: 中途可以 yield 进度事件, 最后 yield 一个 ToolResult。"""
        tool = self._tools.get(call.name)
        if tool is None:
            yield ToolResult(ok=False, obs=f"没有名为 {call.name} 的工具")
            return
        if tool.confirm is not None:
            try:
                allowed = await tool.confirm(call.args)
            except Exception:       # noqa: BLE001
                allowed = False
            if not allowed:
                yield ToolResult(ok=False, obs="用户没有同意执行这一步。换个办法, 或直接回答。")
                return
        try:
            out = tool.handler(call.args)
            if inspect.isawaitable(out):
                out = await asyncio.wait_for(out, timeout=tool.timeout)
        except asyncio.TimeoutError:
            yield ToolResult(ok=False, obs=f"工具 {call.name} 超时 ({int(tool.timeout)} 秒)")
            return
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except Exception as e:      # noqa: BLE001 — 工具坏了交还模型, 不让回合崩
            logger.warning("tool %s failed: %s", call.name, e, exc_info=True)
            yield ToolResult(ok=False, obs=f"工具 {call.name} 出错: {type(e).__name__}: {str(e)[:500]}")
            return
        if isinstance(out, ToolResult):
            yield out
        else:
            yield ToolResult(ok=True, obs=str(out if out is not None else ""))
