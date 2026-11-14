"""Coordinate conversions. Internal points are (x, y) with x=column from left, y=row from top; None means pass."""
from __future__ import annotations

from typing import Optional, Tuple

from ..i18n import tr

Point = Tuple[int, int]
Move = Optional[Point]

GTP_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
SGF_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def other(color: str) -> str:
    return "W" if color == "B" else "B"


def to_gtp(move: Move, size: int) -> str:
    if move is None:
        return "pass"
    x, y = move
    return f"{GTP_COLUMNS[x]}{size - y}"


def from_gtp(text: str, size: int) -> Move:
    t = text.strip().upper()
    if t == "PASS":
        return None
    if len(t) < 2 or t[0] not in GTP_COLUMNS[:size]:
        raise ValueError(tr("无效的 GTP 坐标：{0!r}", text))
    try:
        row = int(t[1:])
    except ValueError:
        raise ValueError(tr("无效的 GTP 坐标：{0!r}", text)) from None
    if not 1 <= row <= size:
        raise ValueError(tr("GTP 坐标越界：{0!r}", text))
    return GTP_COLUMNS.index(t[0]), size - row


def to_sgf(move: Move, size: int) -> str:
    if move is None:
        return ""
    x, y = move
    return SGF_LETTERS[x] + SGF_LETTERS[y]


def from_sgf(text: str, size: int) -> Move:
    if text == "" or (text == "tt" and size <= 19):
        return None
    if len(text) != 2 or text[0] not in SGF_LETTERS or text[1] not in SGF_LETTERS:
        raise ValueError(tr("无效的 SGF 坐标：{0!r}", text))
    x, y = SGF_LETTERS.index(text[0]), SGF_LETTERS.index(text[1])
    if x >= size or y >= size:
        raise ValueError(tr("SGF 坐标越界：{0!r}", text))
    return x, y
