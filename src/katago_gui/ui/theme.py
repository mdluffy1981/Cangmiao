COLORS = {
    "window": "#0F0F1A",
    "text": "#E8E8F0",
    "card": "#16213E",
    "border": "#2A2A44",
    "muted": "#B8B8D0",
    "primary": "#4A90D9",
    "secondary": "#1F3460",
    "danger": "#E74C3C",
    "panel": "#1E1E2E",
    "heading": "#89B4FA",
}

# Candidate marks keyed by CandidateTier.name: fill colour and the text colour drawn on it.
CANDIDATE_COLORS = {"BEST": "#34A853", "HONTE": "#F2C94C", "NORMAL": "#4A90D9"}
CANDIDATE_TEXT_COLORS = {"BEST": "#FFFFFF", "HONTE": "#1A1A1A", "NORMAL": "#FFFFFF"}


APP_STYLESHEET = """
QMainWindow, QWidget#appRoot, QDialog {
    background: #0F0F1A;
    color: #E8E8F0;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: 14px;
}
QLabel { color: #E8E8F0; }
QLabel#mutedText { color: #B8B8D0; }
QLabel#sectionTitle { color: #89B4FA; font-size: 16px; font-weight: 600; }
QLabel#metricValue { color: #F5F5FF; font-size: 16px; font-weight: 600; }
QFrame#banner { background: #FFF3CD; border: 1px solid #E0C060; border-radius: 6px; }
QFrame#banner QLabel { color: #4A3500; background: transparent; border: 0; }
QGroupBox, QTabWidget::pane {
    background: #1E1E2E;
    border: 1px solid #2A2A44;
    border-radius: 8px;
    margin-top: 8px;
}
QScrollArea#sideScroll, QWidget#sidePanel {
    background: #0F0F1A;
}
QWidget#mainMenu {
    background: #1E1E2E;
    border: 1px solid #2A2A44;
    border-radius: 8px;
}
QWidget#mainMenu QPushButton { padding: 0 6px; }
QWidget#mainMenu QPushButton:checked {
    background: #4A90D9;
    color: #0F0F1A;
    font-weight: 600;
}
QGroupBox::title {
    color: #89B4FA;
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QPushButton {
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid #2A2A44;
    border-radius: 6px;
    background: #1F3460;
    color: #E8E8F0;
}
QPushButton:hover { background: #29467F; }
QPushButton:focus { border: 2px solid #89B4FA; }
QPushButton:disabled { background: #242438; color: #8A8AA0; }
QPushButton#dangerButton { background: #8F2D2D; }
QPushButton#primaryButton { background: #4A90D9; color: #0F0F1A; font-weight: 600; }
QWidget#sidePanel QPushButton { min-height: 30px; padding: 0 6px; }
QComboBox, QTableWidget, QProgressBar, QListWidget, QLineEdit, QPlainTextEdit, QDoubleSpinBox {
    background: #16213E;
    color: #E8E8F0;
    border: 1px solid #2A2A44;
    selection-background-color: #29467F;
    selection-color: #FFFFFF;
}
QListWidget { alternate-background-color: #1B2849; }
QTableWidget { gridline-color: #2A2A44; }
QComboBox QAbstractItemView {
    background: #16213E;
    color: #E8E8F0;
    selection-background-color: #29467F;
}
QHeaderView::section {
    background: #1F3460;
    color: #E8E8F0;
    border: 0;
    padding: 4px;
}
QTabBar::tab {
    background: #16213E;
    color: #B8B8D0;
    padding: 6px 14px;
}
QTabBar::tab:selected { color: #E8E8F0; background: #1F3460; }
QStatusBar { background: #16213E; color: #C8C8DC; }
QStatusBar QLabel { color: #C8C8DC; }
QStatusBar::item { border: none; }
QMenuBar { background: #16213E; color: #E8E8F0; }
QMenuBar::item { background: transparent; padding: 4px 10px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: #29467F; }
QMenu { background: #16213E; color: #E8E8F0; border: 1px solid #2A2A44; }
QMenu::item { padding: 5px 24px 5px 16px; }
QMenu::item:selected { background: #29467F; }
QMenu::item:disabled { color: #8A8AA0; }
QMenu::separator { height: 1px; background: #2A2A44; margin: 4px 8px; }
QSplitter::handle { background: #2A2A44; }
QScrollBar:vertical {
    background: #16213E;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #4A4A62;
    min-height: 24px;
    border-radius: 5px;
}
"""
