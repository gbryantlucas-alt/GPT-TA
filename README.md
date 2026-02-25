# AI Essay Batch Grader (Desktop App)

This tool helps a high-school English teacher grade 100+ essays with AI assistance, while keeping full teacher control.

## Highlights of the new review interface

- **Modern split view** for essay review:
  - Left: Word-like essay viewer (rendered HTML from `.docx`) with inline images.
  - Right: grading controls (summary, compliance checklist, rubric scoring, feedback, overall grade).
- **No raw JSON in the UI**.
- **Yellow human-judgment highlights** in the essay viewer.
- **Autosave** with visible status (`Saving…`, `Saved ✓`, `Save failed`).
- **Tabbed grading panel**: Summary, Compliance, Rubric, Flags, Overall, and Diff.

## What the app does

- Uploads batch essays (`.docx`), rubric (`.docx/.pdf` or pasted text), assignment (`.docx/.pdf`).
- Uses OpenAI to:
  - parse rubric dimensions and assignment requirements,
  - score each rubric category,
  - generate category feedback,
  - write 3–5 sentence summary,
  - add assignment compliance notes,
  - flag human-judgment areas with excerpts/questions.
- Runs integrity checks:
  - cross-essay similarity,
  - AI usage signal score (non-definitive, never sole evidence).
- Saves sessions locally for resume.
- Exports:
  - Canvas-ready CSV,
  - per-student `.docx` feedback files.

## Install (step-by-step)

1. Install Python 3.11+ from https://www.python.org/downloads/
2. Open `launchers/`.
3. Double-click:
   - Mac: `Launch_Grader.command`
   - Windows: `Launch_Grader.bat`

The launcher creates a local virtual environment, installs dependencies, and starts the app.

## First run

1. Open **Settings** tab.
2. Paste OpenAI API key.
3. Confirm model and worker count.
4. Click **Save Settings**.

## Grading workflow

1. **Batch Setup**
   - Upload essays (`.docx`).
   - Upload rubric and assignment docs (or paste rubric text).
   - Start AI grading.
2. **Essay Review**
   - Select a student in left sidebar (or leave unselected to keep placeholder state).
   - Read essay in left pane (with images rendered inline and scrollable in the web viewer).
   - Use right-side tabs to edit:
     - **Summary**
     - **Compliance** (status + notes + per-row revert)
     - **Rubric** (score, label, feedback, per-dimension revert, revert all)
     - **Flags** (review questions, teacher notes, jump to highlight)
     - **Overall**
     - **Diff** (All Changes or filtered by section)
   - Use toolbar actions to Save, Mark Finalized, Export, and Next/Previous student.
3. **Integrity**
   - Review similarity flags and AI usage signals.
4. **Export**
   - Use menu action (or existing export controls) to write Canvas CSV and per-student feedback docs.

## Notes

- Essay rendering caches converted HTML for faster navigation.
- If an image cannot be rendered, document remains readable and a fallback marker is shown.
- Batch processing is parallel and resilient: one essay failure does not stop the batch.

