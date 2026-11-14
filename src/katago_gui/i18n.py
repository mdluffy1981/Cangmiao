from __future__ import annotations

from PySide6.QtCore import QLocale

from .i18n_core import ENGLISH as CORE_ENGLISH
from .i18n_ui import ENGLISH as UI_ENGLISH

LANGUAGES = ("zh_CN", "en")
_language = "zh_CN"


def system_language() -> str:
    return "zh_CN" if QLocale.system().language() == QLocale.Language.Chinese else "en"


def get_language() -> str:
    return _language


def set_language(language: str) -> None:
    global _language
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    _language = language


def tr(source: str, *args: object) -> str:
    text = source
    if _language == "en":
        text = UI_ENGLISH.get(source, CORE_ENGLISH.get(source, source))
    return text.format(*args) if args else text
