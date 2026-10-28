"""Non-blocking local assistant UI, with explicit map-proposal review."""

import copy
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl, Qt
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ecu_bench import FuelMap, write_json
from local_ai import (ENDPOINT, MODEL, MODEL_CATALOG, PROMPT_VERSION, ROOT, RUNTIME, fingerprint,
                      load_preferences, make_request, model_profile, parse_reply, runtime_environment)


def text_label(text, name=None):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(True)
    return item


class AssistantPanel(QWidget):
    def __init__(self, context_provider, proposal_loader, parent=None, endpoint=ENDPOINT, settings_path=None):
        super().__init__(parent)
        self.context_provider, self.proposal_loader = context_provider, proposal_loader
        self.endpoint = endpoint
        self.settings_path = Path(settings_path) if settings_path else ROOT/".local/assistant.json"
        self.preferences = load_preferences(self.settings_path)
        self.network = QNetworkAccessManager(self)
        self.network.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.runtime = QProcess(self)
        self.runtime.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.runtime.readyReadStandardOutput.connect(lambda: self.runtime.readAllStandardOutput())
        self.runtime.errorOccurred.connect(self.runtime_error)
        self.installer = QProcess(self)
        self.installer.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.installer.readyReadStandardOutput.connect(self.read_install_output)
        self.installer.finished.connect(self.install_finished)
        self.installer.errorOccurred.connect(self.install_error)
        self.retry = QTimer(self)
        self.retry.setSingleShot(True)
        self.retry.timeout.connect(lambda: self.connect_local())
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(500)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        self.reply = None
        self.probe_reply = None
        self.ready = self.closing = self.cancelled = self.install_requested = False
        self.attempts = 0
        self.messages, self.turns, self.model_metadata = [], [], {}
        self.proposal = self.proposal_base = None
        self.pending = None
        self.preferred_model = self.preferences["model"]
        self.connected = self.inference_busy = False
        self.setup_model = None
        self.install_buffer = b""
        self.pull_buffer = b""
        self.layout_ui()
        self.populate_models(self.preferred_model)
        self.update_selection(report=False)

    def layout_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addWidget(text_label("AI Assistant", "title"))
        layout.addWidget(text_label("Local model · explain app data or request a fuel-map proposal for review.", "muted"))
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Model"))
        self.model_choice = QComboBox()
        self.model_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_choice.setMinimumContentsLength(19)
        self.model_choice.currentIndexChanged.connect(self.model_changed)
        toolbar.addWidget(self.model_choice, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(lambda: self.connect_local())
        toolbar.addWidget(self.connect_button)
        self.install_button = QPushButton("Download selected")
        self.install_button.clicked.connect(self.install_local)
        toolbar.addWidget(self.install_button)
        toolbar.addWidget(QLabel("Language"))
        self.language_choice = QComboBox()
        self.language_choice.addItem("English", "en")
        self.language_choice.addItem("Greek", "el")
        self.language_choice.setCurrentIndex(self.language_choice.findData(self.preferences["language"]))
        self.language_choice.currentIndexChanged.connect(self.preference_changed)
        toolbar.addWidget(self.language_choice)
        layout.addLayout(toolbar)
        self.model_hint = text_label("", "muted")
        layout.addWidget(self.model_hint)
        self.status = text_label("Connect to check installed models. Only the selected model is downloaded.", "muted")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        options = QHBoxLayout()
        options.addWidget(QLabel("Context"))
        self.context_choice = QComboBox()
        self.context_choice.addItem("Current dashboard + editor", "dashboard")
        self.context_choice.addItem("Loaded experiment study + editor", "study")
        options.addWidget(self.context_choice, 1)
        options.addWidget(QLabel("Mode"))
        self.mode_choice = QComboBox()
        self.mode_choice.addItem("Explain / discuss", False)
        self.mode_choice.addItem("Suggest map changes", True)
        options.addWidget(self.mode_choice, 1)
        options.addWidget(QLabel("Compute"))
        self.compute_choice = QComboBox()
        self.compute_choice.addItem("Auto (GPU / CPU)", "auto")
        self.compute_choice.addItem("CPU only", "cpu")
        self.compute_choice.setCurrentIndex(self.compute_choice.findData(self.preferences["compute"]))
        self.compute_choice.currentIndexChanged.connect(self.preference_changed)
        options.addWidget(self.compute_choice)
        layout.addLayout(options)
        body = QSplitter(Qt.Orientation.Horizontal)
        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 6, 0)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Ask about AFR, RPM, map multipliers or the loaded study.\nA fresh app snapshot is attached to each question.")
        chat_layout.addWidget(self.transcript, 1)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Ask a question… Replies are in English by default.")
        self.question.setMaximumHeight(84)
        chat_layout.addWidget(self.question)
        buttons = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send)
        self.send_button.setEnabled(False)
        buttons.addWidget(self.send_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.stop_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear)
        buttons.addWidget(self.clear_button)
        self.save_button = QPushButton("Save chat")
        self.save_button.clicked.connect(self.save_chat)
        buttons.addWidget(self.save_button)
        chat_layout.addLayout(buttons)
        body.addWidget(chat_page)
        proposal_page = QWidget()
        proposal_layout = QVBoxLayout(proposal_page)
        proposal_layout.setContentsMargins(6, 0, 0, 0)
        proposal_layout.addWidget(text_label("Proposal for review", "sectionTitle"))
        self.proposal_note = text_label("Request map changes to see the current and proposed values here.", "muted")
        proposal_layout.addWidget(self.proposal_note)
        self.proposal_table = QTableWidget(0, 3)
        self.proposal_table.setHorizontalHeaderLabels(["kPa / RPM", "Current", "Proposed"])
        self.proposal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.proposal_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.proposal_table.verticalHeader().hide()
        proposal_layout.addWidget(self.proposal_table, 1)
        self.rationale = QPlainTextEdit()
        self.rationale.setReadOnly(True)
        self.rationale.setPlaceholderText("Proposal rationale")
        self.rationale.setMaximumHeight(115)
        proposal_layout.addWidget(self.rationale)
        self.load_button = QPushButton("Load proposal in Fuel maps")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_proposal)
        proposal_layout.addWidget(self.load_button)
        proposal_layout.addWidget(text_label("Review in Fuel maps, then choose Use on next run. Proposals concern this simulator.", "muted"))
        body.addWidget(proposal_page)
        body.setSizes([680, 350])
        body.setChildrenCollapsible(False)
        layout.addWidget(body, 1)

    def populate_models(self, selected):
        blocked = self.model_choice.blockSignals(True)
        self.model_choice.clear()
        names = [*MODEL_CATALOG, *(name for name in self.model_metadata if name not in MODEL_CATALOG)]
        for name in names:
            profile = model_profile(name)
            availability = "Installed" if name in self.model_metadata else ("Download" if self.connected else "Not checked")
            self.model_choice.addItem(f"{profile['label']} · {profile['tier']} · {availability}", name)
        index = self.model_choice.findData(selected)
        self.model_choice.setCurrentIndex(index if index >= 0 else self.model_choice.findData(MODEL))
        self.model_choice.blockSignals(blocked)

    def update_selection(self, report=True):
        model = self.model_choice.currentData()
        profile = model_profile(model)
        self.ready = self.connected and model in self.model_metadata
        size = f"~{profile['download_gb']:g} GB model download" if profile["download_gb"] is not None else "Installed custom model"
        history = "single-question context" if profile["history_messages"] == 0 else "bounded recent history"
        self.model_hint.setText(f"{profile['tier']} · {size} · {profile['num_ctx']:,} token context · {history}. "
                               "Smaller models use less memory; speed depends on the computer.")
        if not self.inference_busy and not self.install_requested:
            self.send_button.setEnabled(self.ready)
            self.install_button.setText("Installed" if self.ready else ("Download selected" if RUNTIME.is_file() else "Install + download"))
            self.install_button.setEnabled(not self.ready)
        extra = "" if RUNTIME.is_file() else " Plus the portable runtime (~1.59 GB download)."
        self.install_button.setToolTip(f"Downloads only {profile['label']}. {size}.{extra}")
        if report and not self.install_requested and not self.inference_busy:
            language = self.language_choice.currentText()
            self.status.setText(f"Ready · {profile['label']} · {language} replies · local inference." if self.ready else
                (f"{profile['label']} is not installed. Choose Download selected." if self.connected else "Connect to check installed models."))

    def model_changed(self, *_):
        self.preferred_model = self.model_choice.currentData()
        self.clear_proposal()
        self.update_selection()
        self.save_preferences()

    def preference_changed(self, *_):
        self.update_selection()
        self.save_preferences()

    def save_preferences(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            write_json(temporary, {"schema": "ecu_assistant_preferences_v1", "model": self.model_choice.currentData(),
                "language": self.language_choice.currentData(), "compute": self.compute_choice.currentData()})
            temporary.replace(self.settings_path)
        except OSError:
            self.status.setText("Selection updated; preferences could not be saved.")

    def request(self, path, payload=None, timeout=5000):
        request = QNetworkRequest(QUrl(self.endpoint+path))
        request.setTransferTimeout(timeout)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if payload is None:
            return self.network.get(request)
        return self.network.post(request, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def connect_local(self):
        if self.closing or self.probe_reply is not None or self.reply is not None:
            return
        self.status.setText("Connecting to the local model service…")
        self.probe_reply = self.request("/api/tags", timeout=1500)
        self.probe_reply.finished.connect(self.models_received)

    def models_received(self):
        reply, self.probe_reply = self.probe_reply, None
        if self.closing:
            reply.deleteLater()
            return
        error = reply.error()
        raw = bytes(reply.readAll())
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            self.connected = False
            self.ready = False
            self.send_button.setEnabled(False)
            if self.runtime.state() == QProcess.ProcessState.NotRunning and RUNTIME.is_file():
                environment = QProcessEnvironment.systemEnvironment()
                for key, value in runtime_environment().items():
                    environment.insert(key, value)
                self.runtime.setProcessEnvironment(environment)
                self.runtime.setWorkingDirectory(str(RUNTIME.parent))
                self.runtime.start(str(RUNTIME), ["serve"])
            if RUNTIME.is_file() and self.attempts < 40:
                self.attempts += 1
                self.retry.start(500)
            else:
                self.status.setText("Local AI is unavailable. Use Install local AI to set up the runtime and model.")
                self.install_button.setEnabled(True)
                self.install_requested = False
                self.busy(False)
                self.progress.hide()
            return
        self.attempts = 0
        try:
            models = json.loads(raw)["models"]
            models = [m for m in models if "cloud" not in m.get("name", "").lower() and not m.get("remote_host")]
            self.model_metadata = {m["name"]: m for m in models}
            self.connected = True
            previous = self.setup_model if self.install_requested else (self.preferred_model or self.model_choice.currentData())
            self.populate_models(previous)
            self.preferred_model = None
            self.update_selection(report=False)
            if self.install_requested and self.setup_model not in self.model_metadata:
                self.pull_model(self.setup_model)
            else:
                self.install_requested = False
                self.busy(False)
                self.progress.hide()
                self.update_selection()
        except (ValueError, KeyError, TypeError) as error:
            self.connected = self.ready = False
            self.install_requested = False
            self.busy(False)
            self.progress.hide()
            self.status.setText("Invalid local service response: "+str(error))

    def runtime_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and not self.closing:
            self.retry.stop()
            self.status.setText("Could not start local runtime: "+self.runtime.errorString())
            self.install_requested = False
            self.busy(False)
            self.install_button.setEnabled(True)
            self.progress.hide()

    def install_local(self):
        if self.reply is not None or self.installer.state() != QProcess.ProcessState.NotRunning:
            return
        self.install_requested = True
        self.setup_model = self.model_choice.currentData()
        self.busy(True)
        self.install_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        if RUNTIME.is_file():
            self.connect_local()
            return
        interpreter = Path(sys.executable)
        if interpreter.with_name("pythonw.exe").is_file():
            interpreter = interpreter.with_name("pythonw.exe")
        self.install_buffer = b""
        self.installer.start(str(interpreter), ["-u", "-X", "utf8", str(ROOT/"setup_local_ai.py")])

    def read_install_output(self):
        self.install_buffer += bytes(self.installer.readAllStandardOutput())
        while b"\n" in self.install_buffer:
            line, self.install_buffer = self.install_buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
                if event["event"] == "progress":
                    self.progress.setRange(0, 100)
                    self.progress.setValue(round(100*event["completed"]/max(1,event["total"])))
                elif "message" in event:
                    self.status.setText(event["message"])
            except (ValueError, KeyError):
                continue

    def install_finished(self, code, _status):
        self.read_install_output()
        if self.closing:
            return
        if code == 0:
            self.connect_local()
        else:
            self.install_requested = False
            self.busy(False)
            self.install_button.setEnabled(True)
            self.progress.hide()

    def install_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.install_requested = False
            self.busy(False)
            self.install_button.setEnabled(True)
            self.progress.hide()
            self.status.setText("Could not start installer: "+self.installer.errorString())

    def pull_model(self, model):
        self.pull_target = model
        profile = model_profile(model)
        self.status.setText(f"Downloading {profile['label']} (~{profile['download_gb']:g} GB)…")
        self.pull_buffer = b""
        self.pull_error = ""
        self.pull_succeeded = False
        self.cancelled = False
        self.reply = self.request("/api/pull", {"model": model, "stream": True}, timeout=180000)
        self.reply.readyRead.connect(self.read_pull_output)
        self.reply.finished.connect(self.pull_finished)
        self.stop_button.setEnabled(True)
        self.send_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()

    def read_pull_output(self):
        self.pull_buffer += bytes(self.reply.readAll())
        while b"\n" in self.pull_buffer:
            line, self.pull_buffer = self.pull_buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
                if event.get("error"):
                    self.pull_error = event["error"]
                    self.status.setText(self.pull_error)
                else:
                    if event.get("status") == "success":
                        self.pull_succeeded = True
                    status = event.get("status", "downloading")
                    if status.startswith("pulling "):
                        status = "downloading model files"
                    elif "sha256" in status:
                        status = "verifying downloaded model"
                    self.status.setText("Model setup: "+status)
                    if event.get("total"):
                        self.progress.setValue(round(100*event.get("completed", 0)/event["total"]))
            except ValueError:
                continue

    def pull_finished(self):
        reply = self.reply
        self.read_pull_output()
        self.reply = None
        error, description = reply.error(), reply.errorString()
        reply.deleteLater()
        self.install_requested = False
        self.busy(False)
        self.stop_button.setEnabled(False)
        self.install_button.setEnabled(True)
        self.progress.hide()
        if self.closing:
            return
        if self.cancelled:
            self.status.setText("Model download stopped. Download selected can resume it.")
        elif error != QNetworkReply.NetworkError.NoError or self.pull_error or not self.pull_succeeded:
            self.status.setText("Model download failed: "+(self.pull_error or description))
        else:
            self.preferred_model = self.pull_target
            self.connect_local()

    def send(self):
        if not self.ready or self.reply is not None:
            return
        try:
            snapshot = self.context_provider(self.context_choice.currentData())
            question = self.question.toPlainText().strip()
            proposals = self.mode_choice.currentData()
            payload = make_request(self.model_choice.currentData(), question, snapshot, self.messages, proposals,
                                   language=self.language_choice.currentData(), compute=self.compute_choice.currentData())
        except (ValueError, KeyError, OSError) as error:
            self.status.setText(str(error))
            return
        self.clear_proposal()
        self.pending = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "prompt_version": PROMPT_VERSION,
            "question": question, "snapshot": copy.deepcopy(snapshot), "snapshot_sha256": fingerprint(snapshot),
            "request": payload, "model_metadata": copy.deepcopy(self.model_metadata.get(payload["model"], {})),
            "language": self.language_choice.currentData(), "compute": self.compute_choice.currentData(),
            "context_profile": model_profile(payload["model"]),
            "proposals_allowed": proposals}
        self.append_message("You", question)
        self.question.clear()
        self.cancelled = False
        self.started_at = time.monotonic()
        self.busy(True)
        self.elapsed_timer.start()
        self.update_elapsed()
        self.reply = self.request("/api/chat", payload, timeout=180000)
        self.reply.finished.connect(self.chat_finished)

    def chat_finished(self):
        reply, self.reply = self.reply, None
        raw = bytes(reply.readAll())
        error, description = reply.error(), reply.errorString()
        reply.deleteLater()
        self.elapsed_timer.stop()
        self.busy(False)
        if self.closing:
            return
        if self.cancelled:
            self.append_message("Status", "Request stopped. No proposal was loaded.")
            self.status.setText("Stopped. You can send another question.")
            return
        try:
            if error != QNetworkReply.NetworkError.NoError:
                try:
                    description = json.loads(raw).get("error", description)
                except (ValueError, AttributeError):
                    pass
                raise ValueError(description)
            response = json.loads(raw)
            if response.get("error"):
                raise ValueError(response["error"])
            if response.get("done_reason") == "length":
                raise ValueError("Model reached the answer limit. Ask a shorter, more specific question.")
            base = FuelMap.from_dict(self.pending["snapshot"]["editor_map"])
            answer, proposal, rationale = parse_reply(response["message"]["content"], base, self.pending["proposals_allowed"])
            self.append_message("Assistant", answer)
            self.messages += [{"role": "user", "content": self.pending["question"]}, {"role": "assistant", "content": answer}]
            self.pending.update({"response": response, "elapsed_wall_s": time.monotonic()-self.started_at,
                "validated_proposal": proposal.to_dict() if proposal else None, "proposal_loaded_in_editor": False})
            self.turns.append(self.pending)
            self.pending = None
            if proposal:
                self.show_proposal(base, proposal, rationale)
            self.status.setText(f"Ready · {self.model_choice.currentData()} · snapshot captured for this reply.")
        except (ValueError, KeyError, TypeError) as error:
            self.append_message("Status", "Request failed: "+str(error))
            self.status.setText("Request failed: "+str(error))
            self.pending = None

    def busy(self, enabled):
        self.inference_busy = enabled
        self.send_button.setEnabled(self.ready and not enabled)
        self.stop_button.setEnabled(enabled)
        for item in (self.model_choice, self.context_choice, self.mode_choice, self.clear_button,
                     self.install_button, self.connect_button, self.language_choice, self.compute_choice):
            item.setEnabled(not enabled)
        if not enabled:
            self.update_selection(report=False)

    def update_elapsed(self):
        self.status.setText(f"Generating locally… {time.monotonic()-self.started_at:.0f} s")

    def append_message(self, role, content):
        self.transcript.appendPlainText(f"{role}\n{content}\n")

    def clear_proposal(self):
        self.proposal = self.proposal_base = None
        self.load_button.setEnabled(False)
        self.proposal_table.setRowCount(0)
        self.rationale.clear()
        self.proposal_note.setText("Request map changes to see the current and proposed values here.")

    def show_proposal(self, base, proposal, rationale):
        self.proposal, self.proposal_base = proposal, base
        self.proposal_table.setRowCount(0)
        changed = 0
        deltas = []
        for row, pressure in enumerate(base.map_kpa_axis):
            for column, rpm in enumerate(base.rpm_axis):
                index = self.proposal_table.rowCount()
                self.proposal_table.insertRow(index)
                before, after = base.values[row][column], proposal.values[row][column]
                changed += before != after
                deltas.append(100*(after/before-1))
                for col, value in enumerate((f"{pressure:g} / {rpm:g}", f"{before:.3f}", f"{after:.3f}")):
                    self.proposal_table.setItem(index, col, QTableWidgetItem(value))
        self.proposal_note.setText(f"{changed} changed cells · fuel-command Δ {min(deltas):+.2f}% to {max(deltas):+.2f}% "
                                  "vs editor, at fixed estimated air and AFR target. Values rounded to 3 decimals.")
        self.rationale.setPlainText(rationale)
        self.load_button.setEnabled(True)

    def load_proposal(self):
        if self.proposal is None:
            return
        try:
            self.proposal_loader(self.proposal, self.proposal_base)
            if self.turns:
                self.turns[-1]["proposal_loaded_in_editor"] = True
            self.load_button.setEnabled(False)
            self.status.setText("Proposal loaded in Fuel maps for review. Use on next run queues it.")
        except ValueError as error:
            self.load_button.setEnabled(False)
            self.status.setText(str(error))

    def stop(self):
        self.cancelled = True
        if self.reply is not None:
            self.reply.abort()
        if self.installer.state() != QProcess.ProcessState.NotRunning:
            self.installer.kill()

    def clear(self):
        if self.reply is None:
            self.messages, self.turns = [], []
            self.transcript.clear()
            self.clear_proposal()

    def save_chat(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save assistant conversation", str(ROOT/"assistant_chat.json"), "JSON (*.json)")
        if path:
            try:
                self.export_chat(Path(path))
                self.status.setText("Conversation and request snapshots saved.")
            except OSError as error:
                self.status.setText("Could not save conversation: "+str(error))

    def export_chat(self, path):
        write_json(path, {"schema": "ecu_assistant_conversation_v1", "endpoint": self.endpoint,
            "data_origin": "synthetic_app_snapshots_and_generated_text", "turns": self.turns,
            "note": "Generated recommendations are hypotheses; schema validation does not establish engineering validity."})

    def shutdown(self):
        self.closing = True
        self.retry.stop()
        self.elapsed_timer.stop()
        if self.probe_reply is not None:
            self.probe_reply.abort()
        self.stop()
        for process in (self.installer, self.runtime):
            if process.state() != QProcess.ProcessState.NotRunning:
                if process is self.runtime and os.name == "nt":
                    # Stop only the server this panel owns, including its model runner.
                    try:
                        subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/taskkill.exe"),
                            "/PID", str(process.processId()), "/T", "/F"], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=3, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    if process.waitForFinished(1000):
                        continue
                process.terminate()
                if not process.waitForFinished(2000):
                    process.kill()
                    process.waitForFinished(1000)
