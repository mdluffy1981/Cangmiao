import pytest

from katago_gui.go.board import IllegalMove
from katago_gui.go.coords import from_gtp, from_sgf, to_gtp, to_sgf
from katago_gui.go.game import GameRecord


def test_gtp_coords_skip_i():
    assert to_gtp((8, 0), 19) == "J19"
    assert from_gtp("J19", 19) == (8, 0)
    assert from_gtp("a1", 9) == (0, 8)
    assert to_gtp(None, 9) == "pass"
    assert from_gtp("PASS", 9) is None
    with pytest.raises(ValueError):
        from_gtp("Z9", 9)
    with pytest.raises(ValueError):
        from_gtp("A10", 9)


def test_sgf_coords():
    assert to_sgf((2, 3), 19) == "cd"
    assert from_sgf("cd", 19) == (2, 3)
    assert from_sgf("", 19) is None
    assert from_sgf("tt", 19) is None
    with pytest.raises(ValueError):
        from_sgf("jj", 9)


def play(g, *moves):
    for m in moves:
        g.play(g.to_move, None if m == "pass" else from_gtp(m, g.size))


def test_capture_and_suicide():
    g = GameRecord(size=9)
    # Black surrounds white stone at B8 ... build capture of white A9
    play(g, "B9", "A9", "A8")
    assert g.board.get(from_gtp("A9", 9)) == ""
    assert g.board.captures["B"] == 1
    # White playing A9 again would be suicide (single stone)
    with pytest.raises(IllegalMove):
        g.check("W", from_gtp("A9", 9))


def test_simple_ko():
    g = GameRecord(size=9)
    # Classic ko shape around D5/E5
    play(g, "D5", "E5", "C4", "F4", "D3", "E3", "pass", "D4")
    # White D4 is in atari? set up: black E4 captures D4
    play(g, "E4")
    assert g.board.get(from_gtp("D4", 9)) == ""
    # White immediate recapture at D4 is ko
    with pytest.raises(IllegalMove, match="劫"):
        g.check("W", from_gtp("D4", 9))
    play(g, "A1", "A2")  # ko threats elsewhere
    assert g.is_legal("W", from_gtp("D4", 9))


def test_occupied_and_turn():
    g = GameRecord(size=9)
    play(g, "E5")
    with pytest.raises(IllegalMove):
        g.check("W", from_gtp("E5", 9))
    with pytest.raises(IllegalMove):
        g.check("B", from_gtp("A1", 9))


def test_multi_stone_suicide_rules():
    def setup(rules):
        g = GameRecord(size=9, rules_key=rules)
        # Black A9,B9 surrounded by white A8,B8,C9 → black plays to fill own last liberty
        play(g, "A9", "A8", "pass", "B8", "pass", "C9")
        return g

    g = setup("chinese")
    with pytest.raises(IllegalMove):
        g.check("B", from_gtp("B9", 9))
    g = setup("tromp-taylor")
    g.play("B", from_gtp("B9", 9))
    assert g.board.get(from_gtp("A9", 9)) == "" and g.board.captures["W"] == 2


def test_undo_count_and_end_by_passes():
    g = GameRecord(size=9, human_color="B")
    assert g.undo_count_for_human() == 0
    play(g, "E5", "C3")
    assert g.undo_count_for_human() == 2
    play(g, "D4")
    assert g.undo_count_for_human() == 1
    g2 = GameRecord(size=9, human_color="W")
    play(g2, "E5")
    assert g2.undo_count_for_human() == 1  # AI's first move only
    play(g, "pass", "pass")
    assert g.ended_by_passes and g.finished
    g.undo()
    assert not g.finished


def test_invalid_size():
    with pytest.raises(ValueError):
        GameRecord(size=15)
