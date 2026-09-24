# SPDX-License-Identifier: Apache-2.0
"""配置: 环境变量 (可写在当前目录的 .env 里) → Settings。

只需要三样就能跑: 选一家模型服务 (PEH_PROVIDER) 和它的 API Key。其余都有默认值。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

#: 常用的 OpenAI 兼容服务。模型名只是默认值, 用 LLM_MODEL 覆盖。
PROVIDERS: dict[str, dict] = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "key_env": "DASHSCOPE_API_KEY"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "model": "deepseek-ai/DeepSeek-V3", "key_env": "SILICONFLOW_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-chat", "key_env": "OPENROUTER_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b", "key_env": ""},
}

#: 代码执行开关: on = 直接跑; ask = 命令行里每次先问; off = 不给模型这个工具。
PYTHON_MODES = ("on", "ask", "off")


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """极简 .env 读取: KEY=VALUE 一行一个, # 开头是注释; 已存在的环境变量不覆盖。"""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def in_container() -> bool:
    return Path("/.dockerenv").exists() or _env("PEH_IN_CONTAINER") == "1"


@dataclass
class Settings:
    provider: str = "deepseek"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    extra_body: dict = field(default_factory=dict)

    home: Path = field(default_factory=lambda: Path.home() / ".pocketexpert-harness")
    workspace: Path = field(default_factory=lambda: Path.cwd() / "workspace")
    max_steps: int = 30
    python_mode: str = "ask"
    allow_private_urls: bool = False

    searxng_url: str = ""
    tavily_api_key: str = field(default="", repr=False)
    brave_api_key: str = field(default="", repr=False)

    mcp_config: Path | None = None
    skills_dirs: list[Path] = field(default_factory=list)
    access_token: str = field(default="", repr=False)
    agent_name: str = "PocketExpert Harness"

    @classmethod
    def from_env(cls, *, serving: bool = False) -> "Settings":
        load_dotenv()
        provider = _env("PEH_PROVIDER", "deepseek").lower()
        preset = PROVIDERS.get(provider, {})
        key = _env("LLM_API_KEY") or (_env(preset["key_env"]) if preset.get("key_env") else "")
        home = Path(_env("PEH_HOME") or Path.home() / ".pocketexpert-harness").expanduser()
        mcp = _env("PEH_MCP_CONFIG")
        mcp_path = Path(mcp).expanduser() if mcp else next(
            (p for p in (Path.cwd() / "mcp.json", home / "mcp.json") if p.is_file()), None)
        dirs = [Path(d).expanduser() for d in _env("PEH_SKILLS_DIRS").split(os.pathsep) if d.strip()]
        dirs += [p for p in (Path.cwd() / "skills", home / "skills") if p not in dirs]
        # 网页服务里没法逐次确认, 所以默认只在容器里放开代码执行 (容器就是沙箱)
        default_py = ("on" if in_container() else "off") if serving else "ask"
        py = _env("PEH_PYTHON", default_py).lower()
        s = cls(
            provider=provider,
            base_url=(_env("LLM_BASE_URL") or preset.get("base_url", "")).rstrip("/"),
            api_key=key,
            model=_env("LLM_MODEL") or preset.get("model", ""),
            temperature=float(_env("LLM_TEMPERATURE")) if _env("LLM_TEMPERATURE") else None,
            max_tokens=int(_env("LLM_MAX_TOKENS")) if _env("LLM_MAX_TOKENS") else None,
            extra_body=json.loads(_env("LLM_EXTRA_BODY", "{}")),
            home=home,
            workspace=Path(_env("PEH_WORKSPACE") or Path.cwd() / "workspace").expanduser(),
            max_steps=int(_env("PEH_MAX_STEPS", "30")),
            python_mode=py if py in PYTHON_MODES else "off",
            allow_private_urls=_env("PEH_ALLOW_PRIVATE_URLS") == "1",
            searxng_url=_env("SEARXNG_URL").rstrip("/"),
            tavily_api_key=_env("TAVILY_API_KEY"),
            brave_api_key=_env("BRAVE_API_KEY"),
            mcp_config=mcp_path,
            skills_dirs=dirs,
            access_token=_env("PEH_ACCESS_TOKEN"),
            agent_name=_env("PEH_AGENT_NAME", "PocketExpert Harness"),
        )
        return s

    def problems(self) -> list[str]:
        """启动前能查出来的配置问题 (空列表 = 可以跑)。"""
        out = []
        if not self.base_url:
            out.append(f"未知的 PEH_PROVIDER={self.provider!r}: 请设 LLM_BASE_URL, 或从 {', '.join(PROVIDERS)} 里选一个")
        if not self.model:
            out.append("没有模型名: 请设 LLM_MODEL")
        if not self.api_key and self.provider != "ollama":
            env = PROVIDERS.get(self.provider, {}).get("key_env") or "LLM_API_KEY"
            out.append(f"没有 API Key: 请设 LLM_API_KEY (或 {env})")
        return out

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "sessions").mkdir(exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
