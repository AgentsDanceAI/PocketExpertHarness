# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

from conftest import FakeModel, call
from fastapi.testclient import TestClient

from pocketexpert_harness.agent import Harness
from pocketexpert_harness.server import create_app


def events_of(resp) -> list[dict]:
    return [json.loads(line[5:]) for line in resp.text.split("\n") if line.startswith("data:")]


def test_chat_roundtrip_persists_transcript(settings):
    model = FakeModel([{"content": "", "tool_calls": [call("remember", {"text": "用户叫小王"})]}, {"content": "好的, 记住了"},
                       lambda msgs: {"content": "小王你好" if "用户叫小王" in msgs[0]["content"] else "?"}])
    app = create_app(settings, harness=Harness(settings, model=model))
    with TestClient(app) as c:
        info = c.get("/api/info").json()
        assert info["model"] == "fake-model" and "remember" in info["tools"] and len(info["skills"]) >= 3
        sid = c.post("/api/sessions").json()["id"]
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "记住我叫小王"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        evs = events_of(r)
        done = evs[-1]
        assert done["event"] == "done" and done["answer"] == "好的, 记住了" and "history" not in done
        s = c.get(f"/api/sessions/{sid}").json()
        assert s["title"] == "记住我叫小王"
        assert [t["role"] for t in s["transcript"]] == ["user", "assistant"]
        assert s["transcript"][1]["steps"][0]["tool"] == "remember" and s["transcript"][1]["steps"][0]["ok"] is True
        # 记忆进了下一轮的系统提示
        r2 = c.post(f"/api/sessions/{sid}/messages", json={"text": "打个招呼"})
        assert events_of(r2)[-1]["answer"] == "小王你好"
        assert c.get("/api/memory").json()["items"][0]["text"] == "用户叫小王"
        assert c.get("/api/sessions").json()[0]["id"] == sid
        assert c.post(f"/api/sessions/{sid}/steer", json={"text": "x"}).json() == {"ok": False}
        assert c.delete(f"/api/sessions/{sid}").json() == {"ok": True}
        assert c.get(f"/api/sessions/{sid}").status_code == 404


def test_errors_and_static(settings):
    app = create_app(settings, harness=Harness(settings, model=FakeModel()))
    with TestClient(app) as c:
        assert c.post("/api/sessions/000000000000/messages", json={"text": "hi"}).status_code == 404
        assert c.post("/api/sessions/../../etc/messages", json={"text": "hi"}).status_code in (404, 405)
        sid = c.post("/api/sessions").json()["id"]
        assert c.post(f"/api/sessions/{sid}/messages", json={"text": "   "}).status_code == 400
        page = c.get("/")
        assert page.status_code == 200 and "PocketExpert Harness" in page.text
        assert c.get("/static/app.js").status_code == 200


def test_access_token_required(settings):
    settings.access_token = "s3cret"
    app = create_app(settings, harness=Harness(settings, model=FakeModel()))
    with TestClient(app) as c:
        assert c.get("/api/auth").json() == {"token_required": True}
        assert c.get("/api/sessions").status_code == 401
        assert c.get("/api/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/sessions", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert c.get("/").status_code == 200
