from __future__ import annotations

import uuid
from pathlib import Path

from grader_app.grading_engine import GradingEngine
from grader_app.models import BatchSession
from grader_app.storage import load_session, save_session


class GraderController:
    def __init__(self) -> None:
        self.session = BatchSession(session_id=str(uuid.uuid4())[:8])
        self.assignment_requirements: list[str] = []
        self.subjective_dimensions: list[str] = []

    def load_session(self, path: str) -> BatchSession:
        self.session = load_session(path)
        return self.session

    def save_session(self) -> str:
        return save_session(self.session)

    def run_batch(
        self,
        api_key: str,
        model: str,
        essay_paths: list[str],
        workers: int,
        on_update=None,
    ) -> BatchSession:
        engine = GradingEngine(api_key, model)
        self.assignment_requirements, self.subjective_dimensions = engine.prepare_session(self.session)
        return engine.process_batch(
            self.session,
            essay_paths,
            self.assignment_requirements,
            self.subjective_dimensions,
            on_update=on_update,
            max_workers=workers,
        )

    def set_rubric_and_assignment(self, rubric_text: str, assignment_text: str) -> None:
        self.session.rubric_text = rubric_text
        self.session.assignment_text = assignment_text

    def student_ids(self) -> list[str]:
        return sorted(self.session.essays.keys())

    @staticmethod
    def status_label(status: str) -> str:
        status_map = {
            "not graded": "Not graded",
            "ai graded": "AI graded",
            "reviewed": "Reviewed",
            "finalized": "Finalized",
            "failed": "Failed",
        }
        return status_map.get(status, status)
