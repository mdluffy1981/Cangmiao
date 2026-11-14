from __future__ import annotations

from dataclasses import dataclass

from ..i18n import tr


@dataclass(frozen=True)
class RuleSet:
    key: str
    label: str
    ko: str  # SIMPLE / SITUATIONAL / POSITIONAL
    multi_stone_suicide: bool
    sgf_name: str
    default_komi: float


RULES: dict[str, RuleSet] = {
    r.key: r
    for r in (
        RuleSet("chinese", "中国规则", "SIMPLE", False, "Chinese", 7.5),
        RuleSet("japanese", "日本规则", "SIMPLE", False, "Japanese", 6.5),
        RuleSet("korean", "韩国规则", "SIMPLE", False, "Korean", 6.5),
        RuleSet("aga", "AGA 规则", "SITUATIONAL", False, "AGA", 7.5),
        RuleSet("new-zealand", "新西兰规则", "SITUATIONAL", True, "NZ", 7.5),
        RuleSet("tromp-taylor", "Tromp-Taylor 规则", "POSITIONAL", True, "Tromp-Taylor", 7.5),
    )
}

_SGF_ALIASES = {
    "chinese": "chinese", "cn": "chinese",
    "japanese": "japanese", "jp": "japanese",
    "korean": "korean", "ko": "korean",
    "aga": "aga",
    "nz": "new-zealand", "new zealand": "new-zealand", "new-zealand": "new-zealand", "newzealand": "new-zealand",
    "tromp-taylor": "tromp-taylor", "tromptaylor": "tromp-taylor", "tromp taylor": "tromp-taylor",
}


def rules_from_sgf(name: str) -> RuleSet | None:
    key = _SGF_ALIASES.get(name.strip().lower())
    return RULES[key] if key else None


def get_rules(key: str) -> RuleSet:
    if key not in RULES:
        raise ValueError(tr("不支持的规则：{0}", key))
    return RULES[key]
