"""Optional LLM ranking of a trusted question list; no authority to invent facts."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.requirements.contracts import Question, RequirementGuidance


class QuestionRankingError(ValueError):
    """Explicitly opted-in model ranking failed or exceeded its permission scope."""


class RankingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_question_ids: list[str] = Field(min_length=1, max_length=3)


class QuestionRanker:
    """Ranks existing deterministic questions; cannot add or modify their content."""

    def __init__(self, model: Any):
        if not callable(getattr(model, "invoke", None)):
            raise ValueError("Question model must implement invoke()")
        self.model = model

    def reorder(
        self, questions: list[Question], guidance: RequirementGuidance | None,
    ) -> list[Question]:
        if len(questions) < 2:
            return list(questions)
        options = {question.question_id: question for question in questions}
        payload = {
            "task": "Order ONLY the question IDs provided. Never invent data or approvals.",
            "options": [
                {
                    "question_id": item.question_id,
                    "reason_code": item.reason_code,
                    "why_needed": item.why_needed,
                }
                for item in questions
            ],
            "scenario_hint": guidance.scenario_hint if guidance else None,
            "objective_hints": guidance.objective_hints if guidance else [],
        }
        try:
            response = self.model.invoke(json.dumps(payload, ensure_ascii=False))
            if isinstance(response, dict) and "parsed" in response:
                if response.get("parsing_error") is not None:
                    raise QuestionRankingError("MODEL_OUTPUT_INVALID")
                response = response["parsed"]
            if not isinstance(response, RankingProposal):
                response = RankingProposal.model_validate(response)
        except QuestionRankingError:
            raise
        except Exception as exc:
            raise QuestionRankingError("QUESTION_RANKING_FAILED") from exc
        ordered = response.ordered_question_ids
        if len(ordered) != len(set(ordered)) or any(qid not in options for qid in ordered):
            raise QuestionRankingError("QUESTION_ID_NOT_ALLOWED")
        return [options[qid] for qid in ordered] + [
            item for item in questions if item.question_id not in set(ordered)
        ]
