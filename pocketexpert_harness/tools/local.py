# SPDX-License-Identifier: Apache-2.0
"""本地工具: 工作区文件读写 与 Python 代码执行。

- 文件工具只在工作区目录 (PEH_WORKSPACE, 默认 ./workspace) 里读写, 路径逃不出去。
- run_python 在子进程里跑, 工作目录是工作区, **环境变量里的密钥一律不传进去**, 并设 CPU / 内存 / 输出上限。
  它不是安全沙箱: 本机跑就是在你的电脑上执行模型写的代码。命令行默认每次先问; 网页服务默认只在容器里开。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from pocketexpert_harness.config import Settings
from pocketexpert_harness.tools import Tool

MAX_READ = 200_000
PY_TIMEOUT = 90
PY_OUTPUT = 20_000
#: 子进程只继承这些环境变量 (不含任何 KEY / TOKEN)
PY_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "PYTHONIOENCODING")


def resolve_in(root: Path, rel: str) -> Path:
    root = root.resolve()
    p = (root / (rel or ".")).resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"路径越出工作区: {rel}")
    return p


def _limits() -> None:      # pragma: no cover — 在子进程里执行
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (PY_TIMEOUT, PY_TIMEOUT + 5))
        resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 << 20, 200 << 20))
    except Exception:
        pass


async def run_python(code: str, cwd: Path, timeout: float = PY_TIMEOUT) -> tuple[int, str]:
    cwd.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in PY_ENV_KEEP if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=cwd, prefix=".peh_", delete=False, encoding="utf-8") as f:
        f.write(code)
        script = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", script, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            preexec_fn=_limits if os.name == "posix" else None)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -9, f"(超时 {int(timeout)} 秒, 已终止)"
        text = out.decode("utf-8", "replace")
        if len(text) > PY_OUTPUT:
            text = text[:PY_OUTPUT // 2] + f"\n…(输出太长, 中间省略 {len(text) - PY_OUTPUT} 字)…\n" + text[-PY_OUTPUT // 2:]
        return proc.returncode or 0, text
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass


def make_tools(s: Settings, *, confirm_python=None) -> list[Tool]:
    ws = s.workspace

    async def _list(args: dict) -> str:
        base = resolve_in(ws, str(args.get("path") or "."))
        if not base.exists():
            return f"不存在: {args.get('path') or '.'}"
        rows = []
        for p in sorted(base.rglob("*") if args.get("recursive") else base.iterdir()):
            if p.name.startswith(".peh_"):
                continue
            rel = p.relative_to(ws.resolve())
            rows.append(f"{rel}/" if p.is_dir() else f"{rel}  ({p.stat().st_size} B)")
            if len(rows) >= 500:
                rows.append("…(只列前 500 项)")
                break
        return "\n".join(rows) or "(空目录)"

    async def _read(args: dict) -> str:
        p = resolve_in(ws, str(args.get("path") or ""))
        if not p.is_file():
            return f"不是文件: {args.get('path')}"
        data = p.read_bytes()[:MAX_READ]
        return data.decode("utf-8", "replace")

    async def _write(args: dict) -> str:
        p = resolve_in(ws, str(args.get("path") or ""))
        if p == ws.resolve():
            return "需要文件名"
        p.parent.mkdir(parents=True, exist_ok=True)
        content = str(args.get("content") or "")
        if args.get("append"):
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")
        return f"已写入 {p.relative_to(ws.resolve())} ({len(content)} 字)"

    path_prop = {"type": "string", "description": "工作区里的相对路径"}
    tools = [
        Tool(name="list_files", handler=_list, obs_cap=6000,
             description="列出工作区里的文件。",
             parameters={"type": "object", "properties": {"path": path_prop, "recursive": {"type": "boolean"}}}),
        Tool(name="read_file", handler=_read, obs_cap=15000,
             description="读取工作区里的一个文本文件。",
             parameters={"type": "object", "properties": {"path": path_prop}, "required": ["path"]}),
        Tool(name="write_file", handler=_write, obs_cap=500,
             description="在工作区里写文件 (覆盖, 或 append=true 追加)。交付物 (报告、代码、数据) 写成文件。",
             parameters={"type": "object", "properties": {"path": path_prop, "content": {"type": "string"},
                                                          "append": {"type": "boolean"}}, "required": ["path", "content"]}),
    ]
    if s.python_mode != "off":
        async def _py(args: dict) -> str:
            code, out = await run_python(str(args.get("code") or ""), ws)
            return f"退出码 {code}\n{out}" if out else f"退出码 {code} (无输出)"
        tools.append(Tool(
            name="run_python", handler=_py, obs_cap=8000, timeout=PY_TIMEOUT + 10,
            confirm=confirm_python if s.python_mode == "ask" else None,
            description="运行一段 Python 3 代码 (工作目录 = 工作区), 返回标准输出。用于计算、数据处理、画图存文件。"
                        "用 print 输出结果; 单次最长 90 秒; 能用的库以运行环境里装了的为准。",
            parameters={"type": "object", "properties": {"code": {"type": "string", "description": "完整的 Python 代码"}},
                        "required": ["code"]}))
    return tools
