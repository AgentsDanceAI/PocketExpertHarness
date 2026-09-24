# SPDX-License-Identifier: Apache-2.0
# 由口袋专家 AI 私有仓原样导出 (skill_format.py), 请勿在此修改 —— 改动请提 issue, 上游改完后重新导出。
"""SKILL.md 格式: frontmatter 解析与触发词清洗 —— 纯标准库。

技能文件沿用生态里的 Claude 式 SKILL.md: 头部一段 `---` 包住的 YAML, 下面是 Markdown 正文。
这里只做格式层 (解析头、去头、清洗触发词、判断触发词是否命中); 存储、打分、装载由调用方负责。
开源外壳 PocketExpertHarness 的内核导出件之一: 这个文件不许 import 本仓任何模块。
"""
from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)
_FM_TEXT_KEYS = {"name", "description", "version", "license"}
_FM_LIST_KEYS = {"triggers", "keywords"}

def _fm_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def parse_skill_frontmatter(text: str) -> tuple[dict, str]:
    """极简 SKILL.md frontmatter 解析 — 生态里的技能文件 (Claude 式) 头部带 YAML,
    直接存库会把 `---` 块原样注入提示词。只认 name/description/version/license 标量
    (含 >|折叠块) 与 triggers/keywords 列表 (行内 [a,b] 或 - 缩进), 其余键一律忽略;
    不引 yaml 依赖。返回 (meta, 去头正文); 无 frontmatter 时 meta 为空、正文原样。"""
    match = _FRONTMATTER_RE.match(text or "")
    if not match:
        return {}, text or ""
    meta: dict = {}
    lines = match.group(1).splitlines()
    i = 0
    list_key = None
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and list_key:
            item = _fm_scalar(stripped[2:])
            if item:
                meta.setdefault(list_key, []).append(item)
            continue
        if ":" not in stripped:
            list_key = None
            continue
        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        value = value.strip()
        list_key = None
        if value in {">", ">-", "|", "|-"}:
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                block.append(lines[i].strip())
                i += 1
            if key in _FM_TEXT_KEYS:
                meta[key] = " ".join(part for part in block if part)
            continue
        if key in _FM_LIST_KEYS:
            if value.startswith("[") and value.endswith("]"):
                items = [_fm_scalar(part) for part in value[1:-1].split(",")]
                meta[key] = [part for part in items if part]
            elif not value:
                list_key = key
            else:
                meta[key] = [p for p in (_fm_scalar(v) for v in value.split(",")) if p]
        elif key in _FM_TEXT_KEYS and value:
            meta[key] = _fm_scalar(value)
    return meta, (text or "")[match.end():].lstrip("\n")


def skill_triggers_from_meta(meta: dict) -> list[str]:
    """frontmatter → 触发词列表 (triggers 优先, 兼容 keywords), 清洗去重限量。"""
    raw = list(meta.get("triggers") or []) + list(meta.get("keywords") or [])
    seen, out = set(), []
    for term in raw:
        term = str(term).strip()[:40]
        low = term.casefold()
        if len(term) >= 2 and low not in seen:
            seen.add(low)
            out.append(term)
    return out[:20]


_ASCII_TERM = re.compile(r"\A[\x20-\x7e]+\Z")


def term_hits(term: str, goal_low: str) -> bool:
    """触发词是否命中目标。

    纯 ASCII 词按**词边界**匹配, 中文按子串匹配 —— 中文没有词边界, 子串是唯一
    可行的判法; 但拉丁字母直接子串会命中单词内部, 实测踩过两次:
    「VI」命中 re-VI-ew、「CRO」命中 s-CRO-llTrigger, 两次都把别的技能的正例抢走。
    """
    term_low = str(term).strip().casefold()
    if len(term_low) < 2:
        return False
    if _ASCII_TERM.match(term_low):
        return re.search(r"(?<![0-9a-z])" + re.escape(term_low) + r"(?![0-9a-z])",
                         goal_low) is not None
    return term_low in goal_low
