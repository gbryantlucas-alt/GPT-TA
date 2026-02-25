# AI Essay Batch Grader (Desktop App)

This app is built for a high school English teacher who wants to grade 100+ essays with AI help and still make the final decisions.

## What this app does

- Uploads many student essays at once (`.docx` files).
- Uploads rubric and assignment documents (`.docx` or `.pdf`) or lets you paste rubric text.
- Uses OpenAI (ChatGPT) to:
  - score each rubric category,
  - write category-by-category feedback,
  - summarize each essay in 3–5 sentences,
  - add assignment compliance notes,
  - flag subjective judgment calls for manual teacher review.
- Runs two integrity checks:
  - cross-essay similarity,
  - AI-usage signal score (with a clear caveat that it is **not proof**).
- Lets the teacher edit all scores/comments and mark essays finalized.
- Saves progress locally so you can close the app and come back later.
- Exports:
  - one Canvas-ready CSV,
  - one feedback `.docx` per student.

---

## Installation (step-by-step, no technical experience needed)

### 1) Install Python

- Go to https://www.python.org/downloads/
- Install Python 3.11+.
- On Windows, make sure you check **“Add Python to PATH”** during install.

### 2) Get your OpenAI API key

- Sign in to OpenAI and create an API key.
- Keep it ready. You will paste it into the app's **Settings** screen.

### 3) Launch the app

#### On Mac
- Open the `launchers` folder.
- Double-click `Launch_Grader.command`.
- If macOS blocks it the first time, right-click -> Open.

#### On Windows
- Open the `launchers` folder.
- Double-click `Launch_Grader.bat`.

The launcher will automatically:
1. create a local virtual environment,
2. install dependencies,
3. start the app.

---

## First-time setup in the app

1. Go to **Settings** tab.
2. Paste OpenAI API key.
3. Choose model (default is `gpt-4.1-mini`).
4. Choose number of parallel workers (default: 6).
5. Click **Save Settings**.

---

## Typical grading workflow

1. In **Batch Setup**:
   - click **Upload Essays (.docx)** and select all student essays,
   - upload rubric file OR paste rubric text,
   - upload assignment sheet.
2. Click **Start AI Grading**.
3. Move to **Essay Review** tab:
   - select each student,
   - edit summary/scores/comments as needed,
   - click **Mark Finalized**.
4. Check the **Integrity** tab for similarity and AI-signal flags.
5. Click **Export Final Outputs**:
   - choose an output folder,
   - app creates Canvas CSV + per-student feedback files.

---

## Important notes

- AI grading is a draft assistant, not an autopilot.
- Subjective dimensions are intentionally flagged for your judgment.
- AI-usage signal score is **non-definitive** and must never be sole evidence of dishonesty.
- If one essay errors during processing, the app logs it and continues with the rest.
- Session state is auto-saved in the `sessions/` folder.

---

## Troubleshooting

- **“Missing API key”**: add key in Settings and click Save.
- **No output file**: check that essays are finalized and you selected an export folder.
- **A single essay fails**: open that student record (status `error`), fix file content, rerun batch.
- **First launch is slow**: normal; dependencies are installing.

