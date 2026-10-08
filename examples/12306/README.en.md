# China rail tickets (12306)

[简体中文](README.md)

Ask about Chinese train tickets in one sentence — seat availability, transfer options and stops — all from **live 12306 data**.

PocketExpertHarness **ships with it built in**: the open-source [12306-mcp](https://github.com/Joooook/12306-mcp) (MIT), the same backend that powers the train-ticket tool in [PocketExpert AI](https://agentsdance.ai)'s travel expert.

![One question, the three fastest trains](answer.png)

## How it found the answer

For the question above it took 5 steps, thinking before each: get today's date (so "next Friday" resolves to Oct 16), look up the station codes for Beijing and Shanghai, query tickets, then filter and sort with Python.

![Each step's reasoning and tool call can be expanded](process.png)

## Run it yourself

1. **Docker**: nothing to do, it is preinstalled. **Local** (`uvx` / `pip`): install [Node.js](https://nodejs.org) 20+; it is started with `npx` automatically (the first download takes about 30 seconds and uses a China npm mirror by default).
2. Run `peh doctor`; `✓ MCP 12306 (内置: 查火车票): 8 个工具` means it is ready, otherwise that line tells you what is missing.
3. Ask in the web UI or terminal, e.g. `peh run "G25 次列车经停哪些站？几点到南京南？"` (which stations does train G25 stop at, and when does it reach Nanjing South?).

To turn it off, set `PEH_BUILTIN_MCP=off` or add `"12306": {"disabled": true}` to `mcp.json`. Outside China, set `npm_config_registry` to use another npm registry.

## Good to know

- **Lookup only — it cannot buy tickets.** Book in the 12306 app or at 12306.cn. It does not log in, solve captchas or grab tickets.
- **Availability changes constantly**; 12306's booking page is the source of truth.
- Tested on 2026-10-08 with Bailian `deepseek-v3.2` (thinking on): 25 s to 2 min per question.
