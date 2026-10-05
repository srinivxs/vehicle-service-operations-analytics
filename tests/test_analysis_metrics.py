"""Unit tests for src/analysis_metrics.py.

Two styles of input are used:

* tiny hand-built frames with answers worked out by hand (exact assertions);
* one deterministic synthetic dataset (``make_dataset``) that has the full
  schema of ``data/cleaned`` so the orchestration (``compute_all``,
  ``impact_estimates``, ``statistical_tests`` ...) can run end to end quickly.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from src import analysis_metrics as am

pytestmark = pytest.mark.unit

RUPEE = "₹"


# --------------------------------------------------------------------------- #
# Tiny-frame builders
# --------------------------------------------------------------------------- #
def fs_frame(*rows: dict) -> pd.DataFrame:
    """Work-order frame with sensible defaults; each dict overrides some columns."""
    out = []
    for i, kw in enumerate(rows or ({},), start=1):
        kw = dict(kw)
        sd = pd.Timestamp(kw.get("service_date", "2026-01-05"))  # a Monday
        labor = kw.get("labor_cost", 100.0)
        parts = kw.get("parts_cost", 100.0)
        revenue = kw.get("revenue", 300.0)
        row = dict(
            work_order_id=f"WO{i:03d}", appointment_id=f"AP{i:03d}", technician_id="T1",
            service_type="Periodic Service",
            check_in_time=sd + pd.Timedelta(hours=9), start_time=sd + pd.Timedelta(hours=9.5),
            end_time=sd + pd.Timedelta(hours=11), promised_ready_time=sd + pd.Timedelta(hours=12),
            estimated_hours=2.0, actual_hours=2.0, parts_wait_hours=0.0, additional_work_found=False,
            qc_passed_first_time=True, center_id="C001", center_name="Alpha", booking_channel="Ather App",
            customer_id=f"CU{i}", customer_type="Individual", skill_level="Mid", billing_type="Customer Paid",
            labor_cost=labor, parts_cost=parts, revenue=revenue, rating=4.0,
            feedback_category="Positive Experience", service_date=sd, year=sd.year,
            month=sd.strftime("%Y-%m"), weekday=sd.day_name(), month_num=sd.month,
            wait_hours=0.5, turnaround_hours=2.0, late_hours=0.0, on_time_flag=True,
            duration_variance_hours=0.0, parts_delay_flag=False, total_cost=labor + parts,
            profit=revenue - labor - parts, cost_variance=0.0, cost_variance_pct=0.0,
            cost_overrun_flag=False, caused_repeat_visit=False, model="Ather 450X",
        )
        row.update(kw)
        row["service_date"] = sd
        out.append(row)
    return pd.DataFrame(out)


def fa_frame(*rows: dict) -> pd.DataFrame:
    out = []
    for i, kw in enumerate(rows or ({},), start=1):
        kw = dict(kw)
        sd = pd.Timestamp(kw.get("scheduled_date", "2026-01-05"))
        row = dict(
            appointment_id=f"AP{i:03d}", center_id="C001", scheduled_date=sd, scheduled_slot="09:00",
            booking_channel="Ather App", requested_service_type="Periodic Service", status="Completed",
            cancellation_reason=np.nan, lead_days=3, lead_time_band="1-3 days", weekday=sd.day_name(),
            month=sd.strftime("%Y-%m"), month_num=sd.month, year=sd.year,
            is_cancelled=False, is_no_show=False, is_completed=True,
        )
        row.update(kw)
        row["scheduled_date"] = sd
        out.append(row)
    return pd.DataFrame(out)


def ftm_frame(*rows: dict) -> pd.DataFrame:
    out = []
    for kw in rows or ({},):
        row = dict(technician_id="T1", center_id="C001", skill_level="Mid", month="2026-01",
                   working_days=26, jobs=10, service_hours=50.0, available_hours=100.0)
        row.update(kw)
        out.append(row)
    return pd.DataFrame(out)


def techs_frame(spec: list[tuple]) -> pd.DataFrame:
    """spec items: (technician_id, center_id, skill_level[, hourly_cost, shift_hours])."""
    rows = []
    for item in spec:
        tid, cid, skill, *rest = item
        hc, sh = (rest + [200.0, 8])[:2] if rest else (200.0, 8)
        rows.append(dict(technician_id=tid, center_id=cid, skill_level=skill,
                         hourly_cost=hc, shift_hours_per_day=sh))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Synthetic full-schema dataset
# --------------------------------------------------------------------------- #
CENTRES = [f"C00{i}" for i in range(1, 9)]
SKILLS = ["Junior", "Mid", "Senior", "Master"]
LEAD_BANDS = [(0, "Same day"), (3, "1-3 days"), (7, "4-7 days"), (14, "8-14 days"), (10**6, "15+ days")]


def _lead_band(days: int) -> str:
    for upper, name in LEAD_BANDS:
        if days <= upper:
            return name
    raise AssertionError


def _date_pool() -> list[pd.Timestamp]:
    dates = set()
    for month in pd.period_range("2025-01", "2026-09", freq="M"):
        first = month.to_timestamp()
        days = [first + pd.Timedelta(days=d - 1) for d in (3, 10, 17, 24)]
        first_sat = first + pd.Timedelta(days=(5 - first.dayofweek) % 7)
        for d in days + [first_sat]:
            if d.dayofweek == 6:
                d += pd.Timedelta(days=1)
            dates.add(d)
    return sorted(dates)


def make_dataset(seed: int = 7, n_fs: int = 2400, n_extra_appts: int = 600) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    centre_names = {c: f"Centre {c}" for c in CENTRES}

    # technicians: Junior/Mid/Senior everywhere, plus a Master at C001
    trows = []
    for c in CENTRES:
        for s in SKILLS[:3] + (["Master"] if c == "C001" else []):
            trows.append(dict(technician_id=f"T{len(trows) + 1:03d}", center_id=c, skill_level=s,
                              years_experience=3, certification="EV L2",
                              hourly_cost={"Junior": 200.0, "Mid": 260.0, "Senior": 360.0, "Master": 450.0}[s],
                              shift_hours_per_day=8))
    technicians = pd.DataFrame(trows)
    by_centre = {c: technicians[technicians["center_id"] == c] for c in CENTRES}

    dates = _date_pool()
    centre_w = np.array([1, 1, 2, 1, 1, 3, 2, 1], dtype=float)
    centre_w /= centre_w.sum()
    center = rng.choice(CENTRES, n_fs, p=centre_w)
    service_date = pd.to_datetime([dates[i] for i in rng.integers(0, len(dates), n_fs)])
    tech_ids, skills = [], []
    for c in center:
        t = by_centre[c].iloc[int(rng.integers(0, len(by_centre[c])))]
        tech_ids.append(t["technician_id"])
        skills.append(t["skill_level"])
    tech_ids = pd.Series(tech_ids, dtype="object")
    skills = pd.Series(skills, dtype="object")
    missing = rng.random(n_fs) < 0.01  # a few jobs without a technician
    tech_ids[missing] = None
    skills[missing] = None

    est = np.round(rng.uniform(1, 6, n_fs), 2)
    actual = np.round(est * rng.uniform(0.7, 1.6, n_fs), 2)
    wait = np.round(rng.exponential(0.6, n_fs) + 0.05, 2)
    delay_p = np.where(center == "C008", 0.4, 0.15)
    parts_delay = rng.random(n_fs) < delay_p
    parts_wait = np.where(parts_delay, np.round(rng.uniform(2, 30, n_fs), 1), 0.0)
    check_in = service_date + pd.to_timedelta(9 + rng.integers(0, 120, n_fs) / 60, unit="h")
    start = check_in + pd.to_timedelta(wait, unit="h")
    end = start + pd.to_timedelta(actual + parts_wait, unit="h")
    promised = check_in + pd.to_timedelta(est + 1.5, unit="h")
    turnaround = np.round((end - check_in).total_seconds() / 3600, 2)
    late = np.round(np.maximum(0, (end - promised).total_seconds() / 3600), 2)
    on_time = late == 0
    billing = rng.choice(["Customer Paid", "Warranty", "Rework (No Charge)"], n_fs, p=[0.8, 0.1, 0.1])
    labor = np.round(actual * 100, 2)
    parts_cost = np.round(rng.uniform(0, 4000, n_fs), 2)
    revenue = np.where(billing == "Rework (No Charge)", 0.0, np.round((labor + parts_cost) * rng.uniform(1.0, 1.6, n_fs), 2))
    total_cost = labor + parts_cost
    est_cost = np.round(est * 100 + parts_cost * rng.uniform(0.8, 1.2, n_fs), 2)
    cvar = total_cost - est_cost
    cvar_pct = cvar / est_cost
    rating = np.where(rng.random(n_fs) < 0.6, rng.integers(1, 6, n_fs).astype(float), np.nan)
    junior = skills.eq("Junior").to_numpy()
    comeback = rng.random(n_fs) < np.where(junior, 0.2, 0.06)
    qc = rng.random(n_fs) >= np.where(junior, 0.2, 0.07)
    service_types = ["Periodic Service", "Tyre Replacement", "Motor & Controller Repair",
                     "Charging System Repair", "Electrical Diagnostics", "Accident & Body Repair"]
    fs = pd.DataFrame(dict(
        work_order_id=[f"WO{i:06d}" for i in range(n_fs)],
        appointment_id=[f"AP{i:06d}" for i in range(n_fs)],
        technician_id=tech_ids, service_type=rng.choice(service_types, n_fs),
        check_in_time=check_in, start_time=start, end_time=end, promised_ready_time=promised,
        estimated_hours=est, actual_hours=actual, parts_wait_hours=parts_wait,
        additional_work_found=rng.random(n_fs) < 0.3, qc_passed_first_time=qc,
        center_id=center, booking_channel=rng.choice(["Ather App", "Phone", "Walk-in"], n_fs),
        customer_id=[f"CU{i:04d}" for i in rng.integers(0, 700, n_fs)],
        model=rng.choice(["Ather 450X", "Ather 450 Apex", "Ather Rizta"], n_fs),
        customer_type=rng.choice(["Individual", "Fleet"], n_fs, p=[0.8, 0.2]),
        center_name=[centre_names[c] for c in center], skill_level=skills, billing_type=billing,
        estimated_cost=est_cost, labor_cost=labor, parts_cost=parts_cost, revenue=revenue, rating=rating,
        feedback_category=rng.choice(["Positive Experience", "Delay", "Pricing"], n_fs),
        service_date=service_date, year=service_date.year, month=service_date.strftime("%Y-%m"),
        wait_hours=wait, turnaround_hours=turnaround, late_hours=late, on_time_flag=on_time,
        duration_variance_hours=np.round(actual - est, 2), parts_delay_flag=parts_delay,
        total_cost=total_cost, profit=revenue - total_cost, cost_variance=cvar,
        cost_variance_pct=cvar_pct, cost_overrun_flag=cvar_pct > 0.10, caused_repeat_visit=comeback,
    ))
    fs["weekday"] = fs["service_date"].dt.day_name()
    fs["month_num"] = fs["service_date"].dt.month

    # appointments: one per work order + extras (cancelled / no-show / completed without a work order)
    n_fa = n_fs + n_extra_appts
    extra_centre = rng.choice(CENTRES, n_extra_appts, p=centre_w)
    sched = pd.to_datetime(list(service_date) + [dates[i] for i in rng.integers(0, len(dates), n_extra_appts)])
    fa_center = np.concatenate([center, extra_centre])
    p_cancel = np.where(fa_center == "C006", 0.45, 0.2)
    extra_status = np.where(rng.random(n_extra_appts) < p_cancel[n_fs:], "Cancelled",
                            np.where(rng.random(n_extra_appts) < 0.15, "No-Show", "Completed"))
    status = np.concatenate([np.full(n_fs, "Completed"), extra_status])
    channel = np.concatenate([fs["booking_channel"].to_numpy(),
                              rng.choice(["Ather App", "Phone", "Walk-in"], n_extra_appts)])
    lead = np.where(channel == "Walk-in", 0, rng.integers(1, 25, n_fa))
    slot_h, slot_m = rng.integers(9, 17, n_fa), rng.integers(0, 60, n_fa)
    fa = pd.DataFrame(dict(
        appointment_id=[f"AP{i:06d}" for i in range(n_fa)],
        vehicle_id="V1", center_id=fa_center,
        booking_date=sched - pd.to_timedelta(lead, unit="D"), scheduled_date=sched,
        scheduled_slot=[f"{h:02d}:{m:02d}" for h, m in zip(slot_h, slot_m)], booking_channel=channel,
        requested_service_type=rng.choice(service_types, n_fa), status=status,
        cancellation_reason=np.where(status == "Cancelled", rng.choice(["Schedule clash", "Price"], n_fa), None),
        customer_id="CU0001", lead_days=lead, lead_time_band=[_lead_band(int(x)) for x in lead],
        is_cancelled=status == "Cancelled", is_no_show=status == "No-Show", is_completed=status == "Completed",
    ))
    fa["weekday"] = fa["scheduled_date"].dt.day_name()
    fa["month"] = fa["scheduled_date"].dt.strftime("%Y-%m")
    fa["month_num"] = fa["scheduled_date"].dt.month
    fa["year"] = fa["scheduled_date"].dt.year

    months = [str(m) for m in pd.period_range("2025-01", "2026-09", freq="M")]
    ftm = pd.DataFrame([dict(technician_id=t.technician_id, center_id=t.center_id, skill_level=t.skill_level,
                             month=m, working_days=26, jobs=20, service_hours=float(rng.uniform(60, 160)),
                             qc_first_pass=0.9, comebacks_caused=1, available_hours=26.0 * t.shift_hours_per_day)
                        for t in technicians.itertuples() for m in months])

    ended = fs.loc[fs["rating"].notna()]
    feedback = pd.DataFrame(dict(
        feedback_id=[f"FB{i:06d}" for i in range(len(ended))], work_order_id=ended["work_order_id"].to_numpy(),
        rating=ended["rating"].to_numpy(), feedback_category=ended["feedback_category"].to_numpy(),
        feedback_date=ended["end_time"].dt.normalize().to_numpy() + pd.to_timedelta(rng.integers(0, 6, len(ended)), unit="D")))

    parts = pd.DataFrame(dict(
        part_id=[f"P{i:03d}" for i in range(1, 13)],
        part_name=[f"Part {i}" for i in range(1, 13)],
        part_category=["Brakes", "Tyres", "Battery", "Electrical"] * 3,
        unit_cost=[650, 1200, 15000, 300, 80, 2500, 9000, 150, 4000, 700, 55, 1800],
        compatible_models="All", supplier_lead_days=[3, 5, 21, 7, 2, 10, 30, 4, 14, 6, 2, 9]))
    nlines = rng.integers(1, 4, n_fs)
    part_usage = pd.DataFrame(dict(
        work_order_id=np.repeat(fs["work_order_id"].to_numpy(), nlines),
        part_id=rng.choice(parts["part_id"].to_numpy(), int(nlines.sum())),
        quantity=rng.integers(1, 4, int(nlines.sum()))))
    part_usage.insert(0, "usage_id", [f"PU{i:06d}" for i in range(len(part_usage))])

    service_centers = pd.DataFrame(dict(center_id=CENTRES, center_name=[centre_names[c] for c in CENTRES]))
    return {"fact_service": fs, "fact_appointments": fa, "fact_technician_month": ftm,
            "technicians": technicians, "service_centers": service_centers, "parts": parts,
            "part_usage": part_usage, "feedback": feedback}


def _copy(d: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {k: v.copy(deep=True) for k, v in d.items()}


@pytest.fixture(scope="module")
def _synth_cache():
    return make_dataset()


@pytest.fixture
def ds(_synth_cache):
    return _copy(_synth_cache)


@pytest.fixture(scope="module")
def synth_metrics(_synth_cache):
    return am.compute_all(_copy(_synth_cache))


@pytest.fixture
def synth_load(ds):
    daily = am.daily_load(ds["fact_service"], ds["technicians"])
    return daily, am.attach_load(ds["fact_service"], daily)


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
class TestFormatting:
    @pytest.mark.parametrize("value, expected", [
        (0, f"{RUPEE}0"),
        (999.4, f"{RUPEE}999"),
        (99_999, f"{RUPEE}99,999"),
        (100_000, f"{RUPEE}1.00 lakh"),
        (2_550_000, f"{RUPEE}25.50 lakh"),
        (9_999_999, f"{RUPEE}100.00 lakh"),
        (10_000_000, f"{RUPEE}1.00 crore"),
        (123_456_789, f"{RUPEE}12.35 crore"),
        (-25_000_000, f"{RUPEE}-2.50 crore"),
        (-150_000, f"{RUPEE}-1.50 lakh"),
    ])
    def test_inr_units(self, value, expected):
        assert am.inr(value) == expected

    @pytest.mark.parametrize("value, nd, expected", [
        (0.5, 1, "50.0%"), (0.12345, 1, "12.3%"), (0.12345, 2, "12.35%"), (1, 0, "100%"),
        (0, 1, "0.0%"), (-0.05, 1, "-5.0%"),
    ])
    def test_pct(self, value, nd, expected):
        assert am.pct(value, nd) == expected

    def test_pct_nan_renders_nan(self):
        assert am.pct(float("nan")) == "nan%"


# --------------------------------------------------------------------------- #
# headline_kpis
# --------------------------------------------------------------------------- #
@pytest.fixture
def kpi_inputs():
    fs = fs_frame(
        dict(customer_id="CU1", revenue=1000.0, labor_cost=200.0, parts_cost=300.0, on_time_flag=True,
             turnaround_hours=2.0, wait_hours=1.0, rating=5.0, cost_variance=10.0, duration_variance_hours=0.5),
        dict(customer_id="CU1", revenue=500.0, labor_cost=100.0, parts_cost=100.0, on_time_flag=False,
             turnaround_hours=4.0, wait_hours=3.0, rating=3.0, cost_variance=-5.0, cost_overrun_flag=True,
             caused_repeat_visit=True, duration_variance_hours=-0.5),
        dict(customer_id="CU2", revenue=800.0, labor_cost=100.0, parts_cost=100.0, on_time_flag=True,
             turnaround_hours=3.0, wait_hours=2.0, rating=np.nan, cost_variance=0.0,
             duration_variance_hours=1.0, qc_passed_first_time=False),
        dict(customer_id="CU3", revenue=200.0, labor_cost=50.0, parts_cost=50.0, on_time_flag=True,
             turnaround_hours=7.0, wait_hours=2.0, rating=4.0, cost_variance=5.0, parts_delay_flag=True,
             duration_variance_hours=1.0),
    )
    fa = fa_frame(dict(), dict(is_cancelled=True, status="Cancelled"), dict(is_no_show=True, status="No-Show"), dict())
    ftm = ftm_frame(dict(service_hours=30.0, available_hours=40.0), dict(technician_id="T2", service_hours=10.0,
                                                                          available_hours=20.0))
    return fs, fa, ftm


class TestHeadlineKpis:
    def test_known_values(self, kpi_inputs):
        h = am.headline_kpis(*kpi_inputs)
        assert h["work_orders"] == 4 and h["appointments"] == 4
        assert h["revenue"] == 2500.0
        assert h["total_cost"] == 1000.0
        assert h["labor_cost"] == 450.0 and h["parts_cost"] == 550.0
        assert h["profit"] == 1500.0
        assert h["margin"] == pytest.approx(0.6)
        assert h["avg_service_cost"] == 250.0
        assert h["avg_revenue_per_job"] == 625.0
        assert h["on_time_rate"] == 0.75
        assert h["avg_turnaround_h"] == pytest.approx(4.0)
        assert h["median_turnaround_h"] == pytest.approx(3.5)
        assert h["avg_wait_h"] == pytest.approx(2.0)
        assert h["cost_variance_total"] == pytest.approx(10.0)
        assert h["cost_overrun_rate"] == 0.25
        assert h["cancellation_rate"] == 0.25 and h["no_show_rate"] == 0.25
        assert h["utilisation"] == pytest.approx(40 / 60)
        assert h["csat"] == pytest.approx(4.0)
        assert h["csat_pct"] == pytest.approx(2 / 3)
        assert h["rating_responses"] == 3
        assert h["repeat_visit_rate"] == pytest.approx(1 / 3)
        assert h["comeback_rate"] == 0.25
        assert h["duration_variance_h"] == pytest.approx(0.5)
        assert h["parts_delay_rate"] == 0.25
        assert h["qc_first_pass"] == 0.75

    def test_types_are_plain_python_and_json_safe(self, kpi_inputs):
        h = am.headline_kpis(*kpi_inputs)
        for k, v in h.items():
            assert type(v) in (int, float), k
        json.dumps(h)

    def test_margin_is_profit_over_revenue(self, kpi_inputs):
        h = am.headline_kpis(*kpi_inputs)
        assert h["margin"] == pytest.approx(h["profit"] / h["revenue"])
        assert h["profit"] == pytest.approx(h["revenue"] - h["total_cost"])
        assert h["total_cost"] == pytest.approx(h["labor_cost"] + h["parts_cost"])

    def test_repeat_visit_rate_counts_customers_not_orders(self):
        fs = fs_frame(dict(customer_id="A"), dict(customer_id="A"), dict(customer_id="A"), dict(customer_id="B"))
        h = am.headline_kpis(fs, fa_frame(), ftm_frame())
        assert h["repeat_visit_rate"] == 0.5

    def test_all_ratings_missing_gives_nan_csat(self):
        fs = fs_frame(dict(rating=np.nan), dict(rating=np.nan))
        h = am.headline_kpis(fs, fa_frame(), ftm_frame())
        assert math.isnan(h["csat"]) and math.isnan(h["csat_pct"])
        assert h["rating_responses"] == 0

    def test_single_row_single_centre_single_month(self):
        h = am.headline_kpis(fs_frame(), fa_frame(), ftm_frame())
        assert h["work_orders"] == 1
        assert h["margin"] == pytest.approx(100 / 300)
        assert h["repeat_visit_rate"] == 0.0

    def test_zero_revenue_gives_nan_not_crash(self):
        fs = fs_frame(dict(revenue=0.0, labor_cost=10.0, parts_cost=0.0))
        with np.errstate(all="ignore"):
            h = am.headline_kpis(fs, fa_frame(), ftm_frame())
        assert h["profit"] == -10.0
        assert not math.isfinite(h["margin"])

    def test_empty_frames_do_not_crash(self):
        fs = fs_frame().iloc[0:0]
        fa = fa_frame().iloc[0:0]
        ftm = ftm_frame().iloc[0:0]
        with np.errstate(all="ignore"):
            h = am.headline_kpis(fs, fa, ftm)
        assert h["work_orders"] == 0 and h["revenue"] == 0.0
        assert math.isnan(h["on_time_rate"])

    def test_missing_column_raises_keyerror(self, kpi_inputs):
        fs, fa, ftm = kpi_inputs
        with pytest.raises(KeyError):
            am.headline_kpis(fs.drop(columns="revenue"), fa, ftm)


# --------------------------------------------------------------------------- #
# service_scorecard / utilisation / cancellation_by
# --------------------------------------------------------------------------- #
class TestScorecards:
    def test_scorecard_by_single_key(self, kpi_inputs):
        fs = kpi_inputs[0].assign(center_id=["C001", "C001", "C002", "C002"])
        sc = am.service_scorecard(fs, "center_id")
        a, b = sc.loc["C001"], sc.loc["C002"]
        assert (a["jobs"], a["revenue"], a["total_cost"], a["profit"]) == (2, 1500.0, 700.0, 800.0)
        assert a["margin"] == pytest.approx(800 / 1500)
        assert a["avg_service_cost"] == pytest.approx(350.0)
        assert a["on_time"] == 0.5
        assert a["csat"] == pytest.approx(4.0) and a["csat_pct"] == 0.5
        assert (b["jobs"], b["revenue"]) == (2, 1000.0)
        assert b["csat_pct"] == 1.0  # NaN rating ignored, the 4.0 counts
        assert b["qc_first_pass"] == 0.5
        assert b["parts_delay"] == 0.5

    def test_scorecard_by_two_keys_has_multiindex(self):
        fs = fs_frame(dict(center_id="C001", skill_level="Mid"), dict(center_id="C001", skill_level="Junior"),
                      dict(center_id="C002", skill_level="Mid"))
        sc = am.service_scorecard(fs, ["center_id", "skill_level"])
        assert sc.index.names == ["center_id", "skill_level"]
        assert sc.loc[("C001", "Junior"), "jobs"] == 1
        assert len(sc) == 3

    def test_group_with_no_ratings_has_nan_csat(self):
        fs = fs_frame(dict(rating=np.nan), dict(rating=np.nan, center_id="C002"), dict(rating=5.0, center_id="C002"))
        sc = am.service_scorecard(fs, "center_id")
        assert math.isnan(sc.loc["C001", "csat"]) and math.isnan(sc.loc["C001", "csat_pct"])
        assert sc.loc["C002", "csat_pct"] == 1.0

    def test_null_group_keys_are_dropped(self):
        fs = fs_frame(dict(skill_level="Mid"), dict(skill_level=None))
        sc = am.service_scorecard(fs, "skill_level")
        assert list(sc.index) == ["Mid"]

    def test_utilisation_is_ratio_of_sums_not_mean_of_ratios(self):
        ftm = ftm_frame(dict(center_id="C001", service_hours=10.0, available_hours=10.0),
                        dict(center_id="C001", technician_id="T2", service_hours=0.0, available_hours=90.0),
                        dict(center_id="C002", service_hours=50.0, available_hours=100.0))
        u = am.utilisation(ftm, "center_id")
        assert u["C001"] == pytest.approx(0.1)  # 10/100, not mean(1.0, 0.0)=0.5
        assert u["C002"] == pytest.approx(0.5)

    def test_utilisation_two_keys(self):
        ftm = ftm_frame(dict(), dict(month="2026-02", service_hours=100.0, available_hours=100.0))
        u = am.utilisation(ftm, ["center_id", "month"])
        assert u[("C001", "2026-01")] == 0.5 and u[("C001", "2026-02")] == 1.0

    def test_cancellation_by(self):
        fa = fa_frame(dict(center_id="C001", is_cancelled=True, lead_days=10),
                      dict(center_id="C001", lead_days=2),
                      dict(center_id="C001", is_no_show=True, lead_days=3),
                      dict(center_id="C001", lead_days=1),
                      dict(center_id="C002", lead_days=0))
        out = am.cancellation_by(fa, "center_id")
        c1 = out.loc["C001"]
        assert c1["appointments"] == 4
        assert c1["cancellation_rate"] == 0.25 and c1["no_show_rate"] == 0.25
        assert c1["mean_lead_days"] == pytest.approx(4.0)
        assert out.loc["C002", "cancellation_rate"] == 0.0


# --------------------------------------------------------------------------- #
# centre_scorecard / monthly_trend / yoy
# --------------------------------------------------------------------------- #
class TestCentreAndTrend:
    def test_centre_scorecard_single_centre_known_values(self):
        fs = fs_frame(
            dict(service_type="Electrical Diagnostics", skill_level="Junior", on_time_flag=True, customer_type="Fleet"),
            dict(service_type="Periodic Service", skill_level="Senior", on_time_flag=False),
            dict(service_type="Accident & Body Repair", skill_level="Mid", on_time_flag=False,
                 service_date="2026-02-02"),
            dict(service_type="Tyre Replacement", skill_level="Mid", service_date="2026-02-03"),
        )
        fa = fa_frame(dict(), dict(is_cancelled=True))
        ftm = ftm_frame(dict(service_hours=30.0, available_hours=60.0),
                        dict(technician_id="T2", month="2025-12", service_hours=10.0, available_hours=40.0))
        techs = techs_frame([("T1", "C001", "Mid"), ("T2", "C001", "Senior"), ("T3", "C001", "Master")])
        sc = am.centre_scorecard(fs, fa, ftm, techs)
        assert list(sc.index) == ["C001"]
        r = sc.loc["C001"]
        assert r["jobs"] == 4
        assert r["technicians"] == 3 and r["senior_or_master_techs"] == 2
        assert r["utilisation"] == pytest.approx(40 / 100)
        assert r["utilisation_2026"] == pytest.approx(0.5)  # 2025-12 excluded
        assert r["cancellation_rate"] == 0.5
        assert r["junior_job_share"] == 0.25
        assert r["complex_job_share"] == 0.5
        assert r["periodic_share"] == 0.25
        assert r["fleet_job_share"] == 0.25
        assert r["complex_on_time"] == 0.5  # 1 of the 2 complex jobs is on time
        # 4 jobs in 2026 / 2 distinct months / 3 technicians
        assert r["jobs_per_tech_month_2026"] == pytest.approx(4 / 2 / 3)

    def test_centre_without_senior_gets_zero_not_nan(self):
        fs = fs_frame(dict(), dict(center_id="C002", center_name="Beta"))
        techs = techs_frame([("T1", "C001", "Senior"), ("T2", "C002", "Junior")])
        ftm = ftm_frame(dict(), dict(center_id="C002", technician_id="T2"))
        sc = am.centre_scorecard(fs, fa_frame(dict(), dict(center_id="C002")), ftm, techs)
        assert sc.loc["C001", "senior_or_master_techs"] == 1
        assert sc.loc["C002", "senior_or_master_techs"] == 0
        assert sc["senior_or_master_techs"].dtype.kind == "i"

    def test_monthly_trend_single_month(self):
        fs = fs_frame(dict(), dict(on_time_flag=False))
        out = am.monthly_trend(fs, fa_frame(dict(), dict(is_cancelled=True)), ftm_frame())
        assert list(out.index) == ["2026-01"]
        r = out.loc["2026-01"]
        assert r["jobs"] == 2 and r["on_time"] == 0.5
        assert r["appointments"] == 2 and r["cancellation_rate"] == 0.5
        assert r["utilisation"] == 0.5

    def test_monthly_trend_months_sorted(self):
        fs = fs_frame(dict(service_date="2026-03-02"), dict(service_date="2026-01-05"), dict(service_date="2026-02-02"))
        fa = fa_frame(dict(scheduled_date="2026-03-02"), dict(scheduled_date="2026-01-05"),
                      dict(scheduled_date="2026-02-02"))
        ftm = ftm_frame(dict(month="2026-03"), dict(month="2026-01"), dict(month="2026-02"))
        assert list(am.monthly_trend(fs, fa, ftm).index) == ["2026-01", "2026-02", "2026-03"]

    def test_yoy_jan_sep_known_values(self):
        fs = fs_frame(
            dict(service_date="2025-03-03", revenue=1000.0, labor_cost=0.0, parts_cost=0.0, on_time_flag=True),
            dict(service_date="2025-04-07", revenue=1000.0, labor_cost=0.0, parts_cost=0.0, on_time_flag=False),
            dict(service_date="2025-12-01", revenue=99999.0, on_time_flag=False),  # Oct-Dec excluded
            dict(service_date="2026-03-02", revenue=3000.0, labor_cost=0.0, parts_cost=0.0, on_time_flag=True),
            dict(service_date="2026-04-06", revenue=1000.0, labor_cost=0.0, parts_cost=0.0, on_time_flag=True),
        )
        fa = fa_frame(dict(scheduled_date="2025-03-03"), dict(scheduled_date="2025-04-07", is_cancelled=True),
                      dict(scheduled_date="2025-11-03", is_cancelled=True),
                      dict(scheduled_date="2026-03-02"), dict(scheduled_date="2026-04-06"))
        ftm = ftm_frame(dict(month="2025-03", service_hours=40.0, available_hours=100.0),
                        dict(month="2025-11", service_hours=100.0, available_hours=100.0),
                        dict(month="2026-03", service_hours=60.0, available_hours=100.0))
        y = am.yoy_jan_sep(fs, fa, ftm)
        assert y.loc["jobs", 2025] == 2 and y.loc["jobs", 2026] == 2
        assert y.loc["revenue", 2025] == 2000.0 and y.loc["revenue", 2026] == 4000.0
        assert y.loc["revenue", "change"] == 2000.0
        assert y.loc["revenue", "pct_change"] == pytest.approx(1.0)
        assert y.loc["on_time", 2025] == 0.5 and y.loc["on_time", 2026] == 1.0
        assert y.loc["cancellation_rate", 2025] == 0.5 and y.loc["cancellation_rate", 2026] == 0.0
        assert y.loc["appointments", 2025] == 2
        assert y.loc["utilisation", 2025] == pytest.approx(0.4)
        assert y.loc["utilisation", 2026] == pytest.approx(0.6)

    def test_yoy_missing_year_raises_keyerror(self):
        fs = fs_frame(dict(service_date="2026-03-02"))
        fa = fa_frame(dict(scheduled_date="2026-03-02"))
        with pytest.raises(KeyError):
            am.yoy_jan_sep(fs, fa, ftm_frame(dict(month="2026-03")))


# --------------------------------------------------------------------------- #
# Daily load, load bands, weekday profile
# --------------------------------------------------------------------------- #
class TestDailyLoad:
    def test_daily_load_known_values(self):
        fs = fs_frame(
            dict(service_date="2026-01-05", estimated_hours=3.0, wait_hours=1.0, on_time_flag=True),
            dict(service_date="2026-01-05", estimated_hours=4.0, wait_hours=3.0, on_time_flag=False),
            dict(service_date="2026-01-06", estimated_hours=10.0, wait_hours=0.0),
            dict(service_date="2026-01-06", estimated_hours=9.0),
        )
        techs = techs_frame([("T1", "C001", "Mid"), ("T2", "C001", "Senior")])
        d = am.daily_load(fs, techs)
        assert len(d) == 2
        mon, tue = d.iloc[0], d.iloc[1]
        assert mon["jobs"] == 2 and mon["booked_hours"] == 7.0
        assert mon["capacity_hours"] == 2 * am.PRODUCTIVE_HOURS_PER_DAY == 14.0
        assert mon["load_ratio"] == 0.5 and not mon["overloaded"]
        assert mon["wait_h"] == 2.0 and mon["on_time"] == 0.5
        assert tue["load_ratio"] == pytest.approx(19 / 14) and tue["overloaded"]
        assert mon["weekday"] == "Monday"

    def test_exactly_full_day_is_not_overloaded(self):
        fs = fs_frame(dict(estimated_hours=14.0))
        d = am.daily_load(fs, techs_frame([("T1", "C001", "Mid"), ("T2", "C001", "Mid")]))
        assert d.loc[0, "load_ratio"] == 1.0
        assert not d.loc[0, "overloaded"]

    def test_centre_without_technicians_gives_nan_load_and_not_overloaded(self):
        fs = fs_frame(dict(center_id="C009", center_name="Ghost"))
        d = am.daily_load(fs, techs_frame([("T1", "C001", "Mid")]))
        assert math.isnan(d.loc[0, "capacity_hours"]) and math.isnan(d.loc[0, "load_ratio"])
        assert not d.loc[0, "overloaded"]

    def test_separate_centres_same_day_are_separate_rows(self):
        fs = fs_frame(dict(), dict(center_id="C002", center_name="Beta"))
        d = am.daily_load(fs, techs_frame([("T1", "C001", "Mid"), ("T2", "C002", "Mid")]))
        assert sorted(d["center_id"]) == ["C001", "C002"]

    def test_attach_load_bands_right_closed(self):
        fs = fs_frame(*[dict(service_date=f"2026-01-{5 + i:02d}", estimated_hours=h)
                        for i, h in enumerate([0.0, 7.0 * 0.6, 7.0 * 1.0, 7.0 * 1.5, 7.0 * 2.0])])
        techs = techs_frame([("T1", "C001", "Mid")])
        out = am.attach_load(fs, am.daily_load(fs, techs))
        assert len(out) == len(fs)
        bands = out["load_band"].astype(str).tolist()
        assert pd.isna(out["load_band"].iloc[0])  # 0 is outside (0, 0.6]
        assert bands[2] == "(0.9, 1.0]"  # right-closed edge stays in the lower band
        assert bands[3] == "(1.4, 1.6]"
        assert bands[4] == "(1.6, inf]"

    def test_attach_load_keeps_unmatched_rows(self):
        fs = fs_frame(dict(), dict(service_date="2026-01-06"))
        daily = am.daily_load(fs, techs_frame([("T1", "C001", "Mid")]))
        daily = daily[daily["service_date"] == "2026-01-05"]
        out = am.attach_load(fs, daily)
        assert len(out) == 2 and out["load_ratio"].isna().sum() == 1

    def test_load_band_profile(self):
        fl = fs_frame(dict(), dict(on_time_flag=False, wait_hours=1.5, rating=2.0, caused_repeat_visit=True),
                      dict(wait_hours=0.1, rating=np.nan))
        fl["load_ratio"] = [0.5, 0.55, 1.5]
        fl["load_band"] = pd.cut(fl["load_ratio"], am.LOAD_BANDS, right=True)
        p = am.load_band_profile(fl)
        assert len(p) == 2  # unobserved bands are not listed
        low = p.iloc[0]
        assert low["jobs"] == 2 and low["on_time"] == 0.5 and low["wait_h"] == 1.0
        assert low["comeback"] == 0.5 and low["csat"] == 3.0
        assert p.iloc[1]["jobs"] == 1 and math.isnan(p.iloc[1]["csat"])

    def test_weekday_profile_order_and_shares(self):
        fs = fs_frame(dict(service_date="2026-01-05"), dict(service_date="2026-01-05"),
                      dict(service_date="2026-01-10"))  # Mon, Mon, Sat
        fa = fa_frame(dict(scheduled_date="2026-01-05"), dict(scheduled_date="2026-01-10", is_cancelled=True))
        w = am.weekday_profile(fs, fa)
        assert list(w.index) == am.WEEKDAY_ORDER
        assert w.loc["Monday", "jobs"] == 2 and w.loc["Saturday", "jobs"] == 1
        assert w.loc["Monday", "job_share"] == pytest.approx(2 / 3)
        assert w.loc["Saturday", "cancellation_rate"] == 1.0
        assert math.isnan(w.loc["Wednesday", "jobs"])
        assert w["job_share"].sum() == pytest.approx(1.0)

    def test_sunday_rows_are_excluded_from_weekday_profile(self):
        fs = fs_frame(dict(service_date="2026-01-04"))  # Sunday
        fa = fa_frame(dict(scheduled_date="2026-01-04"))
        w = am.weekday_profile(fs, fa)
        assert w["jobs"].isna().all()


# --------------------------------------------------------------------------- #
# Overnight carry-over / process stage metrics
# --------------------------------------------------------------------------- #
class TestOvernightCarryOver:
    def test_known_values(self):
        d = pd.Timestamp("2026-01-05")  # Monday
        fs = fs_frame(
            dict(end_time=d + pd.Timedelta(hours=17), on_time_flag=True),                      # same day
            dict(end_time=d + pd.Timedelta(days=1, hours=10), on_time_flag=False),            # carried
            dict(end_time=d + pd.Timedelta(days=1), on_time_flag=False),                      # midnight counts
            dict(end_time=d + pd.Timedelta(days=3), parts_delay_flag=True, on_time_flag=True),  # excluded
            dict(end_time=d + pd.Timedelta(hours=18), center_id="C002", on_time_flag=True),
        )
        r = am.overnight_carry_over(fs)
        assert r["network_share"] == pytest.approx(2 / 4)
        assert r["on_time_if_carried_over"] == 0.0
        assert r["on_time_if_same_day"] == 1.0
        assert r["by_centre"] == {"C001": 0.6667, "C002": 0.0}
        assert r["by_weekday"] == {"Monday": 0.5}

    def test_no_carry_over_gives_nan_for_carried_branch(self):
        r = am.overnight_carry_over(fs_frame(dict(), dict()))
        assert r["network_share"] == 0.0
        assert math.isnan(r["on_time_if_carried_over"])
        assert r["on_time_if_same_day"] == 1.0

    def test_all_jobs_parts_delayed_yields_nan_share(self):
        r = am.overnight_carry_over(fs_frame(dict(parts_delay_flag=True)))
        assert math.isnan(r["network_share"])
        assert r["by_centre"] == {}


class TestProcessStageMetrics:
    @pytest.fixture
    def inputs(self):
        fs = fs_frame(
            dict(appointment_id="AP001", check_in_time=pd.Timestamp("2026-01-05 09:30"),
                 wait_hours=1.0, on_time_flag=True, parts_delay_flag=False, additional_work_found=True,
                 estimated_hours=2.0, actual_hours=3.0, duration_variance_hours=1.0,
                 end_time=pd.Timestamp("2026-01-05 12:00")),
            dict(appointment_id="AP002", check_in_time=pd.Timestamp("2026-01-05 10:00"),
                 wait_hours=2.0, on_time_flag=False, late_hours=4.0, parts_delay_flag=True,
                 parts_wait_hours=10.0, estimated_hours=2.0, actual_hours=2.0, duration_variance_hours=0.0,
                 turnaround_hours=6.0, rating=np.nan, billing_type="Rework (No Charge)",
                 end_time=pd.Timestamp("2026-01-05 16:00")),
            dict(appointment_id="AP003", check_in_time=pd.Timestamp("2026-01-05 11:00"),
                 wait_hours=0.5, on_time_flag=False, late_hours=2.0, parts_delay_flag=True,
                 parts_wait_hours=20.0, duration_variance_hours=-1.0, turnaround_hours=4.0,
                 end_time=pd.Timestamp("2026-01-05 15:00")),
        )
        fa = fa_frame(
            dict(appointment_id="AP001", scheduled_slot="09:00", lead_days=4),
            dict(appointment_id="AP002", scheduled_slot="10:00", lead_days=10),
            dict(appointment_id="AP003", scheduled_slot="11:00", booking_channel="Walk-in", lead_days=0),
            dict(appointment_id="AP004", scheduled_slot="12:00", is_cancelled=True, lead_days=2),
        )
        fb = pd.DataFrame(dict(work_order_id=["WO001", "WO003"],
                               feedback_date=[pd.Timestamp("2026-01-07"), pd.Timestamp("2026-01-06")]))
        return fs, fa, fb

    def test_known_values(self, inputs):
        m = am.process_stage_metrics(*inputs)
        assert m["booking_lead_days_mean_booked"] == pytest.approx((4 + 10 + 2) / 3)
        assert m["booking_lead_days_median_booked"] == 4.0
        assert m["walk_in_share"] == 0.25
        assert m["cancellation_rate"] == 0.25 and m["no_show_rate"] == 0.0
        # AP001 arrives 30 min after slot, AP002 on the slot; walk-in excluded
        assert m["arrival_vs_slot_median_min"] == pytest.approx(15.0)
        assert m["wait_mean_h"] == pytest.approx(3.5 / 3)
        assert m["wait_median_h"] == 1.0
        assert m["wait_over_1_5h_share"] == pytest.approx(1 / 3)
        assert m["additional_work_found_rate"] == pytest.approx(1 / 3)
        assert m["estimated_hours_mean"] == 2.0
        assert m["actual_hours_mean"] == pytest.approx(7 / 3)
        assert m["labour_over_estimate_share"] == pytest.approx(1 / 3)
        assert m["parts_delay_rate"] == pytest.approx(2 / 3)
        assert m["parts_wait_mean_h_delayed"] == 15.0
        assert m["parts_wait_median_h_delayed"] == 15.0
        assert m["on_time_rate"] == pytest.approx(1 / 3)
        assert m["late_hours_median_when_late"] == 3.0
        assert m["late_hours_mean_when_late"] == 3.0
        assert m["feedback_response_rate"] == pytest.approx(2 / 3)
        # WO001 ends 2026-01-05 -> feedback 01-07 (2d); WO003 ends 01-05 -> 01-06 (1d)
        assert m["feedback_lag_days_mean"] == 1.5
        assert m["rework_billing_share"] == pytest.approx(1 / 3)
        assert m["qc_first_pass"] == 1.0 and m["comeback_rate"] == 0.0

    def test_all_values_are_floats(self, inputs):
        m = am.process_stage_metrics(*inputs)
        assert all(isinstance(v, float) for v in m.values())

    def test_no_delayed_and_no_late_jobs_gives_nan(self):
        fs = fs_frame(dict(appointment_id="AP001"))
        fa = fa_frame(dict(appointment_id="AP001"))
        fb = pd.DataFrame(dict(work_order_id=["WO001"], feedback_date=[pd.Timestamp("2026-01-06")]))
        m = am.process_stage_metrics(fs, fa, fb)
        assert math.isnan(m["parts_wait_mean_h_delayed"])
        assert math.isnan(m["late_hours_median_when_late"])
        assert m["arrival_vs_slot_median_min"] == 0.0
        assert m["feedback_lag_days_mean"] == 1.0


# --------------------------------------------------------------------------- #
# Parts: lines, delay by category, impact, ABC, safety stock
# --------------------------------------------------------------------------- #
@pytest.fixture
def parts_inputs():
    fs = fs_frame(
        dict(work_order_id="WO1", parts_delay_flag=True, parts_wait_hours=5.0),
        dict(work_order_id="WO2", parts_delay_flag=False),
        dict(work_order_id="WO3", parts_delay_flag=False, center_id="C002", center_name="Beta"),
    )
    parts = pd.DataFrame(dict(part_id=["P1", "P2", "P3"], part_name=["Brake", "Tyre", "Lamp"],
                              part_category=["Brakes", "Tyres", "Tyres"], unit_cost=[100, 50, 10],
                              supplier_lead_days=[4, 8, 2]))
    usage = pd.DataFrame(dict(usage_id=["U1", "U2", "U3", "U4", "U5"],
                              work_order_id=["WO1", "WO1", "WO2", "WO3", "WO3"],
                              part_id=["P1", "P2", "P2", "P2", "P3"], quantity=[2, 1, 3, 1, 4]))
    return fs, usage, parts


class TestPartsLines:
    def test_lines_cost_and_join(self, parts_inputs):
        fs, usage, parts = parts_inputs
        lines = am.parts_lines(fs, usage, parts)
        assert len(lines) == 5
        assert lines["line_cost"].sum() == 2 * 100 + 1 * 50 + 3 * 50 + 1 * 50 + 4 * 10
        row = lines[lines["usage_id"] == "U1"].iloc[0]
        assert row["line_cost"] == 200 and row["center_id"] == "C001" and bool(row["parts_delay_flag"])

    def test_orphan_usage_rows_are_dropped(self, parts_inputs):
        fs, usage, parts = parts_inputs
        usage = pd.concat([usage, pd.DataFrame(dict(usage_id=["U9"], work_order_id=["WO999"],
                                                    part_id=["P1"], quantity=[1]))])
        assert len(am.parts_lines(fs, usage, parts)) == 5

    def test_unknown_part_is_dropped(self, parts_inputs):
        fs, usage, parts = parts_inputs
        usage.loc[0, "part_id"] = "PX"
        assert len(am.parts_lines(fs, usage, parts)) == 4

    def test_empty_usage(self, parts_inputs):
        fs, usage, parts = parts_inputs
        lines = am.parts_lines(fs, usage.iloc[0:0], parts)
        assert lines.empty and "line_cost" in lines.columns


class TestPartsDelay:
    def test_delay_by_category_counts_each_job_once_per_category(self, parts_inputs):
        lines = am.parts_lines(*parts_inputs)
        out = am.parts_delay_by_category(lines)
        # Tyres: WO1 (delayed), WO2, WO3 -> 3 jobs (WO3 has two Tyres lines but counts once)
        assert out.loc["Tyres", "jobs"] == 3
        assert out.loc["Tyres", "delay_rate"] == pytest.approx(1 / 3)
        assert out.loc["Brakes", "jobs"] == 1 and out.loc["Brakes", "delay_rate"] == 1.0
        assert list(out.index) == ["Brakes", "Tyres"]  # sorted by delay rate desc
        # the first line of each job/category supplies the lead time (WO3: Tyre P2=8d, not Lamp P3=2d)
        assert out.loc["Tyres", "supplier_lead_days"] == pytest.approx(8.0)

    def test_category_by_centre_pivot(self, parts_inputs):
        lines = am.parts_lines(*parts_inputs)
        pv = am.parts_delay_category_centre(lines)
        assert set(pv.columns) == {"Alpha", "Beta"}
        assert pv.loc["Tyres", "Alpha"] == 0.5
        assert pv.loc["Tyres", "Beta"] == 0.0
        assert math.isnan(pv.loc["Brakes", "Beta"])

    def test_parts_delay_impact(self):
        fs = fs_frame(dict(parts_delay_flag=True, on_time_flag=False, turnaround_hours=8.0, parts_wait_hours=6.0,
                           rating=2.0),
                      dict(parts_delay_flag=True, on_time_flag=False, turnaround_hours=4.0, parts_wait_hours=2.0,
                           rating=4.0),
                      dict(parts_delay_flag=False, turnaround_hours=2.0, rating=5.0),
                      dict(parts_delay_flag=False, turnaround_hours=2.0, rating=np.nan))
        out = am.parts_delay_impact(fs)
        d, n = out.loc[True], out.loc[False]
        assert d["jobs"] == 2 and d["on_time"] == 0.0
        assert d["tat_mean_h"] == 6.0 and d["parts_wait_mean_h"] == 4.0
        assert d["csat"] == 3.0 and d["csat_pct"] == 0.5
        assert n["on_time"] == 1.0 and n["csat_pct"] == 1.0


class TestAbcParts:
    @pytest.fixture
    def lines(self):
        # consumption values 600 / 250 / 90 / 40 / 20  (total 1000)
        spec = [("P1", 6, 100), ("P2", 5, 50), ("P3", 9, 10), ("P4", 4, 10), ("P5", 2, 10)]
        rows = []
        for i, (pid, qty, unit) in enumerate(spec):
            rows.append(dict(part_id=pid, part_name=f"Part {pid}", part_category="Cat", unit_cost=unit,
                             supplier_lead_days=5, quantity=qty, line_cost=qty * unit,
                             work_order_id=f"WO{i}", parts_delay_flag=(i % 2 == 0)))
        return pd.DataFrame(rows)

    def test_classes_and_shares(self, lines):
        abc = am.abc_parts(lines)
        assert abc["part_id"].tolist() == ["P1", "P2", "P3", "P4", "P5"]
        assert abc["abc_class"].tolist() == ["A", "A", "B", "B", "C"]
        assert abc["value_share"].tolist() == pytest.approx([0.6, 0.25, 0.09, 0.04, 0.02])
        assert abc["cum_share"].iloc[-1] == pytest.approx(1.0)
        assert abc["value_share"].sum() == pytest.approx(1.0)
        assert abc["cum_share"].is_monotonic_increasing

    def test_sorted_by_value_even_if_input_unsorted(self, lines):
        abc = am.abc_parts(lines.iloc[::-1])
        assert abc["part_id"].iloc[0] == "P1"
        assert abc.index.tolist() == list(range(5))

    def test_aggregates_multiple_lines_for_one_part(self, lines):
        extra = lines.iloc[[0]].assign(work_order_id="WO99", parts_delay_flag=False, quantity=1, line_cost=100)
        abc = am.abc_parts(pd.concat([lines, extra]))
        p1 = abc[abc["part_id"] == "P1"].iloc[0]
        assert p1["units"] == 7 and p1["value"] == 700 and p1["jobs"] == 2
        assert p1["delay_rate"] == 0.5

    def test_single_part_is_class_a(self, lines):
        abc = am.abc_parts(lines.iloc[[0]])
        assert abc["abc_class"].tolist() == ["A"] and abc["value_share"].iloc[0] == 1.0

    def test_part_starting_at_95pct_cumulative_is_class_c(self):
        rows = [dict(part_id="P1", part_name="x", part_category="c", unit_cost=1, supplier_lead_days=1, quantity=1,
                     line_cost=950, work_order_id="W1", parts_delay_flag=False),
                dict(part_id="P2", part_name="y", part_category="c", unit_cost=1, supplier_lead_days=1, quantity=1,
                     line_cost=50, work_order_id="W2", parts_delay_flag=False)]
        abc = am.abc_parts(pd.DataFrame(rows))
        assert abc["abc_class"].tolist() == ["A", "C"]  # P2 starts at 95% cumulative share


class TestSafetyStock:
    @pytest.fixture
    def lines(self):
        def row(part, qty, lead, delay, centre="C008", year=2026, unit=100, wo="W"):
            return dict(part_id=part, part_name=part, part_category="Cat", unit_cost=unit, supplier_lead_days=lead,
                        quantity=qty, work_order_id=wo, parts_delay_flag=delay, center_id=centre, year=year)
        return pd.DataFrame([
            row("PA", 27, 20, True, wo="W1"),                  # 3/month * 20/30 = 2.0 -> 2 units
            row("PB", 1, 3, True, unit=1000, wo="W2"),         # tiny demand -> floor of 1 unit
            row("PC", 40, 30, False, wo="W3"),                 # delay rate 0 -> excluded
            row("PD", 90, 30, True, centre="C001", wo="W4"),   # other centre
            row("PE", 90, 30, True, year=2025, wo="W5"),       # other year
            row("PF", 9, 10, True, unit=5, wo="W6"),           # 1/month*10/30 = .33 -> ceil 1
            row("PF", 9, 10, False, unit=5, wo="W7"),          # PF delay rate 0.5 (still >= .1)
        ])

    def test_known_values(self, lines):
        ss = am.safety_stock_estimate(lines, "C008")
        assert set(ss["part_id"]) == {"PA", "PB", "PF"}
        pa = ss[ss["part_id"] == "PA"].iloc[0]
        assert pa["monthly_units"] == 3.0 and pa["cover_units"] == 2 and pa["stock_value"] == 200
        pb = ss[ss["part_id"] == "PB"].iloc[0]
        assert pb["cover_units"] == 1 and pb["stock_value"] == 1000
        pf = ss[ss["part_id"] == "PF"].iloc[0]
        assert pf["units"] == 18 and pf["cover_units"] == 1 and pf["stock_value"] == 5
        assert ss["stock_value"].is_monotonic_decreasing
        assert ss["cover_units"].dtype.kind == "i"

    def test_threshold_boundary_is_inclusive(self):
        lines = pd.DataFrame([dict(part_id="P", part_name="P", part_category="C", unit_cost=10, supplier_lead_days=3,
                                   quantity=1, work_order_id=f"W{i}", parts_delay_flag=(i == 0), center_id="C008",
                                   year=2026) for i in range(10)])  # delay rate exactly 0.10
        assert len(am.safety_stock_estimate(lines, "C008", min_delay_rate=0.10)) == 1
        assert len(am.safety_stock_estimate(lines, "C008", min_delay_rate=0.11)) == 0

    def test_months_and_year_parameters(self, lines):
        ss = am.safety_stock_estimate(lines, "C008", months=3)  # PA: 9/month * 20 / 30 = 6
        assert ss[ss["part_id"] == "PA"].iloc[0]["cover_units"] == 6
        ss25 = am.safety_stock_estimate(lines, "C008", year=2025)
        assert ss25["part_id"].tolist() == ["PE"]

    def test_unknown_centre_returns_empty(self, lines):
        ss = am.safety_stock_estimate(lines, "C999")
        assert ss.empty and "stock_value" in ss.columns
        assert ss["stock_value"].sum() == 0


# --------------------------------------------------------------------------- #
# People / skill
# --------------------------------------------------------------------------- #
class TestSkill:
    def test_skill_profile_reindexed_to_all_levels(self):
        fs = fs_frame(dict(skill_level="Junior", service_type="Electrical Diagnostics"),
                      dict(skill_level="Junior", service_type="Periodic Service"),
                      dict(skill_level="Senior", service_type="Charging System Repair"),
                      dict(skill_level=None, service_type="Periodic Service"))
        s = am.skill_profile(fs)
        assert list(s.index) == am.SKILL_ORDER
        assert s.loc["Junior", "jobs"] == 2 and s.loc["Junior", "complex_share"] == 0.5
        assert s.loc["Senior", "complex_share"] == 1.0
        assert math.isnan(s.loc["Mid", "jobs"]) and math.isnan(s.loc["Master", "complex_share"])

    def test_skill_profile_complex_only(self):
        fs = fs_frame(dict(skill_level="Junior", service_type="Electrical Diagnostics", on_time_flag=False),
                      dict(skill_level="Junior", service_type="Periodic Service", on_time_flag=True),
                      dict(skill_level="Mid", service_type="Accident & Body Repair"))
        s = am.skill_profile_complex(fs)
        assert s.loc["Junior", "jobs"] == 1 and s.loc["Junior", "on_time"] == 0.0
        assert s.loc["Mid", "jobs"] == 1
        assert list(s.index) == am.SKILL_ORDER

    def test_technician_scorecard(self):
        fs = fs_frame(dict(technician_id="T1"), dict(technician_id="T1"), dict(technician_id="T2", skill_level="Senior"),
                      dict(technician_id=None, skill_level=None))
        ftm = ftm_frame(dict(technician_id="T1", month="2025-12", service_hours=10.0, available_hours=100.0),
                        dict(technician_id="T1", month="2026-01", service_hours=60.0, available_hours=100.0),
                        dict(technician_id="T2", month="2026-01", service_hours=20.0, available_hours=100.0))
        t = am.technician_scorecard(fs, ftm)
        assert t.index.name == "technician_id"
        assert sorted(t.index) == ["T1", "T2"]  # unattributed work orders are dropped
        assert t.loc["T1", "jobs"] == 2
        assert t.loc["T1", "utilisation"] == pytest.approx(0.35)
        assert t.loc["T1", "utilisation_2026"] == pytest.approx(0.6)
        assert t.loc["T2", "skill_level"] == "Senior"

    def test_rework_cost(self):
        fs = fs_frame(dict(billing_type="Rework (No Charge)", labor_cost=100.0, parts_cost=50.0, actual_hours=2.0),
                      dict(billing_type="Rework (No Charge)", labor_cost=50.0, parts_cost=50.0, actual_hours=1.0),
                      dict())
        r = am.rework_cost(fs)
        assert r == {"rework_jobs": 2, "rework_cost": 250.0, "rework_avg_cost": 125.0,
                     "rework_labour_hours": 3.0, "rework_share_of_jobs": pytest.approx(2 / 3)}

    def test_rework_cost_with_no_rework(self):
        r = am.rework_cost(fs_frame(dict()))
        assert r["rework_jobs"] == 0 and r["rework_cost"] == 0.0
        assert math.isnan(r["rework_avg_cost"]) and r["rework_share_of_jobs"] == 0.0

    def test_rework_cost_on_empty_frame_divides_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            am.rework_cost(fs_frame().iloc[0:0])

    def test_overrun_drivers(self):
        fs = fs_frame(
            dict(additional_work_found=True, cost_overrun_flag=True, cost_variance_pct=0.30, revenue=400.0,
                 labor_cost=100.0, parts_cost=100.0, rating=3.0),
            dict(additional_work_found=True, cost_overrun_flag=False, cost_variance_pct=0.10, revenue=400.0,
                 labor_cost=100.0, parts_cost=100.0, rating=3.0),
            dict(additional_work_found=False, revenue=500.0, labor_cost=100.0, parts_cost=100.0, rating=5.0),
            dict(additional_work_found=False, revenue=500.0, labor_cost=100.0, parts_cost=100.0, rating=5.0),
        )
        od = am.overrun_drivers(fs)
        assert "margin_profit" not in od.columns
        yes, no = od.loc[True], od.loc[False]
        assert yes["jobs"] == 2 and yes["overrun"] == 0.5 and yes["cost_var_pct_median"] == pytest.approx(0.20)
        assert yes["margin"] == pytest.approx(400 / 800) and no["margin"] == pytest.approx(600 / 1000)
        assert yes["share_of_jobs"] == 0.5 and no["share_of_jobs"] == 0.5
        assert yes["csat"] == 3.0 and no["csat"] == 5.0


# --------------------------------------------------------------------------- #
# Statistical helpers and tests
# --------------------------------------------------------------------------- #
class TestCramersV:
    def test_known_2x2_value(self):
        chi2, p, dof, v = am._cramers_v(pd.DataFrame([[10, 20], [20, 10]]))
        assert chi2 == pytest.approx(5.4)  # Yates-corrected: 4 * (4.5**2) / 15
        assert dof == 1 and 0 < p < 0.05
        assert v == pytest.approx(math.sqrt(5.4 / 60)) == pytest.approx(0.3)

    def test_independent_table_has_zero_effect(self):
        chi2, p, dof, v = am._cramers_v(pd.DataFrame([[10, 20], [10, 20]]))
        assert chi2 == 0.0 and v == 0.0 and p == 1.0

    def test_rxc_table_uses_min_dim_minus_one(self):
        table = pd.DataFrame([[30, 10, 5], [10, 30, 5]])
        chi2, p, dof, v = am._cramers_v(table)
        assert dof == 2
        n = table.to_numpy().sum()
        assert v == pytest.approx(math.sqrt(chi2 / (n * 1)))

    def test_returns_plain_python_types(self):
        out = am._cramers_v(pd.DataFrame([[5, 9], [8, 3]]))
        assert [type(x) for x in out] == [float, float, int, float]

    def test_degenerate_single_row_table_gives_nan_effect_size(self):
        with np.errstate(all="ignore"):
            chi2, p, dof, v = am._cramers_v(pd.DataFrame([[5, 9]]))
        assert dof == 0 and math.isnan(v)


class TestStatisticalTests:
    EXPECTED_KEYS = {
        "kruskal_turnaround_by_centre", "kruskal_wait_by_centre", "mannwhitney_wait_focus_vs_rest",
        "chi2_on_time_by_centre", "chi2_on_time_vs_parts_delay", "on_time_gap_focus_vs_benchmark",
        "spearman_rating_vs_late_hours", "spearman_rating_vs_wait_hours", "spearman_daily_load_vs_wait",
        "spearman_daily_load_vs_on_time", "chi2_cancellation_vs_lead_band", "spearman_lead_days_vs_cancel_booked",
        "chi2_qc_vs_skill", "chi2_overrun_vs_skill", "chi2_on_time_saturday_vs_weekday",
    }

    @pytest.fixture
    def tests_out(self, ds, synth_load):
        return am.statistical_tests(ds["fact_service"], ds["fact_appointments"], synth_load[0])

    def test_keys_and_ranges(self, tests_out):
        assert set(tests_out) == self.EXPECTED_KEYS
        for name, t in tests_out.items():
            if "p" in t:
                assert 0.0 <= t["p"] <= 1.0, name
            if "cramers_v" in t:
                assert 0.0 <= t["cramers_v"] <= 1.0, name
            if "rho" in t:
                assert -1.0 <= t["rho"] <= 1.0, name
        json.dumps(tests_out)

    def test_kruskal_sample_size_and_effect_size(self, tests_out, ds):
        k = tests_out["kruskal_turnaround_by_centre"]
        assert k["n"] == len(ds["fact_service"])
        assert k["epsilon_sq"] == pytest.approx(k["H"] / (k["n"] - 1))

    def test_on_time_gap_matches_manual_calculation(self, tests_out, ds):
        fs = ds["fact_service"]
        p1 = fs.loc[fs["center_id"] == "C006", "on_time_flag"].mean()
        p2 = fs.loc[fs["center_id"] == "C005", "on_time_flag"].mean()
        n1, n2 = (fs["center_id"] == "C006").sum(), (fs["center_id"] == "C005").sum()
        g = tests_out["on_time_gap_focus_vs_benchmark"]
        se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        assert g["focus_rate"] == pytest.approx(p1) and g["benchmark_rate"] == pytest.approx(p2)
        assert g["gap"] == pytest.approx(p1 - p2)
        assert g["ci95_low"] == pytest.approx(p1 - p2 - 1.96 * se)
        assert g["ci95_high"] == pytest.approx(p1 - p2 + 1.96 * se)
        assert g["ci95_low"] < g["gap"] < g["ci95_high"]
        assert g["cohens_h"] == pytest.approx(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))
        assert (g["focus"], g["benchmark"]) == ("C006", "C005")

    def test_custom_focus_and_benchmark_centres(self, ds, synth_load):
        out = am.statistical_tests(ds["fact_service"], ds["fact_appointments"], synth_load[0],
                                   focus_centre="C001", benchmark_centre="C002")
        assert out["on_time_gap_focus_vs_benchmark"]["focus"] == "C001"
        assert out["mannwhitney_wait_focus_vs_rest"]["centre"] == "C001"

    def test_rank_biserial_is_plus_one_when_focus_always_waits_longer(self, ds, synth_load):
        fs = ds["fact_service"]
        fs.loc[fs["center_id"] == "C006", "wait_hours"] = 1000.0
        out = am.statistical_tests(fs, ds["fact_appointments"], synth_load[0])
        mw = out["mannwhitney_wait_focus_vs_rest"]
        assert mw["rank_biserial"] == pytest.approx(1.0)
        assert mw["median_focus_h"] == 1000.0 and mw["median_rest_h"] < 1000.0
        assert mw["p"] < 0.001

    def test_rank_biserial_is_minus_one_when_focus_always_waits_less(self, ds, synth_load):
        fs = ds["fact_service"]
        fs.loc[fs["center_id"] == "C006", "wait_hours"] = -1.0
        out = am.statistical_tests(fs, ds["fact_appointments"], synth_load[0])
        assert out["mannwhitney_wait_focus_vs_rest"]["rank_biserial"] == pytest.approx(-1.0)

    def test_nan_wait_and_rating_rows_are_ignored(self, ds, synth_load):
        fs = ds["fact_service"]
        fs.loc[fs.index[:50], "wait_hours"] = np.nan
        out = am.statistical_tests(fs, ds["fact_appointments"], synth_load[0])
        assert out["kruskal_wait_by_centre"]["n"] == len(fs) - 50

    @pytest.mark.filterwarnings("ignore:One or more sample arguments is too small")
    def test_missing_focus_centre_fails_loudly(self, ds, synth_load):
        with pytest.raises((ValueError, ZeroDivisionError)):
            am.statistical_tests(ds["fact_service"], ds["fact_appointments"], synth_load[0], focus_centre="C999")

    def test_spearman_daily_load_n_counts_all_days(self, tests_out, synth_load):
        assert tests_out["spearman_daily_load_vs_wait"]["n"] == len(synth_load[0])


# --------------------------------------------------------------------------- #
# What-if models
# --------------------------------------------------------------------------- #
def _with_band(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["load_band"] = pd.cut(df["load_ratio"], am.LOAD_BANDS, right=True)
    return df


class TestCurveLookup:
    def test_on_time_curve_lists_every_band_with_nan_for_empty(self):
        fl = _with_band(fs_frame(dict(on_time_flag=True), dict(on_time_flag=False), dict(on_time_flag=True))
                        .assign(load_ratio=[0.5, 0.55, 0.95]))
        curve = am.on_time_curve(fl)
        assert len(curve) == len(am.LOAD_BANDS) - 1
        assert curve.iloc[0] == 0.5 and curve.iloc[4] == 1.0
        assert curve.iloc[2:4].isna().all()

    def test_curve_lookup_maps_values_and_nan_outside_range(self):
        fl = _with_band(fs_frame(dict(on_time_flag=True), dict(on_time_flag=False)).assign(load_ratio=[0.5, 0.95]))
        curve = am.on_time_curve(fl)
        out = am._curve_lookup(curve, pd.Series([0.1, 0.6, 0.9, 0.95, 1.0, 0.0, np.nan, -1.0]))
        assert out.iloc[0] == 1.0 and out.iloc[1] == 1.0       # 0.6 is the right edge of (0, 0.6]
        assert math.isnan(out.iloc[2])                          # (0.8, 0.9] was never observed
        assert out.iloc[3] == 0.0 and out.iloc[4] == 0.0        # 1.0 is the right edge of (0.9, 1.0]
        assert out.iloc[5:].isna().all()
        assert out.dtype == float


class TestWhatIfAddTechnician:
    @pytest.fixture
    def inputs(self):
        fl = fs_frame(
            dict(center_id="C001", on_time_flag=True, service_date="2026-01-05"),
            dict(center_id="C001", on_time_flag=False, service_date="2026-01-05"),
            *[dict(center_id="C002", on_time_flag=True, service_date=f"2025-02-{3 + i:02d}") for i in range(4)],
        )
        fl["load_ratio"] = [1.2, 1.2, 0.75, 0.75, 0.75, 0.75]
        fl = _with_band(fl)
        ftm = ftm_frame(dict(service_hours=70.0, available_hours=100.0),
                        dict(month="2025-01", service_hours=1.0, available_hours=1.0))
        techs = techs_frame([("T1", "C001", "Mid"), ("T2", "C001", "Mid"), ("T3", "C002", "Mid")])
        return fl, ftm, techs

    def test_known_values(self, inputs):
        r = am.what_if_add_technician(*inputs, center_id="C001")
        assert r["technicians_now"] == 2 and r["technicians_new"] == 3
        assert r["jobs_per_month"] == 2.0
        assert r["utilisation_now"] == pytest.approx(0.7)  # 2025-01 row excluded
        assert r["utilisation_projected"] == pytest.approx(0.7 * 2 / 3)
        assert r["overloaded_day_share_now"] == 1.0 and r["overloaded_day_share_projected"] == 0.0
        # curve: (1.1,1.2] -> 0.5 ; (0.7,0.8] -> 1.0 ; delta = +0.5 for both jobs
        assert r["on_time_now"] == 0.5
        assert r["on_time_delta_pts"] == pytest.approx(0.5)
        assert r["on_time_projected"] == pytest.approx(1.0)
        assert r["extra_on_time_jobs_per_month"] == pytest.approx(1.0)

    def test_projected_on_time_is_capped_at_one(self, inputs):
        fl, ftm, techs = inputs
        # C001 is already 100% on time, but the network curve at its current load is poor (0.25)
        fl["on_time_flag"] = [True, True, True, True, True, True]
        extra = fs_frame(*[dict(center_id="C002", on_time_flag=False, service_date="2025-03-03")] * 6)
        extra["load_ratio"] = 1.2
        fl = _with_band(pd.concat([fl, extra], ignore_index=True))
        r = am.what_if_add_technician(fl, ftm, techs, "C001")
        assert r["on_time_delta_pts"] == pytest.approx(0.75)
        assert r["on_time_now"] == 1.0 and r["on_time_projected"] == 1.0

    def test_more_technicians_lowers_utilisation_proportionally(self, inputs):
        r1 = am.what_if_add_technician(*inputs, center_id="C001", extra_techs=1)
        r2 = am.what_if_add_technician(*inputs, center_id="C001", extra_techs=2)
        assert r2["utilisation_projected"] < r1["utilisation_projected"] < r1["utilisation_now"]

    def test_zero_extra_technicians_changes_nothing(self, inputs):
        r = am.what_if_add_technician(*inputs, center_id="C001", extra_techs=0)
        assert r["on_time_delta_pts"] == 0.0
        assert r["utilisation_projected"] == pytest.approx(r["utilisation_now"])
        assert r["on_time_projected"] == r["on_time_now"]

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_unknown_centre_has_no_months_and_fails_loudly(self, inputs):
        fl, ftm, techs = inputs
        with pytest.raises(ZeroDivisionError):
            am.what_if_add_technician(fl, ftm, techs, "C999")


class TestWhatIfSaturdayCapacity:
    @pytest.fixture
    def fl(self):
        fl = fs_frame(
            dict(service_date="2026-01-03", on_time_flag=True, wait_hours=1.0),
            dict(service_date="2026-01-03", on_time_flag=False, wait_hours=3.0),
            dict(service_date="2026-01-05", on_time_flag=True),   # Monday, sets the (0.9, 1.0] level
            dict(service_date="2026-01-10", center_id="C002", on_time_flag=False),  # centre not selected
        )
        assert fl.loc[0, "weekday"] == "Saturday"
        fl["load_ratio"] = [1.2, 1.2, 0.95, 1.2]
        return _with_band(fl)

    def test_known_values(self, fl):
        r = am.what_if_saturday_capacity(fl, ["C001"], extra_hours_per_tech=2.0)
        # scale 7/9: load 1.2 -> 0.933 (band (0.9,1.0] = 1.0 on-time); old band (1.1,1.2] = (1+0+0)/3? see below
        old = fl.loc[fl["load_band"].astype(str) == "(1.1, 1.2]", "on_time_flag"].mean()
        delta = 1.0 - old
        assert r["centres"] == "C001" and r["extra_hours_per_tech"] == 2.0
        assert r["saturday_jobs_per_month"] == 2.0
        assert r["saturday_on_time_now"] == 0.5
        assert r["saturday_on_time_projected"] == pytest.approx(0.5 + delta)
        assert r["extra_on_time_jobs_per_month"] == pytest.approx(2 * delta)
        assert r["saturday_wait_now_h"] == 2.0
        assert r["saturdays_per_month"] == 1.0

    def test_zero_overtime_leaves_projection_unchanged(self, fl):
        small = am.what_if_saturday_capacity(fl, ["C001"], extra_hours_per_tech=0.0)
        assert small["saturday_on_time_projected"] == pytest.approx(small["saturday_on_time_now"])

    def test_multiple_centres_joined_in_label(self, fl):
        r = am.what_if_saturday_capacity(fl, ["C001", "C002"])
        assert r["centres"] == "C001,C002"
        assert r["saturday_jobs_per_month"] == 3.0

    def test_no_saturday_rows_gives_nan_not_crash(self, fl):
        with np.errstate(all="ignore"):
            r = am.what_if_saturday_capacity(fl, ["C003"])
        assert r["saturday_jobs_per_month"] == 0.0
        assert math.isnan(r["saturday_on_time_now"])


class TestWhatIfSaturdayShift:
    @pytest.fixture
    def fl(self):
        rows = [
            # Saturday: booked 6.0h + walk-in 0.2h on a day with 10h capacity -> load 0.62
            dict(service_date="2026-01-03", booking_channel="Ather App", estimated_hours=6.0, on_time_flag=False),
            dict(service_date="2026-01-03", booking_channel="Walk-in", estimated_hours=0.2, on_time_flag=True),
            # receiving Tue/Wed/Thu (3, 4, 5 days later), capacity 10h, load 0.1
            dict(service_date="2026-01-06", estimated_hours=1.0, on_time_flag=True),
            dict(service_date="2026-01-07", estimated_hours=1.0, on_time_flag=True),
            dict(service_date="2026-01-08", estimated_hours=1.0, on_time_flag=True),
        ]
        fl = fs_frame(*rows)
        fl["load_ratio"] = [0.62, 0.62, 0.1, 0.1, 0.1]
        return _with_band(fl)

    def test_known_values(self, fl):
        r = am.what_if_saturday_shift(fl, fl, shift_share=0.15)
        # Saturday load 0.62 -> (6.2 - 0.9)/10 = 0.53 : moves from band (0.6,0.7] (0.5 on-time) to (0,0.6] (1.0)
        assert r["shift_share_of_booked_saturday_hours"] == 0.15
        assert r["saturday_on_time_now"] == 0.5
        assert r["saturday_on_time_projected"] == pytest.approx(1.0)
        assert r["tue_thu_on_time_now"] == 1.0 and r["tue_thu_on_time_projected"] == pytest.approx(1.0)
        assert r["network_on_time_now"] == pytest.approx(0.8)
        assert r["network_on_time_projected"] == pytest.approx(1.0)
        assert r["extra_on_time_jobs_per_month"] == pytest.approx(1.0)
        assert r["booked_share_of_saturday_hours"] == pytest.approx(6.0 / 6.2)

    def test_zero_shift_changes_nothing(self, fl):
        r = am.what_if_saturday_shift(fl, fl, shift_share=0.0)
        assert r["network_on_time_projected"] == pytest.approx(r["network_on_time_now"])
        assert r["extra_on_time_jobs_per_month"] == pytest.approx(0.0)

    def test_year_with_no_data_gives_nan_projection(self, fl):
        with np.errstate(all="ignore"):
            r = am.what_if_saturday_shift(fl, fl, year=2025)
        assert math.isnan(r["network_on_time_now"]) and math.isnan(r["extra_on_time_jobs_per_month"])

    def test_unobserved_target_band_leaves_projection_undefined(self, fl):
        # only Saturday rows: the (0, 0.6] band the shifted load falls into has no network observations
        r = am.what_if_saturday_shift(fl.iloc[:2], fl.iloc[:2], shift_share=0.15)
        assert r["saturday_on_time_now"] == 0.5
        assert math.isnan(r["saturday_on_time_projected"])


# --------------------------------------------------------------------------- #
# Impact estimates
# --------------------------------------------------------------------------- #
class TestTechnicianMonthlyCost:
    def test_known_value(self):
        techs = techs_frame([("T1", "C001", "Mid", 200.0, 8), ("T2", "C001", "Senior", 400.0, 8)])
        ftm = ftm_frame(dict(month="2026-01", working_days=26), dict(technician_id="T2", month="2026-01", working_days=26),
                        dict(month="2026-02", working_days=24))
        assert am.technician_monthly_cost(techs, ftm, "Mid") == pytest.approx(200 * 8 * 25)
        assert am.technician_monthly_cost(techs, ftm, "Senior") == pytest.approx(400 * 8 * 25)

    def test_unknown_skill_raises(self):
        with pytest.raises(IndexError):
            am.technician_monthly_cost(techs_frame([("T1", "C001", "Mid")]), ftm_frame(), "Master")

    def test_returns_float(self):
        out = am.technician_monthly_cost(techs_frame([("T1", "C001", "Mid")]), ftm_frame(), "Mid")
        assert type(out) is float


@pytest.fixture(scope="module")
def impact(_synth_cache):
    d = _copy(_synth_cache)
    daily = am.daily_load(d["fact_service"], d["technicians"])
    fs_load = am.attach_load(d["fact_service"], daily)
    lines = am.parts_lines(d["fact_service"], d["part_usage"], d["parts"])
    return am.impact_estimates(d, fs_load, lines), d


class TestImpactEstimates:
    def test_sections_present(self, impact):
        out, _ = impact
        assert set(out) == {
            "what_if_C006_plus1", "what_if_C003_plus1", "what_if_C007_plus1", "technician_monthly_cost_mid",
            "technician_monthly_cost_senior", "mumbai_cancellation_recovery", "mumbai_context",
            "what_if_saturday_shift_15pct", "what_if_saturday_overtime_hot_centres", "kolkata_parts",
            "skill_uplift", "booking_window", "estimate_approval"}

    def test_json_serialisable(self, impact):
        json.dumps(impact[0], default=str)

    def test_what_if_projections_are_internally_consistent(self, impact):
        for key in ("what_if_C006_plus1", "what_if_C003_plus1", "what_if_C007_plus1"):
            w = impact[0][key]
            assert w["technicians_new"] == w["technicians_now"] + 1
            assert w["utilisation_projected"] < w["utilisation_now"]
            assert w["on_time_projected"] <= 1.0
            assert w["extra_on_time_jobs_per_month"] == pytest.approx(w["on_time_delta_pts"] * w["jobs_per_month"])
            assert w["overloaded_day_share_projected"] <= w["overloaded_day_share_now"]

    def test_mumbai_recovery_arithmetic(self, impact):
        out, d = impact
        m = out["mumbai_cancellation_recovery"]
        a26 = d["fact_appointments"][d["fact_appointments"]["year"] == 2026]
        canc = a26.groupby("center_id")["is_cancelled"].mean()
        assert m["mumbai_cancel_rate_2026"] == pytest.approx(canc["C006"])
        assert m["other_centres_median_2026"] == pytest.approx(canc.drop("C006").median())
        expected = (m["mumbai_cancel_rate_2026"] - m["other_centres_median_2026"]) * m["appointments_per_month"] \
            * m["completion_rate"]
        assert m["recovered_jobs_per_month"] == pytest.approx(expected)
        assert m["recovered_revenue_per_month"] == pytest.approx(m["recovered_jobs_per_month"] * m["revenue_per_job"])
        assert m["recovered_profit_per_month"] == pytest.approx(m["recovered_jobs_per_month"] * m["profit_per_job"])
        assert m["recovered_jobs_per_month"] > 0  # synthetic C006 cancels more than the rest

    def test_mumbai_context(self, impact):
        out, d = impact
        c = out["mumbai_context"]
        fs = d["fact_service"]
        m26 = fs[(fs["center_id"] == "C006") & (fs["year"] == 2026)]
        assert c["jobs_jan_sep_2026"] == len(m26)
        assert c["profit_per_month_2026"] == pytest.approx(m26["profit"].sum() / 9)
        assert c["jobs_yoy_growth"] == pytest.approx(c["jobs_jan_sep_2026"] / c["jobs_jan_sep_2025"] - 1)

    def test_kolkata_parts(self, impact):
        out, _ = impact
        k = out["kolkata_parts"]
        assert k["parts_delay_rate_2026"] > k["other_centres_median_2026"]
        assert k["avoided_delayed_jobs_per_month"] > 0
        assert k["safety_stock_parts"] >= 1
        assert k["safety_stock_carrying_cost_pa_at_20pct"] == pytest.approx(k["safety_stock_value"] * 0.2)
        assert k["tat_gap_delayed_vs_not_h"] > 0

    def test_skill_uplift(self, impact):
        out, d = impact
        s = out["skill_uplift"]
        assert s["junior_comeback"] > s["mid_comeback"]
        assert s["avoided_comebacks_per_month"] == pytest.approx(
            (s["junior_comeback"] - s["mid_comeback"]) * s["junior_jobs_per_month"])
        assert s["rework_cost_avoided_per_month"] == pytest.approx(
            s["avoided_comebacks_per_month"] * s["rework_avg_cost"])
        assert s["avoided_qc_failures_per_month"] == pytest.approx(
            (s["mid_qc"] - s["junior_qc"]) * s["junior_jobs_per_month"])

    def test_booking_window(self, impact):
        out, _ = impact
        b = out["booking_window"]
        assert b["long_lead_cancel_rate"] is not None
        assert b["recovered_jobs_per_month"] == pytest.approx(
            (b["long_lead_cancel_rate"] - b["target_rate_4_7_days"]) * b["long_lead_appointments_per_month"]
            * impact[1]["fact_appointments"].query("year == 2026")["is_completed"].mean())
        assert 0 <= b["network_long_lead_share"] <= 1 and 0 <= b["mumbai_long_lead_share"] <= 1

    def test_estimate_approval(self, impact):
        e = impact[0]["estimate_approval"]
        assert 0 < e["additional_work_share"] < 1
        assert 0 <= e["overrun_rate_without"] <= 1 and 0 <= e["overrun_rate_with_additional_work"] <= 1

    def test_saturday_overtime_cost_uses_hot_centre_payroll_at_2x(self, impact):
        out, d = impact
        s = out["what_if_saturday_overtime_hot_centres"]
        techs = d["technicians"]
        hot = techs[techs["center_id"].isin(["C001", "C003", "C006", "C007"])]
        assert s["centres"] == "C001,C003,C006,C007"
        assert s["overtime_cost_per_month_at_2x"] == pytest.approx(
            hot["hourly_cost"].sum() * 2.0 * 2 * s["saturdays_per_month"])

    def test_monthly_cost_ordering(self, impact):
        out, _ = impact
        assert out["technician_monthly_cost_senior"] > out["technician_monthly_cost_mid"] > 0


# --------------------------------------------------------------------------- #
# Scorecards on the synthetic dataset
# --------------------------------------------------------------------------- #
class TestSyntheticScorecards:
    def test_centre_scorecard_full(self, ds):
        sc = am.centre_scorecard(ds["fact_service"], ds["fact_appointments"], ds["fact_technician_month"],
                                 ds["technicians"])
        assert list(sc.index) == CENTRES
        assert sc["jobs"].sum() == len(ds["fact_service"])
        assert sc["technicians"].sum() == len(ds["technicians"])
        assert sc.loc["C001", "senior_or_master_techs"] == 2
        assert (sc.drop(index="C001")["senior_or_master_techs"] == 1).all()
        for col in ("on_time", "junior_job_share", "complex_job_share", "periodic_share", "utilisation"):
            assert sc[col].between(0, 1.5).all(), col
        assert sc["appointments"].sum() == len(ds["fact_appointments"])

    def test_scorecard_totals_reconcile_with_headline(self, ds):
        fs = ds["fact_service"]
        h = am.headline_kpis(fs, ds["fact_appointments"], ds["fact_technician_month"])
        for by in ("center_id", "service_type", "month", "model"):
            sc = am.service_scorecard(fs, by)
            assert sc["jobs"].sum() == h["work_orders"]
            assert sc["revenue"].sum() == pytest.approx(h["revenue"])
            assert sc["profit"].sum() == pytest.approx(h["profit"])

    def test_daily_load_conserves_booked_hours(self, ds, synth_load):
        daily, fs_load = synth_load
        assert daily["booked_hours"].sum() == pytest.approx(ds["fact_service"]["estimated_hours"].sum())
        assert daily["jobs"].sum() == len(ds["fact_service"])
        assert len(fs_load) == len(ds["fact_service"])  # attach_load must not duplicate rows
        assert fs_load["load_ratio"].notna().all()

    def test_load_band_profile_covers_all_jobs(self, synth_load):
        _, fs_load = synth_load
        p = am.load_band_profile(fs_load)
        assert p["jobs"].sum() == fs_load["load_band"].notna().sum()


# --------------------------------------------------------------------------- #
# Orchestration: load_cleaned, compute_all, summary, main
# --------------------------------------------------------------------------- #
class TestLoadCleaned:
    @pytest.fixture
    def clean_dir(self, tmp_path, _synth_cache):
        d = _copy(_synth_cache)
        # keep the fixture small
        keep = d["fact_service"].head(60)
        d["fact_service"] = keep
        d["fact_appointments"] = d["fact_appointments"].head(80)
        d["fact_technician_month"] = d["fact_technician_month"].head(40)
        for name, df in d.items():
            df.to_csv(tmp_path / f"{name}.csv", index=False)
        return tmp_path, d

    def test_returns_all_tables_with_derived_columns(self, clean_dir):
        path, src = clean_dir
        out = am.load_cleaned(path)
        assert set(out) == {"fact_service", "fact_appointments", "fact_technician_month", "technicians",
                            "service_centers", "parts", "part_usage", "feedback"}
        fs = out["fact_service"]
        assert len(fs) == 60
        assert pd.api.types.is_datetime64_any_dtype(fs["check_in_time"])
        assert pd.api.types.is_datetime64_any_dtype(fs["service_date"])
        assert (fs["weekday"] == fs["service_date"].dt.day_name()).all()
        assert (fs["month_num"] == fs["service_date"].dt.month).all()
        fa = out["fact_appointments"]
        assert (fa["year"] == fa["scheduled_date"].dt.year).all()
        assert pd.api.types.is_datetime64_any_dtype(out["feedback"]["feedback_date"])

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            am.load_cleaned(tmp_path)


class TestComputeAll:
    EXPECTED_KEYS = {
        "headline", "yoy_jan_sep", "centre_scorecard", "monthly_trend", "service_type_scorecard", "model_scorecard",
        "skill_profile", "skill_profile_complex_jobs", "technician_scorecard", "load_band_profile",
        "weekday_profile", "parts_delay_impact", "parts_delay_by_category", "parts_delay_category_centre",
        "abc_summary", "abc_a_class_parts", "cancellation_by_lead_band", "cancellation_by_channel",
        "cancellation_by_service_type", "cancellation_reasons_by_centre", "lead_band_mix_by_centre", "rework",
        "overnight_carry_over", "process_stage_metrics", "overrun_drivers", "feedback_categories",
        "statistical_tests", "impact"}

    def test_keys(self, synth_metrics):
        assert set(synth_metrics) == self.EXPECTED_KEYS

    def test_json_round_trip(self, synth_metrics):
        text = json.dumps(synth_metrics, default=str)
        assert json.loads(text).keys() == synth_metrics.keys()

    def test_headline_agrees_with_inputs(self, synth_metrics, _synth_cache):
        fs = _synth_cache["fact_service"]
        h = synth_metrics["headline"]
        assert h["work_orders"] == len(fs)
        assert h["on_time_rate"] == pytest.approx(fs["on_time_flag"].mean())
        assert h["revenue"] == pytest.approx(fs["revenue"].sum())
        assert h["cancellation_rate"] == pytest.approx(_synth_cache["fact_appointments"]["is_cancelled"].mean())

    def test_centre_scorecard_records(self, synth_metrics):
        recs = synth_metrics["centre_scorecard"]
        assert [r["center_id"] for r in recs] == CENTRES
        assert all("overloaded_day_share_2026" in r and "utilisation" in r for r in recs)
        assert all(0 <= r["overloaded_day_share"] <= 1 for r in recs)

    def test_abc_summary_shares_sum_to_one(self, synth_metrics):
        assert sum(r["value_share"] for r in synth_metrics["abc_summary"]) == pytest.approx(1.0)
        assert synth_metrics["abc_summary"][0]["abc_class"] == "A"

    def test_cancellation_by_lead_band_is_in_canonical_order(self, synth_metrics):
        assert [r["lead_time_band"] for r in synth_metrics["cancellation_by_lead_band"]] == am.LEAD_ORDER

    def test_yoy_structure(self, synth_metrics):
        y = synth_metrics["yoy_jan_sep"]
        assert set(y["jobs"]) == {"2025", "2026", "change", "pct_change"}

    def test_monthly_trend_covers_all_months(self, synth_metrics):
        assert len(synth_metrics["monthly_trend"]) == 21

    def test_feedback_categories_count_matches(self, synth_metrics, _synth_cache):
        assert sum(synth_metrics["feedback_categories"].values()) == len(_synth_cache["fact_service"])

    def test_does_not_mutate_inputs(self, _synth_cache):
        d = _copy(_synth_cache)
        before = {k: v.copy(deep=True) for k, v in d.items()}
        am.compute_all(d)
        for k in d:
            pd.testing.assert_frame_equal(d[k], before[k])

    def test_default_loads_from_disk(self, monkeypatch, _synth_cache):
        calls = []
        monkeypatch.setattr(am, "load_cleaned", lambda *a, **k: calls.append(1) or _copy(_synth_cache))
        out = am.compute_all()
        assert calls == [1] and "headline" in out


class TestMainAndSummary:
    @pytest.fixture
    def patched(self, monkeypatch, tmp_path, synth_metrics):
        reports = tmp_path / "reports"
        monkeypatch.setattr(am, "REPORTS_DIR", reports)
        monkeypatch.setattr(am, "METRICS_JSON", reports / "analysis_metrics.json")
        monkeypatch.setattr(am, "compute_all", lambda d=None: synth_metrics)
        return reports

    def test_main_writes_json_and_prints_summary(self, patched, capsys):
        assert not patched.exists()
        am.main()
        out = capsys.readouterr().out
        written = json.loads((patched / "analysis_metrics.json").read_text(encoding="utf-8"))
        assert set(written) == TestComputeAll.EXPECTED_KEYS
        assert "NETWORK HEADLINE KPIs" in out and "CENTRE SCORECARD" in out
        assert "STATISTICAL TESTS" in out and "IMPACT ESTIMATES" in out
        assert "Wrote reports" in out and "analysis_metrics.json" in out

    def test_main_overwrites_existing_file(self, patched):
        patched.mkdir(parents=True)
        (patched / "analysis_metrics.json").write_text("stale", encoding="utf-8")
        am.main()
        assert (patched / "analysis_metrics.json").read_text(encoding="utf-8") != "stale"

    def test_print_summary_formats_money_with_rupee_symbol(self, synth_metrics, capsys):
        am._print_summary(synth_metrics)
        out = capsys.readouterr().out
        assert RUPEE in out
        assert "YoY Jan-Sep 2025 vs 2026" in out
        assert "technician_monthly_cost_mid" in out  # non-dict impact entries are printed too

    def test_df_records_resets_index_and_serialises_nan_as_null(self):
        df = pd.DataFrame({"v": [1.0, np.nan]}, index=pd.Index(["a", "b"], name="k"))
        assert am._df_records(df) == [{"k": "a", "v": 1.0}, {"k": "b", "v": None}]

    def test_df_records_stringifies_unserialisable_values(self):
        df = pd.DataFrame({"v": [pd.Interval(0, 1)]})
        assert am._df_records(df)[0]["v"] is not None
