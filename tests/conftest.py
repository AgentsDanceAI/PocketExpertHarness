# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from pocketexpert_harness.config import Settings


class FakeModel:
    """按脚本回复的假模型: 每次调用弹出一条 {content, tool_calls, finish_reason}; 也可以是 f(messages) -> dict。"""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls: list[dict] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.route = {"url": "http://fake.local/v1", "model": "fake-model"}

    async def port(self, messages, route, on_delta, *, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        self.usage["calls"] += 1
        item = self.script.pop(0) if self.script else {"content": "(脚本用完了)"}
        if callable(item):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        if item.get("content"):
            on_delta(item["content"])
        return {"content": item.get("content", ""), "tool_calls": item.get("tool_calls", []),
                "finish_reason": item.get("finish_reason", "stop"), **({"malformed": True, "raw": "x"} if item.get("malformed") else {})}

    async def complete(self, messages):
        return "摘要"

    async def aclose(self):
        return None


def call(name, args=None, cid=None):
    return {"id": cid or f"c_{name}", "name": name, "args": args or {}}


@pytest.fixture
def settings(tmp_path):
    return Settings(provider="custom", base_url="http://fake.local/v1", api_key="k", model="fake-model",
                    home=tmp_path / "home", workspace=tmp_path / "ws", python_mode="on", skills_dirs=[],
                    mcp_config=None, max_steps=8)
