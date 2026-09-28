# SPDX-License-Identifier: Apache-2.0
"""生成 README 用的架构图 (docs/architecture-{zh,en}-{light,dark}.svg)。

改图就改这里再跑: python docs/architecture.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

PALETTES = {
    "light": dict(bg="#ffffff", ink="#1f2328", muted="#59636e", line="#d1d9e0", accent="#1e7cf2",
                  kernel_fill="#f0f6ff", kernel_line="#1e7cf2", chip="#ffffff", chip_line="#9ec5fb",
                  bar="#e3eefe", shell_fill="#f6f8fa", out_fill="#f6f8fa", hook_fill="#fff8e6", hook_line="#e6c36a"),
    "dark": dict(bg="#0d1117", ink="#e6edf3", muted="#9198a1", line="#3d444d", accent="#4da3ff",
                 kernel_fill="#0f1c2e", kernel_line="#4da3ff", chip="#0d1117", chip_line="#2f5f9e",
                 bar="#15263d", shell_fill="#151b23", out_fill="#151b23", hook_fill="#2a2210", hook_line="#8a6d1f"),
}

TEXT = {
    "zh": dict(
        user="用户消息", steer="中途插话", steer_sub="steer",
        kernel="kernel/", kernel_sub="与口袋专家 AI 生产环境同一份代码 · 原样导出",
        inbox="Inbox", inbox_sub="收件箱",
        loop="ReactLoop", loop_sub="每一步",
        steps=["装配提示", "压缩上下文", "步前钩子", "调用模型", "执行工具"],
        again="没收口 → 下一步",
        log="SessionLog", log_sub="唯一事实源 · 每次请求都从日志重新推导消息",
        hooks="hooks", hooks_sub="步数 / 时长上限 · 瞬时错误重试 · 过渡语纠正 · 模型停了再看一眼",
        events="事件流 (SSE)", events_items=["assistant_delta", "step · observation", "steer · notice", "done"],
        clients="网页 · 命令行 · 你的代码",
        shell="外壳 · 本仓其余部分, 三个端口都能换成你自己的实现",
        ports=[
            ("llm 端口", "llm.py · OpenAI 兼容", ["DeepSeek · 通义 · 硅基流动", "OpenAI · OpenRouter · Ollama"]),
            ("tools 端口", "tools/ · mcp.py · skills.py", ["搜索 · 读网页 · 文件 · Python", "MCP (stdio / HTTP) · SKILL.md 技能"]),
            ("assemble 端口", "prompt.py · memory.py", ["系统提示 + 技能目录 + 运行时快照", "soul.md + 长期记忆"]),
        ],
    ),
    "en": dict(
        user="User message", steer="Steer mid-run", steer_sub="inbox.steer()",
        kernel="kernel/", kernel_sub="the same code that runs PocketExpert AI in production · exported verbatim",
        inbox="Inbox", inbox_sub="messages",
        loop="ReactLoop", loop_sub="every step",
        steps=["Assemble", "Compact", "Pre-step hooks", "Call model", "Run tools"],
        again="not concluded → next step",
        log="SessionLog", log_sub="single source of truth · messages re-derived for every request",
        hooks="hooks", hooks_sub="step / time caps · transient-error retry · narration guard · last look when the model stops",
        events="Event stream (SSE)", events_items=["assistant_delta", "step · observation", "steer · notice", "done"],
        clients="Web · CLI · your code",
        shell="Shell · the rest of this repo; replace any of the three ports with your own",
        ports=[
            ("llm port", "llm.py · OpenAI-compatible", ["DeepSeek · Qwen · SiliconFlow", "OpenAI · OpenRouter · Ollama"]),
            ("tools port", "tools/ · mcp.py · skills.py", ["search · read page · files · Python", "MCP (stdio / HTTP) · SKILL.md skills"]),
            ("assemble port", "prompt.py · memory.py", ["system prompt + skills + runtime", "soul.md + long-term memory"]),
        ],
    ),
}

FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', "
        "'Microsoft YaHei', 'Noto Sans CJK SC', 'Noto Sans', Helvetica, Arial, sans-serif")
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"


def t(x, y, s, *, size=14, fill, weight=400, anchor="start", mono=False, opacity=1.0):
    fam = MONO if mono else FONT
    return (f'<text x="{x}" y="{y}" font-family="{escape(fam, {chr(39): "&apos;"})}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" opacity="{opacity}">{escape(s)}</text>')


def rect(x, y, w, h, *, fill, stroke, rx=10, sw=1.2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def arrow(x1, y1, x2, y2, color, *, dash=None, sw=1.6):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d} '
            f'marker-end="url(#ah-{color[1:]})"/>')


def build(lang: str, theme: str) -> str:
    P, T = PALETTES[theme], TEXT[lang]
    W, H = 1200, 660
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="PocketExpertHarness architecture">']
    o.append("<defs>")
    for c in {P["accent"], P["muted"], P["ink"]}:
        o.append(f'<marker id="ah-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                 f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>')
    o.append("</defs>")
    o.append(rect(0.5, 0.5, W - 1, H - 1, fill=P["bg"], stroke=P["line"], rx=16, sw=1))

    # ── 左: 输入 ──
    o.append(rect(28, 118, 150, 48, fill=P["out_fill"], stroke=P["line"]))
    o.append(t(103, 147, T["user"], size=15, fill=P["ink"], weight=600, anchor="middle"))
    o.append(rect(28, 196, 150, 58, fill=P["out_fill"], stroke=P["line"]))
    o.append(t(103, 221, T["steer"], size=15, fill=P["ink"], weight=600, anchor="middle"))
    o.append(t(103, 242, T["steer_sub"], size=12, fill=P["muted"], anchor="middle", mono=True))

    # ── 中: kernel ──
    KX, KY, KW, KH = 206, 40, 780, 348
    o.append(rect(KX, KY, KW, KH, fill=P["kernel_fill"], stroke=P["kernel_line"], rx=16, sw=1.8))
    o.append(t(KX + 22, KY + 32, T["kernel"], size=18, fill=P["accent"], weight=700, mono=True))
    o.append(t(KX + 110, KY + 31, T["kernel_sub"], size=13.5, fill=P["muted"]))
    # 输入箭头 (画在 kernel 框之后, 否则被框盖住)
    o.append(arrow(178, 142, 234, 142, P["ink"]))
    o.append(f'<path d="M178,225 L262,225 L262,174" fill="none" stroke="{P["ink"]}" stroke-width="1.6" '
             f'marker-end="url(#ah-{P["ink"][1:]})"/>')
    # Inbox
    o.append(rect(236, 112, 108, 60, fill=P["chip"], stroke=P["chip_line"]))
    o.append(t(290, 138, T["inbox"], size=15, fill=P["ink"], weight=700, anchor="middle", mono=True))
    o.append(t(290, 158, T["inbox_sub"], size=12, fill=P["muted"], anchor="middle"))
    o.append(arrow(344, 142, 372, 142, P["accent"]))
    # ReactLoop
    LX, LY, LW, LH = 374, 86, 590, 162
    o.append(rect(LX, LY, LW, LH, fill=P["bar"], stroke=P["chip_line"], rx=12))
    o.append(t(LX + 16, LY + 26, T["loop"], size=15, fill=P["ink"], weight=700, mono=True))
    o.append(t(LX + 112, LY + 26, T["loop_sub"], size=12.5, fill=P["muted"]))
    cw, gap, cy = 106, 8, LY + 48
    xs = [LX + 16 + i * (cw + gap) for i in range(5)]
    for i, (x, s) in enumerate(zip(xs, T["steps"], strict=True)):
        o.append(rect(x, cy, cw, 48, fill=P["chip"], stroke=P["chip_line"], rx=9))
        o.append(t(x + cw / 2, cy + 29, s, size=13.5, fill=P["ink"], weight=600, anchor="middle"))
        if i < 4:
            o.append(arrow(x + cw + 1, cy + 24, x + cw + gap - 1, cy + 24, P["accent"], sw=1.4))
    # 回环
    ly = cy + 76
    o.append(f'<path d="M{xs[4] + cw / 2},{cy + 48} L{xs[4] + cw / 2},{ly} L{xs[0] + cw / 2},{ly} L{xs[0] + cw / 2},{cy + 50}" '
             f'fill="none" stroke="{P["accent"]}" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah-{P["accent"][1:]})"/>')
    o.append(f'<rect x="{(xs[0] + xs[4] + cw) / 2 - 78}" y="{ly - 11}" width="156" height="22" fill="{P["bar"]}"/>')
    o.append(t((xs[0] + xs[4] + cw) / 2, ly + 5, T["again"], size=12.5, fill=P["accent"], anchor="middle"))
    # SessionLog
    o.append(rect(LX, 262, LW, 42, fill=P["chip"], stroke=P["chip_line"], rx=9))
    o.append(t(LX + 16, 288, T["log"], size=14, fill=P["ink"], weight=700, mono=True))
    o.append(t(LX + 118, 288, T["log_sub"], size=12.5, fill=P["muted"]))
    # hooks
    o.append(rect(236, 318, 728, 46, fill=P["hook_fill"], stroke=P["hook_line"], rx=9))
    o.append(t(254, 346, T["hooks"], size=14, fill=P["ink"], weight=700, mono=True))
    o.append(t(318, 346, T["hooks_sub"], size=12.5, fill=P["muted"]))

    # ── 右: 输出 ──
    o.append(arrow(986, 150, 1018, 150, P["ink"]))
    o.append(rect(1020, 96, 156, 150, fill=P["out_fill"], stroke=P["line"]))
    o.append(t(1098, 122, T["events"], size=14, fill=P["ink"], weight=700, anchor="middle"))
    for i, s in enumerate(T["events_items"]):
        o.append(t(1098, 150 + i * 23, s, size=12, fill=P["muted"], anchor="middle", mono=True))
    o.append(arrow(1098, 246, 1098, 282, P["muted"]))
    o.append(rect(1020, 284, 156, 48, fill=P["out_fill"], stroke=P["line"]))
    o.append(t(1098, 313, T["clients"], size=13, fill=P["ink"], weight=600, anchor="middle"))

    # ── 下: 外壳与三个端口 ──
    o.append(rect(206, 428, 780, 206, fill="none", stroke=P["line"], rx=16, dash="6 5"))
    o.append(t(228, 456, T["shell"], size=13.5, fill=P["muted"], weight=600))
    bw, bg = 232, 22
    for i, (title, sub, items) in enumerate(T["ports"]):
        x = 226 + i * (bw + bg)
        cx = x + bw / 2
        o.append(arrow(cx, 478, cx, 392, P["accent"], dash="4 4", sw=1.5))
        o.append(rect(x, 478, bw, 136, fill=P["shell_fill"], stroke=P["line"], rx=12))
        o.append(t(cx, 505, title, size=15, fill=P["accent"], weight=700, anchor="middle"))
        o.append(t(cx, 528, sub, size=12, fill=P["ink"], anchor="middle", mono=True))
        o.append(f'<line x1="{x + 20}" y1="541" x2="{x + bw - 20}" y2="541" stroke="{P["line"]}" stroke-width="1"/>')
        for j, s in enumerate(items):
            o.append(t(cx, 566 + j * 24, s, size=12.5, fill=P["muted"], anchor="middle"))

    o.append("</svg>")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    for lang in TEXT:
        for theme in PALETTES:
            path = OUT / f"architecture-{lang}-{theme}.svg"
            path.write_text(build(lang, theme), encoding="utf-8")
            print("wrote", path.name)
