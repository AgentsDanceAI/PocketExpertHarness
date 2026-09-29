# SPDX-License-Identifier: Apache-2.0
"""发版说明格式 (与口袋专家 AI 的 Release 同一套): 仓库里每一份都要过检查, 坏格式要被拦下。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts" / "release_notes.py")
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

GOOD = """# (2026-09-29) 🎉 v9.9.9 — 亮点一 · 亮点二

## 新增功能
- feat(web): 一件事 (9a2b68a)

## 优化改进
- 无

## Bug 修复
- fix(cli): 另一件事 (#12, abc1234)
"""


@pytest.mark.parametrize("path", sorted((ROOT / ".github" / "release-notes").glob("v*.md")), ids=lambda p: p.stem)
def test_every_release_note_in_repo_passes(path):
    title, body = rn.render(path.stem)
    assert title.startswith("(") and "---\n安装: `uvx pocketexpert-harness serve`" in body


def test_good_note_parses_and_footer_links_previous_tag():
    title, body = rn.parse("v9.9.9", GOOD)
    assert title == "(2026-09-29) 🎉 v9.9.9 — 亮点一 · 亮点二" and body.startswith("## 新增功能")
    assert rn.previous_tag("v0.2.0") == "v0.1.0" and rn.previous_tag("v0.1.0") is None


@pytest.mark.parametrize("bad, why", [
    (GOOD.replace("# (2026-09-29) 🎉 v9.9.9 — ", "# PocketExpertHarness v9.9.9 "), "第一行"),
    (GOOD.replace("v9.9.9 —", "v9.9.8 —"), "不一致"),
    (GOOD.replace("## 优化改进\n- 无\n\n", ""), "三段"),
    (GOOD.replace(" (9a2b68a)", ""), "缺提交号"),
    ("**Full Changelog**: https://github.com/x/y/compare/v0.1.0...v9.9.9", "第一行"),
])
def test_bad_notes_are_rejected(bad, why):
    with pytest.raises(ValueError, match=why):
        rn.parse("v9.9.9", bad)


def test_missing_note_blocks_release():
    with pytest.raises(ValueError, match="缺发版说明"):
        rn.render("v99.0.0")
