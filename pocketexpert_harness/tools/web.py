# SPDX-License-Identifier: Apache-2.0
"""联网: web_search (SearXNG / Tavily / Brave 三选一) 与 open_url (读网页正文)。

open_url 默认拒绝内网地址: 网页内容可能诱导模型去读 127.0.0.1、云主机元数据 (169.254.169.254) 这类地址。
每一跳重定向都重新检查。确实要读内网, 设 PEH_ALLOW_PRIVATE_URLS=1。
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from pocketexpert_harness.config import Settings
from pocketexpert_harness.tools import Tool, turn_state

UA = "Mozilla/5.0 (compatible; PocketExpertHarness/0.1; +https://agentsdance.ai)"
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5


# ── 搜索 ────────────────────────────────────────────────────────────────

def search_backend(s: Settings) -> str:
    if s.searxng_url:
        return "searxng"
    if s.tavily_api_key:
        return "tavily"
    if s.brave_api_key:
        return "brave"
    return ""


async def web_search(s: Settings, client: httpx.AsyncClient, query: str, count: int = 8) -> list[dict]:
    backend = search_backend(s)
    count = max(1, min(int(count or 8), 20))
    if backend == "searxng":
        r = await client.get(f"{s.searxng_url}/search", params={"q": query, "format": "json"}, headers={"User-Agent": UA})
        r.raise_for_status()
        items = r.json().get("results") or []
        return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("content", "")} for i in items[:count]]
    if backend == "tavily":
        r = await client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {s.tavily_api_key}"},
                              json={"query": query, "max_results": count})
        r.raise_for_status()
        return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("content", "")}
                for i in (r.json().get("results") or [])[:count]]
    if backend == "brave":
        r = await client.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": count},
                             headers={"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"})
        r.raise_for_status()
        return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": re.sub(r"<[^>]+>", "", i.get("description", ""))}
                for i in ((r.json().get("web") or {}).get("results") or [])[:count]]
    raise RuntimeError("没有配置搜索服务 (SEARXNG_URL / TAVILY_API_KEY / BRAVE_API_KEY)")


def _qnorm(q: str) -> str:
    return re.sub(r"[\s\W_]+", "", q.lower())


def _grams(q: str) -> set:
    t = _qnorm(q)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def seen_query(query: str, previous: list[str]) -> str:
    """这一轮里搜过的近似关键词 (字符二元组 Jaccard ≥ 0.75 算同一个); 没有返回空串。"""
    g = _grams(query)
    for p in previous:
        h = _grams(p)
        if _qnorm(p) == _qnorm(query) or (g and h and len(g & h) / len(g | h) >= 0.75):
            return p
    return ""


def format_results(query: str, items: list[dict]) -> str:
    if not items:
        return f"「{query}」没有搜到结果。换个关键词试试。"
    lines = [f"「{query}」的搜索结果:"]
    for k, i in enumerate(items, 1):
        lines.append(f"[{k}] {i['title']}\n    {i['url']}\n    {i['snippet'][:300]}")
    lines.append("需要细节就用 open_url 读原文; 回答里引用时带上链接。")
    return "\n".join(lines)


# ── 读网页 ──────────────────────────────────────────────────────────────

class UnsafeURL(ValueError):
    pass


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def check_url(url: str, *, allow_private: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL(f"只支持 http/https 链接: {url[:200]}")
    if allow_private:
        return
    host = parts.hostname
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                                             type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeURL(f"域名解析失败: {host} ({e})") from e
    for info in infos:
        if not _is_public(info[4][0]):
            raise UnsafeURL(f"拒绝访问内网地址: {host} → {info[4][0]} (确需访问请设 PEH_ALLOW_PRIVATE_URLS=1)")


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
             "pre", "blockquote", "table", "ul", "ol", "dd", "dt"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:       # noqa: BLE001 — 残缺 HTML 尽量拿多少算多少
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return p.title.strip(), "\n".join(line.strip() for line in text.splitlines()).strip()


async def fetch_text(client: httpx.AsyncClient, url: str, *, allow_private: bool = False) -> tuple[str, str, str]:
    """返回 (最终 URL, 标题, 正文)。手动跟随重定向, 每一跳都过 check_url。"""
    for _ in range(MAX_REDIRECTS + 1):
        await check_url(url, allow_private=allow_private)
        async with client.stream("GET", url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.5"},
                                 follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "").lower()
            if not any(t in ctype for t in ("html", "text", "json", "xml")) and ctype:
                return url, "", f"(这是 {ctype.split(';')[0]} 文件, 不是网页正文, 没有读取)"
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    break
            charset = r.charset_encoding or "utf-8"
            try:
                body = buf.decode(charset, "replace")
            except LookupError:
                body = buf.decode("utf-8", "replace")
            if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                title, text = html_to_text(body)
                return url, title, text
            return url, "", body
    raise RuntimeError("重定向次数太多")


def make_tools(s: Settings, client: httpx.AsyncClient) -> list[Tool]:
    tools = []
    if search_backend(s):
        async def _search(args: dict) -> str:
            q = str(args.get("query") or "").strip()
            if not q:
                return "query 不能为空"
            st = turn_state.get()
            done = st.setdefault("queries", []) if st is not None else []
            dup = seen_query(q, done)
            if dup:
                return (f"「{q}」和这一轮已经搜过的「{dup}」几乎一样, 结果见前面, 没有再搜。"
                        "换一个明显不同的角度, 或者用已有信息直接回答。")
            done.append(q)
            return format_results(q, await web_search(s, client, q, int(args.get("count") or 8)))
        tools.append(Tool(
            name="web_search", handler=_search, obs_cap=5000, timeout=40,
            description="联网搜索, 返回标题、链接和摘要。事实、数据、新闻、价格等会变的信息先搜再答。",
            parameters={"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "count": {"type": "integer", "description": "返回条数, 默认 8, 最多 20"}},
                "required": ["query"]}))

    async def _open(args: dict) -> str:
        url = str(args.get("url") or "").strip()
        final, title, text = await fetch_text(client, url, allow_private=s.allow_private_urls)
        if not text:
            return f"{final} 没有可读的正文"
        head = f"# {title}\n来源: {final}\n\n" if title else f"来源: {final}\n\n"
        return head + text
    tools.append(Tool(
        name="open_url", handler=_open, obs_cap=12000, timeout=45,
        description="读取一个网页的正文 (去掉脚本和样式)。用于细读搜索结果或用户给的链接。",
        parameters={"type": "object", "properties": {"url": {"type": "string", "description": "http(s) 链接"}},
                    "required": ["url"]}))
    return tools
