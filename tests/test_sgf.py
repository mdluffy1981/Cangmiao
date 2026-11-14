import pytest

from katago_gui.go.coords import from_gtp
from katago_gui.go.game import GameRecord
from katago_gui.sgf import SgfError, decode_bytes, game_to_sgf, load_sgf, parse_sgf, save_sgf


def make_game():
    g = GameRecord(size=13, rules_key="japanese", komi=6.5, human_color="W")
    for m in ("D4", "K10", "pass", "C3"):
        g.play(g.to_move, None if m == "pass" else from_gtp(m, 13))
    g.set_result("W+R")
    return g


def test_roundtrip(tmp_path):
    g = make_game()
    p = tmp_path / "对局.sgf"
    save_sgf(g, p)
    r = load_sgf(p)
    assert r.warnings == []
    h = r.game
    assert (h.size, h.rules_key, h.komi, h.human_color, h.result) == (13, "japanese", 6.5, "W", "W+R")
    assert [(m.color, m.move) for m in h.moves] == [(m.color, m.move) for m in g.moves]
    assert h.board == g.board and not h.dirty
    text = p.read_text(encoding="utf-8")
    assert "B[]" in text and "PB[KataGo]" in text and "CA[UTF-8]" in text
    assert "AP[Cangmiao:" in text


def test_escape_and_chinese_names():
    g = GameRecord(size=9)
    g.black_name = "张三]\\"
    r = parse_sgf(game_to_sgf(g))
    assert r.game.black_name == "张三]\\"


def test_variations_and_unknown_props_warn():
    r = parse_sgf("(;GM[1]SZ[9]XX[foo];B[ee](;W[cc];B[gg])(;W[dd]))(;SZ[9])")
    assert len(r.game.moves) == 3
    text = " ".join(r.warnings)
    assert "2 局" in text and "变化分支" in text and "XX" in text


def test_tt_pass_and_rules_mapping():
    r = parse_sgf("(;SZ[19]RU[NZ]KM[7];B[tt];W[])")
    assert r.game.rules_key == "new-zealand" and r.game.ended_by_passes
    r = parse_sgf("(;SZ[9]RU[Ing])")
    assert r.game.rules_key == "chinese" and any("Ing" in w for w in r.warnings)


@pytest.mark.parametrize("text,needle", [
    ("(;SZ[15])", "尺寸"),
    ("(;SZ[9:13])", "非正方形"),
    ("(;SZ[9]AB[aa])", "摆子"),
    ("(;SZ[9]HA[2])", "让子"),
    ("(;SZ[9];W[aa])", "不交替"),
    ("(;SZ[9];B[ee];W[ee])", "非法"),
    ("(;SZ[9];B[zz])", "坐标"),
    ("(;SZ[9];B[ee]", "截断"),
    ("(;SZ[9]C[unterminated", "结束符"),
    ("hello", "起始符"),
    ("(;GM[2])", "GM"),
    ("(;SZ[9]KM[abc])", "贴目"),
])
def test_fatal_errors(text, needle):
    with pytest.raises(SgfError) as ei:
        parse_sgf(text)
    assert needle in str(ei.value)


def test_error_location():
    with pytest.raises(SgfError) as ei:
        parse_sgf("(;SZ[9]\n;B[ee]\n;W[ee])")
    assert ei.value.line == 3


def test_decode_gb18030():
    data = "(;CA[GB18030]SZ[9]PB[李四])".encode("gb18030")
    assert "李四" in decode_bytes(data)
    data = "(;SZ[9]PB[王五])".encode("gb18030")
    assert "王五" in decode_bytes(data)


@pytest.mark.parametrize("text", [
    "junk (;SZ[9])", "(;SZ[9]) trailing", "(;SZ[9];B[aa][bb])",
    "(;SZ[9]KM[nan])", "(;SZ[9]KM[inf])", "(;SZ[9]PL[W])",
    "(;SZ[9];B[aa];SZ[13])", "(;SZ[9]FF[5])",
])
def test_corrupt_or_unsupported_semantics_are_rejected(text):
    with pytest.raises(SgfError):
        parse_sgf(text)


@pytest.mark.parametrize("data", [
    b"(;CA[UTF-8]PB[\xff])", b"(;CA[NotAnEncoding])", b"(;PB[\xff])",
])
def test_bad_encoding_is_not_silently_replaced(data):
    with pytest.raises(SgfError):
        decode_bytes(data)


def test_metadata_and_line_continuation_roundtrip():
    r = parse_sgf("(;SZ[9]EV[Test]PB[foo\\\r\nbar]PW[KataGo])")
    again = parse_sgf(game_to_sgf(r.game))
    assert again.game.black_name == "foobar"
    assert "EV[Test]" in game_to_sgf(r.game) or any("EV" in w for w in r.warnings)


def test_unknown_result_does_not_finish_unfinished_game():
    assert not parse_sgf("(;SZ[9]RE[?];B[ee])").game.finished
