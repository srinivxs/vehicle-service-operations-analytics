"""Page 1 - Executive Overview."""

from __future__ import annotations

import streamlit as st

from app import components as ui
from app import data, insights
from app.formatting import fmt_hours, fmt_inr, fmt_int, fmt_pct, fmt_rating
from src import kpis

TITLE = "Executive Overview"


def render() -> None:
    d = data.filtered_data()
    ui.page_header(TITLE, "Headline KPIs, monthly revenue and profit, and service-centre ranking.")
    ui.require_rows(d.fact)

    k = kpis.headline_kpis(d.fact, d.appts, d.tech)
    trend = kpis.monthly_trend(d.fact)
    scorecard = kpis.centre_scorecard(d.fact, d.appts, d.tech)

    ui.insight(insights.executive_insight(scorecard, k["on_time_pct"]))
    ui.kpi_cards(
        [("Total revenue", "revenue"), ("Total cost", "total_cost"), ("Profit", "profit"),
         ("Profit margin", "margin_pct"), ("Completed services", "work_orders")], k, trend)
    ui.kpi_cards(
        [("On-time %", "on_time_pct"), ("Avg turnaround", "avg_turnaround"),
         ("Avg customer rating", "avg_rating"), ("Cancellation rate", "cancellation_rate")],
        k, trend)

    left, right = st.columns(2)
    with left:
        ui.show(ui.line_chart(
            trend, "month",
            [ui.Series("revenue", "Revenue", ui.REVENUE_COLOR),
             ui.Series("profit", "Profit", ui.PROFIT_COLOR)],
            "Monthly revenue and profit", ui.INR))
    with right:
        ui.show(ui.line_chart(
            trend, "month",
            [ui.Series("margin_pct", "Profit margin", ui.PROFIT_COLOR),
             ui.Series("on_time_pct", "On-time %", ui.ACCENT)],
            "Profit margin and on-time % by month", ui.PCT, y_range=(0.0, 1.0)))

    st.subheader("Service-centre performance ranking")
    bars, table = st.columns([2, 3])
    with bars:
        index = scorecard.assign(performance_index=scorecard["performance_score"] * 100)
        average = index["performance_index"].mean()
        ui.show(ui.hbar(
            index, "center_name", "performance_index",
            "Performance index (0-100, higher is better)", ui.Unit(lambda v: f"{v:.0f}"),
            color_by=ui.better_than(average, True, "performance_index"),
            reference=average, reference_label="Average"))
    with table:
        ui.styled_table(scorecard, [
            ui.Col("rank", "Rank", fmt_int),
            ui.Col("center_name", "Centre"),
            ui.Col("region", "Region"),
            ui.Col("work_orders", "Services", fmt_int),
            ui.Col("revenue", "Revenue", fmt_inr),
            ui.Col("margin_pct", "Margin", fmt_pct, "high"),
            ui.Col("on_time_pct", "On-time", fmt_pct, "high"),
            ui.Col("avg_turnaround", "Turnaround", fmt_hours, "low"),
            ui.Col("avg_rating", "Rating", fmt_rating, "high"),
            ui.Col("cancellation_rate", "Cancel rate", fmt_pct, "low"),
        ])
        st.caption(
            "Performance index = mean percentile rank of on-time %, rating, margin, turnaround "
            "(lower is better) and cancellation rate (lower is better). Green / amber shading "
            "marks the best / worst third of centres per column.")
    ui.footer()
