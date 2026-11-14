"""Auto-configure the KataGo engine shipped next to the packaged executable."""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from .settings import EngineSettings, Settings

log = logging.getLogger(__name__)

PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
CPU_BACKENDS = ("eigenavx2", "eigen")


def bundle_root() -> Path | None:
    """Engine directory of a frozen (installed) build, or None when running from source."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent / "engine"


def configure_bundle_home(executable: str | Path, environ: MutableMapping[str, str] | None = None) -> bool:
    """Isolate flavor-specific settings so one Cangmiao install cannot override another."""
    environ = os.environ if environ is None else environ
    root = Path(executable).resolve().parent / "engine"
    if environ.get("KATAGO_GUI_HOME"):
        return False
    flavor = next((name for marker, name in (
        ("CUDA-NOTICE.txt", "CangmiaoCUDA"),
        ("MODEL-NOTICE.txt", "CangmiaoTiny"),
    ) if (root / marker).is_file()), None)
    if flavor is None:
        return False
    local = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    environ["KATAGO_GUI_HOME"] = str(Path(local) / flavor)
    return True


def cpu_has_avx2() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE))
    except (AttributeError, OSError):
        return False


def bundled_engine(root: Path, avx2: bool) -> EngineSettings | None:
    """Pick the bundled CUDA or best CPU build; None if the bundle is incomplete."""
    config = root / "gtp.cfg"
    model = next(iter(sorted(root.glob("*.bin.gz"))), None)
    if model is None or not config.is_file():
        return None
    backends = ("cuda",) if (root / "CUDA-NOTICE.txt").is_file() else (
        CPU_BACKENDS if avx2 else CPU_BACKENDS[1:]
    )
    for backend in backends:
        exe = root / backend / "katago.exe"
        if exe.is_file():
            return EngineSettings(str(exe), str(model), str(config))
    return None


def apply_bundled_engine(settings: Settings, root: Path | None = None, avx2: bool | None = None) -> bool:
    """Point unconfigured or broken engine settings at the bundled engine and save. Returns True if changed."""
    root = bundle_root() if root is None else root
    if root is None or not settings.engine.missing():
        return False
    engine = bundled_engine(root, cpu_has_avx2() if avx2 is None else avx2)
    if engine is None:
        log.warning("bundled engine incomplete under %s", root)
        return False
    settings.engine = engine
    settings.save()
    log.info("configured bundled engine %s", engine.executable)
    return True
