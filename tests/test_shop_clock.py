"""Unit tests for the shop-hours clock (Mon-Sat, 09:00-19:00)."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from src.config import SHOP_CLOSE_HOUR, SHOP_OPEN_HOUR
from src.generate_data import add_work_hours, align_to_open, round_quarter

pytestmark = pytest.mark.unit

# 2025-03-03 is a Monday; 2025-03-08 a Saturday; 2025-03-02 a Sunday.
MON = datetime(2025, 3, 3)
SAT = datetime(2025, 3, 8)
SUN = datetime(2025, 3, 2)


def at(day: datetime, hour: int, minute: int = 0, second: int = 0, micro: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute, second=second, microsecond=micro)


def test_calendar_assumptions():
    assert (MON.weekday(), SAT.weekday(), SUN.weekday()) == (0, 5, 6)
    assert (SHOP_OPEN_HOUR, SHOP_CLOSE_HOUR) == (9, 19)


# --------------------------------------------------------------------------- #
# align_to_open
# --------------------------------------------------------------------------- #
class TestAlignToOpen:
    @pytest.mark.parametrize("hour", [0, 8, 9, 12, 19, 23])
    def test_sunday_always_rolls_to_monday_open(self, hour):
        assert align_to_open(at(SUN, hour, 30)) == at(MON, 9)

    @pytest.mark.parametrize("ts", [at(MON, 0), at(MON, 7, 59), at(MON, 8, 59, 59, 999999)])
    def test_before_open_moves_to_same_day_open(self, ts):
        assert align_to_open(ts) == at(MON, 9)

    @pytest.mark.parametrize("ts", [at(MON, 19), at(MON, 19, 0, 1), at(MON, 23, 59, 59)])
    def test_at_or_after_close_moves_to_next_day_open(self, ts):
        assert align_to_open(ts) == at(datetime(2025, 3, 4), 9)

    @pytest.mark.parametrize("ts", [at(MON, 9), at(MON, 12, 34, 56, 789), at(MON, 18, 59, 59, 999999)])
    def test_inside_opening_hours_unchanged(self, ts):
        assert align_to_open(ts) == ts

    def test_saturday_evening_skips_sunday(self):
        assert align_to_open(at(SAT, 19, 30)) == at(datetime(2025, 3, 10), 9)

    def test_saturday_before_open_stays_on_saturday(self):
        assert align_to_open(at(SAT, 6)) == at(SAT, 9)

    def test_year_boundary(self):
        assert align_to_open(datetime(2025, 12, 31, 20, 0)) == datetime(2026, 1, 1, 9, 0)

    def test_idempotent_and_never_earlier(self):
        start = datetime(2025, 3, 1)
        for step in range(0, 24 * 14 * 2):  # every 30 minutes for two weeks
            ts = start + timedelta(minutes=30 * step)
            out = align_to_open(ts)
            assert out >= ts
            assert out.weekday() != 6
            assert SHOP_OPEN_HOUR <= out.hour < SHOP_CLOSE_HOUR
            assert align_to_open(out) == out


# --------------------------------------------------------------------------- #
# add_work_hours
# --------------------------------------------------------------------------- #
class TestAddWorkHours:
    def test_within_a_single_day(self):
        assert add_work_hours(at(MON, 10), 2) == at(MON, 12)

    def test_fractional_hours(self):
        assert add_work_hours(at(MON, 10), 0.25) == at(MON, 10, 15)
        assert add_work_hours(at(MON, 10), 1.5) == at(MON, 11, 30)

    def test_ending_exactly_at_close_stays_same_day(self):
        assert add_work_hours(at(MON, 17), 2) == at(MON, 19)
        assert add_work_hours(at(MON, 9), 10) == at(MON, 19)

    def test_spanning_close_continues_next_morning(self):
        # 2h left on Monday, 1h carried over to Tuesday 09:00 -> 10:00.
        assert add_work_hours(at(MON, 17), 3) == at(datetime(2025, 3, 4), 10)

    def test_multi_day_span(self):
        # 10h Monday + 10h Tuesday + 5h Wednesday.
        assert add_work_hours(at(MON, 9), 25) == at(datetime(2025, 3, 5), 14)

    def test_spanning_saturday_close_lands_on_monday(self):
        assert add_work_hours(at(SAT, 17), 3) == at(datetime(2025, 3, 10), 10)

    def test_start_on_sunday_begins_monday(self):
        assert add_work_hours(at(SUN, 12), 1) == at(MON, 10)

    def test_start_before_open_begins_at_open(self):
        assert add_work_hours(at(MON, 7), 1) == at(MON, 10)

    def test_start_after_close_begins_next_morning(self):
        assert add_work_hours(at(MON, 20), 1) == at(datetime(2025, 3, 4), 10)

    @pytest.mark.parametrize("hours", [0, 0.0, -3, -0.5])
    def test_zero_or_negative_hours_do_not_advance(self, hours):
        assert add_work_hours(at(MON, 10, 30), hours) == at(MON, 10, 30)

    def test_zero_hours_still_aligns_to_open(self):
        assert add_work_hours(at(SUN, 12), 0) == at(MON, 9)
        assert add_work_hours(at(MON, 20), 0) == at(datetime(2025, 3, 4), 9)
        assert add_work_hours(at(MON, 3), 0) == at(MON, 9)

    def test_monotonic_and_always_within_open_hours(self):
        start = datetime(2025, 3, 1, 8, 0)
        for step in range(0, 200):
            ts = start + timedelta(minutes=95 * step)
            for hours in (0.25, 3.0, 9.5, 12.0):
                out = add_work_hours(ts, hours)
                assert out >= align_to_open(ts)
                assert out.weekday() != 6
                day_open = out.replace(hour=9, minute=0, second=0, microsecond=0)
                day_close = out.replace(hour=19, minute=0, second=0, microsecond=0)
                assert day_open <= out <= day_close

    def test_additivity_across_split(self):
        ts = at(MON, 15)
        direct = add_work_hours(ts, 14.5)
        stepped = add_work_hours(add_work_hours(ts, 6), 8.5)
        assert direct == stepped


# --------------------------------------------------------------------------- #
# round_quarter
# --------------------------------------------------------------------------- #
class TestRoundQuarter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (1.0, 1.0),
            (1.1, 1.0),
            (1.13, 1.25),
            (1.24, 1.25),
            (2.37, 2.25),
            (2.38, 2.5),
            (10.0, 10.0),
        ],
    )
    def test_rounds_to_nearest_quarter(self, value, expected):
        assert round_quarter(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", [0, 0.0, 0.01, 0.1, -1.0, -100.0])
    def test_floor_is_a_quarter_hour(self, value):
        assert round_quarter(value) == 0.25

    @pytest.mark.parametrize("value, expected", [(0.375, 0.5), (0.625, 0.5), (0.875, 1.0)])
    def test_exact_midpoints_use_bankers_rounding(self, value, expected):
        # Characterisation: Python's round() is used, so .5 ties go to the even quarter.
        assert round_quarter(value) == expected

    def test_accepts_numpy_floats(self):
        assert round_quarter(np.float64(1.9)) == pytest.approx(2.0)

    def test_result_is_always_a_multiple_of_a_quarter(self):
        for x in np.linspace(0, 12, 481):
            r = round_quarter(float(x))
            assert r >= 0.25
            assert (r * 4) == pytest.approx(round(r * 4))
