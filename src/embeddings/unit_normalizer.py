"""Deterministic unit string normalizer for product quantities."""

import logging
import re

logger = logging.getLogger(__name__)

# Conversion tables
VOLUME_TO_ML: dict[str, float] = {
    "ml": 1.0,
    "l": 1000.0,
    "ltr": 1000.0,
    "litre": 1000.0,
    "liter": 1000.0,
    "litres": 1000.0,
    "liters": 1000.0,
}

WEIGHT_TO_G: dict[str, float] = {
    "g": 1.0,
    "gm": 1.0,
    "gms": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kgs": 1000.0,
}

COUNT_UNITS: set[str] = {"pcs", "pc", "piece", "pieces", "pack", "packs", "unit", "units", "dozen", "nos", "no"}

# Pattern: number (with optional decimal) + optional space + unit
_UNIT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)",
    re.IGNORECASE,
)


def normalize_unit(raw: str | None) -> str | None:
    """Normalize a product unit string to a standard form.

    Examples:
        "500 ml" -> "500ml"
        "0.5 L" -> "500ml"
        "1 Kg" -> "1kg"
        "1000g" -> "1kg"
        "6 pcs" -> "6pcs"

    Returns None for unparseable inputs.
    """
    if not raw or not raw.strip():
        return None

    raw = raw.strip().lower()

    match = _UNIT_PATTERN.search(raw)
    if not match:
        logger.debug("Could not parse unit: %s", raw)
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()

    # Volume normalization (to ml, display as ml or L)
    if unit in VOLUME_TO_ML:
        ml = value * VOLUME_TO_ML[unit]
        ml = int(ml) if ml == int(ml) else ml
        if ml >= 1000 and ml % 1000 == 0:
            return f"{int(ml // 1000)}l"
        return f"{ml}ml" if isinstance(ml, int) else f"{ml}ml"

    # Weight normalization (to g, display as g or kg)
    if unit in WEIGHT_TO_G:
        g = value * WEIGHT_TO_G[unit]
        g = int(g) if g == int(g) else g
        if g >= 1000 and g % 1000 == 0:
            return f"{int(g // 1000)}kg"
        return f"{g}g" if isinstance(g, int) else f"{g}g"

    # Count units
    if unit in COUNT_UNITS:
        count = int(value) if value == int(value) else value
        if unit == "dozen":
            return f"{count}dozen"
        return f"{count}pcs"

    logger.debug("Unknown unit type: %s (from %s)", unit, raw)
    return None
