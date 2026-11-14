from __future__ import annotations

from .i18n import LANGUAGES, get_language, tr

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths
from .strength import DEFAULT_PRESET, get_preset
from .go.game import GameRecord


class SettingsError(ValueError):
    pass


@dataclass
class EngineSettings:
    executable: str = ""
    model: str = ""
    config: str = ""

    def missing(self) -> list[str]:
        """Return human-readable descriptions of missing engine files."""
        problems = []
        for label, value in ((tr('KataGo 可执行文件'), self.executable), (tr('模型文件'), self.model), (tr('配置文件'), self.config)):
            if not value:
                problems.append(tr('未设置{0}路径', label))
            elif not Path(value).is_file():
                problems.append(tr('{0}不存在：{1}', label, value))
        return problems


@dataclass
class GameSettings:
    board_size: int = 19
    human_color: str = "B"
    rules: str = "chinese"
    komi: float = 7.5
    strength: str = DEFAULT_PRESET

    def validate(self) -> None:
        GameRecord(self.board_size, self.rules, self.komi, self.human_color)
        get_preset(self.strength)


@dataclass
class Settings:
    engine: EngineSettings = field(default_factory=EngineSettings)
    game: GameSettings = field(default_factory=GameSettings)
    last_sgf_dir: str = ""
    language: str = field(default_factory=get_language)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or paths.settings_file()
        s = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return s
        except (OSError, ValueError) as e:
            raise SettingsError(tr('无法读取设置 {0}：{1}', path, e)) from e
        try:
            if not isinstance(data, dict):
                raise ValueError(tr('设置根节点必须是 JSON 对象'))
            s.language = _string(data, "language", "zh_CN")
            if s.language not in LANGUAGES:
                raise ValueError(tr("不支持的界面语言：{0}", s.language))
            engine = _section(data, "engine")
            game = _section(data, "game")
            s.engine = EngineSettings(_string(engine, "executable", ""),
                                      _string(engine, "model", ""), _string(engine, "config", ""))
            size = game.get("board_size", 19)
            komi = game.get("komi", 7.5)
            if type(size) is not int:
                raise ValueError(tr('board_size 必须是整数'))
            if not isinstance(komi, (int, float)) or isinstance(komi, bool):
                raise ValueError(tr('komi 必须是数值'))
            s.game = GameSettings(size, _string(game, "human_color", "B"),
                                  _string(game, "rules", "chinese"), float(komi),
                                  _string(game, "strength", DEFAULT_PRESET))
            s.game.validate()
            s.last_sgf_dir = _string(data, "last_sgf_dir", "")
            return s
        except (ValueError, OverflowError) as e:
            raise SettingsError(tr('设置无效 {0}：{1}', path, e)) from e

    def save(self, path: Path | None = None) -> None:
        path = path or paths.settings_file()
        self.game.validate()
        if self.language not in LANGUAGES:
            raise ValueError(tr("不支持的界面语言：{0}", self.language))
        path.parent.mkdir(parents=True, exist_ok=True)
        paths.atomic_write_text(path, json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False))


def _section(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(tr('{0} 必须是 JSON 对象', key))
    return value


def _string(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(tr('{0} 必须是字符串', key))
    return value
