import pytest

from katago_gui.controller import InteractionMode, State
from katago_gui.go.coords import from_gtp
from katago_gui.sgf import load_sgf
from katago_gui.ui.main_window import MainWindow

from conftest import wait_state


def test_main_window_flow(qtbot, make_controller, tmp_path):
    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show()
    c.start_engine()
    wait_state(qtbot, c, State.READY)
    assert w.banner.isHidden() and w.board.interactive

    # Click on E5 via the board widget's geometry.
    pt = w.board.center_of(from_gtp("E5", 9)).toPoint()
    from PySide6.QtCore import Qt
    qtbot.mouseClick(w.board, Qt.MouseButton.LeftButton, pos=pt)
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 2, timeout=5000)
    assert w.moves.count() == 2 and "E5" in w.moves.item(0).text()
    # Clicking an occupied point does nothing.
    qtbot.mouseClick(w.board, Qt.MouseButton.LeftButton, pos=pt)
    assert len(c.game.moves) == 2

    p = tmp_path / "g.sgf"
    assert w.save_to(p) and not c.game.dirty
    assert load_sgf(p).game.moves == c.game.moves

    c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and not c.game.moves, timeout=5000)
    assert w.load_path(p)
    wait_state(qtbot, c, State.READY)
    assert len(c.game.moves) == 2 and w.current_path == p

    img = w.grab()
    assert not img.isNull()


def test_main_window_unconfigured(qtbot, isolated_home):
    from katago_gui.settings import Settings
    w = MainWindow(Settings(), ask=False)
    qtbot.addWidget(w)
    w.show()
    w.ctl.start_engine()
    assert w.ctl.state == State.UNCONFIGURED
    assert not w.banner.isHidden() and "setup_engine" in w.banner_text.text()
    assert not w.board.interactive


def test_workspace_starts_directly_and_analysis_preserves_game(qtbot, make_controller, tmp_path):
    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show()
    assert w.centralWidget() is w.workspace
    assert w.brand.text() == "Cangmiao" and w.windowTitle().startswith("Cangmiao")
    assert w.btn_play.parentWidget() is w.main_menu
    assert w.btn_analysis.parentWidget() is w.main_menu
    assert w.btn_play.isChecked() and not w.btn_analysis.isChecked()
    assert all(button.isVisible() for button in (
        w.btn_new, w.btn_analysis, w.btn_settings, w.btn_sidebar
    ))
    c.game.play("B", from_gtp("E5", 9))
    w.current_path = tmp_path / "current.sgf"
    w.btn_analysis.click()
    assert c.mode == InteractionMode.ANALYSIS
    assert len(c.game.moves) == 1
    assert w.current_path == tmp_path / "current.sgf"
    assert w.btn_ai.isHidden() and w.btn_resign.isHidden()
    assert w.tabs.currentWidget() is w.analysis
    assert w.btn_analysis.isChecked() and not w.btn_play.isChecked()


@pytest.mark.parametrize("accepted", [False, True])
def test_left_play_menu_from_analysis_uses_new_game(qtbot, make_controller, monkeypatch, accepted):
    from katago_gui.ui.dialogs import NewGameDialog

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show()
    w.btn_analysis.click()
    c.game.play("B", from_gtp("E5", 9))
    previous = c.game
    w.btn_sidebar.click()
    assert w.main_menu.isVisible() and w.btn_play.isVisible()
    monkeypatch.setattr(NewGameDialog, "exec", lambda _d: (
        NewGameDialog.DialogCode.Accepted if accepted else NewGameDialog.DialogCode.Rejected
    ))
    w.btn_play.click()
    assert c.mode == (InteractionMode.PLAY if accepted else InteractionMode.ANALYSIS)
    assert w.btn_play.isChecked() == accepted
    assert w.btn_analysis.isChecked() != accepted
    if accepted:
        assert c.game is not previous and not c.game.moves
    else:
        assert c.game is previous and len(c.game.moves) == 1


def test_left_play_menu_preserves_current_play_game(qtbot, make_controller):
    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    c.game.play("B", from_gtp("E5", 9))
    previous = c.game
    w.btn_play.click()
    assert c.game is previous and len(c.game.moves) == 1
    assert w.btn_play.isChecked() and not w.btn_analysis.isChecked()


def test_analysis_continues_when_collapsed_and_can_stop_from_menu(qtbot, make_controller):
    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show()
    c.start_engine()
    wait_state(qtbot, c, State.READY)
    w.btn_analysis.click()
    w.analysis.button.click()
    qtbot.waitUntil(lambda: c.analysis is not None, timeout=5000)
    assert w.analysis.button.text() == "停止分析"
    assert c.board_play(from_gtp("E5", 9))
    assert w.analysis.button.text() == "停止分析"  # still on while the move is synced
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.move_number == 1, timeout=5000)
    assert w.analysis.button.text() == "停止分析" and c.state == State.ANALYZING
    w.btn_sidebar.click()
    assert w.right_scroll.isHidden() and c.analysis_enabled
    w.analysis_action.trigger()
    wait_state(qtbot, c, State.READY)
    assert c.state == State.READY and not c.analysis_enabled
    assert w.analysis.button.text() == "开始分析"
    w.btn_sidebar.click()
    assert w.right_scroll.isVisible()


@pytest.mark.parametrize("width, height", [(1280, 860), (1366, 768), (800, 900)])
def test_sidebar_toggle_preserves_tabs_and_board_geometry(qtbot, make_controller, width, height):
    from PySide6.QtCore import Qt

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.resize(width, height)
    w.show()
    qtbot.wait(20)
    w.tabs.setCurrentWidget(w.moves)
    sizes = w.split.sizes()
    expanded_size = w.board.size()
    w.btn_sidebar.setFocus()
    qtbot.keyClick(w.btn_sidebar, Qt.Key.Key_Space)
    qtbot.wait(20)
    assert w.right_scroll.isHidden() and not w.sidebar_action.isChecked()
    assert w.btn_sidebar.isVisible() and w.btn_sidebar.accessibleName() == "展开右栏"
    assert w.board.width() >= expanded_size.width()
    assert w.board.height() >= expanded_size.height()
    w.sidebar_action.trigger()
    qtbot.wait(20)
    assert w.right_scroll.isVisible() and w.btn_sidebar.isChecked()
    assert w.tabs.currentWidget() is w.moves
    assert all(abs(before - after) <= 2 for before, after in zip(sizes, w.split.sizes()))
    w.btn_sidebar.click()
    w.resize(800 if width >= 1100 else 1280, height)
    qtbot.wait(20)
    w.btn_sidebar.click()
    qtbot.wait(20)
    assert w.right_scroll.isVisible() and w.btn_sidebar.isVisible()
    if w.split.orientation() == Qt.Orientation.Vertical:
        assert w.right_scroll.height() >= 200
    for point in ((0, 0), (4, 4), (8, 8)):
        center = w.board.center_of(point)
        assert w.board.point_at(center.x(), center.y()) == point


@pytest.mark.parametrize("color", ["B", "W"])
@pytest.mark.parametrize("entry", ["button", "menu"])
def test_new_game_unifies_color_from_analysis(qtbot, make_controller, monkeypatch, color, entry):
    from katago_gui.ui.dialogs import NewGameDialog

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show()
    c.start_engine(auto_ai_move=False)
    wait_state(qtbot, c, State.READY)
    w.btn_analysis.click()
    assert c.board_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    w.analysis.button.click()
    wait_state(qtbot, c, State.ANALYZING)

    def accept(dialog):
        dialog.show()
        assert dialog.color.isVisible()
        dialog.color.setCurrentIndex(0 if color == "B" else 1)
        dialog.size.setCurrentIndex(1)
        dialog.hide()
        return NewGameDialog.DialogCode.Accepted

    monkeypatch.setattr(NewGameDialog, "exec", accept)
    if entry == "button":
        w.btn_new.click()
    else:
        w.file_actions[0].trigger()
    qtbot.waitUntil(lambda: c.state == State.READY and c.mode == InteractionMode.PLAY, timeout=5000)
    qtbot.wait(150)
    assert c.game.size == 13 and c.game.human_color == color
    assert len(c.game.moves) == (1 if color == "W" else 0)
    assert c.game.to_move == color
    assert not c.analysis_enabled and w.current_path is None
    assert c.settings.game.human_color == color


@pytest.mark.parametrize("cancel_at", ["dialog", "discard"])
def test_new_game_cancel_preserves_record_and_mode(qtbot, make_controller, monkeypatch, tmp_path, cancel_at):
    from katago_gui.ui.dialogs import NewGameDialog

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.btn_analysis.click()
    c.game.play("B", from_gtp("E5", 9))
    w.current_path = tmp_path / "old.sgf"
    game, settings = c.game, c.settings.game
    confirmations = []
    monkeypatch.setattr(NewGameDialog, "exec", lambda _d: (
        NewGameDialog.DialogCode.Rejected if cancel_at == "dialog" else NewGameDialog.DialogCode.Accepted
    ))
    monkeypatch.setattr(w, "confirm_discard", lambda: confirmations.append(True) or False)
    w.new_game()
    assert c.game is game and c.settings.game is settings
    assert c.mode == InteractionMode.ANALYSIS and len(c.game.moves) == 1
    assert w.current_path == tmp_path / "old.sgf"
    assert len(confirmations) == (0 if cancel_at == "dialog" else 1)


def test_startup_does_not_trigger_ai_first_move(qtbot, make_controller):
    c = make_controller(board_size=9, human_color="W")
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    c.start_engine(auto_ai_move=False)
    wait_state(qtbot, c, State.READY)
    qtbot.wait(150)
    assert not c.game.moves and c.can_ai_move()


def test_failed_new_game_keeps_original_record(qtbot, make_controller, monkeypatch, tmp_path):
    from katago_gui.ui.dialogs import NewGameDialog

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    c.start_engine()
    wait_state(qtbot, c, State.READY)
    w.btn_analysis.click()
    assert c.board_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    game, settings = c.game, c.settings.game
    w.current_path = tmp_path / "old.sgf"

    def fail_send(*_args):
        raise RuntimeError("test engine unavailable")

    monkeypatch.setattr(c.engine, "send", fail_send)
    monkeypatch.setattr(NewGameDialog, "exec", lambda _d: NewGameDialog.DialogCode.Accepted)
    w.new_game()
    wait_state(qtbot, c, State.ERROR)
    assert c.game is game and c.settings.game is settings
    assert c.mode == InteractionMode.ANALYSIS
    assert w.current_path == tmp_path / "old.sgf"
    assert "test engine unavailable" in w.banner_text.text()


def test_new_game_save_failure_preserves_original(qtbot, make_controller, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from katago_gui.ui.dialogs import NewGameDialog

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=True)
    qtbot.addWidget(w)
    c.game.play("B", from_gtp("E5", 9))
    game = c.game
    monkeypatch.setattr(NewGameDialog, "exec", lambda _d: NewGameDialog.DialogCode.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(w, "save_sgf", lambda _save_as: False)
    w.new_game()
    assert c.game is game and c.game.dirty


@pytest.mark.parametrize("width, height", [(1280, 860), (1366, 768)])
@pytest.mark.parametrize("low_samples", [False, True])
def test_analysis_panel_fits_without_scrolling(qtbot, make_controller, width, height, low_samples):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from katago_gui.controller import AnalysisResult, CandidateTier
    from katago_gui.engine.gtp import AnalysisSnapshot, CandidateMove
    from katago_gui.go.coords import to_gtp
    from katago_gui.ui.theme import CANDIDATE_COLORS

    c = make_controller(board_size=19)
    w = MainWindow(c.settings, controller=c, ask=False)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    qtbot.addWidget(w)
    w.resize(width, height)
    w.show()
    c.set_mode(InteractionMode.ANALYSIS)
    w.show_workspace()
    cands = [CandidateMove(to_gtp((i % 19, i // 19 + 2), 19), 0 if low_samples else 1000 - i,
                           0.6 - 0.005 * i, 2.0 - 0.2 * i, 0.1, i,
                           [to_gtp((i % 19, i // 19 + 2), 19)]) for i in range(30)]
    r = AnalysisResult(AnalysisSnapshot(cands, root_visits=1 if low_samples else 30000,
                                       root_winrate=0.6, root_score_lead=2.0),
                       "B", 0, 3.0)
    w._on_analysis(r)
    qtbot.wait(20)
    t = w.analysis.table
    assert t.rowCount() == 10 and w.strength_box.isHidden()
    assert w.right_scroll.verticalScrollBar().maximum() == 0
    assert t.verticalScrollBar().maximum() == 0
    assert w.analysis.legend.visibleRegion().boundingRect().height() == w.analysis.legend.height()
    tiers = [t.item(row, 0).toolTip().split("：")[0].split(" · ")[1] for row in range(3)]
    assert tiers == [CandidateTier.BEST.value, CandidateTier.HONTE.value, CandidateTier.HONTE.value]
    image = w.board.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(image.constBits())
    for color in CANDIDATE_COLORS.values():
        assert pixels.count(bytes(QColor(color).getRgb())) > 20
    for row, candidate in enumerate(r.ranked_candidates()):
        assert t.item(row, 0).background().color().name() == CANDIDATE_COLORS[candidate.tier.name].lower()


def test_dark_theme_text_is_readable(qtbot, make_controller):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    c = make_controller()
    w = MainWindow(c.settings, controller=c, ask=False)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    qtbot.addWidget(w)
    w.show()
    qtbot.wait(10)
    for label in (w.workspace_title, w.game_info, w.analysis.info, w.analysis.visits_value, w.lbl_state):
        assert label.palette().color(QPalette.ColorRole.WindowText).lightness() >= 180


def test_candidate_top_ten_updates_with_new_winrates(qtbot):
    from dataclasses import replace
    from katago_gui.controller import AnalysisResult
    from katago_gui.engine.gtp import AnalysisSnapshot, CandidateMove
    from katago_gui.ui.analysis_panel import AnalysisPanel
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    candidates = [CandidateMove(f"A{i + 1}", 100 + i, 0.6 - i / 100, 1.0, 0.1, i, [])
                  for i in range(19)]
    panel.set_result(AnalysisResult(AnalysisSnapshot(candidates), "W", 1, 1.0), 1)
    assert panel.table.rowCount() == 10 and panel.table.item(0, 0).text() == "A1"
    candidates[-1] = replace(candidates[-1], winrate=0.8, visits=500)
    panel.set_result(AnalysisResult(AnalysisSnapshot(candidates), "W", 1, 2.0), 1)
    assert panel.table.rowCount() == 10 and panel.table.item(0, 0).text() == "A19"
    assert panel.table.item(0, 2).text() == "80.0%"


@pytest.mark.parametrize("root_visits, candidate_visits, low_root, low_candidate", [
    (1, 0, True, True),
    (63, 15, True, True),
    (64, 16, False, False),
    (100, 1, False, True),
])
@pytest.mark.parametrize("side, move_number", [("B", 0), ("W", 1), ("B", 20)])
def test_live_winrates_mark_low_samples(qtbot, root_visits, candidate_visits, low_root, low_candidate,
                                       side, move_number):
    from katago_gui.controller import AnalysisResult
    from katago_gui.engine.gtp import AnalysisSnapshot, CandidateMove
    from katago_gui.ui.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    candidate = CandidateMove("D4", candidate_visits, 0.7, 1.5, 0.1, 0, ["D4"])
    for wr in (0.6, 0.4):
        snapshot = AnalysisSnapshot([candidate], root_visits, wr, 2.0)
        panel.set_result(AnalysisResult(snapshot, side, move_number, 1.0), move_number)
        black = wr if side == "B" else 1 - wr
        assert panel.bar.value() == int(black * 1000)
        assert ("低样本" in panel.info.text()) == (low_root or low_candidate)
        assert ("*" in panel.winrates.text()) == low_root
        assert panel.table.item(0, 2).text() == ("70.0%*" if low_candidate else "70.0%")
        tip = panel.table.item(0, 2).toolTip()
        assert ("尚未搜索" in tip) == (candidate_visits == 0)
        assert ("低样本" in tip) == low_candidate
    panel.set_result(None, move_number)
    assert "低样本" not in panel.info.text() and "*" not in panel.winrates.text()
    assert panel.winrates.toolTip() == "" and panel.bar.toolTip() == ""


def test_compact_workspace_uses_vertical_layout(qtbot, make_controller):
    from PySide6.QtCore import Qt

    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    w.show_workspace()
    w.show()
    w.resize(1024, 768)
    qtbot.wait(10)
    assert w.split.orientation() == Qt.Orientation.Vertical
    w.resize(1280, 860)
    qtbot.wait(10)
    assert w.split.orientation() == Qt.Orientation.Horizontal
    for move in ((0, 0), (4, 4), (8, 8)):
        center = w.board.center_of(move)
        assert w.board.point_at(center.x(), center.y()) == move


def test_busy_save_is_blocked_and_failed_import_preserves_filename(qtbot, make_controller, tmp_path):
    c = make_controller("reject_play", board_size=9)
    w = MainWindow(c.settings, controller=c, ask=False)
    qtbot.addWidget(w)
    c.start_engine()
    assert not w.save_to(tmp_path / "busy.sgf")
    assert not (tmp_path / "busy.sgf").exists()
    wait_state(qtbot, c, State.READY)
    original = tmp_path / "original.sgf"
    assert w.save_to(original)
    other = tmp_path / "other.sgf"
    other.write_text("(;SZ[9]PW[KataGo];B[aa];W[bb])", encoding="utf-8")
    assert w.load_path(other)
    wait_state(qtbot, c, State.ERROR)
    assert w.current_path == original


def test_live_analysis_preserves_selected_preview(qtbot):
    from katago_gui.ui.analysis_panel import AnalysisPanel
    from katago_gui.engine.gtp import AnalysisSnapshot, CandidateMove
    from katago_gui.controller import AnalysisResult
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    r = AnalysisResult(AnalysisSnapshot(
        [CandidateMove("D4", 10, 0.6, 1.0, 0.1, 0, ["D4"])], root_visits=10
    ),
                       "B", 0, 0.2)
    panel.set_result(r, 0)
    panel.table.selectRow(0)
    panel.set_result(r, 0)
    assert panel._selected_move() == "D4"
    assert panel.visits_value.text() == "10"
    assert panel.nps_value.text() == "50"
    empty = AnalysisResult(AnalysisSnapshot([], root_visits=0), "B", 0, 0)
    panel.set_result(empty, 0)
    assert panel.nps_value.text() == "—"


def test_ambiguous_detection_requires_explicit_choice(tmp_path):
    from katago_gui.ui.dialogs import detect_engine_files
    for backend in ("opencl", "eigen"):
        folder = tmp_path / backend
        folder.mkdir()
        (folder / "katago.exe").touch()
    with pytest.raises(ValueError, match="多个"):
        detect_engine_files(tmp_path)


def test_unsaved_save_discard_cancel(qtbot, make_controller, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    c = make_controller(board_size=9)
    w = MainWindow(c.settings, controller=c)
    qtbot.addWidget(w)
    c.game.play("B", (4, 4))
    w.current_path = tmp_path / "saved.sgf"
    answer = [QMessageBox.StandardButton.Cancel]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer[0])
    assert not w.confirm_discard() and c.game.dirty
    answer[0] = QMessageBox.StandardButton.Discard
    assert w.confirm_discard() and c.game.dirty
    answer[0] = QMessageBox.StandardButton.Save
    assert w.confirm_discard() and not c.game.dirty
    assert load_sgf(w.current_path).game.moves == c.game.moves
