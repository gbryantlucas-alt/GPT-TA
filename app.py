from __future__ import annotations

import difflib
import json
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from grader_app.controller import GraderController
from grader_app.docx_renderer import DocxHtmlRenderer
from grader_app.exporters import export_canvas_csv, export_student_feedback_files
from grader_app.models import Annotation, AssignmentComplianceItem, CategoryScore
from grader_app.parsers import infer_student_id, read_text

SETTINGS_PATH = Path("settings.json")


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {"api_key": "", "model": "gpt-4.1-mini", "workers": 6}


class EssayPage(QWebEnginePage):
    flag_clicked = Signal(int)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame):
        if url.toString().startswith("flag://"):
            self.flag_clicked.emit(int(url.toString().split("://", 1)[1]))
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


class UploadDropArea(QFrame):
    files_dropped = Signal(list)

    def __init__(self, text: str):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropArea")
        layout = QVBoxLayout(self)
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.files_dropped.emit(paths)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Essay Grader")
        self.resize(1700, 980)

        self.settings = load_settings()
        self.controller = GraderController()
        self.renderer = DocxHtmlRenderer()
        self.essay_paths: list[str] = []
        self.essay_meta: dict[str, dict] = {}
        self.current_sid: str | None = None

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.autosave)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_nav())
        self.pages = QStackedWidget()
        root_layout.addWidget(self.pages)

        self.setup_page = self._build_setup_page()
        self.review_page = self._build_review_page()
        self.integrity_page = self._build_integrity_page()
        self.export_page = self._build_export_page()
        for p in [self.setup_page, self.review_page, self.integrity_page, self.export_page]:
            self.pages.addWidget(p)

        self._apply_styles()
        self.switch_page("Setup")
        self.set_no_selection_state()

    # ---------- shell ----------
    def _build_top_nav(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopNav")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)

        title = QLabel("✎ Essay Grader")
        title.setObjectName("TopTitle")
        row.addWidget(title)

        self.nav_buttons: dict[str, QPushButton] = {}
        for name in ["Setup", "Review", "Integrity", "Export"]:
            b = QPushButton(name)
            b.setObjectName("NavBtn")
            b.clicked.connect(lambda _=None, n=name: self.switch_page(n))
            row.addWidget(b)
            self.nav_buttons[name] = b

        row.addStretch(1)
        self.session_title = QLabel("Scene Analysis Essay")
        self.session_title.setObjectName("SessionTitle")
        row.addWidget(self.session_title)

        self.sessions_btn = QPushButton("← Sessions")
        self.sessions_btn.setObjectName("GhostBtn")
        self.sessions_btn.clicked.connect(self.load_session)
        row.addWidget(self.sessions_btn)

        self.primary_btn = QPushButton("Start Grading")
        self.primary_btn.clicked.connect(self.start_grading)
        row.addWidget(self.primary_btn)
        return bar

    def switch_page(self, name: str):
        mapping = {"Setup": 0, "Review": 1, "Integrity": 2, "Export": 3}
        self.pages.setCurrentIndex(mapping[name])
        for n, b in self.nav_buttons.items():
            b.setProperty("active", n == name)
            b.style().unpolish(b)
            b.style().polish(b)
        self.primary_btn.setVisible(name == "Setup")

    # ---------- setup ----------
    def _build_setup_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QLabel("Session Setup")
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        top_cards = QHBoxLayout()
        top_cards.addWidget(self._build_rubric_card())
        top_cards.addWidget(self._build_assignment_card())
        layout.addLayout(top_cards)

        layout.addWidget(self._build_essays_card(), 1)
        layout.addWidget(self._build_settings_card())

        self.batch_progress = QProgressBar()
        self.batch_progress.setValue(0)
        self.batch_progress.setVisible(False)
        self.batch_status = QLabel("Ready")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(False)
        foot = QHBoxLayout()
        foot.addWidget(self.batch_status)
        foot.addWidget(self.batch_progress, 1)
        foot.addWidget(self.cancel_btn)
        layout.addLayout(foot)
        return w

    def _build_rubric_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        h = QHBoxLayout()
        h.addWidget(QLabel("1. Rubric"))
        self.rubric_status = QLabel("Saved (not parsed)")
        self.rubric_status.setObjectName("Pill")
        h.addStretch(1)
        h.addWidget(self.rubric_status)
        lay.addLayout(h)

        self.rubric_tabs = QTabWidget()
        upload = QWidget(); ul = QVBoxLayout(upload)
        self.rubric_drop = UploadDropArea("Drag & drop a .docx or .pdf file here")
        self.rubric_drop.files_dropped.connect(lambda p: self.load_rubric_from_files(p))
        ul.addWidget(self.rubric_drop)
        b = QPushButton("Browse")
        b.clicked.connect(self.select_rubric_file)
        ul.addWidget(b, 0, Qt.AlignHCenter)
        self.rubric_file_label = QLabel("")
        ul.addWidget(self.rubric_file_label)

        paste = QWidget(); pl = QVBoxLayout(paste)
        self.rubric_text = QTextEdit(); pl.addWidget(self.rubric_text)
        self.rubric_tabs.addTab(upload, "Upload File")
        self.rubric_tabs.addTab(paste, "Paste Text")
        lay.addWidget(self.rubric_tabs)
        return card

    def _build_assignment_card(self) -> QWidget:
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card)
        h = QHBoxLayout()
        h.addWidget(QLabel("2. Assignment Sheet"))
        self.assignment_words = QLabel("0 words")
        self.assignment_words.setObjectName("PillGreen")
        h.addStretch(1); h.addWidget(self.assignment_words)
        lay.addLayout(h)

        self.assignment_tabs = QTabWidget()
        upload = QWidget(); ul = QVBoxLayout(upload)
        self.assignment_drop = UploadDropArea("Drag & drop a .docx or .pdf file here")
        self.assignment_drop.files_dropped.connect(lambda p: self.load_assignment_from_files(p))
        ul.addWidget(self.assignment_drop)
        b = QPushButton("Browse")
        b.clicked.connect(self.select_assignment_file)
        ul.addWidget(b, 0, Qt.AlignHCenter)
        self.assignment_file_label = QLabel("")
        ul.addWidget(self.assignment_file_label)

        paste = QWidget(); pl = QVBoxLayout(paste)
        self.assignment_text = QTextEdit(); pl.addWidget(self.assignment_text)
        self.assignment_tabs.addTab(upload, "Upload File")
        self.assignment_tabs.addTab(paste, "Paste Text")
        lay.addWidget(self.assignment_tabs)
        return card

    def _build_essays_card(self) -> QWidget:
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card)
        h = QHBoxLayout()
        h.addWidget(QLabel("3. Student Essays"))
        self.essay_count_pill = QLabel("0 uploaded")
        self.essay_count_pill.setObjectName("PillGreen")
        h.addStretch(1); h.addWidget(self.essay_count_pill)
        lay.addLayout(h)

        self.essay_drop = UploadDropArea("Drag & drop all student .docx files here")
        self.essay_drop.files_dropped.connect(lambda p: self.load_essays(p))
        lay.addWidget(self.essay_drop)
        b = QPushButton("Browse Files")
        b.clicked.connect(self.select_essays)
        lay.addWidget(b, 0, Qt.AlignHCenter)

        self.essay_table = QTableWidget(0, 4)
        self.essay_table.setHorizontalHeaderLabels(["File", "Student", "Word Count", "Images"])
        self.essay_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.essay_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.essay_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.essay_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.essay_table.verticalHeader().setVisible(False)
        lay.addWidget(self.essay_table, 1)
        return card

    def _build_settings_card(self) -> QWidget:
        card = QFrame(); card.setObjectName("Card")
        lay = QGridLayout(card)
        lay.addWidget(QLabel("OpenAI API Key"), 0, 0)
        self.api_key_input = QLineEdit(self.settings.get("api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.api_key_input, 0, 1)
        lay.addWidget(QLabel("Model"), 1, 0)
        self.model_input = QLineEdit(self.settings.get("model", "gpt-4.1-mini"))
        lay.addWidget(self.model_input, 1, 1)
        lay.addWidget(QLabel("Workers"), 2, 0)
        self.workers_input = QLineEdit(str(self.settings.get("workers", 6)))
        lay.addWidget(self.workers_input, 2, 1)
        save = QPushButton("Save Settings")
        save.clicked.connect(self.save_settings)
        lay.addWidget(save, 0, 2, 3, 1)
        return card

    def save_settings(self):
        self.settings = {
            "api_key": self.api_key_input.text().strip(),
            "model": self.model_input.text().strip(),
            "workers": int(self.workers_input.text() or 6),
        }
        SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    # ---------- review ----------
    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QFrame(); left.setObjectName("SidePanel")
        left.setMinimumWidth(240); left.setMaximumWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        self.search_students = QLineEdit(); self.search_students.setPlaceholderText("Search students...")
        self.search_students.textChanged.connect(self.refresh_student_list_filtered)
        ll.addWidget(self.search_students)
        self.filter_status = QComboBox(); self.filter_status.addItems(["All", "Unreviewed", "In Progress", "Finalized", "Failed"])
        self.filter_status.currentTextChanged.connect(self.refresh_student_list_filtered)
        ll.addWidget(self.filter_status)
        self.finalized_count = QLabel("0/0 finalized")
        ll.addWidget(self.finalized_count)
        self.student_list = QListWidget()
        self.student_list.currentItemChanged.connect(self.on_student_selected)
        ll.addWidget(self.student_list, 1)
        layout.addWidget(left)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        center = QFrame(); cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.review_student_title = QLabel("No student selected")
        self.review_student_title.setObjectName("ReviewTitle")
        top.addWidget(self.review_student_title)
        top.addStretch(1)
        self.export_docx_btn = QPushButton("↓ DOCX")
        self.export_docx_btn.clicked.connect(self.export_single_student_docx)
        top.addWidget(self.export_docx_btn)
        cl.addLayout(top)

        self.summary_toggle = QToolButton()
        self.summary_toggle.setText("▸ Summary & Compliance")
        self.summary_toggle.setCheckable(True)
        self.summary_toggle.setChecked(False)
        self.summary_toggle.toggled.connect(lambda checked: self.summary_banner.setVisible(checked))
        cl.addWidget(self.summary_toggle)
        self.summary_banner = QLabel("No scores yet.")
        self.summary_banner.setObjectName("Banner")
        self.summary_banner.setVisible(False)
        self.summary_banner.setWordWrap(True)
        cl.addWidget(self.summary_banner)

        self.essay_view = QWebEngineView()
        self.essay_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.essay_page = EssayPage(self.essay_view)
        self.essay_page.flag_clicked.connect(self.focus_flag)
        self.essay_view.setPage(self.essay_page)
        cl.addWidget(self.essay_view, 1)
        splitter.addWidget(center)

        right = QFrame(); right.setMinimumWidth(430)
        rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        self.save_status = QLabel("Saved ✓")
        head.addWidget(self.save_status)
        head.addStretch(1)
        self.view_mode = QComboBox(); self.view_mode.addItems(["Current", "Diff"])
        self.view_mode.currentTextChanged.connect(self.on_view_mode_changed)
        head.addWidget(self.view_mode)
        rl.addLayout(head)

        self.right_stack = QStackedWidget()
        rl.addWidget(self.right_stack, 1)

        self.current_panel = self._build_review_current_panel()
        self.diff_panel = self._build_diff_panel()
        self.right_stack.addWidget(self.current_panel)
        self.right_stack.addWidget(self.diff_panel)

        bottom = QFrame(); bottom.setObjectName("BottomBar")
        bl = QHBoxLayout(bottom)
        self.total_label = QLabel("Total: —")
        bl.addWidget(self.total_label)
        bl.addStretch(1)
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.clicked.connect(self.save_current)
        self.finalize_btn = QPushButton("Finalize")
        self.finalize_btn.setObjectName("FinalBtn")
        self.finalize_btn.clicked.connect(self.mark_finalized)
        bl.addWidget(self.save_btn)
        bl.addWidget(self.finalize_btn)
        rl.addWidget(bottom)

        splitter.addWidget(right)
        splitter.setCollapsible(1, False)
        splitter.setSizes([980, 500])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.review_splitter = splitter

        return page

    def _build_review_current_panel(self) -> QWidget:
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        wl.addWidget(scroll)
        content = QWidget(); scroll.setWidget(content)
        cl = QVBoxLayout(content)

        self.review_tabs = QTabWidget()
        cl.addWidget(self.review_tabs)

        # Summary & Compliance
        summary_tab = QWidget(); sl = QVBoxLayout(summary_tab)
        sl.addWidget(QLabel("Summary"))
        self.summary_edit = QTextEdit(); self.summary_edit.textChanged.connect(self.queue_autosave)
        sl.addWidget(self.summary_edit)
        sl.addWidget(QLabel("Assignment Compliance"))
        self.compliance_table = QTableWidget(0, 4)
        self.compliance_table.setHorizontalHeaderLabels(["Requirement", "Status", "Note", "Revert"])
        self.compliance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.compliance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.compliance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.compliance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.compliance_table.verticalHeader().setVisible(False)
        sl.addWidget(self.compliance_table)
        self.review_tabs.addTab(summary_tab, "Summary & Compliance")

        # Rubric
        rubric_tab = QWidget(); rl = QVBoxLayout(rubric_tab)
        self.revert_all_btn = QPushButton("Revert All")
        self.revert_all_btn.clicked.connect(self.revert_all)
        rl.addWidget(self.revert_all_btn, 0, Qt.AlignLeft)
        self.rubric_table = QTableWidget(0, 5)
        self.rubric_table.setHorizontalHeaderLabels(["Dimension", "Score", "Label", "Feedback", "Revert"])
        self.rubric_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.rubric_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.rubric_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.rubric_table.verticalHeader().setVisible(False)
        rl.addWidget(self.rubric_table)
        self.review_tabs.addTab(rubric_tab, "Rubric")

        # Flags
        flags_tab = QWidget(); fl = QVBoxLayout(flags_tab)
        self.flags_table = QTableWidget(0, 5)
        self.flags_table.setHorizontalHeaderLabels(["Dimension", "Excerpt", "Question", "Teacher Note", "Jump"])
        self.flags_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.flags_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.flags_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.flags_table.verticalHeader().setVisible(False)
        fl.addWidget(self.flags_table)
        self.review_tabs.addTab(flags_tab, "Flags")

        # Overall
        overall_tab = QWidget(); ol = QVBoxLayout(overall_tab)
        self.overall_score = QDoubleSpinBox(); self.overall_score.setMaximum(1000); self.overall_score.valueChanged.connect(self.queue_autosave)
        self.overall_note = QTextEdit(); self.overall_note.textChanged.connect(self.queue_autosave)
        ol.addWidget(QLabel("Overall Grade")); ol.addWidget(self.overall_score)
        ol.addWidget(QLabel("Overall Feedback")); ol.addWidget(self.overall_note)
        self.review_tabs.addTab(overall_tab, "Overall")

        return wrapper

    def _build_diff_panel(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w)
        row = QHBoxLayout(); row.addWidget(QLabel("Section"))
        self.diff_filter = QComboBox(); self.diff_filter.addItems(["All Changes", "Summary", "Compliance", "Rubric", "Flags", "Overall"])
        self.diff_filter.currentTextChanged.connect(self.refresh_diff)
        row.addWidget(self.diff_filter)
        l.addLayout(row)
        self.diff_text = QTextEdit(); self.diff_text.setReadOnly(True)
        l.addWidget(self.diff_text)
        return w

    # ---------- integrity/export ----------
    def _build_integrity_page(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 20)
        l.addWidget(QLabel("Integrity"))
        self.similarity_table = QTableWidget(0, 3)
        self.similarity_table.setHorizontalHeaderLabels(["Student A", "Student B", "Similarity %"])
        self.similarity_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.similarity_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.similarity_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        l.addWidget(self.similarity_table)
        self.ai_signal_table = QTableWidget(0, 3)
        self.ai_signal_table.setHorizontalHeaderLabels(["Student", "Suspicion Score", "Caveat"])
        self.ai_signal_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ai_signal_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ai_signal_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        l.addWidget(self.ai_signal_table)
        return w

    def _build_export_page(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 20)
        l.addWidget(QLabel("Export"))
        btn1 = QPushButton("Export to Canvas CSV")
        btn1.clicked.connect(self.export_canvas_only)
        btn2 = QPushButton("Export Student Feedback Files")
        btn2.clicked.connect(self.export_feedback_only)
        btn3 = QPushButton("Export Both")
        btn3.clicked.connect(self.export_outputs)
        self.export_status = QLabel("No exports yet.")
        l.addWidget(btn1); l.addWidget(btn2); l.addWidget(btn3); l.addWidget(self.export_status)
        l.addStretch(1)
        return w

    # ---------- setup actions ----------
    def load_rubric_from_files(self, paths: list[str]):
        if not paths:
            return
        path = paths[0]
        self.controller.session.rubric_text = read_text(path)
        self.rubric_text.setPlainText(self.controller.session.rubric_text)
        self.rubric_file_label.setText(f"✓ {Path(path).name}")

    def load_assignment_from_files(self, paths: list[str]):
        if not paths:
            return
        path = paths[0]
        txt = read_text(path)
        self.controller.session.assignment_text = txt
        self.assignment_text.setPlainText(txt)
        self.assignment_file_label.setText(f"✓ {Path(path).name}")
        self.assignment_words.setText(f"{len(txt.split())} words")

    def select_rubric_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select rubric", "", "Docs (*.docx *.pdf)")
        if f:
            self.load_rubric_from_files([f])

    def select_assignment_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select assignment", "", "Docs (*.docx *.pdf)")
        if f:
            self.load_assignment_from_files([f])

    def select_essays(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select essays", "", "Word Files (*.docx)")
        self.load_essays(files)

    def load_essays(self, files: list[str]):
        new_files = [f for f in files if Path(f).suffix.lower() == ".docx"]
        if not new_files:
            return
        self.essay_paths = sorted(set(self.essay_paths + new_files))
        self.essay_meta = {}
        self.essay_table.setRowCount(len(self.essay_paths))
        for i, path in enumerate(self.essay_paths):
            meta = self.compute_essay_meta(path)
            self.essay_meta[path] = meta
            for c, val in enumerate([Path(path).name, meta["student"], str(meta["words"]), str(meta["images"])]):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.essay_table.setItem(i, c, item)
        self.essay_count_pill.setText(f"{len(self.essay_paths)} uploaded")

    def compute_essay_meta(self, path: str) -> dict:
        text = read_text(path)
        words = len(text.split())
        student = infer_student_id(path, text)
        image_count = 0
        try:
            with zipfile.ZipFile(path) as zf:
                image_count = len([n for n in zf.namelist() if n.startswith("word/media/")])
        except Exception:
            image_count = 0
        return {"student": student, "words": words, "images": image_count}

    def start_grading(self):
        assignment_text = self.assignment_text.toPlainText().strip()
        rubric_text = self.rubric_text.toPlainText().strip()
        if not assignment_text:
            QMessageBox.warning(self, "Missing assignment", "Please upload or paste assignment sheet.")
            return
        if not self.essay_paths:
            QMessageBox.warning(self, "Missing essays", "Please upload student essays.")
            return
        self.controller.session.assignment_text = assignment_text
        self.controller.session.rubric_text = rubric_text
        self.controller.save_session()

        self.save_settings()
        api_key = self.settings.get("api_key", "")
        model = self.settings.get("model", "gpt-4.1-mini")
        workers = int(self.settings.get("workers", 6))
        if not api_key:
            QMessageBox.warning(self, "Missing API key", "Set OpenAI API key in Setup > Settings area.")
            return

        self.batch_progress.setVisible(True)
        self.batch_progress.setMaximum(len(self.essay_paths))
        self.batch_progress.setValue(0)
        self.batch_status.setText("Parsing rubric and grading essays...")

        self.worker = BatchWorker(self.controller, api_key, model, self.essay_paths, workers)
        self.worker.progress.connect(self.on_grade_progress)
        self.worker.done.connect(self.on_grade_done)
        self.worker.failed.connect(lambda err: QMessageBox.critical(self, "Grading failed", err))
        self.worker.start()

    def on_grade_progress(self, sid: str):
        self.batch_progress.setValue(min(self.batch_progress.value() + 1, self.batch_progress.maximum()))
        self.batch_status.setText(f"Processed {sid}")
        self.refresh_student_list_filtered()

    def on_grade_done(self):
        self.batch_status.setText("Batch complete")
        self.refresh_student_list_filtered()
        self.refresh_integrity_tables()
        self.controller.save_session()

    # ---------- review bindings ----------
    def refresh_student_list_filtered(self):
        q = self.search_students.text().strip().lower() if hasattr(self, "search_students") else ""
        filt = self.filter_status.currentText() if hasattr(self, "filter_status") else "All"

        self.student_list.blockSignals(True)
        self.student_list.clear()
        finals = 0
        total = len(self.controller.session.essays)
        for sid in self.controller.student_ids():
            e = self.controller.session.essays[sid]
            if e.status == "finalized":
                finals += 1
            if q and q not in sid.lower():
                continue
            mapping = {"Unreviewed": "ai graded", "In Progress": "reviewed", "Finalized": "finalized", "Failed": "failed"}
            if filt != "All" and e.status != mapping.get(filt, e.status):
                continue
            dot = "●"
            item = QListWidgetItem(f"{dot} {sid}")
            item.setData(Qt.UserRole, sid)
            self.student_list.addItem(item)
        self.student_list.blockSignals(False)
        self.finalized_count.setText(f"{finals}/{total} finalized")

    def set_no_selection_state(self):
        self.current_sid = None
        self.review_student_title.setText("No student selected")
        self.essay_view.setHtml("<html><body style='font-family:Segoe UI;padding:30px;color:#6b7280;'>Select a student to review.</body></html>")
        self.summary_banner.setText("No scores yet.")
        self.summary_edit.setPlainText("")
        self.compliance_table.setRowCount(0)
        self.rubric_table.setRowCount(0)
        self.flags_table.setRowCount(0)
        self.overall_score.setValue(0)
        self.overall_note.setPlainText("")
        self.total_label.setText("Total: —")
        self.diff_text.setPlainText("No scores yet.")

    def on_student_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if not current:
            self.set_no_selection_state()
            return
        sid = current.data(Qt.UserRole)
        if not sid:
            self.set_no_selection_state()
            return
        self.current_sid = sid
        essay = self.controller.session.essays[sid]
        self.review_student_title.setText(sid)

        rendered = self.renderer.render(essay.file_path, essay.annotations)
        self.essay_view.setHtml(rendered.html)
        self.summary_banner.setText(essay.summary or "No scores yet.")

        self.summary_edit.blockSignals(True)
        self.summary_edit.setPlainText(essay.summary)
        self.summary_edit.blockSignals(False)
        self.overall_score.blockSignals(True)
        self.overall_score.setValue(float(essay.overall_grade))
        self.overall_score.blockSignals(False)
        self.overall_note.blockSignals(True)
        self.overall_note.setPlainText(essay.overall_note)
        self.overall_note.blockSignals(False)
        self.total_label.setText(f"Total: {essay.overall_grade if essay.overall_grade else '—'}")

        self.populate_compliance(essay)
        self.populate_rubric(essay)
        self.populate_flags(essay)
        self.refresh_diff()

    def populate_compliance(self, essay):
        t = self.compliance_table
        t.setRowCount(len(essay.compliance))
        for i, c in enumerate(essay.compliance):
            item = QTableWidgetItem(c.requirement)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            t.setItem(i, 0, item)

            status = QComboBox(); status.addItems(["met", "partial", "missing"]); status.setCurrentText(c.status or "partial")
            status.currentTextChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 1, status)
            note = QLineEdit(c.note); note.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 2, note)
            rev = QPushButton("Revert")
            rev.clicked.connect(lambda _=None, idx=i: self.revert_compliance(idx))
            t.setCellWidget(i, 3, rev)

    def populate_rubric(self, essay):
        t = self.rubric_table
        t.setRowCount(len(essay.category_scores))
        for i, r in enumerate(essay.category_scores):
            it = QTableWidgetItem(r.dimension); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            t.setItem(i, 0, it)
            score = QDoubleSpinBox(); score.setMaximum(1000); score.setValue(float(r.score)); score.valueChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 1, score)
            label = QLabel(r.label)
            t.setCellWidget(i, 2, label)
            fb = QTextEdit(r.feedback); fb.setMinimumHeight(74); fb.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 3, fb)
            rev = QPushButton("Revert")
            rev.clicked.connect(lambda _=None, idx=i: self.revert_rubric(idx))
            t.setCellWidget(i, 4, rev)
            t.setRowHeight(i, 92)

    def populate_flags(self, essay):
        t = self.flags_table
        t.setRowCount(len(essay.annotations))
        for i, a in enumerate(essay.annotations):
            for col, txt in enumerate([a.dimension, a.excerpt, a.question]):
                it = QTableWidgetItem(txt); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(i, col, it)
            note = QLineEdit(a.teacher_note); note.textChanged.connect(self.queue_autosave)
            t.setCellWidget(i, 3, note)
            btn = QPushButton("Jump")
            btn.clicked.connect(lambda _=None, idx=i: self.jump_to_flag(idx))
            t.setCellWidget(i, 4, btn)

    def focus_flag(self, idx: int):
        self.review_tabs.setCurrentIndex(2)
        self.flags_table.selectRow(idx)

    def jump_to_flag(self, idx: int):
        self.essay_view.page().runJavaScript(
            f"const el=document.querySelector('mark[data-flag=\"{idx}\"]'); if(el) el.scrollIntoView({{behavior:'smooth', block:'center'}});"
        )

    def queue_autosave(self):
        if not self.current_sid:
            return
        self.save_status.setText("Saving…")
        self.autosave_timer.start(800)

    def sync_ui_to_model(self):
        if not self.current_sid:
            return
        e = self.controller.session.essays[self.current_sid]
        e.summary = self.summary_edit.toPlainText().strip()
        for i, c in enumerate(e.compliance):
            status = self.compliance_table.cellWidget(i, 1)
            note = self.compliance_table.cellWidget(i, 2)
            if isinstance(status, QComboBox):
                c.status = status.currentText()
            if isinstance(note, QLineEdit):
                c.note = note.text().strip()
        for i, r in enumerate(e.category_scores):
            score = self.rubric_table.cellWidget(i, 1)
            label = self.rubric_table.cellWidget(i, 2)
            fb = self.rubric_table.cellWidget(i, 3)
            if isinstance(score, QDoubleSpinBox):
                r.score = score.value()
            if isinstance(label, QLabel):
                r.label = label.text().strip()
            if isinstance(fb, QTextEdit):
                r.feedback = fb.toPlainText().strip()
        for i, a in enumerate(e.annotations):
            note = self.flags_table.cellWidget(i, 3)
            if isinstance(note, QLineEdit):
                a.teacher_note = note.text().strip()
        e.overall_grade = self.overall_score.value()
        e.overall_note = self.overall_note.toPlainText().strip()
        if e.status == "ai graded":
            e.status = "reviewed"

    def autosave(self):
        try:
            self.sync_ui_to_model()
            self.controller.save_session()
            self.save_status.setText("Saved ✓")
            self.total_label.setText(f"Total: {self.controller.session.essays[self.current_sid].overall_grade if self.current_sid else '—'}")
            self.refresh_diff()
            self.refresh_student_list_filtered()
        except Exception as exc:
            self.save_status.setText("Save failed")
            print(f"[autosave] {exc}")

    def save_current(self):
        self.autosave_timer.stop()
        self.save_status.setText("Saving…")
        self.autosave()

    def revert_compliance(self, idx: int):
        if not self.current_sid:
            return
        base = self.controller.session.essays[self.current_sid].ai_original.compliance[idx]
        status = self.compliance_table.cellWidget(idx, 1)
        note = self.compliance_table.cellWidget(idx, 2)
        if isinstance(status, QComboBox):
            status.setCurrentText(base.status)
        if isinstance(note, QLineEdit):
            note.setText(base.note)
        self.queue_autosave()

    def revert_rubric(self, idx: int):
        if not self.current_sid:
            return
        base = self.controller.session.essays[self.current_sid].ai_original.category_scores[idx]
        score = self.rubric_table.cellWidget(idx, 1)
        label = self.rubric_table.cellWidget(idx, 2)
        fb = self.rubric_table.cellWidget(idx, 3)
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
        e = self.controller.session.essays[self.current_sid]
        e.summary = e.ai_original.summary
        e.category_scores = [CategoryScore(**c.__dict__) for c in e.ai_original.category_scores]
        e.compliance = [AssignmentComplianceItem(**c.__dict__) for c in e.ai_original.compliance]
        e.overall_grade = e.ai_original.overall_grade
        e.overall_note = e.ai_original.overall_note
        e.annotations = [Annotation(**a.__dict__) for a in e.ai_original.annotations]
        self.on_student_selected(self.student_list.currentItem(), None)
        self.queue_autosave()

    def on_view_mode_changed(self, mode: str):
        self.right_stack.setCurrentIndex(1 if mode == "Diff" else 0)
        if mode == "Diff":
            self.refresh_diff()

    def refresh_diff(self):
        if not self.current_sid:
            self.diff_text.setPlainText("No student selected.")
            return
        essay = self.controller.session.essays[self.current_sid]
        filt = self.diff_filter.currentText()
        rows: list[str] = []
        add = lambda sec, txt: rows.append(f"[{sec}] {txt}")

        if essay.ai_original.summary != essay.summary:
            add("Summary", "Summary changed")
        for i, c in enumerate(essay.compliance):
            b = essay.ai_original.compliance[i]
            if b.status != c.status or b.note != c.note:
                add("Compliance", f"{c.requirement}: {b.status}/{b.note} -> {c.status}/{c.note}")
        for i, r in enumerate(essay.category_scores):
            b = essay.ai_original.category_scores[i]
            if b.score != r.score:
                add("Rubric", f"{r.dimension} score: {b.score} -> {r.score}")
            if b.feedback != r.feedback:
                diff = " ".join(x for x in difflib.ndiff(b.feedback.split(), r.feedback.split()) if x.startswith("+") or x.startswith("-"))
                add("Rubric", f"{r.dimension} feedback: {diff}")
        if essay.ai_original.overall_grade != essay.overall_grade or essay.ai_original.overall_note != essay.overall_note:
            add("Overall", f"Grade/feedback changed")
        for i, a in enumerate(essay.annotations):
            base_note = essay.ai_original.annotations[i].teacher_note if i < len(essay.ai_original.annotations) else ""
            if a.teacher_note != base_note:
                add("Flags", f"{a.dimension} teacher note changed")

        if filt != "All Changes":
            rows = [r for r in rows if r.startswith(f"[{filt}]")]
        self.diff_text.setPlainText("\n".join(rows) if rows else "No changes.")

    # ---------- integrity/export ----------
    def refresh_integrity_tables(self):
        sim = self.controller.session.integrity_flags
        self.similarity_table.setRowCount(len(sim))
        for i, f in enumerate(sim):
            self.similarity_table.setItem(i, 0, QTableWidgetItem(f.student_a))
            self.similarity_table.setItem(i, 1, QTableWidgetItem(f.student_b))
            self.similarity_table.setItem(i, 2, QTableWidgetItem(f"{round(f.score * 100, 1)}%"))

        essays = list(sorted(self.controller.session.essays.items()))
        self.ai_signal_table.setRowCount(len(essays))
        for i, (sid, e) in enumerate(essays):
            self.ai_signal_table.setItem(i, 0, QTableWidgetItem(sid))
            self.ai_signal_table.setItem(i, 1, QTableWidgetItem(str(e.ai_suspicion_score)))
            self.ai_signal_table.setItem(i, 2, QTableWidgetItem(e.ai_suspicion_note))

    def export_canvas_only(self):
        out = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not out:
            return
        path = export_canvas_csv(self.controller.session, out)
        self.export_status.setText(f"Canvas CSV exported: {path}")

    def export_feedback_only(self):
        out = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not out:
            return
        files = export_student_feedback_files(self.controller.session, out)
        self.export_status.setText(f"Feedback exported: {len(files)} files")

    def export_outputs(self):
        out = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not out:
            return
        self.save_current()
        csv_path = export_canvas_csv(self.controller.session, out)
        files = export_student_feedback_files(self.controller.session, out)
        self.export_status.setText(f"Exported CSV + {len(files)} feedback files")
        QMessageBox.information(self, "Export complete", f"CSV: {csv_path}\nFeedback files: {len(files)}")

    def export_single_student_docx(self):
        if not self.current_sid:
            return
        out = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not out:
            return
        from grader_app.models import BatchSession

        sess = BatchSession(session_id=self.controller.session.session_id)
        sess.essays[self.current_sid] = self.controller.session.essays[self.current_sid]
        files = export_student_feedback_files(sess, out)
        QMessageBox.information(self, "Exported", f"Created: {files[0] if files else 'none'}")

    # ---------- misc ----------
    def mark_finalized(self):
        if not self.current_sid:
            return
        self.save_current()
        self.controller.session.essays[self.current_sid].status = "finalized"
        self.controller.save_session()
        self.refresh_student_list_filtered()

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", "sessions", "Session Files (*.json)")
        if not path:
            return
        self.controller.load_session(path)
        self.rubric_text.setPlainText(self.controller.session.rubric_text)
        self.assignment_text.setPlainText(self.controller.session.assignment_text)
        self.assignment_words.setText(f"{len(self.controller.session.assignment_text.split())} words")
        self.refresh_student_list_filtered()
        self.refresh_integrity_tables()
        self.set_no_selection_state()

    def _apply_styles(self):
        self.setStyleSheet(
            """
QMainWindow, QWidget { background:#f3f5f9; color:#0f2742; font-family:'Segoe UI'; font-size:14px; }
#TopNav { background:#123a67; }
#TopTitle { color:white; font-size:32px; font-weight:700; }
#SessionTitle { color:#d9e6f3; }
QPushButton#NavBtn { background:transparent; color:#e5eef7; padding:8px 14px; border-radius:8px; }
QPushButton#NavBtn[active="true"] { background:#274e7b; color:white; }
QPushButton#GhostBtn { background:transparent; color:#e5eef7; border:1px solid #7da0c2; border-radius:8px; }
QPushButton { background:#1d75bd; color:white; border:none; border-radius:8px; padding:8px 14px; }
QPushButton:hover { background:#145f9f; }
QPushButton#FinalBtn { background:#21a05a; }
QPushButton#FinalBtn:hover { background:#1b8a4c; }
QFrame#Card { background:white; border:1px solid #dbe3ee; border-radius:12px; padding:8px; }
QFrame#DropArea { border:2px dashed #b8c9dc; border-radius:10px; background:#f9fbfe; min-height:90px; }
QLabel#Pill { background:#fdf2d8; color:#b45309; border-radius:10px; padding:4px 10px; }
QLabel#PillGreen { background:#dcfce7; color:#15803d; border-radius:10px; padding:4px 10px; }
QLabel#ReviewTitle { font-size:34px; font-weight:700; padding:8px 14px; }
QFrame#SidePanel { background:#eef2f7; border-right:1px solid #d4dde8; }
QFrame#BottomBar { background:#e9eef4; border-top:1px solid #d4dde8; }
QLabel#Banner { background:#eef3f9; border:1px solid #d7e2f0; border-radius:8px; padding:8px; }
QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox, QListWidget, QTableWidget, QTabWidget::pane { background:white; border:1px solid #cfd9e6; border-radius:8px; padding:4px; }
QHeaderView::section { background:#e5ecf5; border:none; padding:6px; }
            """
        )


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
