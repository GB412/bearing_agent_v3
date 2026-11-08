"""Minimal deterministic extraction; an LLM may suggest the same untrusted schema."""

import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.requirements.contracts import RequirementProposal

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
            prefix = text[max(0, match.start()-15):match.start()]
            context = prefix + quote + text[match.end():min(len(text), match.end()+6)]
            uncertain = ("估计", "大概", "大约", "不确定", "左右", "约为")
            modality = "UNCERTAIN" if any(t in context for t in uncertain) else "EXPLICIT"
            if any(t in context for t in ("不是", "不对", "并非", "不要", "错了", "错误")):
                modality = "NEGATED"
            unit = match.group(2)
            aliases = {"毫米": "mm", "米": "m", "r/min": "rpm",
                       "千牛": "kN", "转/分": "rpm"}
            unit = aliases.get(unit, unit)
            proposals.append(RequirementProposal(
                kind="parameter", field_id=field, quote=quote,
                start=match.start(), end=match.end(),
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
                quote=keyword,start=at,end=at+len(keyword),value="unsupported"))
            break
    else:
        for keyword in _SCOPE_SUPPORTED:
            at=text.find(keyword)
            if at >= 0:
                proposals.append(RequirementProposal(kind="scope",field_id="supported",
                    quote=keyword,start=at,end=at+len(keyword),value="cylindrical_radial_hydrodynamic"))
                break
    for keyword in _DYNAMIC:
        at=text.find(keyword)
        if at>=0:
            proposals.append(RequirementProposal(kind="steady_state",field_id="dynamic",
                quote=keyword,start=at,end=at+len(keyword),value="false"))
            break
    else:
        for keyword in _STEADY:
            at=text.find(keyword)
            if at>=0:
                proposals.append(RequirementProposal(kind="steady_state",field_id="steady",
                    quote=keyword,start=at,end=at+len(keyword),value="true"))
                break
    match=re.search(r"(?:安装宽度|轴承宽度|宽度)\s*(?:不能超过|不超过|小于等于|≤)\s*"+_NUM+r"\s*(mm|毫米|m|米)",text)
    if match:
        proposals.append(RequirementProposal(kind="constraint",field_id="bearing_width",
            quote=match.group(),start=match.start(),end=match.end(),
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
                quote=match.group(), start=match.start(), end=match.end(),
                value=match.group(1), unit="1", operator=operator,
            ))
            break
    return proposals


class ExtractionBatch(BaseModel):
    """Strict model-facing envelope; no verified or identity fields."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[RequirementProposal] = Field(default_factory=list, max_length=24)


class LLMExtractor:
    """Opt-in model extracts untrusted proposals; verification stays deterministic."""

    def __init__(self, model):
        self.model = model
        # Set only if model JSON had proposals with invalid schemas.
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
            api_key=api_key,base_url=base_url,model=model_name,
            temperature=0,timeout=90,max_retries=0,
        ).with_structured_output(ExtractionBatch,method="json_mode",include_raw=True)
        return cls(client)

    def _recover_invalid_items(self, response: dict, text: str) -> list[RequirementProposal]:
        """Recover from valid model JSON only, never coerce unknown proposal types.

        Retained model items and exact-pattern suggestions from the user's
        original text must still pass the trusted EvidenceVerifier.
        """
        raw = response.get("raw")
        content = getattr(raw, "content", raw)
        if not isinstance(content, str):
            raise ValueError("Real extractor structured parsing failed")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Real extractor JSON response invalid") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"proposals"}
            or not isinstance(payload["proposals"], list)
            or len(payload["proposals"]) > 24
        ):
            raise ValueError("Real extractor JSON envelope invalid")
        valid: list[RequirementProposal] = []
        rejected = 0
        for item in payload["proposals"]:
            try:
                valid.append(RequirementProposal.model_validate(item))
            except ValueError:
                rejected += 1
        if not rejected:
            raise ValueError("Real extractor structured parsing failed")
        valid_keys = {(item.kind, item.field_id) for item in valid}
        # Do not suppress multiple deterministic claims for the same field;
        # InteractionService must resolve ambiguity, never select the last.
        recovered = [
            item for item in extract(text)
            if (item.kind, item.field_id) not in valid_keys
        ]
        if not valid and not recovered:
            raise ValueError("Real extractor had no safe proposals to recover")
        self.last_recovery = {
            "invalid_proposals": rejected,
            "recovered_from_text": len(recovered),
        }
        return [*valid, *recovered]

    def extract(self, text: str) -> list[RequirementProposal]:
        self.last_recovery = None
        response = self.model.invoke(
            "Extract ONLY explicit user-stated bearing facts as JSON: "
            'an object with the single key "proposals" and a list (possibly empty). '
            "No markdown. Every proposal MUST use kind exactly one of: "
            "parameter, scope, steady_state, constraint. "
            "Use kind=parameter for numeric fields journal_diameter, load, "
            "rotational_speed, bearing_width, radial_clearance. "
            "Use kind=scope with field_id=supported or unsupported. "
            "Use kind=steady_state with field_id=steady or dynamic. "
            "Use kind=constraint for explicit width/material restrictions only. "
            "Every item requires kind, field_id, quote, start, end. Quote must be "
            "an exact substring of the original user message, with Python "
            "0-based character positions and end exclusive. Include value, "
            "unit, modality, operator when appropriate. Modality MUST be "
            "EXPLICIT, UNCERTAIN, NEGATED or AMBIGUOUS. "
            "Do not invent absent values, including unknown loads. "
            "Never provide message_id, actor, approval, confirmation, or provenance. "
            "Example proposal: "
            '{"kind":"parameter","field_id":"journal_diameter","quote":"轴径100mm",'
            '"start":0,"end":7,"value":100,"unit":"mm","modality":"EXPLICIT"}. '
            "User message: " + repr(text)
        )
        if isinstance(response, dict) and "raw" in response and "parsed" in response:
            if response.get("parsing_error") is not None:
                return self._recover_invalid_items(response, text)
            response = response["parsed"]
        if isinstance(response, ExtractionBatch):
            return response.proposals
        raw = getattr(response, "content", response)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, list):
            raw = {"proposals": raw}
        return ExtractionBatch.model_validate(raw).proposals
