"""Real KataGo acceptance tests; opt in with KATAGO_RUN_REAL_TESTS=1."""
import json
import os
import re
from pathlib import Path

import pytest

from katago_gui.controller import GameController, InteractionMode, State
from katago_gui.go.coords import from_gtp
from katago_gui.go.rules import RULES
from katago_gui.settings import EngineSettings, Settings
from katago_gui.sgf import load_sgf, save_sgf

from conftest import wait_state


def _real_engine() -> EngineSettings | None:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "KataGoDesktop"
    f = Path(os.environ.get("KATAGO_GUI_HOME", str(local))) / "settings.json"
    if not f.is_file():
        return None
    data = json.loads(f.read_text(encoding="utf-8")).get("engine", {})
    es = EngineSettings(data.get("executable", ""), data.get("model", ""), data.get("config", ""))
    return None if es.missing() else es


REAL = _real_engine() if os.environ.get("KATAGO_RUN_REAL_TESTS") == "1" else None
pytestmark = [pytest.mark.real_engine, pytest.mark.skipif(
    REAL is None, reason="需配置 KataGo 并设置 KATAGO_RUN_REAL_TESTS=1")]

START_TIMEOUT = 900_000


@pytest.fixture
def real_controller(qtbot):
    made = []

    def factory(size=9, human="B"):
        assert REAL is not None
        s = Settings()
        s.engine = REAL
        s.game.board_size, s.game.human_color, s.game.strength = size, human, "fast"
        c = GameController(s)
        made.append(c)
        c.start_engine()
        wait_state(qtbot, c, State.READY, timeout=START_TIMEOUT)
        return c

    yield factory
    for c in made:
        c.shutdown()


def command(qtbot, c, text):
    replies = []
    c.engine.send(text, replies.append, timeout_s=60)
    qtbot.waitUntil(lambda: bool(replies), timeout=65000)
    assert replies[0].ok, replies[0].text
    return replies[0].text


def assert_engine_board(qtbot, c):
    text = command(qtbot, c, "showboard")
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(\d+)\s+([.XO+* 0-9]+)", line)
        if match:
            stones = re.findall(r"[.XO+*]", match[2])
            assert len(stones) == c.game.size
            assert int(match[1]) == c.game.size - len(rows)
            rows.append(tuple({"X": "B", "O": "W"}.get(v, "") for v in stones))
    assert tuple(rows) == c.game.board.grid, text


@pytest.mark.parametrize("size", [9, 13, 19])
@pytest.mark.parametrize("human", ["B", "W"])
def test_real_play(qtbot, real_controller, size, human):
    c = real_controller(size, human)
    assert "KataGo" in c.engine_name and c.supports_analysis
    if human == "W":
        assert len(c.game.moves) == 1 and c.game.moves[0].color == "B"
    for _ in range(2):
        mv = next((x, y) for y in range(size) for x in range(size) if c.game.is_legal(c.game.human_color, (x, y))
                  and x in (2, 3, 4, 5) and y in (2, 3, 4, 5))
        assert c.human_play(mv)
        wait_state(qtbot, c, State.READY, State.GAME_OVER, timeout=60_000)
    n = len(c.game.moves)
    assert n == (4 if human == "B" else 5)
    assert_engine_board(qtbot, c)
    c.undo()
    qtbot.waitUntil(lambda: c.state == State.READY and len(c.game.moves) == n - 2, timeout=10_000)
    assert_engine_board(qtbot, c)


def test_real_analysis_illegal_and_sgf(qtbot, real_controller, tmp_path):
    c = real_controller(9, "B")
    c.human_play(from_gtp("E5", 9))
    wait_state(qtbot, c, State.READY, timeout=60_000)
    occupied = c.game.moves[1].move
    assert not c.human_play(occupied)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.snapshot.root_visits > 50, timeout=20_000)
    wr = c.analysis.black_winrate()
    assert 0.0 <= wr <= 1.0 and c.analysis.snapshot.candidates
    # Move while analysing: analysis stops, move is played, AI replies, then analysis resumes.
    mv = next(p for p in [(2, 2), (6, 6), (2, 6), (6, 2)] if c.game.is_legal("B", p))
    assert c.human_play(mv)
    qtbot.waitUntil(lambda: c.state == State.ANALYZING and c.analysis is not None
                    and c.analysis.move_number == 4, timeout=60_000)
    assert len(c.analysis.snapshot.candidates) <= 30
    c.stop_analysis()
    wait_state(qtbot, c, State.READY, timeout=30_000)

    p = tmp_path / "real.sgf"
    save_sgf(c.game, p)
    loaded = load_sgf(p).game
    assert c.replace_game(loaded)
    wait_state(qtbot, c, State.READY, timeout=30_000)
    c.human_pass()
    wait_state(qtbot, c, State.READY, State.GAME_OVER, timeout=60_000)
    assert len(c.game.moves) >= 5


def test_real_rules_and_presets(qtbot, real_controller):
    from katago_gui.strength import PRESETS
    c = real_controller()
    for key, rules in RULES.items():
        c.new_game(9, "B", key, rules.default_komi, "fast")
        wait_state(qtbot, c, State.READY, timeout=30000)
        actual = json.loads(command(qtbot, c, "kata-get-rules"))
        assert actual["ko"] == rules.ko, (key, actual)
        assert actual["suicide"] == rules.multi_stone_suicide, (key, actual)
        assert float(command(qtbot, c, "get_komi")) == rules.default_komi
    for key, preset in PRESETS.items():
        c.set_strength(key)
        wait_state(qtbot, c, State.READY)
        assert int(command(qtbot, c, "kata-get-param maxVisits")) == preset.max_visits
        assert float(command(qtbot, c, "kata-get-param maxTime")) == preset.max_time


def test_real_continuous_analysis_candidates_and_resume(qtbot, real_controller):
    c = real_controller(19)
    commands = []
    results = []
    c.engine.io_log.connect(commands.append)
    c.analysis_changed.connect(lambda r: results.append(r) if r is not None else None)
    assert c.set_mode(InteractionMode.ANALYSIS)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.elapsed >= 6.0, timeout=30_000)
    first = c.analysis
    assert first is not None and first.snapshot.root_visits > 32
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.elapsed > first.elapsed + 2.0
                    and c.analysis.snapshot.root_visits > first.snapshot.root_visits, timeout=15_000)
    latest = c.analysis
    assert latest is not None and c.state == State.ANALYZING and c.analysis_enabled
    assert len(results) >= 5
    assert all(len(r.snapshot.candidates) == 30 for r in results)
    top = latest.ranked_candidates()
    assert len(top) == 10
    assert [r.move.winrate for r in top] == sorted(
        (m.winrate for m in latest.snapshot.candidates), reverse=True
    )[:10]
    assert c.board_play(from_gtp("D4", 19))
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.move_number == 1, timeout=30_000)
    assert c.analysis.to_move == "W" and len(c.analysis.snapshot.candidates) == 30
    assert c.undo()
    qtbot.waitUntil(lambda: c.analysis is not None and c.analysis.move_number == 0
                    and c.analysis.revision != latest.revision, timeout=30_000)
    assert c.analysis_enabled and c.state == State.ANALYZING
    assert sum("kata-analyze" in line for line in commands) == 3
    assert not any("genmove" in line for line in commands)
    c.stop_analysis()
    wait_state(qtbot, c, State.READY, timeout=30_000)
    count = len(results)
    qtbot.wait(500)
    assert not c.analysis_enabled and len(results) == count
    print(f"Continuous search: {first.snapshot.root_visits} -> {latest.snapshot.root_visits} visits "
          f"after {latest.elapsed:.1f}s; 30 candidates/report, top 10 ranked; move/undo resumed; stop stayed off")


def test_real_opening_live_winrate_warnings(qtbot, real_controller):
    from katago_gui.ui.analysis_panel import AnalysisPanel, LOW_CANDIDATE_VISITS, LOW_ROOT_VISITS

    c = real_controller(19)
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    reports = []

    def show(r):
        if r is None:
            panel.set_result(None, len(c.game.moves))
            return
        panel.set_result(r, len(c.game.moves))
        low = r.snapshot.root_visits < LOW_ROOT_VISITS
        assert ("*" in panel.winrates.text()) == low
        assert panel.bar.value() == int(r.black_winrate() * 1000)
        for row, rc in enumerate(r.ranked_candidates()):
            marker = "*" if rc.move.visits < LOW_CANDIDATE_VISITS else ""
            assert panel.table.item(row, 2).text() == f"{rc.move.winrate * 100:.1f}%{marker}"
        reports.append(r)

    c.analysis_changed.connect(show)
    assert c.set_mode(InteractionMode.ANALYSIS)
    assert c.start_analysis()
    qtbot.waitUntil(lambda: bool(reports) and reports[-1].snapshot.root_visits >= LOW_ROOT_VISITS, timeout=120_000)
    assert any(r.snapshot.root_visits < LOW_ROOT_VISITS for r in reports)
    assert any(m.visits == 0 for r in reports for m in r.snapshot.candidates)
    assert c.board_play(from_gtp("D4", 19))
    qtbot.waitUntil(lambda: reports[-1].move_number == 1, timeout=60_000)
    assert c.undo()
    qtbot.waitUntil(lambda: reports[-1].move_number == 0 and reports[-1].revision > 1, timeout=60_000)
    c.stop_analysis()
    wait_state(qtbot, c, State.READY, timeout=30_000)
    assert panel.result == reports[-1]


def test_real_complete_game_and_restore(qtbot, real_controller, tmp_path):
    c = real_controller(9)
    command(qtbot, c, "kata-set-param allowResignation false")
    for _ in range(250):
        move = command(qtbot, c, f"kata-search {c.game.to_move}")
        assert move.lower() != "resign"
        assert c.human_play(from_gtp(move, 9))
        wait_state(qtbot, c, State.READY, State.GAME_OVER, timeout=60000)
        assert_engine_board(qtbot, c)
        if c.game.finished:
            break
    assert c.state == State.GAME_OVER and c.game.ended_by_passes
    assert c.game.result and not c.game.result_note
    path = tmp_path / "complete.sgf"
    save_sgf(c.game, path)
    loaded = load_sgf(path)
    assert not loaded.warnings
    moves, result = list(c.game.moves), c.game.result
    c.new_game(13, "B", "chinese", 7.5, "fast")
    wait_state(qtbot, c, State.READY, timeout=30000)
    c.replace_game(loaded.game)
    wait_state(qtbot, c, State.GAME_OVER, timeout=60000)
    assert c.game.moves == moves and c.game.result == result
    assert_engine_board(qtbot, c)
    print(f"Complete 9x9 game: {len(moves)} moves, result {result}; SGF restored")
