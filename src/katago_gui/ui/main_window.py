from __future__ import annotations

from ..i18n import set_language, tr

import logging
from html import escape
import time
from collections import deque
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QButtonGroup, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..controller import GameController, InteractionMode, State, color_name, format_result
from ..go.coords import to_gtp
from ..settings import Settings
from ..sgf import SgfError, load_sgf, save_sgf
from ..strength import PRESETS, get_preset
from .analysis_panel import AnalysisPanel
from .board_widget import BoardWidget
from .dialogs import EngineSettingsDialog, LogDialog, NewGameDialog
from .move_list import MoveList
from .theme import APP_STYLESHEET
from .tsumego_page import TsumegoPage

log = logging.getLogger("katago_gui.engine")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, controller: Optional[GameController] = None, ask: bool = True):
        super().__init__()
        self.settings = settings
        set_language(settings.language)
        self.ctl = controller or GameController(settings, parent=self)
        self.ask = ask  # tests disable modal prompts
        self.current_path: Optional[Path] = None
        self.log_lines: deque[str] = deque(maxlen=3000)
        self._think_started: Optional[float] = None
        self.resize(1280, 860)
        self.setStyleSheet(APP_STYLESHEET)

        self.board = BoardWidget()
        self.board.point_clicked.connect(self._on_point)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_btn_settings = QPushButton(tr('引擎设置…'))
        self.banner_btn_settings.clicked.connect(self.open_engine_settings)
        self.banner_btn_restart = QPushButton(tr('重启引擎'))
        self.banner_btn_restart.clicked.connect(self.ctl.restart_engine)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.banner_btn_restart)
        bl.addWidget(self.banner_btn_settings)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.banner)
        ll.addWidget(self.board, 1)

        # Controls
        self.btn_new = QPushButton(tr('新建棋局'))
        self.btn_play = QPushButton(tr('人机对战'))
        self.btn_analysis = QPushButton(tr('AI 分析'))
        self.btn_tsumego = QPushButton(tr('死活题'))
        self.btn_play.setCheckable(True)
        self.btn_analysis.setCheckable(True)
        self.btn_tsumego.setCheckable(True)
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        for button in (self.btn_play, self.btn_analysis, self.btn_tsumego):
            self.mode_buttons.addButton(button)
        self.btn_play.clicked.connect(self.enter_play_mode)
        self.btn_settings = QPushButton(tr('引擎设置'))
        self.btn_analysis.clicked.connect(self.enter_analysis_mode)
        self.btn_tsumego.clicked.connect(self.enter_tsumego_mode)
        self.btn_settings.clicked.connect(self.open_engine_settings)
        self.btn_ai = QPushButton(tr('AI 落子'))
        self.btn_undo = QPushButton(tr('悔棋'))
        self.btn_pass = QPushButton(tr('停一手'))
        self.btn_score = QPushButton(tr('数子'))
        self.btn_resign = QPushButton(tr('认输'))
        self.btn_open = QPushButton(tr('打开 SGF'))
        self.btn_save = QPushButton(tr('导出 SGF'))
        self.btn_restart = QPushButton(tr('重启引擎'))
        self.btn_new.clicked.connect(self.new_game)
        self.btn_ai.clicked.connect(self.ctl.ai_move)
        self.btn_undo.clicked.connect(self.ctl.undo)
        self.btn_pass.clicked.connect(self.ctl.human_pass)
        self.btn_score.clicked.connect(self.show_score)
        self.btn_resign.clicked.connect(self.resign)
        self.btn_open.clicked.connect(self.open_sgf)
        self.btn_save.clicked.connect(lambda: self.save_sgf(False))
        self.btn_restart.clicked.connect(self.ctl.restart_engine)
        self._control_buttons = (self.btn_new, self.btn_settings,
                                 self.btn_ai, self.btn_undo, self.btn_pass, self.btn_score,
                                 self.btn_resign, self.btn_restart, self.btn_open, self.btn_save)
        self._button_grid = QGridLayout()
        self._button_grid.setSpacing(6)
        self._button_layout_mode: Optional[InteractionMode] = None
        self.strength = QComboBox()
        for p in PRESETS.values():
            self.strength.addItem(tr(p.label), p.key)
        self.strength.setCurrentIndex(list(PRESETS).index(get_preset(self.ctl.strength_key).key))
        self.strength.currentIndexChanged.connect(self._on_strength)
        self.strength_desc = QLabel()
        self.strength_desc.setWordWrap(True)
        self.strength_desc.setObjectName("mutedText")
        # Strength only affects AI moves, so the whole block is hidden in analysis mode.
        self.strength_box = QWidget()
        sl = QVBoxLayout(self.strength_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        srow = QHBoxLayout()
        self.strength_label = QLabel(tr('AI 强度'))
        srow.addWidget(self.strength_label)
        srow.addWidget(self.strength, 1)
        sl.addLayout(srow)
        sl.addWidget(self.strength_desc)
        self.game_info = QLabel()
        self.game_info.setWordWrap(True)
        self.game_info.setTextFormat(Qt.TextFormat.RichText)
        ctrl = self.control_group = QGroupBox(tr('对局'))
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(10, 12, 10, 10)
        cl.setSpacing(8)
        cl.addWidget(self.game_info)
        cl.addLayout(self._button_grid)
        cl.addWidget(self.strength_box)

        self.moves = MoveList()
        self.analysis = AnalysisPanel()
        self.analysis.toggle_requested.connect(self._toggle_analysis)
        self.analysis.preview_changed.connect(self.board.set_preview)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.analysis, tr('分析'))
        self.tabs.addTab(self.moves, tr('着手列表'))
        right = QWidget()
        right.setObjectName("sidePanel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(ctrl)
        rl.addWidget(self.tabs, 1)
        right.setMinimumWidth(340)

        self.right_scroll = QScrollArea()
        self.right_scroll.setObjectName("sideScroll")
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll.setWidget(right)
        self.right_scroll.setMinimumWidth(360)

        self.split = QSplitter()
        self.split.addWidget(left)
        self.split.addWidget(self.right_scroll)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, False)
        self.split.setCollapsible(1, False)
        self._expanded_sizes: list[int] = []
        self._tsumego_active = False

        self.btn_sidebar = QPushButton(tr('收起右栏'))
        self.btn_sidebar.setCheckable(True)
        self.btn_sidebar.setChecked(True)
        self.btn_sidebar.setAccessibleName(tr('收起右栏'))
        self.btn_sidebar.toggled.connect(self.set_sidebar_expanded)
        self.workspace_title = QLabel()
        self.workspace_title.setObjectName("sectionTitle")
        self.workspace_engine = QLabel()
        self.workspace_engine.setObjectName("mutedText")
        header = QHBoxLayout()
        header.addWidget(self.workspace_title, 1)
        header.addWidget(self.workspace_engine)
        header.addWidget(self.btn_sidebar)

        self.workspace = QWidget()
        self.workspace.setObjectName("appRoot")
        self.main_menu = QWidget()
        self.main_menu.setObjectName("mainMenu")
        self.main_menu.setFixedWidth(128)
        menu_layout = QVBoxLayout(self.main_menu)
        menu_layout.setContentsMargins(8, 12, 8, 12)
        menu_layout.setSpacing(10)
        self.brand = QLabel(APP_NAME)
        self.brand.setObjectName("sectionTitle")
        menu_layout.addWidget(self.brand)
        self.menu_title = QLabel(tr('主菜单'))
        menu_layout.addWidget(self.menu_title)
        menu_layout.addWidget(self.btn_play)
        menu_layout.addWidget(self.btn_analysis)
        menu_layout.addWidget(self.btn_tsumego)
        menu_layout.addStretch(1)
        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(self.main_menu)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.split)
        self.tsumego_page = TsumegoPage()
        self.content_stack.addWidget(self.tsumego_page)
        content.addWidget(self.content_stack, 1)
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(24, 16, 24, 16)
        workspace_layout.setSpacing(12)
        workspace_layout.addLayout(header)
        workspace_layout.addLayout(content, 1)

        self.setCentralWidget(self.workspace)

        self.lbl_turn = QLabel()
        self.lbl_state = QLabel()
        self.lbl_time = QLabel()
        self.lbl_msg = QLabel()
        sb = self.statusBar()
        sb.addWidget(self.lbl_turn)
        sb.addWidget(self.lbl_state)
        sb.addWidget(self.lbl_time)
        sb.addWidget(self.lbl_msg, 1)
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._update_timer)

        self._build_menu()

        c = self.ctl
        c.state_changed.connect(self._on_state)
        c.game_changed.connect(self.refresh)
        c.analysis_changed.connect(self._on_analysis)
        c.message.connect(self._show_msg)
        c.error.connect(self._on_error)
        c.startup_progress.connect(self._show_msg)
        c.engine_info.connect(lambda s: self._show_msg(tr('已连接引擎：{0}', s)))
        c.engine.io_log.connect(self._log)
        c.engine.stderr_line.connect(lambda s: self._log("[stderr] " + s))
        self.refresh()
        self._on_state(c.state)

    def _build_menu(self) -> None:
        m = self.file_menu = self.menuBar().addMenu(tr('文件(&F)'))
        self.file_actions: list[QAction] = []
        for text, key, slot in ((tr('新建棋局…'), QKeySequence.StandardKey.New, self.new_game),
                                (tr('打开 SGF…'), QKeySequence.StandardKey.Open, self.open_sgf),
                                (tr('保存 SGF'), QKeySequence.StandardKey.Save, lambda: self.save_sgf(False)),
                                (tr('另存为…'), QKeySequence.StandardKey.SaveAs, lambda: self.save_sgf(True))):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
            self.file_actions.append(a)
        m.addSeparator()
        q = self.exit_action = QAction(tr('退出'), self)
        q.triggered.connect(self.close)
        m.addAction(q)
        e = self.engine_menu = self.menuBar().addMenu(tr('引擎(&E)'))
        self.engine_actions: list[QAction] = []
        for text, slot in ((tr('引擎设置…'), self.open_engine_settings), (tr('重启引擎'), self.ctl.restart_engine),
                           (tr('查看日志…'), lambda: LogDialog(list(self.log_lines), self).exec())):
            a = QAction(text, self)
            a.triggered.connect(slot)
            e.addAction(a)
            self.engine_actions.append(a)
        view = self.view_menu = self.menuBar().addMenu(tr('视图(&V)'))
        self.sidebar_action = QAction(tr('显示右栏'), self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.setShortcut("Ctrl+Shift+P")
        self.sidebar_action.toggled.connect(self.set_sidebar_expanded)
        view.addAction(self.sidebar_action)
        self.analysis_mode_action = QAction(tr('AI 分析模式'), self)
        self.analysis_mode_action.triggered.connect(self.enter_analysis_mode)
        view.addAction(self.analysis_mode_action)
        self.tsumego_mode_action = QAction(tr('死活题模式'), self)
        self.tsumego_mode_action.triggered.connect(self.enter_tsumego_mode)
        view.addAction(self.tsumego_mode_action)
        self.analysis_action = QAction(tr('开始分析'), self)
        self.analysis_action.triggered.connect(self._toggle_analysis)
        view.addAction(self.analysis_action)
        self.language_menu = self.menuBar().addMenu(tr("语言(&L)"))
        self.language_actions: dict[str, QAction] = {}
        for language, title in (("zh_CN", "简体中文"), ("en", "English")):
            action = QAction(title, self)
            action.setCheckable(True)
            action.setChecked(language == self.settings.language)
            action.triggered.connect(lambda _checked=False, value=language: self.change_language(value))
            self.language_menu.addAction(action)
            self.language_actions[language] = action

    def change_language(self, language: str) -> None:
        previous = self.settings.language
        self.settings.language = language
        if not self._save_settings():
            self.settings.language = previous
            for key, action in self.language_actions.items():
                action.setChecked(key == previous)
            return
        set_language(language)
        self.retranslate_ui()
        self.refresh()
        self._update_timer()
        self._show_msg(tr("界面语言已切换"))

    def retranslate_ui(self) -> None:
        for button, source in (
            (self.btn_new, "新建棋局"), (self.btn_play, "人机对战"),
            (self.btn_analysis, "AI 分析"), (self.btn_tsumego, "死活题"),
            (self.btn_settings, "引擎设置"),
            (self.btn_ai, "AI 落子"), (self.btn_undo, "悔棋"),
            (self.btn_pass, "停一手"), (self.btn_score, "数子"),
            (self.btn_resign, "认输"), (self.btn_open, "打开 SGF"),
            (self.btn_save, "导出 SGF"), (self.btn_restart, "重启引擎"),
            (self.banner_btn_settings, "引擎设置…"), (self.banner_btn_restart, "重启引擎"),
        ):
            button.setText(tr(source))
        self.menu_title.setText(tr("主菜单"))
        self.control_group.setTitle(tr("对局"))
        self.strength_label.setText(tr("AI 强度"))
        self.tabs.setTabText(0, tr("分析"))
        self.tabs.setTabText(1, tr("着手列表"))
        for menu, source in ((self.file_menu, "文件(&F)"), (self.engine_menu, "引擎(&E)"),
                             (self.view_menu, "视图(&V)"), (self.language_menu, "语言(&L)")):
            menu.setTitle(tr(source))
        for action, source in zip(self.file_actions, ("新建棋局…", "打开 SGF…", "保存 SGF", "另存为…")):
            action.setText(tr(source))
        for action, source in zip(self.engine_actions, ("引擎设置…", "重启引擎", "查看日志…")):
            action.setText(tr(source))
        self.exit_action.setText(tr("退出"))
        self.sidebar_action.setText(tr("显示右栏"))
        self.analysis_mode_action.setText(tr("AI 分析模式"))
        self.tsumego_mode_action.setText(tr("死活题模式"))
        for key, action in self.language_actions.items():
            action.setChecked(key == self.settings.language)
        self.strength.blockSignals(True)
        for index, preset in enumerate(PRESETS.values()):
            self.strength.setItemText(index, tr(preset.label))
        self.strength.blockSignals(False)
        expanded = self.btn_sidebar.isChecked()
        text = tr("收起右栏" if expanded else "展开右栏")
        self.btn_sidebar.setText(text)
        self.btn_sidebar.setAccessibleName(text)
        self.analysis.retranslate_ui()
        self.tsumego_page.retranslate_ui()

    # ------------------------------------------------------------ refresh
    def refresh(self) -> None:
        g = self.ctl.game
        self.board.set_game(g)
        self.moves.set_game(g)
        self.analysis.set_result(self.ctl.analysis, len(g.moves))
        if self.ctl.analysis is None:
            self.board.set_analysis(None)
        caps = g.board.captures
        if g.result:
            res = format_result(g.result)
        elif g.finished:
            res = g.result_note or tr('已终局，无计分结果')
        else:
            res = tr('进行中')
        name = self.current_path.name if self.current_path else tr('未保存的棋谱')
        lines = [tr('<b>{0} 路</b> · {1} · 贴目 {2:g}', g.size, tr(g.rules.label), g.komi)]
        if self.ctl.mode == InteractionMode.PLAY:
            lines.append(
                tr('你执{0}，KataGo 执{1}', tr('黑') if g.human_color == 'B' else tr('白'), tr('白') if g.human_color == 'B' else tr('黑'))
            )
        lines.append(tr('手数 {0} · 提子 黑 {1} / 白 {2} · 结果：<b>{3}</b>', len(g.moves), caps['B'], caps['W'], escape(res)))
        lines.append(tr('棋谱：{0}{1}', escape(name), ' *' if g.dirty else ''))
        self.game_info.setText("<br>".join(lines))
        if self.ctl.mode == InteractionMode.ANALYSIS:
            self.workspace_title.setText(tr('AI 分析 · {0} 路 · 第 {1} 手', g.size, len(g.moves)))
        else:
            mode_name = tr('人机对弈 · ') + (tr('你执黑') if g.human_color == "B" else tr('你执白'))
            self.workspace_title.setText(tr('{0} · {1} 路 · {2}', mode_name, g.size, tr(get_preset(self.ctl.strength_key).label)))
        self.setWindowTitle(f"{APP_NAME} — {name}{' *' if g.dirty else ''}")
        self.strength_desc.setText(get_preset(self.ctl.strength_key).describe())
        self.strength.blockSignals(True)
        self.strength.setCurrentIndex(list(PRESETS).index(self.ctl.strength_key))
        self.strength.blockSignals(False)
        self._update_controls()

    def _update_controls(self) -> None:
        c = self.ctl
        s = c.state
        g = c.game
        analysis_mode = c.mode == InteractionMode.ANALYSIS
        self.board.set_interactive(c.can_board_play())
        self.btn_ai.setEnabled(c.can_ai_move())
        self.btn_ai.setVisible(not analysis_mode)
        self.btn_undo.setEnabled(c.can_undo())
        self.btn_pass.setEnabled(c.can_board_play())
        self.btn_score.setEnabled(g.finished)
        self.btn_score.setToolTip("" if g.finished else tr('局中请查看 AI 目差估计'))
        self.btn_resign.setEnabled(c.can_human_play())
        self.btn_resign.setVisible(not analysis_mode)
        self.strength_box.setVisible(not analysis_mode)
        self._layout_buttons(c.mode)
        idle = c.can_replace_game
        self.btn_new.setEnabled(idle)
        self.btn_open.setEnabled(idle)
        self.btn_save.setEnabled(c.can_save)
        for i, action in enumerate(self.file_actions):
            action.setEnabled(idle if i < 2 else c.can_save)
        self.btn_restart.setEnabled(s not in (State.UNCONFIGURED,))
        self.btn_analysis.setEnabled(idle)
        self.btn_play.setEnabled(idle)
        self.btn_tsumego.setEnabled(idle or self._tsumego_active)
        self.btn_analysis.setChecked(not self._tsumego_active and analysis_mode)
        self.btn_play.setChecked(not self._tsumego_active and not analysis_mode)
        self.btn_tsumego.setChecked(self._tsumego_active)
        self.analysis_mode_action.setEnabled(idle)
        self.tsumego_mode_action.setEnabled(idle or self._tsumego_active)
        self.strength.setEnabled(idle)
        # Analysis stays "on" across moves until the user stops it, even while a move is syncing.
        running = c.analysis_enabled or (s == State.ANALYZING and not c.analysis_stopping)
        self.analysis.set_running(running, running or c.can_analyze())
        self.analysis_action.setText(tr('停止分析') if running else tr('开始分析'))
        self.analysis_action.setEnabled(running or c.can_analyze())
        if s in (State.READY, State.GAME_OVER) and not c.supports_analysis and c.commands:
            self.analysis.set_unsupported(tr('当前引擎不支持 kata-analyze，无法显示分析结果。'))
        if g.finished:
            turn = tr('对局已结束')
        elif analysis_mode:
            turn = tr('{0}行棋（编辑模式）', color_name(g.to_move))
        else:
            whose = tr('你') if g.to_move == g.human_color else "AI"
            turn = tr('{0}行棋（{1}）', color_name(g.to_move), whose)
        self.lbl_turn.setText(turn)
        self.lbl_state.setText(tr('引擎：{0}', tr(s.value)))
        self.workspace_engine.setText(tr(s.value))
        if s == State.UNCONFIGURED:
            self.banner_text.setText(tr('尚未配置 KataGo 引擎：') + (c.last_error or "") +
                                     tr('\n请打开“引擎设置”指定 katago.exe、模型和配置文件，或运行 python -m katago_gui.setup_engine 自动安装。'))
            self.banner_btn_restart.hide()
            self.banner.show()
        elif s == State.ERROR:
            self.banner_text.setText(c.last_error + tr('\n棋谱已保留，可重启引擎从当前局面继续，或检查引擎设置。'))
            self.banner_btn_restart.show()
            self.banner.show()
        else:
            self.banner.hide()
    def _layout_buttons(self, mode: InteractionMode) -> None:
        """Pack only the visible control buttons into a dense 3-column grid."""
        if mode == self._button_layout_mode:
            return
        self._button_layout_mode = mode
        for b in self._control_buttons:
            self._button_grid.removeWidget(b)
        hidden = (self.btn_ai, self.btn_resign) if mode == InteractionMode.ANALYSIS else ()
        shown = [b for b in self._control_buttons if b not in hidden]
        for i, b in enumerate(shown):
            self._button_grid.addWidget(b, i // 3, i % 3)

    # ------------------------------------------------------------ signals
    def _on_state(self, s: State) -> None:
        if s in (State.AI_THINKING, State.ANALYZING, State.STARTING):
            self._think_started = time.monotonic()
            self._tick.start()
        else:
            self._think_started = None
            self._tick.stop()
            self.lbl_time.setText("")
        self._update_controls()

    def _update_timer(self) -> None:
        if self._think_started is not None:
            self.lbl_time.setText(tr('{0:.1f} 秒', time.monotonic() - self._think_started))

    def _on_analysis(self, r) -> None:
        self.board.set_analysis(r)
        self.analysis.set_result(r, len(self.ctl.game.moves))

    def _show_msg(self, text: str) -> None:
        self.lbl_msg.setText(text)

    def _on_error(self, text: str) -> None:
        self._show_msg(text.splitlines()[0])
        self._log("[error] " + text)
        self._update_controls()
        if self.ask and self.ctl.state not in (State.UNCONFIGURED, State.ERROR):
            QMessageBox.warning(self, tr('错误'), text)

    def _log(self, line: str) -> None:
        self.log_lines.append(line)
        log.info(line)

    def _on_point(self, x: int, y: int) -> None:
        self.ctl.board_play((x, y))

    def _on_strength(self, _i: int) -> None:
        self.ctl.set_strength(self.strength.currentData(), self._save_settings)
        self.refresh()

    def _toggle_analysis(self) -> None:
        if self.ctl.analysis_enabled or self.ctl.state == State.ANALYZING:
            self.ctl.stop_analysis()
            self._update_controls()
        else:
            self.ctl.start_analysis()

    # ------------------------------------------------------------ actions
    def set_sidebar_expanded(self, expanded: bool) -> None:
        if not expanded and not self.right_scroll.isHidden():
            self._expanded_sizes = self.split.sizes()
        self.right_scroll.setVisible(expanded)
        if expanded:
            if self._expanded_sizes:
                self.split.setSizes(self._expanded_sizes)
            else:
                vertical = self.split.orientation() == Qt.Orientation.Vertical
                total = self.split.height() if vertical else self.split.width()
                board_share = 0.55 if vertical else 0.72
                self.split.setSizes([int(total * board_share), int(total * (1 - board_share))])
        text = tr('收起右栏') if expanded else tr('展开右栏')
        self.btn_sidebar.setText(text)
        self.btn_sidebar.setAccessibleName(text)
        for control in (self.btn_sidebar, self.sidebar_action):
            control.blockSignals(True)
            control.setChecked(expanded)
            control.blockSignals(False)

    def show_workspace(self) -> None:
        self._tsumego_active = False
        self.content_stack.setCurrentWidget(self.split)
        self.refresh()

    def enter_play_mode(self) -> None:
        if self._tsumego_active:
            self._tsumego_active = False
            self.content_stack.setCurrentWidget(self.split)
        if self.ctl.mode == InteractionMode.ANALYSIS:
            self.new_game()
        else:
            self.refresh()
        self._update_controls()

    def enter_analysis_mode(self) -> None:
        self._tsumego_active = False
        self.content_stack.setCurrentWidget(self.split)
        if not self.ctl.can_replace_game:
            self._show_msg(tr('请等待当前引擎操作完成'))
            self._update_controls()
            return

        def committed() -> None:
            self.set_sidebar_expanded(True)
            self.tabs.setCurrentWidget(self.analysis)
            self.refresh()

        self.ctl.set_mode(InteractionMode.ANALYSIS, committed)
        self._update_controls()

    def enter_tsumego_mode(self) -> None:
        if self.ctl.state in (State.STARTING, State.SYNCING, State.AI_THINKING):
            self._show_msg(tr('请等待当前引擎操作完成'))
            self._update_controls()
            return
        if self.ctl.analysis_enabled or self.ctl.state == State.ANALYZING:
            self.ctl.stop_analysis()
        self._tsumego_active = True
        self.content_stack.setCurrentWidget(self.tsumego_page)
        self.workspace_title.setText(tr("死活题"))
        self._update_controls()

    def show_score(self) -> None:
        g = self.ctl.game
        if not g.finished:
            self._show_msg(tr('局中请查看 AI 目差估计'))
            return
        text = format_result(g.result) if g.result else (g.result_note or tr('已终局，但引擎未能给出计分结果'))
        self._show_msg(text)
        if self.ask:
            QMessageBox.information(self, tr('数子结果'), text)

    def confirm_discard(self) -> bool:
        """Return True if it's OK to replace the current game."""
        if not self.ctl.game.dirty or not self.ask:
            return True
        r = QMessageBox.question(self, tr('未保存的棋谱'), tr('当前棋谱有未保存的变更，是否保存？'),
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Save:
            return self.save_sgf(False)
        return r == QMessageBox.StandardButton.Discard

    def new_game(self) -> None:
        if not self.ctl.can_replace_game:
            self._show_msg(tr('请等待当前引擎操作完成'))
            return
        d = NewGameDialog(self.settings.game, self)
        if d.exec() != NewGameDialog.DialogCode.Accepted:
            return
        if not self.confirm_discard():
            return
        size, color, rules, komi, strength = d.values()

        def committed() -> None:
            self.current_path = None
            self._tsumego_active = False
            self.content_stack.setCurrentWidget(self.split)
            self._save_settings()

        self.ctl.new_game(size, color, rules, komi, strength, committed, InteractionMode.PLAY)

    def resign(self) -> None:
        if self.ask and QMessageBox.question(self, tr('认输'), tr('确定认输吗？')) != QMessageBox.StandardButton.Yes:
            return
        self.ctl.resign()

    def open_sgf(self) -> None:
        if not self.ctl.can_replace_game:
            return
        f, _ = QFileDialog.getOpenFileName(self, tr('打开 SGF'), self.settings.last_sgf_dir, tr('SGF 棋谱 (*.sgf);;所有文件 (*)'))
        if f:
            self.load_path(Path(f))

    def load_path(self, path: Path, mode: Optional[InteractionMode] = None) -> bool:
        if not self.ctl.can_replace_game:
            self._show_msg(tr('请等待引擎完成当前操作，再打开棋谱'))
            return False
        try:
            res = load_sgf(path)
        except SgfError as e:
            self._error_box(tr('无法打开棋谱 {0}：\n{1}', path.name, e))
            return False
        except OSError as e:
            self._error_box(tr('无法读取文件：{0}', e))
            return False
        if res.warnings and self.ask:
            text = tr('棋谱可以导入，但有以下问题：\n\n• ') + "\n• ".join(res.warnings) + tr('\n\n是否继续导入？')
            if QMessageBox.question(self, tr('导入警告'), text) != QMessageBox.StandardButton.Yes:
                return False
        for w in res.warnings:
            self._log("[sgf] " + w)
        if not self.confirm_discard():
            return False

        def committed() -> None:
            self.current_path = path
            self.settings.last_sgf_dir = str(path.parent)
            self._save_settings()
            last = res.game.last_move
            self._show_msg(tr('已导入 {0}，共 {1} 手', path.name, len(res.game.moves)) +
                           (tr('，最后一手 {0}', to_gtp(last.move, res.game.size)) if last else ""))
            self.show_workspace()

        return self.ctl.replace_game(res.game, committed, mode=mode)

    def save_sgf(self, save_as: bool) -> bool:
        if not self.ctl.can_save:
            self._show_msg(tr('请等待引擎确认棋局，再保存棋谱'))
            return False
        path = self.current_path
        if path is None or save_as:
            start = str(Path(self.settings.last_sgf_dir or Path.home()) / "对局.sgf")
            f, _ = QFileDialog.getSaveFileName(self, tr('保存 SGF'), start, tr('SGF 棋谱 (*.sgf)'))
            if not f:
                return False
            path = Path(f)
            if path.suffix.lower() != ".sgf":
                path = path.with_suffix(".sgf")
        return self.save_to(path)

    def save_to(self, path: Path) -> bool:
        if not self.ctl.can_save:
            self._show_msg(tr('请等待引擎确认棋局，再保存棋谱'))
            return False
        try:
            save_sgf(self.ctl.game, path)
        except OSError as e:
            self._error_box(tr('保存失败：{0}', e))
            return False
        self.ctl.game.dirty = False
        self.current_path = path
        self.settings.last_sgf_dir = str(path.parent)
        self._save_settings()
        self._show_msg(tr('已保存到 {0}', path))
        self.refresh()
        return True

    def open_engine_settings(self) -> None:
        d = EngineSettingsDialog(self.settings.engine, self)
        if d.exec() != EngineSettingsDialog.DialogCode.Accepted:
            return
        self.settings.engine = d.result_settings()
        if not self._save_settings():
            return
        self.ctl.settings = self.settings
        self.ctl.restart_engine()

    def _error_box(self, text: str) -> None:
        self._log("[error] " + text)
        self._show_msg(text.splitlines()[0])
        if self.ask:
            QMessageBox.critical(self, tr('错误'), text)

    def closeEvent(self, e: QCloseEvent) -> None:
        if self.ctl.state in (State.STARTING, State.SYNCING, State.AI_THINKING, State.ANALYZING):
            self.ctl.interrupt()
        if not self.confirm_discard():
            e.ignore()
            return
        self._save_settings()
        self.ctl.shutdown()
        e.accept()

    def resizeEvent(self, e) -> None:
        compact = e.size().width() < 1100
        orientation = Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
        if self.split.orientation() != orientation:
            self._expanded_sizes = []
            self.split.setOrientation(orientation)
            if self.btn_sidebar.isChecked():
                self.set_sidebar_expanded(True)
        self.right_scroll.setMinimumWidth(0 if compact else 360)
        super().resizeEvent(e)

    def _save_settings(self) -> bool:
        try:
            self.settings.save()
        except (OSError, ValueError) as e:
            self._error_box(tr('设置保存失败：{0}', e))
            return False
        return True
