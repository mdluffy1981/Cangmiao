import ast
import json
import string
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton

from katago_gui.controller import AnalysisResult, InteractionMode, State
from katago_gui.engine.gtp import AnalysisSnapshot, CandidateMove
from katago_gui.i18n import get_language, set_language
from katago_gui.i18n_core import ENGLISH as CORE_ENGLISH
from katago_gui.i18n_ui import ENGLISH as UI_ENGLISH
from katago_gui.settings import Settings
from katago_gui.ui.dialogs import EngineSettingsDialog, NewGameDialog
from katago_gui.ui.main_window import MainWindow

from conftest import wait_state


def has_chinese(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def test_catalog_preserves_format_fields():
    formatter = string.Formatter()
    for source, translated in (CORE_ENGLISH | UI_ENGLISH).items():
        assert not has_chinese(translated), source
        assert {(field, spec, conversion) for _, field, spec, conversion in formatter.parse(source)
                if field is not None} == {
            (field, spec, conversion) for _, field, spec, conversion in formatter.parse(translated)
            if field is not None
        }, source


def test_ui_literal_translation_coverage():
    root = Path(__file__).resolve().parents[1] / "src" / "katago_gui"
    catalog = CORE_ENGLISH | UI_ENGLISH
    for path in [* (root / "ui").glob("*.py"), root / "settings.py", root / "app.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                source = node.args[0].value
                if isinstance(source, str) and has_chinese(source):
                    assert source in catalog, (path.name, node.lineno, source)


def test_language_settings_roundtrip_and_legacy(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(language="en")
    settings.save(path)
    assert Settings.load(path).language == "en"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["language"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Settings.load(path).language == "zh_CN"
    data["language"] = "invalid"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)
    with pytest.raises(ValueError):
        set_language("invalid")
    set_language("en")
    assert Settings.load(tmp_path / "first-launch.json").language == "en"


def test_english_workspace_and_dialogs(qtbot, isolated_home):
    window = MainWindow(Settings(language="en"), ask=False)
    qtbot.addWidget(window)
    window.show()
    assert window.btn_play.text() == "Human vs AI"
    assert window.file_menu.title() == "&File"
    assert window.btn_sidebar.accessibleName() == "Hide Panel"
    assert "Chinese" in window.game_info.text()
    assert "not configured" in window.banner_text.text()
    assert not has_chinese(window.banner_text.text())
    new_game = NewGameDialog(window.settings.game)
    engine = EngineSettingsDialog(window.settings.engine)
    qtbot.addWidget(new_game)
    qtbot.addWidget(engine)
    assert new_game.color.itemText(0) == "Black (first)"
    assert new_game.rules.itemText(0) == "Chinese rules"
    assert new_game.strength.itemText(0) == "Fast"
    for dialog in (new_game, engine):
        box = dialog.findChild(QDialogButtonBox)
        assert box.button(QDialogButtonBox.StandardButton.Ok).text() == "OK"
        assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancel"
        assert not has_chinese(dialog.windowTitle())
        for child in dialog.findChildren(QLabel) + dialog.findChildren(QPushButton):
            assert not has_chinese(child.text()), child.text()
        for child in dialog.findChildren(QPlainTextEdit):
            assert not has_chinese(child.toPlainText())
    for child in window.findChildren(QLabel) + window.findChildren(QPushButton):
        assert not has_chinese(child.text()), child.text()


@pytest.mark.parametrize("width, height", [(1280, 860), (1366, 768)])
def test_english_analysis_and_live_language_switch(qtbot, make_controller, width, height):
    controller = make_controller(board_size=19)
    window = MainWindow(controller.settings, controller=controller, ask=False)
    qtbot.addWidget(window)
    window.resize(width, height)
    window.show()
    controller.set_mode(InteractionMode.ANALYSIS)
    candidates = [CandidateMove(chr(65 + i) + "4", 0, .6 - i * .01, 2., .1, i, ["D4"])
                  for i in range(10)]
    result = AnalysisResult(AnalysisSnapshot(candidates, root_visits=1, root_winrate=.6, root_score_lead=2),
                            "B", 0, 3.)
    controller.analysis = result
    window.refresh()
    window.analysis.table.selectRow(0)
    window.set_sidebar_expanded(False)
    previous_game = controller.game
    window.language_actions["en"].trigger()
    qtbot.wait(30)
    assert controller.game is previous_game and controller.analysis is result
    assert window.right_scroll.isHidden()
    assert window.btn_sidebar.text() == "Show Panel"
    assert get_language() == "en"
    assert Settings.load().language == "en"
    assert window.analysis._selected_move() == "A4"
    assert "Low sample" in window.analysis.info.text()
    assert "Not searched yet" in window.analysis.table.item(0, 0).toolTip()
    assert not has_chinese(window.analysis.legend.text())
    assert not has_chinese(window.analysis.legend.toolTip())
    window.set_sidebar_expanded(True)
    qtbot.wait(30)
    assert window.analysis.table.verticalScrollBar().maximum() == 0
    assert window.right_scroll.verticalScrollBar().maximum() == 0
    window.language_actions["zh_CN"].trigger()
    assert window.btn_play.text() == "人机对战"
    assert window.analysis._selected_move() == "A4"


def test_language_save_failure_keeps_previous_language(qtbot, monkeypatch):
    window = MainWindow(Settings(), ask=False)
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_save_settings", lambda: False)
    window.language_actions["en"].trigger()
    assert window.settings.language == "zh_CN" and get_language() == "zh_CN"
    assert window.language_actions["zh_CN"].isChecked()
    assert not window.language_actions["en"].isChecked()


def test_english_engine_and_game_messages(qtbot, make_controller):
    controller = make_controller(board_size=9)
    controller.settings.language = "en"
    window = MainWindow(controller.settings, controller=controller, ask=False)
    qtbot.addWidget(window)
    controller.start_engine()
    wait_state(qtbot, controller, State.READY)
    assert window.lbl_state.text() == "Engine: Waiting for a move"
    assert controller.board_play((4, 4))
    qtbot.waitUntil(lambda: controller.state == State.READY and len(controller.game.moves) == 2, timeout=5000)
    assert "Black" in window.moves.item(0).text()
    assert "White" in window.moves.item(1).text()
    assert not has_chinese(window.moves.item(1).text())
    from katago_gui.go.game import GameRecord
    from katago_gui.sgf import SgfError, parse_sgf

    with pytest.raises(ValueError) as invalid:
        GameRecord(size=15)
    assert not has_chinese(str(invalid.value))
    with pytest.raises(SgfError) as invalid:
        parse_sgf("not an SGF")
    assert not has_chinese(str(invalid.value))


def test_language_switch_preserves_running_analysis(qtbot, make_controller):
    controller = make_controller(board_size=9)
    window = MainWindow(controller.settings, controller=controller, ask=False)
    qtbot.addWidget(window)
    controller.start_engine()
    wait_state(qtbot, controller, State.READY)
    window.btn_analysis.click()
    window.analysis.button.click()
    qtbot.waitUntil(lambda: controller.analysis is not None, timeout=5000)
    game = controller.game
    visits = controller.analysis.snapshot.root_visits
    window.language_actions["en"].trigger()
    assert controller.game is game and controller.analysis_enabled
    assert controller.state == State.ANALYZING
    assert window.analysis.button.text() == "Stop Analysis"
    qtbot.waitUntil(lambda: controller.analysis.snapshot.root_visits > visits, timeout=5000)
    window.analysis_action.trigger()
    wait_state(qtbot, controller, State.READY)
    assert window.analysis.button.text() == "Start Analysis"
