# SPDX-License-Identifier: Apache-2.0
"""OpenAI 兼容的对话接口 → 内核的 llm 端口。

内核要的形状: ``await llm(messages, route, on_delta) -> {content, tool_calls, finish_reason, raw, malformed}``;
流式正文每来一段就 ``on_delta(text)``, 工具调用在流里拼完再一起返回。DeepSeek / 通义 / 硅基流动 / OpenAI /
OpenRouter / Ollama 都走这一条 (/chat/completions + tools)。
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from pocketexpert_harness.config import Settings

logger = logging.getLogger(__name__)


#: 用户消息里的图片标记。内核的会话日志只存文字 (上游原样导出, 不在本仓改), 所以附件图片在日志里只是一个标记,
#: 发请求那一刻才换成 OpenAI 格式的 image_url 内容块 —— 历史不会被几 MB 的 base64 撑大。
IMAGE_MARKER = re.compile(r"\[\[peh-image:([^\]\n]+)\]\]")
MAX_IMAGES_PER_REQUEST = 6          # 只带最近的几张, 免得每一步都重发全部历史图片
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def expand_images(messages: list, workspace: Optional[Path], enabled: bool) -> list:
    """把用户消息里的图片标记换成内容块; 不支持看图 / 超出张数 / 文件没了 → 换成一句文字说明。"""
    if not any(m.get("role") == "user" and IMAGE_MARKER.search(str(m.get("content") or "")) for m in messages):
        return messages
    budget = MAX_IMAGES_PER_REQUEST if enabled and workspace else 0
    keep: set[tuple[int, int]] = set()
    for i in range(len(messages) - 1, -1, -1):             # 从最新往回数
        m = messages[i]
        if m.get("role") != "user":
            continue
        for j, _ in enumerate(IMAGE_MARKER.finditer(str(m.get("content") or ""))):
            if budget > 0:
                keep.add((i, j))
                budget -= 1
    out = []
    for i, m in enumerate(messages):
        content = str(m.get("content") or "") if m.get("role") == "user" else None
        if content is None or not IMAGE_MARKER.search(content):
            out.append(m)
            continue
        parts: list[dict] = []
        idx = 0

        def _swap(match: "re.Match", _i: int = i, _parts: list = parts) -> str:
            nonlocal idx
            rel = match.group(1).strip()
            j, idx = idx, idx + 1
            if (_i, j) in keep:
                data = _image_data_url(workspace, rel)
                if data:
                    _parts.append({"type": "image_url", "image_url": {"url": data}})
                    return f"(图片 {rel})"
            return f"(图片 {rel}{'' if enabled else ', 当前模型看不了图, 只能当文件处理'})"
        text = IMAGE_MARKER.sub(_swap, content)
        out.append({**m, "content": [{"type": "text", "text": text}] + parts} if parts else {**m, "content": text})
    return out


def _image_data_url(workspace: Optional[Path], rel: str) -> str:
    if workspace is None:
        return ""
    root = workspace.resolve()
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file() or p.stat().st_size > MAX_IMAGE_BYTES:
        return ""
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


class LLMError(RuntimeError):
    """模型服务返回错误。消息里带 HTTP 状态码, 内核的重试钩子据此判断 429/5xx 要不要重试。"""


def _parse_args(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return val if isinstance(val, dict) else None


class ChatModel:
    """一个 OpenAI 兼容端点。``port`` 是给内核的 llm 端口, ``complete`` 给压缩摘要这类不带工具的单次调用。"""

    def __init__(self, settings: Settings, *, client: Optional[httpx.AsyncClient] = None, timeout: float = 180.0):
        self.s = settings
        self._client = client
        self._timeout = timeout
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    @property
    def route(self) -> dict:
        # 只放 url 与模型名: 内核会把路由写进会话日志, 密钥不能进去
        return {"url": self.s.base_url, "model": self.s.model}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
        if self.s.api_key:
            h["Authorization"] = f"Bearer {self.s.api_key}"
        return h

    def _body(self, messages: list, model: str, tools: Optional[list], stream: bool) -> dict:
        messages = expand_images(messages, self.s.workspace, self.s.supports_vision)
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self.s.temperature is not None:
            body["temperature"] = self.s.temperature
        if self.s.max_tokens:
            body["max_tokens"] = self.s.max_tokens
        body.update(self.s.extra_body or {})
        return body

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=15.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def port(self, messages: list, route: dict, on_delta: Callable[[str], None], *,
                   tools: Optional[list] = None) -> dict:
        url = f"{str(route.get('url') or self.s.base_url).rstrip('/')}/chat/completions"
        body = self._body(messages, str(route.get("model") or self.s.model), tools, stream=True)
        content: list[str] = []
        calls: dict[int, dict] = {}
        finish = ""
        async with self._http().stream("POST", url, headers=self._headers(), json=body) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                raise LLMError(f"HTTP {resp.status_code} from {self.s.provider}: {detail}")
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                # 个别服务忽略 stream=true 直接回整包 JSON
                data = json.loads((await resp.aread()).decode("utf-8", "replace"))
                return self._from_message(data, on_delta)
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise LLMError(f"stream error from {self.s.provider}: {json.dumps(chunk['error'], ensure_ascii=False)[:500]}")
                self._count(chunk.get("usage"))
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        content.append(text)
                        on_delta(text)
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(int(tc.get("index") or 0), {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        self.usage["calls"] += 1
        return self._result("".join(content), [calls[k] for k in sorted(calls)], finish)

    def _count(self, usage: Optional[dict]) -> None:
        if isinstance(usage, dict):
            self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)

    def _from_message(self, data: dict, on_delta: Callable[[str], None]) -> dict:
        self._count(data.get("usage"))
        self.usage["calls"] += 1
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = str(msg.get("content") or "")
        if text:
            on_delta(text)
        raw_calls = [{"id": c.get("id") or "", "name": (c.get("function") or {}).get("name") or "",
                      "arguments": (c.get("function") or {}).get("arguments") or ""} for c in msg.get("tool_calls") or []]
        return self._result(text, raw_calls, str(choice.get("finish_reason") or ""))

    @staticmethod
    def _result(content: str, raw_calls: list[dict], finish: str) -> dict:
        tool_calls, bad = [], []
        for i, c in enumerate(raw_calls):
            args = _parse_args(c["arguments"])
            if args is None:
                bad.append(c)
                continue
            tool_calls.append({"id": c["id"] or f"call_{i}", "name": c["name"].strip(), "args": args})
        out = {"content": content, "tool_calls": tool_calls, "finish_reason": finish}
        if bad and not tool_calls:
            # 参数被截断或不是 JSON: 交给内核走格式纠正 (连错几次按没有答案收口)
            names = ", ".join(c["name"] or "?" for c in bad)
            out.update(malformed=True, raw=content + "".join(c["arguments"] for c in bad),
                       nudge=f"你调用 {names} 时给的参数不是合法的 JSON 对象 (可能被截断了)。请重新调用, 参数写完整。")
        return out

    async def complete(self, messages: list) -> str:
        """不带工具、不流式的单次调用 (压缩摘要用)。"""
        url = f"{self.s.base_url}/chat/completions"
        resp = await self._http().post(url, headers=self._headers(), json=self._body(messages, self.s.model, None, stream=False))
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code} from {self.s.provider}: {resp.text[:500]}")
        data = resp.json()
        self._count(data.get("usage"))
        self.usage["calls"] += 1
        return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
