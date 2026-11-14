from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ..go.board import Board, IllegalMove
from ..go.coords import Move, other, to_gtp
from ..go.game import MoveRecord
from ..go.rules import get_rules
from ..i18n import tr
from ..paths import app_home, atomic_write_text
from ..sgf import SgfError
from ..tsumego import TsumegoNode, TsumegoProblem, load_tsumego
from .board_widget import BoardWidget


@dataclass
class PuzzlePosition:
    size: int
    board: Board
    to_move: str
    moves: list[MoveRecord] = field(default_factory=list)
    last_move: Optional[MoveRecord] = None


class TsumegoPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.problems: list[TsumegoProblem] = []
        self.source_path: Optional[Path] = None
        self.problem_index = 0
        self.cursor: Optional[TsumegoNode] = None
        self.position = PuzzlePosition(19, Board(19), "B")
        self.progress: dict[str, str] = {}
        self.progress_path = app_home() / "tsumego_progress.json"
        self._progress_error = ""
        self._load_progress()

        self.board = BoardWidget()
        self.board.point_clicked.connect(self._play_point)
        self.title_label = QLabel()
        self.instructions = QLabel(
            tr("导入包含题目答案分支的 SGF 集合开始做题。棋谱不会自动上传或复制到题库。")
        )
        self.instructions.setWordWrap(True)
        self.source_label = QLabel(tr("尚未导入题集"))
        self.problem_label = QLabel(tr("请导入 SGF 题集"))
        self.problem_list = QListWidget()
        self.problem_list.currentRowChanged.connect(self._select_problem)
        self.status_label = QLabel(self._progress_error)
        self.status_label.setWordWrap(True)

        self.import_button = QPushButton(tr("导入 SGF 题集…"))
        self.import_button.clicked.connect(self._open_file)
        self.previous_button = QPushButton(tr("上一题"))
        self.previous_button.clicked.connect(lambda: self._step_problem(-1))
        self.next_button = QPushButton(tr("下一题"))
        self.next_button.clicked.connect(lambda: self._step_problem(1))
        self.random_button = QPushButton(tr("随机一题"))
        self.random_button.clicked.connect(self._random_problem)
        self.reset_button = QPushButton(tr("重做"))
        self.reset_button.clicked.connect(self._reset)
        self.hint_button = QPushButton(tr("提示"))
        self.hint_button.clicked.connect(self._hint)
        self.answer_button = QPushButton(tr("显示答案"))
        self.answer_button.clicked.connect(self._show_answer)

        side = QWidget()
        side.setMinimumWidth(280)
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(self.title_label)
        side_layout.addWidget(self.instructions)
        side_layout.addWidget(self.import_button)
        side_layout.addWidget(self.source_label)
        side_layout.addWidget(self.problem_list, 1)
        side_layout.addWidget(self.problem_label)
        for button in (self.previous_button, self.next_button, self.random_button,
                       self.reset_button, self.hint_button, self.answer_button):
            side_layout.addWidget(button)
        side_layout.addWidget(self.status_label)
        side_layout.addStretch(1)

        split = QSplitter()
        split.addWidget(self.board)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self.retranslate_ui()
        self._render()

    def _load_progress(self) -> None:
        try:
            data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self._progress_error = tr("无法读取做题进度：{0}", e)
            return
        if not isinstance(data, dict) or any(
            not isinstance(key, str) or value not in ("correct", "wrong")
            for key, value in data.items()
        ):
            self._progress_error = tr("做题进度文件格式无效，将在本次运行中重新记录")
            return
        self.progress = data

    def _save_progress(self) -> None:
        try:
            atomic_write_text(self.progress_path, json.dumps(self.progress, ensure_ascii=False, indent=2))
        except OSError as e:
            self.status_label.setText(tr("保存做题进度失败：{0}", e))

    def load_problems(self, path: str | Path) -> None:
        source = Path(path)
        problems = load_tsumego(source)
        if not problems:
            raise ValueError(tr("题集为空"))
        self.source_path = source.resolve()
        self.problems = problems
        self.problem_index = 0
        self.problem_list.blockSignals(True)
        self.problem_list.clear()
        self.problem_list.addItems([problem.title for problem in problems])
        self.problem_list.blockSignals(False)
        self.source_label.setText(tr("题集：{0} · {1} 道", source.name, len(problems)))
        self.problem_list.setCurrentRow(0)
        self._load_problem()

    def _open_file(self) -> None:
        start = str(self.source_path.parent if self.source_path else Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("导入 SGF 题集"), start, tr("SGF 棋谱 (*.sgf);;所有文件 (*)")
        )
        if not path:
            return
        try:
            self.load_problems(path)
        except (OSError, ValueError, SgfError) as e:
            self.status_label.setText(tr("无法导入题集：{0}", e))

    def _select_problem(self, row: int) -> None:
        if 0 <= row < len(self.problems) and row != self.problem_index:
            self.problem_index = row
            self._load_problem()

    def _problem_key(self) -> str:
        return f"{self.source_path}#{self.problem_index}" if self.source_path else ""

    def _load_problem(self) -> None:
        problem = self.problems[self.problem_index]
        self.cursor = problem.root
        self.position = PuzzlePosition(problem.size, problem.board, problem.to_move)
        self.board.set_preview([])
        self.problem_label.setText(tr("{0} · {1} 先行", problem.title, tr("黑" if problem.to_move == "B" else "白")))
        status = self.progress.get(self._problem_key())
        self.status_label.setText(tr("上次结果：{0}", tr("正解" if status == "correct" else "未解出"))
                                  if status else tr("轮到{0}方行棋", tr("黑" if problem.to_move == "B" else "白")))
        self._render()

    def _render(self) -> None:
        self.board.set_game(self.position)
        self.board.set_analysis(None)
        self.board.set_interactive(bool(self.problems))
        self.problem_list.setCurrentRow(self.problem_index if self.problems else -1)
        self.previous_button.setEnabled(bool(self.problems))
        self.next_button.setEnabled(bool(self.problems))
        self.random_button.setEnabled(bool(self.problems))
        self.reset_button.setEnabled(bool(self.problems))
        self.hint_button.setEnabled(bool(self.problems))
        self.answer_button.setEnabled(bool(self.problems))

    def _play_step(self, step: TsumegoNode) -> None:
        color = self.position.to_move
        self.position.board = self.position.board.play(color, step.move, get_rules("chinese"))
        record = MoveRecord(color, step.move)
        self.position.moves.append(record)
        self.position.last_move = record
        self.position.to_move = other(color)
        self.cursor = step

    def _play_point(self, x: int, y: int) -> None:
        if self.cursor is None:
            return
        move: Move = (x, y)
        matching = [step for step in self.cursor.children
                    if step.color == self.position.to_move and step.move == move]
        accepted = next((step for step in matching if step.accepted), None)
        if accepted is None:
            self.board.set_preview([])
            self.progress[self._problem_key()] = "wrong"
            self._save_progress()
            self.status_label.setText(tr("不正确，试试其他着法"))
            return
        try:
            self._play_step(accepted)
            reply = next((step for step in self.cursor.children
                          if step.color == self.position.to_move and step.accepted), None)
            if reply is not None:
                self._play_step(reply)
                self.status_label.setText(tr("正解！对方应于 {0}", to_gtp(reply.move, self.position.size)))
            elif any(step.color == self.position.to_move for step in self.cursor.children):
                self.status_label.setText(tr("正解！"))
            else:
                self.progress[self._problem_key()] = "correct"
                self._save_progress()
                self.status_label.setText(tr("正解，题目完成"))
        except IllegalMove as e:
            self.status_label.setText(tr("答案棋谱包含非法着法：{0}", e))
            return
        self.board.set_preview([])
        self._render()

    def _step_problem(self, offset: int) -> None:
        if not self.problems:
            return
        self.problem_index = (self.problem_index + offset) % len(self.problems)
        self.problem_list.setCurrentRow(self.problem_index)
        self._load_problem()

    def _random_problem(self) -> None:
        if self.problems:
            self.problem_index = random.randrange(len(self.problems))
            self.problem_list.setCurrentRow(self.problem_index)
            self._load_problem()

    def _reset(self) -> None:
        if self.problems:
            self._load_problem()

    def _hint(self) -> None:
        if self.cursor is None:
            return
        step = next((item for item in self.cursor.children
                     if item.color == self.position.to_move and item.accepted), None)
        if step is None:
            self.status_label.setText(tr("当前没有可用提示"))
            return
        self.board.set_preview([to_gtp(step.move, self.position.size)])
        self.status_label.setText(tr("提示：{0}", to_gtp(step.move, self.position.size)))

    def _show_answer(self) -> None:
        if self.cursor is None:
            return
        moves: list[str] = []
        node = self.cursor
        to_move = self.position.to_move
        while True:
            step = next((item for item in node.children
                         if item.color == to_move and item.accepted), None)
            if step is None:
                break
            moves.append(to_gtp(step.move, self.position.size))
            color = other(to_move)
            reply = next((item for item in step.children
                          if item.color == color and item.accepted), None)
            to_move = color
            node = step
            if reply is not None:
                moves.append(to_gtp(reply.move, self.position.size))
                to_move = other(color)
                node = reply
            else:
                break
        self.board.set_preview(moves)
        self.status_label.setText(tr("显示答案预览"))

    def retranslate_ui(self) -> None:
        self.title_label.setText(tr("死活题"))
        self.instructions.setText(
            tr("导入包含题目答案分支的 SGF 集合开始做题。棋谱不会自动上传或复制到题库。")
        )
        self.import_button.setText(tr("导入 SGF 题集…"))
        self.previous_button.setText(tr("上一题"))
        self.next_button.setText(tr("下一题"))
        self.random_button.setText(tr("随机一题"))
        self.reset_button.setText(tr("重做"))
        self.hint_button.setText(tr("提示"))
        self.answer_button.setText(tr("显示答案"))
        if not self.problems:
            self.source_label.setText(tr("尚未导入题集"))
            self.problem_label.setText(tr("请导入 SGF 题集"))
        if self._progress_error:
            self.status_label.setText(self._progress_error)
