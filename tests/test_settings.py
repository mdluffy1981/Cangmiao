import json

import pytest

from katago_gui.settings import Settings


@pytest.mark.parametrize("data", [
    "[]", "{", '{"game":{"board_size":15}}', '{"game":{"human_color":"X"}}',
    '{"game":{"rules":"unknown"}}', '{"game":{"komi":"bad"}}',
    '{"game":{"komi":NaN}}', '{"game":{"strength":"unknown"}}',
    '{"engine":{"model":null}}', '{"game":{"board_size":9.1}}',
])
def test_bad_settings_are_reported_without_overwriting(tmp_path, data):
    path = tmp_path / "settings.json"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)
    assert path.read_text(encoding="utf-8") == data


def test_settings_roundtrip_and_first_launch(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings.load(path)
    s.game.board_size, s.game.human_color = 9, "W"
    s.save(path)
    assert Settings.load(path) == s
    assert json.loads(path.read_text(encoding="utf-8"))["game"]["board_size"] == 9


def test_failed_atomic_save_preserves_original(tmp_path, monkeypatch):
    from pathlib import Path
    from katago_gui.sgf import save_sgf
    from katago_gui.go.game import GameRecord
    path = tmp_path / "original.sgf"
    path.write_text("original", encoding="utf-8")

    def fail_replace(self, target):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        save_sgf(GameRecord(size=9), path)
    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [path]
