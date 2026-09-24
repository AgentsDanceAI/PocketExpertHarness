# SPDX-License-Identifier: Apache-2.0
"""PocketExpertHarness 内核 —— 与口袋专家 AI 生产环境同一份代码, 由私有仓原样导出, 请勿在此修改。

  loop          ReAct 回合驱动器 (Inbox / SessionLog / ReactLoop, 三个端口: llm / tools / assemble)
  hooks         回合钩子 (步前 / 请求 / 请求出错 / 模型停了 四个挂载点, 默认: 步数、时长、瞬时错误重试、过渡语纠正)
  skill_format  SKILL.md frontmatter 解析

改动请提 issue 或在 PR 里说明, 我们在上游改完后重新导出。
"""
