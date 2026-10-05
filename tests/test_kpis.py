"""Unit tests for src/kpis.py using small hand-built frames with known answers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import kpis
from src.kpis import Filters

FACT_DEFAULTS: dict = {
    "appointment_id": "A",
    "technician_id": "T1",
    "service_type": "Periodic Service",
    "model": "Ather 450X",
    "center_id": "C001",
    "center_name": "Alpha",
    "region": "South",
    "skill_level": "Senior",
    "customer_id": "CU1",
    "service_date": "2025-01-10",
    "month": "2025-01",
    "estimated_hours": 2.0,
    "actual_hours": 2.0,
    "duration_variance_hours": 0.0,
    "wait_hours": 1.0,
    "turnaround_hours": 3.0,
    "late_hours": 0.0,
    "on_time_flag": True,
    "labor_cost": 100.0,
    "parts_cost": 300.0,
    "revenue": 500.0,
    "cost_variance": 0.0,
    "cost_variance_pct": 0.0,
    "cost_overrun_flag": False,
    "rating": 5.0,
    "feedback_category": "Positive Experience",
    "qc_passed_first_time": True,
    "caused_repeat_visit": False,
    "parts_delay_flag": False,
}


def make_fact(rows: list[dict]) -> pd.DataFrame:
    """Build a fact_service-like frame; each row overrides FACT_DEFAULTS."""
    records = [
        {**FACT_DEFAULTS, "work_order_id": f"WO{i}", **row} for i, row in enumerate(rows, start=1)
    ]
    df = pd.DataFrame(records)
    df["service_date"] = pd.to_datetime(df["service_date"])
    return df


def make_appts(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "center_name": "Alpha",
        "region": "South",
        "model": "Ather 450X",
        "requested_service_type": "Periodic Service",
        "scheduled_date": "2025-01-10",
        "lead_time_band": "1-3 days",
        "cancellation_reason": None,
        "is_cancelled": False,
        "is_no_show": False,
    }
    records = [{**defaults, "appointment_id": f"AP{i}", **row} for i, row in enumerate(rows, 1)]
    df = pd.DataFrame(records)
    df["scheduled_date"] = pd.to_datetime(df["scheduled_date"])
    return df


def make_tech(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "technician_id": "T1",
        "center_id": "C001",
        "center_name": "Alpha",
        "region": "South",
        "skill_level": "Senior",
        "month": "2025-01",
        "jobs": 10,
        "service_hours": 80.0,
        "available_hours": 160.0,
        "comebacks_caused": 0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


@pytest.fixture
def fact() -> pd.DataFrame:
    return make_fact(
        [
            {  # Alpha, on time, 5 star, repeat customer CU1
                "revenue": 1000.0, "labor_cost": 200.0, "parts_cost": 400.0, "rating": 5.0,
                "turnaround_hours": 2.0, "wait_hours": 0.5, "customer_id": "CU1",
                "cost_variance": 50.0, "cost_overrun_flag": True, "estimated_hours": 2.0,
                "actual_hours": 2.5, "duration_variance_hours": 0.5,
            },
            {  # Alpha, late, 3 star, CU1 again, caused a comeback
                "revenue": 600.0, "labor_cost": 100.0, "parts_cost": 300.0, "rating": 3.0,
                "turnaround_hours": 6.0, "wait_hours": 1.5, "customer_id": "CU1",
                "on_time_flag": False, "late_hours": 1.5, "caused_repeat_visit": True,
                "parts_delay_flag": True, "month": "2025-02", "service_date": "2025-02-04",
                "feedback_category": "Turnaround Time", "qc_passed_first_time": False,
            },
            {  # Beta, on time, unrated, CU2
                "center_name": "Beta", "region": "North", "service_type": "Brake Service",
                "model": "Ather Rizta", "revenue": 400.0, "labor_cost": 100.0,
                "parts_cost": 100.0, "rating": np.nan, "feedback_category": None,
                "customer_id": "CU2", "technician_id": "T2", "skill_level": "Junior",
                "turnaround_hours": 4.0, "wait_hours": 1.0, "late_hours": 0.0,
                "service_date": "2025-02-20", "month": "2025-02",
            },
            {  # Beta, late, 4 star, CU3
                "center_name": "Beta", "region": "North", "service_type": "Brake Service",
                "model": "Ather Rizta", "revenue": 200.0, "labor_cost": 50.0,
                "parts_cost": 50.0, "rating": 4.0, "customer_id": "CU3", "technician_id": "T2",
                "skill_level": "Junior", "turnaround_hours": 12.0, "wait_hours": 2.0,
                "on_time_flag": False, "late_hours": 9.0, "service_date": "2025-03-05",
                "month": "2025-03", "feedback_category": "Parts Availability",
            },
        ]
    )


@pytest.fixture
def appts() -> pd.DataFrame:
    return make_appts(
        [
            {},
            {"is_cancelled": True, "cancellation_reason": "Price Concern",
             "lead_time_band": "4-7 days"},
            {"is_no_show": True, "lead_time_band": "Same day"},
            {"center_name": "Beta", "region": "North", "is_cancelled": True,
             "cancellation_reason": "Personal Reasons", "scheduled_date": "2025-02-10"},
        ]
    )


@pytest.fixture
def tech() -> pd.DataFrame:
    return make_tech(
        [
            {},
            {"month": "2025-02", "service_hours": 120.0, "available_hours": 160.0},
            {"technician_id": "T2", "center_name": "Beta", "region": "North",
             "skill_level": "Junior", "service_hours": 40.0, "available_hours": 160.0,
             "jobs": 5, "comebacks_caused": 2},
        ]
    )


# --------------------------------------------------------------------------- #
# Scalar helpers
# --------------------------------------------------------------------------- #
class TestScalarHelpers:
    def test_safe_ratio_normal(self):
        assert kpis.safe_ratio(1, 4) == 0.25

    @pytest.mark.parametrize("denominator", [0, np.nan, None])
    def test_safe_ratio_degenerate_denominator_is_nan(self, denominator):
        assert np.isnan(kpis.safe_ratio(5, denominator))

    def test_total_cost_is_labour_plus_parts(self, fact):
        assert kpis.total_cost(fact) == 600 + 400 + 200 + 100

    def test_repeat_visit_rate(self, fact):
        # CU1 has 2 orders; CU2 and CU3 have 1 -> 1/3
        assert kpis.repeat_visit_rate(fact) == pytest.approx(1 / 3)

    def test_repeat_visit_rate_empty_is_nan(self, fact):
        assert np.isnan(kpis.repeat_visit_rate(fact.iloc[0:0]))

    def test_utilisation(self, tech):
        assert kpis.utilisation(tech) == pytest.approx((80 + 120 + 40) / (160 * 3))

    def test_utilisation_zero_available_is_nan(self):
        assert np.isnan(kpis.utilisation(make_tech([{"available_hours": 0.0}])))

    def test_csat_share_ignores_nan(self):
        assert kpis.csat_share(pd.Series([5, 4, 3, np.nan])) == pytest.approx(2 / 3)

    def test_csat_share_all_nan_is_nan(self):
        assert np.isnan(kpis.csat_share(pd.Series([np.nan, np.nan])))


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
class TestFilters:
    def test_empty_filter_keeps_everything(self, fact):
        assert len(kpis.apply_filters(fact, Filters())) == len(fact)

    def test_date_range_is_inclusive(self, fact):
        out = kpis.apply_filters(fact, Filters(start=date(2025, 2, 4), end=date(2025, 2, 20)))
        assert list(out["work_order_id"]) == ["WO2", "WO3"]

    def test_open_ended_date_ranges(self, fact):
        assert len(kpis.apply_filters(fact, Filters(start=date(2025, 2, 5)))) == 2
        assert len(kpis.apply_filters(fact, Filters(end=date(2025, 2, 5)))) == 2

    def test_end_date_includes_timestamps_on_that_day(self):
        df = make_fact([{"service_date": "2025-02-04 15:30"}])
        out = kpis.apply_filters(df, Filters(end=date(2025, 2, 4)))
        assert len(out) == 1

    def test_dimension_filters_combine_with_and(self, fact):
        flt = Filters(regions=("North",), centres=("Beta",), service_types=("Brake Service",),
                      models=("Ather Rizta",))
        assert len(kpis.apply_filters(fact, flt)) == 2
        conflicting = Filters(regions=("North",), centres=("Alpha",))
        assert kpis.apply_filters(fact, conflicting).empty

    def test_empty_result_does_not_crash_downstream(self, fact, appts, tech):
        flt = Filters(centres=("Nowhere",))
        f = kpis.apply_filters(fact, flt)
        a = kpis.apply_filters(appts, flt, kpis.APPOINTMENT_COLUMNS)
        t = kpis.apply_filters(tech, flt, kpis.TECH_MONTH_COLUMNS)
        assert f.empty and a.empty and t.empty
        assert kpis.headline_kpis(f, a, t)["revenue"] == 0

    def test_appointments_use_scheduled_date_and_service_type(self, appts):
        flt = Filters(start=date(2025, 2, 1), end=date(2025, 2, 28))
        out = kpis.apply_filters(appts, flt, kpis.APPOINTMENT_COLUMNS)
        assert list(out["appointment_id"]) == ["AP4"]
        by_type = kpis.apply_filters(
            appts, Filters(service_types=("Brake Service",)), kpis.APPOINTMENT_COLUMNS
        )
        assert by_type.empty

    def test_tech_month_filter_uses_month_overlap(self, tech):
        flt = Filters(start=date(2025, 2, 15), end=date(2025, 2, 20))
        out = kpis.apply_filters(tech, flt, kpis.TECH_MONTH_COLUMNS)
        assert set(out["month"]) == {"2025-02"}

    def test_tech_month_ignores_service_type_and_model(self, tech):
        flt = Filters(service_types=("Brake Service",), models=("Nope",))
        assert len(kpis.apply_filters(tech, flt, kpis.TECH_MONTH_COLUMNS)) == len(tech)

    def test_tech_month_open_ended_and_centre(self, tech):
        out = kpis.apply_filters(
            tech, Filters(start=date(2025, 2, 1), centres=("Alpha",)), kpis.TECH_MONTH_COLUMNS
        )
        assert list(out["month"]) == ["2025-02"]
        assert len(kpis.apply_filters(tech, Filters(end=date(2025, 1, 31)), kpis.TECH_MONTH_COLUMNS)) == 2

    def test_enrich_technician_month(self):
        tm = pd.DataFrame({"technician_id": ["T1"], "center_id": ["C001"]})
        centers = pd.DataFrame(
            {"center_id": ["C001"], "center_name": ["Alpha"], "region": ["South"], "city": ["X"]}
        )
        out = kpis.enrich_technician_month(tm, centers)
        assert out.loc[0, "center_name"] == "Alpha" and out.loc[0, "region"] == "South"


# --------------------------------------------------------------------------- #
# Headline KPIs
# --------------------------------------------------------------------------- #
class TestHeadline:
    def test_fact_kpis_known_values(self, fact):
        k = kpis.fact_kpis(fact)
        assert k["work_orders"] == 4
        assert k["revenue"] == 2200
        assert k["total_cost"] == 1300
        assert k["profit"] == 900
        assert k["margin_pct"] == pytest.approx(900 / 2200)
        assert k["parts_share"] == pytest.approx(850 / 1300)
        assert k["avg_service_cost"] == pytest.approx(325)
        assert k["on_time_pct"] == 0.5
        assert k["avg_turnaround"] == pytest.approx(6.0)
        assert k["median_turnaround"] == pytest.approx(5.0)
        assert k["cost_variance"] == 50
        assert k["cost_overrun_rate"] == 0.25
        assert k["avg_rating"] == pytest.approx(4.0)  # NaN rating ignored
        assert k["csat_pct"] == pytest.approx(2 / 3)
        assert k["rated_orders"] == 3
        assert k["comeback_rate"] == 0.25
        assert k["parts_delay_rate"] == 0.25
        assert k["qc_first_pass_rate"] == 0.75
        assert k["avg_wait"] == pytest.approx(1.25)
        assert k["avg_duration_variance"] == pytest.approx(0.125)
        assert k["repeat_visit_rate"] == pytest.approx(1 / 3)

    def test_appointment_kpis(self, appts):
        k = kpis.appointment_kpis(appts)
        assert k["appointments"] == 4
        assert k["cancellation_rate"] == 0.5
        assert k["no_show_rate"] == 0.25

    def test_headline_combines_all_sources(self, fact, appts, tech):
        k = kpis.headline_kpis(fact, appts, tech)
        assert k["revenue"] == 2200
        assert k["cancellation_rate"] == 0.5
        assert k["utilisation"] == pytest.approx(240 / 480)

    def test_empty_inputs_return_zero_or_nan(self, fact, appts, tech):
        k = kpis.headline_kpis(fact.iloc[0:0], appts.iloc[0:0], tech.iloc[0:0])
        assert k["work_orders"] == 0 and k["revenue"] == 0 and k["profit"] == 0
        for key in ("margin_pct", "parts_share", "avg_service_cost", "on_time_pct", "avg_turnaround",
                    "median_turnaround", "avg_rating", "csat_pct", "repeat_visit_rate",
                    "cancellation_rate", "utilisation"):
            assert np.isnan(k[key]), key

    def test_zero_revenue_gives_nan_margin(self):
        df = make_fact([{"revenue": 0.0, "labor_cost": 10.0, "parts_cost": 0.0}])
        k = kpis.fact_kpis(df)
        assert k["profit"] == -10
        assert np.isnan(k["margin_pct"])

    def test_all_ratings_missing(self):
        df = make_fact([{"rating": np.nan}, {"rating": np.nan}])
        k = kpis.fact_kpis(df)
        assert np.isnan(k["avg_rating"]) and np.isnan(k["csat_pct"])
        assert k["rated_orders"] == 0


# --------------------------------------------------------------------------- #
# Grouped KPIs
# --------------------------------------------------------------------------- #
class TestGroupKpis:
    def test_by_single_column(self, fact):
        out = kpis.group_kpis(fact, "center_name").set_index("center_name")
        alpha, beta = out.loc["Alpha"], out.loc["Beta"]
        assert alpha["work_orders"] == 2 and beta["work_orders"] == 2
        assert alpha["revenue"] == 1600 and beta["revenue"] == 600
        assert alpha["profit"] == 600 and beta["profit"] == 300
        assert alpha["margin_pct"] == pytest.approx(600 / 1600)
        assert alpha["avg_service_cost"] == pytest.approx(500)  # (600 + 400) / 2
        assert alpha["parts_share"] == pytest.approx(700 / 1000)
        assert alpha["on_time_pct"] == 0.5
        assert beta["avg_rating"] == 4.0  # NaN rating skipped
        assert beta["csat_pct"] == 1.0
        assert beta["rated_orders"] == 1
        assert alpha["repeat_visit_rate"] == 1.0  # CU1 appears twice
        assert beta["repeat_visit_rate"] == 0.0
        assert alpha["comeback_rate"] == 0.5

    def test_by_multiple_columns(self, fact):
        out = kpis.group_kpis(fact, ["center_name", "region"])
        assert set(out.columns) >= {"center_name", "region", "revenue"}
        assert len(out) == 2

    def test_missing_group_keys_are_dropped(self):
        df = make_fact([{"technician_id": "T1"}, {"technician_id": None}])
        assert len(kpis.group_kpis(df, "technician_id")) == 1

    def test_zero_revenue_group_has_nan_margin(self):
        df = make_fact([{"revenue": 0.0, "labor_cost": 5.0}])
        out = kpis.group_kpis(df, "center_name")
        assert np.isnan(out.loc[0, "margin_pct"])

    def test_empty_frame(self, fact):
        out = kpis.group_kpis(fact.iloc[0:0], "center_name")
        assert out.empty and "revenue" in out.columns and "repeat_visit_rate" in out.columns

    def test_monthly_trend_sorted_with_mom(self, fact):
        out = kpis.monthly_trend(fact.sample(frac=1, random_state=1))
        assert list(out["month"]) == ["2025-01", "2025-02", "2025-03"]
        assert out.loc[0, "revenue"] == 1000
        assert np.isnan(out.loc[0, "revenue_mom_pct"])
        assert out.loc[1, "revenue"] == 1000  # 600 + 400
        assert out.loc[1, "revenue_mom_pct"] == pytest.approx(0.0)
        assert out.loc[2, "revenue_mom_pct"] == pytest.approx(-0.8)
        assert out.loc[2, "profit_mom_pct"] == pytest.approx(
            (out.loc[2, "profit"] - out.loc[1, "profit"]) / out.loc[1, "profit"]
        )

    def test_monthly_trend_empty(self, fact):
        assert kpis.monthly_trend(fact.iloc[0:0]).empty

    def test_service_type_performance_sorted_by_revenue(self, fact):
        out = kpis.service_type_performance(fact)
        assert list(out["service_type"]) == ["Periodic Service", "Brake Service"]
        periodic = out.iloc[0]
        assert periodic["avg_est_hours"] == pytest.approx(2.0)
        assert periodic["avg_actual_hours"] == pytest.approx(2.25)
        assert periodic["cost_overrun_rate"] == 0.5
        assert periodic["avg_cost_variance_pct"] == 0.0


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #
class TestAppointments:
    def test_rates_by_centre(self, appts):
        out = kpis.appointment_rates_by(appts, "center_name").set_index("center_name")
        assert out.loc["Alpha", "appointments"] == 3
        assert out.loc["Alpha", "cancellation_rate"] == pytest.approx(1 / 3)
        assert out.loc["Alpha", "no_show_rate"] == pytest.approx(1 / 3)
        assert out.loc["Beta", "cancellation_rate"] == 1.0

    def test_rates_empty(self, appts):
        assert kpis.appointment_rates_by(appts.iloc[0:0], "center_name").empty

    def test_cancellation_by_respects_order(self, appts):
        order = ["Same day", "1-3 days", "4-7 days", "8-14 days"]
        out = kpis.cancellation_by(appts, "lead_time_band", order)
        assert list(out["lead_time_band"]) == ["Same day", "1-3 days", "4-7 days"]
        assert out.loc[2, "cancellation_rate"] == 1.0

    def test_cancellation_by_without_order(self, appts):
        out = kpis.cancellation_by(appts, "center_name")
        assert len(out) == 2

    def test_cancellation_reasons(self, appts):
        out = kpis.cancellation_reasons(appts)
        assert set(out["cancellation_reason"]) == {"Price Concern", "Personal Reasons"}
        assert out["share"].sum() == pytest.approx(1.0)
        assert out["cancellations"].sum() == 2

    def test_cancellation_reasons_empty(self, appts):
        out = kpis.cancellation_reasons(appts.iloc[0:0])
        assert out.empty and list(out.columns) == ["cancellation_reason", "cancellations", "share"]


# --------------------------------------------------------------------------- #
# Centre / technician scorecards
# --------------------------------------------------------------------------- #
class TestScorecards:
    def test_centre_scorecard_columns_and_rank(self, fact, appts, tech):
        card = kpis.centre_scorecard(fact, appts, tech)
        assert set(card["center_name"]) == {"Alpha", "Beta"}
        assert {"cancellation_rate", "utilisation", "performance_score", "rank"} <= set(card.columns)
        assert sorted(card["rank"]) == [1.0, 2.0]
        alpha = card.set_index("center_name").loc["Alpha"]
        assert alpha["utilisation"] == pytest.approx(200 / 320)
        assert alpha["appointments"] == 3

    def test_centre_scorecard_best_centre_ranks_first(self):
        fact = make_fact(
            [
                {"center_name": "Good", "on_time_flag": True, "rating": 5.0, "revenue": 900.0,
                 "turnaround_hours": 2.0},
                {"center_name": "Bad", "on_time_flag": False, "rating": 2.0, "revenue": 300.0,
                 "turnaround_hours": 20.0, "late_hours": 5.0},
            ]
        )
        appts = make_appts([{"center_name": "Good"}, {"center_name": "Bad", "is_cancelled": True}])
        tech = make_tech([{"center_name": "Good"}, {"center_name": "Bad"}])
        card = kpis.centre_scorecard(fact, appts, tech)
        assert list(card["center_name"]) == ["Good", "Bad"]
        assert card.loc[0, "performance_score"] > card.loc[1, "performance_score"]

    def test_centre_scorecard_empty(self, fact, appts, tech):
        card = kpis.centre_scorecard(fact.iloc[0:0], appts.iloc[0:0], tech.iloc[0:0])
        assert card.empty

    def test_utilisation_by(self, tech):
        out = kpis.utilisation_by(tech, "center_name").set_index("center_name")
        assert out.loc["Alpha", "utilisation"] == pytest.approx(200 / 320)
        assert out.loc["Beta", "jobs"] == 5

    def test_utilisation_by_zero_available_hours(self):
        out = kpis.utilisation_by(make_tech([{"available_hours": 0.0}]), "center_name")
        assert np.isnan(out.loc[0, "utilisation"])

    def test_technician_scorecard(self, fact, tech):
        card = kpis.technician_scorecard(fact, tech).set_index("technician_id")
        assert card.loc["T1", "utilisation"] == pytest.approx(200 / 320)
        assert card.loc["T1", "jobs"] == 20
        assert card.loc["T1", "work_orders"] == 2
        assert card.loc["T1", "on_time_pct"] == 0.5
        assert card.loc["T2", "comebacks_caused"] == 2
        assert card.loc["T2", "skill_level"] == "Junior"
        assert card.index[0] == "T1"  # sorted by utilisation desc

    def test_technician_scorecard_technician_without_orders(self, fact, tech):
        only_t1 = fact.loc[fact["technician_id"] == "T1"]
        card = kpis.technician_scorecard(only_t1, tech).set_index("technician_id")
        assert np.isnan(card.loc["T2", "on_time_pct"])

    def test_technician_scorecard_empty(self, fact, tech):
        card = kpis.technician_scorecard(fact.iloc[0:0], tech.iloc[0:0])
        assert card.empty

    def test_utilisation_matrix(self, tech):
        m = kpis.technician_utilisation_matrix(tech)
        assert m.loc["T1", "2025-01"] == pytest.approx(0.5)
        assert m.loc["T1", "2025-02"] == pytest.approx(0.75)
        assert np.isnan(m.loc["T2", "2025-02"])

    def test_utilisation_matrix_empty(self, tech):
        assert kpis.technician_utilisation_matrix(tech.iloc[0:0]).empty


# --------------------------------------------------------------------------- #
# Distributions
# --------------------------------------------------------------------------- #
class TestDistributions:
    def test_delay_distribution_bands(self):
        df = make_fact([{"late_hours": v} for v in (0, 0, 0.5, 1.0, 3.0, 30.0)])
        out = kpis.delay_distribution(df)
        counts = dict(zip(out["band"], out["work_orders"]))
        assert counts["On time"] == 2
        assert counts["0-1h"] == 2  # 0.5 and 1.0 (right-closed)
        assert counts["2-4h"] == 1
        assert counts["> 24h"] == 1
        assert out["share"].sum() == pytest.approx(1.0)
        assert list(out["band"])[0] == "On time"

    def test_turnaround_bands_without_zero_label(self):
        df = make_fact([{"turnaround_hours": v} for v in (1.0, 3.0, 100.0)])
        out = kpis.delay_distribution(df, "turnaround_hours", kpis.TURNAROUND_EDGES, None)
        assert out["band"].iloc[0] == "<= 2h"
        assert out["work_orders"].sum() == 3
        assert out["work_orders"].iloc[-1] == 1

    def test_delay_distribution_ignores_nan_and_handles_empty(self):
        df = make_fact([{"late_hours": np.nan}])
        out = kpis.delay_distribution(df)
        assert out["work_orders"].sum() == 0
        assert out["share"].isna().all()
        assert len(out) == len(kpis.LATE_HOURS_EDGES) + 1

    def test_wait_by_weekday_ordered(self):
        df = make_fact(
            [
                {"service_date": "2025-01-06", "wait_hours": 1.0},  # Monday
                {"service_date": "2025-01-13", "wait_hours": 3.0},  # Monday
                {"service_date": "2025-01-11", "wait_hours": 5.0},  # Saturday
            ]
        )
        out = kpis.wait_by_weekday(df)
        assert list(out["weekday"]) == ["Monday", "Saturday"]
        assert out.loc[0, "avg_wait"] == pytest.approx(2.0)
        assert out.loc[0, "work_orders"] == 2

    def test_wait_by_weekday_empty(self, fact):
        assert kpis.wait_by_weekday(fact.iloc[0:0]).empty


# --------------------------------------------------------------------------- #
# Customer and parts views
# --------------------------------------------------------------------------- #
class TestCustomerAndParts:
    def test_rating_matrix(self, fact):
        m = kpis.rating_matrix(fact, "service_type", "center_name")
        assert m.loc["Periodic Service", "Alpha"] == pytest.approx(4.0)
        assert m.loc["Brake Service", "Beta"] == pytest.approx(4.0)
        assert np.isnan(m.loc["Periodic Service", "Beta"])

    def test_feedback_distribution(self, fact):
        out = kpis.feedback_distribution(fact)
        assert out["responses"].sum() == 3  # NaN category excluded
        assert out["share"].sum() == pytest.approx(1.0)
        assert out.loc[0, "responses"] == 1

    def test_feedback_distribution_empty(self, fact):
        assert kpis.feedback_distribution(fact.iloc[0:0]).empty

    def test_parts_cost_by_category(self, fact):
        usage = pd.DataFrame(
            {
                "work_order_id": ["WO1", "WO1", "WO2", "WO99"],
                "part_id": ["P1", "P2", "P1", "P2"],
                "quantity": [2, 1, 1, 5],
            }
        )
        parts = pd.DataFrame(
            {
                "part_id": ["P1", "P2"],
                "part_category": ["Brakes", "Tyres"],
                "unit_cost": [100.0, 500.0],
            }
        )
        out = kpis.parts_cost_by_category(usage, parts, fact)
        costs = dict(zip(out["part_category"], out["parts_cost"]))
        assert costs == {"Brakes": 300.0, "Tyres": 500.0}  # WO99 not in filtered fact
        assert out.loc[0, "part_category"] == "Tyres"
        assert out["share"].sum() == pytest.approx(1.0)

    def test_parts_cost_by_category_empty(self, fact):
        usage = pd.DataFrame({"work_order_id": ["WO1"], "part_id": ["P1"], "quantity": [1]})
        parts = pd.DataFrame({"part_id": ["P1"], "part_category": ["B"], "unit_cost": [1.0]})
        assert kpis.parts_cost_by_category(usage, parts, fact.iloc[0:0]).empty
