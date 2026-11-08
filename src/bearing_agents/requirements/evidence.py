"""Lightweight semantic and engineering validation of typed LLM proposals.

Source identity comes from the authenticated interaction, not the model.
No character offsets, quote matching, or model-granted approval authority.
"""

import re

from bearing_agents.core.unit_normalizer import UNITS, normalize
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.requirements.contracts import RequirementProposal, VerifiedRequirement

_CANONICAL_UNIT = {
    "journal_diameter": "mm", "load": "N", "rotational_speed": "rpm",
    "bearing_width": "mm", "radial_clearance": "mm",
}
_SCOPE = {"supported": "cylindrical_radial_hydrodynamic", "unsupported": "unsupported"}
_UNIT_ALIASES = {
    "毫米": "mm", "米": "m", "千牛": "kN", "转/分": "rpm", "r/min": "rpm",
}
_FIELD_WORDS = {
    "journal_diameter": ("轴径", "轴颈", "D="),
    "load": ("载荷", "F="),
    "rotational_speed": ("转速", "n="),
    "bearing_width": ("宽度",),
    "radial_clearance": ("间隙",),
}
_UNIT_WORDS = {
    "mm": ("mm", "毫米"), "m": ("m", "米"),
    "N": ("N", "牛"), "kN": ("kN", "千牛"),
    "rpm": ("rpm", "r/min", "转/分"),
}
_UNCERTAIN = ("估计", "大概", "大约", "不确定", "左右", "约为")
_NEGATED = ("不是", "不对", "并非", "不要", "错了", "错误", "更正", "改成", "改为")


def claim_context(text: str, start: int, end: int) -> str:
    """Find a local clause for the *offline* deterministic pattern extractor."""
    left = re.split(r"[，,。；;！？!?\n]", text[max(0, start-14):start])[-1]
    right = text[end:min(len(text), end+16)]
    parts = re.split(r"[，,。；;！？!?\n]", right, maxsplit=1)
    trailer = parts[1].lstrip() if len(parts) > 1 else ""
    context = left + text[start:end] + parts[0]
    if trailer.startswith(("不确定", "我还不确定", "可能", "不是", "不对", "错了")):
        context += trailer[:9]
    return context


def _normalize_value(field: str, value: float, unit: str,
                     registry: ParameterSchemaRegistry) -> tuple[float, str]:
    unit = _UNIT_ALIASES.get(unit, unit)
    target = _CANONICAL_UNIT[field]
    schema = registry.get(field)
    if schema is None or schema.dimension is None or unit not in UNITS:
        raise ValueError("Unrecognized engineering dimension or unit")
    base_value, _ = normalize(value, unit, schema.dimension)
    base_target, _ = normalize(1.0, target, schema.dimension)
    normalized = base_value / base_target
    registry.validate(field, normalized, target)
    return normalized, target


def _known_claims(text: str, proposal: RequirementProposal):
    # Pattern-based checks are a simple consistency safeguard for recognized
    # expressions; no model-created character spans are checked or trusted.
    from bearing_agents.requirements.extraction import extract

    return [
        item for item in extract(text)
        if item.kind == proposal.kind and item.field_id == proposal.field_id
    ]


def verify(text: str, proposal: RequirementProposal, registry: ParameterSchemaRegistry
           ) -> VerifiedRequirement:
    def result(code: str, reason: str, value=None, unit=None):
        return VerifiedRequirement(
            proposal=proposal, decision=code, reason=reason,
            normalized_value=value, normalized_unit=unit,
        )

    if proposal.modality != "EXPLICIT":
        return result("CLARIFY", "NOT_EXPLICIT")
    if proposal.kind == "scope":
        if _SCOPE.get(proposal.field_id) != proposal.value:
            return result("REJECT", "SCOPE_MISMATCH")
        if not any(x in text for x in ("轴承", "可倾瓦", "静压")):
            return result("CLARIFY", "SCOPE_NOT_STATED")
        matches = _known_claims(text, proposal)
        if matches and any(item.value != proposal.value for item in matches):
            return result("REJECT", "SCOPE_CONFLICT")
        return result("ACCEPT", "VALIDATED", proposal.value)
    if proposal.kind == "steady_state":
        expected = {"steady": True, "dynamic": False}.get(proposal.field_id)
        actual = (
            proposal.value if isinstance(proposal.value, bool)
            else str(proposal.value).lower() == "true"
            if str(proposal.value).lower() in {"true", "false"} else None
        )
        if expected is None or expected != actual:
            return result("REJECT", "STEADY_MISMATCH")
        if not any(word in text for word in ("稳态", "稳定", "恒定", "动态", "工况")):
            return result("CLARIFY", "REGIME_NOT_STATED")
        matches = _known_claims(text, proposal)
        if matches and any(item.value != proposal.value for item in matches):
            return result("REJECT", "REGIME_CONFLICT")
        return result("ACCEPT", "VALIDATED", proposal.value)

    if proposal.kind not in {"parameter", "constraint", "preference"}:
        return result("REJECT", "UNSUPPORTED_KIND")
    if proposal.kind in {"constraint", "preference"}:
        if proposal.field_id == "material":
            if proposal.operator not in {"IN", "NOT_IN"}:
                return result("REJECT", "MATERIAL_OPERATOR_INVALID")
            if not isinstance(proposal.value, str) or not proposal.value.strip():
                return result("REJECT", "MATERIAL_VALUE_INVALID")
            if not any(x in text for x in ("材料", "不能用", "禁止", "不得使用")):
                return result("CLARIFY", "MATERIAL_NOT_STATED")
            try:
                registry.validate("material", proposal.value, "1")
            except ValueError:
                return result("REJECT", "MATERIAL_VALUE_INVALID")
            return result("ACCEPT", "VALIDATED", proposal.value, "1")
        if proposal.field_id != "bearing_width" or proposal.operator != "LE":
            return result("CLARIFY", "CONSTRAINT_UNSUPPORTED")
        if proposal.kind == "constraint" and any(
            mark in text for mark in ("最好", "尽量", "希望")
        ) and not any(mark in text for mark in ("必须", "硬性", "强制")):
            return result("CLARIFY", "SOFT_PREFERENCE_NOT_HARD_CONSTRAINT")
        if not any(word in text for word in ("宽度", "安装空间")):
            return result("CLARIFY", "CONSTRAINT_NOT_STATED")
    elif proposal.field_id not in _CANONICAL_UNIT:
        return result("CLARIFY", "UNKNOWN_INPUT_FIELD")

    field = proposal.field_id
    if not isinstance(proposal.value, (int, float)) or isinstance(proposal.value, bool):
        return result("CLARIFY", "VALUE_NOT_NUMERIC")
    if not proposal.unit:
        return result("CLARIFY", "UNIT_MISSING")
    if not any(word in text for word in _FIELD_WORDS[field]):
        return result("CLARIFY", "FIELD_NOT_STATED")
    if not any(word in text for word in _UNIT_WORDS.get(
        _UNIT_ALIASES.get(proposal.unit, proposal.unit), ()
    )):
        return result("CLARIFY", "UNIT_NOT_STATED")
    try:
        value, unit = _normalize_value(
            field, float(proposal.value), proposal.unit, registry,
        )
    except (ValueError, TypeError, KeyError):
        return result("REJECT", "INVALID_ENGINEERING_VALUE")

    claims = _known_claims(text, proposal)
    if claims:
        if any(item.modality != "EXPLICIT" for item in claims):
            return result("CLARIFY", "UNCONFIRMED_INPUT")
        try:
            known = [
                _normalize_value(field, float(item.value), item.unit, registry)
                for item in claims
            ]
        except (ValueError, TypeError, KeyError):
            return result("CLARIFY", "KNOWN_INPUT_INVALID")
        if any(abs(item[0] - value) > max(1e-8, abs(value)*1e-9)
               or item[1] != unit for item in known):
            return result("REJECT", "KNOWN_VALUE_CONFLICT")
    else:
        # An LLM may understand a phrasing the patterns missed, but a declared
        # absent/unknown input must not turn into a verified numeric value.
        if any(x in text for x in ("没查到", "还没查", "不知道", "不清楚")):
            return result("CLARIFY", "UNKNOWN_INPUT")
    return result("ACCEPT", "VALIDATED", value, unit)
