from __future__ import annotations

from ..i18n import tr

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import paths
from ..go.rules import RULES, get_rules
from ..settings import EngineSettings, GameSettings
from ..strength import PRESETS, get_preset

SETUP_HELP = (
    "需要三个文件：KataGo 可执行文件（katago.exe）、神经网络模型（*.bin.gz）和 GTP 配置文件（*.cfg）。\n\n"
    "自动安装（推荐，在项目目录运行）：\n"
    "    python -m katago_gui.setup_engine            # GPU（OpenCL）\n"
    "    python -m katago_gui.setup_engine --backend cuda  # NVIDIA CUDA（需安装 CUDA 12.5 与 cuDNN 9）\n"
    "    python -m katago_gui.setup_engine --backend eigenavx2   # 仅 CPU\n\n"
    "手动安装：从 https://github.com/lightvector/KataGo/releases 下载 Windows 版 KataGo，"
    "从 https://katagotraining.org/networks/ 下载模型，并使用压缩包内的 default_gtp.cfg。"
)


class NewGameDialog(QDialog):
    def __init__(self, gs: GameSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr('新建棋局'))
        form = QFormLayout()
        self.size = QComboBox()
        for n in (9, 13, 19):
            self.size.addItem(tr('{0} 路', n), n)
        self.size.setCurrentIndex([9, 13, 19].index(gs.board_size) if gs.board_size in (9, 13, 19) else 2)
        self.color = QComboBox()
        self.color.addItem(tr('执黑（先行）'), "B")
        self.color.addItem(tr('执白（AI 先行）'), "W")
        self.color.setCurrentIndex(0 if gs.human_color == "B" else 1)
        self.rules = QComboBox()
        for r in RULES.values():
            self.rules.addItem(tr(r.label), r.key)
        self.rules.setCurrentIndex(list(RULES).index(get_rules(gs.rules).key))
        self.komi = QDoubleSpinBox()
        self.komi.setRange(-150, 150)
        self.komi.setSingleStep(0.5)
        self.komi.setDecimals(1)
        self.komi.setValue(gs.komi)
        self.rules.currentIndexChanged.connect(lambda _i: self.komi.setValue(get_rules(self.rules.currentData()).default_komi))
        self.strength = QComboBox()
        for p in PRESETS.values():
            self.strength.addItem(tr(p.label), p.key)
        self.strength.setCurrentIndex(list(PRESETS).index(get_preset(gs.strength).key))
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.strength.currentIndexChanged.connect(self._update_desc)
        self._update_desc()
        form.addRow(tr('棋盘'), self.size)
        form.addRow(tr('玩家执色'), self.color)
        form.addRow(tr('规则'), self.rules)
        form.addRow(tr('贴目'), self.komi)
        form.addRow(tr('AI 强度'), self.strength)
        form.addRow("", self.desc)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _update_desc(self) -> None:
        self.desc.setText(get_preset(self.strength.currentData()).describe())

    def values(self) -> tuple[int, str, str, float, str]:
        k = self.komi.value()
        k = round(k * 2) / 2
        return self.size.currentData(), self.color.currentData(), self.rules.currentData(), k, self.strength.currentData()


def detect_engine_files(base: Path) -> EngineSettings:
    es = EngineSettings()
    if not base.is_dir():
        return es
    executables = list(base.rglob("katago.exe"))
    models = list(base.rglob("*.bin.gz"))
    if len(executables) > 1 or len(models) > 1:
        raise ValueError(tr('默认目录中存在多个引擎或模型，请用“浏览”明确选择后端和模型'))
    exe = executables[0] if executables else None
    model = models[0] if models else None
    cfg = base / "gtp.cfg"
    if not cfg.is_file():
        cfg = next(base.rglob("default_gtp.cfg"), None)
    es.executable = str(exe) if exe else ""
    es.model = str(model) if model else ""
    es.config = str(cfg) if cfg else ""
    return es


class EngineSettingsDialog(QDialog):
    def __init__(self, es: EngineSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr('引擎设置'))
        self.resize(720, 420)
        self.exe = QLineEdit(es.executable)
        self.model = QLineEdit(es.model)
        self.config = QLineEdit(es.config)
        form = QFormLayout()
        for label, edit, filt in ((tr('KataGo 程序'), self.exe, tr('程序 (*.exe);;所有文件 (*)')),
                                  (tr('模型文件'), self.model, tr('模型 (*.bin.gz *.bin *.txt.gz);;所有文件 (*)')),
                                  (tr('配置文件'), self.config, tr('配置 (*.cfg);;所有文件 (*)'))):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            b = QPushButton(tr('浏览…'))
            b.clicked.connect(lambda _c=False, e=edit, f=filt: self._browse(e, f))
            row.addWidget(b)
            form.addRow(label, row)
        detect = QPushButton(tr('从默认目录检测（{0}）', paths.default_engine_dir()))
        detect.clicked.connect(self._detect)
        self.status = QLabel()
        self.status.setWordWrap(True)
        help_box = QPlainTextEdit(tr(SETUP_HELP))
        help_box.setReadOnly(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(detect)
        lay.addWidget(self.status)
        lay.addWidget(help_box, 1)
        lay.addWidget(bb)
        for e in (self.exe, self.model, self.config):
            e.textChanged.connect(self._validate)
        self._validate()

    def _browse(self, edit: QLineEdit, filt: str) -> None:
        start = str(Path(edit.text()).parent) if edit.text() else str(paths.default_engine_dir())
        f, _ = QFileDialog.getOpenFileName(self, tr('选择文件'), start, filt)
        if f:
            edit.setText(str(Path(f)))

    def _detect(self) -> None:
        try:
            es = detect_engine_files(paths.default_engine_dir())
        except (OSError, ValueError) as e:
            self.status.setText(tr('检测失败：{0}', e))
            return
        for e, v in ((self.exe, es.executable), (self.model, es.model), (self.config, es.config)):
            if v:
                e.setText(v)
        self._validate()

    def _validate(self) -> None:
        problems = self.result_settings().missing()
        self.status.setText(tr('✔ 三个文件均已找到') if not problems else "⚠ " + "；".join(problems))

    def result_settings(self) -> EngineSettings:
        return EngineSettings(self.exe.text().strip().strip('"'), self.model.text().strip().strip('"'),
                              self.config.text().strip().strip('"'))


class LogDialog(QDialog):
    def __init__(self, lines: list[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr('引擎日志'))
        self.resize(800, 500)
        t = QPlainTextEdit("\n".join(lines))
        t.setReadOnly(True)
        t.moveCursor(t.textCursor().MoveOperation.End)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr('完整日志文件：{0}', paths.logs_dir() / 'katago_gui.log')))
        lay.addWidget(t)
