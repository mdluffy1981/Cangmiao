from __future__ import annotations

from typing import Iterable, Optional

from .coords import Move, Point, other
from .rules import RuleSet
from ..i18n import tr


class IllegalMove(Exception):
    pass


class Board:
    """Immutable board position. grid[y][x] holds '', 'B' or 'W'."""

    __slots__ = ("size", "grid", "captures")

    def __init__(self, size: int, grid: Optional[tuple] = None, captures: Optional[dict] = None):
        self.size = size
        self.grid: tuple = grid if grid is not None else tuple(tuple("" for _ in range(size)) for _ in range(size))
        self.captures = dict(captures) if captures else {"B": 0, "W": 0}

    def __eq__(self, other_: object) -> bool:
        return isinstance(other_, Board) and self.grid == other_.grid

    def __hash__(self) -> int:
        return hash(self.grid)

    def get(self, p: Point) -> str:
        return self.grid[p[1]][p[0]]

    def neighbors(self, p: Point) -> Iterable[Point]:
        x, y = p
        if x > 0:
            yield x - 1, y
        if x < self.size - 1:
            yield x + 1, y
        if y > 0:
            yield x, y - 1
        if y < self.size - 1:
            yield x, y + 1

    def group(self, grid: list, p: Point) -> tuple[set, set]:
        color = grid[p[1]][p[0]]
        stones, libs, stack = {p}, set(), [p]
        while stack:
            q = stack.pop()
            for n in self.neighbors(q):
                c = grid[n[1]][n[0]]
                if c == "":
                    libs.add(n)
                elif c == color and n not in stones:
                    stones.add(n)
                    stack.append(n)
        return stones, libs

    def play(self, color: str, move: Move, rules: RuleSet) -> "Board":
        """Return the position after the move (ko/superko are checked by Game)."""
        if move is None:
            return self
        x, y = move
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise IllegalMove(tr("落子位置超出棋盘"))
        if self.grid[y][x]:
            raise IllegalMove(tr("该位置已有棋子"))
        grid = [list(r) for r in self.grid]
        grid[y][x] = color
        opp = other(color)
        captured = 0
        for n in self.neighbors(move):
            if grid[n[1]][n[0]] == opp:
                stones, libs = self.group(grid, n)
                if not libs:
                    for sx, sy in stones:
                        grid[sy][sx] = ""
                    captured += len(stones)
        stones, libs = self.group(grid, move)
        caps = dict(self.captures)
        if not libs:
            if len(stones) == 1 or not rules.multi_stone_suicide:
                raise IllegalMove(tr("禁止自杀着法"))
            for sx, sy in stones:
                grid[sy][sx] = ""
            caps[opp] += len(stones)
        caps[color] += captured
        return Board(self.size, tuple(tuple(r) for r in grid), caps)
