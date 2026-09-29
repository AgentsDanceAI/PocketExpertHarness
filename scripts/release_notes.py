# SPDX-License-Identifier: Apache-2.0
"""发版说明: 每个版本一份 .github/release-notes/<标签>.md, 发布流水线先查格式再用它建 GitHub Release。

格式 (与口袋专家 AI 的 Release 同一套):
  # (2026-09-29) 🎉 v0.2.0 — 亮点 · 亮点 · 亮点        ← 标题; 🎉 只给核心升级
  ## 新增功能 / ## 优化改进 / ## Bug 修复              ← 三段, 按这个顺序, 没有的段写「- 无」
  - feat(范围): 说明 (提交号)                          ← 每条带提交号或 PR 号

  python scripts/release_notes.py check v0.2.0            只检查
  python scripts/release_notes.py render v0.2.0 OUT.md    检查并写出正文 (标题打印到标准输出)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / ".github" / "release-notes"
SECTIONS = ("新增功能", "优化改进", "Bug 修复")
REPO = "https://github.com/AgentsDanceAI/PocketExpertHarness"
TITLE_RE = re.compile(r"^# \((\d{4}-\d{2}-\d{2})\) (?:🎉 )?(v\d+\.\d+\.\d+) — (\S.*\S)$")
REF_RE = re.compile(r"\((?:#\d+|[0-9a-f]{7,40})(?:, (?:#\d+|[0-9a-f]{7,40}))*\)$")


def parse(tag: str, text: str) -> tuple[str, str]:
    """返回 (标题, 正文); 格式不对抛 ValueError, 一次列出所有问题。"""
    lines = text.strip().splitlines()
    problems = []
    m = TITLE_RE.match(lines[0]) if lines else None
    if not m:
        problems.append("第一行要写成「# (YYYY-MM-DD) [🎉 ]vX.Y.Z — 亮点 · 亮点」")
    elif m.group(2) != tag:
        problems.append(f"标题里的版本 {m.group(2)} 和标签 {tag} 不一致")
    heads = [ln[3:].strip() for ln in lines if ln.startswith("## ")]
    if tuple(heads) != SECTIONS:
        problems.append(f"要有且按顺序只有三段: {' / '.join(SECTIONS)} (现在是: {' / '.join(heads) or '无'})")
    for ln in lines[1:]:
        if ln.startswith("- ") and ln.strip() != "- 无" and not REF_RE.search(ln.strip()):
            problems.append(f"这条缺提交号或 PR 号: {ln.strip()[:60]}")
    if problems:
        raise ValueError(f"{tag} 的发版说明格式不对:\n  " + "\n  ".join(problems))
    return lines[0][2:], "\n".join(lines[1:]).strip()


def previous_tag(tag: str) -> str | None:
    def key(t: str) -> tuple[int, ...]:
        return tuple(int(x) for x in t[1:].split("."))
    older = [p.stem for p in NOTES_DIR.glob("v*.md") if key(p.stem) < key(tag)]
    return max(older, key=key) if older else None


def render(tag: str) -> tuple[str, str]:
    path = NOTES_DIR / f"{tag}.md"
    if not path.exists():
        raise ValueError(f"缺发版说明 {path.relative_to(ROOT)} —— 打标签前先按口袋专家 AI 的格式写好")
    title, body = parse(tag, path.read_text(encoding="utf-8"))
    v = tag[1:]
    foot = f"安装: `uvx pocketexpert-harness serve` · [PyPI](https://pypi.org/project/pocketexpert-harness/{v}/)"
    prev = previous_tag(tag)
    if prev:
        foot += f" · [完整改动]({REPO}/compare/{prev}...{tag})"
    return title, f"{body}\n\n---\n{foot}\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("check", "render"):
        print(__doc__)
        return 2
    try:
        title, body = render(argv[1])
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    if argv[0] == "render":
        Path(argv[2]).write_text(body, encoding="utf-8")
        print(title)
    else:
        print(f"✓ {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
