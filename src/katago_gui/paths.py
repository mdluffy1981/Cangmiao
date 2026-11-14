from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    path = path.resolve()
    stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def app_home() -> Path:
    override = os.environ.get("KATAGO_GUI_HOME")
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(local) / "KataGoDesktop"
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_file() -> Path:
    return app_home() / "settings.json"


def logs_dir() -> Path:
    p = app_home() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_engine_dir() -> Path:
    return app_home() / "engine"


def engine_work_dir() -> Path:
    p = app_home() / "engine_work"
    p.mkdir(parents=True, exist_ok=True)
    return p
