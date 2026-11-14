from __future__ import annotations

from .i18n import set_language, system_language, tr

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, paths
from .bundled import apply_bundled_engine
from .settings import Settings, SettingsError
from .controller import InteractionMode
from .ui.main_window import MainWindow


def setup_logging() -> None:
    h = RotatingFileHandler(paths.logs_dir() / "katago_gui.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    set_language(system_language())
    try:
        setup_logging()
        settings = Settings.load()
        set_language(settings.language)
        apply_bundled_engine(settings)
    except (OSError, SettingsError) as e:
        QMessageBox.critical(None, tr('启动失败'), tr('{0}\n请修正设置或备份并移走损坏的设置文件，再重新启动。', e))
        return 1
    win = MainWindow(settings)
    win.show()
    sgf_args = [a for a in argv[1:] if a.lower().endswith(".sgf")]
    # Load before starting the engine so the startup sync replays the imported game.
    loaded = bool(sgf_args) and win.load_path(Path(sgf_args[0]), mode=InteractionMode.ANALYSIS)
    win.ctl.start_engine(auto_ai_move=False)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
