"""Virtual ECU Studio: desktop front end for documented engine experiments."""

import argparse
import copy
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / ".deps" / "desktop").is_dir():
    sys.path.insert(0, str(ROOT / ".deps" / "desktop"))

if "--smoke-test" in sys.argv or "--research-smoke-test" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QProcess, QTimer, Qt, QRectF, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QTableWidget, QTableWidgetItem,
    QTabBar, QTabWidget, QVBoxLayout, QWidget)

from ecu_bench import FuelMap, Protocol, run_experiment, write_json
from engine_dynamics import Inputs, Parameters
from fuel_dynamics import (FuelParameters, advance, default_config, observe,
                            validate_map_domain, validate_scenario)
from run_fuel_dynamics import export_suite
from studio_themes import THEMES, stylesheet
from ai_panel import AssistantPanel


def label(text, object_name=None):
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    return widget


class TracePlot(QWidget):
    """Small live trace widget; stored CSV remains the research data source."""
    def __init__(self, title, key, color, parent=None, reference=None):
        super().__init__(parent)
        self.title, self.key, self.color = title, key, QColor(color)
        self.samples = []
        self.theme = THEMES["new_gen"]
        self.reference = reference
        self.setMinimumHeight(160)

    def set_theme(self, theme):
        self.theme = theme
        self.color = QColor(theme[{"rpm": "speed", "map_kpa": "pressure", "afr": "afr"}[self.key]])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self.theme["plot"]))
        painter.setFont(QFont(self.theme["font"], 9))
        painter.setPen(QColor(self.theme["plot_text"]))
        painter.drawText(16, 25, self.title)
        box = QRectF(65, 44, max(1, self.width()-90), max(1, self.height()-78))
        data = self.samples
        values = [s[self.key] for s in data] or [0, 1]
        if self.reference is not None:
            values = [*values, self.reference]
        low, high = min(values), max(values)
        margin = max((high-low)*0.15, abs(high)*0.025, 0.5)
        low, high = low-margin, high+margin
        last_time = max(5.0, data[-1]["time_s"] if data else 5.0)
        for index in range(5):
            y = box.top() + box.height()*index/4
            painter.setPen(QColor(self.theme["grid"]))
            painter.drawLine(int(box.left()), int(y), int(box.right()), int(y))
            painter.setPen(QColor(self.theme["axis"]))
            painter.drawText(QRectF(0, y-9, 57, 18), Qt.AlignmentFlag.AlignRight, f"{high-(high-low)*index/4:.1f}")
        painter.drawText(int(box.left()), self.height()-12, "0 s")
        painter.drawText(int(box.right()-55), self.height()-12, f"{last_time:.1f} s")
        if self.reference is not None:
            y = box.bottom() - (self.reference-low)/(high-low)*box.height()
            painter.setPen(QPen(QColor(self.theme["reference"]), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(box.left()), int(y), int(box.right()), int(y))
            painter.drawText(self.width()-110, 25, f"Target {self.reference:g}")
        if len(data) > 1:
            path = QPainterPath()
            for index, sample in enumerate(data):
                x = box.left() + sample["time_s"]/last_time*box.width()
                y = box.bottom() - (sample[self.key]-low)/(high-low)*box.height()
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(self.color, 2.2))
            painter.drawPath(path)


class Studio(QMainWindow):
    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = Path(settings_path) if settings_path else ROOT/".local/appearance.json"
        self.theme_id = "new_gen"
        try:
            preference = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(preference, dict) and preference.get("theme") in THEMES:
                self.theme_id = preference["theme"]
        except (OSError, ValueError, TypeError):
            pass
        self.setWindowTitle("Virtual ECU Studio")
        self.resize(1200, 860)
        self.setMinimumSize(1000, 760)
        self.config = default_config()
        self.parameters = Parameters(**self.config["parameters"])
        self.fuel_parameters = FuelParameters(**self.config["fuel_parameters"])
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.saved_paths = []
        self.baseline = FuelMap.from_dict(json.loads((ROOT / "maps" / "baseline.json").read_text()))
        self.map_presets = [FuelMap.from_dict(json.loads((ROOT / "maps" / name).read_text(encoding="utf-8")))
                            for name in ("dynamic_plus_10_percent.json", "dynamic_baseline.json", "dynamic_minus_10_percent.json")]
        self.candidate = self.map_presets[0]
        self.pending_fuel_map = self.map_presets[1]
        self.active_fuel_map = self.pending_fuel_map
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(25, 20, 25, 16)
        layout.setSpacing(14)
        layout.addWidget(label("VIRTUAL ECU  /  LOCAL SIMULATION", "eyebrow"))
        titlebar = QHBoxLayout()
        titlebar.addWidget(label("Engine tuning studio", "title"), 1)
        titlebar.addWidget(label("Theme", "muted"))
        self.theme_choice = QComboBox()
        self.theme_choice.setMinimumWidth(145)
        self.theme_choice.setAccessibleName("Appearance theme")
        self.theme_choice.setToolTip("Change appearance. Your choice is remembered for the next launch.")
        for theme_id, theme in THEMES.items():
            self.theme_choice.addItem(theme["label"], theme_id)
        self.theme_choice.setCurrentIndex(self.theme_choice.findData(self.theme_id))
        self.theme_choice.currentIndexChanged.connect(lambda _: self.apply_theme(self.theme_choice.currentData()))
        titlebar.addWidget(self.theme_choice)
        layout.addLayout(titlebar)
        layout.addWidget(label("Synthetic telemetry · uncalibrated research model · no vehicle connection", "muted"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.build_dashboard()
        self.build_maps()
        self.build_history()
        self.build_experiments()
        self.assistant = AssistantPanel(self.assistant_snapshot, self.load_assistant_proposal,
                                        settings_path=self.settings_path.with_name("assistant.json"))
        self.tabs.addTab(self.assistant, "AI Assistant")
        self.tabs.currentChanged.connect(self.tab_changed)
        self.setCentralWidget(container)
        self.reset()
        self.refresh_history()
        studies = sorted((ROOT/"results/research").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if studies:
            self.load_research(studies[0].parent)
        self.apply_theme(self.theme_id, persist=False)
        QApplication.instance().installEventFilter(self)

    def apply_theme(self, theme_id, persist=True):
        if theme_id not in THEMES:
            return
        self.theme_id = theme_id
        theme = THEMES[theme_id]
        app = QApplication.instance()
        palette = QPalette()
        for role, key in ((QPalette.ColorRole.Window, "background"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "input"), (QPalette.ColorRole.AlternateBase, "panel"),
                          (QPalette.ColorRole.Text, "input_text"), (QPalette.ColorRole.Button, "button"),
                          (QPalette.ColorRole.ButtonText, "button_text"), (QPalette.ColorRole.Highlight, "accent"),
                          (QPalette.ColorRole.HighlightedText, "background"), (QPalette.ColorRole.ToolTipBase, "panel"),
                          (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.PlaceholderText, "muted")):
            palette.setColor(role, QColor(theme[key]))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme["disabled"]))
        app.setPalette(palette)
        app.setFont(QFont(theme["font"], 10))
        app.setStyleSheet(stylesheet(theme_id))
        for plot in (self.speed_plot, self.pressure_plot, self.afr_plot):
            plot.set_theme(theme)
        if persist:
            try:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.settings_path.with_suffix(".tmp")
                write_json(temporary, {"schema": "studio_appearance_v1", "theme": theme_id})
                temporary.replace(self.settings_path)
                self.statusBar().showMessage(f"Theme: {theme['label']} · preference saved", 3500)
            except OSError:
                self.statusBar().showMessage("Theme applied; preference could not be saved.", 5000)
        self.refresh_research_figure()

    def tab_changed(self, index):
        if self.tabs.widget(index) is self.assistant and not self.assistant.ready:
            self.assistant.connect_local()

    def assistant_snapshot(self, source):
        from datetime import datetime, timezone
        from fuel_dynamics import MODEL_VERSION
        from run_fuel_dynamics import metrics
        snapshot = {"schema": "ecu_assistant_snapshot_v1", "model_version": MODEL_VERSION,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(), "data_origin": "synthetic_simulation",
            "source": source, "scenario": self.scenario["name"], "sample_count": len(self.samples),
            "engine_parameters": asdict(self.parameters), "fuel_parameters": asdict(self.fuel_parameters),
            "active_map": self.active_fuel_map.to_dict(), "editor_map": self.edited_map().to_dict(),
            "telemetry": observe(self.state, self.current_inputs(), self.parameters, self.fuel_parameters,
                                 self.active_fuel_map, self.tick_count*self.config["integration_step_s"]),
            "recent_samples": copy.deepcopy(self.samples[-3:]),
            "limits": "Uncalibrated air/speed/fuel simulator; ignition and real-engine validation are absent."}
        if len(self.samples) > 1:
            scenario = {**self.scenario, "fuel_map": self.active_fuel_map.to_dict(), "events": self.recorded_events}
            snapshot["run_metrics"] = metrics(self.samples, scenario, self.parameters, self.fuel_parameters)
        if source == "study":
            if not self.study_directory:
                raise ValueError("Load a study in Experiments first")
            from local_ai import study_summary
            snapshot["study"] = study_summary(self.study_directory)
            for key in ("model_version", "engine_parameters", "fuel_parameters"):
                snapshot[key] = snapshot["study"][key]
            # A study question must not inherit unrelated live-run readings.
            for key in ("telemetry", "recent_samples", "run_metrics", "sample_count", "scenario", "active_map"):
                snapshot.pop(key, None)
        elif source != "dashboard":
            raise ValueError("Unknown assistant context source")
        return snapshot

    def load_assistant_proposal(self, proposal, base):
        if self.edited_map() != base:
            raise ValueError("The editor changed after the request. Ask for a fresh proposal.")
        validate_map_domain(proposal, self.parameters)
        self.candidate = proposal
        blocked = self.map_preset_choice.blockSignals(True)
        self.map_preset_choice.setCurrentIndex(-1)
        self.map_preset_choice.setPlaceholderText("AI proposal")
        self.map_preset_choice.blockSignals(blocked)
        for row, values in enumerate(proposal.values):
            for column, value in enumerate(values):
                self.map_table.cellWidget(row, column).setValue(value)
        self.fuel_result.setText("AI proposal loaded for review. Use on next run queues it; Dashboard > Reset applies it.")
        self.tabs.setCurrentIndex(1)

    def build_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("Operating scenario"))
        self.scenario_choice = QComboBox()
        self.scenario_choice.addItems(["Manual bench", "Steady idle", "Throttle step", "Load step"])
        self.scenario_choice.setMinimumWidth(190)
        self.scenario_choice.currentIndexChanged.connect(self.reset)
        toolbar.addWidget(self.scenario_choice)
        toolbar.addStretch()
        self.start_button = QPushButton("Start simulation")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        toolbar.addWidget(self.start_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause)
        toolbar.addWidget(self.pause_button)
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(self.reset)
        toolbar.addWidget(reset_button)
        self.export_button = QPushButton("Save run")
        self.export_button.clicked.connect(self.save_run)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)
        cards = QHBoxLayout()
        self.card_values = {}
        for title, key, unit in (("ENGINE SPEED", "rpm", "RPM"), ("MANIFOLD PRESSURE", "map_kpa", "kPa absolute"),
                                 ("CYLINDER AIR FLOW", "cylinder_air_g_s", "g/s"),
                                 ("AIR / FUEL RATIO", "afr", "g air / g fuel"),
                                 ("MODEL NET TORQUE", "net_torque_nm", "Nm")):
            panel = QFrame()
            panel.setObjectName("panel")
            inner = QVBoxLayout(panel)
            inner.setContentsMargins(17, 13, 17, 13)
            inner.addWidget(label(title, "muted"))
            value = label("0", "value")
            inner.addWidget(value)
            inner.addWidget(label(unit, "muted"))
            self.card_values[key] = value
            cards.addWidget(panel)
        layout.addLayout(cards)
        controls = QHBoxLayout()
        self.throttle_slider = QSlider(Qt.Orientation.Horizontal)
        self.throttle_slider.setRange(0, 1000)
        self.throttle_slider.setSingleStep(10)
        self.throttle_slider.setToolTip("Drag or use Up / Down: 1% per press. Hold a key to repeat.")
        self.load_slider = QSlider(Qt.Orientation.Horizontal)
        self.load_slider.setRange(0, 600)
        self.load_slider.setSingleStep(10)
        self.load_slider.setToolTip("Drag or use Right / Left: 1 Nm per press. Hold a key to repeat.")
        self.throttle_readout = label("")
        self.load_readout = label("")
        for title, slider, readout in (("Throttle  ↑ / ↓", self.throttle_slider, self.throttle_readout),
                                       ("External load  ← / →", self.load_slider, self.load_readout)):
            column = QVBoxLayout()
            header = QHBoxLayout()
            header.addWidget(label(title))
            header.addStretch()
            header.addWidget(readout)
            column.addLayout(header)
            column.addWidget(slider)
            controls.addLayout(column, 1)
        self.throttle_slider.valueChanged.connect(self.controls_changed)
        self.load_slider.valueChanged.connect(self.controls_changed)
        layout.addLayout(controls)
        self.map_status = label("", "muted")
        self.map_status.setWordWrap(True)
        layout.addWidget(self.map_status)
        self.speed_plot = TracePlot("Engine speed / RPM", "rpm", "#52dbc2")
        self.pressure_plot = TracePlot("Manifold absolute pressure / kPa", "map_kpa", "#73adff")
        self.afr_plot = TracePlot("Air / fuel ratio", "afr", "#f3bf68", reference=self.fuel_parameters.afr_target)
        plots = QHBoxLayout()
        plots.addWidget(self.speed_plot, 1)
        plots.addWidget(self.pressure_plot, 1)
        plots.addWidget(self.afr_plot, 1)
        layout.addLayout(plots, 1)
        self.run_info = label("", "muted")
        layout.addWidget(self.run_info)
        layout.addWidget(label("AFR and torque are simulated. The mixture-to-torque relationship is an uncalibrated assumption.", "muted"))
        self.tabs.addTab(page, "Dashboard")

    def eventFilter(self, watched, event):
        # Keep mapping independent of which slider/button has focus. Allow
        # normal navigation in combo boxes, tab bars, editors and popups.
        if (event.type() == QEvent.Type.KeyPress
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and self.isActiveWindow()
                and self.tabs.currentIndex() == 0
                and self.scenario_choice.currentIndex() == 0
                and QApplication.activePopupWidget() is None
                and not isinstance(QApplication.focusWidget(), (QComboBox, QTabBar, QLineEdit))):
            actions = {
                Qt.Key.Key_Up: (self.throttle_slider, 10),
                Qt.Key.Key_Down: (self.throttle_slider, -10),
                Qt.Key.Key_Right: (self.load_slider, 10),
                Qt.Key.Key_Left: (self.load_slider, -10),
            }
            action = actions.get(event.key())
            if action is not None:
                slider, change = action
                slider.setValue(slider.value() + change)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def build_maps(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("Fuel correction map", "title"))
        description = label("Dimensionless fuel multipliers. Rows: MAP / kPa. Columns: RPM.\n"
                            "Queue a map, then Dashboard > Reset > Start. The map stays fixed throughout each run.", "muted")
        description.setWordWrap(True)
        layout.addWidget(description)
        presets = QHBoxLayout()
        presets.addWidget(label("Editor preset"))
        self.map_preset_choice = QComboBox()
        self.map_preset_choice.addItems(["+10% fuel", "Baseline", "-10% fuel"])
        self.map_preset_choice.currentIndexChanged.connect(self.load_map_preset)
        presets.addWidget(self.map_preset_choice)
        presets.addStretch()
        layout.addLayout(presets)
        self.map_table = QTableWidget(len(self.candidate.map_kpa_axis), len(self.candidate.rpm_axis))
        self.map_table.setHorizontalHeaderLabels([f"{x:g} RPM" for x in self.candidate.rpm_axis])
        self.map_table.setVerticalHeaderLabels([f"{x:g} kPa" for x in self.candidate.map_kpa_axis])
        self.map_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.map_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, values in enumerate(self.candidate.values):
            for column, value in enumerate(values):
                editor = QDoubleSpinBox()
                editor.setRange(0.5, 1.5)
                editor.setDecimals(3)
                editor.setSingleStep(0.01)
                editor.setValue(value)
                editor.valueChanged.connect(self.map_changed)
                self.map_table.setCellWidget(row, column, editor)
        self.map_table.setMinimumHeight(210)
        layout.addWidget(self.map_table)
        buttons = QHBoxLayout()
        save_map_button = QPushButton("Save map as…")
        save_map_button.clicked.connect(self.save_map)
        buttons.addWidget(save_map_button)
        apply_button = QPushButton("Use on next run")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.queue_dashboard_map)
        buttons.addWidget(apply_button)
        run_button = QPushButton("Run fixed-point check")
        run_button.clicked.connect(self.run_fuel_comparison)
        buttons.addWidget(run_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.fuel_result = label("Fixed-point check: 3000 RPM, 60 kPa, 20 g/s air. The active dashboard map is shown on the Dashboard.", "muted")
        self.fuel_result.setWordWrap(True)
        layout.addWidget(self.fuel_result)
        layout.addStretch()
        self.tabs.addTab(page, "Fuel maps")

    def build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("Saved experiments", "title"))
        layout.addWidget(label("Every saved experiment includes telemetry, configuration and source snapshots.", "muted"))
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Model", "Experiment ID", "Runs"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history_table)
        buttons = QHBoxLayout()
        open_button = QPushButton("Open selected report")
        open_button.clicked.connect(self.open_selected_report)
        buttons.addWidget(open_button)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_history)
        buttons.addWidget(refresh)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.tabs.addTab(page, "Run history")

    def build_experiments(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addWidget(label("Controlled experiments", "title"))
        explanation = label("Compare three fuel maps under matched inputs. Sensitivity varies one assumption at a time; ranges are deterministic, not confidence intervals.", "muted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        toolbar = QHBoxLayout()
        self.study_choice = QComboBox()
        self.study_choice.addItem("Sensitivity: 63 conditions + 2 replay checks", "sensitivity")
        self.study_choice.addItem("Nominal pilot: 9 conditions + 2 replay checks", "nominal")
        toolbar.addWidget(self.study_choice, 1)
        self.study_start = QPushButton("Run study")
        self.study_start.setObjectName("primary")
        self.study_start.clicked.connect(lambda: self.start_research())
        toolbar.addWidget(self.study_start)
        self.study_cancel = QPushButton("Cancel")
        self.study_cancel.setEnabled(False)
        self.study_cancel.clicked.connect(self.cancel_research)
        toolbar.addWidget(self.study_cancel)
        layout.addLayout(toolbar)
        self.study_progress = QProgressBar()
        self.study_progress.setRange(0, 63)
        self.study_progress.setValue(0)
        layout.addWidget(self.study_progress)
        self.study_status = label("Ready. The plan and source snapshot are saved before simulation starts.", "muted")
        self.study_status.setWordWrap(True)
        layout.addWidget(self.study_status)
        buttons = QHBoxLayout()
        self.study_report = QPushButton("Open report")
        self.study_report.clicked.connect(lambda: self.open_research_file("report.md"))
        buttons.addWidget(self.study_report)
        self.study_folder = QPushButton("Open results / PNG / PDF")
        self.study_folder.clicked.connect(lambda: self.open_research_file(""))
        buttons.addWidget(self.study_folder)
        self.study_load = QPushButton("Load saved study")
        self.study_load.clicked.connect(self.choose_research)
        buttons.addWidget(self.study_load)
        self.figure_choice = QComboBox()
        for title, name in (("AFR and RPM traces", "nominal_traces"), ("RPM sensitivity ranges", "sensitivity_ranges"),
                            ("ECU estimate and AFR error", "ecu_estimate_sweep")):
            self.figure_choice.addItem(title, name)
        self.figure_choice.currentIndexChanged.connect(self.refresh_research_figure)
        buttons.addWidget(self.figure_choice, 1)
        layout.addLayout(buttons)
        self.figure_scroll = QScrollArea()
        self.figure_scroll.setWidgetResizable(True)
        self.figure_preview = label("Saved research figures will appear here.", "muted")
        self.figure_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figure_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.figure_scroll.setWidget(self.figure_preview)
        layout.addWidget(self.figure_scroll, 1)
        self.study_directory = None
        self.figure_source = None
        self.study_buffer = ""
        self.study_cancelled = False
        self.study_complete = False
        self.study_process = QProcess(self)
        self.study_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.study_process.readyReadStandardOutput.connect(self.read_research_output)
        self.study_process.finished.connect(self.research_finished)
        self.study_process.errorOccurred.connect(self.research_process_error)
        self.study_report.setEnabled(False)
        self.study_folder.setEnabled(False)
        self.tabs.addTab(page, "Experiments")

    def start_research(self, output_root=None):
        if self.study_process.state() != QProcess.ProcessState.NotRunning:
            return
        self.study_directory = None
        self.study_buffer = ""
        self.study_last_message = ""
        self.study_cancelled = self.study_complete = False
        self.study_progress.setRange(0, 63 if self.study_choice.currentData() == "sensitivity" else 9)
        self.study_progress.setValue(0)
        self.study_status.setText("Starting study and preparing plotting environment…")
        self.study_running_controls(True)
        self.study_report.setEnabled(False)
        self.study_folder.setEnabled(False)
        interpreter = Path(sys.executable)
        if os.name == "nt" and interpreter.with_name("pythonw.exe").is_file():
            interpreter = interpreter.with_name("pythonw.exe")
        self.study_process.setWorkingDirectory(str(ROOT))
        self.study_process.start(str(interpreter), ["-u", "-X", "utf8", str(ROOT/"research_study.py"),
            "--mode", self.study_choice.currentData(), "--output-dir", str(output_root or ROOT/"results/research"),
            "--json-progress"])

    def study_running_controls(self, running):
        for widget in (self.study_start, self.study_choice, self.study_load):
            widget.setEnabled(not running)
        self.study_cancel.setEnabled(running)

    def read_research_output(self):
        self.study_buffer += bytes(self.study_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.study_buffer:
            line, self.study_buffer = self.study_buffer.split("\n", 1)
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                self.study_last_message = line.strip()
                continue
            kind = event.get("event")
            if kind == "started":
                self.study_directory = Path(event["directory"])
                self.study_progress.setMaximum(event["total"])
                self.study_status.setText("Plan saved. Running matched conditions…")
            elif kind == "progress":
                self.study_progress.setValue(event["done"])
                self.study_status.setText(f"{event['done']} / {event['total']} · {event['case']} · {event['scenario']} · failures: {event['failures']}")
            elif kind == "rendering":
                self.study_status.setText("Simulations complete. Exporting three PNG and three PDF figures…")
            elif kind == "complete":
                self.study_complete = True
            elif kind == "error":
                self.study_last_message = event["message"]

    def cancel_research(self):
        if self.study_process.state() != QProcess.ProcessState.NotRunning:
            self.study_cancelled = True
            self.study_status.setText("Cancelling; completed condition files will be kept.")
            self.study_process.kill()

    def research_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.study_running_controls(False)
            self.study_status.setText("Could not start study: " + self.study_process.errorString())

    def research_finished(self, exit_code, _exit_status):
        self.read_research_output()
        self.study_running_controls(False)
        if self.study_directory:
            if self.study_cancelled or exit_code != 0 or not self.study_complete:
                from research_study import mark_interrupted
                mark_interrupted(self.study_directory, "cancelled" if self.study_cancelled else "failed")
            self.load_research(self.study_directory)
        if self.study_cancelled:
            self.study_status.setText("Cancelled. Completed conditions and the partial report have been kept.")
        elif exit_code != 0 or not self.study_complete:
            self.study_status.setText("Study failed: " + (self.study_last_message or self.study_buffer.strip() or "see saved report"))
        self.refresh_history()

    def choose_research(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose saved study folder", str(ROOT/"results/research"))
        if directory:
            self.load_research(Path(directory))

    def load_research(self, directory):
        try:
            manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
            if "study_version" not in manifest:
                raise ValueError("Choose a controlled-study folder containing study_plan.json.")
            self.study_directory = directory
            self.study_progress.setRange(0, manifest["expected_conditions"])
            self.study_progress.setValue(len(manifest["runs"])+len(manifest["failures"]))
            repeats = sum(r["matches"] for r in manifest["repeat_checks"])
            self.study_status.setText(f"{manifest['status']} · {len(manifest['runs'])}/{manifest['expected_conditions']} conditions · {len(manifest['failures'])} failures · {repeats}/{len(manifest['repeat_checks'])} replay checks matched. Synthetic data.")
            self.study_report.setEnabled((directory/"report.md").is_file())
            self.study_folder.setEnabled(True)
            self.refresh_research_figure()
        except (OSError, ValueError, KeyError) as error:
            self.study_status.setText("Cannot load study: " + str(error))

    def refresh_research_figure(self, *_):
        path = self.study_directory/"figures"/(self.figure_choice.currentData()+".png") if self.study_directory else None
        self.figure_source = QPixmap(str(path)) if path and path.is_file() else None
        if self.figure_source and not self.figure_source.isNull():
            width = max(300, self.figure_scroll.viewport().width()-18)
            preview = self.figure_source.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
            self.figure_preview.setPixmap(preview)
            self.figure_preview.setMinimumHeight(preview.height())
        else:
            self.figure_preview.clear()
            self.figure_preview.setMinimumHeight(100)
            self.figure_preview.setText("No exported figure available for this study.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "figure_choice"):
            self.refresh_research_figure()

    def open_research_file(self, name):
        if self.study_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.study_directory/name)))

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.assistant.shutdown()
        if self.study_process.state() != QProcess.ProcessState.NotRunning:
            self.study_cancel_research_on_close()
        super().closeEvent(event)

    def study_cancel_research_on_close(self):
        self.cancel_research()
        self.study_process.waitForFinished(3000)

    def controls_changed(self):
        self.throttle_readout.setText(f"{self.throttle_slider.value()/10:.1f} %")
        self.load_readout.setText(f"{self.load_slider.value()/10:.1f} Nm")

    def reset(self, *_):
        self.timer.stop()
        self.tick_count = 0
        self.samples = []
        self.recorded_events = []
        self.selected = self.scenario_choice.currentIndex()
        self.scenario = copy.deepcopy(self.config["scenarios"][max(0, self.selected-1)])
        self.active_fuel_map = self.pending_fuel_map
        self.scenario["fuel_map"] = self.active_fuel_map.to_dict()
        if self.selected == 0:
            self.scenario["name"] = "manual_bench"
            self.scenario["duration_s"] = 30.0
        self.state, self.stride, self.total_ticks, _ = validate_scenario(
            self.scenario, self.parameters, self.config["integration_step_s"], self.config["sampling_rate_hz"])
        self.initial_state = self.state
        first = self.scenario["events"][0]
        self.throttle_slider.setValue(round(first["throttle"] * 1000))
        self.load_slider.setValue(round(first["load_nm"] * 10))
        self.throttle_slider.setEnabled(self.selected == 0)
        self.load_slider.setEnabled(self.selected == 0)
        self.start_button.setText("Start simulation")
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.display(observe(self.state, Inputs(first["throttle"], first["load_nm"]), self.parameters,
                             self.fuel_parameters, self.active_fuel_map))
        self.update_map_status()
        self.statusBar().showMessage("Ready · simulation time 0.00 s")

    def current_inputs(self):
        if self.selected == 0:
            return Inputs(self.throttle_slider.value()/1000, self.load_slider.value()/10)
        time_s = self.tick_count * self.config["integration_step_s"]
        event = self.scenario["events"][0]
        for candidate in self.scenario["events"]:
            if candidate["time_s"] <= time_s:
                event = candidate
        return Inputs(event["throttle"], event["load_nm"])

    def record_sample(self, inputs):
        time_s = self.tick_count * self.config["integration_step_s"]
        event = {"time_s": time_s, "throttle": inputs.throttle, "load_nm": inputs.load_nm}
        if not self.recorded_events or any(self.recorded_events[-1][key] != event[key] for key in ("throttle", "load_nm")):
            self.recorded_events.append(event)
        sample = observe(self.state, inputs, self.parameters, self.fuel_parameters, self.active_fuel_map, time_s)
        if self.samples and self.samples[-1]["time_s"] == time_s:
            self.samples[-1] = sample
        else:
            self.samples.append(sample)
        return sample

    def start(self):
        if self.tick_count >= self.total_ticks:
            return
        self.record_sample(self.current_inputs())
        self.timer.start()
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)

    def pause(self):
        self.timer.stop()
        self.start_button.setText("Resume")
        self.start_button.setEnabled(self.tick_count < self.total_ticks)
        self.pause_button.setEnabled(False)
        self.statusBar().showMessage(f"Paused · simulation time {self.tick_count*self.config['integration_step_s']:.2f} s")

    def tick(self):
        try:
            # One reporting interval per callback. Input events are held over the
            # following internal steps; simulation time is independent of GUI latency.
            inputs = self.current_inputs()
            self.record_sample(inputs)
            for _ in range(self.stride):
                if self.tick_count >= self.total_ticks:
                    break
                self.state = advance(self.state, inputs, self.parameters, self.fuel_parameters,
                                     self.active_fuel_map, self.config["integration_step_s"])
                self.tick_count += 1
            inputs = self.current_inputs()
            sample = self.record_sample(inputs)
            if self.selected:
                self.throttle_slider.setValue(round(inputs.throttle*1000))
                self.load_slider.setValue(round(inputs.load_nm*10))
            self.display(sample)
            self.export_button.setEnabled(len(self.samples) >= 2)
            self.statusBar().showMessage(f"Running · simulation time {sample['time_s']:.2f} s")
            if self.tick_count >= self.total_ticks:
                self.pause()
                self.statusBar().showMessage("Run complete · use Save run to archive it")
        except ValueError as error:
            self.pause()
            self.statusBar().showMessage(str(error))
            self.start_button.setEnabled(False)
            QMessageBox.warning(self, "Model domain reached", f"{error}\nReset to begin a new run.")

    def display(self, sample):
        for key, widget in self.card_values.items():
            widget.setText(f"{sample[key]:,.0f}" if key == "rpm" else f"{sample[key]:.2f}")
        for plot in (self.speed_plot, self.pressure_plot, self.afr_plot):
            plot.samples = self.samples
            plot.update()
        self.run_info.setText(f"Simulation {sample['time_s']:.2f} s  /  {len(self.samples)} samples  /  "
                              "integration 1 ms  /  reporting 50 Hz")

    def archive_current(self, output_root=None):
        if len(self.samples) < 2:
            raise ValueError("Run the simulation before saving")
        scenario = {"name": self.scenario["name"], "duration_s": self.samples[-1]["time_s"],
                    "operating_scenario": self.scenario.get("operating_scenario", self.scenario["name"]),
                    "condition": self.active_fuel_map.name,
                    "fuel_map": self.active_fuel_map.to_dict(),
                    "initial": {"rpm": self.initial_state.rpm, "map_kpa": self.initial_state.pressure_pa/1000,
                                "fuel_mass_flow_kg_s": self.initial_state.fuel_mass_flow_kg_s},
                    "events": copy.deepcopy(self.recorded_events)}
        config = {**copy.deepcopy(self.config), "scenarios": [scenario]}
        return export_suite(output_root or ROOT / "results" / "desktop", config, [self.samples], origin="desktop")

    def save_run(self):
        self.pause()
        try:
            directory = self.archive_current()
            self.statusBar().showMessage(f"Saved {directory}")
            self.refresh_history()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Could not save run", str(error))

    def edited_map(self):
        values = tuple(tuple(self.map_table.cellWidget(row, column).value()
                             for column in range(self.map_table.columnCount())) for row in range(self.map_table.rowCount()))
        name = self.candidate.name if values == self.candidate.values else "desktop_edited_map"
        return FuelMap(name, self.candidate.rpm_axis, self.candidate.map_kpa_axis, values)

    def load_map_preset(self, index):
        self.candidate = self.map_presets[index]
        for row, values in enumerate(self.candidate.values):
            for column, value in enumerate(values):
                self.map_table.cellWidget(row, column).setValue(value)
        self.fuel_result.setText("Editor preset loaded. Use on next run queues it for the next Dashboard reset.")

    def map_changed(self, *_):
        self.fuel_result.setText("Editor changed. Use on next run queues this version; run the fixed-point check again for updated results.")

    def queue_dashboard_map(self):
        self.pending_fuel_map = self.edited_map()
        validate_map_domain(self.pending_fuel_map, self.parameters)
        self.update_map_status()
        self.fuel_result.setText(f"Queued {self.pending_fuel_map.name}. Dashboard > Reset > Start simulation applies it. "
                                "The current recording keeps its original map.")

    def update_map_status(self):
        text = f"Current fuel map: {self.active_fuel_map.name}"
        if self.pending_fuel_map != self.active_fuel_map:
            text += f"  |  Queued for next Reset: {self.pending_fuel_map.name}"
        self.map_status.setText(text)

    def save_map(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save fuel map", str(ROOT / "maps" / "custom_map.json"), "JSON (*.json)")
        if path:
            try:
                write_json(Path(path), self.edited_map().to_dict())
                self.fuel_result.setText(f"Map saved: {path}")
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "Could not save map", str(error))

    def run_fuel_comparison(self, output_root=None):
        # QPushButton emits a boolean, which must not be mistaken for a path.
        if isinstance(output_root, bool):
            output_root = None
        directory = run_experiment(output_root or ROOT / "results" / "step_01", self.baseline, self.edited_map(), Protocol())
        summary = json.loads((directory / "summary.json").read_text())
        self.fuel_result.setText(f"Baseline AFR: {summary['baseline']['final_window_mean_afr']:.4f}   |   "
                                f"Edited map AFR: {summary['candidate']['final_window_mean_afr']:.4f}\n"
                                f"Synthetic fixed-point comparison saved to {directory}")
        self.refresh_history()
        return directory

    def refresh_history(self):
        self.saved_paths = sorted((ROOT / "results").glob("*/*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.history_table.setRowCount(0)
        valid_paths = []
        for path in self.saved_paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                values = (data["model_version"], data["experiment_id"], str(len(data["runs"])))
                row = self.history_table.rowCount()
                self.history_table.insertRow(row)
                for column, value in enumerate(values):
                    self.history_table.setItem(row, column, QTableWidgetItem(value))
                valid_paths.append(path.parent)
            except (OSError, ValueError, KeyError):
                continue
        self.saved_paths = valid_paths

    def open_selected_report(self):
        row = self.history_table.currentRow()
        if 0 <= row < len(self.saved_paths):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_paths[row] / "report.md")))


def smoke_test(app, window, output):
    """Exercise the actual widgets and offscreen rendering without desktop access."""
    import tempfile
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider
    from fuel_dynamics import simulate_scenario
    output.mkdir(parents=True, exist_ok=True)
    window.show()
    app.processEvents()
    window.scenario_choice.setCurrentIndex(2)
    window.start()
    window.timer.stop()
    for _ in range(400):
        window.tick()
    assert window.samples[-1]["rpm"] > 900
    window.pause()
    paused_tick = window.tick_count
    window.start()
    window.timer.stop()
    window.tick()
    window.pause()
    assert window.tick_count == paused_tick + window.stride
    with tempfile.TemporaryDirectory() as temporary:
        directory = window.archive_current(temporary)
        saved = json.loads((directory / "config.json").read_text())
        replay = simulate_scenario(saved["scenarios"][0], window.parameters, window.fuel_parameters)
        assert replay == window.samples, "Desktop recording did not reproduce exactly"
        fuel_directory = window.run_fuel_comparison(temporary)
        summary = json.loads((fuel_directory / "summary.json").read_text())
        assert abs(summary["candidate"]["final_window_mean_afr"] - 14.7/1.1) < 1e-8
        window.map_table.cellWidget(1, 1).setValue(1.05)
        changed_directory = window.run_fuel_comparison(temporary)
        changed = json.loads((changed_directory / "summary.json").read_text())
        assert abs(changed["candidate"]["final_window_mean_afr"] - 14.7/1.05) < 1e-8
        window.map_table.cellWidget(1, 1).setValue(1.1)
    app.processEvents()
    assert window.grab().save(str(output / "dashboard.png"))
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    assert window.grab().save(str(output / "fuel_maps.png"))
    window.tabs.setCurrentIndex(2)
    app.processEvents()
    assert window.grab().save(str(output / "history.png"))
    window.tabs.setCurrentIndex(0)
    while window.tick_count < window.total_ticks:
        window.tick()
    assert len(window.samples) == 1001 and not window.start_button.isEnabled()
    baseline_final_rpm = window.samples[-1]["rpm"]
    baseline_map = window.active_fuel_map
    window.queue_dashboard_map()
    assert window.active_fuel_map == baseline_map
    assert window.pending_fuel_map != baseline_map
    with tempfile.TemporaryDirectory() as temporary:
        directory = window.archive_current(temporary)
        saved = json.loads((directory / "config.json").read_text())
        assert FuelMap.from_dict(saved["scenarios"][0]["fuel_map"]) == baseline_map
    window.reset()
    assert window.active_fuel_map == window.pending_fuel_map
    window.start()
    window.timer.stop()
    while window.tick_count < window.total_ticks:
        window.tick()
    assert abs(window.samples[-1]["afr"] - 14.7/1.1) < 1e-4
    assert abs(window.samples[-1]["rpm"] - baseline_final_rpm) > 1
    with tempfile.TemporaryDirectory() as temporary:
        directory = window.archive_current(temporary)
        saved = json.loads((directory / "config.json").read_text())
        assert simulate_scenario(saved["scenarios"][0], window.parameters, window.fuel_parameters) == window.samples
    print("Fuel coupling check passed: queued map, frozen recording, reset activation, live AFR/RPM response and replay")
    window.map_preset_choice.setCurrentIndex(1)
    window.queue_dashboard_map()
    window.scenario_choice.setCurrentIndex(0)
    window.throttle_slider.setValue(200)
    window.start()
    window.timer.stop()
    for _ in range(30):
        window.tick()
    window.load_slider.setValue(150)
    for _ in range(30):
        window.tick()
    window.pause()
    with tempfile.TemporaryDirectory() as temporary:
        directory = window.archive_current(temporary)
        saved = json.loads((directory / "config.json").read_text())
        assert simulate_scenario(saved["scenarios"][0], window.parameters, window.fuel_parameters) == window.samples
    window.reset()
    assert not window.samples and not window.timer.isActive()
    window.activateWindow()
    window.throttle_slider.setFocus()
    app.processEvents()
    window.throttle_slider.setValue(200)
    window.load_slider.setValue(100)
    QTest.keyClick(window.throttle_slider, Qt.Key.Key_Up)
    assert window.throttle_slider.value() == 210
    QTest.keyClick(window.throttle_slider, Qt.Key.Key_Down)
    assert window.throttle_slider.value() == 200
    QTest.keyClick(window.throttle_slider, Qt.Key.Key_Right)
    assert window.throttle_slider.value() == 200 and window.load_slider.value() == 110
    QTest.keyClick(window.load_slider, Qt.Key.Key_Left)
    assert window.load_slider.value() == 100
    repeated = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier, "", True, 1)
    QApplication.sendEvent(window.throttle_slider, repeated)
    assert window.throttle_slider.value() == 210
    window.throttle_slider.setValue(1000)
    QTest.keyClick(window.throttle_slider, Qt.Key.Key_Up)
    assert window.throttle_slider.value() == 1000
    window.throttle_slider.setValue(0)
    QTest.keyClick(window.throttle_slider, Qt.Key.Key_Down)
    assert window.throttle_slider.value() == 0
    window.load_slider.setValue(600)
    QTest.keyClick(window.load_slider, Qt.Key.Key_Right)
    assert window.load_slider.value() == 600
    window.load_slider.setValue(0)
    QTest.keyClick(window.load_slider, Qt.Key.Key_Left)
    assert window.load_slider.value() == 0
    # Real mouse drag still changes the slider after the keyboard filter.
    window.throttle_slider.setValue(200)
    option = QStyleOptionSlider()
    window.throttle_slider.initStyleOption(option)
    handle = window.throttle_slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, window.throttle_slider)
    start = handle.center()
    end = start + QPoint(55, 0)
    QTest.mousePress(window.throttle_slider, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.throttle_slider, end)
    QTest.mouseRelease(window.throttle_slider, Qt.MouseButton.LeftButton, pos=end)
    assert window.throttle_slider.value() > 200
    window.scenario_choice.setCurrentIndex(1)
    window.start_button.setFocus()
    before = (window.throttle_slider.value(), window.load_slider.value())
    QTest.keyClick(window.start_button, Qt.Key.Key_Up)
    assert (window.throttle_slider.value(), window.load_slider.value()) == before
    window.scenario_choice.setCurrentIndex(0)
    window.scenario_choice.setFocus()
    QTest.keyClick(window.scenario_choice, Qt.Key.Key_Down)
    assert window.scenario_choice.currentIndex() == 1
    window.tabs.setCurrentIndex(1)
    editor = window.map_table.cellWidget(1, 1)
    editor.setFocus()
    initial_value = editor.value()
    QTest.keyClick(editor, Qt.Key.Key_Up)
    assert abs(editor.value() - initial_value - editor.singleStep()) < 1e-9
    assert (window.throttle_slider.value(), window.load_slider.value()) == before
    print("Keyboard check passed: four arrows, repeat, bounds, mouse drag, preset lock, combo navigation and map editing")
    print("Desktop smoke test passed: scenarios, start/pause/resume/reset, manual inputs, fuel editor, archive/replay, three rendered tabs")
    window.close()


def research_smoke_test(app, window, output):
    """Exercise real child-process success, responsiveness, saved plots and cancellation."""
    import tempfile
    import time
    from PySide6.QtTest import QTest
    output.mkdir(parents=True, exist_ok=True)
    window.show()
    window.tabs.setCurrentIndex(3)
    app.processEvents()
    beats = []
    heartbeat = QTimer()
    heartbeat.setInterval(20)
    heartbeat.timeout.connect(lambda: beats.append(time.monotonic()))
    heartbeat.start()
    with tempfile.TemporaryDirectory() as temporary:
        window.study_choice.setCurrentIndex(1)
        window.start_research(Path(temporary))
        deadline = time.monotonic()+90
        while window.study_process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
            QTest.qWait(30)
        app.processEvents()
        assert window.study_process.state() == QProcess.ProcessState.NotRunning, "Study process timed out"
        assert window.study_complete, window.study_status.text()
        directory = window.study_directory
        manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "complete" and len(manifest["runs"]) == 9
        assert len(beats) > 20, "GUI did not continue processing timer events"
        assert max(b-a for a,b in zip(beats, beats[1:])) < 2, "GUI blocked during study"
        for index, name in enumerate(("nominal_traces", "sensitivity_ranges", "ecu_estimate_sweep")):
            window.figure_choice.setCurrentIndex(index)
            app.processEvents()
            assert not window.figure_preview.pixmap().isNull()
            assert (directory/"figures"/(name+".pdf")).stat().st_size > 1000
            assert window.grab().save(str(output/("experiments_"+name+".png")))
        window.study_choice.setCurrentIndex(0)
        window.start_research(Path(temporary))
        deadline = time.monotonic()+20
        while window.study_directory is None and time.monotonic() < deadline:
            QTest.qWait(20)
        assert window.study_directory is not None, window.study_status.text()
        window.cancel_research()
        deadline = time.monotonic()+10
        while window.study_process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
            QTest.qWait(20)
        app.processEvents()
        assert window.study_process.state() == QProcess.ProcessState.NotRunning
        partial = json.loads((window.study_directory/"manifest.json").read_text(encoding="utf-8"))
        assert partial["status"] == "cancelled", partial["status"]
        assert window.study_start.isEnabled() and not window.study_cancel.isEnabled()
        assert (window.study_directory/"report.md").is_file()
    heartbeat.stop()
    window.close()
    print("Research desktop check passed: real child process, 9 conditions, responsive GUI, three previews/PDFs, cancellation and preserved partial report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--research-smoke-test", action="store_true")
    parser.add_argument("--tab", choices=("dashboard", "maps", "history", "experiments", "assistant"), default="dashboard")
    parser.add_argument("--qa-dir", type=Path, default=ROOT / "tmp" / "desktop_qa")
    args = parser.parse_args()
    application = QApplication(sys.argv[:1])
    # Qt's offscreen platform does not discover Windows fonts automatically.
    # Register the same local fonts explicitly for the app and QA renders.
    font_directory = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    for font_file in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf"):
        if (font_directory / font_file).is_file():
            QFontDatabase.addApplicationFont(str(font_directory / font_file))
    application.setFont(QFont("Segoe UI", 10))
    application.setStyle("Fusion")
    application.setStyleSheet(stylesheet("new_gen"))
    settings_path = args.qa_dir/"appearance.json" if args.smoke_test or args.research_smoke_test else None
    window = Studio(settings_path=settings_path)
    if args.smoke_test:
        smoke_test(application, window, args.qa_dir)
    elif args.research_smoke_test:
        research_smoke_test(application, window, args.qa_dir)
    else:
        window.tabs.setCurrentIndex(("dashboard", "maps", "history", "experiments", "assistant").index(args.tab))
        window.show()
        sys.exit(application.exec())


if __name__ == "__main__":
    main()
