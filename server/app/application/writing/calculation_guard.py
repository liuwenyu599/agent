"""Deterministic arithmetic verification for generated official documents.

LLMs understand the prose relationship; Python owns arithmetic.  This module is deliberately
conservative: it only rewrites claims where the operands and the claimed result are both explicit
in the same local sentence/paragraph.  Unknown relationships are left untouched rather than
inventing a formula.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Tuple


_Q2 = Decimal("0.01")


def _fmt(value: Decimal) -> str:
    value = value.quantize(_Q2, rounding=ROUND_HALF_UP)
    return format(value, "f").rstrip("0").rstrip(".")


def _same_money(expected_yuan: Decimal, stated: Decimal, stated_unit: str) -> bool:
    expected = expected_yuan / Decimal("10000") if "万" in stated_unit else expected_yuan
    return abs(expected - stated) < Decimal("0.005")


# Explicit formula, e.g. 1336×150×12=239.85万元.
_EXPLICIT_MUL = re.compile(
    r"(?P<a>\d+(?:\.\d+)?)\s*[×xX*]\s*"
    r"(?P<b>\d+(?:\.\d+)?)"
    r"(?:\s*[×xX*]\s*(?P<c>\d+(?:\.\d+)?))?"
    r"\s*(?:=|＝|合计|共计|总计|应为|为)\s*"
    r"(?P<stated>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元)"
)

# Natural official-document wording, e.g.
# “1336人，按每人每月150元补助，补助12个月，共计239.85万元”。
_PER_PERSON_MONTH = re.compile(
    r"(?P<count>\d+(?:\.\d+)?)\s*(?:人|名|户)"
    r"(?P<middle1>[^。；;\n]{0,90}?)"
    r"每(?:人|名|户)每月\s*(?P<rate>\d+(?:\.\d+)?)\s*元"
    r"(?P<middle2>[^。；;\n]{0,90}?)"
    r"(?P<months>\d+(?:\.\d+)?)\s*(?:个)?月"
    r"(?P<middle3>[^。；;\n]{0,90}?)"
    r"(?:合计|共计|总计|预算(?:为)?|金额(?:为)?|需(?:资金|经费)?)[：:]?\s*"
    r"(?P<stated>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元)"
)

# Quantity × unit price, e.g. “采购120台，每台3500元，共计41万元”。
_QUANTITY_UNIT_PRICE = re.compile(
    r"(?P<count>\d+(?:\.\d+)?)\s*(?P<count_unit>台|套|件|册|份|个)"
    r"(?P<middle1>[^。；;\n]{0,90}?)"
    r"每(?:台|套|件|册|份|个)\s*(?P<rate>\d+(?:\.\d+)?)\s*元"
    r"(?P<middle2>[^。；;\n]{0,90}?)"
    r"(?:合计|共计|总计|预算(?:为)?|金额(?:为)?)[：:]?\s*"
    r"(?P<stated>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元)"
)


def _replace_result(match: re.Match, expected_yuan: Decimal, events: List[str]) -> str:
    try:
        stated = Decimal(match.group("stated"))
    except (InvalidOperation, TypeError):
        return match.group(0)
    unit = match.group("unit")
    if _same_money(expected_yuan, stated, unit):
        return match.group(0)
    expected_display = expected_yuan / Decimal("10000") if "万" in unit else expected_yuan
    shown = _fmt(expected_display)
    old = match.group("stated")
    events.append(f"算术校验：{old}{unit} → {shown}{unit}")
    rel_start = match.start("stated") - match.start()
    rel_end = match.end("stated") - match.start()
    raw = match.group(0)
    return raw[:rel_start] + shown + raw[rel_end:]


def verify_and_fix_calculations(text: str) -> Tuple[str, List[str]]:
    """Verify explicit derived-money claims and repair only provably wrong results."""
    events: List[str] = []

    def explicit(m: re.Match) -> str:
        try:
            value = Decimal(m.group("a")) * Decimal(m.group("b"))
            if m.group("c"):
                value *= Decimal(m.group("c"))
        except (InvalidOperation, TypeError):
            return m.group(0)
        return _replace_result(m, value, events)

    def ppm(m: re.Match) -> str:
        try:
            value = Decimal(m.group("count")) * Decimal(m.group("rate")) * Decimal(m.group("months"))
        except (InvalidOperation, TypeError):
            return m.group(0)
        return _replace_result(m, value, events)

    def unit_price(m: re.Match) -> str:
        try:
            value = Decimal(m.group("count")) * Decimal(m.group("rate"))
        except (InvalidOperation, TypeError):
            return m.group(0)
        return _replace_result(m, value, events)

    out = _EXPLICIT_MUL.sub(explicit, text or "")
    out = _PER_PERSON_MONTH.sub(ppm, out)
    out = _QUANTITY_UNIT_PRICE.sub(unit_price, out)
    return out, events
