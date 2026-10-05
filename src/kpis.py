"""Framework-free KPI calculations for the vehicle service analytics dashboard.

Every function takes plain pandas DataFrames and returns a dict / DataFrame, so
the same definitions can be unit-tested, reused in notebooks and mirrored in
Power BI DAX (see ``powerbi/dax_measures.md``).

Conventions
-----------
* Rates are returned as fractions in ``[0, 1]`` (format as % in the UI layer).
* Empty inputs never raise: sums are ``0`` and ratios / means are ``NaN``.
* ``Total Cost`` is always ``labor_cost + parts_cost`` and ``Profit`` is
  ``revenue - Total Cost``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd

NAN = float("nan")

WEEKDAY_ORDER: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
LEAD_TIME_ORDER: tuple[str, ...] = ("Same day", "1-3 days", "4-7 days", "8-14 days", "15+ days")
LATE_HOURS_EDGES: tuple[float, ...] = (0, 1, 2, 4, 8, 24)
TURNAROUND_EDGES: tuple[float, ...] = (2, 4, 8, 24, 72)
CSAT_THRESHOLD = 4
REPEAT_MIN_ORDERS = 2


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Filters:
    """Global slicer selection. An empty tuple / ``None`` means "no restriction"."""

    start: date | None = None
    end: date | None = None
    regions: tuple[str, ...] = ()
    centres: tuple[str, ...] = ()
    service_types: tuple[str, ...] = ()
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilterColumns:
    """Which column of a given table each slicer applies to (``None`` = not applicable)."""

    date_col: str
    date_is_month: bool = False
    region: str | None = "region"
    centre: str | None = "center_name"
    service_type: str | None = None
    model: str | None = None


FACT_COLUMNS = FilterColumns("service_date", False, "region", "center_name", "service_type", "model")
APPOINTMENT_COLUMNS = FilterColumns(
    "scheduled_date", False, "region", "center_name", "requested_service_type", "model"
)
TECH_MONTH_COLUMNS = FilterColumns("month", True, "region", "center_name", None, None)


def _date_mask(df: pd.DataFrame, cols: FilterColumns, flt: Filters) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    if flt.start is None and flt.end is None:
        return mask
    if cols.date_is_month:
        months = df[cols.date_col].astype(str)
        if flt.start is not None:
            mask &= months >= pd.Timestamp(flt.start).strftime("%Y-%m")
        if flt.end is not None:
            mask &= months <= pd.Timestamp(flt.end).strftime("%Y-%m")
        return mask
    dates = pd.to_datetime(df[cols.date_col])
    if flt.start is not None:
        mask &= dates >= pd.Timestamp(flt.start)
    if flt.end is not None:
        mask &= dates < pd.Timestamp(flt.end) + pd.Timedelta(days=1)
    return mask


def apply_filters(
    df: pd.DataFrame, filters: Filters, columns: FilterColumns = FACT_COLUMNS
) -> pd.DataFrame:
    """Return the rows of ``df`` that satisfy every active slicer.

    Date filtering is inclusive of both ``start`` and ``end``. For month-grain
    tables (``date_is_month``) a month is kept when it overlaps the date range.
    Slicers whose column is ``None`` for this table are ignored.
    """
    mask = _date_mask(df, columns, filters)
    selections = (
        (columns.region, filters.regions),
        (columns.centre, filters.centres),
        (columns.service_type, filters.service_types),
        (columns.model, filters.models),
    )
    for column, values in selections:
        if column is not None and values:
            mask &= df[column].isin(values)
    return df.loc[mask]


def enrich_technician_month(tech_month: pd.DataFrame, centers: pd.DataFrame) -> pd.DataFrame:
    """Attach ``center_name`` and ``region`` to the technician-month table."""
    return tech_month.merge(
        centers[["center_id", "center_name", "region"]], on="center_id", how="left"
    )


# --------------------------------------------------------------------------- #
# Scalar helpers
# --------------------------------------------------------------------------- #
def safe_ratio(numerator: float, denominator: float) -> float:
    """``numerator / denominator`` or ``NaN`` when the denominator is 0 / NaN."""
    if denominator is None or pd.isna(denominator) or denominator == 0:
        return NAN
    return float(numerator) / float(denominator)


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if series.notna().any() else NAN


def total_cost(fact: pd.DataFrame) -> float:
    """Total Cost = SUM(labor_cost + parts_cost)."""
    return float((fact["labor_cost"] + fact["parts_cost"]).sum())


def repeat_visit_rate(fact: pd.DataFrame) -> float:
    """Customers with >= 2 work orders / customers with >= 1 (within ``fact``)."""
    counts = fact["customer_id"].value_counts()
    return safe_ratio(int((counts >= REPEAT_MIN_ORDERS).sum()), len(counts))


def utilisation(tech_month: pd.DataFrame) -> float:
    """Technician utilisation = SUM(service_hours) / SUM(available_hours)."""
    return safe_ratio(tech_month["service_hours"].sum(), tech_month["available_hours"].sum())


def csat_share(ratings: pd.Series) -> float:
    """Share of rated work orders with a rating of 4 or more (NaN ratings ignored)."""
    rated = ratings.dropna()
    return safe_ratio(int((rated >= CSAT_THRESHOLD).sum()), len(rated))


# --------------------------------------------------------------------------- #
# Headline KPIs
# --------------------------------------------------------------------------- #
def fact_kpis(fact: pd.DataFrame) -> dict[str, float]:
    """All KPIs derivable from ``fact_service`` for the given (already filtered) rows."""
    revenue = float(fact["revenue"].sum())
    cost = total_cost(fact)
    orders = len(fact)
    return {
        "work_orders": orders,
        "revenue": revenue,
        "total_cost": cost,
        "labor_cost": float(fact["labor_cost"].sum()),
        "parts_cost": float(fact["parts_cost"].sum()),
        "profit": revenue - cost,
        "margin_pct": safe_ratio(revenue - cost, revenue),
        "parts_share": safe_ratio(float(fact["parts_cost"].sum()), cost),
        "avg_service_cost": safe_ratio(cost, orders),
        "on_time_pct": _mean(fact["on_time_flag"]),
        "avg_turnaround": _mean(fact["turnaround_hours"]),
        "median_turnaround": float(fact["turnaround_hours"].median()) if orders else NAN,
        "cost_variance": float(fact["cost_variance"].sum()),
        "cost_overrun_rate": _mean(fact["cost_overrun_flag"]),
        "avg_rating": _mean(fact["rating"]),
        "csat_pct": csat_share(fact["rating"]),
        "rated_orders": int(fact["rating"].notna().sum()),
        "repeat_visit_rate": repeat_visit_rate(fact),
        "comeback_rate": _mean(fact["caused_repeat_visit"]),
        "avg_duration_variance": _mean(fact["duration_variance_hours"]),
        "parts_delay_rate": _mean(fact["parts_delay_flag"]),
        "qc_first_pass_rate": _mean(fact["qc_passed_first_time"]),
        "avg_wait": _mean(fact["wait_hours"]),
    }


def appointment_kpis(appts: pd.DataFrame) -> dict[str, float]:
    """Cancellation and no-show rates over all appointments."""
    total = len(appts)
    return {
        "appointments": total,
        "cancellation_rate": safe_ratio(int(appts["is_cancelled"].sum()), total),
        "no_show_rate": safe_ratio(int(appts["is_no_show"].sum()), total),
    }


def headline_kpis(
    fact: pd.DataFrame, appts: pd.DataFrame, tech_month: pd.DataFrame
) -> dict[str, float]:
    """The 16 canonical KPIs (plus supporting counts) for the filtered data."""
    return {
        **fact_kpis(fact),
        **appointment_kpis(appts),
        "utilisation": utilisation(tech_month),
    }


# --------------------------------------------------------------------------- #
# Grouped KPIs
# --------------------------------------------------------------------------- #
def _as_keys(by: str | Sequence[str]) -> list[str]:
    return [by] if isinstance(by, str) else list(by)


def group_kpis(fact: pd.DataFrame, by: str | Sequence[str]) -> pd.DataFrame:
    """Work-order KPIs per group of ``by`` (one row per group, ``by`` as columns).

    Rows whose group key is missing are dropped. Rates are fractions.
    """
    keys = _as_keys(by)
    rated = fact["rating"].notna()
    work = fact.assign(
        _cost=fact["labor_cost"] + fact["parts_cost"],
        _csat=np.where(rated, (fact["rating"] >= CSAT_THRESHOLD).astype(float), np.nan),
    )
    out = work.groupby(keys, observed=True).agg(
        work_orders=("work_order_id", "count"),
        revenue=("revenue", "sum"),
        labor_cost=("labor_cost", "sum"),
        parts_cost=("parts_cost", "sum"),
        total_cost=("_cost", "sum"),
        cost_variance=("cost_variance", "sum"),
        avg_cost_variance_pct=("cost_variance_pct", "mean"),
        cost_overrun_rate=("cost_overrun_flag", "mean"),
        on_time_pct=("on_time_flag", "mean"),
        avg_turnaround=("turnaround_hours", "mean"),
        median_turnaround=("turnaround_hours", "median"),
        avg_wait=("wait_hours", "mean"),
        avg_est_hours=("estimated_hours", "mean"),
        avg_actual_hours=("actual_hours", "mean"),
        avg_duration_variance=("duration_variance_hours", "mean"),
        avg_rating=("rating", "mean"),
        csat_pct=("_csat", "mean"),
        rated_orders=("rating", "count"),
        comeback_rate=("caused_repeat_visit", "mean"),
        parts_delay_rate=("parts_delay_flag", "mean"),
        qc_first_pass_rate=("qc_passed_first_time", "mean"),
    )
    out = out.reset_index()
    out["profit"] = out["revenue"] - out["total_cost"]
    out["margin_pct"] = out["profit"] / out["revenue"].where(out["revenue"] != 0)
    out["avg_service_cost"] = out["total_cost"] / out["work_orders"].where(out["work_orders"] != 0)
    out["parts_share"] = out["parts_cost"] / out["total_cost"].where(out["total_cost"] != 0)
    return out.merge(_repeat_rate_by(fact, keys), on=keys, how="left")


def _repeat_rate_by(fact: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Repeat-visit rate per group: customers with >= 2 orders / customers."""
    per_customer = fact.groupby([*keys, "customer_id"], observed=True).size()
    flagged = (per_customer >= REPEAT_MIN_ORDERS).groupby(level=keys, observed=True).mean()
    return flagged.rename("repeat_visit_rate").reset_index()


def monthly_trend(fact: pd.DataFrame) -> pd.DataFrame:
    """KPIs per calendar month (``YYYY-MM``) with month-over-month revenue / profit change."""
    trend = group_kpis(fact, "month").sort_values("month").reset_index(drop=True)
    trend["revenue_mom_pct"] = trend["revenue"].pct_change(fill_method=None)
    trend["profit_mom_pct"] = trend["profit"].pct_change(fill_method=None)
    return trend


def service_type_performance(fact: pd.DataFrame) -> pd.DataFrame:
    """Volume, duration, delay, cost and satisfaction per service type (revenue-descending)."""
    return group_kpis(fact, "service_type").sort_values("revenue", ascending=False, ignore_index=True)


def appointment_rates_by(appts: pd.DataFrame, by: str | Sequence[str]) -> pd.DataFrame:
    """Appointments, cancellations, no-shows and their rates per group."""
    keys = _as_keys(by)
    out = (
        appts.groupby(keys, observed=True)
        .agg(
            appointments=("appointment_id", "count"),
            cancelled=("is_cancelled", "sum"),
            no_shows=("is_no_show", "sum"),
        )
        .reset_index()
    )
    out["cancellation_rate"] = out["cancelled"] / out["appointments"].where(out["appointments"] != 0)
    out["no_show_rate"] = out["no_shows"] / out["appointments"].where(out["appointments"] != 0)
    return out


def cancellation_by(
    appts: pd.DataFrame, by: str, order: Sequence[str] | None = None
) -> pd.DataFrame:
    """Cancellation / no-show rate per ``by``; ``order`` fixes the row order if given."""
    out = appointment_rates_by(appts, by)
    if order is not None:
        rank = {value: i for i, value in enumerate(order)}
        out = out.sort_values(by, key=lambda s: s.map(rank), ignore_index=True)
    return out


def cancellation_reasons(appts: pd.DataFrame) -> pd.DataFrame:
    """Cancelled appointments by recorded reason, most common first."""
    cancelled = appts.loc[appts["is_cancelled"] & appts["cancellation_reason"].notna()]
    counts = cancelled["cancellation_reason"].value_counts()
    out = counts.rename_axis("cancellation_reason").reset_index(name="cancellations")
    out["share"] = out["cancellations"] / out["cancellations"].sum() if len(out) else []
    return out


def centre_scorecard(
    fact: pd.DataFrame, appts: pd.DataFrame, tech_month: pd.DataFrame
) -> pd.DataFrame:
    """One row per service centre with the KPIs needed to rank performance.

    ``performance_score`` is the mean percentile rank (0-1, higher is better) of
    on-time %, average rating, margin %, turnaround (lower better) and
    cancellation rate (lower better); ``rank`` 1 is the best centre.
    """
    base = group_kpis(fact, ["center_name", "region"])
    cancel = appointment_rates_by(appts, "center_name")[
        ["center_name", "appointments", "cancellation_rate", "no_show_rate"]
    ]
    util = utilisation_by(tech_month, "center_name")[["center_name", "utilisation"]]
    card = base.merge(cancel, on="center_name", how="left").merge(util, on="center_name", how="left")
    ranks = pd.concat(
        [
            card["on_time_pct"].rank(pct=True),
            card["avg_rating"].rank(pct=True),
            card["margin_pct"].rank(pct=True),
            card["avg_turnaround"].rank(pct=True, ascending=False),
            card["cancellation_rate"].rank(pct=True, ascending=False),
        ],
        axis=1,
    )
    card["performance_score"] = ranks.mean(axis=1)
    card["rank"] = card["performance_score"].rank(ascending=False, method="min")
    return card.sort_values("rank", ignore_index=True)


def utilisation_by(tech_month: pd.DataFrame, by: str | Sequence[str]) -> pd.DataFrame:
    """Utilisation (SUM service hours / SUM available hours) per group."""
    keys = _as_keys(by)
    out = (
        tech_month.groupby(keys, observed=True)
        .agg(
            jobs=("jobs", "sum"),
            service_hours=("service_hours", "sum"),
            available_hours=("available_hours", "sum"),
        )
        .reset_index()
    )
    out["utilisation"] = out["service_hours"] / out["available_hours"].where(
        out["available_hours"] != 0
    )
    return out


def technician_scorecard(fact: pd.DataFrame, tech_month: pd.DataFrame) -> pd.DataFrame:
    """Per technician: workload and utilisation (technician-month) plus quality from work orders."""
    util = utilisation_by(tech_month, "technician_id")
    profile = tech_month.groupby("technician_id", as_index=False).agg(
        skill_level=("skill_level", "first"),
        center_name=("center_name", "first"),
        comebacks_caused=("comebacks_caused", "sum"),
    )
    quality = group_kpis(fact, "technician_id")[
        [
            "technician_id",
            "work_orders",
            "on_time_pct",
            "avg_rating",
            "qc_first_pass_rate",
            "comeback_rate",
            "avg_duration_variance",
        ]
    ]
    card = util.merge(profile, on="technician_id", how="left")
    return card.merge(quality, on="technician_id", how="left").sort_values(
        "utilisation", ascending=False, ignore_index=True
    )


def technician_utilisation_matrix(tech_month: pd.DataFrame) -> pd.DataFrame:
    """Technician (rows) x month (columns) utilisation matrix."""
    sums = tech_month.pivot_table(
        index="technician_id",
        columns="month",
        values=["service_hours", "available_hours"],
        aggfunc="sum",
    )
    if sums.empty:
        return pd.DataFrame()
    available = sums["available_hours"].where(sums["available_hours"] != 0)
    return sums["service_hours"] / available


# --------------------------------------------------------------------------- #
# Distributions
# --------------------------------------------------------------------------- #
def _band_labels(edges: Sequence[float], zero_label: str | None) -> list[str]:
    first = zero_label or f"<= {edges[0]:g}h"
    middle = [f"{lo:g}-{hi:g}h" for lo, hi in zip(edges[:-1], edges[1:])]
    return [first, *middle, f"> {edges[-1]:g}h"]


def delay_distribution(
    fact: pd.DataFrame,
    column: str = "late_hours",
    edges: Sequence[float] = LATE_HOURS_EDGES,
    zero_label: str | None = "On time",
) -> pd.DataFrame:
    """Work orders per band of ``column`` (hours); bands are right-closed.

    The first band is ``<= edges[0]`` (labelled ``zero_label`` for late hours,
    i.e. exactly on time), the last is ``> edges[-1]``.
    """
    labels = _band_labels(edges, zero_label)
    values = fact[column].dropna()
    bands = pd.cut(values, bins=[-np.inf, *edges, np.inf], labels=labels, right=True)
    counts = bands.value_counts().reindex(labels, fill_value=0)
    out = counts.rename_axis("band").reset_index(name="work_orders")
    out["share"] = out["work_orders"] / out["work_orders"].sum() if len(values) else np.nan
    out["band"] = out["band"].astype(str)
    return out


def wait_by_weekday(fact: pd.DataFrame) -> pd.DataFrame:
    """Average wait (hours) and work-order count per weekday of ``service_date``."""
    weekday = pd.to_datetime(fact["service_date"]).dt.day_name().rename("weekday")
    out = (
        fact.assign(weekday=weekday)
        .groupby("weekday")
        .agg(avg_wait=("wait_hours", "mean"), work_orders=("work_order_id", "count"))
        .reindex([d for d in WEEKDAY_ORDER if d in set(weekday)])
        .reset_index()
    )
    return out


# --------------------------------------------------------------------------- #
# Customer and parts views
# --------------------------------------------------------------------------- #
def rating_matrix(fact: pd.DataFrame, index: str, columns: str) -> pd.DataFrame:
    """Mean rating pivoted ``index`` x ``columns`` (NaN where nothing was rated)."""
    return fact.pivot_table(index=index, columns=columns, values="rating", aggfunc="mean")


def feedback_distribution(fact: pd.DataFrame) -> pd.DataFrame:
    """Feedback categories ranked by count, with share of all categorised feedback."""
    counts = fact["feedback_category"].value_counts()
    out = counts.rename_axis("feedback_category").reset_index(name="responses")
    out["share"] = out["responses"] / out["responses"].sum() if len(out) else []
    return out


def parts_cost_by_category(
    part_usage: pd.DataFrame, parts: pd.DataFrame, fact: pd.DataFrame
) -> pd.DataFrame:
    """Catalogue parts cost (quantity x unit cost) per part category for the filtered work orders."""
    used = part_usage.loc[part_usage["work_order_id"].isin(fact["work_order_id"])]
    lines = used.merge(parts[["part_id", "part_category", "unit_cost"]], on="part_id", how="left")
    lines["line_cost"] = lines["quantity"] * lines["unit_cost"]
    out = (
        lines.groupby("part_category")
        .agg(quantity=("quantity", "sum"), parts_cost=("line_cost", "sum"))
        .sort_values("parts_cost", ascending=False)
        .reset_index()
    )
    out["share"] = out["parts_cost"] / out["parts_cost"].sum() if len(out) else []
    return out
