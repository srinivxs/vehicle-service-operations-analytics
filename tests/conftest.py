"""Shared, pipeline-specific fixtures.

The simulation is generated once per session (cached) and handed to tests as
independent deep copies, so a test that mutates a frame cannot affect others.
Fixture names are deliberately pipeline-specific to avoid clashing with other
test modules.
"""
from __future__ import annotations

import pytest

from src.generate_data import ServiceDataGenerator, inject_defects

PIPELINE_SEED = 11
PIPELINE_N_VEHICLES = 300


def _copy_tables(tables):
    return {name: df.copy(deep=True) for name, df in tables.items()}


@pytest.fixture(scope="session")
def _pipeline_sim_cache():
    """Generate one small clean dataset and its defect-injected twin (read-only)."""
    clean = ServiceDataGenerator(seed=PIPELINE_SEED, n_vehicles=PIPELINE_N_VEHICLES).generate()
    raw, manifest = inject_defects(clean, seed=PIPELINE_SEED)
    return {"clean": clean, "raw": raw, "manifest": manifest}


@pytest.fixture
def small_clean_tables(_pipeline_sim_cache):
    """Freshly copied clean (defect-free) generated tables."""
    return _copy_tables(_pipeline_sim_cache["clean"])


@pytest.fixture
def small_raw_tables(_pipeline_sim_cache):
    """Freshly copied raw tables with defects injected."""
    return _copy_tables(_pipeline_sim_cache["raw"])


@pytest.fixture
def small_defect_manifest(_pipeline_sim_cache):
    """Manifest of injected defect counts matching ``small_raw_tables``."""
    return {t: dict(v) for t, v in _pipeline_sim_cache["manifest"].items()}
