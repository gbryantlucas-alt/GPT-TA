from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from grader_app.ai_client import AIClient
from grader_app.integrity import ai_usage_signal_score, similarity_flags
from grader_app.models import (
    Annotation,
    AssignmentComplianceItem,
    BatchSession,
    CategoryScore,
    EssayResult,
    RubricDimension,
)
from grader_app.parsers import infer_student_id, read_text
from grader_app.storage import save_session


class GradingEngine:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini") -> None:
        self.ai = AIClient(api_key=api_key, model=model)

    def prepare_session(self, session: BatchSession) -> tuple[list[str], list[str]]:
        parsed = self.ai.parse_rubric_and_assignment(session.rubric_text, session.assignment_text)
        session.rubric_dimensions = [RubricDimension(**d) for d in parsed.get("rubric_dimensions", [])]
        requirements = parsed.get("assignment_requirements", [])
        subjective = parsed.get("subjective_dimensions", [])
        return requirements, subjective

    def _grade_one(
        self,
        file_path: str,
        rubric_dimensions: list[RubricDimension],
        assignment_requirements: list[str],
        subjective_dimensions: list[str],
    ) -> tuple[str, EssayResult, str]:
        text = read_text(file_path)
        student_id = infer_student_id(file_path, text)
        result = EssayResult(student_id=student_id, file_path=file_path, file_name=Path(file_path).name, status="ai graded")
        try:
            graded = self.ai.grade_essay(text, student_id, rubric_dimensions, assignment_requirements, subjective_dimensions)
            result.summary = graded.get("summary", "")
            result.category_scores = [CategoryScore(**s) for s in graded.get("category_scores", [])]
            result.overall_grade = graded.get("overall_grade", 0)
            result.overall_note = graded.get("overall_note", "")
            result.compliance = [
                AssignmentComplianceItem(requirement=i.get("requirement", ""), status=i.get("status", ""), note=i.get("note", ""))
                for i in graded.get("assignment_compliance", [])
            ]
            result.annotations = [Annotation(**a) for a in graded.get("annotations", [])]
            score, note = ai_usage_signal_score(text)
            result.ai_suspicion_score = score
            result.ai_suspicion_note = note
            result.refresh_ai_snapshot()
        except Exception as exc:
            result.status = "failed"
            result.error = f"{exc}\n{traceback.format_exc()}"
        return student_id, result, text

    def process_batch(
        self,
        session: BatchSession,
        essay_paths: list[str],
        assignment_requirements: list[str],
        subjective_dimensions: list[str],
        on_update: Callable[[str], None] | None = None,
        max_workers: int = 6,
    ) -> BatchSession:
        texts: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(
                    self._grade_one,
                    p,
                    session.rubric_dimensions,
                    assignment_requirements,
                    subjective_dimensions,
                )
                for p in essay_paths
            ]
            for future in as_completed(futures):
                sid, result, text = future.result()
                session.essays[sid] = result
                texts[sid] = text
                save_session(session)
                if on_update:
                    on_update(sid)

        session.integrity_flags = similarity_flags(texts)
        save_session(session)
        return session
