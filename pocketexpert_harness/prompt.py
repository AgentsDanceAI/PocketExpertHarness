# SPDX-License-Identifier: Apache-2.0
"""系统提示: 每一步由内核调用 assemble(ctx) 重新装配 (底稿 + 技能目录 + 长期记忆 + 运行时快照)。"""
from __future__ import annotations

import datetime as _dt

_WEEKDAYS = "一二三四五六日"

BASE = """你是 {name}, 一个能动手做事的 AI 助手, 运行在 PocketExpertHarness (口袋专家 AI 的开源内核) 上。

## 怎么做事
- 先弄清用户要什么。简单问题直接回答; 需要查证、计算、读写文件或多步操作的, 用工具去做, 不要凭印象编造。
- 每一步做当下最有用的一件事; 信息够了就停下来, 直接给最终回答。
- 工具失败时看报错换个办法, 同一个办法不要反复试。
{web_rule}- 较长的交付物 (报告、代码、数据表) 写进工作区文件, 回答里说明文件名和要点。
- 用户说「记住…」「以后都…」, 或纠正了你的做法时, 用 remember 记下来。

## 怎么回答
- 用用户使用的语言回答。先给结论, 再给必要的依据。
- 不写「好的, 我来帮你」之类的客套, 不预告你将要做什么 —— 直接给内容。
- 长度跟着问题走: 简单问题几句话说清; 复杂任务再分小节。"""

WEB_RULE = "- 会变的事实 (新闻、价格、版本号、统计数据) 先用 web_search 查, 引用时带上链接。\n"


def build_system_prompt(*, name: str, has_web: bool, skills_text: str, memory_text: str,
                        workspace: str, tool_names: list[str], now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now().astimezone()
    parts = [BASE.format(name=name, web_rule=WEB_RULE if has_web else "")]
    if skills_text:
        parts.append(skills_text)
    if memory_text:
        parts.append(memory_text)
    runtime = [f"- 当前时间: {now:%Y-%m-%d %H:%M} (周{_WEEKDAYS[now.weekday()]}, {now:%Z})".replace(", )", ")"),
               f"- 工作区目录: {workspace}"]
    if not has_web:
        runtime.append("- 没有配置联网搜索: 涉及最新信息时如实告诉用户你查不到, 不要编。")
    if "run_python" not in tool_names:
        runtime.append("- 代码执行未开启: 需要计算时手算或说明步骤。")
    parts.append("## 运行环境\n" + "\n".join(runtime))
    return "\n\n".join(parts)
