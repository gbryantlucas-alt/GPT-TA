from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RubricDimension:
    name: str
    description: str
    scale_labels: list[str] = field(default_factory=list)
    max_score: float = 0


@dataclass
class Annotation:
    dimension: str
    excerpt: str
    question: str
    teacher_note: str = ""


@dataclass
class CategoryScore:
    dimension: str
    score: float
    label: str
    feedback: str


@dataclass
class AssignmentComplianceItem:
    requirement: str
    status: str
    note: str


@dataclass
class EssaySnapshot:
    summary: str = ""
    category_scores: list[CategoryScore] = field(default_factory=list)
    overall_grade: float = 0
    overall_note: str = ""
    compliance: list[AssignmentComplianceItem] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class EssayResult:
    student_id: str
    file_path: str
    status: str = "not graded"
    file_name: str = ""
    summary: str = ""
    category_scores: list[CategoryScore] = field(default_factory=list)
    overall_grade: float = 0
    overall_note: str = ""
    compliance: list[AssignmentComplianceItem] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    ai_suspicion_score: float = 0
    ai_suspicion_note: str = ""
    error: str = ""
    ai_original: EssaySnapshot = field(default_factory=EssaySnapshot)

    def refresh_ai_snapshot(self) -> None:
        self.ai_original = EssaySnapshot(
            summary=self.summary,
            category_scores=[CategoryScore(**asdict(c)) for c in self.category_scores],
            overall_grade=self.overall_grade,
            overall_note=self.overall_note,
            compliance=[AssignmentComplianceItem(**asdict(c)) for c in self.compliance],
            annotations=[Annotation(**asdict(a)) for a in self.annotations],
        )


@dataclass
class SimilarityFlag:
    student_a: str
    student_b: str
    score: float


@dataclass
class BatchSession:
    session_id: str
    rubric_text: str = ""
    assignment_text: str = ""
    rubric_dimensions: list[RubricDimension] = field(default_factory=list)
    essays: dict[str, EssayResult] = field(default_factory=dict)
    integrity_flags: list[SimilarityFlag] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
