from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional

from .board import Board, IllegalMove
from .coords import Move, other
from .rules import RULES, RuleSet, get_rules
from ..i18n import tr

SUPPORTED_SIZES = (9, 13, 19)


@dataclass
class MoveRecord:
    color: str
    move: Move  # None = pass


@dataclass
class GameRecord:
    size: int = 19
    rules_key: str = "chinese"
    komi: float = 7.5
    human_color: str = "B"
    moves: list[MoveRecord] = field(default_factory=list)
    boards: list[Board] = field(default_factory=list)
    result: str = ""  # SGF RE value, e.g. "B+R", "W+3.5", "Void"/"?" style text
    result_note: str = ""
    dirty: bool = False
    black_name: str = ""
    white_name: str = ""
    date: str = ""

    def __post_init__(self) -> None:
        if self.size not in SUPPORTED_SIZES:
            raise ValueError(tr("不支持的棋盘尺寸：{0}", self.size))
        if self.human_color not in ("B", "W"):
            raise ValueError(tr("不支持的执色：{0}", self.human_color))
        if self.rules_key not in RULES:
            raise ValueError(tr("不支持的规则：{0}", self.rules_key))
        if not math.isfinite(self.komi) or abs(self.komi) > 150 or self.komi * 2 % 1:
            raise ValueError(tr("贴目必须在 -150 到 150 之间，且为 0.5 的整数倍"))
        if not self.boards:
            self.boards = [Board(self.size)]

    @property
    def rules(self) -> RuleSet:
        return get_rules(self.rules_key)

    @property
    def ai_color(self) -> str:
        return other(self.human_color)

    @property
    def board(self) -> Board:
        return self.boards[-1]

    @property
    def to_move(self) -> str:
        return "B" if len(self.moves) % 2 == 0 else "W"

    @property
    def last_move(self) -> Optional[MoveRecord]:
        return self.moves[-1] if self.moves else None

    @property
    def finished(self) -> bool:
        return self.result not in ("", "?") or self.ended_by_passes

    @property
    def ended_by_passes(self) -> bool:
        return len(self.moves) >= 2 and self.moves[-1].move is None and self.moves[-2].move is None

    def check(self, color: str, move: Move) -> Board:
        """Validate a move for the side to move; return the resulting board."""
        if color != self.to_move:
            raise IllegalMove(tr("现在不是该方行棋"))
        new = self.board.play(color, move, self.rules)
        if move is None:
            return new
        ko = self.rules.ko
        if ko == "SIMPLE":
            if len(self.boards) >= 2 and new == self.boards[-2]:
                raise IllegalMove(tr("劫：不能立即提回"))
        elif ko == "POSITIONAL":
            if any(new == b for b in self.boards):
                raise IllegalMove(tr("全局同形（超级劫）禁止"))
        elif ko == "SITUATIONAL":
            # A position repeats situationally if the same side would be to move again.
            next_to_move = other(color)
            for i, b in enumerate(self.boards):
                mover = "B" if i % 2 == 0 else "W"
                if mover == next_to_move and new == b:
                    raise IllegalMove(tr("情境同形（超级劫）禁止"))
        return new

    def is_legal(self, color: str, move: Move) -> bool:
        try:
            self.check(color, move)
            return True
        except IllegalMove:
            return False

    def play(self, color: str, move: Move) -> None:
        new = self.check(color, move)
        self.moves.append(MoveRecord(color, move))
        self.boards.append(new)
        if self.result == "?":
            self.result = ""
        self.dirty = True

    def undo(self) -> MoveRecord:
        if not self.moves:
            raise IndexError(tr("没有可撤销的着手"))
        self.boards.pop()
        self.dirty = True
        self.result = ""
        self.result_note = ""
        return self.moves.pop()

    def set_result(self, result: str, note: str = "") -> None:
        self.result = result
        self.result_note = note
        self.dirty = True

    def undo_count_for_human(self) -> int:
        """Moves to retract so the human gets their previous turn back (see plan: undo one full human/AI round)."""
        if not self.moves:
            return 0
        if self.moves[-1].color == self.ai_color:
            return 2 if len(self.moves) >= 2 else 1
        return 1
