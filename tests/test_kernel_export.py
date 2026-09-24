# SPDX-License-Identifier: Apache-2.0
"""kernel/ 由上游原样导出: 这里只核对它没被就地改过, 以及它只依赖标准库。"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

KERNEL = Path(__file__).resolve().parent.parent / "pocketexpert_harness" / "kernel"
ROOT = KERNEL.parent.parent


def test_kernel_files_match_export_manifest():
    manifest = json.loads((KERNEL / "EXPORT.json").read_text(encoding="utf-8"))
    assert manifest["files"], "EXPORT.json 为空"
    for rel, meta in manifest["files"].items():
        data = (ROOT / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], (
            f"{rel} 与导出清单不一致: kernel/ 只能由上游导出脚本改写, 请提 issue 而不是在这里改")


def test_kernel_depends_on_stdlib_only():
    for py in KERNEL.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for n in names:
                root = n.split(".")[0]
                assert n == "__future__" or root in sys.stdlib_module_names or n.startswith("pocketexpert_harness.kernel"), \
                    f"{py.name} import 了 {n}"
