"""Shared page shell: styling, data check and the global slicers (used by every page)."""

from __future__ import annotations

import streamlit as st

from app import components as ui
from app import data


def setup() -> None:
    """Inject CSS, verify the data files exist, then draw the global slicers in the sidebar."""
    ui.inject_css()
    directory = data.data_dir()
    missing = data.missing_files(directory)
    if missing:
        st.error(
            f"Missing cleaned data files in {directory}: {', '.join(missing)}. "
            "Run src/generate_data.py and src/data_cleaning.py first."
        )
        st.stop()
    dataset = data.load_dataset(str(directory))
    filters = ui.sidebar_filters(data.filter_options(dataset))
    selected = data.apply_slicers(dataset, filters)
    with st.sidebar:
        st.caption(f"{len(selected.fact):,} of {len(dataset.fact):,} work orders selected")
