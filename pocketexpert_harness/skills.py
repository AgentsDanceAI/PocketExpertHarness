# SPDX-License-Identifier: Apache-2.0
"""技能: 一个目录一个技能, 入口是 SKILL.md (头部 YAML 写 name / description, 下面是给模型的操作说明)。

渐进加载: 系统提示里只列技能名与一句话说明; 模型判断用得上时调 use_skill 读全文,
技能目录里的其它文件 (模板、参考资料、脚本) 用 use_skill(name, file=...) 按需再读。
查找顺序: 内置示例 → ./skills → ~/.pocketexpert-harness/skills → PEH_SKILLS_DIRS; 同名的后者覆盖前者。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pocketexpert_harness.kernel.skill_format import parse_skill_frontmatter, skill_triggers_from_meta, term_hits
from pocketexpert_harness.tools import Tool

BUILTIN_DIR = Path(__file__).parent / "builtin_skills"
MAX_SKILL_FILE = 120_000


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str
    triggers: list[str] = field(default_factory=list)

    def files(self) -> list[str]:
        root = self.path.parent
        return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                      if p.is_file() and p.name != "SKILL.md" and not p.name.startswith("."))[:100]


def load_skill(skill_md: Path) -> Skill:
    text = skill_md.read_text(encoding="utf-8")[:MAX_SKILL_FILE]
    meta, body = parse_skill_frontmatter(text)
    name = str(meta.get("name") or skill_md.parent.name).strip()
    desc = str(meta.get("description") or "").strip() or (body.strip().splitlines() or [""])[0][:200]
    return Skill(name=name, description=desc, path=skill_md, body=body.strip(), triggers=skill_triggers_from_meta(meta))


def discover(dirs: list[Path], *, include_builtin: bool = True) -> dict[str, Skill]:
    found: dict[str, Skill] = {}
    for base in ([BUILTIN_DIR] if include_builtin else []) + list(dirs):
        if not base.is_dir():
            continue
        for md in sorted(base.glob("*/SKILL.md")):
            try:
                sk = load_skill(md)
            except (OSError, UnicodeDecodeError):
                continue
            found[sk.name] = sk
    return found


def match(goal: str, skills: dict[str, Skill], limit: int = 2) -> list[Skill]:
    """用户这句话命中了哪些技能的触发词 (与口袋专家 AI 同一套判法: 拉丁词按词边界, 中文按子串)。
    命中多的排前面; 没有触发词的技能不会被自动选中, 只能由模型自己 use_skill。"""
    low = (goal or "").casefold()
    scored = []
    for sk in skills.values():
        hits = sum(1 for t in sk.triggers if term_hits(t, low))
        if hits:
            scored.append((hits, sk.name, sk))
    return [sk for _h, _n, sk in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]]


def catalog_text(skills: dict[str, Skill]) -> str:
    if not skills:
        return ""
    lines = ["可用技能 (做对应的事之前先用 use_skill 读它的完整说明, 再照做):"]
    for sk in skills.values():
        lines.append(f"- {sk.name}: {sk.description[:200]}")
    return "\n".join(lines)


def make_tool(skills: dict[str, Skill]) -> Tool:
    async def _use(args: dict) -> str:
        name = str(args.get("name") or "").strip()
        sk = skills.get(name) or next((s for s in skills.values() if s.name.lower() == name.lower()), None)
        if sk is None:
            return f"没有名为 {name!r} 的技能。可用: {', '.join(skills) or '(无)'}"
        rel = str(args.get("file") or "").strip()
        if rel:
            root = sk.path.parent.resolve()
            p = (root / rel).resolve()
            if root not in p.parents or not p.is_file():
                return f"技能 {sk.name} 里没有文件 {rel!r}。有这些: {', '.join(sk.files()) or '(无)'}"
            return p.read_text(encoding="utf-8", errors="replace")[:MAX_SKILL_FILE]
        extra = sk.files()
        tail = f"\n\n(这个技能目录里还有: {', '.join(extra)} —— 需要时用 use_skill(name, file=...) 读取)" if extra else ""
        return f"# 技能: {sk.name}\n\n{sk.body}{tail}"

    return Tool(name="use_skill", handler=_use, obs_cap=30000,
                description="读取一个技能的完整操作说明 (或技能目录里的附带文件)。技能列表见系统提示。",
                parameters={"type": "object", "properties": {
                    "name": {"type": "string", "description": "技能名"},
                    "file": {"type": "string", "description": "可选: 技能目录里的附带文件相对路径"}},
                    "required": ["name"]})
