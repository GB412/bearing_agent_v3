"""Deterministic verification of model-owned spans, values and units."""

import re

from bearing_agents.core.unit_normalizer import UNITS, normalize
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.requirements.contracts import RequirementProposal, VerifiedRequirement

_CANONICAL_UNIT = {"journal_diameter":"mm","load":"N","rotational_speed":"rpm","bearing_width":"mm"}
_SAFE_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")
_NEGATED = ("不是", "不对", "不要", "并非", "错误", "错了")
_UNCERTAIN = ("估计", "大约", "大概", "可能", "不确定", "左右", "约为", "猜")
_SCOPE = {"supported":"cylindrical_radial_hydrodynamic","unsupported":"unsupported"}


def verify(text: str, proposal: RequirementProposal, registry: ParameterSchemaRegistry
           ) -> VerifiedRequirement:
    def decision(code: str, reason: str, value=None, unit=None):
        return VerifiedRequirement(proposal=proposal,decision=code,reason=reason,
                                   normalized_value=value,normalized_unit=unit)

    if proposal.end > len(text) or proposal.start >= proposal.end:
        return decision("REJECT", "SPAN_OUT_OF_RANGE")
    quote = text[proposal.start:proposal.end]
    if quote != proposal.quote:
        return decision("REJECT", "QUOTE_MISMATCH")
    if proposal.modality != "EXPLICIT":
        return decision("CLARIFY", "NOT_EXPLICIT")
    context = text[max(0, proposal.start-14):min(len(text),proposal.end+9)]
    if any(marker in context for marker in _NEGATED+_UNCERTAIN):
        return decision("CLARIFY", "NEGATED_OR_UNCERTAIN")
    if proposal.kind == "scope":
        if _SCOPE.get(proposal.field_id) != proposal.value:
            return decision("REJECT", "SCOPE_MISMATCH")
        expected = "滚动" if proposal.field_id == "unsupported" else "滑动"
        if expected not in quote and not any(
            tag in quote for tag in ("可倾瓦", "静压", "圆柱径向动压", "球轴承", "滚子轴承")
        ):
            return decision("CLARIFY", "SCOPE_AMBIGUOUS")
        return decision("ACCEPT","VERIFIED",proposal.value)
    if proposal.kind == "steady_state":
        if proposal.field_id == "dynamic" and proposal.value == "false":
            return decision("ACCEPT","VERIFIED","false")
        if proposal.field_id == "steady" and proposal.value == "true":
            return decision("ACCEPT","VERIFIED","true")
        return decision("REJECT","STEADY_MISMATCH")
    if proposal.kind not in {"parameter","constraint"}:
        return decision("REJECT","UNSUPPORTED_KIND")
    if proposal.kind == "constraint":
        if proposal.field_id != "bearing_width" or proposal.operator != "LE":
            return decision("CLARIFY", "CONSTRAINT_UNSUPPORTED")
        if not any(p in quote for p in ("不超过","不能超过","小于等于","≤")):
            return decision("REJECT","CONSTRAINT_SEMANTICS_MISMATCH")
    elif proposal.field_id not in {"journal_diameter","load","rotational_speed"}:
        return decision("CLARIFY","UNKNOWN_INPUT_FIELD")
    else:
        tokens={"journal_diameter":("轴径","轴颈直径","D="),
                "load":("载荷","F="),
                "rotational_speed":("转速","n=")}[proposal.field_id]
        if not any(t in quote for t in tokens):
            return decision("REJECT","FIELD_MISMATCH")
    nums=_SAFE_NUMBER.findall(quote)
    if len(nums)!=1 or not isinstance(proposal.value,(int,float)):
        return decision("CLARIFY","NUMERIC_AMBIGUITY")
    try:
        if float(nums[0]) != float(proposal.value):
            return decision("REJECT","VALUE_MISMATCH")
        unit=proposal.unit
        if unit not in UNITS:
            return decision("CLARIFY","UNKNOWN_OR_MISSING_UNIT")
        suffix=quote[quote.find(nums[0])+len(nums[0]):].strip()
        aliases={"mm":("mm","毫米"),"m":("m","米"),"kN":("kN",),"N":("N",),
                 "rpm":("rpm","r/min")}
        if suffix not in aliases.get(unit,()):
            return decision("REJECT","UNIT_MISMATCH")
        target=_CANONICAL_UNIT[proposal.field_id]
        schema=registry.get(proposal.field_id)
        if schema is None or schema.dimension is None:
            return decision("REJECT","NO_PARAMETER_SCHEMA")
        base_value,base_unit=normalize(float(proposal.value),unit,schema.dimension)
        base_target,_=normalize(1.0,target,schema.dimension)
        value=base_value/base_target
        registry.validate(proposal.field_id,value,target)
    except (ValueError,TypeError,KeyError) as exc:
        return decision("REJECT",type(exc).__name__)
    return decision("ACCEPT","VERIFIED",value,target)
