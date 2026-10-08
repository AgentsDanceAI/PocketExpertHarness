<h1 align="center">
  <img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/logo.png" alt="PocketExpertHarness" width="88"><br>
  PocketExpertHarness
</h1>

<p align="center">
  <b>Your open-source personal AI agent that gets things done</b><br>
  The same kernel that runs PocketExpert AI (口袋专家 AI) in production, self-hosted in one command on your own computer or server: it searches, reads pages, runs code, reads and writes files, sees images and draws charts, plugs into MCP and skills, and remembers who you are.
</p>

<p align="center">
  <a href="https://github.com/AgentsDanceAI/PocketExpertHarness/blob/main/README.md">简体中文</a> · <b>English</b>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-5_min-06B6D4?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-what-is-an-agent-harness"><img src="https://img.shields.io/badge/Start_here-Background-F59E0B?style=for-the-badge" alt="Background"></a>
  <a href="https://agentsdance.ai"><img src="https://img.shields.io/badge/Try_online-No_signup-8B5CF6?style=for-the-badge" alt="Try online"></a>
  <a href="https://github.com/AgentsDanceAI/PocketExpertHarness/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-22C55E?style=for-the-badge" alt="Apache-2.0"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/pocketexpert-harness/"><img src="https://img.shields.io/pypi/v/pocketexpert-harness?logo=pypi&logoColor=white&label=PyPI&color=3775A9" alt="PyPI"></a>
  <a href="https://github.com/AgentsDanceAI/PocketExpertHarness/releases/latest"><img src="https://img.shields.io/github/v/release/AgentsDanceAI/PocketExpertHarness?logo=github&label=Release&color=24292F" alt="GitHub Release"></a>
  <a href="#-community"><img src="https://img.shields.io/badge/groups-WeChat_·_Xiaohongshu-07C160?logo=wechat&logoColor=white" alt="WeChat and Xiaohongshu groups"></a>
  <a href="#1-run-with-docker-recommended-includes-web-search"><img src="https://img.shields.io/badge/Docker-one_command-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
  <a href="#-mcp"><img src="https://img.shields.io/badge/MCP-stdio_·_HTTP-111111" alt="MCP"></a>
  <a href="#-skills"><img src="https://img.shields.io/badge/skills-SKILL.md-8B5CF6" alt="SKILL.md"></a>
  <a href="#-pocketexpert-ai"><img src="https://img.shields.io/badge/PocketExpert_AI-scan_to_get_the_app-0D96F6" alt="PocketExpert AI-scan to get the app"></a>
  <a href="https://github.com/AgentsDanceAI/PocketExpertHarness/actions/workflows/ci.yml"><img src="https://github.com/AgentsDanceAI/PocketExpertHarness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://x.com/AgentsDanceAI"><img src="https://img.shields.io/badge/X-@AgentsDanceAI-000000?logo=x&logoColor=white" alt="X"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/screenshot.png" alt="Web chat" width="820">
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

- **2026-10-08** 🎉 **v0.3.0** — kernel synced with 7 production updates (parallel tool calls within a step, turn traces, the old JSON-action guessing removed); a reproducible [CSV-to-report example](https://github.com/AgentsDanceAI/PocketExpertHarness/tree/main/examples/sales-report).
- **2026-09-29** **v0.2.0** — upload images, files and videos in the web UI (paperclip, paste or drag-and-drop); vision models see images directly; charts and files in answers render inline and download with one click, plus a Workspace files panel; a live timer from the moment you send (thinking → step N → total time); copy buttons for answers and code blocks; matplotlib bundled with CJK fonts preconfigured; `peh run -f FILE` and `/file PATH` in terminal chat.
- **2026-09-24** 🎉 **v0.1.0, first open-source release** — the same kernel as PocketExpert AI in production; web chat (steer mid-run, stop any time) and CLI; MCP (stdio / Streamable HTTP), SKILL.md skills, long-term memory; presets for DeepSeek / Qwen / SiliconFlow / OpenAI / OpenRouter / Ollama; `docker compose` ships SearXNG for web search.

## 🧪 A reproducible example

[12 CSV rows → summary, chart and report](examples/sales-report/README.en.md): synthetic input, the complete prompt, actual reference outputs, and independent numerical verification. Start with a small task you can check before scaling up.

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

### 2. Or run it locally (one line, no clone)

Install [uv](https://docs.astral.sh/uv/) (think `npx` for Python; or `pip install uv`), then:

```bash
export PEH_PROVIDER=deepseek LLM_API_KEY=sk-...
uvx pocketexpert-harness serve # open http://127.0.0.1:8080
```

The first run fetches it from PyPI in a few seconds; after that it starts instantly. To keep `peh` on your PATH:

```bash
uv tool install pocketexpert-harness     # or: pipx install / pip install pocketexpert-harness
```

To hack on the code, clone the repo and `pip install -e .`.

**What `peh` is**: this project's own command (short for PocketExpert Harness), available after any of the installs above. The ones you'll use:

| Command | What it does |
|---|---|
| `peh serve` | web chat (the same UI as the Docker setup) |
| `peh` | chat right in the terminal |
| `peh run "question"` | ask once and exit — handy in scripts |
| `peh run -f report.xlsx "summarize"` | ask with attachments (repeat `-f`); in terminal chat use `/file PATH` |
| `peh doctor` | check that model, search and MCP are configured |

**Web search (bring your own when running locally; without it everything works except searching the web)** — pick one:

- **Run your own SearXNG (free, no key, recommended)**: needs Docker; grab the ready-made config first:
  ```bash
  curl -fsSLo searxng.yml https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/deploy/searxng/settings.yml
  docker run -d --name searxng -p 127.0.0.1:8888:8080 -e SEARXNG_SECRET=some-random-string \
    -v "$PWD/searxng.yml:/etc/searxng/settings.yml:ro" searxng/searxng
  export SEARXNG_URL=http://127.0.0.1:8888
  ```
- **Tavily**: get a key at [tavily.com](https://tavily.com), then `export TAVILY_API_KEY=tvly-...`
- **Brave Search**: get a key from the [Brave Search API](https://brave.com/search/api/), then `export BRAVE_API_KEY=...`

Then run `peh doctor`: the search line should read `✓ 联网搜索: searxng` (or tavily / brave).
The Docker setup needs none of this — `docker compose up -d` starts SearXNG alongside.

### Something wrong? Run `peh doctor` first

It makes one real model call, then reports search, code execution and MCP status line by line. With Docker: `docker compose exec harness peh doctor`.

- **The page loads but never answers**: usually a wrong key or no balance; the model line in doctor shows the raw error.
- **Use it from other machines on your network**: set `PEH_ACCESS_TOKEN` in `.env` first, then drop `127.0.0.1:` from the port mapping in `docker-compose.yml`. Locally, `peh serve --host 0.0.0.0` refuses to start without a token.
- **Web search returns nothing**: with Docker, give the bundled SearXNG a moment on first start; locally, configure one of the three search options above.

## 🧠 Models

Any OpenAI-compatible `/chat/completions` endpoint with tool calling works. Presets: `deepseek`, `qwen`, `siliconflow`, `openai`, `openrouter`, `ollama`. Override with `LLM_MODEL` and `LLM_BASE_URL`.

## 💭 Thinking mode

On by default: models that can reason **think before every step**. The web UI streams the reasoning live and folds it into "思考 · N 字" afterwards; the terminal shows it in grey. Within a turn the previous step's reasoning is passed back so the model keeps its train of thought instead of starting over (required by DeepSeek; verified faster and steadier on Alibaba Bailian). Models that reject the parameter (e.g. `qwen-vl-max`) fall back to no thinking automatically. Control it with `PEH_THINKING=auto|on|off`; `peh doctor` checks it with a real call.

Bailian (`enable_thinking`) is verified with deepseek-v3.2 / qwen-plus / qwen3-max; DeepSeek (`thinking.type=enabled`), SiliconFlow (`enable_thinking`) and OpenRouter (`reasoning.enabled`) follow their official docs and are not yet verified by us. On Bailian deepseek-v3.2, two multi-step tasks run twice each finished faster with thinking on (84 s / 117 s vs 91 s / 135 s; 91 s / 50 s vs 106 s / 124 s), all answers correct; without passing the reasoning back, thinking was slower than not thinking at all.

## 🖼️ Images, files and charts

Attach files in the web UI with the paperclip, by pasting, or by dragging them in (≤ 50MB each, up to 10 per message); they land in the workspace under `uploads/`. Images go straight to vision models — detected from the model name (`vl`, `vision`, `gpt-4o`, `claude`, `gemini`, `omni`, …) or forced with `PEH_VISION=on|off`. Video and audio can be uploaded and processed as files, but no audio/video understanding model is wired in yet. Ask for a chart and it is drawn with matplotlib, saved to the workspace and shown inline; the Workspace files panel lists everything the agent produced.

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/architecture-en-dark.svg">
  <img alt="PocketExpertHarness architecture: the kernel (Inbox → ReactLoop → SessionLog + hooks) connects to the shell through three ports: llm, tools and assemble" src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/architecture-en-light.svg">
</picture>

The kernel has exactly three ports: call the model, run a tool, assemble the system prompt. The rest of this repository is one implementation of those ports; swap any of them.

## 📡 Events

`assistant_delta`, `step`, `observation`, `steer`, `notice`, `done`. The web API streams the same events over SSE at `POST /api/sessions/{id}/messages`; steer with `POST /api/sessions/{id}/steer`, stop with `POST /api/sessions/{id}/stop`.

## 🛡️ Security notes

- `run_python` is **not a sandbox**. Locally it runs model-written code on your machine; the CLI asks first by default and the web server enables it only inside a container. Secrets in the environment are not passed to the child process.
- The web server binds to 127.0.0.1 and refuses to listen publicly unless `PEH_ACCESS_TOKEN` is set.
- See [SECURITY.md](https://github.com/AgentsDanceAI/PocketExpertHarness/blob/main/SECURITY.md) to report a vulnerability.

## 🧪 PocketExpert AI

This repository is the kernel. The full product, [PocketExpert AI](https://agentsdance.ai), runs on the same engine and adds 250+ domain experts, multi-expert groups, and one-click slides / web pages / videos — no model or key setup. Scan with your phone, or click to download on your computer:

<table align="center">
  <tr>
    <td align="center" width="176">
      <img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/miniprogram.jpg" width="140" alt="PocketExpert AI WeChat Mini Program code"><br>
      <b>WeChat</b><br>
      <sub>Mini Program · scan</sub>
    </td>
    <td align="center" width="176">
      <img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/qr-ios.png" width="140" alt="PocketExpert AI iPhone / iPad download QR code"><br>
      <b>iPhone / iPad</b><br>
      <sub>Scan → App Store</sub>
    </td>
    <td align="center" width="176">
      <img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/qr-android.png" width="140" alt="PocketExpert AI Android download QR code"><br>
      <b>Android</b><br>
      <sub>Scan → APK</sub>
    </td>
    <td align="center" width="176">
      <a href="https://agentsdance.ai/downloads/AgentsDance-mac-arm64.dmg"><img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/dl-mac.png" width="140" alt="Download PocketExpert AI for Mac (Apple Silicon)"></a><br>
      <b>Mac</b><br>
      <sub>Apple Silicon · download</sub>
    </td>
    <td align="center" width="176">
      <a href="https://agentsdance.ai/downloads/AgentsDance-win-x64.zip"><img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/dl-windows.png" width="140" alt="Download PocketExpert AI for Windows (x64)"></a><br>
      <b>Windows</b><br>
      <sub>x64 · download</sub>
    </td>
  </tr>
</table>

<p align="center">Or just open <a href="https://agentsdance.ai">agentsdance.ai</a> in a browser · Intel Mac and Windows ARM builds on the <a href="https://agentsdance.ai/download">download page</a> · Android also on <a href="https://play.google.com/store/apps/details?id=ai.agentsdance.mobile">Google Play</a> · one account everywhere</p>

## 💬 Community

<!-- 小红书群二维码 28 天有效, 当前这张 2026-10-27 过期, 到期前换 docs/xhs-group.png; 微信群码是永久的 -->
<table>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/wecom-group.png" width="200" alt="Scan to join the 口袋专家AI·交流群 WeChat group"><br><b>WeChat group</b><br><sub>Scan with WeChat</sub></td>
    <td align="center"><img src="https://raw.githubusercontent.com/AgentsDanceAI/PocketExpertHarness/main/docs/xhs-group.png" width="200" alt="Scan to join the 口袋专家AI交流群 Xiaohongshu group"><br><b>Xiaohongshu group</b><br><sub>Scan with the Xiaohongshu app</sub></td>
  </tr>
</table>

- Groups (Chinese-speaking): a WeChat group and a Xiaohongshu (RED) group — scan the matching code above; the Xiaohongshu one needs the Xiaohongshu app
- Problems or feature requests: open an [issue](https://github.com/AgentsDanceAI/PocketExpertHarness/issues)
- Updates: X [@AgentsDanceAI](https://x.com/AgentsDanceAI)
- Anything else: support@agentsdance.ai

## 🤝 Contributing

See [CONTRIBUTING.md](https://github.com/AgentsDanceAI/PocketExpertHarness/blob/main/CONTRIBUTING.md). `kernel/` is exported from upstream; please open an issue instead of editing it here.

## 📄 License

[Apache License 2.0](https://github.com/AgentsDanceAI/PocketExpertHarness/blob/main/LICENSE)

## ⭐ Star History

<a href="https://star-history.com/#AgentsDanceAI/PocketExpertHarness&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=AgentsDanceAI/PocketExpertHarness&type=Date" width="600" />
  </picture>
</a>

If it helps, give it a ⭐ star.
