"""Optional model prioritizes only the analysis steps supplied by the host.

The model cannot alter applicability, values, rule statuses or engineering results.
Its free-form explanation is intentionally not displayed as a technical conclusion.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.design.contracts import AnalysisStep


class StrategyAdviceError(ValueError):
    """An opted-in strategy model violated its structured-output contract."""


class StrategyRankingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_step_ids: list[str] = Field(min_length=1)
    explanation: str | None = Field(default=None, max_length=500)


class StrategyAdvisor:
    """Allow the model to reorder steps, but never authorize engineering claims."""

    def __init__(self, model: Any):
        if not callable(getattr(model, "invoke", None)):
            raise TypeError("Strategy model must expose invoke")
        self.model = model

    def prioritize(
        self, steps: list[AnalysisStep], *, objective: str,
    ) -> tuple[list[AnalysisStep], str]:
        originals = {item.step_id: item for item in steps}
        if len(originals) != len(steps):
            raise StrategyAdviceError("DUPLICATE_STEP_IDS")
        prompt = {
            "task": (
                "Return JSON with ordered_step_ids containing precisely the provided "
                "step IDs once each. You may prioritize, but cannot add tasks, "
                "change engineering statuses or claim numerical/solver results."
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
            if hasattr(output, "content") and not isinstance(output, (str, dict)):
                output = output.content
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
        # Ignore any model-authored prose. Only the order is considered,
        # and all step details are retained verbatim from the trusted host.
        note = "未审核模型建议：仅调整分析步骤顺序；工程状态、数值与规则判定未改变。"
        return [originals[key] for key in ids], note
