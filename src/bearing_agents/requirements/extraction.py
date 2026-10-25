"""Minimal deterministic extraction; an LLM may suggest the same untrusted schema."""

import re

from bearing_agents.requirements.contracts import RequirementProposal

_NUM = r"([0-9]+(?:\.[0-9]+)?)"
_PATTERNS = (
    ("journal_diameter", rf"(?:轴径|轴颈直径|D\s*=)\s*[:：=]?\s*{_NUM}\s*(mm|毫米|m|米)\b?"),
    ("load", rf"(?:径向载荷|轴承载荷|载荷|F\s*=)\s*[:：=]?\s*{_NUM}\s*(kN|N)\b?"),
    ("rotational_speed", rf"(?:转速|n\s*=)\s*[:：=]?\s*{_NUM}\s*(r/min|rpm)\b?"),
)
_NEGATIVE = ("不是", "不对", "不要", "并非", "错误", "错了", "不确定", "估计", "大约", "大概", "可能", "约为", "左右", "猜")
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
            modality = "UNCERTAIN" if any(t in context for t in ("估计", "大概", "大约", "不确定", "左右", "约为")) else "EXPLICIT"
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
    return proposals


class LLMExtractor:
    """Optional structured LLM proposal adapter. Never gains write permission."""

    def __init__(self, model):
        self.model = model

    def extract(self, text: str) -> list[RequirementProposal]:
        response = self.model.invoke(
            "Extract explicit bearing requirement claims only. Return a JSON array of "
            "objects with kind, field_id, quote, start, end, value, unit, modality. "
            "Do not infer missing data or include identity, authority or approvals. "
            "Text: " + repr(text)
        )
        import json
        raw = getattr(response, "content", response)
        if isinstance(raw, str):
            raw = json.loads(raw)
        return [RequirementProposal.model_validate(item) for item in raw]
