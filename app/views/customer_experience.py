"""Page 4 - Customer Experience."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import components as ui
from app import data, insights
from src import kpis

TITLE = "Customer Experience"


def _rating_range(ratings: pd.Series) -> tuple[float, float]:
    """Y-range for the rating trend: observed range +/- 0.5, kept within the 1-5 scale."""
    if ratings.notna().sum() == 0:
        return 1.0, 5.0
    return max(1.0, ratings.min() - 0.5), min(5.0, ratings.max() + 0.5)


def render() -> None:
    d = data.filtered_data()
    ui.page_header(TITLE, "Ratings, cancellations, repeat visits and customer feedback.")
    ui.require_rows(d.fact)

    k = kpis.headline_kpis(d.fact, d.appts, d.tech)
    trend = kpis.monthly_trend(d.fact)
    by_centre = kpis.group_kpis(d.fact, "center_name")
    by_lead = kpis.cancellation_by(d.appts, "lead_time_band", kpis.LEAD_TIME_ORDER)

    ui.insight(insights.customer_insight(by_centre, by_lead))
    ui.kpi_cards(
        [("Avg rating", "avg_rating"), ("CSAT %", "csat_pct"),
         ("Cancellation rate", "cancellation_rate"), ("No-show rate", "no_show_rate"),
         ("Repeat visit rate", "repeat_visit_rate"), ("Comeback rate", "comeback_rate")],
        k, trend)

    left, right = st.columns(2)
    with left:
        ui.show(ui.line_chart(
            trend, "month", [ui.Series("avg_rating", "Average rating", ui.ACCENT)],
            "Rating trend (1-5 scale)", ui.RATING, y_range=_rating_range(trend["avg_rating"])))
    with right:
        ui.show(ui.line_chart(
            trend, "month", [ui.Series("csat_pct", "CSAT % (rating 4+)", ui.BLUE)],
            "CSAT % trend", ui.PCT, y_range=(0.0, 1.0)))

    ui.show(ui.heatmap(
        kpis.rating_matrix(d.fact, "service_type", "center_name"),
        "Average rating by service type and centre", ui.RATING, label="Average rating",
        zmin=1.0, zmax=5.0))

    st.subheader("Cancellations")
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.show(ui.hbar(
            kpis.cancellation_by(d.appts, "center_name"), "center_name", "cancellation_rate",
            "Cancellation rate by centre", ui.PCT, reference=k["cancellation_rate"],
            hover_columns=[("appointments", "Appointments", ui.COUNT),
                           ("no_show_rate", "No-show rate", ui.PCT)]))
    with c2:
        ui.show(ui.column_chart(
            by_lead, "lead_time_band", "cancellation_rate", "Cancellation rate by lead time",
            ui.PCT, monthly=False, color=ui.BLUE))
    with c3:
        reasons = kpis.cancellation_reasons(d.appts)
        ui.show(ui.hbar(reasons, "cancellation_reason", "cancellations",
                        "Cancellation reasons", ui.COUNT,
                        hover_columns=[("share", "Share", ui.PCT)]))

    st.subheader("Repeat visits")
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.show(ui.hbar(
            by_centre, "center_name", "repeat_visit_rate", "Repeat-visit rate by centre", ui.PCT,
            reference=k["repeat_visit_rate"]))
        st.caption(ui.KPI_HELP["repeat_visit_rate"])
    with c2:
        ui.show(ui.hbar(
            by_centre, "center_name", "comeback_rate", "Comeback rate by centre", ui.PCT,
            color=ui.ORANGE, reference=k["comeback_rate"]))
        st.caption(ui.KPI_HELP["comeback_rate"])
    with c3:
        by_skill = kpis.group_kpis(d.fact, "skill_level")
        by_skill = by_skill.set_index("skill_level").reindex(
            [s for s in ui.SKILL_ORDER if s in set(by_skill["skill_level"])]).reset_index()
        ui.show(ui.hbar(
            by_skill, "skill_level", "comeback_rate", "Comeback rate by technician skill level",
            ui.PCT, color_by=lambda row: ui.SKILL_COLORS.get(row["skill_level"], ui.NEUTRAL),
            hover_columns=[("work_orders", "Work orders", ui.COUNT),
                           ("qc_first_pass_rate", "QC first-pass", ui.PCT)]))

    feedback = kpis.feedback_distribution(d.fact)
    ui.show(ui.hbar(
        feedback, "feedback_category", "responses", "Feedback categories", ui.COUNT,
        color_by=lambda row: ui.ACCENT if row["feedback_category"] == "Positive Experience"
        else ui.BLUE,
        hover_columns=[("share", "Share of feedback", ui.PCT)]))
    st.caption("Feedback exists only for rated work orders. Green = positive experience; blue = complaint themes.")
    ui.footer()
