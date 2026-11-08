"""Minimal deterministic extraction; an LLM may suggest the same untrusted schema."""

import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.requirements.contracts import RequirementProposal
from bearing_agents.requirements.evidence import claim_context

_NUM = r"([0-9]+(?:\.[0-9]+)?)"
_PATTERNS = (
    ("journal_diameter",
     rf"(?:轴径|轴颈直径|D\s*=)\s*[:：=]?\s*(?:是|为)?\s*{_NUM}\s*(mm|毫米|m|米)(?![A-Za-z])"),
    ("load",
     rf"(?:径向载荷|轴承载荷|载荷|F\s*=)\s*[:：=]?\s*"
     rf"(?:后来查到了[，,]?\s*)?(?:是|为)?\s*{_NUM}\s*(kN|N|千牛)(?![A-Za-z])"),
    ("rotational_speed",
     rf"(?:转速|n\s*=)\s*[:：=]?\s*(?:是|为)?\s*"
     rf"{_NUM}\s*(r/min|rpm|转/分)(?![A-Za-z])"),
    ("bearing_width",
     rf"(?:轴承宽度|(?<!安装)宽度)\s*(?:为|是|=|:|：)?\s*{_NUM}\s*(mm|毫米|m|米)(?![A-Za-z])"),
    ("radial_clearance",
     rf"(?:径向间隙|半径间隙)\s*(?:为|是|=|:|：)?\s*{_NUM}\s*(mm|毫米|m|米)(?![A-Za-z])"),
)
_SCOPE_UNSUPPORTED = ("滚动轴承", "球轴承", "圆锥滚子", "滚子轴承", "可倾瓦", "静压轴承")
_SCOPE_SUPPORTED = ("圆柱径向动压", "径向动压滑动轴承", "圆柱滑动轴承")
_DYNAMIC = ("动态载荷", "载荷周期", "两个工况", "多工况", "变载荷", "非稳态")
_STEADY = ("单一稳态", "单稳态", "稳定载荷", "恒定载荷且恒定转速")

def extract(text: str) -> list[RequirementProposal]:
    proposals: list[RequirementProposal] = []
    for field, expression in _PATTERNS:
        for match in re.finditer(expression, text, flags=re.I):
            quote = match.group()
            context = claim_context(text, match.start(), match.end())
            uncertain = ("估计", "大概", "大约", "不确定", "左右", "约为")
            modality = "UNCERTAIN" if any(t in context for t in uncertain) else "EXPLICIT"
            if any(t in context for t in ("不是", "不对", "并非", "不要", "错了", "错误")):
                modality = "NEGATED"
            unit = match.group(2)
            aliases = {"毫米": "mm", "米": "m", "r/min": "rpm",
                       "千牛": "kN", "转/分": "rpm"}
            unit = aliases.get(unit, unit)
            proposals.append(RequirementProposal(
                kind="parameter", field_id=field, 
                value=float(match.group(1)), unit=unit,
                modality=modality,
                role=("DESIGN_VARIABLE" if field in {
                    "bearing_width", "radial_clearance",
                } else "FIXED_INPUT"),
            ))
    for keyword in _SCOPE_UNSUPPORTED:
        at=text.find(keyword)
        if at >= 0:
            proposals.append(RequirementProposal(kind="scope",field_id="unsupported",
                value="unsupported"))
            break
    else:
        for keyword in _SCOPE_SUPPORTED:
            at=text.find(keyword)
            if at >= 0:
                proposals.append(RequirementProposal(kind="scope",field_id="supported",
                    value="cylindrical_radial_hydrodynamic"))
                break
    for keyword in _DYNAMIC:
        at=text.find(keyword)
        if at>=0:
            proposals.append(RequirementProposal(kind="steady_state",field_id="dynamic",
                value="false"))
            break
    else:
        for keyword in _STEADY:
            at=text.find(keyword)
            if at>=0:
                proposals.append(RequirementProposal(kind="steady_state",field_id="steady",
                    value="true"))
                break
    match=re.search(r"(?:安装宽度|轴承宽度|宽度)\s*(?:不能超过|不超过|小于等于|≤)\s*"+_NUM+r"\s*(mm|毫米|m|米)",text)
    if match:
        proposals.append(RequirementProposal(kind="constraint",field_id="bearing_width",
            
            value=float(match.group(1)),unit={"毫米":"mm","米":"m"}.get(match.group(2),match.group(2)),operator="LE"))
    # User-specified materials are constraints, not recommendations.
    material_patterns = (
        (r"(?:不能用|禁止使用|不得使用)\s*([\u4e00-\u9fa5]{2,12})", "NOT_IN"),
        (r"材料(?:只允许|仅允许|必须使用)\s*([\u4e00-\u9fa5]{2,12})", "IN"),
    )
    for expression, operator in material_patterns:
        match = re.search(expression, text)
        if match:
            proposals.append(RequirementProposal(
                kind="constraint", field_id="material",
                
                value=match.group(1), unit="1", operator=operator,
            ))
            break
    return proposals


class ExtractionBatch(BaseModel):
    """JSON-Schema-compatible, model-facing extraction envelope."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[RequirementProposal] = Field(default_factory=list, max_length=24)


class LLMExtractor:
    """Structured real-LLM extraction; no text span offsets or write privileges."""

    def __init__(self, model):
        self.model = model
        self.last_recovery: dict[str, int] | None = None

    @classmethod
    def from_environment(cls):
        if os.getenv("BEARING_LLM_ENABLED", "").strip().lower() not in {
            "1", "true", "yes", "on",
        }:
            raise ValueError("Real extraction requires BEARING_LLM_ENABLED=true")
        api_key = os.getenv("BEARING_LLM_API_KEY", "").strip()
        base_url = os.getenv("BEARING_LLM_BASE_URL", "").strip()
        model_name = os.getenv("BEARING_REQUIREMENTS_MODEL", "").strip() or (
            os.getenv("BEARING_PLANNER_MODEL", "").strip()
        )
        if not (api_key and base_url and model_name):
            raise ValueError("Configure BEARING_LLM_API_KEY/BASE_URL and a model name")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Install project [llm] extra for real extraction") from exc
        client = ChatOpenAI(
            api_key=api_key, base_url=base_url, model=model_name,
            temperature=0, timeout=90, max_retries=0,
        ).with_structured_output(ExtractionBatch, method="json_mode", include_raw=True)
        return cls(client)

    @staticmethod
    def _parse_response(response) -> tuple[list[RequirementProposal], int]:
        """Keep individually valid items from JSON; reject malformed envelope/API."""
        if isinstance(response, dict) and "raw" in response and "parsed" in response:
            if response.get("parsing_error") is None and response.get("parsed") is not None:
                return ExtractionBatch.model_validate(response["parsed"]).proposals, 0
            response = getattr(response["raw"], "content", response["raw"])
        if isinstance(response, ExtractionBatch):
            return response.proposals, 0
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError as exc:
                raise ValueError("Real extractor JSON response invalid") from exc
        if not isinstance(response, dict) or set(response) != {"proposals"}:
            raise ValueError("Real extractor JSON envelope invalid")
        raw_proposals = response["proposals"]
        if not isinstance(raw_proposals, list) or len(raw_proposals) > 24:
            raise ValueError("Real extractor JSON envelope invalid")
        valid = []
        rejected = 0
        for item in raw_proposals:
            try:
                valid.append(RequirementProposal.model_validate(item))
            except ValueError:
                rejected += 1
        return valid, rejected

    def extract(self, text: str) -> list[RequirementProposal]:
        self.last_recovery = None
        response = self.model.invoke(
            "Extract bearing-design requirements as a JSON object with exactly "
            "one key: proposals (an array, empty if no facts). No markdown. "
            "Each proposal has kind, field_id, value, unit, modality, operator "
            "as applicable. NEVER output quote, start, end, source_ref, "
            "confirmed_by or approval. Valid kinds: parameter, scope, "
            "steady_state, constraint, preference. For numeric parameters use "
            "field_id journal_diameter, load, rotational_speed, bearing_width "
            "or radial_clearance; include numeric value and unit. Scope uses "
            "field_id supported or unsupported and value "
            "cylindrical_radial_hydrodynamic or unsupported. Steady-state uses "
            "field_id steady/dynamic and value true/false as STRINGS. "
            "Constraints and preferences can use bearing_width (LE) or "
            "material (IN/NOT_IN). '最好' expresses a preference, not an "
            "approved hard constraint. Modality MUST be EXPLICIT, UNCERTAIN, "
            "UNKNOWN, NEGATED, AMBIGUOUS, or CORRECTION. If the user says "
            "a value is approximate/unknown, do not mark it EXPLICIT. "
            "For a correction, mark CORRECTION; never silently overwrite old "
            "values. Do not invent missing numbers. "
            "For example: "
            '{"proposals":[{"kind":"parameter","field_id":"journal_diameter",'
            '"value":100,"unit":"mm","modality":"EXPLICIT"}]}. '
            "User message: " + repr(text)
        )
        model_items, rejected = self._parse_response(response)
        # Deterministic extraction supplements omissions from explicit user
        # phrasing, but cannot override a model item for the same kind/field.
        existing = {(item.kind, item.field_id) for item in model_items}
        additions = [
            item for item in extract(text)
            if (item.kind, item.field_id) not in existing
        ]
        if rejected or additions:
            self.last_recovery = {
                "invalid_proposals": rejected,
                "recovered_from_text": len(additions),
            }
        return [*model_items, *additions]
