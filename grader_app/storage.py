from __future__ import annotations

import json
from pathlib import Path

from grader_app.models import (
    Annotation,
    AssignmentComplianceItem,
    BatchSession,
    CategoryScore,
    EssayResult,
    EssaySnapshot,
    RubricDimension,
    SimilarityFlag,
)


def save_session(session: BatchSession, out_dir: str = "sessions") -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"{session.session_id}.json"
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    return str(path)


def _snapshot_from_dict(raw: dict) -> EssaySnapshot:
    return EssaySnapshot(
        summary=raw.get("summary", ""),
        category_scores=[CategoryScore(**c) for c in raw.get("category_scores", [])],
        overall_grade=raw.get("overall_grade", 0),
        overall_note=raw.get("overall_note", ""),
        compliance=[AssignmentComplianceItem(**c) for c in raw.get("compliance", [])],
        annotations=[Annotation(**a) for a in raw.get("annotations", [])],
    )


def load_session(path: str) -> BatchSession:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    sess = BatchSession(
        session_id=raw["session_id"],
        rubric_text=raw.get("rubric_text", ""),
        assignment_text=raw.get("assignment_text", ""),
    )
    sess.rubric_dimensions = [RubricDimension(**d) for d in raw.get("rubric_dimensions", [])]
    for sid, e in raw.get("essays", {}).items():
        essay = EssayResult(
            student_id=e["student_id"],
            file_path=e["file_path"],
            status=e.get("status", "not graded"),
            file_name=e.get("file_name", ""),
            summary=e.get("summary", ""),
            overall_grade=e.get("overall_grade", 0),
            overall_note=e.get("overall_note", ""),
            ai_suspicion_score=e.get("ai_suspicion_score", 0),
            ai_suspicion_note=e.get("ai_suspicion_note", ""),
            error=e.get("error", ""),
        )
        essay.category_scores = [CategoryScore(**c) for c in e.get("category_scores", [])]
        essay.compliance = [AssignmentComplianceItem(**c) for c in e.get("compliance", [])]
        essay.annotations = [Annotation(**a) for a in e.get("annotations", [])]
        ai_original = e.get("ai_original")
        if ai_original:
            essay.ai_original = _snapshot_from_dict(ai_original)
        else:
            essay.refresh_ai_snapshot()
        sess.essays[sid] = essay
    sess.integrity_flags = [SimilarityFlag(**f) for f in raw.get("integrity_flags", [])]
    return sess
