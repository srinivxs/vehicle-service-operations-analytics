"""Clean, validate, and enrich the raw service-operations extract.

Reads ``data/raw/*.csv``, applies the documented cleaning rules (DQ01-DQ20),
and writes:

* ``data/cleaned/<table>.csv``     - normalised tables ready for the SQL database
* ``data/cleaned/fact_service.csv`` - one row per work order with derived KPIs
* ``data/cleaned/fact_appointments.csv`` - one row per appointment
* ``data/cleaned/fact_technician_month.csv`` - technician utilisation by month
* ``data/cleaned/dim_date.csv``    - calendar dimension for Power BI
* ``reports/data_quality_report.md`` and ``reports/cleaning_log.csv``

Usage:
    python -m src.data_cleaning
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import (
    CLEAN_DIR,
    MAX_PLAUSIBLE_KM_PER_DAY,
    MODEL_FIRST_YEAR,
    PERIOD_END,
    PERIOD_START,
    PRODUCTIVE_HOURS_PER_DAY,
    RAW_DIR,
    REPEAT_VISIT_WINDOW_DAYS,
    REPORTS_DIR,
    WORKING_WEEKDAYS,
)

TABLES = (
    "customers", "vehicles", "service_centers", "technicians", "appointments",
    "work_orders", "parts", "part_usage", "financials", "feedback",
)
PRIMARY_KEYS = {
    "customers": "customer_id", "vehicles": "vehicle_id", "service_centers": "center_id",
    "technicians": "technician_id", "appointments": "appointment_id", "work_orders": "work_order_id",
    "parts": "part_id", "part_usage": "usage_id", "financials": "work_order_id", "feedback": "feedback_id",
}
DATETIME_COLS = {
    "appointments": ["booking_date", "scheduled_date"],
    "work_orders": ["check_in_time", "start_time", "end_time", "promised_ready_time"],
    "feedback": ["feedback_date"],
    "vehicles": ["purchase_date"],
    "customers": ["registration_date"],
}
CANONICAL_STATUS = {"completed": "Completed", "cancelled": "Cancelled", "canceled": "Cancelled",
                    "no-show": "No-Show", "no show": "No-Show", "noshow": "No-Show"}
CANONICAL_REGIONS = ("North", "South", "East", "West")
MODEL_ALIASES = {"ather 450x": "Ather 450X", "450x": "Ather 450X", "ather 450 apex": "Ather 450 Apex",
                 "450 apex": "Ather 450 Apex", "ather rizta": "Ather Rizta", "rizta": "Ather Rizta"}
REVENUE_SHIFT_RATIO = 10
REVENUE_SHIFT_FLOOR = 50_000


@dataclass
class CleaningLog:
    """Collects one entry per rule application so every change is auditable."""

    entries: list[dict] = field(default_factory=list)

    def add(self, rule: str, table: str, column: str, issue: str, action: str, rows: int) -> None:
        self.entries.append({"rule_id": rule, "table": table, "column": column, "issue": issue,
                             "action": action, "rows_affected": int(rows)})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.entries, columns=["rule_id", "table", "column", "issue", "action", "rows_affected"])


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def normalise_text(s: pd.Series) -> pd.Series:
    """Trim and collapse internal whitespace, keeping missing values missing."""
    return s.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)


def parse_datetime(s: pd.Series) -> pd.Series:
    """Parse ISO-8601 values, falling back to Indian DD/MM/YYYY entry format."""
    iso = pd.to_datetime(s, format="ISO8601", errors="coerce")
    fallback = pd.to_datetime(s.where(iso.isna()), format="%d/%m/%Y", errors="coerce")
    return iso.fillna(fallback)


def canonical_case(s: pd.Series, valid: list[str] | tuple[str, ...]) -> pd.Series:
    """Map case/whitespace variants onto a list of valid labels."""
    lookup = {v.lower(): v for v in valid}
    return normalise_text(s).str.lower().map(lookup)


def drop_exact_duplicates(df: pd.DataFrame, table: str, log: CleaningLog) -> pd.DataFrame:
    n = int(df.duplicated().sum())
    log.add("DQ01", table, "*", "Exact duplicate rows", "Removed", n)
    return df.drop_duplicates().reset_index(drop=True)


def drop_duplicate_keys(df: pd.DataFrame, table: str, log: CleaningLog) -> pd.DataFrame:
    key = PRIMARY_KEYS[table]
    n = int(df.duplicated(subset=key).sum())
    log.add("DQ02", table, key, "Duplicate primary key with conflicting values", "Kept first occurrence", n)
    return df.drop_duplicates(subset=key, keep="first").reset_index(drop=True)


def profile(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in raw.items():
        key = PRIMARY_KEYS[name]
        rows.append({"table": name, "raw_rows": len(df), "exact_duplicates": int(df.duplicated().sum()),
                     "duplicate_keys": int(df.duplicated(subset=key).sum()),
                     "null_cells": int(df.isna().sum().sum()),
                     "columns_with_nulls": ", ".join(f"{c} ({n})" for c, n in df.isna().sum().items() if n) or "-"})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Table-level cleaning
# --------------------------------------------------------------------------- #
def clean_customers(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "customers", log)
    before = df["region"].astype("string")
    df["region"] = canonical_case(df["region"], CANONICAL_REGIONS)
    log.add("DQ03", "customers", "region", "Case/whitespace variants", "Standardised to canonical region",
            int((before != df["region"]).sum()))
    df["customer_type"] = normalise_text(df["customer_type"])
    df["registration_date"] = parse_datetime(df["registration_date"]).dt.date
    return drop_duplicate_keys(df, "customers", log)


def clean_vehicles(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "vehicles", log)
    raw_model = df["model"].astype("string")
    df["model"] = normalise_text(raw_model).str.lower().map(MODEL_ALIASES)
    log.add("DQ03", "vehicles", "model", "Model name variants", "Mapped to canonical model name",
            int((raw_model != df["model"]).sum()))
    df["purchase_date"] = parse_datetime(df["purchase_date"])

    first_year = df["model"].map(MODEL_FIRST_YEAR)
    purchase_year = df["purchase_date"].dt.year
    bad_year = (df["model_year"] < first_year) | (df["model_year"] > purchase_year + 1) | (df["model_year"] > PERIOD_END.year)
    df.loc[bad_year, "model_year"] = purchase_year[bad_year]
    log.add("DQ15", "vehicles", "model_year", "Model year before model launch or after purchase",
            "Imputed from purchase_date year", int(bad_year.sum()))

    age_days = (pd.Timestamp(PERIOD_END) - df["purchase_date"]).dt.days.clip(lower=1)
    bad_km = (df["mileage_km"] < 0) | (df["mileage_km"] > age_days * MAX_PLAUSIBLE_KM_PER_DAY)
    df["mileage_km"] = df["mileage_km"].astype("Float64").mask(bad_km)
    log.add("DQ16", "vehicles", "mileage_km", f"Negative or > {MAX_PLAUSIBLE_KM_PER_DAY} km/day since purchase",
            "Set to null (excluded from mileage analysis)", int(bad_km.sum()))
    df["model_year"] = df["model_year"].astype("Int64")
    df["purchase_date"] = df["purchase_date"].dt.date
    return drop_duplicate_keys(df, "vehicles", log)


def clean_appointments(df: pd.DataFrame, vehicles: pd.DataFrame, raw_wo: pd.DataFrame,
                       technicians: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "appointments", log)
    raw_status = df["status"]
    df["status"] = normalise_text(df["status"]).str.lower().map(CANONICAL_STATUS)
    log.add("DQ20", "appointments", "status", "Status spelling/case variants", "Mapped to Completed/Cancelled/No-Show",
            int((raw_status != df["status"]).sum()))

    iso = pd.to_datetime(df["scheduled_date"], format="ISO8601", errors="coerce")
    df["scheduled_date"] = parse_datetime(df["scheduled_date"])
    log.add("DQ04", "appointments", "scheduled_date", "DD/MM/YYYY format mixed with ISO", "Parsed to ISO date",
            int((iso.isna() & df["scheduled_date"].notna()).sum()))
    df["booking_date"] = parse_datetime(df["booking_date"])

    out_of_range = ~df["scheduled_date"].between(pd.Timestamp(PERIOD_START), pd.Timestamp(PERIOD_END))
    log.add("DQ05", "appointments", "scheduled_date", "Unparseable or outside reporting period", "Removed",
            int(out_of_range.sum()))
    df = df[~out_of_range]
    bad_booking = df["booking_date"] > df["scheduled_date"]
    df.loc[bad_booking, "booking_date"] = df.loc[bad_booking, "scheduled_date"]
    log.add("DQ05", "appointments", "booking_date", "Booking after scheduled date", "Capped at scheduled date",
            int(bad_booking.sum()))

    orphan = ~df["vehicle_id"].isin(vehicles["vehicle_id"])
    log.add("DQ06", "appointments", "vehicle_id", "Vehicle not in vehicle master (orphan FK)", "Removed with dependent rows",
            int(orphan.sum()))
    df = df[~orphan].copy()

    missing_center = df["center_id"].isna()
    tech_centre = (raw_wo.dropna(subset=["technician_id"]).drop_duplicates("appointment_id")
                   .merge(technicians[["technician_id", "center_id"]], on="technician_id")
                   .set_index("appointment_id")["center_id"])
    df.loc[missing_center, "center_id"] = df.loc[missing_center, "appointment_id"].map(tech_centre)
    still_missing = df["center_id"].isna()
    log.add("DQ07", "appointments", "center_id", "Missing service centre",
            "Imputed from assigned technician's centre", int(missing_center.sum() - still_missing.sum()))
    log.add("DQ07", "appointments", "center_id", "Missing service centre with no technician to infer from",
            "Removed", int(still_missing.sum()))
    df = df[~still_missing]

    for col in ("booking_channel", "requested_service_type", "cancellation_reason"):
        df[col] = normalise_text(df[col])
    df["booking_date"] = df["booking_date"].dt.date
    df["scheduled_date"] = df["scheduled_date"].dt.date
    return drop_duplicate_keys(df, "appointments", log)


def clean_work_orders(df: pd.DataFrame, appointments: pd.DataFrame, technicians: pd.DataFrame,
                      service_types: list[str], log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "work_orders", log)
    raw_stype = df["service_type"]
    df["service_type"] = canonical_case(df["service_type"], service_types)
    log.add("DQ03", "work_orders", "service_type", "Case/whitespace variants", "Standardised to canonical service type",
            int((raw_stype != df["service_type"]).sum()))
    for col in DATETIME_COLS["work_orders"]:
        df[col] = parse_datetime(df[col])

    orphan = ~df["appointment_id"].isin(appointments["appointment_id"])
    log.add("DQ18", "work_orders", "appointment_id", "Parent appointment removed or missing", "Removed (cascade)",
            int(orphan.sum()))
    df = df[~orphan].copy()

    swapped = df["end_time"] < df["start_time"]
    df.loc[swapped, ["start_time", "end_time"]] = df.loc[swapped, ["end_time", "start_time"]].to_numpy()
    log.add("DQ08", "work_orders", "start_time/end_time", "End time earlier than start time",
            "Treated as transposed entry and swapped", int(swapped.sum()))

    log.add("DQ09", "work_orders", "start_time", "Missing start time",
            "Retained; wait_hours null and excluded from wait KPIs", int(df["start_time"].isna().sum()))

    invalid_tech = df["technician_id"].notna() & ~df["technician_id"].isin(technicians["technician_id"])
    missing_tech = df["technician_id"].isna()
    df.loc[invalid_tech, "technician_id"] = pd.NA
    log.add("DQ10", "work_orders", "technician_id", "Technician missing or not in technician master",
            "Set to null; kept for financial KPIs, excluded from technician KPIs",
            int(invalid_tech.sum() + missing_tech.sum()))
    for col in ("additional_work_found", "qc_passed_first_time"):
        df[col] = df[col].astype(str).str.strip().str.lower().map({"true": True, "false": False})
    return drop_duplicate_keys(df, "work_orders", log)


def clean_part_usage(df: pd.DataFrame, work_orders: pd.DataFrame, parts: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "part_usage", log)
    bad_qty = df["quantity"] <= 0
    log.add("DQ17", "part_usage", "quantity", "Zero or negative quantity", "Removed", int(bad_qty.sum()))
    df = df[~bad_qty]
    orphan_part = ~df["part_id"].isin(parts["part_id"])
    log.add("DQ17", "part_usage", "part_id", "Part not in parts master", "Removed", int(orphan_part.sum()))
    df = df[~orphan_part]
    orphan_wo = ~df["work_order_id"].isin(work_orders["work_order_id"])
    log.add("DQ18", "part_usage", "work_order_id", "Parent work order removed", "Removed (cascade)", int(orphan_wo.sum()))
    return drop_duplicate_keys(df[~orphan_wo], "part_usage", log)


def clean_financials(df: pd.DataFrame, work_orders: pd.DataFrame, part_usage: pd.DataFrame,
                     parts: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "financials", log)
    orphan = ~df["work_order_id"].isin(work_orders["work_order_id"])
    log.add("DQ18", "financials", "work_order_id", "Parent work order removed", "Removed (cascade)", int(orphan.sum()))
    df = df[~orphan].copy()

    for col in ("estimated_cost", "labor_cost", "parts_cost", "revenue"):
        neg = df[col] < 0
        df.loc[neg, col] = df.loc[neg, col].abs()
        log.add("DQ11", "financials", col, "Negative amount", "Sign-entry error: converted to absolute value",
                int(neg.sum()))

    missing = df["parts_cost"].isna()
    usage_cost = (part_usage.merge(parts[["part_id", "unit_cost"]], on="part_id")
                  .assign(line=lambda d: d["quantity"] * d["unit_cost"])
                  .groupby("work_order_id")["line"].sum())
    df.loc[missing, "parts_cost"] = df.loc[missing, "work_order_id"].map(usage_cost).fillna(0.0)
    log.add("DQ12", "financials", "parts_cost", "Missing parts cost", "Recomputed from part_usage x unit_cost",
            int(missing.sum()))

    cost = df["labor_cost"] + df["parts_cost"]
    shifted = (df["revenue"] > REVENUE_SHIFT_RATIO * cost) & (df["revenue"] > REVENUE_SHIFT_FLOOR)
    df.loc[shifted, "revenue"] = (df.loc[shifted, "revenue"] / 100).round(2)
    log.add("DQ13", "financials", "revenue", f"Revenue > {REVENUE_SHIFT_RATIO}x job cost and > INR {REVENUE_SHIFT_FLOOR:,}",
            "Decimal-place entry error: divided by 100", int(shifted.sum()))

    recon = df["work_order_id"].map(usage_cost).fillna(0.0)
    mismatch = (df["parts_cost"] - recon).abs() > 1
    log.add("DQ19", "financials", "parts_cost", "Parts cost differs from sum of part_usage lines",
            "Reported only; financials kept as billing system of record", int(mismatch.sum()))
    df["billing_type"] = normalise_text(df["billing_type"])
    return drop_duplicate_keys(df, "financials", log)


def clean_feedback(df: pd.DataFrame, work_orders: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = drop_exact_duplicates(df, "feedback", log)
    missing = df["rating"].isna()
    log.add("DQ14", "feedback", "rating", "Missing rating", "Removed", int(missing.sum()))
    df = df[~missing]
    out_of_range = ~df["rating"].between(1, 5)
    log.add("DQ14", "feedback", "rating", "Rating outside 1-5 scale", "Removed", int(out_of_range.sum()))
    df = df[~out_of_range].copy()
    df["rating"] = df["rating"].astype(int)
    orphan = ~df["work_order_id"].isin(work_orders["work_order_id"])
    log.add("DQ18", "feedback", "work_order_id", "Parent work order removed", "Removed (cascade)", int(orphan.sum()))
    df = df[~orphan]
    df["feedback_date"] = parse_datetime(df["feedback_date"]).dt.date
    df["feedback_category"] = normalise_text(df["feedback_category"])
    df = drop_duplicate_keys(df, "feedback", log)
    dup_wo = df.duplicated(subset="work_order_id")
    log.add("DQ02", "feedback", "work_order_id", "More than one feedback per work order", "Kept first", int(dup_wo.sum()))
    return df[~dup_wo]


# --------------------------------------------------------------------------- #
# Analytical outputs
# --------------------------------------------------------------------------- #
def working_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    days = pd.date_range(start, end, freq="D")
    return int(np.isin(days.weekday, WORKING_WEEKDAYS).sum())


def build_fact_service(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    wo = t["work_orders"]
    f = (wo.merge(t["appointments"][["appointment_id", "vehicle_id", "center_id", "booking_channel"]], on="appointment_id", how="left")
         .merge(t["vehicles"][["vehicle_id", "customer_id", "model", "variant", "vehicle_category", "purchase_date"]], on="vehicle_id", how="left")
         .merge(t["customers"][["customer_id", "customer_type"]], on="customer_id", how="left")
         .merge(t["service_centers"][["center_id", "center_name", "city", "region"]], on="center_id", how="left")
         .merge(t["technicians"][["technician_id", "skill_level"]], on="technician_id", how="left")
         .merge(t["financials"], on="work_order_id", how="left")
         .merge(t["feedback"][["work_order_id", "rating", "feedback_category"]], on="work_order_id", how="left"))

    hours = lambda a, b: (f[b] - f[a]).dt.total_seconds() / 3600  # noqa: E731
    f["service_date"] = f["check_in_time"].dt.normalize()
    f["year"] = f["service_date"].dt.year
    f["month"] = f["service_date"].dt.strftime("%Y-%m")
    f["wait_hours"] = hours("check_in_time", "start_time").round(2)
    f["turnaround_hours"] = hours("check_in_time", "end_time").round(2)
    f["late_hours"] = hours("promised_ready_time", "end_time").clip(lower=0).round(2)
    f["on_time_flag"] = f["end_time"] <= f["promised_ready_time"]
    f["duration_variance_hours"] = (f["actual_hours"] - f["estimated_hours"]).round(2)
    f["parts_delay_flag"] = f["parts_wait_hours"] > 0
    f["total_cost"] = (f["labor_cost"] + f["parts_cost"]).round(2)
    f["profit"] = (f["revenue"] - f["total_cost"]).round(2)
    f["cost_variance"] = (f["total_cost"] - f["estimated_cost"]).round(2)
    f["cost_variance_pct"] = (f["cost_variance"] / f["estimated_cost"].where(f["estimated_cost"] > 0)).round(4)
    f["cost_overrun_flag"] = f["cost_variance_pct"] > 0.10
    f["vehicle_age_years"] = ((f["service_date"] - pd.to_datetime(f["purchase_date"])).dt.days / 365.25).round(2)

    f = f.sort_values(["vehicle_id", "check_in_time"]).reset_index(drop=True)
    prev_same = f.groupby(["vehicle_id", "service_type"])["end_time"].shift()
    f["days_since_same_service"] = (f["check_in_time"] - prev_same).dt.days
    f["is_repeat_visit"] = f["days_since_same_service"].le(REPEAT_VISIT_WINDOW_DAYS).fillna(False)
    # Attribute the comeback to the original job (and its technician), not the return visit.
    next_same = f.groupby(["vehicle_id", "service_type"])["check_in_time"].shift(-1)
    f["caused_repeat_visit"] = ((next_same - f["end_time"]).dt.days <= REPEAT_VISIT_WINDOW_DAYS).fillna(False)
    f["customer_visit_number"] = f.sort_values("check_in_time").groupby("customer_id").cumcount() + 1
    f["service_date"] = f["service_date"].dt.date
    f = f.drop(columns=["purchase_date"]).sort_values("check_in_time").reset_index(drop=True)
    return f


def build_fact_appointments(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    a = (t["appointments"]
         .merge(t["vehicles"][["vehicle_id", "customer_id", "model", "vehicle_category"]], on="vehicle_id", how="left")
         .merge(t["customers"][["customer_id", "customer_type"]], on="customer_id", how="left")
         .merge(t["service_centers"][["center_id", "center_name", "region"]], on="center_id", how="left"))
    sched = pd.to_datetime(a["scheduled_date"])
    a["lead_days"] = (sched - pd.to_datetime(a["booking_date"])).dt.days
    a["lead_time_band"] = pd.cut(a["lead_days"], [-1, 0, 3, 7, 14, 999],
                                 labels=["Same day", "1-3 days", "4-7 days", "8-14 days", "15+ days"]).astype(str)
    a["weekday"] = sched.dt.day_name()
    a["month"] = sched.dt.strftime("%Y-%m")
    a["is_cancelled"] = a["status"].eq("Cancelled")
    a["is_no_show"] = a["status"].eq("No-Show")
    a["is_completed"] = a["status"].eq("Completed")
    return a


def build_fact_technician_month(t: dict[str, pd.DataFrame], fact: pd.DataFrame) -> pd.DataFrame:
    months = pd.period_range(PERIOD_START, PERIOD_END, freq="M")
    cal = pd.DataFrame({"month": months.strftime("%Y-%m"),
                        "working_days": [working_days(m.start_time, m.end_time) for m in months]})
    grid = t["technicians"][["technician_id", "center_id", "skill_level"]].merge(cal, how="cross")
    used = (fact.dropna(subset=["technician_id"]).groupby(["technician_id", "month"])
            .agg(jobs=("work_order_id", "size"), service_hours=("actual_hours", "sum"),
                 qc_first_pass=("qc_passed_first_time", "mean"), comebacks_caused=("caused_repeat_visit", "sum"))
            .reset_index())
    tm = grid.merge(used, on=["technician_id", "month"], how="left")
    tm[["jobs", "service_hours", "comebacks_caused"]] = tm[["jobs", "service_hours", "comebacks_caused"]].fillna(0)
    tm["available_hours"] = tm["working_days"] * PRODUCTIVE_HOURS_PER_DAY
    tm["utilisation"] = (tm["service_hours"] / tm["available_hours"]).round(4)
    tm["service_hours"] = tm["service_hours"].round(2)
    return tm


def build_dim_date() -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.date_range(PERIOD_START, PERIOD_END, freq="D")})
    d["year"] = d["date"].dt.year
    d["quarter"] = "Q" + d["date"].dt.quarter.astype(str)
    d["month_number"] = d["date"].dt.month
    d["month_name"] = d["date"].dt.strftime("%b")
    d["year_month"] = d["date"].dt.strftime("%Y-%m")
    d["weekday_number"] = d["date"].dt.weekday + 1
    d["weekday_name"] = d["date"].dt.day_name()
    d["is_working_day"] = d["date"].dt.weekday.isin(WORKING_WEEKDAYS)
    d["date"] = d["date"].dt.date
    return d


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def write_report(prof: pd.DataFrame, log: CleaningLog, clean: dict[str, pd.DataFrame], fact: pd.DataFrame) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_df = log.frame()
    log_df.to_csv(REPORTS_DIR / "cleaning_log.csv", index=False)
    summary = prof.assign(clean_rows=prof["table"].map({k: len(v) for k, v in clean.items()}))
    summary["rows_removed"] = summary["raw_rows"] - summary["clean_rows"]
    summary["pct_retained"] = (summary["clean_rows"] / summary["raw_rows"] * 100).round(2)
    summary.to_csv(REPORTS_DIR / "data_quality_summary.csv", index=False)

    def md(df: pd.DataFrame) -> str:
        cols = list(df.columns)
        lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
        lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
        return "\n".join(lines)

    checks = pd.DataFrame([
        {"check": "Work orders with end_time < start_time", "result": int((fact["end_time"] < fact["start_time"]).sum())},
        {"check": "Negative revenue or cost", "result": int((fact[["revenue", "labor_cost", "parts_cost"]] < 0).any(axis=1).sum())},
        {"check": "Ratings outside 1-5", "result": int((~fact["rating"].dropna().between(1, 5)).sum())},
        {"check": "Work orders without financials", "result": int(fact["revenue"].isna().sum())},
        {"check": "Work orders without centre", "result": int(fact["center_id"].isna().sum())},
        {"check": "Duplicate work_order_id", "result": int(fact["work_order_id"].duplicated().sum())},
    ])
    text = f"""# Data Quality Report

Generated by `src/data_cleaning.py`. Reporting period {PERIOD_START} to {PERIOD_END}.

## 1. Row counts, duplicates and nulls (raw -> cleaned)

{md(summary[["table", "raw_rows", "exact_duplicates", "duplicate_keys", "null_cells", "clean_rows", "rows_removed", "pct_retained"]])}

## 2. Cleaning rules applied

Every rule is logged with the rows it touched (`reports/cleaning_log.csv`). Rules with zero
affected rows were still executed and are shown for completeness.

{md(log_df)}

## 3. Post-cleaning validation (all should be 0)

{md(checks)}

## 4. Raw null profile by column

{md(prof[["table", "columns_with_nulls"]])}

## 5. Notes

* Work orders with a missing `start_time` (DQ09) are kept for financial and turnaround KPIs
  (turnaround is measured from check-in); their wait_hours is null and excluded from averages.
* Work orders with a null `technician_id` (DQ10) count towards centre and financial KPIs but
  not technician rankings or utilisation.
* Feedback rows removed under DQ14 reduce the rating sample only; the underlying work orders stay.
"""
    (REPORTS_DIR / "data_quality_report.md").write_text(text, encoding="utf-8")


def load_raw() -> dict[str, pd.DataFrame]:
    return {name: pd.read_csv(RAW_DIR / f"{name}.csv", dtype={"technician_id": "string"}) for name in TABLES}


def run(raw: dict[str, pd.DataFrame] | None = None, write: bool = True) -> dict[str, pd.DataFrame]:
    raw = raw if raw is not None else load_raw()
    log = CleaningLog()
    prof = profile(raw)
    c: dict[str, pd.DataFrame] = {}
    c["service_centers"] = raw["service_centers"].copy()
    c["technicians"] = raw["technicians"].copy()
    c["parts"] = raw["parts"].copy()
    c["customers"] = clean_customers(raw["customers"].copy(), log)
    c["vehicles"] = clean_vehicles(raw["vehicles"].copy(), log)
    c["appointments"] = clean_appointments(raw["appointments"].copy(), c["vehicles"], raw["work_orders"],
                                           c["technicians"], log)
    service_types = sorted(normalise_text(c["appointments"]["requested_service_type"]).dropna().unique())
    c["work_orders"] = clean_work_orders(raw["work_orders"].copy(), c["appointments"], c["technicians"], service_types, log)
    c["part_usage"] = clean_part_usage(raw["part_usage"].copy(), c["work_orders"], c["parts"], log)
    c["financials"] = clean_financials(raw["financials"].copy(), c["work_orders"], c["part_usage"], c["parts"], log)
    c["feedback"] = clean_feedback(raw["feedback"].copy(), c["work_orders"], log)

    fact = build_fact_service(c)
    outputs = {
        **c,
        "fact_service": fact,
        "fact_appointments": build_fact_appointments(c),
        "fact_technician_month": build_fact_technician_month(c, fact),
        "dim_date": build_dim_date(),
    }
    if write:
        CLEAN_DIR.mkdir(parents=True, exist_ok=True)
        for name, df in outputs.items():
            df.to_csv(CLEAN_DIR / f"{name}.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
        write_report(prof, log, c, fact)
    return outputs


def main() -> None:
    out = run()
    for name, df in out.items():
        print(f"{name:<24} {len(df):>7,}")


if __name__ == "__main__":
    main()
