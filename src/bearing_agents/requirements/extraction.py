"""Minimal deterministic extraction; an LLM may suggest the same untrusted schema."""

import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.requirements.contracts import RequirementProposal

_NUM = r"([0-9]+(?:\.[0-9]+)?)"
_PATTERNS = (
    ("journal_diameter",
     rf"(?:轴径|轴颈直径|D\s*=)\s*[:：=]?\s*{_NUM}\s*(mm|毫米|m|米)(?![A-Za-z])"),
    ("load", rf"(?:径向载荷|轴承载荷|载荷|F\s*=)\s*[:：=]?\s*{_NUM}\s*(kN|N)(?![A-Za-z])"),
    ("rotational_speed", rf"(?:转速|n\s*=)\s*[:：=]?\s*{_NUM}\s*(r/min|rpm)(?![A-Za-z])"),
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
            unit = {"毫米": "mm", "米": "m", "r/min": "rpm"}.get(unit, unit)
            proposals.append(RequirementProposal(
                kind="parameter", field_id=field, quote=quote,
                start=match.start(), end=match.end(),
                value=float(match.group(1)), unit=unit,
                modality=modality, role="FIXED_INPUT",
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

    def extract(self, text: str) -> list[RequirementProposal]:
        response = self.model.invoke(
            "Extract only explicit bearing facts and constraints. Return a JSON object "
            "with the key proposals containing a list of items. Each item must contain "
            "kind, field_id, quote, start, end and (if present) value, unit, modality, "
            "operator. The start/end are Python string character indices in the "
            "original message. Do not infer missing fields. Never include message_id, "
            "actor, confirmation or verified source fields. User message: " + repr(text)
        )
        if isinstance(response,dict) and "raw" in response and "parsed" in response:
            if response.get("parsing_error") is not None:
                raise ValueError("Real extractor structured parsing failed")
            response = response["parsed"]
        if isinstance(response,ExtractionBatch):
            return response.proposals
        raw = getattr(response, "content", response)
        if isinstance(raw,str):
            raw = json.loads(raw)
        if isinstance(raw,list):
            raw = {"proposals":raw}
        return ExtractionBatch.model_validate(raw).proposals
