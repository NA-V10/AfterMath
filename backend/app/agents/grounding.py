"""Grounding check: LLM prose may only mention entities and figures present in tool outputs."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.agents.resolver import CODE_RE
from app.agents.schemas import Grounding

# Decimals, numbers with thousands separators, 4+ digit integers, and percentages are checked.
# Small integers ("2 hours", "wave 3") are too ambiguous to check meaningfully.
NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d{4,})(%?)(?![\w])")


def number_variants(values: Iterable[float | int]) -> set[str]:
    out: set[str] = set()
    for v in values:
        if isinstance(v, int) or float(v).is_integer():
            i = int(v)
            out |= {str(i), f"{i:,}"}
        else:
            f = float(v)
            out |= {f"{f:.2f}", f"{f:.1f}", f"{f:g}", f"{round(f)}"}
            out |= {f"{f * 100:.0f}", f"{f * 100:.1f}"}  # fractions quoted as percentages
    return out


def check_grounding(
    text: str, allowed_codes: Iterable[str], allowed_numbers: Iterable[float | int]
) -> Grounding:
    codes = set(allowed_codes)
    numbers = number_variants(allowed_numbers)
    unknown_codes = sorted({m.group(1) for m in CODE_RE.finditer(text)} - codes)
    unknown_numbers = sorted({m.group(1) for m in NUMBER_RE.finditer(text)} - numbers)
    return Grounding(
        checked=True,
        ok=not unknown_codes and not unknown_numbers,
        unknown_asset_codes=unknown_codes,
        unknown_numbers=unknown_numbers,
    )
