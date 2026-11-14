from __future__ import annotations

from ..i18n import tr

from typing import Optional

from PySide6.QtWidgets import QListWidget, QWidget

from ..go.coords import to_gtp
from ..go.game import GameRecord


class MoveList(QListWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)

    def set_game(self, game: GameRecord) -> None:
        self.clear()
        for i, m in enumerate(game.moves, 1):
            who = tr('黑') if m.color == "B" else tr('白')
            role = "（AI）" if m.color == game.ai_color else ""
            where = tr('停一手') if m.move is None else to_gtp(m.move, game.size)
            self.addItem(f"{i:>3}. {who}{role} {where}")
        if self.count():
            self.scrollToBottom()
            self.setCurrentRow(self.count() - 1)
