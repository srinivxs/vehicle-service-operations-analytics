"""Smoke tests: every dashboard page renders, and global slicers drive every KPI.

Uses streamlit.testing.v1.AppTest against the real cleaned data in data/cleaned/.
Each page is rendered through a tiny harness (shell + page) because AppTest cannot
switch between callable st.Page pages; the shell is exactly what the entry script uses.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import data
from app.formatting import fmt_inr
from src import kpis

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "app" / "streamlit_app.py"
PAGE_MODULES = ["executive_overview", "operations", "financial_analysis", "customer_experience"]
CENTRE = "Pune - Baner"
TIMEOUT = 120

pytestmark = pytest.mark.skipif(
    bool(data.missing_files(data.data_dir())), reason="cleaned data files not available"
)


def page_app(module: str) -> AppTest:
    """AppTest running the shared shell (slicers) followed by one page."""
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from app import shell
from app.views import {module}
shell.setup()
{module}.render()
"""
    return AppTest.from_string(script, default_timeout=TIMEOUT)


def metric_values(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def select_centre(at: AppTest, centre: str = CENTRE) -> None:
    at.sidebar.multiselect(key="flt_centres").select(centre)


@pytest.fixture(scope="module")
def unfiltered() -> data.FilteredData:
    return data.apply_slicers(data.load_dataset(str(data.data_dir())), kpis.Filters())


def expected_revenue(filters: kpis.Filters) -> str:
    dataset = data.load_dataset(str(data.data_dir()))
    return fmt_inr(data.apply_slicers(dataset, filters).fact["revenue"].sum())


def test_entry_script_runs_and_shows_headline_kpis(unfiltered):
    at = AppTest.from_file(str(ENTRY), default_timeout=TIMEOUT).run()
    assert not at.exception
    values = metric_values(at)
    assert values["Total revenue"] == fmt_inr(unfiltered.fact["revenue"].sum())
    assert values["Completed services"] == f"{len(unfiltered.fact):,}"
    assert {"On-time %", "Avg turnaround", "Avg customer rating", "Cancellation rate"} <= set(values)


def test_entry_script_slicer_changes_headline_revenue():
    at = AppTest.from_file(str(ENTRY), default_timeout=TIMEOUT).run()
    before = metric_values(at)["Total revenue"]
    select_centre(at)
    at.run()
    assert not at.exception
    after = metric_values(at)["Total revenue"]
    assert after != before
    assert after == expected_revenue(kpis.Filters(centres=(CENTRE,)))


@pytest.mark.parametrize("module", PAGE_MODULES)
def test_page_renders_without_exception(module):
    at = page_app(module).run()
    assert not at.exception
    assert len(at.metric) >= 4
    assert len(at.get("plotly_chart")) >= 3
    assert any("Key insight" in md.value for md in at.markdown)
    assert any("Synthetic data" in md.value for md in at.markdown)


@pytest.mark.parametrize("module", PAGE_MODULES)
def test_centre_slicer_updates_every_kpi_on_page(module):
    """Acceptance criterion: selecting a centre changes the KPIs shown on every page."""
    at = page_app(module).run()
    before = metric_values(at)
    select_centre(at)
    at.run()
    assert not at.exception
    after = metric_values(at)
    assert set(after) == set(before)
    unchanged = [label for label in before if before[label] == after[label]]
    assert not unchanged, f"KPIs unaffected by centre slicer on {module}: {unchanged}"


def test_centre_and_date_range_filter_match_computed_values():
    at = page_app("executive_overview").run()
    select_centre(at)
    at.sidebar.date_input(key="flt_dates").set_value((date(2025, 6, 1), date(2025, 12, 31)))
    at.run()
    assert not at.exception
    expected = kpis.Filters(date(2025, 6, 1), date(2025, 12, 31), centres=(CENTRE,))
    assert metric_values(at)["Total revenue"] == expected_revenue(expected)
    filtered = data.apply_slicers(data.load_dataset(str(data.data_dir())), expected)
    assert metric_values(at)["Completed services"] == f"{len(filtered.fact):,}"


def test_other_slicers_filter_results():
    at = page_app("executive_overview").run()
    at.sidebar.multiselect(key="flt_regions").select("South")
    at.sidebar.multiselect(key="flt_service_types").select("Periodic Service")
    at.sidebar.multiselect(key="flt_models").select("Ather Rizta")
    at.run()
    assert not at.exception
    expected = kpis.Filters(
        regions=("South",), service_types=("Periodic Service",), models=("Ather Rizta",)
    )
    assert metric_values(at)["Total revenue"] == expected_revenue(expected)


def test_empty_selection_shows_warning_not_crash():
    at = page_app("operations").run()
    at.sidebar.multiselect(key="flt_regions").select("North")
    at.sidebar.multiselect(key="flt_centres").select(CENTRE)  # Pune is West -> no overlap
    at.run()
    assert not at.exception
    assert any("No work orders match" in w.value for w in at.warning)


def test_reset_button_restores_all_data(unfiltered):
    at = page_app("executive_overview").run()
    select_centre(at)
    at.run()
    at.sidebar.button[0].click()
    at.run()
    assert not at.exception
    assert metric_values(at)["Total revenue"] == fmt_inr(unfiltered.fact["revenue"].sum())


def test_missing_data_directory_shows_error(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(data.DATA_ENV_VAR, str(tmp_path))
    at = page_app("executive_overview").run()
    assert any("Missing cleaned data files" in e.value for e in at.error)


def test_single_day_selection_does_not_crash():
    """st.date_input yields one date while the user is still picking a range."""
    at = page_app("executive_overview").run()
    at.sidebar.date_input(key="flt_dates").set_value((date(2026, 3, 1),))
    at.run()
    assert not at.exception
    assert metric_values(at)["Total revenue"] == expected_revenue(kpis.Filters(date(2026, 3, 1), date(2026, 9, 30)))
