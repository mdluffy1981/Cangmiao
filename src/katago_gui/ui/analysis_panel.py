from __future__ import annotations

from ..i18n import tr

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..controller import (ANALYSIS_MAX_MOVES, DISPLAY_CANDIDATES, HONTE_MAX_SCORE_LOSS, HONTE_MAX_WINRATE_LOSS,
                          AnalysisResult, CandidateTier)
from .theme import CANDIDATE_COLORS, CANDIDATE_TEXT_COLORS

ROW_HEIGHT = 22
HINT = "胜率/目差均以当前行棋方视角显示；选中一行可在棋盘上预览变化（不改变棋局）。"
# These are warning thresholds, not statistical confidence guarantees.
LOW_ROOT_VISITS = 64
LOW_CANDIDATE_VISITS = 16
LOW_SAMPLE_HINT = (
    "* 低样本：局面访问数不足 {0} 或候选访问数不足 {1}。\n"
    "胜率为实时评估，开局或刚落子时可能明显波动；更多搜索也不保证数值不再变化。"
)


class AnalysisPanel(QWidget):
    toggle_requested = Signal()
    preview_changed = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.result: Optional[AnalysisResult] = None
        self.button = QPushButton(tr('开始分析'))
        self.button.clicked.connect(self.toggle_requested)
        self.info = QLabel(tr('尚无分析结果'))
        self.info.setObjectName("mutedText")
        self.info.setWordWrap(True)
        self.winrates = QLabel(tr('黑方 —    白方 —'))
        self.winrates.setObjectName("sectionTitle")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat(tr('黑胜率 —'))
        self.visits_value = QLabel("—")
        self.elapsed_value = QLabel("—")
        self.nps_value = QLabel("—")
        metrics = QGridLayout()
        self.metric_labels: list[QLabel] = []
        metrics.setHorizontalSpacing(6)
        for col, (title, value) in enumerate((
            (tr('访问数'), self.visits_value), (tr('用时'), self.elapsed_value), ("NPS", self.nps_value)
        )):
            title_label = QLabel(title)
            self.metric_labels.append(title_label)
            title_label.setObjectName("mutedText")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setObjectName("metricValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            metrics.addWidget(title_label, 0, 2 * col)
            metrics.addWidget(value, 0, 2 * col + 1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr('着法'), tr('排名'), tr('胜率'), tr('目差'), tr('访问数'), tr('主变化')])
        hh = self.table.horizontalHeader()
        for col in range(5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        vh = self.table.verticalHeader()
        vh.setVisible(False)
        vh.setMinimumSectionSize(ROW_HEIGHT - 4)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(ROW_HEIGHT)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setToolTip(tr(HINT))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.addWidget(self.button)
        top.addStretch(1)
        top.addWidget(self.winrates)
        lay.addLayout(top)
        lay.addWidget(self.bar)
        lay.addLayout(metrics)
        lay.addWidget(self.info)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.legend)
        self.retranslate_ui()

    @staticmethod
    def low_sample_hint() -> str:
        return tr(LOW_SAMPLE_HINT, LOW_ROOT_VISITS, LOW_CANDIDATE_VISITS)

    def retranslate_ui(self) -> None:
        for label, source in zip(self.metric_labels, ("访问数", "用时", "NPS")):
            label.setText(tr(source))
        self.table.setHorizontalHeaderLabels([tr(source) for source in
                                              ("着法", "排名", "胜率", "目差", "访问数", "主变化")])
        self.table.setToolTip(tr(HINT))
        self.legend.setText(
            "&nbsp;&nbsp;".join(
                f"<span style='color:{CANDIDATE_COLORS[t.name]}'>●</span> {tr(t.value)}" for t in CandidateTier
            ) + tr("&nbsp;&nbsp;<span style='color:#B8B8D0'>（胜率前 {0} / 最多 {1} 候选）</span>",
                   DISPLAY_CANDIDATES, ANALYSIS_MAX_MOVES)
        )
        self.legend.setToolTip(
            tr("最优解：胜率最高的候选。\n本手：与最优解胜率差 ≤ {0:g}% 且目差差距 ≤ {1:g} 目。\n普通：其余候选。\n{2}\n{3}",
               HONTE_MAX_WINRATE_LOSS * 100, HONTE_MAX_SCORE_LOSS, tr(HINT), self.low_sample_hint())
        )
        self._fit_table()

    def showEvent(self, e: QShowEvent) -> None:
        self._fit_table()
        super().showEvent(e)

    def _fit_table(self) -> None:
        """Reserve room for every displayed candidate so the table never needs its own scrollbar."""
        header = self.table.horizontalHeader().sizeHint().height()
        rows = self.table.verticalHeader().defaultSectionSize() * DISPLAY_CANDIDATES
        self.table.setMinimumHeight(header + rows + 2 * self.table.frameWidth() + 2)

    def set_running(self, running: bool, enabled: bool) -> None:
        self.button.setText(tr('停止分析') if running else tr('开始分析'))
        self.button.setEnabled(enabled)

    def set_unsupported(self, text: str) -> None:
        self.info.setText(text)

    def set_result(self, r: Optional[AnalysisResult], current_move_number: int) -> None:
        prev = self._selected_move() if self.result and r and self.result.move_number == r.move_number else None
        self.result = r
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        if r is None:
            self.bar.setValue(0)
            self.bar.setFormat(tr('黑胜率 —'))
            self.winrates.setText(tr('黑方 —    白方 —'))
            self.winrates.setToolTip("")
            self.bar.setToolTip("")
            self.info.setToolTip("")
            self.visits_value.setText("—")
            self.elapsed_value.setText("—")
            self.nps_value.setText("—")
            self.info.setText(tr('尚无分析结果'))
            self.preview_changed.emit([])
            return
        low_root = r.snapshot.root_visits < LOW_ROOT_VISITS
        marker = "*" if low_root else ""
        root_hint = self.low_sample_hint() if low_root else tr('实时搜索评估；胜率会随搜索继续变化。')
        self.winrates.setToolTip(root_hint)
        self.bar.setToolTip(root_hint)
        bw = r.black_winrate()
        if bw is not None:
            self.bar.setValue(int(bw * 1000))
            lead = r.black_score_lead()
            self.bar.setFormat(tr('黑胜率 {0:.1f}%{1}  白 {2:.1f}%{3}', bw * 100, marker, 100 - bw * 100, marker) +
                               (tr('  黑目差 {0:+.1f}', lead) if lead is not None else ""))
            self.winrates.setText(tr('黑方 {0:.1f}%{1}    白方 {2:.1f}%{3}', bw * 100, marker, (1 - bw) * 100, marker))
        else:
            self.bar.setValue(0)
            self.bar.setFormat(tr('黑胜率 —'))
            self.winrates.setText(tr('黑方 —    白方 —'))
        self.visits_value.setText(str(r.snapshot.root_visits))
        self.elapsed_value.setText(f"{r.elapsed:.1f}s")
        self.nps_value.setText(
            f"{r.snapshot.root_visits / r.elapsed:.0f}" if r.elapsed > 0 else "—"
        )
        stale = tr('（已过期）') if r.move_number != current_move_number else ""
        side = tr('黑') if r.to_move == "B" else tr('白')
        ranked = r.ranked_candidates()
        low_candidates = sum(rc.move.visits < LOW_CANDIDATE_VISITS for rc in ranked)
        warning = tr(' · *低样本，胜率易波动') if low_root or low_candidates else ""
        self.info.setText(tr('第 {0} 手后局面 · {1}方行棋{2} · 返回 {3} 个候选{4}', r.move_number, side, stale, len(r.snapshot.candidates), warning))
        self.info.setToolTip(self.low_sample_hint() if warning else "")
        total = r.snapshot.root_visits
        for rc in ranked:
            c = rc.move
            row = self.table.rowCount()
            self.table.insertRow(row)
            share = f"{c.visits / total * 100:.1f}%" if total > 0 else "—"
            marker = "*" if c.visits < LOW_CANDIDATE_VISITS else ""
            vals = [c.move, str(rc.rank), f"{c.winrate * 100:.1f}%{marker}", f"{c.score_lead:+.1f}", str(c.visits),
                    " ".join(c.pv[:10])]
            tip = (tr('{0} · {1}：胜率 {2:.1f}%，目差 {3:+.1f}，访问 {4}（占 {5}）\n主变化：{6}', c.move, tr(rc.tier.value), c.winrate * 100, c.score_lead, c.visits, share, ' '.join(c.pv[:20])))
            if c.visits == 0:
                tip += tr('\n尚未搜索，当前为模型初始评估。')
            if marker:
                tip += tr('\n低样本：该候选访问数不足 {0}，胜率与排名可能明显波动。', LOW_CANDIDATE_VISITS)
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col in (1, 2, 3, 4):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 0:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    it.setBackground(QBrush(QColor(CANDIDATE_COLORS[rc.tier.name])))
                    it.setForeground(QBrush(QColor(CANDIDATE_TEXT_COLORS[rc.tier.name])))
                it.setToolTip(tip)
                it.setData(Qt.ItemDataRole.UserRole, c.pv)
                self.table.setItem(row, col, it)
            if c.move == prev:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
        self._on_select()

    def _selected_move(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.table.item(rows[0].row(), 0)
        return it.text() if it else None

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.preview_changed.emit([])
            return
        it = self.table.item(rows[0].row(), 0)
        self.preview_changed.emit(list(it.data(Qt.ItemDataRole.UserRole) or []))
