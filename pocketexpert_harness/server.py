# SPDX-License-Identifier: Apache-2.0
"""网页聊天服务: FastAPI + SSE, 界面是 web/ 下的静态页 (无需构建)。

默认只听 127.0.0.1。要让别的机器访问, 设 PEH_ACCESS_TOKEN 再把 --host 改成 0.0.0.0 ——
页面第一次打开会让你输入这个口令。
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pocketexpert_harness import __version__
from pocketexpert_harness.agent import Harness
from pocketexpert_harness.config import Settings
from pocketexpert_harness.kernel.loop import Inbox
from pocketexpert_harness.sessions import SessionStore, TranscriptBuilder
from pocketexpert_harness.tools.web import search_backend

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
KEEPALIVE_S = 15.0


class TextIn(BaseModel):
    text: str


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


class Runner:
    """每个会话同一时间只跑一轮; 跑的时候可以插话 (steer) 或停止。"""

    def __init__(self, harness: Harness, store: SessionStore):
        self.harness, self.store = harness, store
        self.active: dict[str, dict] = {}

    async def stream(self, sid: str, text: str):
        sess = self.store.get(sid)
        if sess is None:
            raise HTTPException(404, "会话不存在")
        if sid in self.active:
            raise HTTPException(409, "这个会话还有一轮没跑完")
        sess["transcript"].append({"role": "user", "text": text, "at": time.time()})
        if sess.get("title") in ("", "新对话"):
            sess["title"] = text.strip().splitlines()[0][:40] or "新对话"
        self.store.save(sess)
        inbox, queue, tb = Inbox(), asyncio.Queue(), TranscriptBuilder()
        history = list(sess.get("history") or [])

        async def worker() -> None:
            finished = False
            try:
                async for ev in self.harness.run_turn(history, text, inbox=inbox):
                    tb.feed(ev)
                    if ev.get("event") == "done":
                        sess["history"] = ev["history"]
                        finished = True
                        ev = {k: v for k, v in ev.items() if k != "history"}
                    queue.put_nowait(ev)
            except asyncio.CancelledError:
                queue.put_nowait({"event": "done", "answer": tb._draft, "kind": "aborted"})
            except Exception as e:      # noqa: BLE001
                logger.exception("turn failed")
                queue.put_nowait({"event": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
            finally:
                if not finished:
                    # 停止或出错的一轮也留在历史里, 不然下一轮模型不知道用户问过什么
                    partial = tb._draft.strip() or tb.answer
                    sess["history"] = history + [{"role": "user", "content": text},
                                                 {"role": "assistant", "content": partial or "(这一轮被中途停止了)"}]
                    tb.kind = tb.kind or "aborted"
                    tb.answer = tb.answer or partial
                sess["transcript"].append(tb.record())
                self.store.save(sess)
                self.active.pop(sid, None)
                queue.put_nowait(None)

        task = asyncio.create_task(worker())
        self.active[sid] = {"inbox": inbox, "task": task}
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if ev is None:
                    break
                yield _sse(ev)
        finally:
            if not task.done():
                task.cancel()

    def steer(self, sid: str, text: str) -> bool:
        run = self.active.get(sid)
        if not run:
            return False
        run["inbox"].steer(text)
        return True

    def stop(self, sid: str) -> bool:
        run = self.active.get(sid)
        if not run:
            return False
        run["task"].cancel()
        return True


def create_app(settings: Optional[Settings] = None, *, harness: Optional[Harness] = None) -> FastAPI:
    settings = settings or (harness.s if harness else Settings.from_env(serving=True))
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        h = harness or Harness(settings)
        await h.start()
        store = SessionStore(settings.home / "sessions")
        state.update(harness=h, store=store, runner=Runner(h, store))
        try:
            yield
        finally:
            if harness is None:
                await h.close()

    app = FastAPI(title="PocketExpertHarness", version=__version__, lifespan=lifespan)

    def auth(request: Request) -> None:
        if not settings.access_token:
            return
        got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(got, settings.access_token):
            raise HTTPException(401, "需要访问口令")

    guard = [Depends(auth)]

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/api/info", dependencies=guard)
    async def info():
        h: Harness = state["harness"]
        return {"name": settings.agent_name, "version": __version__, "provider": settings.provider,
                "model": settings.model, "tools": h.registry.names, "web_search": search_backend(settings) or None,
                "python": settings.python_mode, "workspace": str(settings.workspace),
                "skills": [{"name": s.name, "description": s.description} for s in h.skills.values()],
                "mcp": h.mcp.status()}

    @app.get("/api/auth", include_in_schema=False)
    async def auth_required():
        return {"token_required": bool(settings.access_token)}

    @app.get("/api/sessions", dependencies=guard)
    async def list_sessions():
        return state["store"].list()

    @app.post("/api/sessions", dependencies=guard)
    async def new_session():
        s = state["store"].create()
        return {"id": s["id"], "title": s["title"]}

    @app.get("/api/sessions/{sid}", dependencies=guard)
    async def get_session(sid: str):
        s = state["store"].get(sid)
        if s is None:
            raise HTTPException(404, "会话不存在")
        return {"id": s["id"], "title": s["title"], "transcript": s["transcript"], "running": sid in state["runner"].active}

    @app.delete("/api/sessions/{sid}", dependencies=guard)
    async def delete_session(sid: str):
        state["runner"].stop(sid)
        return {"ok": state["store"].delete(sid)}

    @app.post("/api/sessions/{sid}/messages", dependencies=guard)
    async def send(sid: str, body: TextIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "消息为空")
        gen = state["runner"].stream(sid, text)
        first = await gen.__anext__()       # 先跑到第一帧: 会话不存在 / 正在跑 这类错误要以 HTTP 状态码返回
        async def rest():
            yield first
            async for chunk in gen:
                yield chunk
        return StreamingResponse(rest(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/sessions/{sid}/steer", dependencies=guard)
    async def steer(sid: str, body: TextIn):
        return {"ok": state["runner"].steer(sid, body.text.strip())}

    @app.post("/api/sessions/{sid}/stop", dependencies=guard)
    async def stop(sid: str):
        return {"ok": state["runner"].stop(sid)}

    @app.get("/api/memory", dependencies=guard)
    async def get_memory():
        m = state["harness"].memory
        return {"soul": m.soul(), "items": m.items()}

    @app.put("/api/memory/soul", dependencies=guard)
    async def put_soul(body: TextIn):
        state["harness"].memory.set_soul(body.text)
        return {"ok": True}

    @app.delete("/api/memory/items/{item_id}", dependencies=guard)
    async def delete_item(item_id: str):
        return {"ok": state["harness"].memory.delete(item_id)}

    @app.exception_handler(HTTPException)
    async def http_error(_req: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app
