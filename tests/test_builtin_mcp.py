# SPDX-License-Identifier: Apache-2.0
"""装上就有的 MCP 服务 (查火车票): 有 Node.js 20+ 就启用, 没有就跳过并说明原因; mcp.json 同名覆盖 / 关掉; 开关。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pocketexpert_harness import mcp as M
from pocketexpert_harness.config import Settings

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


def fake_env(monkeypatch, *, npx=True, binary=False, node=20):
    paths = {"npx": "/usr/bin/npx" if npx else None, "12306-mcp": "/usr/local/bin/12306-mcp" if binary else None,
             "node": "/usr/bin/node" if node else None}
    monkeypatch.setattr(M.shutil, "which", lambda name: paths.get(name))
    monkeypatch.setattr(M, "_node_major", lambda: node)
    monkeypatch.delenv("npm_config_registry", raising=False)
    monkeypatch.delenv("NPM_CONFIG_REGISTRY", raising=False)


def test_npx_with_node20_starts_12306_from_the_cn_mirror(monkeypatch):
    fake_env(monkeypatch)
    on, skipped = M.builtin_servers()
    spec = on["12306"]
    assert spec["command"] == "npx" and spec["args"] == ["-y", M.TRAIN_MCP_PACKAGE] and not skipped
    assert spec["env"]["npm_config_registry"] == "https://registry.npmmirror.com"
    assert spec["timeout"] >= 120, "第一次要下载, 超时要放宽"
    monkeypatch.setenv("npm_config_registry", "https://registry.npmjs.org")
    assert M.builtin_servers()[0]["12306"]["env"]["npm_config_registry"] == "https://registry.npmjs.org"


def test_preinstalled_binary_is_used_without_download(monkeypatch):
    fake_env(monkeypatch, npx=False, binary=True, node=None)
    assert M.builtin_servers()[0]["12306"]["command"] == "12306-mcp"


def test_missing_or_old_node_is_skipped_not_failed(monkeypatch, tmp_path):
    fake_env(monkeypatch, npx=False, node=None)
    on, skipped = M.builtin_servers()
    assert not on and "Node.js 20+" in skipped["12306"]
    fake_env(monkeypatch, node=18)
    on, skipped = M.builtin_servers()
    assert not on and "现在是 18" in skipped["12306"]
    mgr = M.MCPManager(None, builtins=True)
    assert mgr.load() == {}
    row = mgr.status()[0]
    assert row["status"] == "skipped" and row["builtin"] and not mgr.failed, "缺 Node 不是配置错误"


def test_user_config_overrides_or_disables_the_builtin(monkeypatch, tmp_path):
    fake_env(monkeypatch)
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"12306": {"disabled": True}}}))
    assert M.MCPManager(cfg, builtins=True).load() == {}
    cfg.write_text(json.dumps({"mcpServers": {"12306": {"url": "http://my-gateway.local/mcp"}}}))
    assert M.MCPManager(cfg, builtins=True).load() == {"12306": {"url": "http://my-gateway.local/mcp"}}
    fake_env(monkeypatch, npx=False, node=None)
    mgr = M.MCPManager(cfg, builtins=True)
    mgr.load()
    assert not mgr.skipped, "自己配了同名服务, 就不该再提示缺 Node"


def test_builtins_off_means_nothing_extra(monkeypatch, tmp_path):
    fake_env(monkeypatch)
    assert M.MCPManager(None).load() == {} and M.MCPManager(None, builtins=False).status() == []


def test_settings_switch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PEH_BUILTIN_MCP", raising=False)
    assert Settings.from_env().builtin_mcp is True
    monkeypatch.setenv("PEH_BUILTIN_MCP", "off")
    assert Settings.from_env().builtin_mcp is False
    assert Settings().builtin_mcp is False, "直接构造 Settings 不起子进程"


async def test_builtin_spec_starts_with_its_own_timeout(monkeypatch):
    # 用假服务代替 12306-mcp, 走一遍真实启动: 内置标记出现在状态里, 工具挂上
    monkeypatch.setattr(M, "builtin_servers", lambda: ({"12306": {"command": sys.executable, "args": [FAKE], "builtin": True,
                                                                  "timeout": 120.0}}, {}))
    mgr = M.MCPManager(None, builtins=True)
    await mgr.start(timeout=1)
    try:
        row = mgr.status()[0]
        assert row["status"] == "ready" and row["builtin"] and row["tools"] > 0
    finally:
        await mgr.close()


def test_docker_image_pins_the_same_12306_mcp_version():
    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    assert f"npm install -g --omit=dev --ignore-scripts {M.TRAIN_MCP_PACKAGE}" in dockerfile, "镜像预装的版本要和代码里钉的一致"


async def test_builtin_retries_once_then_explains(monkeypatch, tmp_path):
    # 第一次起不来 (像 12306 一时不应答), 第二次好了 → 照常可用
    flag = tmp_path / "started-once"
    script = tmp_path / "flaky.py"
    script.write_text(f"import os, runpy, sys\nflag = {str(flag)!r}\n"
                      "if not os.path.exists(flag):\n    open(flag, 'w').close(); sys.exit(1)\n"
                      f"runpy.run_path({FAKE!r}, run_name='__main__')\n")
    monkeypatch.setattr(M, "builtin_servers", lambda: ({"12306": {"command": sys.executable, "args": [str(script)], "builtin": True,
                                                                  "timeout": 10.0, "retries": 1}}, {}))
    monkeypatch.setattr(M.asyncio, "sleep", _no_sleep)
    mgr = M.MCPManager(None, builtins=True)
    await mgr.start()
    try:
        assert mgr.status()[0]["status"] == "ready" and not mgr.failed
    finally:
        await mgr.close()
    # 两次都起不来 → 人话说明, 并标成内置
    monkeypatch.setattr(M, "builtin_servers", lambda: ({"12306": {"command": "/nonexistent/12306-mcp", "builtin": True,
                                                                  "timeout": 5.0, "retries": 1}}, {}))
    mgr = M.MCPManager(None, builtins=True)
    await mgr.start()
    row = mgr.status()[0]
    assert row["status"] == "failed" and row["builtin"] and row["error"].startswith("查火车票服务没起来")


async def _no_sleep(_s):
    return None
