"""Data-driven "Key insight" sentences for each dashboard page.

Every number and name in the returned text is computed from the filtered data;
nothing is hardcoded. Functions return an empty string when there is not enough
data to say anything useful.
"""

from __future__ import annotations

import pandas as pd

from app.formatting import fmt_hours, fmt_inr, fmt_pct, month_label


def _extremes(df: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series] | None:
    """(lowest row, highest row) by ``column`` ignoring NaN; None if fewer than 2 rows."""
    valid = df.dropna(subset=[column])
    if len(valid) < 2:
        return None
    return valid.loc[valid[column].idxmin()], valid.loc[valid[column].idxmax()]


def executive_insight(scorecard: pd.DataFrame, network_on_time: float) -> str:
    """Worst on-time centre vs the network average and best-ranked centre."""
    pair = _extremes(scorecard, "on_time_pct")
    if pair is None:
        return ""
    worst, best = pair
    gap = (best["on_time_pct"] - worst["on_time_pct"]) * 100
    top = scorecard.loc[scorecard["rank"].idxmin()]
    return (
        f"{worst['center_name']} has the lowest on-time rate at {fmt_pct(worst['on_time_pct'])} "
        f"(network {fmt_pct(network_on_time)}), {gap:.1f} points behind {best['center_name']}. "
        f"{top['center_name']} ranks first overall on the performance index."
    )


def operations_insight(scorecard: pd.DataFrame, weekday_wait: pd.DataFrame) -> str:
    """Slowest centre by average turnaround and the weekday with the longest wait."""
    parts: list[str] = []
    pair = _extremes(scorecard, "avg_turnaround")
    if pair is not None:
        _, slowest = pair
        parts.append(
            f"{slowest['center_name']} is slowest, averaging {fmt_hours(slowest['avg_turnaround'])} "
            f"turnaround (median {fmt_hours(slowest['median_turnaround'])})."
        )
    wait = _extremes(weekday_wait, "avg_wait")
    if wait is not None:
        _, longest = wait
        parts.append(
            f"Customers wait longest on {longest['weekday']}s "
            f"({fmt_hours(longest['avg_wait'])} before work starts)."
        )
    return " ".join(parts)


def financial_insight(by_service: pd.DataFrame, trend: pd.DataFrame) -> str:
    """Highest- and lowest-margin service types and the best profit month."""
    parts: list[str] = []
    pair = _extremes(by_service, "margin_pct")
    if pair is not None:
        low, high = pair
        parts.append(
            f"{high['service_type']} earns the best margin ({fmt_pct(high['margin_pct'])}) while "
            f"{low['service_type']} earns the lowest ({fmt_pct(low['margin_pct'])})."
        )
    if not trend.empty:
        best = trend.loc[trend["profit"].idxmax()]
        parts.append(
            f"Profit peaked in {month_label(best['month'])} at {fmt_inr(best['profit'])}."
        )
    return " ".join(parts)


def customer_insight(
    by_centre: pd.DataFrame, by_lead: pd.DataFrame, rating_column: str = "avg_rating"
) -> str:
    """Lowest-rated centre and the lead-time band that loses the most appointments."""
    parts: list[str] = []
    pair = _extremes(by_centre, rating_column)
    if pair is not None:
        lowest, _ = pair
        parts.append(
            f"{lowest['center_name']} has the lowest average rating "
            f"({lowest[rating_column]:.2f} / 5)."
        )
    lead = _extremes(by_lead, "cancellation_rate")
    if lead is not None:
        _, worst = lead
        parts.append(
            f"Appointments booked {worst['lead_time_band']} ahead are cancelled most often "
            f"({fmt_pct(worst['cancellation_rate'])})."
        )
    return " ".join(parts)
