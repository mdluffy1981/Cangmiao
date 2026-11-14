from __future__ import annotations

from typing import Optional, Protocol

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..controller import AnalysisResult
from ..go.coords import GTP_COLUMNS, Point, from_gtp
from ..go.game import MoveRecord
from ..go.board import Board
from .theme import CANDIDATE_COLORS, CANDIDATE_TEXT_COLORS

STAR_POINTS = {
    9: [(2, 2), (6, 2), (4, 4), (2, 6), (6, 6)],
    13: [(3, 3), (9, 3), (6, 6), (3, 9), (9, 9)],
    19: [(x, y) for x in (3, 9, 15) for y in (3, 9, 15)],
}


class BoardPosition(Protocol):
    size: int
    board: Board
    to_move: str
    moves: list[MoveRecord]
    last_move: Optional[MoveRecord]


def compact_count(n: int) -> str:
    """Short visit count for a board mark, e.g. 950, 1.2k, 35k, 1.4M."""
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1_000_000:.1f}M"


class BoardWidget(QWidget):
    point_clicked = Signal(int, int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.game: Optional[BoardPosition] = None
        self.analysis: Optional[AnalysisResult] = None
        self.preview: list[str] = []  # GTP moves of a previewed variation
        self.show_candidates = True
        self.interactive = False
        self._hover: Optional[Point] = None
        self.setMouseTracking(True)
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ------------------------------------------------------------ API
    def set_game(self, game: BoardPosition) -> None:
        self.game = game
        self.update()

    def set_analysis(self, a: Optional[AnalysisResult]) -> None:
        self.analysis = a
        if a is None:
            self.preview = []
        self.update()

    def set_preview(self, pv: list[str]) -> None:
        self.preview = list(pv)
        self.update()

    def set_interactive(self, on: bool) -> None:
        self.interactive = on
        if not on:
            self._hover = None
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)
        self.update()

    # -------------------------------------------------------- geometry
    def _geom(self) -> tuple[float, float, float]:
        n = self.game.size if self.game else 19
        side = min(self.width(), self.height())
        cell = side / (n + 1)
        ox = (self.width() - side) / 2 + cell
        oy = (self.height() - side) / 2 + cell
        return cell, ox, oy

    def point_at(self, px: float, py: float) -> Optional[Point]:
        if not self.game:
            return None
        cell, ox, oy = self._geom()
        fx, fy = (px - ox) / cell, (py - oy) / cell
        x, y = round(fx), round(fy)
        if not (0 <= x < self.game.size and 0 <= y < self.game.size):
            return None
        if (fx - x) ** 2 + (fy - y) ** 2 > 0.45 ** 2:
            return None
        return x, y

    def center_of(self, p: Point) -> QPointF:
        cell, ox, oy = self._geom()
        return QPointF(ox + p[0] * cell, oy + p[1] * cell)

    # ----------------------------------------------------------- events
    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        p = self.point_at(e.position().x(), e.position().y()) if self.interactive else None
        if p != self._hover:
            self._hover = p
            self.update()

    def leaveEvent(self, _e) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.interactive or not self.game:
            return
        p = self.point_at(e.position().x(), e.position().y())
        if p is None or self.game.board.get(p):
            return
        self.point_clicked.emit(p[0], p[1])

    # ------------------------------------------------------------ paint
    def paintEvent(self, _e) -> None:
        if not self.game:
            return
        g = self.game
        n = g.size
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell, ox, oy = self._geom()
        side = cell * (n + 1)
        bx, by = ox - cell, oy - cell
        qp.fillRect(QRectF(bx, by, side, side), QColor("#DCB35C"))

        qp.setPen(QPen(QColor("#3a2a10"), max(1.0, cell / 30)))
        for i in range(n):
            qp.drawLine(QPointF(ox, oy + i * cell), QPointF(ox + (n - 1) * cell, oy + i * cell))
            qp.drawLine(QPointF(ox + i * cell, oy), QPointF(ox + i * cell, oy + (n - 1) * cell))
        qp.setBrush(QColor("#3a2a10"))
        for p in STAR_POINTS[n]:
            qp.drawEllipse(self.center_of(p), cell * 0.1, cell * 0.1)

        f = QFont(self.font())
        f.setPixelSize(max(8, int(cell * 0.32)))
        qp.setFont(f)
        qp.setPen(QColor("#4a3818"))
        for i in range(n):
            c = self.center_of((i, 0))
            label = GTP_COLUMNS[i]
            qp.drawText(QRectF(c.x() - cell / 2, oy - cell * 0.95, cell, cell * 0.5), Qt.AlignmentFlag.AlignCenter, label)
            qp.drawText(QRectF(c.x() - cell / 2, oy + (n - 1) * cell + cell * 0.45, cell, cell * 0.5),
                        Qt.AlignmentFlag.AlignCenter, label)
            r = self.center_of((0, i))
            num = str(n - i)
            qp.drawText(QRectF(ox - cell * 0.98, r.y() - cell / 2, cell * 0.5, cell), Qt.AlignmentFlag.AlignCenter, num)
            qp.drawText(QRectF(ox + (n - 1) * cell + cell * 0.48, r.y() - cell / 2, cell * 0.5, cell),
                        Qt.AlignmentFlag.AlignCenter, num)

        board = g.board
        for y in range(n):
            for x in range(n):
                c = board.grid[y][x]
                if c:
                    self._stone(qp, (x, y), c, cell)

        last = g.last_move
        if last is not None and last.move is not None and not self.preview:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor("#E74C3C"))
            qp.drawEllipse(self.center_of(last.move), cell * 0.10, cell * 0.10)

        if self.preview:
            self._paint_preview(qp, cell)
        elif self.show_candidates and self.analysis is not None and self.analysis.move_number == len(g.moves):
            self._paint_candidates(qp, cell)

        if self._hover is not None and not board.get(self._hover) and not self.preview:
            col = QColor(0, 0, 0, 90) if g.to_move == "B" else QColor(255, 255, 255, 140)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(col)
            qp.drawEllipse(self.center_of(self._hover), cell * 0.46, cell * 0.46)
        qp.end()

    def _stone(self, qp: QPainter, p: Point, color: str, cell: float, alpha: int = 255) -> None:
        c = self.center_of(p)
        r = cell * 0.47
        grad = QRadialGradient(c.x() - r * 0.35, c.y() - r * 0.35, r * 1.4)
        if color == "B":
            grad.setColorAt(0, QColor(90, 90, 90, alpha))
            grad.setColorAt(1, QColor(10, 10, 10, alpha))
            qp.setPen(QPen(QColor(0, 0, 0, alpha), 1))
        else:
            grad.setColorAt(0, QColor(255, 255, 255, alpha))
            grad.setColorAt(1, QColor(200, 200, 200, alpha))
            qp.setPen(QPen(QColor(90, 90, 90, alpha), 1))
        qp.setBrush(QBrush(grad))
        qp.drawEllipse(c, r, r)

    def _paint_candidates(self, qp: QPainter, cell: float) -> None:
        a = self.analysis
        assert a is not None and self.game is not None
        ranked = [rc for rc in a.ranked_candidates() if rc.move.move.lower() != "pass"]
        if not ranked:
            return
        f = QFont(self.font())
        f.setPixelSize(max(7, int(cell * 0.22)))
        f.setBold(True)
        qp.setFont(f)
        for rc in ranked:
            c = rc.move
            try:
                p = from_gtp(c.move, self.game.size)
            except ValueError:
                continue
            if p is None or self.game.board.get(p):
                continue
            center = self.center_of(p)
            qp.setPen(QPen(QColor(0, 0, 0, 120), 1))
            qp.setBrush(QColor(CANDIDATE_COLORS[rc.tier.name]))
            qp.drawEllipse(center, cell * 0.44, cell * 0.44)
            qp.setPen(QColor(CANDIDATE_TEXT_COLORS[rc.tier.name]))
            qp.drawText(QRectF(center.x() - cell / 2, center.y() - cell / 2, cell, cell),
                        Qt.AlignmentFlag.AlignCenter, f"{c.winrate * 100:.1f}%\n{compact_count(c.visits)}")

    def _paint_preview(self, qp: QPainter, cell: float) -> None:
        assert self.game is not None
        color = self.game.to_move
        f = QFont(self.font())
        f.setPixelSize(max(7, int(cell * 0.38)))
        f.setBold(True)
        qp.setFont(f)
        seen: set = set()
        for i, mv in enumerate(self.preview[:12]):
            try:
                p = from_gtp(mv, self.game.size)
            except ValueError:
                break
            if p is not None and p not in seen and not self.game.board.get(p):
                seen.add(p)
                self._stone(qp, p, color, cell, alpha=170)
                c = self.center_of(p)
                qp.setPen(QColor("white") if color == "B" else QColor("black"))
                qp.drawText(QRectF(c.x() - cell / 2, c.y() - cell / 2, cell, cell), Qt.AlignmentFlag.AlignCenter, str(i + 1))
            color = "W" if color == "B" else "B"
