"""Streamlit entry point: four pages mirroring the Power BI report, shared global slicers.

Run with:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import shell  # noqa: E402
from app.views import (  # noqa: E402
    customer_experience,
    executive_overview,
    financial_analysis,
    operations,
)

PAGES = (
    (executive_overview, ":material/dashboard:", "executive-overview"),
    (operations, ":material/engineering:", "operations"),
    (financial_analysis, ":material/payments:", "financial-analysis"),
    (customer_experience, ":material/sentiment_satisfied:", "customer-experience"),
)


def main() -> None:
    st.set_page_config(
        page_title="Vehicle Service Operations Analytics",
        page_icon=":material/two_wheeler:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    navigation = st.navigation(
        [
            st.Page(module.render, title=module.TITLE, icon=icon, url_path=path,
                    default=module is executive_overview)
            for module, icon, path in PAGES
        ]
    )
    shell.setup()
    navigation.run()


main()
