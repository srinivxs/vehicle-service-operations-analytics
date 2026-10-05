"""Unit tests for the pure dashboard helpers: formatting, insights and axis ticks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import components, insights
from app.formatting import (
    MISSING,
    fmt_hours,
    fmt_inr,
    fmt_int,
    fmt_pct,
    fmt_rating,
    fmt_signed_pct,
    month_label,
)


class TestFormatting:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (78_238_663, "₹7.8 Cr"),
            (4_230_000, "₹42.3 L"),
            (45_200, "₹45,200"),
            (0, "₹0"),
            (-4_230_000, "-₹42.3 L"),
            (9_996_000, "₹1.0 Cr"),  # rounds up across the lakh/crore boundary
            (100_000, "₹1.0 L"),
        ],
    )
    def test_fmt_inr(self, value, expected):
        assert fmt_inr(value) == expected

    def test_fmt_inr_decimals(self):
        assert fmt_inr(12_345_678, decimals=2) == "₹1.23 Cr"

    @pytest.mark.parametrize("fn", [fmt_inr, fmt_pct, fmt_hours, fmt_int, fmt_rating, fmt_signed_pct])
    @pytest.mark.parametrize("missing", [None, float("nan"), np.nan])
    def test_missing_values(self, fn, missing):
        assert fn(missing) == MISSING

    def test_other_formats(self):
        assert fmt_pct(0.7321) == "73.2%"
        assert fmt_hours(2.5) == "2.5 h"
        assert fmt_int(24092) == "24,092"
        assert fmt_rating(4.0205) == "4.02 / 5"
        assert fmt_signed_pct(0.032) == "+3.2%"
        assert fmt_signed_pct(-0.05) == "-5.0%"

    def test_month_label(self):
        assert month_label("2025-03") == "Mar 25"
        assert month_label("2026-12") == "Dec 26"


class TestNiceTicks:
    def test_ticks_cover_range_and_are_round(self):
        ticks = components.nice_ticks(0, 7_800_000)
        assert ticks[0] == 0 and ticks[-1] <= 7_800_000
        steps = {round(b - a) for a, b in zip(ticks, ticks[1:])}
        assert len(steps) == 1

    def test_degenerate_range(self):
        assert components.nice_ticks(5, 5) == [5]

    def test_negative_lower_bound(self):
        assert min(components.nice_ticks(-100, 100)) >= -100


def _scorecard() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "center_name": ["A", "B", "C"],
            "on_time_pct": [0.9, 0.6, 0.8],
            "avg_turnaround": [4.0, 9.0, 5.0],
            "median_turnaround": [3.0, 4.0, 3.5],
            "rank": [1.0, 3.0, 2.0],
        }
    )


class TestInsights:
    def test_executive_insight_names_worst_centre_and_values(self):
        text = insights.executive_insight(_scorecard(), 0.77)
        assert "B has the lowest on-time rate at 60.0%" in text
        assert "network 77.0%" in text
        assert "30.0 points behind A" in text
        assert "A ranks first" in text

    def test_executive_insight_needs_two_centres(self):
        assert insights.executive_insight(_scorecard().iloc[:1], 0.8) == ""

    def test_operations_insight(self):
        weekday = pd.DataFrame({"weekday": ["Monday", "Saturday"], "avg_wait": [0.5, 3.0]})
        text = insights.operations_insight(_scorecard(), weekday)
        assert "B is slowest, averaging 9.0 h" in text
        assert "Saturdays" in text

    def test_operations_insight_empty(self):
        empty = pd.DataFrame(columns=["weekday", "avg_wait", "center_name", "avg_turnaround"])
        assert insights.operations_insight(empty, empty) == ""

    def test_financial_insight(self):
        by_service = pd.DataFrame(
            {"service_type": ["X", "Y"], "margin_pct": [0.1, 0.4]}
        )
        trend = pd.DataFrame({"month": ["2025-01", "2025-02"], "profit": [100_000.0, 250_000.0]})
        text = insights.financial_insight(by_service, trend)
        assert "Y earns the best margin (40.0%)" in text
        assert "X earns the lowest (10.0%)" in text
        assert "Feb 25" in text and "₹2.5 L" in text

    def test_financial_insight_empty(self):
        assert insights.financial_insight(pd.DataFrame(columns=["margin_pct"]),
                                          pd.DataFrame(columns=["month", "profit"])) == ""

    def test_customer_insight(self):
        by_centre = pd.DataFrame({"center_name": ["A", "B"], "avg_rating": [4.5, 3.6]})
        by_lead = pd.DataFrame(
            {"lead_time_band": ["Same day", "15+ days"], "cancellation_rate": [0.0, 0.2]}
        )
        text = insights.customer_insight(by_centre, by_lead)
        assert "B has the lowest average rating (3.60 / 5)" in text
        assert "15+ days ahead" in text and "20.0%" in text

    def test_customer_insight_empty(self):
        assert insights.customer_insight(pd.DataFrame(columns=["avg_rating"]),
                                         pd.DataFrame(columns=["cancellation_rate"])) == ""
