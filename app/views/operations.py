"""Page 2 - Operations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import components as ui
from app import data, insights
from app.formatting import fmt_hours, fmt_inr, fmt_int, fmt_pct, fmt_rating
from src import kpis

TITLE = "Operations"


def render() -> None:
    d = data.filtered_data()
    ui.page_header(TITLE, "Turnaround, technician workload, estimated vs actual duration and delays.")
    ui.require_rows(d.fact)

    k = kpis.headline_kpis(d.fact, d.appts, d.tech)
    trend = kpis.monthly_trend(d.fact)
    centres = kpis.centre_scorecard(d.fact, d.appts, d.tech)
    weekday = kpis.wait_by_weekday(d.fact)
    by_type = kpis.service_type_performance(d.fact)

    ui.insight(insights.operations_insight(centres, weekday))
    ui.kpi_cards(
        [("Avg turnaround", "avg_turnaround"), ("Median turnaround", "median_turnaround"),
         ("Avg wait before start", "avg_wait"), ("On-time %", "on_time_pct")], k, trend)
    ui.kpi_cards(
        [("Technician utilisation", "utilisation"), ("Parts delay rate", "parts_delay_rate"),
         ("Avg duration variance", "avg_duration_variance"),
         ("QC first-pass", "qc_first_pass_rate")], k, trend)

    left, right = st.columns(2)
    with left:
        ui.show(ui.grouped_bar(
            centres.sort_values("avg_turnaround", ascending=False), "center_name",
            [ui.Series("avg_turnaround", "Mean", ui.ACCENT),
             ui.Series("median_turnaround", "Median", ui.NEUTRAL)],
            "Turnaround time by centre (hours)", ui.HOURS, horizontal=True))
        st.caption("The mean is pulled up by a minority of long repairs; the median shows the typical job.")
    with right:
        _technician_workload(d.fact, d.tech)

    st.subheader("Technician utilisation by month")
    ui.show(ui.heatmap(
        kpis.technician_utilisation_matrix(d.tech), "Utilisation: technician x month", ui.PCT,
        label="Utilisation", show_values=False, zmin=0.0))
    st.caption(ui.KPI_HELP["utilisation"])

    left, right = st.columns(2)
    with left:
        ui.show(ui.grouped_bar(
            by_type.sort_values("avg_actual_hours", ascending=False), "service_type",
            [ui.Series("avg_est_hours", "Estimated", ui.ESTIMATED_COLOR),
             ui.Series("avg_actual_hours", "Actual", ui.ACTUAL_COLOR)],
            "Estimated vs actual duration by service type (hours)", ui.HOURS, horizontal=True))
        ui.show(ui.column_chart(
            weekday, "weekday", "avg_wait", "Average wait before start by weekday", ui.HOURS,
            monthly=False))
    with right:
        ui.show(ui.column_chart(
            kpis.delay_distribution(d.fact), "band", "work_orders",
            "Delay distribution: hours past promised time", ui.COUNT, monthly=False))
        ui.show(ui.column_chart(
            kpis.delay_distribution(d.fact, "turnaround_hours", kpis.TURNAROUND_EDGES, None),
            "band", "work_orders", "Turnaround time bands", ui.COUNT, color=ui.BLUE,
            monthly=False))

    st.subheader("Service-type performance")
    ui.styled_table(by_type, [
        ui.Col("service_type", "Service type"),
        ui.Col("work_orders", "Services", fmt_int),
        ui.Col("avg_turnaround", "Turnaround", fmt_hours, "low"),
        ui.Col("on_time_pct", "On-time", fmt_pct, "high"),
        ui.Col("avg_est_hours", "Est. duration", fmt_hours),
        ui.Col("avg_actual_hours", "Actual duration", fmt_hours),
        ui.Col("avg_duration_variance", "Duration var.", fmt_hours, "low"),
        ui.Col("parts_delay_rate", "Parts delay", fmt_pct, "low"),
        ui.Col("avg_rating", "Rating", fmt_rating, "high"),
        ui.Col("revenue", "Revenue", fmt_inr),
    ])
    ui.footer()


def _technician_workload(fact: pd.DataFrame, tech: pd.DataFrame) -> None:
    """Technician utilisation bars coloured by skill level."""
    card = kpis.technician_scorecard(fact, tech)
    if ui.no_data_note(card, "technician records"):
        return
    card = card.assign(label=card["technician_id"] + " (" + card["skill_level"].astype(str) + ")")
    ui.show(ui.hbar(
        card, "label", "utilisation", "Technician workload: utilisation", ui.PCT,
        color_by=lambda row: ui.SKILL_COLORS.get(row["skill_level"], ui.NEUTRAL),
        hover_columns=[("jobs", "Jobs", ui.COUNT), ("service_hours", "Service hours", ui.COUNT),
                       ("center_name", "Centre", ui.Unit(str))]))
    swatches = " ".join(
        f'<span style="color:{c}">&#9632;</span> {name}' for name, c in ui.SKILL_COLORS.items())
    st.markdown(f"<small>Skill level: {swatches}</small>", unsafe_allow_html=True)
