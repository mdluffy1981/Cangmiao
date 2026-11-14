from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS = Path(__file__).parent
FAKE = TESTS / "fake_gtp_engine.py"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    from katago_gui.i18n import set_language

    set_language("zh_CN")
    monkeypatch.setenv("KATAGO_GUI_HOME", str(tmp_path / "home"))
    yield tmp_path / "home"
    set_language("zh_CN")


@pytest.fixture
def make_controller(qtbot, monkeypatch):
    from katago_gui.controller import GameController
    from katago_gui.settings import Settings

    made = []

    def factory(behavior: str = "", **game):
        monkeypatch.setenv("FAKE_GTP_BEHAVIOR", behavior)
        s = Settings()
        s.engine.executable = s.engine.model = s.engine.config = str(FAKE)
        for k, v in game.items():
            setattr(s.game, k, v)

        class FakeController(GameController):
            def _launch(self) -> None:
                self.engine.start(sys.executable, ["-u", str(FAKE)], str(TESTS))

        c = FakeController(s)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.engine.kill()


def wait_state(qtbot, ctl, *states, timeout=10000):
    qtbot.waitUntil(lambda: ctl.state in states, timeout=timeout)
