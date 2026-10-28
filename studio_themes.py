"""Presentation-only themes for the desktop studio."""

from string import Template


THEMES = {
    "new_gen": {
        "label": "New Gen", "font": "Segoe UI", "background": "#101720", "text": "#e7edf5",
        "muted": "#9aaec2", "accent": "#52dbc2", "panel": "#182330", "border": "#293a4c",
        "panel_radius": "8", "radius": "5", "value": "#e7edf5", "value_weight": "600",
        "button": "#263748", "button_text": "#e7edf5", "button_hover": "#344b60",
        "bevel_light": "#354d63", "bevel_dark": "#354d63", "disabled": "#65778a",
        "disabled_background": "#182330", "primary": "#42d3b5", "primary_text": "#092721",
        "primary_hover": "#65e2c8", "input": "#1e2d3c", "input_text": "#e7edf5",
        "input_border": "#395168", "tab": "#17222e", "header": "#223344", "header_text": "#adc1d4",
        "track": "#314358", "handle_radius": "7", "plot": "#15212d", "plot_text": "#c5d4e3",
        "grid": "#2a3c4e", "axis": "#849db4", "reference": "#8b9eb1",
        "speed": "#52dbc2", "pressure": "#73adff", "afr": "#f3bf68", "progress_fill": "#285c53",
    },
    "retro": {
        "label": "Retro", "font": "Consolas", "background": "#252622", "text": "#eee6ce",
        "muted": "#bebbaa", "accent": "#f0be59", "panel": "#30312a", "border": "#686a5c",
        "panel_radius": "0", "radius": "0", "value": "#ffd37c", "value_weight": "700",
        "button": "#c7c5b9", "button_text": "#24251f", "button_hover": "#e0ddcf",
        "bevel_light": "#eeebdd", "bevel_dark": "#74766a", "disabled": "#aaa99b",
        "disabled_background": "#44463d", "primary": "#efbe60", "primary_text": "#26251a",
        "primary_hover": "#ffda8b", "input": "#171b14", "input_text": "#f5cf80",
        "input_border": "#747565", "tab": "#36382f", "header": "#c0beb0", "header_text": "#25271f",
        "track": "#595c4e", "handle_radius": "0", "plot": "#181d14", "plot_text": "#e3d9bb",
        "grid": "#343e2a", "axis": "#b5b49a", "reference": "#a4a588",
        "speed": "#f0be59", "pressure": "#a9c77a", "afr": "#8dc8cb", "progress_fill": "#625534",
    },
    "simple": {
        "label": "Simple", "font": "Segoe UI", "background": "#f4f5f7", "text": "#233044",
        "muted": "#546176", "accent": "#2463b4", "panel": "#ffffff", "border": "#c8d0dc",
        "panel_radius": "3", "radius": "3", "value": "#192b45", "value_weight": "600",
        "button": "#ffffff", "button_text": "#233044", "button_hover": "#e8edf5",
        "bevel_light": "#c8d0dc", "bevel_dark": "#c8d0dc", "disabled": "#8993a2",
        "disabled_background": "#e8ecf1", "primary": "#2463b4", "primary_text": "#ffffff",
        "primary_hover": "#1b5096", "input": "#ffffff", "input_text": "#233044",
        "input_border": "#aab7c8", "tab": "#e8edf3", "header": "#e8edf4", "header_text": "#34445c",
        "track": "#ccd5e1", "handle_radius": "6", "plot": "#ffffff", "plot_text": "#233044",
        "grid": "#e0e6ee", "axis": "#546176", "reference": "#77869a",
        "speed": "#157d68", "pressure": "#2863b9", "afr": "#ac6111", "progress_fill": "#b4d0f2",
    },
}


def stylesheet(theme_id):
    return Template("""
QWidget { background: $background; color: $text; font-family: '$font'; font-size: 13px; }
QMainWindow { background: $background; }
QLabel#muted { color: $muted; }
QLabel#eyebrow { color: $accent; font-weight: 700; font-size: 11px; }
QLabel#title { font-size: 27px; font-weight: 700; }
QLabel#sectionTitle { font-size: 16px; font-weight: 700; }
QFrame#panel { background: $panel; border: 1px solid $border; border-radius: ${panel_radius}px; }
QFrame#panel QLabel { background: transparent; }
QLabel#value { color: $value; font-size: 31px; font-weight: $value_weight; }
QPushButton { background: $button; color: $button_text; border: 1px solid $bevel_dark;
    border-top-color: $bevel_light; border-left-color: $bevel_light;
    border-radius: ${radius}px; padding: 9px 17px; }
QPushButton:hover { background: $button_hover; }
QPushButton:pressed { border-top-color: $bevel_dark; border-bottom-color: $bevel_light; padding-top: 10px; padding-bottom: 8px; }
QPushButton:disabled { background: $disabled_background; color: $disabled; border-color: $border; }
QPushButton#primary { background: $primary; color: $primary_text; font-weight: 700; border: 1px solid $primary; }
QPushButton#primary:hover { background: $primary_hover; border-color: $primary_hover; }
QPushButton#primary:disabled { background: $disabled_background; color: $disabled; border-color: $border; }
QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QComboBox, QDoubleSpinBox, QLineEdit { background: $input; color: $input_text; border: 1px solid $input_border;
    border-radius: ${radius}px; padding: 7px; selection-background-color: $accent; selection-color: $background; }
QPlainTextEdit { background: $input; color: $input_text; border: 1px solid $input_border; padding: 8px;
    selection-background-color: $accent; selection-color: $background; }
QSplitter::handle { background: $border; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: $disabled; border-color: $border; }
QComboBox QAbstractItemView { background: $input; color: $input_text; border: 1px solid $input_border;
    selection-background-color: $accent; selection-color: $background; outline: none; }
QTabWidget::pane { border: 1px solid $border; top: -1px; }
QTabBar::tab { background: $tab; padding: 12px 24px; color: $muted; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }
QTabBar::tab:hover { color: $text; }
QTableWidget { background: $panel; gridline-color: $border; border: 1px solid $border;
    selection-background-color: $accent; selection-color: $background; }
QHeaderView::section { background: $header; color: $header_text; padding: 9px; border: 0; }
QTableCornerButton::section { background: $header; border: 0; }
QSlider::groove:horizontal { background: $track; height: 5px; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: 15px; margin: -5px 0; border-radius: ${handle_radius}px; }
QSlider::handle:horizontal:focus { border: 1px solid $text; }
QSlider::handle:horizontal:disabled { background: $disabled; }
QProgressBar { background: $input; color: $text; border: 1px solid $border; border-radius: ${radius}px;
    text-align: center; min-height: 19px; }
QProgressBar::chunk { background: $progress_fill; }
QScrollArea { border: 1px solid $border; }
QScrollBar:vertical { background: $tab; width: 13px; margin: 0; }
QScrollBar:horizontal { background: $tab; height: 13px; margin: 0; }
QScrollBar::handle { background: $track; min-height: 22px; min-width: 22px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: $tab; }
QToolTip { background: $panel; color: $text; border: 1px solid $border; padding: 5px; }
QStatusBar { color: $muted; }
""").substitute(THEMES[theme_id])
