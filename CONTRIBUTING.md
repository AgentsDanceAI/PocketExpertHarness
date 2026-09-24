# 参与贡献

谢谢你愿意帮忙! 下面几条说清楚怎么提、哪些地方怎么改。

## 目录分工

- `pocketexpert_harness/kernel/`: 从口袋专家 AI 上游**原样导出**, 与生产环境是同一份代码。请不要在本仓直接改 —— CI 会核对它与导出清单 (`kernel/EXPORT.json`) 一致。发现问题或有改进建议, 请开 issue 说明, 我们在上游改完后重新导出。
- 其余目录 (模型接口、工具、MCP、技能、记忆、命令行、网页端、文档): 欢迎直接提 PR。

## 本地开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

测试不需要真实的模型 Key: 用的是按脚本回复的假模型 (`tests/conftest.py`)。

## 提交要求

- 每个提交都要带 DCO 签名 (`git commit -s`), 表示你有权以 Apache-2.0 贡献这段代码:
  `Signed-off-by: 你的名字 <邮箱>`
- 一个 PR 做一件事; 行为变化要配测试。
- 新工具请写清楚它的安全边界 (能访问什么、不能访问什么)。

## 行为准则

就事论事, 对人友善。
