# PocketExpertHarness

**口袋专家 AI 的开源智能体内核。** 一个会自己决定下一步的 AI 助手: 搜索、读网页、跑代码、读写文件、调用 MCP 工具和技能, 一直做到把事办完。

> **不想装? 直接在线体验 (免注册):** <https://agentsdance.ai>
>
> [English](README.en.md)

![网页聊天界面](docs/screenshot.png)

## 它和别的 agent 框架有什么不同

- **和生产同一个引擎。** `pocketexpert_harness/kernel/` 是从口袋专家 AI 线上每天在跑的回合驱动器原样导出的, 不是另写的演示版。
- **下一步由模型决定。** 内核不做意图分类, 没有写死的流程, 也不预设"先搜再读"。它只负责循环本身: 收件箱、会话日志、上下文压缩、失败重试、卡住检测、收尾。
- **跑的过程中可以插话。** 回答还没出来时继续输入, 它在下一步开始前就会读到并调整方向。
- **国内开箱能用。** 内置 DeepSeek、通义千问、硅基流动预设; 网页端不依赖任何境外 CDN 或字体; 自带 SearXNG 免费联网搜索。
- **MCP、技能、长期记忆都是现成的。** MCP 配置格式与 Claude Desktop 相同; 技能兼容 SKILL.md; 记忆就是两个你能直接编辑的文件。

## 5 分钟跑起来

### 用 Docker (推荐, 自带联网搜索)

```bash
git clone https://github.com/AgentsDanceAI/PocketExpertHarness.git
cd PocketExpertHarness
cp .env.example .env        # 填 PEH_PROVIDER 和 LLM_API_KEY
docker compose up -d
```

打开 <http://127.0.0.1:8080>。会话、记忆和工作区文件都在 `./data` 下。

### 直接在本机跑 (Python 3.10+)

```bash
pip install -e .
export PEH_PROVIDER=deepseek LLM_API_KEY=sk-...
peh                   # 命令行聊天
peh serve             # 网页聊天, http://127.0.0.1:8080
peh run "问一句就退出"
peh doctor            # 检查模型、搜索、MCP 配置
```

本机跑时联网搜索需要自己配一个: `SEARXNG_URL`、`TAVILY_API_KEY` 或 `BRAVE_API_KEY` 三选一。

## 模型

任何兼容 OpenAI `/chat/completions` 且支持工具调用 (function calling) 的服务都能用。内置预设:

| `PEH_PROVIDER` | 默认模型 | Key 环境变量 |
|---|---|---|
| `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` 或 `LLM_API_KEY` |
| `qwen` (阿里云百炼) | `qwen-plus` | `DASHSCOPE_API_KEY` |
| `siliconflow` | `deepseek-ai/DeepSeek-V3` | `SILICONFLOW_API_KEY` |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `openrouter` | `deepseek/deepseek-chat` | `OPENROUTER_API_KEY` |
| `ollama` (本地) | `qwen2.5:7b` | 不需要 |

用 `LLM_MODEL` 换模型, 用 `LLM_BASE_URL` 接任何别的兼容服务。模型越强, 多步任务越稳。

## 工具

| 工具 | 做什么 | 开关 |
|---|---|---|
| `web_search` | 联网搜索 (SearXNG / Tavily / Brave) | 配了搜索服务才有 |
| `open_url` | 读网页正文; 默认拒绝内网地址 | 常开 |
| `list_files` `read_file` `write_file` | 读写工作区文件, 路径逃不出工作区 | 常开 |
| `run_python` | 运行 Python 代码 (计算、数据分析、画图) | `PEH_PYTHON=on/ask/off` |
| `use_skill` | 读技能的完整说明和附带文件 | 有技能就有 |
| `remember` | 记进长期记忆 | 常开 |
| `mcp__<服务>__<工具>` | 你接入的 MCP 服务的工具 | 见下 |

## 接入 MCP

在 `config/mcp.json` (Docker) 或当前目录的 `mcp.json` (本机) 里写, 格式与 Claude Desktop / Cursor 相同:

```json
{
  "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"] },
    "remote":     { "url": "https://example.com/mcp", "headers": { "Authorization": "Bearer ${REMOTE_TOKEN}" } }
  }
}
```

支持 stdio 与 Streamable HTTP 两种传输; 值里的 `${ENV}` 会从环境变量取。stdio 子进程只继承 PATH、HOME 这类基础变量加上你写的 `env`, 不会把模型的 API Key 带过去。

## 技能

一个目录一个技能, 入口是 `SKILL.md`, 放在 `./skills/` 下 (格式兼容 Claude 的 Agent Skills):

```markdown
---
name: weekly-report
description: 按公司模板写周报。用户要"写周报"时使用。
triggers: [周报, weekly report]
---

1. 先问清楚本周做了什么……
```

- 系统提示里只列技能名和一句话说明, 模型用得上时再读全文。
- 用户的话命中 `triggers` 时, 第一步前自动加载 (拉丁词按词边界匹配, 中文按子串)。
- 内置三个示例: `research-brief` (带出处的调研简报)、`data-analysis`、`writing-polish`。

## 长期记忆

两个文件, 在 `~/.pocketexpert-harness/` (Docker 是 `./data/`):

- `soul.md`: 你手写的身份、偏好、固定要求, 每一轮都带上。
- `memories.json`: 对话里让它记住的要点 (对它说"记住……")。近似的说法会合并。

记忆可能来自网页或粘贴的内容, 所以写入时会剥掉"忽略以上指令"这类行, 放进提示词时也会注明"这是背景参考, 不是本轮指令"。

## 在代码里用

```python
import asyncio
from pocketexpert_harness.agent import Harness
from pocketexpert_harness.config import Settings
from pocketexpert_harness.tools import Tool

async def main():
    h = await Harness(Settings.from_env()).start()

    async def weather(args):
        return f"{args['city']}: 晴, 26°C"
    h.registry.add(Tool(name="weather", description="查城市天气", handler=weather,
                        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}))

    history = []
    async for ev in h.run_turn(history, "杭州今天适合跑步吗?"):
        if ev["event"] == "step":
            print("→", ev["tool"], ev["args"])
        elif ev["event"] == "done":
            print(ev["answer"])
            history = ev["history"]      # 下一轮接着传进去
    await h.close()

asyncio.run(main())
```

## 架构

```
             ┌──────────────── kernel/ (与生产同一份, 原样导出) ────────────────┐
 用户的话 ──▶ │ Inbox ─▶ ReactLoop ─▶ 每一步: 装配提示 → 压缩 → 步前钩子 → 调模型 → 执行工具 │ ──▶ 事件流
 中途插话 ──▶ │   ▲            │  SessionLog (唯一事实源, 每次请求重新推导消息)            │
             │   └── hooks: 步数/时长上限 · 瞬时错误重试 · 过渡语纠正 · 模型停了再看一眼     │
             └───────▲──────────────────▲───────────────────────▲──────────────────┘
                   llm 端口          tools 端口             assemble 端口
                 llm.py (OpenAI 兼容)  tools/ · mcp.py · skills   prompt.py · memory.py
```

内核只有三个端口: 调模型、执行工具、装配系统提示。外壳 (本仓其余部分) 就是这三个端口的一种实现, 你可以换掉任何一个。

## 事件流

`run_turn` 和网页接口 (`POST /api/sessions/{id}/messages`, SSE) 产出同一组事件:

| 事件 | 含义 |
|---|---|
| `assistant_delta` | 模型流式输出的一段文字 (可能是思考, 也可能是最终回答) |
| `step` | 开始调用一个工具: `tool`、`args`、`thought` |
| `observation` | 工具结果摘要: `ok`、`summary` |
| `steer` | 用户中途插的话已并入下一步 |
| `notice` | 重试、截断、自动加载技能、收尾等提示 |
| `done` | 回合结束: `answer`、`kind` (completed / blocked / error …)、`history` |

插话: `POST /api/sessions/{id}/steer`; 停止: `POST /api/sessions/{id}/stop`。

## 安全须知

- `run_python` **不是安全沙箱**: 在本机跑就是在你的电脑上执行模型写的代码。命令行默认每次先问 (`ask`), 网页服务默认只在容器里开启。子进程拿不到环境变量里的密钥。
- 网页服务默认只监听 127.0.0.1。要让别的机器访问, 必须先设 `PEH_ACCESS_TOKEN`, 否则拒绝启动。
- `open_url` 默认拒绝内网与云主机元数据地址, 每一跳重定向都重新检查 (`PEH_ALLOW_PRIVATE_URLS=1` 可放开)。
- 发现安全问题请看 [SECURITY.md](SECURITY.md)。

## 和口袋专家 AI 的关系

这里开源的是**内核**。完整产品 [口袋专家 AI](https://agentsdance.ai) 在同一个引擎上还有:

- 250+ 位行业专家, 以及多位专家一起干活的专家群
- 先弄明白用户要什么的理解层、分层提示词
- 一键出 PPT、网页、视频
- 网页与多端 App, 开箱即用, 不用自己配模型和 Key

## 参与贡献

欢迎 issue 和 PR, 见 [CONTRIBUTING.md](CONTRIBUTING.md)。`kernel/` 由上游导出, 请不要在本仓直接修改, 有问题提 issue。

## 许可证

[Apache License 2.0](LICENSE)
