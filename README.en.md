<h1 align="center">
  <img src="docs/logo.png" alt="PocketExpertHarness" width="88"><br>
  PocketExpertHarness
</h1>

<p align="center">
  <b>The open-source agent harness behind PocketExpert AI (口袋专家 AI)</b><br>
  An assistant that decides its own next step — search, read pages, run code, read and write files, call MCP tools and skills — until the job is done.
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-5_min-06B6D4?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-what-is-an-agent-harness"><img src="https://img.shields.io/badge/Start_here-Background-F59E0B?style=for-the-badge" alt="Background"></a>
  <a href="https://agentsdance.ai"><img src="https://img.shields.io/badge/Try_online-No_signup-8B5CF6?style=for-the-badge" alt="Try online"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-22C55E?style=for-the-badge" alt="Apache-2.0"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-3776AB?logo=python&logoColor=white" alt="Python ≥3.10">
  <img src="https://img.shields.io/badge/Docker-one_command-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/MCP-stdio_·_HTTP-111111" alt="MCP">
  <img src="https://img.shields.io/badge/skills-SKILL.md-8B5CF6" alt="SKILL.md">
  <a href="https://github.com/AgentsDanceAI/PocketExpertHarness/actions/workflows/ci.yml"><img src="https://github.com/AgentsDanceAI/PocketExpertHarness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://x.com/AgentsDanceAI"><img src="https://img.shields.io/badge/X-@AgentsDanceAI-000000?logo=x&logoColor=white" alt="X"></a>
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="Web chat" width="820">
</p>

> **Try it online, no signup:** <https://agentsdance.ai>
>
> **On your phone:** get Pocket Expert AI for iPhone / iPad on the [App Store](https://apps.apple.com/app/%E5%8F%A3%E8%A2%8B%E4%B8%93%E5%AE%B6ai/id6801482441). Android, the WeChat Mini Program and desktop apps are on the [download page](https://agentsdance.ai/download).

---

## 🤔 What is an agent harness

A language model on its own can only talk: text in, text out. To actually get something done — look things up, read pages, do math, edit files, call other services — it needs a layer that acts on its behalf: hand it the tools, run whichever one it picks, feed the result back, and let it decide the next step; along the way, compact the context when it grows too long, retry failed calls, wrap up when it gets stuck, and refuse what it must not do.

That layer is the **agent harness**. **The model thinks; the harness acts, remembers and keeps it within bounds.**

<p align="center">
  <code>agent = model (thinks) + harness (loop · tools · memory · skills · safety bounds)</code>
</p>

PocketExpertHarness is the harness that runs [PocketExpert AI](https://agentsdance.ai) in production every day, open-sourced together with a ready-to-use shell (web chat, CLI, web search, MCP, skills, long-term memory). It is for you if you want to:

- **Run your own AI assistant**: up in 5 minutes with Docker, on your own model key, with your data on your own machine;
- **See how an AI assistant actually works**: the kernel is a handful of files, and the event stream shows what it thought and which tool it called at every step;
- **Build on top of it**: swap the model, add tools, write skills, connect MCP servers, or call it straight from Python.

## ✨ Why this one

- **Same engine as production.** `pocketexpert_harness/kernel/` is exported verbatim from the turn driver that runs PocketExpert AI in production every day. It is not a separate demo.
- **The model decides the next step.** No intent classifier, no hard-coded pipeline. The kernel only owns the loop: inbox, session log, context compaction, retries, stuck detection and wrap-up.
- **Steer it mid-run.** Keep typing while it works; your note is picked up before the next step.
- **Works well in mainland China.** Presets for DeepSeek, Qwen (DashScope) and SiliconFlow; the web UI loads no foreign CDN or fonts; a bundled SearXNG gives free web search.
- **MCP, skills and long-term memory built in.** MCP config uses the Claude Desktop format; skills use SKILL.md; memory is two files you can edit.

## 📰 What's new

- **2026-09-24** 🎉 **v0.1.0, first open-source release** — the same kernel as PocketExpert AI in production; web chat (steer mid-run, stop any time) and CLI; MCP (stdio / Streamable HTTP), SKILL.md skills, long-term memory; presets for DeepSeek / Qwen / SiliconFlow / OpenAI / OpenRouter / Ollama; `docker compose` ships SearXNG for web search.

## 🚀 Quick start

### 0. Get a model key

Pick any one:

| Use | Get a key at | Put in `.env` |
|---|---|---|
| DeepSeek (recommended, cheap and capable) | [DeepSeek Platform](https://platform.deepseek.com/api_keys) | `PEH_PROVIDER=deepseek`<br>`LLM_API_KEY=sk-...` |
| Any model on OpenRouter | [openrouter.ai/keys](https://openrouter.ai/keys) | `PEH_PROVIDER=openrouter`<br>`OPENROUTER_API_KEY=sk-...` |
| Free, nothing leaves your machine | install [Ollama](https://ollama.com), then `ollama pull qwen2.5:7b` | `PEH_PROVIDER=ollama` |

More presets and custom endpoints under [Models](#-models).

### 1. Run with Docker (recommended, includes web search)

Install [Docker](https://docs.docker.com/get-docker/) first (Docker Desktop on Windows / macOS), then:

```bash
git clone https://github.com/AgentsDanceAI/PocketExpertHarness.git
cd PocketExpertHarness
cp .env.example .env        # open .env and fill in the two lines above
docker compose up -d        # the first run builds the image, give it a few minutes
```

Open <http://127.0.0.1:8080>. Sessions, memory and workspace files live in `./data` and survive container removal.

- Different port: add `PEH_PORT=8090` to `.env`
- Update: `git pull && docker compose up -d --build`
- Stop: `docker compose down`

### 2. Or run it locally (Python 3.10+)

```bash
git clone https://github.com/AgentsDanceAI/PocketExpertHarness.git
cd PocketExpertHarness
pip install -e .
export PEH_PROVIDER=deepseek LLM_API_KEY=sk-...
peh                   # terminal chat
peh serve             # web chat at http://127.0.0.1:8080
peh run "one-shot question"
peh doctor            # check model, search and MCP config
```

For web search when running locally, set one of `SEARXNG_URL`, `TAVILY_API_KEY` or `BRAVE_API_KEY` (it works without, just offline).

### Something wrong? Run `peh doctor` first

It makes one real model call, then reports search, code execution and MCP status line by line. With Docker: `docker compose exec harness peh doctor`.

- **The page loads but never answers**: usually a wrong key or no balance; the model line in doctor shows the raw error.
- **Use it from other machines on your network**: set `PEH_ACCESS_TOKEN` in `.env` first, then drop `127.0.0.1:` from the port mapping in `docker-compose.yml`. Locally, `peh serve --host 0.0.0.0` refuses to start without a token.
- **Web search returns nothing**: with Docker, give the bundled SearXNG a moment on first start; locally, configure one of the three search options above.

## 🧠 Models

Any OpenAI-compatible `/chat/completions` endpoint with tool calling works. Presets: `deepseek`, `qwen`, `siliconflow`, `openai`, `openrouter`, `ollama`. Override with `LLM_MODEL` and `LLM_BASE_URL`.

## 🔧 Tools

`web_search`, `open_url` (blocks private and metadata addresses), `list_files` / `read_file` / `write_file` (confined to the workspace), `run_python` (`PEH_PYTHON=on|ask|off`), `use_skill`, `remember`, and `mcp__<server>__<tool>` for every connected MCP server.

## 🔌 MCP

Put servers in `config/mcp.json` (Docker) or `./mcp.json` (local), Claude Desktop format. stdio and Streamable HTTP are supported; `${ENV}` references are expanded. stdio servers only inherit basic variables such as PATH and HOME plus the `env` you set, never the model API key.

## 📚 Skills

One directory per skill with a `SKILL.md` (name, description, optional `triggers`). The prompt lists names and descriptions; the model reads full instructions with `use_skill`. When the user's message hits a trigger word, the skill is loaded automatically before the first step.

## 💾 Long-term memory

`soul.md` (hand-written identity and preferences, included every turn) and `memories.json` (points the agent was asked to remember). Lines that look like prompt injection are stripped on write, and memory is injected as clearly labeled background.

## 🐍 Use it from code

```python
import asyncio
from pocketexpert_harness.agent import Harness
from pocketexpert_harness.config import Settings

async def main():
    h = await Harness(Settings.from_env()).start()
    async for ev in h.run_turn([], "Introduce yourself in one sentence"):
        if ev["event"] == "done":
            print(ev["answer"])
    await h.close()

asyncio.run(main())
```

The kernel has exactly three ports: call the model, run a tool, assemble the system prompt. The rest of this repository is one implementation of those ports; swap any of them.

## 📡 Events

`assistant_delta`, `step`, `observation`, `steer`, `notice`, `done`. The web API streams the same events over SSE at `POST /api/sessions/{id}/messages`; steer with `POST /api/sessions/{id}/steer`, stop with `POST /api/sessions/{id}/stop`.

## 🛡️ Security notes

- `run_python` is **not a sandbox**. Locally it runs model-written code on your machine; the CLI asks first by default and the web server enables it only inside a container. Secrets in the environment are not passed to the child process.
- The web server binds to 127.0.0.1 and refuses to listen publicly unless `PEH_ACCESS_TOKEN` is set.
- See [SECURITY.md](SECURITY.md) to report a vulnerability.

## 🧪 PocketExpert AI

This repository is the kernel. The full product at [agentsdance.ai](https://agentsdance.ai) adds 250+ domain experts, multi-expert groups, an understanding layer and layered prompts, one-click slides / web pages / videos, and ready-to-use apps with no model setup: web, [iPhone / iPad](https://apps.apple.com/app/%E5%8F%A3%E8%A2%8B%E4%B8%93%E5%AE%B6ai/id6801482441), Android, the WeChat Mini Program and desktop, all on one account.

## 💬 Community

- Problems or feature requests: open an [issue](https://github.com/AgentsDanceAI/PocketExpertHarness/issues)
- Updates: X [@AgentsDanceAI](https://x.com/AgentsDanceAI)
- Anything else: support@agentsdance.ai

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). `kernel/` is exported from upstream; please open an issue instead of editing it here.

## 📄 License

[Apache License 2.0](LICENSE)

## ⭐ Star History

<a href="https://star-history.com/#AgentsDanceAI/PocketExpertHarness&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date" width="600" />
  </picture>
</a>

If it helps, give it a ⭐ star.
