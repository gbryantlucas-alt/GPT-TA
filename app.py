from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from grader_app.controller import GraderController
from grader_app.docx_renderer import DocxHtmlRenderer
from grader_app.exporters import export_canvas_csv, export_student_feedback_files
from grader_app.models import AssignmentComplianceItem, CategoryScore
from grader_app.parsers import read_text

SETTINGS_PATH = Path("settings.json")


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {"api_key": "", "model": "gpt-4.1-mini", "workers": 6}


class EssayPage(QWebEnginePage):
    flag_clicked = Signal(int)
    image_clicked = Signal(str)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame):
        s = url.toString()
        if s.startswith("flag://"):
            self.flag_clicked.emit(int(s.split("://", 1)[1]))
            return False
        if s.startswith("img://"):
            self.image_clicked.emit(s.split("://", 1)[1])
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class BatchWorker(QThread):
    progress = Signal(str)
    done = Signal()
    failed = Signal(str)

    def __init__(self, controller: GraderController, api_key: str, model: str, essay_paths: list[str], workers: int):
        super().__init__()
        self.controller = controller
        self.api_key = api_key
        self.model = model
        self.essay_paths = essay_paths
        self.workers = workers

    def run(self):
        try:
            self.controller.run_batch(
                self.api_key,
                self.model,
                self.essay_paths,
                self.workers,
                on_update=lambda sid: self.progress.emit(sid),
            )
            self.done.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class GradingPanel(QWidget):
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.loading = False
        self.current_sid: str | None = None

        root = QVBoxLayout(self)

        self.header = QLabel("Select a student to review")
        self.header.setObjectName("StudentHeader")
        root.addWidget(self.header)

        self.save_status = QLabel("Saved ✓")
        self.save_status.setObjectName("SaveStatus")
        root.addWidget(self.save_status)

        tool = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.final_btn = QPushButton("Mark Finalized")
        self.export_btn = QPushButton("Export")
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        for b in [self.save_btn, self.final_btn, self.export_btn, self.prev_btn, self.next_btn]:
            tool.addWidget(b)
        root.addLayout(tool)

        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        root.addWidget(self.content_scroll, 1)

        container = QWidget()
        self.content_scroll.setWidget(container)
        c_layout = QVBoxLayout(container)

        self.tabs = QTabWidget()
        c_layout.addWidget(self.tabs)

        # Summary
        sum_tab = QWidget()
        sum_layout = QVBoxLayout(sum_tab)
        self.summary_edit = QTextEdit()
        self.summary_edit.textChanged.connect(self._emit_edit)
        sum_layout.addWidget(self.summary_edit)
        self.tabs.addTab(sum_tab, "Summary")

        # Compliance
        comp_tab = QWidget()
        comp_layout = QVBoxLayout(comp_tab)
        self.compliance_table = QTableWidget(0, 4)
        self.compliance_table.setHorizontalHeaderLabels(["Requirement", "Status", "Note", "Revert"])
        self.compliance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.compliance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.compliance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.compliance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.compliance_table.verticalHeader().setVisible(False)
        comp_layout.addWidget(self.compliance_table)
        self.tabs.addTab(comp_tab, "Compliance")

        # Rubric
        rub_tab = QWidget()
        rub_layout = QVBoxLayout(rub_tab)
        self.revert_all_btn = QPushButton("Revert all rubric changes")
        rub_layout.addWidget(self.revert_all_btn)
        self.rubric_table = QTableWidget(0, 5)
        self.rubric_table.setHorizontalHeaderLabels(["Dimension", "Score", "Label", "Feedback", "Revert"])
        self.rubric_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.rubric_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.rubric_table.verticalHeader().setVisible(False)
        rub_layout.addWidget(self.rubric_table)
        self.tabs.addTab(rub_tab, "Rubric")

        # Flags
        flag_tab = QWidget()
        flag_layout = QVBoxLayout(flag_tab)
        self.flags_table = QTableWidget(0, 5)
        self.flags_table.setHorizontalHeaderLabels(["Dimension", "Excerpt", "Review Question", "Teacher Note", "Jump"])
        self.flags_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.flags_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.flags_table.verticalHeader().setVisible(False)
        flag_layout.addWidget(self.flags_table)
        self.tabs.addTab(flag_tab, "Flags")

        # Overall
        ov_tab = QWidget()
        ov_layout = QVBoxLayout(ov_tab)
        self.overall_score = QDoubleSpinBox()
        self.overall_score.setMaximum(1000)
        self.overall_score.valueChanged.connect(self._emit_edit)
        self.overall_note = QTextEdit()
        self.overall_note.textChanged.connect(self._emit_edit)
        ov_layout.addWidget(QLabel("Overall Grade"))
        ov_layout.addWidget(self.overall_score)
        ov_layout.addWidget(QLabel("Overall Feedback"))
        ov_layout.addWidget(self.overall_note)
        self.tabs.addTab(ov_tab, "Overall")

        # Diff
        diff_tab = QWidget()
        diff_layout = QVBoxLayout(diff_tab)
        self.diff_filter = QComboBox()
        self.diff_filter.addItems(["All Changes", "Summary", "Compliance", "Rubric", "Overall", "Flags"])
        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        diff_layout.addWidget(self.diff_filter)
        diff_layout.addWidget(self.diff_view)
        self.tabs.addTab(diff_tab, "Diff")

    def _emit_edit(self):
        if not self.loading:
            self.edited.emit()
        self.current_sid: str | None = None
        self.category_widgets: dict[str, dict] = {}
        self.compliance_widgets: list[dict] = []
        self.annotation_widgets: dict[int, QWidget] = {}

        outer = QVBoxLayout(self)
        self.student_header = QLabel("Select a student")
        self.student_header.setObjectName("StudentHeader")
        outer.addWidget(self.student_header)

        self.save_status = QLabel("Saved ✓")
        self.save_status.setObjectName("SaveStatus")
        outer.addWidget(self.save_status)

        self.view_tabs = QTabWidget()
        outer.addWidget(self.view_tabs)

        current = QWidget()
        current_layout = QVBoxLayout(current)

        current_layout.addWidget(QLabel("Essay Summary"))
        self.summary = QTextEdit()
        self.summary.textChanged.connect(self.edited)
        current_layout.addWidget(self.summary)

        current_layout.addWidget(QLabel("Assignment Compliance"))
        self.compliance_container = QWidget()
        self.compliance_layout = QVBoxLayout(self.compliance_container)
        current_layout.addWidget(self.compliance_container)

        current_layout.addWidget(QLabel("Rubric"))
        self.rubric_container = QWidget()
        self.rubric_layout = QVBoxLayout(self.rubric_container)
        current_layout.addWidget(self.rubric_container)

        current_layout.addWidget(QLabel("Overall Grade"))
        grade_line = QHBoxLayout()
        self.overall = QDoubleSpinBox()
        self.overall.setMaximum(1000)
        self.overall.valueChanged.connect(self.edited)
        grade_line.addWidget(self.overall)
        self.overall_note = QTextEdit()
        self.overall_note.setMaximumHeight(80)
        self.overall_note.textChanged.connect(self.edited)
        current_layout.addLayout(grade_line)
        current_layout.addWidget(self.overall_note)

        self.flags_title = QLabel("Human review flags")
        current_layout.addWidget(self.flags_title)
        self.flags_container = QWidget()
        self.flags_layout = QVBoxLayout(self.flags_container)
        current_layout.addWidget(self.flags_container)

        self.view_tabs.addTab(current, "Current")

        self.diff_box = QTextEdit()
        self.diff_box.setReadOnly(True)
        self.view_tabs.addTab(self.diff_box, "Diff")

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.revert_all_btn = QPushButton("Revert All")
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        self.final_btn = QPushButton("Mark Finalized")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.revert_all_btn)
        btns.addWidget(self.prev_btn)
        btns.addWidget(self.next_btn)
        btns.addWidget(self.final_btn)
        outer.addLayout(btns)

    def set_save_status(self, text: str):
        self.save_status.setText(text)

    def set_placeholder(self):
        self.loading = True
        self.current_sid = None
        self.header.setText("Select a student to review")
        self.summary_edit.setPlainText("")
        self.compliance_table.setRowCount(0)
        self.rubric_table.setRowCount(0)
        self.flags_table.setRowCount(0)
        self.overall_score.setValue(0)
        self.overall_note.setPlainText("")
        self.diff_view.setPlainText("Select a student to see differences.")
        self.tabs.setEnabled(False)
        self.loading = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("English Essay Batch Grader")
        self.resize(1500, 900)

        self.settings = load_settings()
        self.controller = GraderController()
        self.renderer = DocxHtmlRenderer()
        self.essay_paths: list[str] = []
        self.current_sid: str | None = None
        self.current_unresolved: list[int] = []
        self.loading_selection = False

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.autosave)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_batch_tab(), "Batch Setup")
        self.tabs.addTab(self._build_review_tab(), "Essay Review")
        self.tabs.addTab(self._build_integrity_tab(), "Integrity")
        self.tabs.addTab(self._build_settings_tab(), "Settings")

        self._build_menu()
        self._apply_styles()
        self.set_no_selection_state()
        self.batch_tab = self._build_batch_tab()
        self.review_tab = self._build_review_tab()
        self.integrity_tab = self._build_integrity_tab()
        self.settings_tab = self._build_settings_tab()
        self.tabs.addTab(self.batch_tab, "Batch Setup")
        self.tabs.addTab(self.review_tab, "Essay Review")
        self.tabs.addTab(self.integrity_tab, "Integrity")
        self.tabs.addTab(self.settings_tab, "Settings")
        self._build_menu()
        self._apply_styles()

    def _build_batch_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        row = QHBoxLayout()
        buttons = [
            ("Upload Essays (.docx)", self.select_essays),
            ("Upload Rubric File", self.select_rubric_file),
            ("Upload Assignment File", self.select_assignment_file),
            ("Load Saved Session", self.load_session),
            ("Start AI Grading", self.start_grading),
        ]
        for text, fn in buttons:
            b = QPushButton(text)
            b.clicked.connect(fn)
        b1 = QPushButton("Upload Essays (.docx)")
        b1.clicked.connect(self.select_essays)
        b2 = QPushButton("Upload Rubric File")
        b2.clicked.connect(self.select_rubric_file)
        b3 = QPushButton("Upload Assignment File")
        b3.clicked.connect(self.select_assignment_file)
        b4 = QPushButton("Load Saved Session")
        b4.clicked.connect(self.load_session)
        b5 = QPushButton("Start AI Grading")
        b5.clicked.connect(self.start_grading)
        for b in [b1, b2, b3, b4, b5]:
            row.addWidget(b)
        l.addLayout(row)
        self.rubric_text = QTextEdit()
        self.assignment_text = QTextEdit()
        l.addWidget(QLabel("Rubric Text"))
        l.addWidget(self.rubric_text)
        l.addWidget(QLabel("Assignment Text"))
        l.addWidget(self.assignment_text)
        self.batch_status = QLabel("No batch started")
        l.addWidget(self.batch_status)
        return w

    def _build_review_tab(self):
        w = QWidget()
        root = QHBoxLayout(w)

        self.student_list = QListWidget()
        self.student_list.setMinimumWidth(220)
        self.student_list.setMaximumWidth(280)
        self.student_list.currentItemChanged.connect(self.on_student_select)
        root.addWidget(self.student_list)

        self.review_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self.review_splitter, 1)
        self.student_list.currentTextChanged.connect(self.on_student_select)
        self.student_list.setMaximumWidth(260)
        root.addWidget(self.student_list)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        self.essay_view = QWebEngineView()
        self.essay_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.essay_page = EssayPage(self.essay_view)
        self.essay_page.flag_clicked.connect(self.focus_flag)
        self.essay_page.image_clicked.connect(self.open_image_dialog)
        self.essay_view.setPage(self.essay_page)
        self.review_splitter.addWidget(self.essay_view)

        self.panel = GradingPanel()
        self.panel.setMinimumWidth(400)
        self.review_splitter.addWidget(self.panel)
        self.review_splitter.setCollapsible(1, False)
        self.review_splitter.setStretchFactor(0, 4)
        self.review_splitter.setStretchFactor(1, 2)
        self.review_splitter.setSizes([1000, 450])

        self.panel.edited.connect(self.queue_autosave)
        self.panel.save_btn.clicked.connect(self.save_current)
        self.panel.final_btn.clicked.connect(self.mark_finalized)
        self.panel.export_btn.clicked.connect(self.export_outputs)
        self.panel.prev_btn.clicked.connect(self.select_prev)
        self.panel.next_btn.clicked.connect(self.select_next)
        self.panel.revert_all_btn.clicked.connect(self.revert_all)
        self.panel.diff_filter.currentTextChanged.connect(self.refresh_diff_current)
        split.addWidget(self.essay_view)

        panel_wrap = QWidget()
        panel_layout = QVBoxLayout(panel_wrap)
        self.panel = GradingPanel()
        panel_layout.addWidget(self.panel)
        split.addWidget(panel_wrap)
        split.setSizes([980, 420])

        self.panel.edited.connect(self.queue_autosave)
        self.panel.save_btn.clicked.connect(self.save_current)
        self.panel.revert_all_btn.clicked.connect(self.revert_all)
        self.panel.next_btn.clicked.connect(self.select_next)
        self.panel.prev_btn.clicked.connect(self.select_prev)
        self.panel.final_btn.clicked.connect(self.mark_finalized)
        return w

    def _build_integrity_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        self.integrity_text = QTextEdit()
        self.integrity_text.setReadOnly(True)
        l.addWidget(self.integrity_text)
        return w

    def _build_settings_tab(self):
        w = QWidget()
        l = QFormLayout(w)
        self.api_key = QLineEdit(self.settings.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit(self.settings.get("model", "gpt-4.1-mini"))
        self.workers = QLineEdit(str(self.settings.get("workers", 6)))
        l.addRow("OpenAI API Key", self.api_key)
        l.addRow("Model", self.model)
        l.addRow("Parallel Workers", self.workers)
        btn = QPushButton("Save Settings")
        btn.clicked.connect(self.save_settings)
        l.addRow(btn)
        return w

    def _build_menu(self):
        menu = self.menuBar().addMenu("File")
        menu.addAction("Export Final Outputs", self.export_outputs)
        save = QPushButton("Save Settings")
        save.clicked.connect(self.save_settings)
        l.addRow(save)
        return w


    def _build_menu(self):
        menu = self.menuBar().addMenu("File")
        export_action = menu.addAction("Export Final Outputs")
        export_action.triggered.connect(self.export_outputs)

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#f6f8fb; color:#1f2937; font-family:'Segoe UI'; font-size:13px; }
            QPushButton { background:#2563eb; color:white; border:none; border-radius:6px; padding:8px 12px; }
            QPushButton:hover { background:#1d4ed8; }
            QTextEdit, QLineEdit, QListWidget, QComboBox, QDoubleSpinBox, QTableWidget { background:white; border:1px solid #d1d5db; border-radius:6px; }
            #StudentHeader { font-size:16px; font-weight:700; }
            #SaveStatus { color:#047857; font-weight:600; }
            QHeaderView::section { background:#e5e7eb; border:none; padding:6px; }
            """
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "review_splitter"):
            print(f"[resize] window={self.width()}x{self.height()} splitter={self.review_splitter.sizes()}")

    def save_settings(self):
        self.settings = {
            "api_key": self.api_key.text().strip(),
            "model": self.model.text().strip(),
            "workers": int(self.workers.text() or 6),
        }
            QTextEdit, QLineEdit, QListWidget, QComboBox, QDoubleSpinBox { background:white; border:1px solid #d1d5db; border-radius:6px; padding:6px; }
            #StudentHeader { font-size:16px; font-weight:700; }
            #SaveStatus { color:#047857; font-weight:600; }
            """
        )

    def save_settings(self):
        self.settings = {"api_key": self.api_key.text().strip(), "model": self.model.text().strip(), "workers": int(self.workers.text() or 6)}
        SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Saved", "Settings saved.")

    def select_essays(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select essays", "", "Word Files (*.docx)")
        if files:
            self.essay_paths = files
            self.batch_status.setText(f"Selected {len(files)} essays")

    def select_rubric_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select rubric", "", "Docs (*.docx *.pdf)")
        if f:
            self.rubric_text.setPlainText(read_text(f))

    def select_assignment_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select assignment", "", "Docs (*.docx *.pdf)")
        if f:
            self.assignment_text.setPlainText(read_text(f))

    def start_grading(self):
        if not self.essay_paths:
            QMessageBox.warning(self, "Missing", "Upload essays first.")
            return
        if not self.api_key.text().strip():
            QMessageBox.warning(self, "Missing", "Set API key in Settings.")
            return
        self.controller.set_rubric_and_assignment(self.rubric_text.toPlainText().strip(), self.assignment_text.toPlainText().strip())
        self.batch_status.setText("Running AI grading in background...")
        self.worker = BatchWorker(
            self.controller,
            self.api_key.text().strip(),
            self.model.text().strip(),
            self.essay_paths,
            int(self.workers.text() or 6),
        )
        self.worker = BatchWorker(self.controller, self.api_key.text().strip(), self.model.text().strip(), self.essay_paths, int(self.workers.text() or 6))
        self.worker.progress.connect(self.on_batch_progress)
        self.worker.done.connect(self.on_batch_done)
        self.worker.failed.connect(lambda e: QMessageBox.critical(self, "Batch failed", e))
        self.worker.start()

    def on_batch_progress(self, sid: str):
        self.refresh_students()
        self.batch_status.setText(f"Processed {sid} ({len(self.controller.session.essays)})")

    def on_batch_done(self):
        self.refresh_students()
        self.refresh_integrity()
        self.batch_status.setText("Batch complete.")

    def refresh_students(self):
        self.student_list.blockSignals(True)
        self.student_list.clear()
        for sid in self.controller.student_ids():
            essay = self.controller.session.essays[sid]
            it = QListWidgetItem(f"{sid} · {self.controller.status_label(essay.status)}")
            it.setData(Qt.UserRole, sid)
            self.student_list.addItem(it)
        self.student_list.blockSignals(False)

    def set_no_selection_state(self):
        self.current_sid = None
        self.panel.set_placeholder()
        self.panel.set_save_status("Saved ✓")
        self.essay_view.setHtml("<html><body style='font-family:Segoe UI;padding:28px;color:#6b7280;'>Select a student to review.</body></html>")

    def on_student_select(self, current: QListWidgetItem | None, previous: QListWidgetItem | None):
        print(f"[selection] current={current.data(Qt.UserRole) if current else None} previous={previous.data(Qt.UserRole) if previous else None}")
        if not current:
            self.set_no_selection_state()
            return
        sid = current.data(Qt.UserRole)
        self.current_sid = sid
        essay = self.controller.session.essays[sid]

        self.loading_selection = True
        self.panel.loading = True
        self.panel.tabs.setEnabled(True)
        self.panel.current_sid = sid
        self.panel.header.setText(f"{sid} • {essay.file_name or Path(essay.file_path).name}")

        rendered = self.renderer.render(essay.file_path, essay.annotations)
        self.current_unresolved = rendered.unresolved_flags
        self.essay_view.setHtml(rendered.html)

        self.panel.summary_edit.setPlainText(essay.summary)
        self.populate_compliance_tab(essay)
        self.populate_rubric_tab(essay)
        self.populate_flags_tab(essay)
        self.panel.overall_score.setValue(float(essay.overall_grade))
        self.panel.overall_note.setPlainText(essay.overall_note)
        self.refresh_diff_current()

        self.panel.loading = False
        self.loading_selection = False

    def populate_compliance_tab(self, essay):
        t = self.panel.compliance_table
        t.setRowCount(len(essay.compliance))
        for i, item in enumerate(essay.compliance):
            req = QTableWidgetItem(item.requirement)
            req.setFlags(req.flags() & ~Qt.ItemIsEditable)
            t.setItem(i, 0, req)

            status = QComboBox()
            status.addItems(["met", "partial", "missing"])
            status.setCurrentText(item.status or "partial")
            status.currentTextChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 1, status)

            note = QLineEdit(item.note)
            note.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 2, note)

            rev = QPushButton("Revert")
            rev.clicked.connect(lambda _=None, idx=i: self.revert_compliance(idx))
            t.setCellWidget(i, 3, rev)

    def populate_rubric_tab(self, essay):
        t = self.panel.rubric_table
        t.setRowCount(len(essay.category_scores))
        for i, cat in enumerate(essay.category_scores):
            dim = QTableWidgetItem(cat.dimension)
            dim.setFlags(dim.flags() & ~Qt.ItemIsEditable)
            t.setItem(i, 0, dim)

            score = QDoubleSpinBox()
            score.setMaximum(1000)
            score.setValue(float(cat.score))
            score.valueChanged.connect(lambda _=None, idx=i: self.update_label_from_score(idx))
            score.valueChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 1, score)

            label = QLabel(cat.label)
            t.setCellWidget(i, 2, label)

            fb = QTextEdit(cat.feedback)
            fb.setMinimumHeight(80)
            fb.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 3, fb)

            rev = QPushButton("Revert")
            rev.clicked.connect(lambda _=None, idx=i: self.revert_rubric(idx))
            t.setCellWidget(i, 4, rev)
            t.setRowHeight(i, 110)

    def populate_flags_tab(self, essay):
        t = self.panel.flags_table
        t.setRowCount(len(essay.annotations))
        for i, ann in enumerate(essay.annotations):
            for col, val in enumerate([ann.dimension, ann.excerpt, ann.question]):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(i, col, it)

            note = QLineEdit(ann.teacher_note)
            note.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 3, note)

            jump = QPushButton("Jump")
            jump.clicked.connect(lambda _=None, idx=i: self.jump_to_flag(idx))
            t.setCellWidget(i, 4, jump)

    def update_label_from_score(self, idx: int):
        if self.panel.loading or not self.current_sid:
            return
        essay = self.controller.session.essays[self.current_sid]
        cat = essay.category_scores[idx]
        score_widget = self.panel.rubric_table.cellWidget(idx, 1)
        label_widget = self.panel.rubric_table.cellWidget(idx, 2)
        if not isinstance(score_widget, QDoubleSpinBox) or not isinstance(label_widget, QLabel):
            return
        score = score_widget.value()
        # simple label update fallback based on current label tokens
        parts = [p.strip() for p in cat.label.split("/") if p.strip()] or [cat.label]
        if len(parts) == 1:
            new_label = parts[0]
        elif score < 40:
            new_label = parts[0]
        elif score < 75:
            new_label = parts[min(1, len(parts) - 1)]
        else:
            new_label = parts[-1]
        label_widget.setText(new_label)

    def jump_to_flag(self, idx: int):
        self.essay_view.page().runJavaScript(
            f"""
            const el=document.querySelector('mark[data-flag="{idx}"]');
            if(el){{el.scrollIntoView({{behavior:'smooth', block:'center'}});}}
            """
        )

    def focus_flag(self, index: int):
        if not self.current_sid:
            return
        self.panel.tabs.setCurrentIndex(3)
        self.panel.flags_table.selectRow(index)
        self.jump_to_flag(index)

    def open_image_dialog(self, _image_id: str):
        QMessageBox.information(self, "Image", "Image clicked in essay viewer.")

    def queue_autosave(self):
        if self.panel.loading or self.loading_selection:
            return
        self.panel.set_save_status("Saving…")
        self.autosave_timer.start(800)

    def sync_ui_to_model(self):
        if not self.current_sid:
            return
        essay = self.controller.session.essays[self.current_sid]
        essay.summary = self.panel.summary_edit.toPlainText().strip()

        for i, comp in enumerate(essay.compliance):
            status = self.panel.compliance_table.cellWidget(i, 1)
            note = self.panel.compliance_table.cellWidget(i, 2)
            if isinstance(status, QComboBox):
                comp.status = status.currentText()
            if isinstance(note, QLineEdit):
                comp.note = note.text().strip()

        for i, cat in enumerate(essay.category_scores):
            score = self.panel.rubric_table.cellWidget(i, 1)
            label = self.panel.rubric_table.cellWidget(i, 2)
            fb = self.panel.rubric_table.cellWidget(i, 3)
            if isinstance(score, QDoubleSpinBox):
                cat.score = score.value()
            if isinstance(label, QLabel):
                cat.label = label.text().strip()
            if isinstance(fb, QTextEdit):
                cat.feedback = fb.toPlainText().strip()

        for i, ann in enumerate(essay.annotations):
            note = self.panel.flags_table.cellWidget(i, 3)
            if isinstance(note, QLineEdit):
                ann.teacher_note = note.text().strip()

        essay.overall_grade = self.panel.overall_score.value()
        self.student_list.clear()
        for sid in self.controller.student_ids():
            essay = self.controller.session.essays[sid]
            item = QListWidgetItem(f"{sid} · {self.controller.status_label(essay.status)}")
            item.setData(Qt.UserRole, sid)
            self.student_list.addItem(item)

    def on_student_select(self, _):
        item = self.student_list.currentItem()
        if not item:
            return
        sid = item.data(Qt.UserRole)
        self.current_sid = sid
        essay = self.controller.session.essays[sid]
        self.panel.current_sid = sid
        self.panel.student_header.setText(f"{sid} • {essay.file_name or Path(essay.file_path).name}")

        rendered = self.renderer.render(essay.file_path, essay.annotations)
        self.essay_view.setHtml(rendered.html)
        self.build_panel(essay, rendered.unresolved_flags)

    def build_panel(self, essay, unresolved_flags: list[int]):
        self.panel.summary.blockSignals(True)
        self.panel.summary.setPlainText(essay.summary)
        self.panel.summary.blockSignals(False)

        while self.panel.compliance_layout.count():
            c = self.panel.compliance_layout.takeAt(0)
            if c.widget():
                c.widget().deleteLater()
        self.panel.compliance_widgets = []

        for idx, item in enumerate(essay.compliance):
            row = QWidget()
            rl = QHBoxLayout(row)
            req = QLabel(item.requirement)
            req.setWordWrap(True)
            status = QComboBox()
            status.addItems(["met", "partial", "missing"])
            status.setCurrentText(item.status or "partial")
            note = QLineEdit(item.note)
            revert = QPushButton("Revert")
            rl.addWidget(req, 3)
            rl.addWidget(status, 1)
            rl.addWidget(note, 2)
            rl.addWidget(revert)
            self.panel.compliance_layout.addWidget(row)
            status.currentTextChanged.connect(self.queue_autosave)
            note.textChanged.connect(self.queue_autosave)
            revert.clicked.connect(lambda _=None, i=idx, s=status, n=note: self.revert_compliance_field(i, s, n))
            self.panel.compliance_widgets.append({"status": status, "note": note})

        while self.panel.rubric_layout.count():
            c = self.panel.rubric_layout.takeAt(0)
            if c.widget():
                c.widget().deleteLater()
        self.panel.category_widgets = {}

        for i, cat in enumerate(essay.category_scores):
            box = QFrame()
            bl = QVBoxLayout(box)
            name = QLabel(cat.dimension)
            score = QDoubleSpinBox()
            score.setMaximum(100)
            score.setValue(float(cat.score))
            label = QLabel(cat.label)
            fb = QTextEdit(cat.feedback)
            fb.setMaximumHeight(80)
            needs = QLabel("Needs human review")
            needs.setVisible(any(a.dimension == cat.dimension for a in essay.annotations))
            revert = QPushButton("Revert")
            top = QHBoxLayout()
            top.addWidget(name)
            top.addWidget(needs)
            bl.addLayout(top)
            bl.addWidget(score)
            bl.addWidget(label)
            bl.addWidget(fb)
            bl.addWidget(revert)
            self.panel.rubric_layout.addWidget(box)
            score.valueChanged.connect(lambda _=None, i=i: self.update_label_from_score(i))
            score.valueChanged.connect(self.queue_autosave)
            fb.textChanged.connect(self.queue_autosave)
            revert.clicked.connect(lambda _=None, i=i, s=score, f=fb: self.revert_category_field(i, s, f))
            self.panel.category_widgets[cat.dimension] = {"score": score, "label": label, "feedback": fb, "index": i}

        self.panel.overall.blockSignals(True)
        self.panel.overall.setValue(float(essay.overall_grade))
        self.panel.overall.blockSignals(False)
        self.panel.overall_note.blockSignals(True)
        self.panel.overall_note.setPlainText(essay.overall_note)
        self.panel.overall_note.blockSignals(False)

        while self.panel.flags_layout.count():
            c = self.panel.flags_layout.takeAt(0)
            if c.widget():
                c.widget().deleteLater()
        for idx, ann in enumerate(essay.annotations):
            txt = f"{ann.dimension}: {ann.question}"
            if idx in unresolved_flags:
                txt += " (Locate required)"
            lbl = QLabel(txt)
            lbl.setWordWrap(True)
            self.panel.flags_layout.addWidget(lbl)

        self.refresh_diff_view(essay)

    def update_label_from_score(self, cat_index: int):
        sid = self.current_sid
        if not sid:
            return
        essay = self.controller.session.essays[sid]
        cat = essay.category_scores[cat_index]
        score = self.panel.category_widgets[cat.dimension]["score"].value()
        labels = [x.strip() for x in cat.label.split("/") if x.strip()] or [cat.label]
        if len(labels) == 1:
            label = labels[0]
        elif score < 0.4 * max(1, score):
            label = labels[0]
        elif score < 0.75 * max(1, score):
            label = labels[min(1, len(labels) - 1)]
        else:
            label = labels[-1]
        self.panel.category_widgets[cat.dimension]["label"].setText(label)

    def queue_autosave(self):
        self.panel.set_save_status("Saving…")
        self.autosave_timer.start(800)

    def _sync_ui_to_model(self):
        sid = self.current_sid
        if not sid:
            return
        essay = self.controller.session.essays[sid]
        essay.summary = self.panel.summary.toPlainText().strip()
        for i, c in enumerate(essay.compliance):
            c.status = self.panel.compliance_widgets[i]["status"].currentText()
            c.note = self.panel.compliance_widgets[i]["note"].text().strip()
        for cat in essay.category_scores:
            w = self.panel.category_widgets[cat.dimension]
            cat.score = w["score"].value()
            cat.label = w["label"].text().strip()
            cat.feedback = w["feedback"].toPlainText().strip()
        essay.overall_grade = self.panel.overall.value()
        essay.overall_note = self.panel.overall_note.toPlainText().strip()
        if essay.status == "ai graded":
            essay.status = "reviewed"

    def autosave(self):
        try:
            self.sync_ui_to_model()
            self.controller.save_session()
            self.panel.set_save_status("Saved ✓")
            self.refresh_students()
            self.refresh_diff_current()
        except Exception as exc:
            print(f"[autosave] failed: {exc}")
            self.panel.set_save_status("Save failed")

    def save_current(self):
        self.autosave_timer.stop()
        self.panel.set_save_status("Saving…")
        self.autosave()

    def revert_compliance(self, idx: int):
        if not self.current_sid:
            return
        base = self.controller.session.essays[self.current_sid].ai_original.compliance[idx]
        status = self.panel.compliance_table.cellWidget(idx, 1)
        note = self.panel.compliance_table.cellWidget(idx, 2)
        if isinstance(status, QComboBox):
            status.setCurrentText(base.status)
        if isinstance(note, QLineEdit):
            note.setText(base.note)
        self.queue_autosave()

    def revert_rubric(self, idx: int):
        if not self.current_sid:
            return
        base = self.controller.session.essays[self.current_sid].ai_original.category_scores[idx]
        score = self.panel.rubric_table.cellWidget(idx, 1)
        label = self.panel.rubric_table.cellWidget(idx, 2)
        fb = self.panel.rubric_table.cellWidget(idx, 3)
        if isinstance(score, QDoubleSpinBox):
            score.setValue(float(base.score))
        if isinstance(label, QLabel):
            label.setText(base.label)
        if isinstance(fb, QTextEdit):
            fb.setPlainText(base.feedback)
        self.queue_autosave()

    def revert_all(self):
        if not self.current_sid:
            return
        essay = self.controller.session.essays[self.current_sid]
            self._sync_ui_to_model()
            self.controller.save_session()
            self.panel.set_save_status("Saved ✓")
            if self.current_sid:
                self.refresh_students()
            if self.current_sid:
                self.refresh_diff_view(self.controller.session.essays[self.current_sid])
        except Exception:
            self.panel.set_save_status("Save failed (click Save to retry)")

    def save_current(self):
        self.panel.set_save_status("Saving…")
        self.autosave_timer.stop()
        self.autosave()

    def revert_category_field(self, idx: int, score_widget: QDoubleSpinBox, feedback_widget: QTextEdit):
        sid = self.current_sid
        if not sid:
            return
        base = self.controller.session.essays[sid].ai_original.category_scores[idx]
        score_widget.setValue(float(base.score))
        feedback_widget.setPlainText(base.feedback)
        self.queue_autosave()

    def revert_compliance_field(self, idx: int, status_widget: QComboBox, note_widget: QLineEdit):
        sid = self.current_sid
        if not sid:
            return
        base = self.controller.session.essays[sid].ai_original.compliance[idx]
        status_widget.setCurrentText(base.status)
        note_widget.setText(base.note)
        self.queue_autosave()

    def revert_all(self):
        sid = self.current_sid
        if not sid:
            return
        essay = self.controller.session.essays[sid]
        essay.summary = essay.ai_original.summary
        essay.category_scores = [CategoryScore(**c.__dict__) for c in essay.ai_original.category_scores]
        essay.compliance = [AssignmentComplianceItem(**c.__dict__) for c in essay.ai_original.compliance]
        essay.overall_grade = essay.ai_original.overall_grade
        essay.overall_note = essay.ai_original.overall_note
        essay.annotations = [type(a)(**a.__dict__) for a in essay.ai_original.annotations]
        self.on_student_select(self.student_list.currentItem(), None)
        self.queue_autosave()

    def refresh_diff_current(self):
        if not self.current_sid:
            self.panel.diff_view.setPlainText("Select a student to see differences.")
            return
        essay = self.controller.session.essays[self.current_sid]
        filt = self.panel.diff_filter.currentText()

        lines: list[str] = []
        add = lambda section, text: lines.append(f"[{section}] {text}")

        if essay.ai_original.summary != essay.summary:
            add("Summary", "Summary text changed")

        for i, item in enumerate(essay.compliance):
            base = essay.ai_original.compliance[i]
            if base.status != item.status or base.note != item.note:
                add("Compliance", f"{item.requirement}: {base.status}/{base.note} -> {item.status}/{item.note}")

        for i, cat in enumerate(essay.category_scores):
            base = essay.ai_original.category_scores[i]
            if base.score != cat.score:
                add("Rubric", f"{cat.dimension} score: {base.score} -> {cat.score}")
            if base.label != cat.label:
                add("Rubric", f"{cat.dimension} label: {base.label} -> {cat.label}")
            if base.feedback != cat.feedback:
                diff = " ".join(x for x in difflib.ndiff(base.feedback.split(), cat.feedback.split()) if x.startswith("+") or x.startswith("-"))
                add("Rubric", f"{cat.dimension} feedback changed: {diff}")

        if essay.ai_original.overall_grade != essay.overall_grade:
            add("Overall", f"Overall grade: {essay.ai_original.overall_grade} -> {essay.overall_grade}")
        if essay.ai_original.overall_note != essay.overall_note:
            add("Overall", "Overall feedback changed")

        for i, ann in enumerate(essay.annotations):
            base_note = essay.ai_original.annotations[i].teacher_note if i < len(essay.ai_original.annotations) else ""
            if base_note != ann.teacher_note:
                add("Flags", f"{ann.dimension} note changed")

        if filt != "All Changes":
            lines = [ln for ln in lines if ln.startswith(f"[{filt}]")]

        self.panel.diff_view.setPlainText("\n".join(lines) if lines else "No changes.")
        self.build_panel(essay, [])
        self.queue_autosave()

    def refresh_diff_view(self, essay):
        lines = ["AI Original vs Teacher Edited\n"]
        for i, cat in enumerate(essay.category_scores):
            base = essay.ai_original.category_scores[i]
            if base.score != cat.score:
                lines.append(f"[Score] {cat.dimension}: {base.score} -> {cat.score}")
            if base.feedback != cat.feedback:
                lines.append(f"[Feedback] {cat.dimension} changed")
                diff = difflib.ndiff(base.feedback.split(), cat.feedback.split())
                lines.append(" ".join([d for d in diff if d.startswith("+") or d.startswith("-")]))
        if essay.ai_original.overall_grade != essay.overall_grade:
            lines.append(f"[Overall grade] {essay.ai_original.overall_grade} -> {essay.overall_grade}")
        if essay.ai_original.overall_note != essay.overall_note:
            lines.append("[Overall note] changed")
        for i, item in enumerate(essay.compliance):
            base = essay.ai_original.compliance[i]
            if base.status != item.status or base.note != item.note:
                lines.append(f"[Compliance] {item.requirement}: {base.status}/{base.note} -> {item.status}/{item.note}")
        if len(lines) == 1:
            lines.append("No teacher edits yet.")
        self.panel.diff_box.setPlainText("\n".join(lines))

    def mark_finalized(self):
        if not self.current_sid:
            return
        self.save_current()
        self.controller.session.essays[self.current_sid].status = "finalized"
        self.controller.save_session()
        self.refresh_students()

    def select_next(self):
        row = self.student_list.currentRow()
        if row < self.student_list.count() - 1:
            self.student_list.setCurrentRow(row + 1)

    def select_prev(self):
        row = self.student_list.currentRow()
        if row > 0:
            self.student_list.setCurrentRow(row - 1)

    def focus_flag(self, index: int):
        if not self.current_sid:
            return
        essay = self.controller.session.essays[self.current_sid]
        if index < len(essay.annotations):
            ann = essay.annotations[index]
            QMessageBox.information(self, "Human Review Flag", f"{ann.dimension}\n\n{ann.question}")

    def open_image_dialog(self, image_id: str):
        QMessageBox.information(self, "Image Preview", "Image clicked. If it is small in the essay, zoom in with browser controls.")

    def refresh_integrity(self):
        lines = ["Cross-Essay Similarity\n======================="]
        for f in self.controller.session.integrity_flags:
            lines.append(f"{f.student_a} ↔ {f.student_b}: {f.score}")
        lines += ["\nAI Usage Signals (non-definitive)\n======================="]
        for sid, essay in sorted(self.controller.session.essays.items()):
            lines.append(f"{sid}: {essay.ai_suspicion_score} | {essay.ai_suspicion_note}")
        self.integrity_text.setPlainText("\n".join(lines))


    def export_outputs(self):
        if not self.controller.session.essays:
            QMessageBox.warning(self, "Nothing to export", "No graded essays found.")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not out_dir:
            return
        try:
            self.save_current()
            csv_path = export_canvas_csv(self.controller.session, out_dir)
            files = export_student_feedback_files(self.controller.session, out_dir)
            QMessageBox.information(self, "Export complete", f"CSV: {csv_path}\nFeedback files: {len(files)}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def load_session(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load Session", "sessions", "Session Files (*.json)")
        if not f:
            return
        self.controller.load_session(f)
        self.rubric_text.setPlainText(self.controller.session.rubric_text)
        self.assignment_text.setPlainText(self.controller.session.assignment_text)
        self.refresh_students()
        self.refresh_integrity()
        self.set_no_selection_state()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
