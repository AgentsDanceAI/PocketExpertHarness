# SPDX-License-Identifier: Apache-2.0
"""搜索: 智谱联网搜索 (引擎依次兜底)、选用哪家; 流式请求带上用量。"""
from __future__ import annotations

import json

import httpx

from pocketexpert_harness.llm import ChatModel
from pocketexpert_harness.tools.web import search_backend, web_search


def test_paid_api_beats_searxng_and_peh_search_forces(settings):
    settings.searxng_url = "http://127.0.0.1:8888"
    assert search_backend(settings) == "searxng"
    settings.zhipu_api_key = "zk"
    assert search_backend(settings) == "zhipu", "配了 Key 多半就是想用它, 比自建 SearXNG 优先"
    settings.search_provider = "searxng"
    assert search_backend(settings) == "searxng"
    settings.search_provider = "brave"          # 指定了但没配 → 按默认顺序
    assert search_backend(settings) == "zhipu"


async def test_zhipu_falls_back_through_engines(settings):
    settings.zhipu_api_key, settings.zhipu_search_engine = "zk", "search_pro_sogou,search_std"
    settings.searxng_url = ""
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body["search_engine"])
        assert req.headers["authorization"] == "Bearer zk" and len(body["search_query"]) <= 70
        if body["search_engine"] == "search_pro_sogou":
            return httpx.Response(429, json={"error": {"code": "1113", "message": "余额不足或无可用资源包"}})
        return httpx.Response(200, json={"search_result": [
            {"title": "好东西", "link": "https://example.com/a", "content": "2024 年底上映"},
            {"title": "没链接但有正文", "link": "", "content": "摘要也有用"},
            {"title": "空", "link": "", "content": ""}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        out = await web_search(settings, c, "2024年底上映的国产电影 " * 10, 5)
    assert seen == ["search_pro_sogou", "search_std"]
    assert [o["title"] for o in out] == ["好东西", "没链接但有正文"]


def test_streaming_requests_ask_for_usage(settings):
    body = ChatModel(settings)._body([{"role": "user", "content": "x"}], "m", None, True)
    assert body["stream_options"] == {"include_usage": True}
    assert "stream_options" not in ChatModel(settings)._body([{"role": "user", "content": "x"}], "m", None, False)
