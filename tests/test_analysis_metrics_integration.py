"""Integration tests: src/analysis_metrics.py on the real ``data/cleaned`` extract.

Checks that the evidence module agrees with the canonical KPI definitions (computed
independently from the raw CSV columns and via ``src.kpis``), that cross-table
invariants hold, and that ``main()`` writes its JSON to a temporary path (the real
``reports/`` folder is never touched).
"""
from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from src import analysis_metrics as am
from src import kpis
from src.config import CLEAN_DIR

pytestmark = pytest.mark.integration

REQUIRED = ["fact_service", "fact_appointments", "fact_technician_month", "technicians", "service_centers",
            "parts", "part_usage", "feedback"]

if not all((CLEAN_DIR / f"{name}.csv").exists() for name in REQUIRED):  # pragma: no cover
    pytest.skip("data/cleaned is not populated", allow_module_level=True)


@pytest.fixture(scope="module")
def data():
    return am.load_cleaned()


@pytest.fixture(scope="module")
def metrics(data):
    return am.compute_all(data)


@pytest.fixture(scope="module")
def head(metrics):
    return metrics["headline"]


# --------------------------------------------------------------------------- #
# Agreement with canonical KPI definitions
# --------------------------------------------------------------------------- #
class TestHeadlineAgreesWithCanonicalKpis:
    def test_on_time_is_mean_of_flag(self, head, data):
        assert head["on_time_rate"] == pytest.approx(data["fact_service"]["on_time_flag"].mean())

    def test_revenue_cost_profit(self, head, data):
        fs = data["fact_service"]
        assert head["revenue"] == pytest.approx(fs["revenue"].sum())
        assert head["total_cost"] == pytest.approx((fs["labor_cost"] + fs["parts_cost"]).sum())
        assert head["profit"] == pytest.approx(head["revenue"] - head["total_cost"])
        assert head["margin"] == pytest.approx(head["profit"] / head["revenue"])
        assert head["labor_cost"] + head["parts_cost"] == pytest.approx(head["total_cost"])

    def test_cancellation_and_no_show_from_appointments(self, head, data):
        fa = data["fact_appointments"]
        assert head["cancellation_rate"] == pytest.approx((fa["status"] == "Cancelled").mean())
        assert head["no_show_rate"] == pytest.approx((fa["status"] == "No-Show").mean())
        assert head["appointments"] == len(fa)

    def test_utilisation_is_ratio_of_sums(self, head, data):
        t = data["fact_technician_month"]
        assert head["utilisation"] == pytest.approx(t["service_hours"].sum() / t["available_hours"].sum())

    def test_csat(self, head, data):
        r = data["fact_service"]["rating"].dropna()
        assert head["csat"] == pytest.approx(r.mean())
        assert head["csat_pct"] == pytest.approx((r >= 4).mean())
        assert head["rating_responses"] == len(r)

    def test_repeat_visit_and_comeback(self, head, data):
        fs = data["fact_service"]
        counts = fs["customer_id"].value_counts()
        assert head["repeat_visit_rate"] == pytest.approx((counts >= 2).sum() / len(counts))
        assert head["comeback_rate"] == pytest.approx(fs["caused_repeat_visit"].mean())

    def test_matches_independent_kpi_module(self, head, data):
        ref = kpis.headline_kpis(data["fact_service"], data["fact_appointments"], data["fact_technician_month"])
        pairs = {
            "work_orders": "work_orders", "revenue": "revenue", "total_cost": "total_cost", "profit": "profit",
            "margin": "margin_pct", "on_time_rate": "on_time_pct", "avg_turnaround_h": "avg_turnaround",
            "median_turnaround_h": "median_turnaround", "cost_overrun_rate": "cost_overrun_rate",
            "csat": "avg_rating", "csat_pct": "csat_pct", "repeat_visit_rate": "repeat_visit_rate",
            "comeback_rate": "comeback_rate", "parts_delay_rate": "parts_delay_rate",
            "qc_first_pass": "qc_first_pass_rate", "avg_wait_h": "avg_wait", "utilisation": "utilisation",
            "cancellation_rate": "cancellation_rate", "no_show_rate": "no_show_rate",
            "appointments": "appointments", "avg_service_cost": "avg_service_cost",
            "duration_variance_h": "avg_duration_variance",
        }
        for mine, theirs in pairs.items():
            assert head[mine] == pytest.approx(ref[theirs]), mine

    def test_all_rates_are_proper_fractions(self, head):
        for key in ("on_time_rate", "cost_overrun_rate", "cancellation_rate", "no_show_rate", "csat_pct",
                    "repeat_visit_rate", "comeback_rate", "parts_delay_rate", "qc_first_pass", "utilisation"):
            assert 0.0 <= head[key] <= 1.5, key  # utilisation can exceed 1 only mildly
        assert 1.0 <= head["csat"] <= 5.0
        assert 0 < head["margin"] < 1


# --------------------------------------------------------------------------- #
# Cross-table invariants
# --------------------------------------------------------------------------- #
class TestInvariants:
    def test_centre_scorecard_reconciles_to_network(self, metrics, head):
        c = pd.DataFrame(metrics["centre_scorecard"])
        assert len(c) == 8
        assert c["jobs"].sum() == head["work_orders"]
        assert c["revenue"].sum() == pytest.approx(head["revenue"])
        assert c["appointments"].sum() == head["appointments"]
        assert c["technicians"].sum() == 18
        assert c["overloaded_day_share"].between(0, 1).all()
        assert c["on_time"].between(0, 1).all()

    def test_monthly_trend_reconciles_and_is_sorted(self, metrics, head):
        m = pd.DataFrame(metrics["monthly_trend"])
        assert len(m) == 21
        assert m["month"].is_monotonic_increasing
        assert m["jobs"].sum() == head["work_orders"]
        assert m["appointments"].sum() == head["appointments"]

    def test_group_scorecards_sum_to_network(self, metrics, head):
        for key in ("service_type_scorecard", "model_scorecard"):
            df = pd.DataFrame(metrics[key])
            assert df["jobs"].sum() == head["work_orders"], key
            assert df["revenue"].sum() == pytest.approx(head["revenue"]), key

    def test_yoy_is_like_for_like_jan_sep(self, metrics, data):
        fs = data["fact_service"]
        y = metrics["yoy_jan_sep"]
        jan_sep = fs[fs["service_date"].dt.month <= 9]
        for year in (2025, 2026):
            assert y["jobs"][str(year)] == (jan_sep["service_date"].dt.year == year).sum()
        assert y["jobs"]["change"] == pytest.approx(y["jobs"]["2026"] - y["jobs"]["2025"])
        assert y["revenue"]["pct_change"] == pytest.approx(y["revenue"]["2026"] / y["revenue"]["2025"] - 1)

    def test_daily_load_conserves_hours_and_jobs(self, data):
        fs = data["fact_service"]
        daily = am.daily_load(fs, data["technicians"])
        assert daily["jobs"].sum() == len(fs)
        assert daily["booked_hours"].sum() == pytest.approx(fs["estimated_hours"].sum())
        assert daily["load_ratio"].notna().all()
        assert (daily["capacity_hours"] > 0).all()
        fl = am.attach_load(fs, daily)
        assert len(fl) == len(fs)

    def test_load_bands_show_on_time_deteriorating_with_load(self, metrics):
        lb = pd.DataFrame(metrics["load_band_profile"])
        low = lb.iloc[0]["on_time"]
        high = lb.iloc[-1]["on_time"]
        assert low > high

    def test_parts_tables(self, data, metrics):
        lines = am.parts_lines(data["fact_service"], data["part_usage"], data["parts"])
        assert len(lines) == len(data["part_usage"])  # every usage row resolves to a part and a work order
        abc = am.abc_parts(lines)
        assert abc["value_share"].sum() == pytest.approx(1.0)
        assert set(abc["abc_class"]) <= {"A", "B", "C"}
        assert abc["abc_class"].iloc[0] == "A" and abc["abc_class"].iloc[-1] == "C"
        assert abc["value"].is_monotonic_decreasing
        assert pd.DataFrame(metrics["abc_summary"])["value_share"].sum() == pytest.approx(1.0)

    def test_parts_delayed_jobs_are_never_on_time(self, data):
        impact = am.parts_delay_impact(data["fact_service"])
        assert impact.loc[True, "on_time"] < impact.loc[False, "on_time"]
        assert impact.loc[True, "tat_mean_h"] > impact.loc[False, "tat_mean_h"]

    def test_cancellation_by_lead_band_covers_all_bands_in_order(self, metrics, head):
        lb = pd.DataFrame(metrics["cancellation_by_lead_band"])
        assert lb["lead_time_band"].tolist() == am.LEAD_ORDER
        assert lb["appointments"].sum() == head["appointments"]

    def test_weekday_profile_has_six_days_summing_to_one(self, metrics):
        w = pd.DataFrame(metrics["weekday_profile"])
        assert w["weekday"].tolist() == am.WEEKDAY_ORDER
        assert w["job_share"].sum() == pytest.approx(1.0)

    def test_skill_profile_has_all_levels(self, metrics):
        assert [r["skill_level"] for r in metrics["skill_profile"]] == am.SKILL_ORDER

    def test_rework_counts_match_billing_type(self, metrics, data):
        fs = data["fact_service"]
        assert metrics["rework"]["rework_jobs"] == (fs["billing_type"] == "Rework (No Charge)").sum()

    def test_feedback_categories_total_equals_rated_jobs(self, metrics, head):
        # feedback_category is only populated for jobs that received a rating
        assert sum(metrics["feedback_categories"].values()) == head["rating_responses"]

    def test_process_stage_metrics_agree_with_headline(self, metrics, head):
        p = metrics["process_stage_metrics"]
        assert p["on_time_rate"] == pytest.approx(head["on_time_rate"])
        assert p["cancellation_rate"] == pytest.approx(head["cancellation_rate"])
        assert p["csat"] == pytest.approx(head["csat"])
        assert 0 <= p["walk_in_share"] <= 1
        assert p["wait_p90_h"] >= p["wait_median_h"]

    def test_statistical_tests_are_valid(self, metrics):
        for name, t in metrics["statistical_tests"].items():
            if "p" in t:
                assert 0.0 <= t["p"] <= 1.0, name
            if "cramers_v" in t:
                assert 0.0 <= t["cramers_v"] <= 1.0, name
            if "rho" in t:
                assert -1.0 <= t["rho"] <= 1.0, name
        gap = metrics["statistical_tests"]["on_time_gap_focus_vs_benchmark"]
        assert gap["ci95_low"] < gap["gap"] < gap["ci95_high"]
        assert gap["gap"] == pytest.approx(gap["focus_rate"] - gap["benchmark_rate"])
        mw = metrics["statistical_tests"]["mannwhitney_wait_focus_vs_rest"]
        assert -1.0 <= mw["rank_biserial"] <= 1.0

    def test_impact_estimates_are_sensible(self, metrics):
        imp = metrics["impact"]
        for key in ("what_if_C006_plus1", "what_if_C003_plus1", "what_if_C007_plus1"):
            w = imp[key]
            assert w["technicians_new"] == w["technicians_now"] + 1
            assert w["utilisation_projected"] < w["utilisation_now"]
            assert w["on_time_now"] <= w["on_time_projected"] <= 1.0
            assert w["overloaded_day_share_projected"] <= w["overloaded_day_share_now"]
        assert imp["technician_monthly_cost_senior"] > imp["technician_monthly_cost_mid"] > 0
        assert imp["kolkata_parts"]["safety_stock_value"] > 0
        s = imp["what_if_saturday_shift_15pct"]
        assert s["saturday_on_time_projected"] >= s["saturday_on_time_now"]
        for section in imp.values():
            if isinstance(section, dict):
                for k, v in section.items():
                    if isinstance(v, float):
                        assert not math.isnan(v), k


class TestTechnicianHourlyCostAssumption:
    def test_hourly_cost_is_uniform_within_skill_level(self, data):
        """``technician_monthly_cost`` takes the first technician of a skill level as representative."""
        t = data["technicians"]
        assert (t.groupby("skill_level")["hourly_cost"].nunique() == 1).all()


# --------------------------------------------------------------------------- #
# Docs agreement and main()
# --------------------------------------------------------------------------- #
class TestDocsAndOutput:
    def test_headline_numbers_are_quoted_in_findings(self, head):
        findings = CLEAN_DIR.parents[1] / "docs" / "findings.md"
        if not findings.exists():
            pytest.skip("docs/findings.md not present")
        text = findings.read_text(encoding="utf-8")
        assert am.inr(head["revenue"]) in text
        assert am.inr(head["profit"]) in text
        assert am.pct(head["on_time_rate"]) in text
        assert am.pct(head["margin"]) in text

    def test_main_writes_json_to_patched_path_only(self, monkeypatch, tmp_path, metrics, capsys):
        reports = tmp_path / "out" / "reports"
        target = reports / "analysis_metrics.json"
        monkeypatch.setattr(am, "REPORTS_DIR", reports)
        monkeypatch.setattr(am, "METRICS_JSON", target)
        monkeypatch.setattr(am, "compute_all", lambda d=None: metrics)  # already computed above; avoids a re-run
        am.main()
        out = capsys.readouterr().out
        assert target.exists()
        written = json.loads(target.read_text(encoding="utf-8"))
        assert set(written) == set(metrics)
        assert written["headline"]["work_orders"] == metrics["headline"]["work_orders"]
        assert "NETWORK HEADLINE KPIs" in out and "Wrote reports" in out

    @pytest.mark.slow
    def test_main_end_to_end_recomputes_from_disk(self, monkeypatch, tmp_path, head):
        reports = tmp_path / "reports"
        monkeypatch.setattr(am, "REPORTS_DIR", reports)
        monkeypatch.setattr(am, "METRICS_JSON", reports / "analysis_metrics.json")
        am.main()
        written = json.loads((reports / "analysis_metrics.json").read_text(encoding="utf-8"))
        assert written["headline"]["revenue"] == pytest.approx(head["revenue"])
        assert written["headline"]["on_time_rate"] == pytest.approx(head["on_time_rate"])
