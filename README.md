# Essay Grader (Desktop App)

A local desktop tool for high-school English teachers to batch-grade essays with AI assistance while keeping full teacher control.

## What’s in this refactor

- New **AppShell** with top navigation: **Setup | Review | Integrity | Export**.
- Setup page now uses clean upload cards for Rubric, Assignment, and Student Essays.
- Review page is a focused 3-column workspace:
  - left: student list/search/filter,
  - center: paper-like essay viewer with inline images + yellow highlights,
  - right: grading panel (Summary & Compliance, Rubric, Flags, Overall, Diff).
- Integrity page shows similarity table + AI-usage heuristic table.
- Export page provides dedicated export actions.

All existing backend capabilities are preserved:
- AI grading pipeline
- Session persistence
- Integrity computations
- Canvas CSV export + per-student feedback DOCX export

---

## Install

1. Install Python 3.11+.
2. Open the `launchers/` folder.
3. Run:
   - macOS: `Launch_Grader.command`
   - Windows: `Launch_Grader.bat`

---

## Workflow

### 1) Setup
- Upload/paste rubric.
- Upload/paste assignment sheet.
- Upload all student `.docx` essays.
- Save API settings (key/model/workers).
- Click **Start Grading**.

### 2) Review
- Search/filter students in left sidebar.
- Click a student to load essay + grading data.
- Edit scores/feedback in right tabs.
- Use autosave or **Save Changes**.
- Click **Finalize** when done.

### 3) Integrity
- Review high-similarity pairs and AI-usage signal scores (non-definitive).

### 4) Export
- Export Canvas CSV.
- Export student feedback DOCX files.

---

## Smoke test checklist

1. Open app and verify top nav appears with Setup/Review/Integrity/Export.
2. On Setup, upload sample files and confirm counts/pills update.
3. Start grading; verify progress updates and failures do not crash batch.
4. In Review, select students; verify:
   - center essay scrolls to bottom,
   - images render inline,
   - yellow highlights are visible,
   - clicking highlight focuses Flags.
5. Edit rubric/compliance/overall fields and verify save status changes to `Saved ✓`.
6. Open Diff mode and verify edits are listed.
7. Export from Export page and verify CSV + DOCX outputs are created.

---

## Notes

- AI-usage heuristic is only a signal and **must not** be used as sole evidence of misconduct.
- Session data is stored locally in `sessions/`.
