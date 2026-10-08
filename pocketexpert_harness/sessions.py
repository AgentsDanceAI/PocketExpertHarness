# SPDX-License-Identifier: Apache-2.0
"""会话存储: 一个会话一个 JSON 文件 (~/.pocketexpert-harness/sessions/<id>.json)。

  history     给模型的历史 (内核会话日志的投影, 下一轮原样播种)
  transcript  给人看的记录 (用户的话、每一步做了什么、最终回答)
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

_ID_RE = re.compile(r"^[a-f0-9]{12}$")
THINKING_CAP = 8000       # 每段思考最多存这么多字 (给人回看, 不回传给模型)


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, sid: str) -> Path:
        if not _ID_RE.match(sid or ""):
            raise KeyError(sid)
        return self.root / f"{sid}.json"

    def create(self, title: str = "") -> dict:
        now = time.time()
        sess = {"id": uuid.uuid4().hex[:12], "title": title or "新对话", "created": now, "updated": now,
                "history": [], "transcript": []}
        self.save(sess)
        return sess

    def get(self, sid: str) -> Optional[dict]:
        try:
            return json.loads(self._path(sid).read_text(encoding="utf-8"))
        except (KeyError, FileNotFoundError, json.JSONDecodeError):
            return None

    def save(self, sess: dict) -> None:
        sess["updated"] = time.time()
        path = self._path(sess["id"])
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    def delete(self, sid: str) -> bool:
        try:
            self._path(sid).unlink()
            return True
        except (KeyError, FileNotFoundError):
            return False

    def list(self) -> list[dict]:
        rows = []
        for p in self.root.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows.append({"id": d.get("id"), "title": d.get("title"), "updated": d.get("updated", 0)})
        return sorted(rows, key=lambda r: r["updated"], reverse=True)


class TranscriptBuilder:
    """把一轮的事件流折叠成一条给人看的助手记录: 步骤列表 + 最终回答。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.answer = ""
        self.kind = ""
        self.notices: list[str] = []
        self._draft = ""
        self._think = ""          # 当前这一步的思考 (思考开着才有), 等这一步的工具调用或最终回答来了挂上去
        self.thinking = ""        # 写最终回答之前的那段思考

    def feed(self, ev: dict) -> None:
        e = ev.get("event")
        if e == "thinking":
            self._think += str(ev.get("text") or "")
        elif e == "assistant_delta":
            self._draft += str(ev.get("text") or "")
        elif e == "step":
            st = {"n": ev.get("n"), "tool": ev.get("tool"), "args": ev.get("args") or {},
                  "thought": str(ev.get("thought") or self._draft).strip()[:600], "ok": None, "summary": ""}
            if self._think.strip():
                st["thinking"] = self._think.strip()[:THINKING_CAP]
            self.steps.append(st)
            self._draft, self._think = "", ""
        elif e == "observation":
            for st in reversed(self.steps):
                if st["n"] == ev.get("n"):
                    st["ok"], st["summary"] = ev.get("ok"), str(ev.get("summary") or "")[:600]
                    break
        elif e == "steer":
            self.steps.append({"n": ev.get("n"), "tool": "steer", "args": {}, "thought": str(ev.get("text") or ""), "ok": True, "summary": ""})
        elif e == "notice":
            self.notices.append(str(ev.get("reason") or ev.get("kind") or ""))
        elif e == "done":
            self.answer, self.kind = str(ev.get("answer") or ""), str(ev.get("kind") or "")
            self.thinking, self._think = self._think.strip()[:THINKING_CAP], ""

    def record(self, took: Optional[float] = None) -> dict:
        rec = {"role": "assistant", "text": self.answer, "steps": self.steps, "kind": self.kind, "at": time.time()}
        if self.thinking or self._think.strip():
            rec["thinking"] = (self.thinking or self._think.strip())[:THINKING_CAP]
        if took is not None:
            rec["took"] = round(took, 1)
        return rec
