"""Project-wide paths and business-rule constants.

Every KPI definition that depends on a threshold reads it from here so the
Python pipeline, SQL views, and dashboard stay consistent.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "cleaned"
REPORTS_DIR = PROJECT_ROOT / "reports"

SEED = 42

# Reporting window covered by the synthetic extract.
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2026, 9, 30)

# Service centres operate Monday-Saturday, 09:00-19:00.
SHOP_OPEN_HOUR = 9
SHOP_CLOSE_HOUR = 19
WORKING_WEEKDAYS = (0, 1, 2, 3, 4, 5)

# Productive (bookable) hours per technician per working day, used for utilisation.
PRODUCTIVE_HOURS_PER_DAY = 7.0

# A completed visit for the same vehicle and service type within this many days
# of a previous completed visit is counted as a repeat (comeback) visit.
REPEAT_VISIT_WINDOW_DAYS = 30

# Standard buffer a service advisor adds to the estimate when promising a ready time.
PROMISE_BUFFER_HOURS = 1.5

# Pricing assumptions (INR, excluding GST).
LABOUR_BILL_RATE = 750.0
WARRANTY_LABOUR_RATE = 500.0
PARTS_MARKUP = 1.30
WARRANTY_PARTS_MARKUP = 1.05
SERVICE_PLAN_FEE = 950.0
FLEET_DISCOUNT = 0.10

VEHICLE_MODELS = ("Ather 450X", "Ather 450 Apex", "Ather Rizta")

# First model year each model could legally exist (used by data-quality rules).
MODEL_FIRST_YEAR = {"Ather 450X": 2020, "Ather 450 Apex": 2024, "Ather Rizta": 2024}

# A two-wheeler realistically cannot exceed this odometer reading.
MAX_PLAUSIBLE_KM_PER_DAY = 250
