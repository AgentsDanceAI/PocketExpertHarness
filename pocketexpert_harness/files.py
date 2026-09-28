# SPDX-License-Identifier: Apache-2.0
"""工作区文件: 上传落盘、按扩展名分类、列目录。上传的东西统一放 uploads/, 模型用工作区工具就能读到。"""
from __future__ import annotations

import re
import time
from pathlib import Path

from pocketexpert_harness.tools.local import resolve_in

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = "uploads"

KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"),
    "video": (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"),
    "audio": (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"),
    "table": (".csv", ".tsv", ".xlsx", ".xls"),
    "doc": (".pdf", ".docx", ".doc", ".pptx", ".txt", ".md", ".json", ".html"),
}
KIND_LABEL = {"image": "图片", "video": "视频", "audio": "音频", "table": "表格", "doc": "文档", "file": "文件"}


def kind_of(name: str) -> str:
    low = name.lower()
    for kind, exts in KINDS.items():
        if low.endswith(exts):
            return kind
    return "file"


def safe_name(name: str) -> str:
    """只留文件名本身, 去掉路径与控制字符; 空了就给个默认名。中文照留。"""
    base = Path(str(name or "")).name.strip()
    base = re.sub(r"[\x00-\x1f\\/:*?\"<>|]+", "_", base)
    base = base.lstrip(".") or "upload"
    return base[:120]


def save_upload(workspace: Path, name: str, data: bytes) -> dict:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    fname = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_name(name)}"
    rel = f"{UPLOAD_DIR}/{fname}"
    path = resolve_in(workspace, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": rel, "name": safe_name(name), "kind": kind_of(fname), "size": len(data)}


def list_files(workspace: Path, limit: int = 500) -> list[dict]:
    root = workspace.resolve()
    if not root.is_dir():
        return []
    rows = []
    for p in sorted(root.rglob("*"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        if not p.is_file() or p.name.startswith(".peh_") or any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        st = p.stat()
        rel = str(p.relative_to(root))
        rows.append({"path": rel, "name": p.name, "kind": kind_of(p.name), "size": st.st_size, "mtime": st.st_mtime})
        if len(rows) >= limit:
            break
    return rows


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}B"
