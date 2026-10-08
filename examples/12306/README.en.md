# China rail tickets (12306)

[简体中文](README.md)

Ask about Chinese train tickets in one sentence — seat availability, transfer options and stops — all from **live 12306 data**.

It uses the open-source [12306-mcp](https://github.com/Joooook/12306-mcp) (MIT), the same backend that powers the train-ticket tool in [PocketExpert AI](https://agentsdance.ai)'s travel expert. PocketExpertHarness needs no code changes: just add one MCP server.

![One question, the three fastest trains](answer.png)

## How it found the answer

For the question above it took 5 steps, thinking before each: get today's date (so "next Friday" resolves to Oct 16), look up the station codes for Beijing and Shanghai, query tickets, then filter and sort with Python.

![Each step's reasoning and tool call can be expanded](process.png)

## Run it yourself

1. Install Node.js 18+ (for `npx`). The Docker image already includes it.
2. Put [mcp.json](mcp.json) in place: next to where you run `peh` (or set `PEH_MCP_CONFIG`), or as `config/mcp.json` for Docker, then `docker compose restart`.
3. Run `peh doctor`; `✓ MCP 12306: 8 个工具` means it is connected. The first run downloads 12306-mcp (about 30 seconds).
4. Ask in the web UI or terminal, e.g. `peh run "G25 次列车经停哪些站？几点到南京南？"` (which stations does train G25 stop at, and when does it reach Nanjing South?).

The `npm_config_registry` line points `npx` at a mirror in China; delete it if you are elsewhere.

## Good to know

- **Lookup only — it cannot buy tickets.** Book in the 12306 app or at 12306.cn. It does not log in, solve captchas or grab tickets.
- **Availability changes constantly**; 12306's booking page is the source of truth.
- Tested on 2026-10-08 with Bailian `deepseek-v3.2` (thinking on): 25 s to 2 min per question.
