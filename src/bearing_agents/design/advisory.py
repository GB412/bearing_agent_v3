"""Optional model chooses order of already declared engineering analysis tasks.

A model cannot change applicability, rule status, numeric values or candidate state.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.design.contracts import AnalysisStep


class StrategyAdviceError(ValueError):
    """Controlled error when an opted-in strategy model breaks its output contract."""


class StrategyRankingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_step_ids: list[str] = Field(min_length=1, max_length=6)
    explanation: str = Field(min_length=1, max_length=500)


class StrategyAdvisor:
    """Return a reordered analysis plan plus a clearly non-authoritative explanation."""

    def __init__(self, model: Any):
        if not callable(getattr(model, "invoke", None)):
            raise TypeError("Strategy model must expose invoke")
        self.model = model

    def prioritize(
        self, steps: list[AnalysisStep], *, objective: str,
    ) -> tuple[list[AnalysisStep], str]:
        originals = {item.step_id: item for item in steps}
        prompt = {
            "task": (
                "Sort ONLY provided step IDs to prioritize analysis. Do not compute numbers, "
                "assert a PASS/FAIL judgment, or claim a solver was executed. "
                "All statuses are fixed by the host."
            ),
            "objective_text_unverified": objective[:500],
            "steps": [item.model_dump(mode="json") for item in steps],
        }
        try:
            output = self.model.invoke(json.dumps(prompt, ensure_ascii=False))
            if isinstance(output, dict) and "parsed" in output:
                if output.get("parsing_error") is not None:
                    raise StrategyAdviceError("MODEL_OUTPUT_INVALID")
                output = output["parsed"]
            if isinstance(output, str):
                output = json.loads(output)
            proposal = StrategyRankingProposal.model_validate(output)
        except StrategyAdviceError:
            raise
        except Exception as exc:
            raise StrategyAdviceError("MODEL_OUTPUT_INVALID") from exc
        ids = proposal.ordered_step_ids
        if len(ids) != len(set(ids)) or set(ids) != set(originals):
            raise StrategyAdviceError("STEP_IDS_NOT_ALLOWED")
        # Do not allow model-generated quantitative or authoritative judgments.
        banned = ("合格", "不合格", "安全", "超限", "pass", "fail", "safe")
        explanation = proposal.explanation.strip()
        if any(ch.isdigit() for ch in explanation) or any(
            term in explanation.lower() for term in banned
        ):
            raise StrategyAdviceError("UNSUPPORTED_ENGINEERING_ASSERTION")
        note = "未审核模型建议（仅影响分析顺序）： " + explanation
        return [originals[key] for key in ids], note
