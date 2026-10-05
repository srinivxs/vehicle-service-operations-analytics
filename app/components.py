"""Reusable UI building blocks: palette, Plotly template, KPI cards, charts, tables, slicers.

Design rules (dataviz skill): one categorical palette assigned in fixed order, one
accent colour for single-series charts, sequential single-hue ramp for magnitude,
thin marks, hairline recessive grid, legend whenever there are two or more series,
a single y-axis per chart (no dual axes), and values formatted with units.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, NamedTuple, Sequence

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from app.data import FILTERS_KEY, FilterOptions
from app.formatting import (
    MISSING,
    fmt_hours,
    fmt_inr,
    fmt_int,
    fmt_pct,
    fmt_rating,
    month_label,
)
from src.kpis import Filters

# --------------------------------------------------------------------------- #
# Palette (validated with the dataviz validator; mirrored in powerbi theme JSON)
# --------------------------------------------------------------------------- #
ACCENT = "#00A67E"  # slot 1 - green, the single-series colour
BLUE = "#2A78D6"  # slot 2
ORANGE = "#EB6834"  # slot 3
VIOLET = "#4A3AA7"  # slot 4
MAGENTA = "#E87BA4"  # slot 5
YELLOW = "#EDA100"  # slot 6
CATEGORICAL: tuple[str, ...] = (ACCENT, BLUE, ORANGE, VIOLET, MAGENTA, YELLOW)

NEUTRAL = "#A9B4B0"  # de-emphasised / "plan" series
INK = "#1F2A27"
INK_SECONDARY = "#52605B"
INK_MUTED = "#8A9691"
GRID = "#E6EBE9"
AXIS = "#C9D1CE"
SURFACE = "#FFFFFF"
PAGE_TINT = "#F4F7F6"
GOOD_TINT = "#D9F2EA"
BAD_TINT = "#FBE5D6"
SEQUENTIAL = [[0.0, "#E6F6F1"], [0.55, "#86D6C0"], [1.0, "#00573F"]]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Entity colours stay fixed across every chart (colour follows the entity).
REVENUE_COLOR = ACCENT
COST_COLOR = BLUE
PROFIT_COLOR = VIOLET
PARTS_COLOR = BLUE
LABOUR_COLOR = ORANGE
ESTIMATED_COLOR = NEUTRAL
ACTUAL_COLOR = ACCENT
SKILL_COLORS = {"Junior": ORANGE, "Mid": BLUE, "Senior": ACCENT, "Master": VIOLET}
SKILL_ORDER = tuple(SKILL_COLORS)

FOOTER = (
    "Synthetic data for demonstration. Modelled on an EV two-wheeler service network; "
    "not affiliated with Ather Energy. Amounts in INR."
)

KPI_HELP = {
    "revenue": "Total Revenue = SUM(revenue)",
    "total_cost": "Total Cost = SUM(labor_cost + parts_cost)",
    "profit": "Profit = Revenue - Total Cost",
    "margin_pct": "Margin % = Profit / Revenue",
    "work_orders": "Completed services = count of work orders",
    "avg_service_cost": "Average Service Cost = Total Cost / completed work orders",
    "on_time_pct": "On-Time % = on-time work orders / completed work orders",
    "avg_turnaround": "Average turnaround hours (check-in to ready), mean of turnaround_hours",
    "median_turnaround": "Median turnaround hours (robust to very long repairs)",
    "avg_wait": "Average wait before work starts (hours)",
    "avg_rating": "Customer Satisfaction = mean rating (1-5) of rated work orders",
    "csat_pct": "CSAT % = share of rated work orders scoring 4 or 5",
    "cancellation_rate": "Cancellation Rate = cancelled / all appointments",
    "no_show_rate": "No-show rate = no-shows / all appointments",
    "utilisation": "Technician Utilisation = SUM(service hours) / SUM(available hours). "
    "Measured at month grain: a date range includes every month it overlaps. "
    "Date, region and centre slicers apply; service type and model do not.",
    "cost_variance": "Cost Variance = SUM(actual cost - estimated cost)",
    "cost_overrun_rate": "Share of work orders whose actual cost exceeded the estimate by more than 10%",
    "repeat_visit_rate": "Repeat Visit Rate = customers with 2+ work orders / customers with 1+ "
    "(within the selected filters)",
    "comeback_rate": "Comeback rate = share of work orders that caused a repeat visit",
    "parts_delay_rate": "Share of work orders delayed by parts availability",
    "qc_first_pass_rate": "Share of work orders passing quality check first time",
    "avg_duration_variance": "Mean (actual - estimated) hours",
    "parts_share": "Parts cost as a share of total cost",
}


# --------------------------------------------------------------------------- #
# Plotly template and page styling
# --------------------------------------------------------------------------- #
def _build_template() -> go.layout.Template:
    axis = {"showline": True, "linecolor": AXIS, "ticks": "", "zeroline": False,
            "tickfont": {"color": INK_MUTED, "size": 11}, "title": {"font": {"color": INK_MUTED}}}
    return go.layout.Template(
        layout={
            "font": {"family": FONT, "size": 12, "color": INK_SECONDARY},
            "colorway": list(CATEGORICAL),
            "paper_bgcolor": SURFACE,
            "plot_bgcolor": SURFACE,
            "margin": {"l": 8, "r": 16, "t": 56, "b": 8},
            "title": {"font": {"size": 14, "color": INK}, "x": 0.0, "xanchor": "left"},
            "xaxis": {**axis, "showgrid": False, "automargin": True},
            "yaxis": {**axis, "showgrid": True, "gridcolor": GRID, "gridwidth": 1,
                      "showline": False, "automargin": True},
            "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right",
                       "x": 1.0, "font": {"color": INK_SECONDARY}, "title": {"text": ""}},
            "hoverlabel": {"bgcolor": SURFACE, "bordercolor": AXIS,
                           "font": {"family": FONT, "color": INK}},
            "bargap": 0.35,
        }
    )


pio.templates["vso"] = _build_template()
pio.templates.default = "vso"

_CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1500px; }}
.insight {{ border-left: 4px solid {ACCENT}; background: {PAGE_TINT}; padding: .6rem .9rem;
  border-radius: 0 6px 6px 0; margin: .25rem 0 1rem 0; color: {INK}; font-size: .95rem; }}
.insight strong {{ color: {ACCENT}; margin-right: .4rem; text-transform: uppercase;
  font-size: .75rem; letter-spacing: .04em; }}
.footer {{ color: {INK_MUTED}; font-size: .78rem; margin-top: 2rem; border-top: 1px solid {GRID};
  padding-top: .6rem; }}
</style>
"""


def inject_css() -> None:
    """Apply page-level CSS (insight callout, footer)."""
    st.markdown(_CSS, unsafe_allow_html=True)


def footer() -> None:
    """Synthetic-data disclaimer shown at the bottom of every page."""
    st.markdown(f'<div class="footer">{html.escape(FOOTER)}</div>', unsafe_allow_html=True)


def insight(text: str) -> None:
    """Render the computed "Key insight" callout (HTML-escaped; hidden when empty)."""
    if text:
        st.markdown(
            f'<div class="insight"><strong>Key insight</strong>{html.escape(text)}</div>',
            unsafe_allow_html=True,
        )


def page_header(title: str, subtitle: str) -> None:
    """Page title with a one-line description."""
    st.title(title)
    st.caption(subtitle)


# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Kpi:
    """One KPI card: label, pre-formatted value, definition tooltip, optional sparkline."""

    label: str
    value: str
    help: str | None = None
    trend: Sequence[float] | None = None


def kpi_row(items: Sequence[Kpi]) -> None:
    """Render KPI cards side by side."""
    for column, item in zip(st.columns(len(items)), items):
        with column:
            spark = _sparkline(item.trend)
            st.metric(item.label, item.value, help=item.help, border=True, chart_data=spark)


def _sparkline(trend: Sequence[float] | None) -> list[float] | None:
    if trend is None or len(trend) < 2 or any(pd.isna(v) for v in trend):
        return None
    return [float(v) for v in trend]


# Period-level ratios whose per-month value is not comparable to the headline figure.
NO_SPARKLINE = frozenset({"repeat_visit_rate"})


def kpi_cards(spec: Sequence[tuple[str, str]], values: dict[str, float],
              trend: pd.DataFrame | None = None) -> None:
    """Render a row of cards from ``(label, kpi_key)`` pairs.

    Values come from the ``headline_kpis`` dict; a monthly sparkline is added when the
    monthly trend frame has a column with the same key.
    """
    formats = kpi_formats()
    items = []
    for label, key in spec:
        has_trend = trend is not None and key in trend.columns and key not in NO_SPARKLINE
        items.append(Kpi(label, formats[key](values[key]), KPI_HELP.get(key),
                         list(trend[key]) if has_trend else None))
    kpi_row(items)


def kpi_formats() -> dict[str, Callable[[float], str]]:
    """Default formatter for each KPI key."""
    return {
        "revenue": fmt_inr, "total_cost": fmt_inr, "profit": fmt_inr, "cost_variance": fmt_inr,
        "avg_service_cost": fmt_inr, "work_orders": fmt_int, "appointments": fmt_int,
        "avg_turnaround": fmt_hours, "median_turnaround": fmt_hours, "avg_wait": fmt_hours,
        "avg_duration_variance": fmt_hours, "avg_rating": fmt_rating,
    } | {key: fmt_pct for key in (
        "margin_pct", "on_time_pct", "csat_pct", "cancellation_rate", "no_show_rate",
        "utilisation", "cost_overrun_rate", "repeat_visit_rate", "comeback_rate",
        "parts_delay_rate", "qc_first_pass_rate", "parts_share",
    )}


# --------------------------------------------------------------------------- #
# Units and axes
# --------------------------------------------------------------------------- #
class Unit(NamedTuple):
    """How a measure is formatted in labels, tooltips and axis ticks."""

    fmt: Callable[[float], str]
    tickformat: str | None = None
    ticksuffix: str = ""


INR = Unit(fmt_inr)
PCT = Unit(fmt_pct, ".0%")
HOURS = Unit(fmt_hours, ".1f", " h")
COUNT = Unit(fmt_int, ",.0f")
RATING = Unit(lambda v: f"{v:.2f}", ".1f")


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Evenly spaced round tick values (1/2/2.5/5 x 10^k) covering [lo, hi]."""
    span = hi - lo
    if not span > 0:
        return [lo]
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.ceil(lo / step) * step
    return [float(start + i * step) for i in range(math.floor((hi - start) / step + 1e-9) + 1)]


def _apply_unit(fig: go.Figure, axis: str, unit: Unit, lo: float, hi: float) -> None:
    update = fig.update_yaxes if axis == "y" else fig.update_xaxes
    if unit is INR:
        ticks = nice_ticks(lo, hi)
        update(tickvals=ticks, ticktext=[fmt_inr(v, 1 if abs(v) >= 1e5 else 0) for v in ticks])
    elif unit.tickformat:
        update(tickformat=unit.tickformat, ticksuffix=unit.ticksuffix)


def _value_range(values: pd.Series, pad: float = 0.16, floor_zero: bool = True) -> tuple[float, float]:
    clean = values.dropna()
    if clean.empty:
        return 0.0, 1.0
    lo = min(0.0, float(clean.min())) if floor_zero else float(clean.min())
    hi = max(0.0, float(clean.max()))
    span = (hi - lo) or 1.0
    return (lo - span * pad if lo < 0 else lo), hi + span * pad


def _texts(values: Sequence[float], unit: Unit) -> list[str]:
    return [unit.fmt(v) if pd.notna(v) else MISSING for v in values]


def show(fig: go.Figure) -> None:
    """Render a figure with the shared config (no toolbar, template colours untouched)."""
    key = "chart-" + str(fig.layout.title.text)
    fig.update_layout(plot_bgcolor=SURFACE, paper_bgcolor=SURFACE)
    st.plotly_chart(
        fig,
        theme=None,
        width="stretch",
        key=key,
        config={"displayModeBar": False, "displaylogo": False},
    )


# --------------------------------------------------------------------------- #
# Chart builders
# --------------------------------------------------------------------------- #
class Series(NamedTuple):
    """A measure to plot: dataframe column, legend label and colour."""

    column: str
    label: str
    color: str


def _month_axis(fig: go.Figure, months: Sequence[str]) -> None:
    step = max(1, math.ceil(len(months) / 10))
    fig.update_xaxes(
        type="category",
        tickmode="array",
        tickvals=list(months[::step]),
        ticktext=[month_label(m) for m in months[::step]],
    )


def line_chart(df: pd.DataFrame, x: str, series: Sequence[Series], title: str, unit: Unit,
               *, y_range: tuple[float, float] | None = None) -> go.Figure:
    """Multi-line trend over months (2px lines, last-point marker, legend if 2+ series)."""
    fig = go.Figure()
    for s in series:
        fig.add_scatter(
            x=df[x], y=df[s.column], name=s.label, mode="lines",
            line={"color": s.color, "width": 2}, customdata=_texts(df[s.column], unit),
            hovertemplate=f"{s.label}: %{{customdata}}<extra></extra>",
        )
        if len(df):
            fig.add_scatter(
                x=df[x].iloc[[-1]], y=df[s.column].iloc[[-1]], mode="markers", showlegend=False,
                marker={"color": s.color, "size": 8, "line": {"color": SURFACE, "width": 2}},
                hoverinfo="skip",
            )
    values = pd.concat([df[s.column] for s in series]) if len(df) else pd.Series(dtype=float)
    lo, hi = y_range or _value_range(values, floor_zero=True)
    _apply_unit(fig, "y", unit, lo, hi)
    fig.update_yaxes(range=[lo, hi])
    _month_axis(fig, list(df[x]))
    fig.update_layout(title=title, hovermode="x unified", showlegend=len(series) > 1)
    return fig


def column_chart(df: pd.DataFrame, x: str, y: str, title: str, unit: Unit,
                 color: str = ACCENT, *, monthly: bool = True) -> go.Figure:
    """Vertical bars (months when ``monthly``), positives in ``color`` and negatives in orange."""
    colors = [color if (pd.isna(v) or v >= 0) else ORANGE for v in df[y]]
    fig = go.Figure(
        go.Bar(x=df[x], y=df[y], marker={"color": colors, "cornerradius": 4},
               customdata=_texts(df[y], unit), hovertemplate="%{customdata}<extra></extra>")
    )
    lo, hi = _value_range(df[y])
    _apply_unit(fig, "y", unit, lo, hi)
    fig.update_yaxes(range=[lo, hi])
    if monthly:
        _month_axis(fig, list(df[x]))
    else:
        fig.update_xaxes(type="category")
    fig.update_layout(title=title, showlegend=False, bargap=0.4)
    return fig


def hbar(df: pd.DataFrame, category: str, value: str, title: str, unit: Unit, *,
         color: str = ACCENT, color_by: Callable[[pd.Series], str] | None = None,
         reference: float | None = None, reference_label: str = "Network",
         hover_columns: Sequence[tuple[str, str, Unit]] = ()) -> go.Figure:
    """Horizontal ranked bar (largest on top), value labels at bar ends, optional reference line."""
    d = df.sort_values(value, ascending=True, na_position="first")
    colors = [color_by(row) for _, row in d.iterrows()] if color_by else color
    hover = _hover_lines(d, hover_columns)
    fig = go.Figure(
        go.Bar(
            x=d[value], y=d[category], orientation="h", marker={"color": colors, "cornerradius": 4},
            text=_texts(d[value], unit), textposition="outside", cliponaxis=False,
            textfont={"color": INK_SECONDARY, "size": 11}, customdata=hover,
            hovertemplate="%{y}<br>%{customdata}<extra></extra>",
        )
    )
    lo, hi = _value_range(d[value])
    _apply_unit(fig, "x", unit, lo, hi)
    fig.update_xaxes(range=[lo, hi], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, type="category")
    if reference is not None and pd.notna(reference):
        fig.add_vline(x=reference, line={"color": INK_MUTED, "width": 1},
                      annotation_position="top left",
                      annotation={"text": f"{reference_label}: {unit.fmt(reference)}",
                                  "font": {"color": INK_MUTED, "size": 11}, "yanchor": "bottom"})
    fig.update_layout(title=title, showlegend=False, height=max(220, 34 * len(d) + 90))
    return fig


def _hover_lines(df: pd.DataFrame, extras: Sequence[tuple[str, str, Unit]]) -> list[str]:
    """Pre-formatted extra tooltip lines (label: value) per row."""
    return [
        "<br>".join(f"{label}: {unit.fmt(row[col])}" for col, label, unit in extras)
        for _, row in df.iterrows()
    ]


def grouped_bar(df: pd.DataFrame, category: str, series: Sequence[Series], title: str, unit: Unit,
                *, horizontal: bool = False, stacked: bool = False) -> go.Figure:
    """Grouped or stacked bars; a 2px surface gap separates fills, legend lists the series."""
    fig = go.Figure()
    d = df.iloc[::-1] if horizontal else df
    for s in series:
        values = d[s.column]
        kwargs = {"x": values, "y": d[category], "orientation": "h"} if horizontal else \
            {"x": d[category], "y": values}
        fig.add_bar(
            name=s.label, marker={"color": s.color, "cornerradius": 0 if stacked else 4,
                                  "line": {"color": SURFACE, "width": 2 if stacked else 0}},
            customdata=_texts(values, unit),
            hovertemplate=f"{s.label}: %{{customdata}}<extra></extra>", **kwargs,
        )
    totals = d[[s.column for s in series]].sum(axis=1) if stacked else \
        pd.concat([d[s.column] for s in series])
    lo, hi = _value_range(totals, pad=0.05)
    axis = "x" if horizontal else "y"
    _apply_unit(fig, axis, unit, lo, hi)
    (fig.update_xaxes if horizontal else fig.update_yaxes)(range=[lo, hi], showgrid=True, gridcolor=GRID)
    if horizontal:
        fig.update_yaxes(showgrid=False, type="category")
    fig.update_layout(
        title=title, barmode="stack" if stacked else "group", hovermode="y unified" if horizontal
        else "x unified", showlegend=True,
        height=max(280, 30 * len(d) * (1 if stacked else len(series)) + 100) if horizontal else None,
    )
    return fig


def heatmap(matrix: pd.DataFrame, title: str, unit: Unit, *, label: str,
            show_values: bool = True, zmin: float | None = None,
            zmax: float | None = None) -> go.Figure:
    """Sequential single-hue heatmap with 2px cell gaps and a slim colour bar."""
    x = [month_label(c) if _is_month(c) else c for c in matrix.columns]
    text = [[unit.fmt(v) if pd.notna(v) else "" for v in row] for row in matrix.to_numpy()]
    fig = go.Figure(
        go.Heatmap(
            z=matrix.to_numpy(dtype=float), x=x, y=list(matrix.index), colorscale=SEQUENTIAL,
            zmin=zmin, zmax=zmax, xgap=2, ygap=2, text=text,
            texttemplate="%{text}" if show_values else None, textfont={"size": 11},
            hovertemplate=f"%{{y}} / %{{x}}<br>{label}: %{{text}}<extra></extra>",
            colorbar={"thickness": 10, "outlinewidth": 0, "tickformat": unit.tickformat,
                      "tickfont": {"color": INK_MUTED, "size": 10}},
        )
    )
    fig.update_xaxes(showgrid=False, type="category", side="bottom")
    fig.update_yaxes(showgrid=False, type="category", autorange="reversed")
    fig.update_layout(title=title, height=max(300, 24 * len(matrix) + 120))
    return fig


def _is_month(value: object) -> bool:
    text = str(value)
    return len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit()


def better_than(reference: float, higher_is_better: bool = True,
                column: str | None = None) -> Callable[[pd.Series], str]:
    """Bar colour rule: accent when a row beats ``reference``, orange when it trails."""

    def rule(row: pd.Series) -> str:
        value = row[column] if column else None
        if value is None or pd.isna(value) or pd.isna(reference):
            return NEUTRAL
        good = value >= reference if higher_is_better else value <= reference
        return ACCENT if good else ORANGE

    return rule


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Col:
    """A table column: source name, header, formatter and (optional) direction of 'better'."""

    name: str
    label: str
    fmt: Callable[[float], str] | None = None
    better: str | None = None  # "high" | "low" | None


def _tint(series: pd.Series, better: str) -> list[str]:
    """CSS shading: best third of rows green, worst third amber (needs >= 3 distinct values)."""
    if series.nunique() < 3:
        return [""] * len(series)
    low, high = series.quantile(1 / 3), series.quantile(2 / 3)
    good, bad = (high, low) if better == "high" else (low, high)

    def css(value: float) -> str:
        if pd.isna(value):
            return ""
        if (value >= good if better == "high" else value <= good):
            return f"background-color: {GOOD_TINT}"
        if (value <= bad if better == "high" else value >= bad):
            return f"background-color: {BAD_TINT}"
        return ""

    return [css(v) for v in series]


def styled_table(df: pd.DataFrame, columns: Sequence[Col]) -> None:
    """Show a formatted table with best/worst-third shading on columns that define 'better'."""
    display = df[[c.name for c in columns]].rename(columns={c.name: c.label for c in columns})
    styler = display.style.format(
        {c.label: c.fmt for c in columns if c.fmt is not None}, na_rep=MISSING
    )
    for c in columns:
        if c.better:
            styler = styler.apply(_tint, subset=[c.label], better=c.better, axis=0)
    st.dataframe(styler, hide_index=True, width="stretch", height=36 * (len(display) + 1) + 3)


# --------------------------------------------------------------------------- #
# Global slicers (sidebar)
# --------------------------------------------------------------------------- #
KEY_DATES = "flt_dates"
KEY_REGIONS = "flt_regions"
KEY_CENTRES = "flt_centres"
KEY_SERVICES = "flt_service_types"
KEY_MODELS = "flt_models"


def _reset_filters(options: FilterOptions) -> None:
    st.session_state[KEY_DATES] = (options.min_date, options.max_date)
    for key in (KEY_REGIONS, KEY_CENTRES, KEY_SERVICES, KEY_MODELS):
        st.session_state[key] = []


def _date_bounds(selected: object, options: FilterOptions) -> tuple[date, date]:
    """Normalise st.date_input output (single date while the user is mid-selection)."""
    if isinstance(selected, (tuple, list)):
        if len(selected) == 2:
            return selected[0], selected[1]
        if len(selected) == 1:
            return selected[0], options.max_date
    return options.min_date, options.max_date


def sidebar_filters(options: FilterOptions) -> Filters:
    """Render the shared slicers and store the selection in session state.

    Widgets live in the entry script so their state (and the stored ``Filters``)
    persists while the user moves between pages.
    """
    with st.sidebar:
        st.markdown("### Filters")
        picked = st.date_input(
            "Date range", value=(options.min_date, options.max_date), min_value=options.min_date,
            max_value=options.max_date, key=KEY_DATES, format="DD/MM/YYYY",
        )
        regions = st.multiselect("Region", options.regions, key=KEY_REGIONS, placeholder="All regions")
        centres = st.multiselect("Service centre", options.centres, key=KEY_CENTRES,
                                 placeholder="All centres")
        services = st.multiselect("Service type", options.service_types, key=KEY_SERVICES,
                                  placeholder="All service types")
        models = st.multiselect("Model", options.models, key=KEY_MODELS, placeholder="All models")
        st.button("Reset filters", on_click=_reset_filters, args=(options,), width="stretch")
    start, end = _date_bounds(picked, options)
    current = Filters(start, end, tuple(regions), tuple(centres), tuple(services), tuple(models))
    st.session_state[FILTERS_KEY] = current
    return current


def require_rows(df: pd.DataFrame) -> None:
    """Stop the page with a friendly message when the slicers match no work orders."""
    if df.empty:
        st.warning("No work orders match the current filters. Widen the date range or clear a slicer.")
        footer()
        st.stop()


def no_data_note(df: pd.DataFrame, what: str) -> bool:
    """Show a short note and return True when ``df`` is empty."""
    if df.empty:
        st.caption(f"No {what} for the current filters.")
    return df.empty
