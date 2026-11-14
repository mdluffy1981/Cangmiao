import pytest

from katago_gui.controller import InteractionMode, State
from katago_gui.engine import launch
from katago_gui.go.coords import from_gtp
from katago_gui.go.game import GameRecord

from conftest import wait_state


def started(qtbot, make_controller, behavior="", **game):
    c = make_controller(behavior, **game)
    c.start_engine()
    wait_state(qtbot, c, State.READY, State.GAME_OVER, State.AI_THINKING)
    wait_state(qtbot, c, State.READY, State.GAME_OVER)
    return c


def test_unconfigured(qtbot, isolated_home):
    from katago_gui.controller import GameController
    from katago_gui.settings import Settings
    c = GameController(Settings())
    msgs = []
    c.error.connect(msgs.append)
    c.start_engine()
    assert c.state == State.UNCONFIGURED and "未配置" in msgs[0]


def test_startup_and_human_ai_round(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    assert c.engine_name.startswith("FakeGo") and c.supports_analysis
    assert c.can_human_play()
    assert c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    assert [m.color for m in c.game.moves] == ["B", "W"]
    assert c.game.moves[1].move == (0, 0)  # fake AI plays first empty point A9


def test_illegal_human_move_rejected_locally(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    msgs = []
    c.message.connect(msgs.append)
    assert not c.human_play(from_gtp("E5", 9))
    assert "非法" in msgs[-1] and len(c.game.moves) == 2


def test_ai_first_when_human_white(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=13, human_color="W")
    assert len(c.game.moves) == 1 and c.game.moves[0].color == "B"
    assert c.can_human_play()


def test_new_game_ai_black(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    assert c.new_game(19, "W", "japanese", 6.5, "fast")
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 1, timeout=5000)
    assert c.game.size == 19 and c.game.moves[0].color == "B" and c.game.komi == 6.5


def test_unconfigured_white_game_opens_once_after_engine_configuration(qtbot, make_controller):
    c = make_controller(board_size=9)
    assert c.new_game(9, "W", "chinese", 7.5, "fast")
    assert not c.game.moves
    c.start_engine(auto_ai_move=False)
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 1, timeout=5000)
    assert c.game.moves[0].color == "B"
    c.restart_engine()
    wait_state(qtbot, c, State.READY)
    assert len(c.game.moves) == 1


def test_undo_round_and_ai_first_move(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    assert c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and not c.game.moves, timeout=5000)
    c2 = started(qtbot, make_controller, board_size=9, human_color="W")
    assert len(c2.game.moves) == 1
    c2.undo()
    qtbot.waitUntil(lambda: c2.state == State.READY and not c2.game.moves, timeout=5000)
    assert c2.can_ai_move()  # AI does not auto-replay after undo
    c2.ai_move()
    qtbot.waitUntil(lambda: c2.state == State.READY and len(c2.game.moves) == 1, timeout=5000)


def test_undo_rejected_keeps_board(qtbot, make_controller):
    c = started(qtbot, make_controller, "reject_second_undo", board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    before = list(c.game.moves)
    errs = []
    c.error.connect(errs.append)
    c.undo()
    qtbot.waitUntil(lambda: bool(errs), timeout=5000)
    wait_state(qtbot, c, State.READY)
    assert c.game.moves == before and "拒绝悔棋" in errs[0]
    # Engine was restored: a further move must still be in sync.
    c.human_play(from_gtp("D4", 9))
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 4, timeout=5000)


def test_double_pass_scores(qtbot, make_controller):
    c = started(qtbot, make_controller, "genmove_pass", board_size=9)
    c.human_pass()
    wait_state(qtbot, c, State.GAME_OVER)
    assert c.game.result == "W+7.5"
    assert c.can_undo() and not c.can_human_play()
    c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and not c.game.moves, timeout=5000)
    assert c.game.result == ""


def test_double_pass_without_score(qtbot, make_controller):
    c = started(qtbot, make_controller, "genmove_pass,fail_final_score", board_size=9)
    c.human_pass()
    wait_state(qtbot, c, State.GAME_OVER)
    assert c.game.result == "" and "未能" in c.game.result_note and c.game.finished


def test_ai_resigns_and_human_resigns(qtbot, make_controller):
    c = started(qtbot, make_controller, "genmove_resign", board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.GAME_OVER)
    assert c.game.result == "B+R"
    c2 = started(qtbot, make_controller, board_size=9)
    assert c2.resign()
    assert c2.state == State.GAME_OVER and c2.game.result == "W+R"


def test_illegal_ai_move_enters_error_and_restart_recovers(qtbot, make_controller, monkeypatch):
    c = started(qtbot, make_controller, "genmove_illegal", board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.ERROR)
    assert "非法" in c.last_error and len(c.game.moves) == 1
    monkeypatch.setenv("FAKE_GTP_BEHAVIOR", "")
    c.restart_engine()
    wait_state(qtbot, c, State.READY)
    assert len(c.game.moves) == 1 and c.can_ai_move()


def test_engine_crash(qtbot, make_controller):
    c = started(qtbot, make_controller, "crash_on_genmove", board_size=9)
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.ERROR)
    assert "退出" in c.last_error and len(c.game.moves) == 1


def test_engine_exit_on_start(qtbot, make_controller):
    c = make_controller("exit_on_start")
    c.start_engine()
    wait_state(qtbot, c, State.ERROR)
    assert "启动失败" in c.last_error and "cannot load model" in c.last_error


def test_search_timeout(qtbot, make_controller, monkeypatch):
    monkeypatch.setattr(launch, "SEARCH_GRACE_S", 0.0)
    c = started(qtbot, make_controller, "slow_genmove", board_size=9, strength="fast")
    c.human_play(from_gtp("E5", 9))
    assert c.state == State.AI_THINKING
    assert not c.human_play(from_gtp("D4", 9))  # repeated input blocked while thinking
    wait_state(qtbot, c, State.ERROR, timeout=8000)
    assert "超时" in c.last_error


def test_analysis_follows_moves_until_stopped(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    results = []
    c.analysis_changed.connect(results.append)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: any(r is not None for r in results), timeout=5000)
    a = c.analysis
    assert a.move_number == 0 and a.black_winrate() == pytest.approx(0.6)
    # Playing while analysing stops analysis first, plays, and then re-analyses the new position.
    assert c.human_play(from_gtp("E5", 9))
    qtbot.waitUntil(lambda: c.state == State.ANALYZING and c.analysis is not None
                    and c.analysis.move_number == 2, timeout=5000)
    assert len(c.game.moves) == 2 and c.analysis_enabled
    c.stop_analysis()
    wait_state(qtbot, c, State.READY)
    assert not c.analysis_enabled
    c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and not c.game.moves, timeout=5000)
    qtbot.wait(150)
    assert c.state == State.READY  # a stopped analysis does not come back by itself


def test_analysis_mode_resumes_after_each_edit(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    commands = []
    c.engine.io_log.connect(commands.append)
    assert c.set_mode(InteractionMode.ANALYSIS)
    assert c.start_analysis()
    for n, move in enumerate(("E5", "D4"), start=1):
        qtbot.waitUntil(lambda: c.state == State.ANALYZING and not c.analysis_stopping, timeout=5000)
        assert c.board_play(from_gtp(move, 9))
        qtbot.waitUntil(lambda n=n: c.analysis is not None and c.analysis.move_number == n, timeout=5000)
    assert any("kata-analyze W 20 maxmoves 30 minmoves 30" in line for line in commands)
    assert not any("genmove" in line for line in commands)
    # Leaving analysis mode turns continuous analysis off.
    assert c.set_mode(InteractionMode.PLAY)
    wait_state(qtbot, c, State.READY)
    qtbot.wait(150)
    assert c.state == State.READY and not c.analysis_enabled and c.analysis is None


def test_when_idle_can_end_analysis(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    assert c.start_analysis()
    ran = []
    assert c.when_idle(lambda: ran.append(True), end_analysis=True)
    qtbot.waitUntil(lambda: ran == [True], timeout=5000)
    qtbot.wait(150)
    assert c.state == State.READY and not c.analysis_enabled


def test_analysis_mode_edits_both_sides_without_genmove(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    commands = []
    c.engine.io_log.connect(commands.append)
    assert c.set_mode(InteractionMode.ANALYSIS)
    for move in ("E5", "D4", "F6"):
        assert c.board_play(from_gtp(move, 9))
        wait_state(qtbot, c, State.READY)
    assert [m.color for m in c.game.moves] == ["B", "W", "B"]
    assert not any("genmove" in line for line in commands)
    assert not c.ai_move()
    assert c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 2, timeout=5000)


def test_analysis_revision_changes_for_same_move_number(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    c.set_mode(InteractionMode.ANALYSIS)
    assert c.board_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: c.analysis is not None, timeout=5000)
    old_revision = c.analysis.revision
    c.stop_analysis()
    wait_state(qtbot, c, State.READY)
    assert c.undo()
    wait_state(qtbot, c, State.READY)
    assert c.board_play(from_gtp("D4", 9))
    wait_state(qtbot, c, State.READY)
    assert c.analysis is None
    assert c.start_analysis()
    qtbot.waitUntil(lambda: c.analysis is not None, timeout=5000)
    assert c.analysis.move_number == 1
    assert c.analysis.revision != old_revision


def test_analysis_runs_until_stopped(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9, strength="fast")
    c.start_analysis()
    wait_state(qtbot, c, State.ANALYZING)
    qtbot.waitUntil(lambda: c.analysis is not None, timeout=5000)
    first = c.analysis.snapshot.root_visits
    qtbot.wait(2500)  # beyond the fast preset's two-second move budget
    assert c.state == State.ANALYZING and c.analysis.snapshot.root_visits > first
    c.stop_analysis()
    wait_state(qtbot, c, State.READY)
    assert c.analysis is not None and c.analysis.snapshot.root_visits >= first


def test_rank_candidates_shows_top_winrates_with_tiers():
    from katago_gui.controller import CandidateTier, rank_candidates
    from katago_gui.engine.gtp import CandidateMove

    def cand(move, winrate, score, visits=10, order=0):
        return CandidateMove(move, visits, winrate, score, 0.1, order, [move])

    # Engine order is by visits; display order must be by side-to-move winrate.
    cands = [cand("A1", 0.50, 1.0, 100, 0), cand("B1", 0.62, 3.0, 50, 1), cand("C1", 0.61, 2.5, 40, 2),
             cand("D1", 0.61, 1.5, 30, 3)]
    cands += [cand(f"E{i}", 0.30 - i / 100, -5.0, 5, 3 + i) for i in range(1, 12)]
    ranked = rank_candidates(cands)
    assert len(ranked) == 10
    assert [r.move.move for r in ranked[:4]] == ["B1", "C1", "D1", "A1"]
    assert [r.rank for r in ranked] == list(range(1, 11))
    assert [r.tier for r in ranked[:4]] == [
        CandidateTier.BEST, CandidateTier.HONTE, CandidateTier.NORMAL, CandidateTier.NORMAL
    ]  # D1 is close in winrate but 1.5 points behind
    assert all(r.tier == CandidateTier.NORMAL for r in ranked[4:])
    assert rank_candidates([]) == []


@pytest.mark.parametrize("winrate, score, expected", [
    (0.58, 1.0, "HONTE"),
    (0.579999, 1.0, "NORMAL"),
    (0.58, 0.999999, "NORMAL"),
])
def test_candidate_tier_includes_exact_boundaries(winrate, score, expected):
    from katago_gui.controller import rank_candidates
    from katago_gui.engine.gtp import CandidateMove
    candidates = [
        CandidateMove("D4", 20, 0.6, 2.0, 0.1, 0, []),
        CandidateMove("C4", 10, winrate, score, 0.1, 1, []),
    ]
    assert rank_candidates(candidates)[1].tier.name == expected


def test_replacing_game_in_another_mode_ends_analysis(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    c.set_mode(InteractionMode.ANALYSIS)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: c.analysis is not None, timeout=5000)
    assert c.replace_game(GameRecord(size=9), mode=InteractionMode.PLAY)
    qtbot.waitUntil(lambda: c.state == State.READY and c.mode == InteractionMode.PLAY, timeout=5000)
    qtbot.wait(100)
    assert not c.analysis_enabled and c.analysis is None


def test_analysis_unsupported(qtbot, make_controller):
    c = started(qtbot, make_controller, "no_analyze", board_size=9)
    errs = []
    c.error.connect(errs.append)
    assert not c.start_analysis()
    assert "不支持" in errs[0]


def test_replace_game_syncs(qtbot, make_controller):
    c = started(qtbot, make_controller, board_size=9)
    g = GameRecord(size=13, human_color="B")
    for m in ("D4", "K10", "C3"):
        g.play(g.to_move, from_gtp(m, 13))
    assert c.replace_game(g)
    wait_state(qtbot, c, State.READY)
    assert c.game is g and c.can_ai_move()
    c.ai_move()
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == 4, timeout=5000)


def test_failed_replace_preserves_interaction_mode(qtbot, make_controller):
    c = started(qtbot, make_controller, "reject_play", board_size=9)
    g = GameRecord(size=9, human_color="B")
    g.play("B", from_gtp("E5", 9))
    g.play("W", from_gtp("D4", 9))
    assert c.replace_game(g, mode=InteractionMode.ANALYSIS)
    wait_state(qtbot, c, State.ERROR)
    assert c.mode == InteractionMode.PLAY
    assert c.game is not g


def test_silent_analysis_keeps_running_until_stopped(qtbot, make_controller):
    c = started(qtbot, make_controller, "silent_analysis", strength="fast")
    c.start_analysis()
    wait_state(qtbot, c, State.ANALYZING)
    qtbot.wait(300)
    assert c.state == State.ANALYZING and c.analysis is None
    c.stop_analysis()
    wait_state(qtbot, c, State.READY, timeout=2000)
    assert c.analysis is None


def test_pending_analysis_action_cannot_be_overwritten(qtbot, make_controller):
    c = started(qtbot, make_controller, "slow_analysis_stop", board_size=9)
    c.start_analysis()
    assert c.human_play((4, 4))
    assert not c.human_play((3, 3))
    qtbot.waitUntil(lambda: c.state == State.ANALYZING and len(c.game.moves) == 2, timeout=5000)
    assert c.game.moves[0].move == (4, 4)
    c.stop_analysis()
    wait_state(qtbot, c, State.READY)


def test_restart_cancels_pending_analysis_action(qtbot, make_controller):
    c = started(qtbot, make_controller, "slow_analysis_stop", board_size=9)
    c.start_analysis()
    c.human_play((4, 4))
    c.restart_engine()
    wait_state(qtbot, c, State.READY)
    c.start_analysis()
    c.stop_analysis()
    wait_state(qtbot, c, State.READY)
    assert not c.game.moves


def test_unacknowledged_move_rolls_back_on_crash(qtbot, make_controller):
    c = started(qtbot, make_controller, "crash_on_play", board_size=9)
    assert c.human_play((4, 4))
    assert len(c.game.moves) == 1  # optimistic display
    wait_state(qtbot, c, State.ERROR)
    assert not c.game.moves and not c.game.dirty


def test_failed_import_keeps_previous_record(qtbot, make_controller):
    c = started(qtbot, make_controller, "reject_play", board_size=9)
    previous = c.game
    imported = GameRecord(size=13)
    imported.play("B", (4, 4))
    imported.play("W", (3, 3))
    c.replace_game(imported)
    wait_state(qtbot, c, State.ERROR)
    assert c.game is previous


def test_search_parameter_failure_is_not_ready(qtbot, make_controller):
    c = make_controller("reject_param")
    c.start_engine()
    wait_state(qtbot, c, State.ERROR)
    assert not c.can_human_play()


def test_analysis_id_mismatch_is_protocol_error(qtbot, make_controller):
    c = started(qtbot, make_controller, "wrong_analysis_id")
    c.start_analysis()
    wait_state(qtbot, c, State.ERROR)
    assert "编号" in c.last_error


def test_new_unconfigured_game_persists_preferences(qtbot):
    from katago_gui.controller import GameController
    from katago_gui.settings import Settings
    c = GameController(Settings())
    assert c.new_game(9, "W", "japanese", 6.5, "fast")
    assert c.settings.game.board_size == 9
    assert c.settings.game.human_color == "W"


def test_startup_timeout_is_explicit(qtbot, make_controller, monkeypatch):
    monkeypatch.setattr(launch, "STARTUP_TIMEOUT_S", 0.05)
    c = make_controller("slow_start")
    c.start_engine()
    wait_state(qtbot, c, State.ERROR, timeout=2000)
    assert "启动失败" in c.last_error and "超时" in c.last_error


def test_missing_executable_is_actionable(qtbot, make_controller, tmp_path):
    c = make_controller()
    c._launch = lambda: c.engine.start(str(tmp_path / "missing.exe"), [], str(tmp_path))
    c.start_engine()
    wait_state(qtbot, c, State.ERROR, timeout=2000)
    assert "无法启动" in c.last_error


@pytest.mark.parametrize("code, hint", [(-1073741515, True), (-1073741511, True), (1, False)])
def test_engine_exit_explains_missing_dll(qtbot, code, hint):
    from PySide6.QtCore import QProcess
    from katago_gui.engine.process import EXITED, GtpEngine
    engine = GtpEngine()
    engine._dead = False
    failures = []
    engine.failed.connect(lambda kind, detail: failures.append((kind, detail)))
    engine._on_finished(code, QProcess.ExitStatus.NormalExit)
    assert failures[0][0] == EXITED
    assert ("运行库（DLL）" in failures[0][1]) == hint
