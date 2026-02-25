from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from grader_app.models import RubricDimension
from grader_app.parsers import safe_json_extract


class AIClient:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini") -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _chat_json(self, system: str, user: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return safe_json_extract(content)

    def parse_rubric_and_assignment(self, rubric_text: str, assignment_text: str) -> dict[str, Any]:
        system = "You are an expert high-school English assessment assistant. Return strict JSON only."
        user = f"""
Parse this rubric and assignment info into structured data.
Return JSON with keys:
- rubric_dimensions: array of objects {{name, description, scale_labels, max_score}}
- assignment_requirements: array of concise requirement strings
- subjective_dimensions: array of rubric dimension names that require human judgment.

Rubric text:\n{rubric_text}\n
Assignment text:\n{assignment_text}
"""
        return self._chat_json(system, user)

    def grade_essay(
        self,
        essay_text: str,
        student_id: str,
        rubric_dimensions: list[RubricDimension],
        assignment_requirements: list[str],
        subjective_dimensions: list[str],
    ) -> dict[str, Any]:
        rubric_json = json.dumps([d.__dict__ for d in rubric_dimensions])
        requirements = json.dumps(assignment_requirements)
        subjective = json.dumps(subjective_dimensions)
        system = "You are a careful English teacher assistant. You must be evidence-based and concise. Return strict JSON only."
        user = f"""
Evaluate the essay for student {student_id}.
Return JSON keys:
- summary: 3-5 sentence summary of argument/structure/strengths/weaknesses
- category_scores: array of {{dimension, score, label, feedback}}
- overall_grade: numeric
- overall_note: string
- assignment_compliance: array of {{requirement, status, note}} where status in [met, partial, missing]
- annotations: array of {{dimension, excerpt, question}} focused on subjective judgment calls needing human review.

Rubric dimensions: {rubric_json}
Assignment requirements: {requirements}
Subjective dimensions to prioritize for annotations: {subjective}

Essay:\n{essay_text}
"""
        return self._chat_json(system, user)
