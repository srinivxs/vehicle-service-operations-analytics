"""Cached data loading and slicer-aware filtering for the Streamlit dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src import kpis
from src.kpis import Filters

ROOT = Path(__file__).resolve().parents[1]
DATA_ENV_VAR = "VSO_DATA_DIR"
DEFAULT_DATA_DIR = ROOT / "data" / "cleaned"
FILTERS_KEY = "filters"

REQUIRED_FILES = (
    "fact_service.csv",
    "fact_appointments.csv",
    "fact_technician_month.csv",
    "part_usage.csv",
    "parts.csv",
    "service_centers.csv",
)


@dataclass(frozen=True)
class Dataset:
    """All unfiltered tables used by the dashboard."""

    fact: pd.DataFrame
    appts: pd.DataFrame
    tech: pd.DataFrame
    part_usage: pd.DataFrame
    parts: pd.DataFrame


@dataclass(frozen=True)
class FilterOptions:
    """Values offered by the global slicers."""

    min_date: date
    max_date: date
    regions: list[str]
    centres: list[str]
    service_types: list[str]
    models: list[str]


@dataclass(frozen=True)
class FilteredData:
    """The tables after applying the global slicers, plus the slicer values."""

    fact: pd.DataFrame
    appts: pd.DataFrame
    tech: pd.DataFrame
    part_usage: pd.DataFrame
    parts: pd.DataFrame
    filters: Filters


def data_dir() -> Path:
    """Directory holding the cleaned CSVs (override with the VSO_DATA_DIR env var)."""
    return Path(os.environ.get(DATA_ENV_VAR, DEFAULT_DATA_DIR))


def missing_files(directory: Path) -> list[str]:
    """Names of required CSVs that are not present in ``directory``."""
    return [name for name in REQUIRED_FILES if not (directory / name).exists()]


@st.cache_data(show_spinner="Loading service data...")
def load_dataset(directory: str) -> Dataset:
    """Read the cleaned CSVs once and cache them."""
    base = Path(directory)
    centers = pd.read_csv(base / "service_centers.csv")
    return Dataset(
        fact=pd.read_csv(base / "fact_service.csv", parse_dates=["service_date"]),
        appts=pd.read_csv(base / "fact_appointments.csv", parse_dates=["scheduled_date"]),
        tech=kpis.enrich_technician_month(
            pd.read_csv(base / "fact_technician_month.csv"), centers
        ),
        part_usage=pd.read_csv(base / "part_usage.csv"),
        parts=pd.read_csv(base / "parts.csv"),
    )


def filter_options(dataset: Dataset) -> FilterOptions:
    """Slicer choices derived from the data."""
    fact = dataset.fact
    return FilterOptions(
        min_date=fact["service_date"].min().date(),
        max_date=fact["service_date"].max().date(),
        regions=sorted(fact["region"].dropna().unique()),
        centres=sorted(fact["center_name"].dropna().unique()),
        service_types=sorted(fact["service_type"].dropna().unique()),
        models=sorted(fact["model"].dropna().unique()),
    )


def apply_slicers(dataset: Dataset, filters: Filters) -> FilteredData:
    """Filter every table with the same slicer selection."""
    return FilteredData(
        fact=kpis.apply_filters(dataset.fact, filters, kpis.FACT_COLUMNS),
        appts=kpis.apply_filters(dataset.appts, filters, kpis.APPOINTMENT_COLUMNS),
        tech=kpis.apply_filters(dataset.tech, filters, kpis.TECH_MONTH_COLUMNS),
        part_usage=dataset.part_usage,
        parts=dataset.parts,
        filters=filters,
    )


def current_filters() -> Filters:
    """Slicer selection stored in session state by the sidebar (all-open if unset)."""
    return st.session_state.get(FILTERS_KEY, Filters())


def filtered_data() -> FilteredData:
    """Load the dataset and apply the current global slicers."""
    return apply_slicers(load_dataset(str(data_dir())), current_filters())
