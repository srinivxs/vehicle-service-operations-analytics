"""Evidence metrics behind the findings, root-cause and recommendation documents.

Every number quoted in ``docs/findings.md``, ``docs/root_cause_analysis.md``,
``docs/process_map.md`` and ``docs/recommendations.md`` is produced by a pure
function in this module, computed from ``data/cleaned``. Re-running the module
regenerates ``reports/analysis_metrics.json`` so the documents can be verified.

KPI definitions follow the canonical project definitions (see
``docs/business_requirements.md``):

* Revenue = SUM(revenue); Total Cost = SUM(labor_cost + parts_cost)
* Profit = Revenue - Cost; Margin = Profit / Revenue
* On-Time % = mean(on_time_flag); Avg Turnaround = mean(turnaround_hours)
* Cost overrun rate = mean(cost_variance_pct > 10%)
* Cancellation Rate = Cancelled / all appointments
* Utilisation = SUM(service_hours) / SUM(available_hours)
* CSAT = mean(rating); CSAT% = share of ratings >= 4
* Repeat Visit Rate = customers with >= 2 work orders / customers with >= 1
* Comeback rate = mean(caused_repeat_visit)

Relationships reported here are associations. They are framed as hypotheses for
operational follow-up, never as proof of causation.

Usage:
    python -m src.analysis_metrics            # print summary + write JSON
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from src.config import CLEAN_DIR, PRODUCTIVE_HOURS_PER_DAY, REPORTS_DIR

FOCUS_YEAR = 2026  # most recent (partial) year: Jan-Sep
YOY_MONTHS = range(1, 10)  # Jan-Sep comparable window
LOAD_BANDS = [0, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, np.inf]
LEAD_ORDER = ["Same day", "1-3 days", "4-7 days", "8-14 days", "15+ days"]
WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
COMPLEX_TYPES = ("Motor & Controller Repair", "Charging System Repair",
                 "Electrical Diagnostics", "Accident & Body Repair")
SKILL_ORDER = ["Junior", "Mid", "Senior", "Master"]
METRICS_JSON = REPORTS_DIR / "analysis_metrics.json"


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def inr(x: float) -> str:
    """Format rupees in Indian units (crore >= 1e7, lakh >= 1e5)."""
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:,.2f} crore"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:,.2f} lakh"
    return f"₹{x:,.0f}"


def pct(x: float, nd: int = 1) -> str:
    return f"{x * 100:.{nd}f}%"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_cleaned(clean_dir: Path = CLEAN_DIR) -> dict[str, pd.DataFrame]:
    """Load the cleaned analytical tables needed for the analysis."""
    dt_cols = ["check_in_time", "start_time", "end_time", "promised_ready_time"]
    fs = pd.read_csv(clean_dir / "fact_service.csv", parse_dates=dt_cols)
    fs["service_date"] = pd.to_datetime(fs["service_date"])
    fs["weekday"] = fs["service_date"].dt.day_name()
    fs["month_num"] = fs["service_date"].dt.month
    fa = pd.read_csv(clean_dir / "fact_appointments.csv", parse_dates=["booking_date", "scheduled_date"])
    fa["month_num"] = fa["scheduled_date"].dt.month
    fa["year"] = fa["scheduled_date"].dt.year
    return {
        "fact_service": fs,
        "fact_appointments": fa,
        "fact_technician_month": pd.read_csv(clean_dir / "fact_technician_month.csv"),
        "technicians": pd.read_csv(clean_dir / "technicians.csv"),
        "service_centers": pd.read_csv(clean_dir / "service_centers.csv"),
        "parts": pd.read_csv(clean_dir / "parts.csv"),
        "part_usage": pd.read_csv(clean_dir / "part_usage.csv"),
        "feedback": pd.read_csv(clean_dir / "feedback.csv", parse_dates=["feedback_date"]),
    }


# --------------------------------------------------------------------------- #
# Core KPI functions
# --------------------------------------------------------------------------- #
def headline_kpis(fs: pd.DataFrame, fa: pd.DataFrame, ftm: pd.DataFrame) -> dict[str, float]:
    """Network-level KPIs using the canonical definitions."""
    revenue = fs["revenue"].sum()
    cost = fs["total_cost"].sum()
    visits = fs.groupby("customer_id").size()
    return {
        "work_orders": int(len(fs)),
        "appointments": int(len(fa)),
        "revenue": float(revenue),
        "total_cost": float(cost),
        "labor_cost": float(fs["labor_cost"].sum()),
        "parts_cost": float(fs["parts_cost"].sum()),
        "profit": float(revenue - cost),
        "margin": float((revenue - cost) / revenue),
        "avg_service_cost": float(cost / len(fs)),
        "avg_revenue_per_job": float(revenue / len(fs)),
        "on_time_rate": float(fs["on_time_flag"].mean()),
        "avg_turnaround_h": float(fs["turnaround_hours"].mean()),
        "median_turnaround_h": float(fs["turnaround_hours"].median()),
        "avg_wait_h": float(fs["wait_hours"].mean()),
        "cost_variance_total": float(fs["cost_variance"].sum()),
        "cost_overrun_rate": float(fs["cost_overrun_flag"].mean()),
        "cancellation_rate": float(fa["is_cancelled"].mean()),
        "no_show_rate": float(fa["is_no_show"].mean()),
        "utilisation": float(ftm["service_hours"].sum() / ftm["available_hours"].sum()),
        "csat": float(fs["rating"].mean()),
        "csat_pct": float((fs["rating"].dropna() >= 4).mean()),
        "rating_responses": int(fs["rating"].notna().sum()),
        "repeat_visit_rate": float((visits >= 2).mean()),
        "comeback_rate": float(fs["caused_repeat_visit"].mean()),
        "duration_variance_h": float(fs["duration_variance_hours"].mean()),
        "parts_delay_rate": float(fs["parts_delay_flag"].mean()),
        "qc_first_pass": float(fs["qc_passed_first_time"].mean()),
    }


def service_scorecard(fs: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """Operational + financial + experience KPIs for any grouping of work orders."""
    g = fs.groupby(by)
    out = g.agg(
        jobs=("work_order_id", "size"),
        revenue=("revenue", "sum"),
        total_cost=("total_cost", "sum"),
        profit=("profit", "sum"),
        on_time=("on_time_flag", "mean"),
        tat_mean_h=("turnaround_hours", "mean"),
        tat_median_h=("turnaround_hours", "median"),
        wait_h=("wait_hours", "mean"),
        late_h=("late_hours", "mean"),
        parts_delay=("parts_delay_flag", "mean"),
        qc_first_pass=("qc_passed_first_time", "mean"),
        comeback=("caused_repeat_visit", "mean"),
        overrun=("cost_overrun_flag", "mean"),
        duration_var_h=("duration_variance_hours", "mean"),
        csat=("rating", "mean"),
    )
    out["margin"] = out["profit"] / out["revenue"]
    out["avg_service_cost"] = out["total_cost"] / out["jobs"]
    out["csat_pct"] = g["rating"].apply(lambda s: (s.dropna() >= 4).mean())
    return out


def utilisation(ftm: pd.DataFrame, by: str | list[str]) -> pd.Series:
    """SUM(service_hours) / SUM(available_hours) for a grouping of technician-months."""
    g = ftm.groupby(by)[["service_hours", "available_hours"]].sum()
    return g["service_hours"] / g["available_hours"]


def cancellation_by(fa: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    g = fa.groupby(by)
    return g.agg(appointments=("appointment_id", "size"), cancellation_rate=("is_cancelled", "mean"),
                 no_show_rate=("is_no_show", "mean"), mean_lead_days=("lead_days", "mean"))


def centre_scorecard(fs: pd.DataFrame, fa: pd.DataFrame, ftm: pd.DataFrame,
                     technicians: pd.DataFrame) -> pd.DataFrame:
    """One row per centre combining service, booking, capacity and staffing KPIs."""
    sc = service_scorecard(fs, ["center_id", "center_name"]).reset_index().set_index("center_id")
    canc = cancellation_by(fa, "center_id")
    sc = sc.join(canc)
    sc["utilisation"] = utilisation(ftm, "center_id")
    sc["utilisation_2026"] = utilisation(ftm[ftm["month"].str.startswith(str(FOCUS_YEAR))], "center_id")
    sc["technicians"] = technicians.groupby("center_id").size()
    sc["senior_or_master_techs"] = (technicians[technicians["skill_level"].isin(["Senior", "Master"])]
                                    .groupby("center_id").size()).reindex(sc.index).fillna(0).astype(int)
    sc["junior_job_share"] = fs.assign(j=fs["skill_level"].eq("Junior")).groupby("center_id")["j"].mean()
    # service mix and workload per technician (comparative investigation vs benchmark centres)
    mix = fs.assign(cx=fs["service_type"].isin(COMPLEX_TYPES), per=fs["service_type"].eq("Periodic Service"),
                    fleet=fs["customer_type"].eq("Fleet"))
    sc["complex_job_share"] = mix.groupby("center_id")["cx"].mean()
    sc["periodic_share"] = mix.groupby("center_id")["per"].mean()
    sc["fleet_job_share"] = mix.groupby("center_id")["fleet"].mean()
    sc["complex_on_time"] = mix[mix["cx"]].groupby("center_id")["on_time_flag"].mean()
    f26 = fs[fs["year"] == FOCUS_YEAR]
    sc["jobs_per_tech_month_2026"] = f26.groupby("center_id").size() / f26["month"].nunique() / sc["technicians"]
    return sc


def monthly_trend(fs: pd.DataFrame, fa: pd.DataFrame, ftm: pd.DataFrame) -> pd.DataFrame:
    m = service_scorecard(fs, "month")
    m = m.join(cancellation_by(fa, "month")[["appointments", "cancellation_rate"]])
    m["utilisation"] = utilisation(ftm, "month")
    return m


def yoy_jan_sep(fs: pd.DataFrame, fa: pd.DataFrame, ftm: pd.DataFrame) -> pd.DataFrame:
    """Like-for-like Jan-Sep 2025 vs Jan-Sep 2026 comparison."""
    f = fs[fs["month_num"].isin(YOY_MONTHS)]
    a = fa[fa["month_num"].isin(YOY_MONTHS)]
    t = ftm[ftm["month"].str[5:7].astype(int).isin(YOY_MONTHS)].assign(year=lambda d: d["month"].str[:4].astype(int))
    y = service_scorecard(f, "year")
    y = y.join(cancellation_by(a, "year")[["appointments", "cancellation_rate"]])
    y["utilisation"] = utilisation(t, "year")
    y = y.T
    y["change"] = y[2026] - y[2025]
    y["pct_change"] = y["change"] / y[2025]
    return y


# --------------------------------------------------------------------------- #
# Workload / capacity
# --------------------------------------------------------------------------- #
def daily_load(fs: pd.DataFrame, technicians: pd.DataFrame) -> pd.DataFrame:
    """Centre-day booked workload as a share of rostered productive capacity.

    load_ratio = SUM(estimated_hours of jobs checked in that day)
                 / (rostered technicians x productive hours per day)
    """
    n_tech = technicians.groupby("center_id").size()
    d = (fs.groupby(["center_id", "center_name", "service_date", "weekday"])
         .agg(jobs=("work_order_id", "size"), booked_hours=("estimated_hours", "sum"),
              wait_h=("wait_hours", "mean"), on_time=("on_time_flag", "mean"))
         .reset_index())
    d["capacity_hours"] = d["center_id"].map(n_tech) * PRODUCTIVE_HOURS_PER_DAY
    d["load_ratio"] = d["booked_hours"] / d["capacity_hours"]
    d["overloaded"] = d["load_ratio"] > 1.0
    return d


def attach_load(fs: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    out = fs.merge(daily[["center_id", "service_date", "load_ratio"]], on=["center_id", "service_date"], how="left")
    out["load_band"] = pd.cut(out["load_ratio"], LOAD_BANDS, right=True)
    return out


def load_band_profile(fs_load: pd.DataFrame) -> pd.DataFrame:
    """On-time, wait, QC and CSAT by centre-day load band (job-weighted)."""
    g = fs_load.groupby("load_band", observed=True)
    return g.agg(jobs=("work_order_id", "size"), on_time=("on_time_flag", "mean"), wait_h=("wait_hours", "mean"),
                 qc_first_pass=("qc_passed_first_time", "mean"), comeback=("caused_repeat_visit", "mean"),
                 csat=("rating", "mean"))


def weekday_profile(fs: pd.DataFrame, fa: pd.DataFrame) -> pd.DataFrame:
    w = service_scorecard(fs, "weekday")[["jobs", "on_time", "wait_h", "csat"]]
    w = w.join(cancellation_by(fa, "weekday")[["appointments", "cancellation_rate"]])
    w["job_share"] = w["jobs"] / w["jobs"].sum()
    return w.reindex(WEEKDAY_ORDER)


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #
def overnight_carry_over(fs: pd.DataFrame) -> dict[str, Any]:
    """Share of jobs *without* a parts delay that finish on a later calendar day than check-in.

    These jobs are not waiting for parts, so carrying over is a capacity/queue signal.
    """
    nd = fs[~fs["parts_delay_flag"]].copy()
    nd["carry_over"] = nd["end_time"].dt.normalize() > nd["check_in_time"].dt.normalize()
    return {
        "network_share": float(nd["carry_over"].mean()),
        "on_time_if_carried_over": float(nd.loc[nd["carry_over"], "on_time_flag"].mean()),
        "on_time_if_same_day": float(nd.loc[~nd["carry_over"], "on_time_flag"].mean()),
        "by_centre": nd.groupby("center_id")["carry_over"].mean().round(4).to_dict(),
        "by_weekday": nd.groupby("weekday")["carry_over"].mean().round(4).to_dict(),
    }


def process_stage_metrics(fs: pd.DataFrame, fa: pd.DataFrame, feedback: pd.DataFrame) -> dict[str, float]:
    """Measured durations / rates for each workflow stage where the data supports it."""
    booked = fa[fa["booking_channel"] != "Walk-in"]
    slot = pd.to_datetime(fa["scheduled_date"].dt.strftime("%Y-%m-%d") + " " + fa["scheduled_slot"])
    ci = fs[["appointment_id", "check_in_time"]].merge(
        fa[["appointment_id", "booking_channel"]].assign(slot=slot), on="appointment_id")
    ci = ci[ci["booking_channel"] != "Walk-in"]
    arrival_min = (ci["check_in_time"] - ci["slot"]).dt.total_seconds() / 60
    fb = feedback.merge(fs[["work_order_id", "end_time"]], on="work_order_id")
    lag = (fb["feedback_date"] - fb["end_time"].dt.normalize()).dt.days
    delayed = fs[fs["parts_delay_flag"]]
    late = fs[~fs["on_time_flag"]]
    return {
        "booking_lead_days_mean_booked": float(booked["lead_days"].mean()),
        "booking_lead_days_median_booked": float(booked["lead_days"].median()),
        "walk_in_share": float((fa["booking_channel"] == "Walk-in").mean()),
        "cancellation_rate": float(fa["is_cancelled"].mean()),
        "no_show_rate": float(fa["is_no_show"].mean()),
        "arrival_vs_slot_median_min": float(arrival_min.median()),
        "arrival_vs_slot_p90_min": float(arrival_min.quantile(0.9)),
        "wait_mean_h": float(fs["wait_hours"].mean()),
        "wait_median_h": float(fs["wait_hours"].median()),
        "wait_p90_h": float(fs["wait_hours"].quantile(0.9)),
        "wait_over_1_5h_share": float((fs["wait_hours"] > 1.5).mean()),
        "additional_work_found_rate": float(fs["additional_work_found"].mean()),
        "estimated_hours_mean": float(fs["estimated_hours"].mean()),
        "actual_hours_mean": float(fs["actual_hours"].mean()),
        "actual_hours_median": float(fs["actual_hours"].median()),
        "duration_variance_mean_h": float(fs["duration_variance_hours"].mean()),
        "labour_over_estimate_share": float((fs["duration_variance_hours"] > 0).mean()),
        "parts_delay_rate": float(fs["parts_delay_flag"].mean()),
        "parts_wait_mean_h_delayed": float(delayed["parts_wait_hours"].mean()),
        "parts_wait_median_h_delayed": float(delayed["parts_wait_hours"].median()),
        "qc_first_pass": float(fs["qc_passed_first_time"].mean()),
        "on_time_rate": float(fs["on_time_flag"].mean()),
        "late_hours_median_when_late": float(late["late_hours"].median()),
        "late_hours_mean_when_late": float(late["late_hours"].mean()),
        "turnaround_median_h": float(fs["turnaround_hours"].median()),
        "turnaround_mean_h": float(fs["turnaround_hours"].mean()),
        "feedback_response_rate": float(fs["rating"].notna().mean()),
        "feedback_lag_days_mean": float(lag.mean()),
        "csat": float(fs["rating"].mean()),
        "comeback_rate": float(fs["caused_repeat_visit"].mean()),
        "rework_billing_share": float((fs["billing_type"] == "Rework (No Charge)").mean()),
    }


def parts_lines(fs: pd.DataFrame, part_usage: pd.DataFrame, parts: pd.DataFrame) -> pd.DataFrame:
    cols = ["work_order_id", "center_id", "center_name", "service_date", "year", "parts_delay_flag", "parts_wait_hours"]
    return (part_usage.merge(parts, on="part_id")
            .merge(fs[cols], on="work_order_id")
            .assign(line_cost=lambda d: d["quantity"] * d["unit_cost"]))


def parts_delay_by_category(lines: pd.DataFrame) -> pd.DataFrame:
    """Share of jobs that needed a part of each category and suffered a parts delay.

    The data records parts delay at work-order level, not which part was short,
    so this is the delay rate of jobs *containing* each category (an association).
    """
    wc = lines.drop_duplicates(["work_order_id", "part_category"])
    return (wc.groupby("part_category").agg(jobs=("work_order_id", "size"), delay_rate=("parts_delay_flag", "mean"),
                                            supplier_lead_days=("supplier_lead_days", "mean"))
            .sort_values("delay_rate", ascending=False))


def parts_delay_category_centre(lines: pd.DataFrame) -> pd.DataFrame:
    wc = lines.drop_duplicates(["work_order_id", "part_category"])
    return wc.pivot_table(index="part_category", columns="center_name", values="parts_delay_flag", aggfunc="mean")


def parts_delay_impact(fs: pd.DataFrame) -> pd.DataFrame:
    g = fs.groupby("parts_delay_flag")
    return g.agg(jobs=("work_order_id", "size"), on_time=("on_time_flag", "mean"),
                 tat_mean_h=("turnaround_hours", "mean"), tat_median_h=("turnaround_hours", "median"),
                 parts_wait_mean_h=("parts_wait_hours", "mean"), csat=("rating", "mean"),
                 csat_pct=("rating", lambda s: (s.dropna() >= 4).mean()))


def abc_parts(lines: pd.DataFrame) -> pd.DataFrame:
    """ABC classification of parts by consumption value (A = top 80%, B = next 15%, C = last 5%)."""
    p = (lines.groupby(["part_id", "part_name", "part_category", "unit_cost", "supplier_lead_days"])
         .agg(units=("quantity", "sum"), value=("line_cost", "sum"), jobs=("work_order_id", "nunique"),
              delay_rate=("parts_delay_flag", "mean"))
         .reset_index().sort_values("value", ascending=False))
    p["value_share"] = p["value"] / p["value"].sum()
    p["cum_share"] = p["value_share"].cumsum()
    p["abc_class"] = np.where(p["cum_share"] - p["value_share"] < 0.80, "A",
                              np.where(p["cum_share"] - p["value_share"] < 0.95, "B", "C"))
    return p.reset_index(drop=True)


def safety_stock_estimate(lines: pd.DataFrame, center_id: str, min_delay_rate: float = 0.10,
                          months: int = 9, year: int = FOCUS_YEAR) -> pd.DataFrame:
    """Working capital to hold one supplier lead time of demand for high-stock-out parts at a centre.

    Assumption (stated in recommendations): cover = average monthly usage x
    supplier_lead_days / 30, rounded up to at least one unit, for every part
    whose jobs at that centre had a parts-delay rate >= ``min_delay_rate``.
    """
    c = lines[(lines["center_id"] == center_id) & (lines["year"] == year)]
    p = (c.groupby(["part_id", "part_name", "part_category", "unit_cost", "supplier_lead_days"])
         .agg(units=("quantity", "sum"), delay_rate=("parts_delay_flag", "mean"), jobs=("work_order_id", "nunique"))
         .reset_index())
    p = p[p["delay_rate"] >= min_delay_rate].copy()
    p["monthly_units"] = p["units"] / months
    p["cover_units"] = np.maximum(1, np.ceil(p["monthly_units"] * p["supplier_lead_days"] / 30)).astype(int)
    p["stock_value"] = p["cover_units"] * p["unit_cost"]
    return p.sort_values("stock_value", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# People / skill
# --------------------------------------------------------------------------- #
def skill_profile(fs: pd.DataFrame) -> pd.DataFrame:
    s = service_scorecard(fs.dropna(subset=["skill_level"]), "skill_level")
    s["complex_share"] = fs.assign(c=fs["service_type"].isin(COMPLEX_TYPES)).groupby("skill_level")["c"].mean()
    return s.reindex(SKILL_ORDER)


def skill_profile_complex(fs: pd.DataFrame) -> pd.DataFrame:
    """Skill comparison restricted to complex jobs (controls for job mix)."""
    c = fs[fs["service_type"].isin(COMPLEX_TYPES)].dropna(subset=["skill_level"])
    return service_scorecard(c, "skill_level").reindex(SKILL_ORDER)


def technician_scorecard(fs: pd.DataFrame, ftm: pd.DataFrame) -> pd.DataFrame:
    t = service_scorecard(fs.dropna(subset=["technician_id"]), ["technician_id", "center_name", "skill_level"])
    t = t.reset_index().set_index("technician_id")
    t["utilisation"] = utilisation(ftm, "technician_id")
    t["utilisation_2026"] = utilisation(ftm[ftm["month"].str.startswith(str(FOCUS_YEAR))], "technician_id")
    return t


def rework_cost(fs: pd.DataFrame) -> dict[str, float]:
    rw = fs[fs["billing_type"] == "Rework (No Charge)"]
    return {"rework_jobs": int(len(rw)), "rework_cost": float(rw["total_cost"].sum()),
            "rework_avg_cost": float(rw["total_cost"].mean()), "rework_labour_hours": float(rw["actual_hours"].sum()),
            "rework_share_of_jobs": float(len(rw) / len(fs))}


def overrun_drivers(fs: pd.DataFrame) -> pd.DataFrame:
    g = fs.groupby("additional_work_found")
    out = g.agg(jobs=("work_order_id", "size"), overrun=("cost_overrun_flag", "mean"),
                cost_var_pct_median=("cost_variance_pct", "median"), margin_profit=("profit", "sum"),
                revenue=("revenue", "sum"), csat=("rating", "mean"))
    out["margin"] = out["margin_profit"] / out["revenue"]
    out["share_of_jobs"] = out["jobs"] / out["jobs"].sum()
    return out.drop(columns="margin_profit")


# --------------------------------------------------------------------------- #
# Statistical tests (with effect sizes)
# --------------------------------------------------------------------------- #
def _cramers_v(table: pd.DataFrame) -> tuple[float, float, int, float]:
    chi2, p, dof, _ = stats.chi2_contingency(table)
    n = table.to_numpy().sum()
    k = min(table.shape) - 1
    return float(chi2), float(p), int(dof), float(math.sqrt(chi2 / (n * k)))


def statistical_tests(fs: pd.DataFrame, fa: pd.DataFrame, daily: pd.DataFrame,
                      focus_centre: str = "C006", benchmark_centre: str = "C005") -> dict[str, dict[str, Any]]:
    """Non-parametric tests with effect sizes. Associations only - not causal evidence."""
    out: dict[str, dict[str, Any]] = {}
    tat = fs.dropna(subset=["turnaround_hours"])

    groups = [g["turnaround_hours"].to_numpy() for _, g in tat.groupby("center_id")]
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    out["kruskal_turnaround_by_centre"] = {"H": float(h), "p": float(p), "epsilon_sq": float(h / (n - 1)), "n": int(n)}

    w = fs.dropna(subset=["wait_hours"])
    groups = [g["wait_hours"].to_numpy() for _, g in w.groupby("center_id")]
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    out["kruskal_wait_by_centre"] = {"H": float(h), "p": float(p), "epsilon_sq": float(h / (n - 1)), "n": int(n)}

    a = w.loc[w["center_id"] == focus_centre, "wait_hours"]
    b = w.loc[w["center_id"] != focus_centre, "wait_hours"]
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    out["mannwhitney_wait_focus_vs_rest"] = {
        "centre": focus_centre, "U": float(u), "p": float(p),
        "rank_biserial": float(2 * u / (len(a) * len(b)) - 1),
        "median_focus_h": float(a.median()), "median_rest_h": float(b.median())}

    ct = pd.crosstab(fs["center_id"], fs["on_time_flag"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_on_time_by_centre"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}

    ct = pd.crosstab(fs["parts_delay_flag"], fs["on_time_flag"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_on_time_vs_parts_delay"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}

    # Two-proportion comparison of on-time: focus vs benchmark centre, with 95% CI on the gap.
    x1 = fs.loc[fs["center_id"] == focus_centre, "on_time_flag"]
    x2 = fs.loc[fs["center_id"] == benchmark_centre, "on_time_flag"]
    p1, p2 = x1.mean(), x2.mean()
    se = math.sqrt(p1 * (1 - p1) / len(x1) + p2 * (1 - p2) / len(x2))
    h_cohen = 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))
    out["on_time_gap_focus_vs_benchmark"] = {
        "focus": focus_centre, "benchmark": benchmark_centre, "focus_rate": float(p1), "benchmark_rate": float(p2),
        "gap": float(p1 - p2), "ci95_low": float(p1 - p2 - 1.96 * se), "ci95_high": float(p1 - p2 + 1.96 * se),
        "cohens_h": float(h_cohen)}

    r = fs.dropna(subset=["rating", "late_hours"])
    rho, p = stats.spearmanr(r["late_hours"], r["rating"])
    out["spearman_rating_vs_late_hours"] = {"rho": float(rho), "p": float(p), "n": int(len(r))}
    rho, p = stats.spearmanr(r["wait_hours"].fillna(0), r["rating"])
    out["spearman_rating_vs_wait_hours"] = {"rho": float(rho), "p": float(p), "n": int(len(r))}

    rho, p = stats.spearmanr(daily["load_ratio"], daily["wait_h"], nan_policy="omit")
    out["spearman_daily_load_vs_wait"] = {"rho": float(rho), "p": float(p), "n": int(len(daily))}
    rho, p = stats.spearmanr(daily["load_ratio"], daily["on_time"], nan_policy="omit")
    out["spearman_daily_load_vs_on_time"] = {"rho": float(rho), "p": float(p), "n": int(len(daily))}

    ct = pd.crosstab(fa["lead_time_band"], fa["is_cancelled"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_cancellation_vs_lead_band"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}
    booked = fa[fa["booking_channel"] != "Walk-in"]
    rho, p = stats.spearmanr(booked["lead_days"], booked["is_cancelled"].astype(int))
    out["spearman_lead_days_vs_cancel_booked"] = {"rho": float(rho), "p": float(p), "n": int(len(booked))}

    sk = fs.dropna(subset=["skill_level"])
    ct = pd.crosstab(sk["skill_level"], sk["qc_passed_first_time"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_qc_vs_skill"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}
    ct = pd.crosstab(sk["skill_level"], sk["cost_overrun_flag"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_overrun_vs_skill"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}

    ct = pd.crosstab(fs["weekday"].eq("Saturday"), fs["on_time_flag"])
    chi2, p, dof, v = _cramers_v(ct)
    out["chi2_on_time_saturday_vs_weekday"] = {"chi2": chi2, "p": p, "dof": dof, "cramers_v": v}
    return out


# --------------------------------------------------------------------------- #
# What-if capacity model
# --------------------------------------------------------------------------- #
def on_time_curve(fs_load: pd.DataFrame) -> pd.Series:
    """Network on-time rate by daily load band - the response curve used by the what-if model."""
    return fs_load.groupby("load_band", observed=False)["on_time_flag"].mean()


def _curve_lookup(curve: pd.Series, load: pd.Series) -> pd.Series:
    bands = pd.cut(load, LOAD_BANDS, right=True)
    return bands.map(curve).astype(float)


def what_if_add_technician(fs_load: pd.DataFrame, ftm: pd.DataFrame, technicians: pd.DataFrame,
                           center_id: str, extra_techs: int = 1, year: int = FOCUS_YEAR) -> dict[str, float]:
    """Project utilisation and on-time if ``extra_techs`` are added at a centre.

    Model (deliberately simple, stated as an assumption):
      * demand = the centre's observed jobs in ``year`` (no growth, no recovered cancellations);
      * every day's load ratio is scaled by n / (n + extra_techs);
      * on-time changes by the *difference* in the network on-time-by-load curve
        between old and new load (a delta method), so the centre keeps its own
        residual performance gap (e.g. skill mix, parts) - a conservative choice.
    """
    curve = on_time_curve(fs_load)
    n = int((technicians["center_id"] == center_id).sum())
    c = fs_load[(fs_load["center_id"] == center_id) & (fs_load["year"] == year)]
    months = c["month"].nunique()
    new_load = c["load_ratio"] * n / (n + extra_techs)
    delta = (_curve_lookup(curve, new_load) - _curve_lookup(curve, c["load_ratio"])).mean()
    t = ftm[(ftm["center_id"] == center_id) & ftm["month"].str.startswith(str(year))]
    util_now = t["service_hours"].sum() / t["available_hours"].sum()
    on_time_now = c["on_time_flag"].mean()
    jobs_pm = len(c) / months
    return {
        "center_id": center_id, "technicians_now": n, "technicians_new": n + extra_techs,
        "jobs_per_month": float(jobs_pm),
        "utilisation_now": float(util_now), "utilisation_projected": float(util_now * n / (n + extra_techs)),
        "overloaded_day_share_now": float((c.drop_duplicates("service_date")["load_ratio"] > 1).mean()),
        "overloaded_day_share_projected": float((c.drop_duplicates("service_date")["load_ratio"] * n / (n + extra_techs) > 1).mean()),
        "on_time_now": float(on_time_now), "on_time_projected": float(min(1.0, on_time_now + delta)),
        "on_time_delta_pts": float(delta),
        "extra_on_time_jobs_per_month": float(delta * jobs_pm),
    }


def what_if_saturday_shift(fs_load: pd.DataFrame, fs: pd.DataFrame, shift_share: float = 0.15,
                           year: int = FOCUS_YEAR) -> dict[str, float]:
    """Project the effect of moving ``shift_share`` of *booked* (non walk-in) Saturday
    workload to the following Tuesday-Thursday of the same centre (spread evenly).

    Uses the same delta-on-curve method as :func:`what_if_add_technician`.
    """
    curve = on_time_curve(fs_load)
    f = fs_load[fs_load["year"] == year].copy()
    day = (f.groupby(["center_id", "service_date", "weekday"])
           .agg(load=("load_ratio", "first"),
                booked_hours=("estimated_hours", lambda s: s[f.loc[s.index, "booking_channel"] != "Walk-in"].sum()),
                all_hours=("estimated_hours", "sum"))
           .reset_index())
    day["cap"] = day["all_hours"] / day["load"]
    day["new_load"] = day["load"]
    sat = day["weekday"] == "Saturday"
    moved = day.loc[sat, "booked_hours"] * shift_share
    day.loc[sat, "new_load"] = (day.loc[sat, "all_hours"] - moved) / day.loc[sat, "cap"]
    # receiving days: Tue/Wed/Thu of the following week, same centre
    recv = []
    for (cid, d), mv in zip(day.loc[sat, ["center_id", "service_date"]].itertuples(index=False), moved):
        for k in (3, 4, 5):
            recv.append((cid, d + pd.Timedelta(days=k), mv / 3))
    recv_df = pd.DataFrame(recv, columns=["center_id", "service_date", "add_h"]).groupby(
        ["center_id", "service_date"])["add_h"].sum()
    day = day.set_index(["center_id", "service_date"])
    add = recv_df.reindex(day.index).fillna(0.0)
    day["new_load"] = day["new_load"] + add / day["cap"]
    day = day.reset_index()
    f = f.merge(day[["center_id", "service_date", "new_load"]], on=["center_id", "service_date"])
    f["delta"] = _curve_lookup(curve, f["new_load"]) - _curve_lookup(curve, f["load_ratio"])
    months = f["month"].nunique()
    is_sat = f["weekday"] == "Saturday"
    return {
        "shift_share_of_booked_saturday_hours": shift_share,
        "saturday_on_time_now": float(f.loc[is_sat, "on_time_flag"].mean()),
        "saturday_on_time_projected": float(f.loc[is_sat, "on_time_flag"].mean() + f.loc[is_sat, "delta"].mean()),
        "tue_thu_on_time_now": float(f.loc[f["weekday"].isin(["Tuesday", "Wednesday", "Thursday"]), "on_time_flag"].mean()),
        "tue_thu_on_time_projected": float(
            (f.loc[f["weekday"].isin(["Tuesday", "Wednesday", "Thursday"]), "on_time_flag"]
             + f.loc[f["weekday"].isin(["Tuesday", "Wednesday", "Thursday"]), "delta"]).mean()),
        "network_on_time_now": float(f["on_time_flag"].mean()),
        "network_on_time_projected": float(f["on_time_flag"].mean() + f["delta"].mean()),
        "extra_on_time_jobs_per_month": float(f["delta"].sum() / months),
        "booked_share_of_saturday_hours": float(day.loc[day["weekday"] == "Saturday", "booked_hours"].sum()
                                                / day.loc[day["weekday"] == "Saturday", "all_hours"].sum()),
    }


def what_if_saturday_capacity(fs_load: pd.DataFrame, centres: list[str], extra_hours_per_tech: float = 2.0,
                              year: int = FOCUS_YEAR) -> dict[str, float]:
    """Project Saturday on-time if each technician at ``centres`` works ``extra_hours_per_tech``
    additional productive hours on Saturdays (extended shift / overtime). Same delta-on-curve method."""
    curve = on_time_curve(fs_load)
    f = fs_load[(fs_load["year"] == year) & (fs_load["weekday"] == "Saturday") & fs_load["center_id"].isin(centres)].copy()
    scale = PRODUCTIVE_HOURS_PER_DAY / (PRODUCTIVE_HOURS_PER_DAY + extra_hours_per_tech)
    f["delta"] = _curve_lookup(curve, f["load_ratio"] * scale) - _curve_lookup(curve, f["load_ratio"])
    months = fs_load.loc[fs_load["year"] == year, "month"].nunique()
    saturdays_pm = f.drop_duplicates("service_date")["service_date"].nunique() / months
    return {
        "centres": ",".join(centres), "extra_hours_per_tech": extra_hours_per_tech,
        "saturday_jobs_per_month": float(len(f) / months),
        "saturday_on_time_now": float(f["on_time_flag"].mean()),
        "saturday_on_time_projected": float(f["on_time_flag"].mean() + f["delta"].mean()),
        "extra_on_time_jobs_per_month": float(f["delta"].sum() / months),
        "saturday_wait_now_h": float(f["wait_hours"].mean()),
        "saturdays_per_month": float(saturdays_pm),
    }


# --------------------------------------------------------------------------- #
# Recommendation impact estimates (conservative, assumption-driven)
# --------------------------------------------------------------------------- #
def technician_monthly_cost(technicians: pd.DataFrame, ftm: pd.DataFrame, skill: str = "Mid") -> float:
    """Payroll cost of one technician: hourly_cost x shift hours x mean working days per month."""
    t = technicians[technicians["skill_level"] == skill].iloc[0]
    wd = ftm.drop_duplicates("month")["working_days"].mean()
    return float(t["hourly_cost"] * t["shift_hours_per_day"] * wd)


def impact_estimates(d: dict[str, pd.DataFrame], fs_load: pd.DataFrame, lines: pd.DataFrame) -> dict[str, Any]:
    fs, fa, ftm, techs = d["fact_service"], d["fact_appointments"], d["fact_technician_month"], d["technicians"]
    out: dict[str, Any] = {}
    f26 = fs[fs["year"] == FOCUS_YEAR]
    a26 = fa[fa["year"] == FOCUS_YEAR]
    months26 = f26["month"].nunique()

    # R1 capacity at Mumbai (C006) and Chennai (C003)
    out["what_if_C006_plus1"] = what_if_add_technician(fs_load, ftm, techs, "C006")
    out["what_if_C003_plus1"] = what_if_add_technician(fs_load, ftm, techs, "C003")
    out["what_if_C007_plus1"] = what_if_add_technician(fs_load, ftm, techs, "C007")
    out["technician_monthly_cost_mid"] = technician_monthly_cost(techs, ftm, "Mid")
    out["technician_monthly_cost_senior"] = technician_monthly_cost(techs, ftm, "Senior")

    # Recovered bookings if Mumbai cancellation rate fell to the median of the other centres (2026)
    canc = a26.groupby("center_id")["is_cancelled"].mean()
    others_median = canc.drop("C006").median()
    m_appts_pm = (a26["center_id"] == "C006").sum() / months26
    m_rev_job = f26.loc[f26["center_id"] == "C006", "revenue"].mean()
    m_profit_job = f26.loc[f26["center_id"] == "C006", "profit"].mean()
    m_completion = a26.loc[a26["center_id"] == "C006", "is_completed"].mean()
    recovered = (canc["C006"] - others_median) * m_appts_pm * m_completion
    out["mumbai_cancellation_recovery"] = {
        "mumbai_cancel_rate_2026": float(canc["C006"]), "other_centres_median_2026": float(others_median),
        "appointments_per_month": float(m_appts_pm), "completion_rate": float(m_completion),
        "recovered_jobs_per_month": float(recovered), "revenue_per_job": float(m_rev_job),
        "profit_per_job": float(m_profit_job),
        "recovered_revenue_per_month": float(recovered * m_rev_job),
        "recovered_profit_per_month": float(recovered * m_profit_job)}

    m26 = f26[f26["center_id"] == "C006"]
    m25 = fs[(fs["center_id"] == "C006") & (fs["year"] == FOCUS_YEAR - 1) & fs["month_num"].isin(YOY_MONTHS)]
    out["mumbai_context"] = {
        "profit_per_month_2026": float(m26["profit"].sum() / months26),
        "revenue_per_month_2026": float(m26["revenue"].sum() / months26),
        "jobs_jan_sep_2025": int(len(m25)), "jobs_jan_sep_2026": int(len(m26)),
        "jobs_yoy_growth": float(len(m26) / len(m25) - 1),
        "hire_cost_share_of_profit": float(technician_monthly_cost(techs, ftm, "Senior") / (m26["profit"].sum() / months26)),
    }

    # R2 Saturday levelling and Saturday capacity at the four most loaded centres
    out["what_if_saturday_shift_15pct"] = what_if_saturday_shift(fs_load, fs, 0.15)
    hot = ["C001", "C003", "C006", "C007"]
    sat = what_if_saturday_capacity(fs_load, hot, 2.0)
    hot_techs = techs[techs["center_id"].isin(hot)]
    # Assumption: overtime paid at 2x the technician's hourly cost.
    sat["overtime_cost_per_month_at_2x"] = float(hot_techs["hourly_cost"].sum() * 2.0 * 2 * sat["saturdays_per_month"])
    out["what_if_saturday_overtime_hot_centres"] = sat

    # R3 Kolkata parts: delay rate to median of other centres
    pdr = f26.groupby("center_id")["parts_delay_flag"].mean()
    k = f26[f26["center_id"] == "C008"]
    k_jobs_pm = len(k) / months26
    target = pdr.drop("C008").median()
    avoided = (pdr["C008"] - target) * k_jobs_pm
    non_delayed_on_time = k.loc[~k["parts_delay_flag"], "on_time_flag"].mean()
    tat_gap = (k.loc[k["parts_delay_flag"], "turnaround_hours"].mean()
               - k.loc[~k["parts_delay_flag"], "turnaround_hours"].mean())
    ss = safety_stock_estimate(lines, "C008")
    out["kolkata_parts"] = {
        "parts_delay_rate_2026": float(pdr["C008"]), "other_centres_median_2026": float(target),
        "jobs_per_month": float(k_jobs_pm), "avoided_delayed_jobs_per_month": float(avoided),
        "extra_on_time_jobs_per_month": float(avoided * non_delayed_on_time),
        "turnaround_hours_saved_per_month": float(avoided * tat_gap),
        "tat_gap_delayed_vs_not_h": float(tat_gap),
        "parts_delay_complex_jobs_all_period": float(fs.loc[(fs["center_id"] == "C008") & fs["service_type"].isin(COMPLEX_TYPES), "parts_delay_flag"].mean()),
        "parts_delay_other_jobs_all_period": float(fs.loc[(fs["center_id"] == "C008") & ~fs["service_type"].isin(COMPLEX_TYPES), "parts_delay_flag"].mean()),
        "safety_stock_parts": int(len(ss)), "safety_stock_value": float(ss["stock_value"].sum()),
        "safety_stock_carrying_cost_pa_at_20pct": float(ss["stock_value"].sum() * 0.20)}

    # R4 skill: junior comeback / QC at Mid level
    sk = f26.dropna(subset=["skill_level"]).groupby("skill_level").agg(
        jobs=("work_order_id", "size"), cb=("caused_repeat_visit", "mean"), qc=("qc_passed_first_time", "mean"),
        overrun=("cost_overrun_flag", "mean"), dvar=("duration_variance_hours", "mean"))
    rw = rework_cost(f26)
    j_pm = sk.loc["Junior", "jobs"] / months26
    avoided_cb = (sk.loc["Junior", "cb"] - sk.loc["Mid", "cb"]) * j_pm
    avoided_qc = (sk.loc["Mid", "qc"] - sk.loc["Junior", "qc"]) * j_pm
    hours_saved = (sk.loc["Junior", "dvar"] - sk.loc["Mid", "dvar"]) * j_pm
    out["skill_uplift"] = {
        "junior_jobs_per_month": float(j_pm), "junior_comeback": float(sk.loc["Junior", "cb"]),
        "mid_comeback": float(sk.loc["Mid", "cb"]), "junior_qc": float(sk.loc["Junior", "qc"]),
        "mid_qc": float(sk.loc["Mid", "qc"]),
        "avoided_comebacks_per_month": float(avoided_cb), "avoided_qc_failures_per_month": float(avoided_qc),
        "rework_avg_cost": rw["rework_avg_cost"],
        "rework_cost_avoided_per_month": float(avoided_cb * rw["rework_avg_cost"]),
        "labour_hours_saved_per_month": float(hours_saved),
        "junior_duration_var_h": float(sk.loc["Junior", "dvar"]), "mid_duration_var_h": float(sk.loc["Mid", "dvar"])}

    # R5 booking window: cancellation of 8+ day bookings brought to 4-7 day rate
    lb = cancellation_by(a26, "lead_time_band")
    long_mask = a26["lead_time_band"].isin(["8-14 days", "15+ days"])
    long_pm = long_mask.sum() / months26
    long_rate = a26.loc[long_mask, "is_cancelled"].mean()
    target = lb.loc["4-7 days", "cancellation_rate"]
    rec = (long_rate - target) * long_pm * a26["is_completed"].mean()
    out["booking_window"] = {
        "long_lead_appointments_per_month": float(long_pm), "long_lead_cancel_rate": float(long_rate),
        "target_rate_4_7_days": float(target), "recovered_jobs_per_month": float(rec),
        "recovered_revenue_per_month": float(rec * f26["revenue"].mean()),
        "recovered_profit_per_month": float(rec * f26["profit"].mean()),
        "mumbai_long_lead_share": float(a26.loc[a26["center_id"] == "C006", "lead_time_band"]
                                        .isin(["8-14 days", "15+ days"]).mean()),
        "network_long_lead_share": float(long_mask.mean())}

    # R6 estimate / approval discipline
    od = overrun_drivers(f26)
    out["estimate_approval"] = {
        "additional_work_share": float(od.loc[True, "share_of_jobs"]),
        "overrun_rate_with_additional_work": float(od.loc[True, "overrun"]),
        "overrun_rate_without": float(od.loc[False, "overrun"]),
        "csat_with_additional_work": float(od.loc[True, "csat"]),
        "csat_without": float(od.loc[False, "csat"])}
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.reset_index().to_json(orient="records", default_handler=str))


def compute_all(d: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    """Compute every metric cited in the docs. Returns a JSON-serialisable dict."""
    d = d if d is not None else load_cleaned()
    fs, fa, ftm, techs = d["fact_service"], d["fact_appointments"], d["fact_technician_month"], d["technicians"]
    daily = daily_load(fs, techs)
    fs_load = attach_load(fs, daily)
    lines = parts_lines(fs, d["part_usage"], d["parts"])
    centre = centre_scorecard(fs, fa, ftm, techs)
    abc = abc_parts(lines)
    overload_share = daily.groupby("center_id")["overloaded"].mean()
    overload_share_26 = daily[daily["service_date"].dt.year == FOCUS_YEAR].groupby("center_id")["overloaded"].mean()
    centre["overloaded_day_share"] = overload_share
    centre["overloaded_day_share_2026"] = overload_share_26
    lb = load_band_profile(fs_load)
    lb.index = lb.index.astype(str)
    return {
        "headline": headline_kpis(fs, fa, ftm),
        "yoy_jan_sep": json.loads(yoy_jan_sep(fs, fa, ftm).to_json(orient="index")),
        "centre_scorecard": _df_records(centre),
        "monthly_trend": _df_records(monthly_trend(fs, fa, ftm)),
        "service_type_scorecard": _df_records(service_scorecard(fs, "service_type")),
        "model_scorecard": _df_records(service_scorecard(fs, "model")),
        "skill_profile": _df_records(skill_profile(fs)),
        "skill_profile_complex_jobs": _df_records(skill_profile_complex(fs)),
        "technician_scorecard": _df_records(technician_scorecard(fs, ftm)),
        "load_band_profile": _df_records(lb),
        "weekday_profile": _df_records(weekday_profile(fs, fa)),
        "parts_delay_impact": _df_records(parts_delay_impact(fs)),
        "parts_delay_by_category": _df_records(parts_delay_by_category(lines)),
        "parts_delay_category_centre": _df_records(parts_delay_category_centre(lines)),
        "abc_summary": _df_records(abc.groupby("abc_class").agg(parts=("part_id", "size"), value_share=("value_share", "sum"),
                                                               mean_delay_rate=("delay_rate", "mean"))),
        "abc_a_class_parts": _df_records(abc[abc["abc_class"] == "A"][["part_id", "part_name", "part_category", "value_share", "delay_rate", "supplier_lead_days"]].set_index("part_id")),
        "cancellation_by_lead_band": _df_records(cancellation_by(fa, "lead_time_band").reindex(LEAD_ORDER)),
        "cancellation_by_channel": _df_records(cancellation_by(fa, "booking_channel")),
        "cancellation_by_service_type": _df_records(cancellation_by(fa, "requested_service_type")),
        "cancellation_reasons_by_centre": _df_records(pd.crosstab(fa.loc[fa["is_cancelled"], "center_id"],
                                                                  fa.loc[fa["is_cancelled"], "cancellation_reason"])),
        "lead_band_mix_by_centre": _df_records(pd.crosstab(fa["center_id"], fa["lead_time_band"], normalize="index")[LEAD_ORDER]),
        "rework": rework_cost(fs),
        "overnight_carry_over": overnight_carry_over(fs),
        "process_stage_metrics": process_stage_metrics(fs, fa, d["feedback"]),
        "overrun_drivers": _df_records(overrun_drivers(fs)),
        "feedback_categories": fs["feedback_category"].value_counts().to_dict(),
        "statistical_tests": statistical_tests(fs, fa, daily),
        "impact": impact_estimates(d, fs_load, lines),
    }


def _print_summary(m: dict[str, Any]) -> None:
    h = m["headline"]
    print("=" * 78)
    print("NETWORK HEADLINE KPIs (Jan 2025 - Sep 2026)")
    print("=" * 78)
    print(f"Work orders {h['work_orders']:,} | Appointments {h['appointments']:,}")
    print(f"Revenue {inr(h['revenue'])} | Cost {inr(h['total_cost'])} | Profit {inr(h['profit'])} | Margin {pct(h['margin'])}")
    print(f"On-time {pct(h['on_time_rate'])} | Turnaround mean {h['avg_turnaround_h']:.1f} h / median {h['median_turnaround_h']:.2f} h"
          f" | Wait {h['avg_wait_h']:.2f} h")
    print(f"Utilisation {pct(h['utilisation'])} | Cancellation {pct(h['cancellation_rate'])} | CSAT {h['csat']:.2f} ({pct(h['csat_pct'])} >=4)")
    print(f"Overrun rate {pct(h['cost_overrun_rate'])} | Parts delay {pct(h['parts_delay_rate'])} | QC first-pass {pct(h['qc_first_pass'])}"
          f" | Comeback {pct(h['comeback_rate'])} | Repeat-visit {pct(h['repeat_visit_rate'])}")

    print("\nCENTRE SCORECARD")
    cols = ["center_name", "jobs", "on_time", "wait_h", "tat_mean_h", "parts_delay", "utilisation", "utilisation_2026",
            "overloaded_day_share_2026", "cancellation_rate", "mean_lead_days", "qc_first_pass", "comeback", "overrun", "csat", "margin"]
    c = pd.DataFrame(m["centre_scorecard"]).set_index("center_id")[cols]
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.3f}".format):
        print(c)

    y = m["yoy_jan_sep"]
    print("\nYoY Jan-Sep 2025 vs 2026")
    for k in ("jobs", "revenue", "profit", "on_time", "wait_h", "utilisation", "csat", "cancellation_rate"):
        print(f"  {k:<18} {y[k]['2025']:>14,.3f} -> {y[k]['2026']:>14,.3f}  ({y[k]['pct_change'] * 100:+.1f}%)")

    print("\nSTATISTICAL TESTS (associations, not causal)")
    for name, t in m["statistical_tests"].items():
        print(f"  {name}: " + ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in t.items()))

    print("\nIMPACT ESTIMATES")
    for name, t in m["impact"].items():
        if isinstance(t, dict):
            print(f"  {name}: " + ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in t.items()))
        else:
            print(f"  {name}: {t:,.0f}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ₹ on Windows consoles
    metrics = compute_all()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_JSON.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    _print_summary(metrics)
    print(f"\nWrote {METRICS_JSON.relative_to(REPORTS_DIR.parent)}")


if __name__ == "__main__":
    main()
