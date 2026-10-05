"""Page 3 - Financial Analysis."""

from __future__ import annotations

import streamlit as st

from app import components as ui
from app import data, insights
from app.formatting import fmt_inr, fmt_pct
from src import kpis

TITLE = "Financial Analysis"


def _profit_bars(df, category: str, title: str):
    """Profit ranking: accent for profit, orange for loss."""
    return ui.hbar(
        df, category, "profit", title, ui.INR,
        color_by=lambda row: ui.ACCENT if row["profit"] >= 0 else ui.ORANGE,
        hover_columns=[("revenue", "Revenue", ui.INR), ("margin_pct", "Margin", ui.PCT)])


def render() -> None:
    d = data.filtered_data()
    ui.page_header(TITLE, "Revenue vs cost, profitability, cost variance and cost mix.")
    ui.require_rows(d.fact)

    k = kpis.headline_kpis(d.fact, d.appts, d.tech)
    trend = kpis.monthly_trend(d.fact)
    by_type = kpis.service_type_performance(d.fact)
    by_centre = kpis.group_kpis(d.fact, "center_name")

    ui.insight(insights.financial_insight(by_type, trend))
    ui.kpi_cards(
        [("Total revenue", "revenue"), ("Total cost", "total_cost"), ("Profit", "profit"),
         ("Profit margin", "margin_pct")], k, trend)
    ui.kpi_cards(
        [("Avg service cost", "avg_service_cost"), ("Cost variance", "cost_variance"),
         ("Cost overrun rate", "cost_overrun_rate"), ("Parts share of cost", "parts_share")],
        k, trend)

    left, right = st.columns(2)
    with left:
        ui.show(ui.line_chart(
            trend, "month",
            [ui.Series("revenue", "Revenue", ui.REVENUE_COLOR),
             ui.Series("total_cost", "Total cost", ui.COST_COLOR)],
            "Revenue vs cost", ui.INR))
    with right:
        ui.show(ui.column_chart(trend, "month", "profit", "Monthly profit", ui.INR,
                                color=ui.PROFIT_COLOR))

    left, right = st.columns(2)
    with left:
        ui.show(ui.line_chart(
            trend, "month",
            [ui.Series("margin_pct", "Profit margin", ui.PROFIT_COLOR),
             ui.Series("cost_overrun_rate", "Cost overrun rate", ui.ORANGE)],
            "Monthly financial trend: margin and overrun rate", ui.PCT, y_range=(0.0, 1.0)))
    with right:
        ui.show(ui.column_chart(trend, "month", "cost_variance", "Monthly cost variance", ui.INR,
                                color=ui.ORANGE))

    left, right = st.columns(2)
    with left:
        ui.show(_profit_bars(by_centre, "center_name", "Profit by service centre"))
    with right:
        ui.show(_profit_bars(by_type, "service_type", "Profit by service type"))

    st.subheader("Cost variance (actual cost minus estimate)")
    left, right = st.columns(2)
    with left:
        ui.show(ui.hbar(
            by_type, "service_type", "cost_variance", "Cost variance by service type", ui.INR,
            color=ui.ORANGE, hover_columns=[("cost_overrun_rate", "Overrun rate", ui.PCT)]))
    with right:
        by_skill = kpis.group_kpis(d.fact, "skill_level")
        ui.show(ui.hbar(
            by_skill, "skill_level", "cost_variance", "Cost variance by technician skill level",
            ui.INR, color=ui.ORANGE,
            hover_columns=[("cost_overrun_rate", "Overrun rate", ui.PCT)]))
        st.caption("Overrun rate by skill level: " + ", ".join(
            f"{r.skill_level} {fmt_pct(r.cost_overrun_rate)}" for r in by_skill.itertuples()) + ".")

    left, right = st.columns(2)
    with left:
        ui.show(ui.grouped_bar(
            by_centre.sort_values("total_cost", ascending=False), "center_name",
            [ui.Series("parts_cost", "Parts", ui.PARTS_COLOR),
             ui.Series("labor_cost", "Labour", ui.LABOUR_COLOR)],
            "Parts vs labour cost by centre", ui.INR, horizontal=True, stacked=True))
    with right:
        ui.show(ui.hbar(
            kpis.group_kpis(d.fact, "billing_type"), "billing_type", "revenue",
            "Revenue by billing type", ui.INR,
            hover_columns=[("margin_pct", "Margin", ui.PCT)]))

    categories = kpis.parts_cost_by_category(d.part_usage, d.parts, d.fact)
    ui.show(ui.hbar(
        categories, "part_category", "parts_cost", "Parts cost by part category", ui.INR,
        hover_columns=[("share", "Share of parts cost", ui.PCT)]))
    st.caption(
        f"Part-category cost is quantity x catalogue unit cost for the selected work orders "
        f"({fmt_inr(categories['parts_cost'].sum())}); it reconciles to the parts cost KPI.")
    ui.footer()
