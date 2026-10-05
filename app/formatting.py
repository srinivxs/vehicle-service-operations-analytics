"""Display formatting helpers (Indian lakh / crore currency, percentages, hours)."""

from __future__ import annotations

import math

MISSING = "—"  # em dash shown for NaN / None
RUPEE = "₹"
LAKH = 1e5
CRORE = 1e7


def _is_missing(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_inr(value: float | None, decimals: int = 1) -> str:
    """Format rupees in the Indian system: 7.8 Cr, 42.3 L, or plain digits below one lakh."""
    if _is_missing(value):
        return MISSING
    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    lakhs = round(amount / LAKH, decimals)
    if amount >= CRORE or lakhs >= 100:
        return f"{sign}{RUPEE}{amount / CRORE:.{decimals}f} Cr"
    if amount >= LAKH:
        return f"{sign}{RUPEE}{lakhs:.{decimals}f} L"
    return f"{sign}{RUPEE}{amount:,.0f}"


def fmt_pct(value: float | None, decimals: int = 1) -> str:
    """Format a fraction (0.732) as a percentage (73.2%)."""
    return MISSING if _is_missing(value) else f"{value * 100:.{decimals}f}%"


def fmt_hours(value: float | None, decimals: int = 1) -> str:
    """Format a duration in hours."""
    return MISSING if _is_missing(value) else f"{value:.{decimals}f} h"


def fmt_int(value: float | None) -> str:
    """Format a count with thousands separators."""
    return MISSING if _is_missing(value) else f"{value:,.0f}"


def fmt_rating(value: float | None) -> str:
    """Format a 1-5 rating."""
    return MISSING if _is_missing(value) else f"{value:.2f} / 5"


def fmt_signed_pct(value: float | None, decimals: int = 1) -> str:
    """Format a fraction with an explicit sign (+3.2%)."""
    return MISSING if _is_missing(value) else f"{value * 100:+.{decimals}f}%"


def month_label(year_month: str) -> str:
    """'2025-03' -> 'Mar 25' (compact axis label)."""
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    year, month = year_month.split("-")
    return f"{months[int(month) - 1]} {year[2:]}"
