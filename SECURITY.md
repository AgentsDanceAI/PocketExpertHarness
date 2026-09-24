# 安全问题报告

发现安全漏洞时, 请**不要**公开提 issue, 发邮件到 **support@agentsdance.ai**, 标题写明「PocketExpertHarness 安全问题」。
我们会在 3 个工作日内回复, 修复后在发布说明里致谢 (除非你希望匿名)。

已知且有意为之的边界 (不算漏洞):

- `run_python` 不是沙箱: 本机模式下就是在你的电脑上执行代码。需要隔离请用 Docker。
- 你自己在 `mcp.json` 里配置的 MCP 服务, 权限由你决定。
