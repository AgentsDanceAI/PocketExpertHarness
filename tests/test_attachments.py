# SPDX-License-Identifier: Apache-2.0
"""附件与工作区文件: 上传落盘、交给模型 (看图 / 不看图)、网页上查看与下载。"""
from __future__ import annotations

import base64
import json

import pytest
from conftest import FakeModel
from fastapi.testclient import TestClient

from pocketexpert_harness.agent import Harness, compose_message
from pocketexpert_harness.files import MAX_UPLOAD_BYTES, kind_of, list_files, safe_name, save_upload
from pocketexpert_harness.llm import MAX_IMAGES_PER_REQUEST, ChatModel, expand_images
from pocketexpert_harness.server import create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def test_save_upload_cleans_name_and_classifies(tmp_path):
    info = save_upload(tmp_path, "../../etc/销售 数据.csv", b"a,b\n1,2\n")
    assert info["path"].startswith("uploads/") and info["path"].endswith("-销售 数据.csv")
    assert info["kind"] == "table" and info["size"] == 8
    assert (tmp_path / info["path"]).read_bytes() == b"a,b\n1,2\n"
    assert safe_name("..hidden") == "hidden" and safe_name("") == "upload"
    assert kind_of("x.PNG") == "image" and kind_of("a.mov") == "video" and kind_of("a.bin") == "file"
    with pytest.raises(ValueError):
        save_upload(tmp_path, "big.bin", b"0" * (MAX_UPLOAD_BYTES + 1))
    assert list_files(tmp_path)[0]["path"] == info["path"]


def test_compose_message_vision_and_not(tmp_path):
    img = save_upload(tmp_path, "cat.png", PNG)
    vid = save_upload(tmp_path, "clip.mp4", b"\x00" * 10)
    atts = [img, vid, {"path": "uploads/没有这个文件.png", "kind": "image"}]
    on = compose_message("这是什么?", atts, vision=True, workspace=tmp_path)
    assert on.startswith("这是什么?") and f"[[peh-image:{img['path']}]]" in on
    assert "音视频理解" in on and "没有这个文件" not in on
    off = compose_message("", [img], vision=False, workspace=tmp_path)
    assert off.startswith("请看我上传的附件") and "[[peh-image:" not in off and "看不了图" in off
    assert compose_message("只有文字", [], vision=True) == "只有文字"


def test_expand_images_builds_content_parts(tmp_path):
    img = save_upload(tmp_path, "a.png", PNG)
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": f"看图\n[[peh-image:{img['path']}]]"}]
    out = expand_images(msgs, tmp_path, enabled=True)
    parts = out[1]["content"]
    assert parts[0]["type"] == "text" and "[[peh-image" not in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    off = expand_images(msgs, tmp_path, enabled=False)
    assert isinstance(off[1]["content"], str) and "看不了图" in off[1]["content"]
    bad = expand_images([{"role": "user", "content": "[[peh-image:../../etc/passwd]]"}], tmp_path, enabled=True)
    assert isinstance(bad[0]["content"], str)
    assert msgs[1]["content"].startswith("看图"), "原消息不能被就地改掉 (内核日志要保持文字)"


def test_expand_images_keeps_only_newest(tmp_path):
    imgs = [save_upload(tmp_path, f"{i}.png", PNG)["path"] for i in range(MAX_IMAGES_PER_REQUEST + 3)]
    msgs = [{"role": "user", "content": f"[[peh-image:{p}]]"} for p in imgs]
    out = expand_images(msgs, tmp_path, enabled=True)
    with_img = [m for m in out if isinstance(m["content"], list)]
    assert len(with_img) == MAX_IMAGES_PER_REQUEST
    assert isinstance(out[0]["content"], str) and isinstance(out[-1]["content"], list)


def test_chat_model_body_expands_when_vision(settings):
    settings.model = "qwen-vl-max"
    settings.workspace.mkdir(parents=True, exist_ok=True)
    img = save_upload(settings.workspace, "a.png", PNG)
    body = ChatModel(settings)._body([{"role": "user", "content": f"[[peh-image:{img['path']}]]"}], "qwen-vl-max", None, True)
    assert isinstance(body["messages"][0]["content"], list)


def test_web_upload_view_download_and_send(settings):
    settings.model = "qwen-vl-max"            # 看图模型: 附件图片应当以内容块交给模型
    seen = {}

    def reply(msgs):
        seen["user"] = msgs[-1]["content"]
        return {"content": "是一张 1x1 的图"}
    app = create_app(settings, harness=Harness(settings, model=FakeModel([reply])))
    with TestClient(app) as c:
        up = c.post("/api/uploads?name=cat.png", content=PNG).json()
        assert up["kind"] == "image" and up["url"].startswith("/api/files/uploads/")
        got = c.get(up["url"])
        assert got.status_code == 200 and got.content == PNG
        assert "attachment" in c.get(up["url"] + "?download=1").headers.get("content-disposition", "")
        assert c.get("/api/files/../../etc/passwd").status_code in (403, 404)
        assert c.get("/api/files/nope.txt").status_code == 404
        assert c.post("/api/uploads?name=x", content=b"").status_code == 400
        assert c.get("/api/files").json()[0]["path"] == up["path"]
        sid = c.post("/api/sessions").json()["id"]
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "这是什么?", "attachments": [up]})
        evs = [json.loads(line[5:]) for line in r.text.split("\n") if line.startswith("data:")]
        assert evs[-1]["answer"] == "是一张 1x1 的图"
        s = c.get(f"/api/sessions/{sid}").json()
        assert s["transcript"][0]["attachments"][0]["path"] == up["path"]
        assert s["transcript"][1]["took"] >= 0
        assert c.post(f"/api/sessions/{sid}/messages", json={"text": "", "attachments": []}).status_code == 400
        info = c.get("/api/info").json()
        assert info["vision"] is True and info["max_upload_mb"] == 50
    assert isinstance(seen["user"], str) and "[[peh-image:" in seen["user"], "假模型拿到的是内核日志里的原文 (图片在真接口里才展开)"


def test_files_accept_token_in_query(settings):
    settings.access_token = "s3cret"
    app = create_app(settings, harness=Harness(settings, model=FakeModel()))
    with TestClient(app) as c:
        up = c.post("/api/uploads?name=a.txt", content=b"hi", headers={"Authorization": "Bearer s3cret"}).json()
        assert c.get(up["url"]).status_code == 401
        assert c.get(up["url"] + "?token=s3cret").status_code == 200
        assert c.post("/api/uploads?name=b.txt&token=s3cret", content=b"x").status_code == 401, "上传不认 URL 里的口令"
