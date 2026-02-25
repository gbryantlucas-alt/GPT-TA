from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from grader_app.exporters import export_canvas_csv, export_student_feedback_files
from grader_app.grading_engine import GradingEngine
from grader_app.models import BatchSession
from grader_app.parsers import read_text
from grader_app.storage import load_session, save_session

SETTINGS_PATH = Path("settings.json")


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {"api_key": "", "model": "gpt-4.1-mini", "workers": 6}


class TeacherGraderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("English Essay Batch Grader")
        self.root.geometry("1280x800")
        self.settings = load_settings()

        self.session = BatchSession(session_id=str(uuid.uuid4())[:8])
        self.essay_paths: list[str] = []
        self.current_student: str | None = None
        self.assignment_requirements: list[str] = []
        self.subjective_dimensions: list[str] = []

        self._build_ui()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        self.batch_tab = ttk.Frame(notebook)
        self.review_tab = ttk.Frame(notebook)
        self.integrity_tab = ttk.Frame(notebook)
        self.settings_tab = ttk.Frame(notebook)

        notebook.add(self.batch_tab, text="Batch Setup")
        notebook.add(self.review_tab, text="Essay Review")
        notebook.add(self.integrity_tab, text="Integrity")
        notebook.add(self.settings_tab, text="Settings")

        self._build_batch_tab()
        self._build_review_tab()
        self._build_integrity_tab()
        self._build_settings_tab()

    def _build_batch_tab(self) -> None:
        controls = ttk.Frame(self.batch_tab)
        controls.pack(fill="x", padx=10, pady=10)

        ttk.Button(controls, text="Upload Essays (.docx)", command=self.select_essays).pack(side="left", padx=4)
        ttk.Button(controls, text="Upload Rubric File", command=self.select_rubric_file).pack(side="left", padx=4)
        ttk.Button(controls, text="Upload Assignment File", command=self.select_assignment_file).pack(side="left", padx=4)
        ttk.Button(controls, text="Load Saved Session", command=self.load_session_file).pack(side="left", padx=4)
        ttk.Button(controls, text="Start AI Grading", command=self.start_grading).pack(side="left", padx=4)

        text_frame = ttk.Frame(self.batch_tab)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(text_frame)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(text_frame)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Rubric Text (paste/edit)").pack(anchor="w")
        self.rubric_text = tk.Text(left, height=20)
        self.rubric_text.pack(fill="both", expand=True)

        ttk.Label(right, text="Assignment Text").pack(anchor="w")
        self.assignment_text = tk.Text(right, height=20)
        self.assignment_text.pack(fill="both", expand=True)

        self.batch_status = tk.StringVar(value="No batch started")
        ttk.Label(self.batch_tab, textvariable=self.batch_status).pack(anchor="w", padx=10, pady=6)

    def _build_review_tab(self) -> None:
        wrapper = ttk.Frame(self.review_tab)
        wrapper.pack(fill="both", expand=True)

        left = ttk.Frame(wrapper)
        left.pack(side="left", fill="y")
        right = ttk.Frame(wrapper)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        ttk.Label(left, text="Students").pack(anchor="w")
        self.student_list = tk.Listbox(left, width=35)
        self.student_list.pack(fill="y", expand=True)
        self.student_list.bind("<<ListboxSelect>>", self.on_student_select)

        top = ttk.Frame(right)
        top.pack(fill="x")
        ttk.Button(top, text="Save Edits", command=self.save_current_edits).pack(side="left", padx=4)
        ttk.Button(top, text="Mark Finalized", command=self.mark_finalized).pack(side="left", padx=4)
        ttk.Button(top, text="Export Final Outputs", command=self.export_outputs).pack(side="left", padx=4)

        ttk.Label(right, text="Essay Summary").pack(anchor="w")
        self.summary_text = tk.Text(right, height=6)
        self.summary_text.pack(fill="x")

        ttk.Label(right, text="Assignment Compliance").pack(anchor="w")
        self.compliance_text = tk.Text(right, height=6)
        self.compliance_text.pack(fill="x")

        ttk.Label(right, text="Rubric Scores + Feedback (JSON editable)").pack(anchor="w")
        self.feedback_text = tk.Text(right, height=12)
        self.feedback_text.pack(fill="both", expand=True)

        ttk.Label(right, text="Human Judgment Flags").pack(anchor="w")
        self.annotation_text = tk.Text(right, height=6)
        self.annotation_text.pack(fill="x")

        grade_frame = ttk.Frame(right)
        grade_frame.pack(fill="x", pady=6)
        ttk.Label(grade_frame, text="Overall Grade:").pack(side="left")
        self.overall_grade_var = tk.StringVar()
        ttk.Entry(grade_frame, textvariable=self.overall_grade_var, width=10).pack(side="left", padx=6)
        self.overall_note = tk.Text(right, height=4)
        self.overall_note.pack(fill="x")

    def _build_integrity_tab(self) -> None:
        self.integrity_text = tk.Text(self.integrity_tab)
        self.integrity_text.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_settings_tab(self) -> None:
        frm = ttk.Frame(self.settings_tab)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frm, text="OpenAI API Key").grid(row=0, column=0, sticky="w")
        self.api_key_var = tk.StringVar(value=self.settings.get("api_key", ""))
        ttk.Entry(frm, textvariable=self.api_key_var, show="*", width=60).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Model").grid(row=1, column=0, sticky="w")
        self.model_var = tk.StringVar(value=self.settings.get("model", "gpt-4.1-mini"))
        ttk.Entry(frm, textvariable=self.model_var, width=30).grid(row=1, column=1, sticky="w")

        ttk.Label(frm, text="Parallel Workers").grid(row=2, column=0, sticky="w")
        self.workers_var = tk.IntVar(value=self.settings.get("workers", 6))
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self.workers_var, width=5).grid(row=2, column=1, sticky="w")

        ttk.Button(frm, text="Save Settings", command=self.save_settings).grid(row=3, column=0, pady=10)

    def save_settings(self) -> None:
        self.settings = {
            "api_key": self.api_key_var.get().strip(),
            "model": self.model_var.get().strip(),
            "workers": int(self.workers_var.get()),
        }
        SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        messagebox.showinfo("Saved", "Settings saved.")

    def select_essays(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("Word Docs", "*.docx")])
        if paths:
            self.essay_paths = list(paths)
            self.batch_status.set(f"Selected {len(self.essay_paths)} essays")

    def select_rubric_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Docs/PDF", "*.docx *.pdf")])
        if path:
            self.session.rubric_text = read_text(path)
            self.rubric_text.delete("1.0", "end")
            self.rubric_text.insert("1.0", self.session.rubric_text)

    def select_assignment_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Docs/PDF", "*.docx *.pdf")])
        if path:
            self.session.assignment_text = read_text(path)
            self.assignment_text.delete("1.0", "end")
            self.assignment_text.insert("1.0", self.session.assignment_text)

    def start_grading(self) -> None:
        if not self.essay_paths:
            messagebox.showerror("Missing essays", "Please upload essay files first.")
            return
        if not self.api_key_var.get().strip():
            messagebox.showerror("Missing API key", "Please set OpenAI API key in Settings tab.")
            return

        self.session.rubric_text = self.rubric_text.get("1.0", "end").strip()
        self.session.assignment_text = self.assignment_text.get("1.0", "end").strip()
        if not self.session.rubric_text:
            messagebox.showerror("Missing rubric", "Please upload or paste rubric text.")
            return

        def run_batch() -> None:
            self.batch_status.set("Parsing rubric and assignment...")
            engine = GradingEngine(self.api_key_var.get().strip(), self.model_var.get().strip())
            self.assignment_requirements, self.subjective_dimensions = engine.prepare_session(self.session)
            self.batch_status.set("Processing essays in parallel...")
            engine.process_batch(
                self.session,
                self.essay_paths,
                self.assignment_requirements,
                self.subjective_dimensions,
                on_update=lambda sid: self.root.after(0, self.on_batch_update, sid),
                max_workers=int(self.workers_var.get()),
            )
            save_session(self.session)
            self.root.after(0, self.refresh_integrity_panel)
            self.batch_status.set("Batch complete. Review essays and finalize exports.")

        threading.Thread(target=run_batch, daemon=True).start()

    def on_batch_update(self, student_id: str) -> None:
        self.refresh_student_list()
        self.batch_status.set(f"Processed: {student_id} ({len(self.session.essays)} complete)")

    def refresh_student_list(self) -> None:
        self.student_list.delete(0, "end")
        for sid, essay in sorted(self.session.essays.items()):
            self.student_list.insert("end", f"{sid} [{essay.status}]")

    def on_student_select(self, _event=None) -> None:
        sel = self.student_list.curselection()
        if not sel:
            return
        label = self.student_list.get(sel[0])
        sid = label.split(" [")[0]
        self.current_student = sid
        essay = self.session.essays[sid]

        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", essay.summary)
        self.compliance_text.delete("1.0", "end")
        self.compliance_text.insert("1.0", json.dumps([c.__dict__ for c in essay.compliance], indent=2))
        self.feedback_text.delete("1.0", "end")
        self.feedback_text.insert("1.0", json.dumps([c.__dict__ for c in essay.category_scores], indent=2))
        self.annotation_text.delete("1.0", "end")
        self.annotation_text.insert("1.0", json.dumps([a.__dict__ for a in essay.annotations], indent=2))
        self.overall_grade_var.set(str(essay.overall_grade))
        self.overall_note.delete("1.0", "end")
        self.overall_note.insert("1.0", essay.overall_note)

    def save_current_edits(self) -> None:
        sid = self.current_student
        if not sid:
            return
        essay = self.session.essays[sid]
        essay.summary = self.summary_text.get("1.0", "end").strip()
        essay.overall_grade = float(self.overall_grade_var.get() or 0)
        essay.overall_note = self.overall_note.get("1.0", "end").strip()
        essay.category_scores = [
            __import__("grader_app.models", fromlist=["CategoryScore"]).CategoryScore(**x)
            for x in json.loads(self.feedback_text.get("1.0", "end"))
        ]
        essay.compliance = [
            __import__("grader_app.models", fromlist=["AssignmentComplianceItem"]).AssignmentComplianceItem(**x)
            for x in json.loads(self.compliance_text.get("1.0", "end"))
        ]
        essay.annotations = [
            __import__("grader_app.models", fromlist=["Annotation"]).Annotation(**x)
            for x in json.loads(self.annotation_text.get("1.0", "end"))
        ]
        save_session(self.session)
        messagebox.showinfo("Saved", f"Saved edits for {sid}.")
        self.refresh_student_list()

    def mark_finalized(self) -> None:
        sid = self.current_student
        if not sid:
            return
        self.save_current_edits()
        self.session.essays[sid].status = "finalized"
        save_session(self.session)
        self.refresh_student_list()

    def refresh_integrity_panel(self) -> None:
        self.integrity_text.delete("1.0", "end")
        self.integrity_text.insert("end", "Cross-Essay Similarity Flags\n")
        self.integrity_text.insert("end", "=" * 45 + "\n")
        for f in self.session.integrity_flags:
            self.integrity_text.insert("end", f"{f.student_a} ↔ {f.student_b}: {f.score}\n")

        self.integrity_text.insert("end", "\nAI Usage Signal Scores (Non-definitive)\n")
        self.integrity_text.insert("end", "=" * 45 + "\n")
        for sid, essay in sorted(self.session.essays.items()):
            self.integrity_text.insert("end", f"{sid}: {essay.ai_suspicion_score} | {essay.ai_suspicion_note}\n")

    def export_outputs(self) -> None:
        self.save_current_edits()
        out_dir = filedialog.askdirectory()
        if not out_dir:
            return
        csv_path = export_canvas_csv(self.session, out_dir)
        files = export_student_feedback_files(self.session, out_dir)
        messagebox.showinfo("Export complete", f"CSV: {csv_path}\nFeedback files: {len(files)}")

    def load_session_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Session JSON", "*.json")], initialdir="sessions")
        if not path:
            return
        self.session = load_session(path)
        self.rubric_text.delete("1.0", "end")
        self.rubric_text.insert("1.0", self.session.rubric_text)
        self.assignment_text.delete("1.0", "end")
        self.assignment_text.insert("1.0", self.session.assignment_text)
        self.refresh_student_list()
        self.refresh_integrity_panel()
        self.batch_status.set(f"Loaded session {self.session.session_id}")


if __name__ == "__main__":
    root = tk.Tk()
    app = TeacherGraderApp(root)
    root.mainloop()
