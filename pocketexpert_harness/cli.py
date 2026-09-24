# SPDX-License-Identifier: Apache-2.0
"""命令行: peh (或 pocketexpert-harness)。

  peh                     交互聊天 (同 peh chat)
  peh run "问题"          问一句就退出, 适合脚本
  peh serve               网页聊天 (默认 http://127.0.0.1:8080)
  peh doctor              检查模型 / 搜索 / MCP 配置
  peh skills | mcp | memory
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from typing import Optional

from pocketexpert_harness import __version__
from pocketexpert_harness.agent import Harness
from pocketexpert_harness.config import Settings, in_container
from pocketexpert_harness.sessions import SessionStore
from pocketexpert_harness.tools.web import search_backend

PROMO = "想要 250+ 位行业专家、专家群协作、一键出 PPT / 网页 / 视频和手机 App? → 口袋专家 AI  https://agentsdance.ai"


class Style:
    def __init__(self, enabled: bool):
        self.on = enabled

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def dim(self, s: str) -> str:
        return self._w("2", s)

    def cyan(self, s: str) -> str:
        return self._w("36", s)

    def red(self, s: str) -> str:
        return self._w("31", s)

    def bold(self, s: str) -> str:
        return self._w("1", s)


def _short(obj, n: int = 90) -> str:
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _check_config(s: Settings, st: Style) -> bool:
    probs = s.problems()
    for p in probs:
        print(st.red("✗ " + p), file=sys.stderr)
    if probs:
        print(st.dim("把配置写进当前目录的 .env (参考 .env.example), 或设成环境变量。"), file=sys.stderr)
    return not probs


async def _ask(prompt: str) -> str:
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        return ""


def make_confirm(st: Style, auto_yes: bool):
    async def confirm(args: dict) -> bool:
        if auto_yes:
            return True
        code = str(args.get("code") or "")
        print("\n" + st.cyan("模型要在你的电脑上运行这段 Python 代码:"))
        print(st.dim("\n".join("  │ " + ln for ln in code.splitlines()[:60])))
        return (await _ask("执行吗? [y/N] ")).strip().lower() in ("y", "yes", "是")
    return confirm


async def run_one_turn(h: Harness, history: list, text: str, st: Style) -> tuple[str, list]:
    """跑一轮并把过程打印出来; 返回 (回答, 新历史)。Ctrl+C 停止这一轮。"""
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    installed = False
    if os.name == "posix":
        try:
            loop.add_signal_handler(signal.SIGINT, task.cancel)
            installed = True
        except (NotImplementedError, RuntimeError):
            pass
    streamed, answer, new_history = False, "", history
    try:
        async for ev in h.run_turn(history, text):
            e = ev.get("event")
            if e == "assistant_delta":
                sys.stdout.write(str(ev.get("text") or ""))
                sys.stdout.flush()
                streamed = True
            elif e == "step":
                if streamed:
                    sys.stdout.write("\n")
                    streamed = False
                print(st.cyan(f"  → {ev.get('tool')} ") + st.dim(_short(ev.get("args") or {})))
            elif e == "observation":
                mark = "✓" if ev.get("ok") else "✗"
                print(st.dim(f"    {mark} {_short(ev.get('summary') or '', 110)}"))
            elif e == "notice" and ev.get("kind") not in ("request_retry",):
                print(st.dim(f"  ({ev.get('reason') or ev.get('kind')})"))
            elif e == "done":
                answer, new_history = str(ev.get("answer") or ""), ev.get("history") or history
                if not streamed and answer:
                    print(answer)
        if streamed:
            sys.stdout.write("\n")
    except asyncio.CancelledError:
        if task is not None and hasattr(task, "uncancel"):
            task.uncancel()
        print(st.dim("\n(已停止这一轮)"))
        new_history = history + [{"role": "user", "content": text}, {"role": "assistant", "content": "(这一轮被中途停止了)"}]
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)
    return answer, new_history


async def cmd_chat(s: Settings, args) -> int:
    st = Style(sys.stdout.isatty())
    if not _check_config(s, st):
        return 2
    h = Harness(s, confirm_python=make_confirm(st, args.yes))
    await h.start()
    store = SessionStore(s.home / "sessions")
    sess = store.get(args.session) if args.session else None
    sess = sess or store.create()
    print(st.bold(f"PocketExpertHarness {__version__}") + st.dim(f"  ·  {s.provider}/{s.model}  ·  工具 {len(h.registry)} 个"
                                                            f"  ·  技能 {len(h.skills)} 个  ·  会话 {sess['id']}"))
    for row in h.mcp.status():
        if row["status"] == "failed":
            print(st.red(f"  MCP {row['name']} 没连上: {row.get('error')}"))
    print(st.dim("输入问题回车; /new 新会话, /memory 看记忆, /tools 看工具, /exit 退出; 回答中按 Ctrl+C 停止这一轮。"))
    print(st.dim(PROMO) + "\n")
    try:
        while True:
            text = (await _ask(st.bold("你 › "))).strip()
            if not text:
                continue
            if text in ("/exit", "/quit", "exit", "quit"):
                break
            if text == "/new":
                sess = store.create()
                print(st.dim(f"新会话 {sess['id']}"))
                continue
            if text == "/tools":
                print("\n".join(f"  {t.name}" for t in h.registry))
                continue
            if text == "/memory":
                print(h.memory.render() or st.dim("(还没有长期记忆)"))
                continue
            answer, sess["history"] = await run_one_turn(h, sess.get("history") or [], text, st)
            sess["transcript"] += [{"role": "user", "text": text}, {"role": "assistant", "text": answer}]
            if sess.get("title") == "新对话":
                sess["title"] = text[:40]
            store.save(sess)
            print()
    finally:
        await h.close()
    return 0


async def cmd_run(s: Settings, args) -> int:
    st = Style(sys.stderr.isatty())
    if not _check_config(s, st):
        return 2
    h = Harness(s, confirm_python=make_confirm(st, args.yes))
    await h.start()
    try:
        answer = ""
        async for ev in h.run_turn([], args.question):
            e = ev.get("event")
            if e == "step" and not args.quiet:
                print(st.dim(f"→ {ev.get('tool')} {_short(ev.get('args') or {})}"), file=sys.stderr)
            elif e == "done":
                answer = str(ev.get("answer") or "")
        print(answer)
    finally:
        await h.close()
    return 0 if answer else 1


async def cmd_doctor(s: Settings, _args) -> int:
    st = Style(sys.stdout.isatty())
    ok = _check_config(s, st)
    h = Harness(s)
    try:
        if ok:
            try:
                reply = await h.model.complete([{"role": "user", "content": "只回复两个字: 正常"}])
                print(f"✓ 模型 {s.provider}/{s.model} 可用: {reply.strip()[:40]}")
            except Exception as e:      # noqa: BLE001
                ok = False
                print(st.red(f"✗ 模型调用失败: {e}"))
        backend = search_backend(s)
        print(f"{'✓' if backend else '·'} 联网搜索: {backend or '未配置 (设 SEARXNG_URL / TAVILY_API_KEY / BRAVE_API_KEY)'}")
        print(f"· 代码执行: {s.python_mode}   工作区: {s.workspace}")
        await h.mcp.start()
        rows = h.mcp.status()
        if not rows:
            print(f"· MCP: 未配置 ({s.mcp_config or '没有 mcp.json'})")
        for row in rows:
            if row["status"] == "ready":
                print(f"✓ MCP {row['name']}: {row['tools']} 个工具")
            else:
                ok = False
                print(st.red(f"✗ MCP {row['name']}: {row.get('error')}"))
    finally:
        await h.close()
    return 0 if ok else 1


def cmd_serve(s: Settings, args) -> int:
    import uvicorn

    from pocketexpert_harness.server import create_app
    st = Style(sys.stdout.isatty())
    if not _check_config(s, st):
        return 2
    if args.host not in ("127.0.0.1", "localhost", "::1") and not s.access_token:
        if not in_container():
            print(st.red("对外监听必须先设 PEH_ACCESS_TOKEN (访问口令), 否则任何人都能用你的 API Key。"), file=sys.stderr)
            return 2
        # 容器里必须听 0.0.0.0, 真正对外与否由端口映射决定 (docker-compose.yml 默认只映射到宿主机 127.0.0.1)
        print(st.red("提示: 没设 PEH_ACCESS_TOKEN。端口只映射到 127.0.0.1 时没问题; 映射到公网之前务必设置。"), file=sys.stderr)
    print(st.bold(f"PocketExpertHarness {__version__}") + f"  →  http://{args.host}:{args.port}")
    uvicorn.run(create_app(s), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="peh", description="PocketExpertHarness: 口袋专家 AI 的开源智能体内核")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    p_chat = sub.add_parser("chat", help="交互聊天 (默认)")
    p_chat.add_argument("--session", help="接着某个会话聊")
    p_chat.add_argument("-y", "--yes", action="store_true", help="运行代码前不再询问")
    p_run = sub.add_parser("run", help="问一句就退出")
    p_run.add_argument("question")
    p_run.add_argument("-q", "--quiet", action="store_true", help="不打印过程")
    p_run.add_argument("-y", "--yes", action="store_true", help="运行代码前不再询问")
    p_serve = sub.add_parser("serve", help="网页聊天")
    p_serve.add_argument("--host", default=os.environ.get("PEH_HOST", "127.0.0.1"))
    p_serve.add_argument("--port", type=int, default=int(os.environ.get("PEH_PORT", "8080")))
    sub.add_parser("doctor", help="检查配置")
    sub.add_parser("skills", help="列出技能")
    sub.add_parser("mcp", help="MCP 服务状态")
    p_mem = sub.add_parser("memory", help="长期记忆")
    p_mem.add_argument("action", nargs="?", default="list", choices=["list", "clear"])
    args = ap.parse_args(argv)
    cmd = args.cmd or "chat"
    if cmd == "chat" and not hasattr(args, "session"):
        args.session, args.yes = None, False
    s = Settings.from_env(serving=(cmd == "serve"))
    if cmd == "serve":
        return cmd_serve(s, args)
    if cmd == "skills":
        from pocketexpert_harness.skills import discover
        for sk in discover(s.skills_dirs).values():
            print(f"{sk.name:24} {sk.description[:80]}  ({sk.path.parent})")
        return 0
    if cmd == "memory":
        from pocketexpert_harness.memory import Memory
        m = Memory(s.home)
        if args.action == "clear":
            m.clear()
            print("已清空记忆条目 (soul.md 不动)")
        else:
            print(m.render() or "(还没有长期记忆)")
            print(f"\n文件: {m.soul_path}  {m.items_path}")
        return 0
    if cmd == "mcp":
        async def _mcp() -> int:
            from pocketexpert_harness.mcp import MCPManager
            m = MCPManager(s.mcp_config)
            await m.start()
            for row in m.status():
                print(row)
            await m.close()
            return 0 if not m.failed else 1
        return asyncio.run(_mcp())
    runner = {"chat": cmd_chat, "run": cmd_run, "doctor": cmd_doctor}[cmd]
    try:
        return asyncio.run(runner(s, args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
