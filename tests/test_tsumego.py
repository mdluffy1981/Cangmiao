import pytest

from katago_gui.go.coords import from_gtp
from katago_gui.sgf import SgfError
from katago_gui.tsumego import parse_tsumego
from katago_gui.ui.tsumego_page import TsumegoPage


def test_parse_sgf_setup_and_answer_variations():
    problems = parse_tsumego(
        "(;GM[1]SZ[9]GN[Corner]PL[B]AB[aa][ab]AW[bb];B[cc]"
        "(;W[dd];B[ee])(;W[de]))"
    )
    assert len(problems) == 1
    problem = problems[0]
    assert (problem.title, problem.size, problem.to_move) == ("Corner", 9, "B")
    assert problem.board.get((0, 0)) == "B"
    assert problem.board.get((0, 1)) == "B"
    assert problem.board.get((1, 1)) == "W"
    first = problem.root.children[0]
    assert (first.color, first.move) == ("B", (2, 2))
    assert [(step.color, step.move) for step in first.children] == [
        ("W", (3, 3)), ("W", (3, 4))
    ]
    assert first.children[0].children[0].move == (4, 4)


def test_parse_compressed_setup_and_wrong_variation():
    problem = parse_tsumego(
        "(;SZ[9]AB[aa:bb]PL[W];W[cc](;B[dd])(;B[ee]C[Wrong answer]))"
    )[0]
    assert [problem.board.get((x, y)) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))] == [
        "B", "B", "B", "B"
    ]
    answers = problem.root.children[0].children
    assert answers[0].accepted
    assert not answers[1].accepted


@pytest.mark.parametrize("text", [
    "(;SZ[15];B[aa])",
    "(;SZ[9]AB[aa]AW[aa];B[bb])",
    "(;SZ[9];B[])",
    "(;SZ[9]PL[X];B[aa])",
    "(;SZ[9];B[aa]W[bb])",
])
def test_reject_invalid_tsumego_sgf(text):
    with pytest.raises(SgfError):
        parse_tsumego(text)


def test_page_plays_answer_reply_and_persists_progress(qtbot, tmp_path, isolated_home):
    path = tmp_path / "life-and-death.sgf"
    path.write_text(
        "(;SZ[9]GN[Test]PL[B]AB[aa];B[cb](;W[cc];B[dd])(;W[cd]))",
        encoding="utf-8",
    )
    page = TsumegoPage()
    qtbot.addWidget(page)
    page.load_problems(path)
    page._play_point(*from_gtp("C8", 9))
    assert [(move.color, move.move) for move in page.position.moves] == [
        ("B", from_gtp("C8", 9)), ("W", from_gtp("C7", 9))
    ]
    page._play_point(*from_gtp("D6", 9))
    assert page.progress[page._problem_key()] == "correct"
    assert "正解" in page.status_label.text()
    assert (isolated_home / "tsumego_progress.json").is_file()


def test_page_rejects_wrong_move_and_hint_does_not_change_position(qtbot, tmp_path):
    path = tmp_path / "puzzle.sgf"
    path.write_text("(;SZ[9]PL[B];B[bb];W[cc])", encoding="utf-8")
    page = TsumegoPage()
    qtbot.addWidget(page)
    page.load_problems(path)
    before = page.position.board
    page._hint()
    assert page.position.board == before
    assert "提示" in page.status_label.text()
    page._play_point(*from_gtp("C8", 9))
    assert page.position.board == before
    assert "不正确" in page.status_label.text()


def test_main_window_has_independent_tsumego_mode(qtbot, make_controller):
    from katago_gui.controller import InteractionMode
    from katago_gui.ui.main_window import MainWindow

    controller = make_controller(board_size=9)
    window = MainWindow(controller.settings, controller=controller, ask=False)
    qtbot.addWidget(window)
    window.btn_tsumego.click()
    assert window.content_stack.currentWidget() is window.tsumego_page
    assert window.btn_tsumego.isChecked()
    assert controller.mode == InteractionMode.PLAY
    window.btn_analysis.click()
    assert window.content_stack.currentWidget() is window.split
    assert controller.mode == InteractionMode.ANALYSIS
    assert window.btn_analysis.isChecked()
    assert not window.btn_tsumego.isChecked()
