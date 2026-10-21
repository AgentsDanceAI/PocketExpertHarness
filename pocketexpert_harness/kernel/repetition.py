# SPDX-License-Identifier: Apache-2.0
# 由口袋专家 AI 私有仓原样导出 (repetition.py), 请勿在此修改 —— 改动请提 issue, 上游改完后重新导出。
"""Bounded, chunk-independent detection of dense natural-language output loops.

This is deliberately conservative: repeated syntax and quoted source material are
not evidence of a generation loop. No answer-length budget is imposed here.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import re


_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_CALL = re.compile(r"[A-Za-z_$][\w.$]*\s*\($")
_QUOTES = {'"': '"', '“': '”', '「': '」', '『': '』', '‘': '’'}
_ENDS = frozenset("。！？.!?\n")


@dataclass(frozen=True)
class _Unit:
    text: str
    start: int
    end: int


class ProseRepetitionGuard:
    """Feed arbitrary deltas; ``cut_at`` is an absolute valid-prefix boundary.

    Keep at most one short sentence and a fixed recent window of prose units.
    Six occurrences alone are insufficient: at least 900 characters must be
    overwhelmingly repeated prose. A recurring sentence in a varied article is
    therefore allowed. Markdown/code/quotation boundaries never count as prose.
    """
    WINDOW_CHARS = 16_384
    UNIT_CHARS = 512
    MAX_UNITS = 128
    MIN_OCCURRENCES = 6
    MIN_SPAN = 900
    DENSITY = 0.82

    def __init__(self):
        self.total_chars = 0
        self.cut_at: int | None = None
        self._units: deque[_Unit] = deque()
        self._sentence = ""
        self._start = 0
        self._overflow = False
        self._line_prefix = ""
        self._line_skip = False
        self._fence = ""
        self._inline = False
        self._quote = ""
        self._braces = 0

    @property
    def buffered_chars(self) -> int:
        return len(self._sentence) + sum(len(unit.text) for unit in self._units)

    def feed(self, piece: str) -> None:
        if self.cut_at is not None:
            return
        for char in piece:
            self.total_chars += 1
            self._char(char)
            if self.cut_at is not None:
                break

    def _barrier(self) -> None:
        self._units.clear()
        self._sentence = ""
        self._overflow = False
        self._start = self.total_chars

    def _char(self, char: str) -> None:
        # Inspect only the short line prefix; never accumulate an unbounded line.
        if len(self._line_prefix) < 96:
            self._line_prefix += char
        prefix = self._line_prefix.lstrip(" \t")
        if char != "\n" and not self._line_skip:
            if prefix in ("```", "~~~"):
                self._fence = "" if self._fence == prefix else (self._fence or prefix)
                self._inline = False
                self._line_skip = True
                self._barrier()
            elif (prefix[:1] in ("|", ">", "#") or self._line_prefix.startswith(("    ", "\t"))
                  or char in "=<>" or (char == "(" and _CALL.fullmatch(prefix))):
                self._line_skip = True
                self._barrier()
        if char == "\n":
            if not (self._line_skip or self._fence or self._quote or self._inline or self._braces):
                self._complete()
            self._line_prefix = ""
            self._line_skip = False
            self._start = self.total_chars
            return
        if self._line_skip or self._fence:
            return
        if self._quote:
            if char == self._quote:
                self._quote = ""
            return
        if char in _QUOTES:
            self._quote = _QUOTES[char]
            return
        if char == "`":
            self._inline = not self._inline
            return
        if self._inline:
            return
        if char == "{":
            self._braces += 1
            self._barrier()
        elif char == "}" and self._braces:
            self._braces -= 1
            self._barrier()
        if self._braces or char == "}":
            return
        if not self._sentence:
            self._start = self.total_chars - 1
        if not self._overflow:
            self._sentence += char
            if len(self._sentence) > self.UNIT_CHARS:
                self._sentence = ""
                self._overflow = True
        if char in _ENDS:
            self._complete()

    def _complete(self) -> None:
        text = " ".join(self._sentence.split()).casefold()
        start = self._start
        self._sentence = ""
        overflow, self._overflow = self._overflow, False
        self._start = self.total_chars
        cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
        if overflow or len(text) < 10 or (cjk < 8 and len(_WORDS.findall(text)) < 5):
            return
        self._units.append(_Unit(text, start, self.total_chars))
        while self._units and (len(self._units) > self.MAX_UNITS
                               or self.total_chars - self._units[0].start > self.WINDOW_CHARS):
            self._units.popleft()
        units = list(self._units)
        hits = [i for i, unit in enumerate(units) if unit.text == text]
        if len(hits) < self.MIN_OCCURRENCES:
            return
        first, second = hits[0], hits[1]
        span = self.total_chars - units[first].start
        if span < self.MIN_SPAN:
            return
        counts = Counter(unit.text for unit in units[first:])
        repeated = sum(len(unit.text) for unit in units[first:] if counts[unit.text] >= 3)
        if repeated / span < self.DENSITY:
            return
        # Extend a sentence match back to the start of its repeated multi-sentence
        # block, keeping the entire first copy rather than cutting into a sentence.
        left, right = first, second
        while left > 0 and right > first and units[left - 1].text == units[right - 1].text:
            left -= 1
            right -= 1
        self.cut_at = units[right].start


def repetition_cut(text: str, **_legacy_options) -> str | None:
    """Nonstreaming callers use exactly the same detector as streaming callers."""
    guard = ProseRepetitionGuard()
    guard.feed(text)
    return text[:guard.cut_at].rstrip() if guard.cut_at is not None else None
