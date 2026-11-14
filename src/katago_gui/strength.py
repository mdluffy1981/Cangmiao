from __future__ import annotations

from dataclasses import dataclass

from .i18n import tr


@dataclass(frozen=True)
class StrengthPreset:
    key: str
    label: str
    max_visits: int
    max_time: float

    def describe(self) -> str:
        return tr(
            "对局预算：每手 {0} 次访问 / {1:g} 秒。实际棋力取决于模型和硬件，不对应固定段位。",
            self.max_visits, self.max_time,
        )


PRESETS: dict[str, StrengthPreset] = {
    p.key: p
    for p in (
        StrengthPreset("fast", "快速", 32, 2.0),
        StrengthPreset("standard", "标准", 200, 5.0),
        StrengthPreset("strong", "较强", 800, 10.0),
        StrengthPreset("max", "最强", 3000, 20.0),
    )
}

DEFAULT_PRESET = "standard"


def get_preset(key: str) -> StrengthPreset:
    if key not in PRESETS:
        raise ValueError(tr("不支持的思考强度：{0}", key))
    return PRESETS[key]
