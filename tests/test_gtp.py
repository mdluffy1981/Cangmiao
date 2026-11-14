import pytest

from katago_gui.engine.gtp import GtpParseError, ResponseAssembler, parse_analysis_line, parse_response


def test_parse_response_ok_and_error():
    r = parse_response(["=5 C4"])
    assert r.ok and r.id == 5 and r.text == "C4"
    r = parse_response(["= protocol_version", "name", "version"])
    assert r.ok and r.id is None and r.text.splitlines() == ["protocol_version", "name", "version"]
    r = parse_response(["?3 cannot undo"])
    assert not r.ok and r.error == "cannot undo"
    r = parse_response(["=7"])
    assert r.ok and r.text == ""
    with pytest.raises(GtpParseError):
        parse_response(["garbage"])


def test_assembler_blocks():
    a = ResponseAssembler()
    assert a.feed("noise before\n") is None
    assert a.feed("=1 2\r\n") is None
    assert a.feed("\r\n") == ["=1 2"]
    assert a.feed("\n") is None
    a.feed("= a")
    a.feed("b")
    assert a.feed("") == ["= a", "b"]


REAL_LINE = ("info move C4 visits 93 edgeVisits 93 utility -0.62 winrate 0.192977 scoreMean -0.49 scoreStdev 7.0 "
             "scoreLead -0.497225 scoreSelfplay -1.41 prior 0.0268 lcb 0.16 utilityLcb -0.70 weight 114.2 order 1 "
             "pv C4 D3 F3 info move C6 visits 120 edgeVisits 120 utility -0.6 winrate 0.25 scoreMean 0.1 "
             "scoreLead 0.1 prior 0.2 order 0 pv C6 G4 rootInfo visits 300 utility -0.6 winrate 0.21 scoreLead -0.3")


def test_parse_analysis_line():
    s = parse_analysis_line(REAL_LINE)
    assert s is not None
    assert [c.move for c in s.candidates] == ["C6", "C4"]
    assert s.candidates[1].pv == ["C4", "D3", "F3"]
    assert s.candidates[1].visits == 93
    assert s.candidates[1].score_lead == pytest.approx(-0.497225)
    assert s.root_visits == 300 and s.root_winrate == pytest.approx(0.21)


def test_parse_analysis_without_root():
    s = parse_analysis_line("info move D4 visits 10 winrate 0.5 scoreLead 1 order 0 pv D4")
    assert s.root_visits == 10 and s.root_winrate == 0.5
    assert parse_analysis_line("") is None


@pytest.mark.parametrize("text", [
    "info move D4 visits 10 winrate nan scoreLead 0 prior 0.1 order 0 pv D4",
    "info move D4 visits 10 winrate 1.5 scoreLead 0 prior 0.1 order 0 pv D4",
    "info move D4 visits -1 winrate 0.5 scoreLead 0 prior 0.1 order 0 pv D4",
    "info move D4 visits 10 scoreLead 0 prior 0.1 order 0 pv D4",
    "rootInfo visits 10 winrate inf scoreLead 0",
])
def test_invalid_analysis_cannot_reach_ui(text):
    with pytest.raises(GtpParseError):
        parse_analysis_line(text)
