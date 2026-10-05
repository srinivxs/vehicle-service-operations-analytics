"""Tests for the synthetic data generator and the defect injector."""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pytest

import src.generate_data as gd
from src.config import PERIOD_END, PERIOD_START, SEED
from src.generate_data import ServiceDataGenerator, inject_defects
from src.reference_data import CENTRES, MODELS, PARTS, SERVICE_TYPES

pytestmark = pytest.mark.unit

EXPECTED_COLUMNS = {
    "customers": ["customer_id", "customer_type", "city", "region", "registration_date"],
    "vehicles": ["vehicle_id", "customer_id", "model", "variant", "vehicle_category", "battery_kwh",
                 "model_year", "purchase_date", "mileage_km"],
    "service_centers": ["center_id", "center_name", "city", "state", "region", "service_bays",
                        "daily_job_capacity", "opened_date"],
    "technicians": ["technician_id", "center_id", "skill_level", "years_experience", "certification",
                    "hourly_cost", "shift_hours_per_day"],
    "appointments": ["appointment_id", "vehicle_id", "center_id", "booking_date", "scheduled_date",
                     "scheduled_slot", "booking_channel", "requested_service_type", "status",
                     "cancellation_reason"],
    "work_orders": ["work_order_id", "appointment_id", "technician_id", "service_type", "check_in_time",
                    "start_time", "end_time", "promised_ready_time", "estimated_hours", "actual_hours",
                    "parts_wait_hours", "odometer_km", "additional_work_found", "qc_passed_first_time"],
    "parts": ["part_id", "part_name", "part_category", "unit_cost", "compatible_models", "supplier_lead_days"],
    "part_usage": ["usage_id", "work_order_id", "part_id", "quantity"],
    "financials": ["work_order_id", "billing_type", "estimated_cost", "labor_cost", "parts_cost", "revenue"],
    "feedback": ["feedback_id", "work_order_id", "rating", "feedback_category", "feedback_date"],
}
PRIMARY_KEYS = {
    "customers": "customer_id", "vehicles": "vehicle_id", "service_centers": "center_id",
    "technicians": "technician_id", "appointments": "appointment_id", "work_orders": "work_order_id",
    "parts": "part_id", "part_usage": "usage_id", "financials": "work_order_id", "feedback": "feedback_id",
}
VALID_STATUS = {"Completed", "Cancelled", "No-Show"}
RIZTA_EXCLUDED = {"P019", "P020", "P025"}  # 450-series-only parts


# --------------------------------------------------------------------------- #
# Generator: determinism and structure
# --------------------------------------------------------------------------- #
class TestDeterminism:
    def test_same_seed_gives_identical_tables(self):
        a = ServiceDataGenerator(seed=5, n_vehicles=150).generate()
        b = ServiceDataGenerator(seed=5, n_vehicles=150).generate()
        assert a.keys() == b.keys()
        for name in a:
            pd.testing.assert_frame_equal(a[name], b[name], obj=name)

    def test_different_seed_changes_output(self):
        a = ServiceDataGenerator(seed=5, n_vehicles=150).generate()
        b = ServiceDataGenerator(seed=6, n_vehicles=150).generate()
        assert not a["appointments"].equals(b["appointments"])

    def test_inject_defects_is_deterministic(self, small_clean_tables):
        raw1, m1 = inject_defects(small_clean_tables, seed=3)
        raw2, m2 = inject_defects(small_clean_tables, seed=3)
        assert m1 == m2
        for name in raw1:
            pd.testing.assert_frame_equal(raw1[name], raw2[name], obj=name)

    def test_different_defect_seed_changes_defects(self, small_clean_tables):
        raw1, _ = inject_defects(small_clean_tables, seed=3)
        raw2, _ = inject_defects(small_clean_tables, seed=4)
        assert not raw1["appointments"].equals(raw2["appointments"])

    def test_constructor_honours_n_vehicles(self):
        tables = ServiceDataGenerator(seed=1, n_vehicles=120).generate()
        # Customers own several vehicles, so the last customer may overshoot the target slightly.
        assert 120 <= len(tables["vehicles"]) < 120 + 21


class TestSchema:
    def test_all_tables_present(self, small_clean_tables):
        assert set(small_clean_tables) == set(EXPECTED_COLUMNS)

    @pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
    def test_columns_in_order(self, small_clean_tables, table):
        assert list(small_clean_tables[table].columns) == EXPECTED_COLUMNS[table]

    @pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
    def test_tables_not_empty(self, small_clean_tables, table):
        assert len(small_clean_tables[table]) > 0

    def test_no_simulation_columns_leak_into_vehicles(self, small_clean_tables):
        assert not [c for c in small_clean_tables["vehicles"].columns if c.startswith("sim_")]

    def test_reference_tables_mirror_reference_data(self, small_clean_tables):
        assert len(small_clean_tables["service_centers"]) == len(CENTRES)
        assert len(small_clean_tables["parts"]) == len(PARTS)
        assert set(small_clean_tables["technicians"]["center_id"]) == {c.center_id for c in CENTRES}


class TestKeys:
    @pytest.mark.parametrize("table, key", sorted(PRIMARY_KEYS.items()))
    def test_primary_key_unique_and_not_null(self, small_clean_tables, table, key):
        col = small_clean_tables[table][key]
        assert col.notna().all()
        assert col.is_unique

    @pytest.mark.parametrize(
        "child, column, parent, parent_key",
        [
            ("vehicles", "customer_id", "customers", "customer_id"),
            ("technicians", "center_id", "service_centers", "center_id"),
            ("appointments", "vehicle_id", "vehicles", "vehicle_id"),
            ("appointments", "center_id", "service_centers", "center_id"),
            ("work_orders", "appointment_id", "appointments", "appointment_id"),
            ("work_orders", "technician_id", "technicians", "technician_id"),
            ("part_usage", "work_order_id", "work_orders", "work_order_id"),
            ("part_usage", "part_id", "parts", "part_id"),
            ("financials", "work_order_id", "work_orders", "work_order_id"),
            ("feedback", "work_order_id", "work_orders", "work_order_id"),
        ],
    )
    def test_foreign_keys_resolve(self, small_clean_tables, child, column, parent, parent_key):
        t = small_clean_tables
        assert t[child][column].notna().all()
        assert t[child][column].isin(t[parent][parent_key]).all()

    def test_every_work_order_has_exactly_one_financial_row(self, small_clean_tables):
        wo, fin = small_clean_tables["work_orders"], small_clean_tables["financials"]
        assert set(wo["work_order_id"]) == set(fin["work_order_id"])

    def test_at_most_one_feedback_per_work_order(self, small_clean_tables):
        assert small_clean_tables["feedback"]["work_order_id"].is_unique


# --------------------------------------------------------------------------- #
# Generator: value ranges and business rules
# --------------------------------------------------------------------------- #
class TestValueRanges:
    def test_ratings_between_1_and_5(self, small_clean_tables):
        r = small_clean_tables["feedback"]["rating"]
        assert r.between(1, 5).all()
        assert (r == r.round()).all()
        assert r.nunique() >= 3  # a real spread, not a constant

    def test_money_and_hours_never_negative(self, small_clean_tables):
        fin = small_clean_tables["financials"]
        for col in ("estimated_cost", "labor_cost", "parts_cost", "revenue"):
            assert (fin[col] >= 0).all(), col
        wo = small_clean_tables["work_orders"]
        for col in ("estimated_hours", "actual_hours", "parts_wait_hours"):
            assert (wo[col] >= 0).all(), col
        assert (wo["estimated_hours"] > 0).all()
        assert (wo["actual_hours"] >= 0.25).all()
        assert (small_clean_tables["part_usage"]["quantity"] >= 1).all()
        assert (small_clean_tables["vehicles"]["mileage_km"] >= 0).all()

    def test_work_order_time_ordering(self, small_clean_tables):
        wo = small_clean_tables["work_orders"]
        assert (wo["end_time"] >= wo["start_time"]).all()
        assert (wo["start_time"] >= wo["check_in_time"]).all()
        assert (wo["promised_ready_time"] >= wo["check_in_time"]).all()

    def test_work_order_timestamps_respect_shop_hours(self, small_clean_tables):
        wo = small_clean_tables["work_orders"]
        for col in ("check_in_time", "start_time", "end_time", "promised_ready_time"):
            ts = pd.to_datetime(wo[col])
            assert (ts.dt.weekday != 6).all(), f"{col} falls on a Sunday"
            minutes = ts.dt.hour * 60 + ts.dt.minute
            assert (minutes >= 9 * 60).all(), f"{col} before opening"
            assert (minutes <= 19 * 60).all(), f"{col} after closing"

    def test_appointment_statuses_and_reasons(self, small_clean_tables):
        a = small_clean_tables["appointments"]
        assert set(a["status"]) == VALID_STATUS
        cancelled = a["status"] == "Cancelled"
        assert a.loc[cancelled, "cancellation_reason"].notna().all()
        assert a.loc[~cancelled, "cancellation_reason"].isna().all()

    def test_appointment_dates_inside_period_and_booked_before_visit(self, small_clean_tables):
        a = small_clean_tables["appointments"]
        assert (a["scheduled_date"] >= PERIOD_START).all()
        assert (a["scheduled_date"] <= PERIOD_END).all()
        assert (a["booking_date"] <= a["scheduled_date"]).all()
        assert all(d.weekday() != 6 for d in a["scheduled_date"]), "appointments on closed Sunday"

    def test_slot_format(self, small_clean_tables):
        slots = small_clean_tables["appointments"]["scheduled_slot"]
        assert slots.str.fullmatch(r"\d{2}:\d{2}").all()
        hours = slots.str[:2].astype(int)
        assert hours.between(9, 17).all()

    def test_slot_minutes_are_valid_clock_minutes(self, small_clean_tables):
        minutes = small_clean_tables["appointments"]["scheduled_slot"].str[3:].astype(int)
        assert minutes.between(0, 59).all()

    def test_service_types_are_known(self, small_clean_tables):
        assert set(small_clean_tables["work_orders"]["service_type"]) <= set(SERVICE_TYPES)
        assert set(small_clean_tables["appointments"]["requested_service_type"]) <= set(SERVICE_TYPES)

    def test_work_order_service_type_matches_appointment(self, small_clean_tables):
        m = small_clean_tables["work_orders"].merge(small_clean_tables["appointments"], on="appointment_id")
        assert (m["service_type"] == m["requested_service_type"]).all()

    def test_check_in_is_on_scheduled_date(self, small_clean_tables):
        m = small_clean_tables["work_orders"].merge(small_clean_tables["appointments"], on="appointment_id")
        assert (pd.to_datetime(m["check_in_time"]).dt.date == m["scheduled_date"]).all()

    def test_feedback_date_not_before_job_end(self, small_clean_tables):
        m = small_clean_tables["feedback"].merge(small_clean_tables["work_orders"], on="work_order_id")
        assert (pd.to_datetime(m["feedback_date"]) >= pd.to_datetime(m["end_time"]).dt.normalize()).all()

    def test_everything_inside_reporting_window_for_visits_started(self, small_clean_tables):
        wo = small_clean_tables["work_orders"]
        assert pd.to_datetime(wo["check_in_time"]).dt.date.between(PERIOD_START, PERIOD_END).all()

    def test_technician_and_centre_masters(self, small_clean_tables):
        tech = small_clean_tables["technicians"]
        assert set(tech["skill_level"]) <= {"Junior", "Mid", "Senior", "Master"}
        assert (tech["hourly_cost"] > 0).all()
        # every centre has at least one senior-or-master technician unless it is the junior-heavy roster
        seniors = tech[tech["skill_level"].isin(["Senior", "Master"])]["center_id"]
        junior_heavy = {c.center_id for c in CENTRES if c.junior_heavy_roster}
        assert set(c.center_id for c in CENTRES) - junior_heavy <= set(seniors)
        assert set(tech[tech["center_id"].isin(junior_heavy)]["skill_level"]) <= {"Junior", "Mid"}

    def test_work_orders_executed_by_technician_of_the_appointment_centre(self, small_clean_tables):
        t = small_clean_tables
        m = (t["work_orders"].merge(t["appointments"][["appointment_id", "center_id"]], on="appointment_id")
             .merge(t["technicians"][["technician_id", "center_id"]], on="technician_id", suffixes=("_appt", "_tech")))
        assert len(m) == len(t["work_orders"])
        assert (m["center_id_appt"] == m["center_id_tech"]).all()


class TestBusinessRules:
    def test_work_orders_only_for_completed_appointments(self, small_clean_tables):
        a, wo = small_clean_tables["appointments"], small_clean_tables["work_orders"]
        status = a.set_index("appointment_id")["status"]
        assert (wo["appointment_id"].map(status) == "Completed").all()

    def test_every_completed_appointment_has_exactly_one_work_order(self, small_clean_tables):
        a, wo = small_clean_tables["appointments"], small_clean_tables["work_orders"]
        completed = set(a.loc[a["status"] == "Completed", "appointment_id"])
        assert set(wo["appointment_id"]) == completed
        assert wo["appointment_id"].is_unique

    def test_rework_is_free_and_only_rework_is_free(self, small_clean_tables):
        fin = small_clean_tables["financials"]
        rework = fin["billing_type"] == "Rework (No Charge)"
        assert rework.sum() > 0, "fixture should contain comeback (rework) jobs"
        assert (fin.loc[rework, "revenue"] == 0).all()
        assert (fin.loc[~rework, "revenue"] > 0).all()

    def test_billing_types_are_known(self, small_clean_tables):
        assert set(small_clean_tables["financials"]["billing_type"]) <= {
            "Rework (No Charge)", "Warranty", "Service Plan", "Customer Paid"}

    def test_parts_cost_equals_usage_times_unit_cost(self, small_clean_tables):
        t = small_clean_tables
        usage = t["part_usage"].merge(t["parts"][["part_id", "unit_cost"]], on="part_id")
        expected = (usage["quantity"] * usage["unit_cost"]).groupby(usage["work_order_id"]).sum()
        fin = t["financials"].set_index("work_order_id")
        expected = expected.reindex(fin.index).fillna(0.0)
        assert (fin["parts_cost"] - expected).abs().max() < 0.01

    def test_labour_cost_equals_hours_times_technician_rate(self, small_clean_tables):
        t = small_clean_tables
        m = (t["work_orders"].merge(t["technicians"][["technician_id", "hourly_cost"]], on="technician_id")
             .merge(t["financials"], on="work_order_id"))
        assert ((m["actual_hours"] * m["hourly_cost"]) - m["labor_cost"]).abs().max() < 0.02

    def test_model_year_not_before_model_launch(self, small_clean_tables):
        v = small_clean_tables["vehicles"]
        launch_year = v["model"].map({m: int(info[2][:4]) for m, info in MODELS.items()})
        assert (v["model_year"] >= launch_year).all()
        launch_date = v["model"].map({m: date.fromisoformat(info[2]) for m, info in MODELS.items()})
        assert (v["purchase_date"] >= launch_date).all()
        assert (v["model_year"] == v["purchase_date"].map(lambda d: d.year)).all()

    def test_models_variants_and_battery_are_consistent(self, small_clean_tables):
        v = small_clean_tables["vehicles"]
        assert set(v["model"]) <= set(MODELS)
        for model, (category, variants, _) in MODELS.items():
            sub = v[v["model"] == model]
            assert set(sub["vehicle_category"]) <= {category}
            allowed = {name: kwh for name, kwh, _ in variants}
            assert set(sub["variant"]) <= set(allowed)
            assert all(allowed[var] == kwh for var, kwh in zip(sub["variant"], sub["battery_kwh"]))

    def test_registration_date_is_first_purchase(self, small_clean_tables):
        t = small_clean_tables
        first = t["vehicles"].groupby("customer_id")["purchase_date"].min()
        reg = t["customers"].set_index("customer_id")["registration_date"]
        assert (reg == first.reindex(reg.index)).all()

    def test_part_usage_lines_unique_per_work_order_and_quantity_bounded(self, small_clean_tables):
        pu = small_clean_tables["part_usage"]
        assert not pu.duplicated(["work_order_id", "part_id"]).any()
        max_qty = {"P005": 1, "P006": 1, "P007": 2, "P034": 2}
        assert (pu["quantity"] <= pu["part_id"].map(max_qty).fillna(2)).all()

    def test_work_order_odometer_never_exceeds_current_vehicle_mileage(self, small_clean_tables):
        t = small_clean_tables
        m = (t["work_orders"].merge(t["appointments"][["appointment_id", "vehicle_id"]], on="appointment_id")
             .merge(t["vehicles"][["vehicle_id", "mileage_km"]], on="vehicle_id"))
        assert (m["odometer_km"] >= 0).all()
        assert (m["odometer_km"] <= m["mileage_km"] + 1).all()

    def test_first_service_not_before_purchase(self, small_clean_tables):
        t = small_clean_tables
        m = (t["work_orders"].merge(t["appointments"][["appointment_id", "vehicle_id"]], on="appointment_id")
             .merge(t["vehicles"][["vehicle_id", "purchase_date"]], on="vehicle_id"))
        assert (pd.to_datetime(m["check_in_time"]).dt.date >= m["purchase_date"]).all()


class TestPartCompatibility:
    @pytest.fixture
    def usage_with_model(self, small_clean_tables):
        t = small_clean_tables
        return (t["part_usage"]
                .merge(t["work_orders"][["work_order_id", "appointment_id"]], on="work_order_id")
                .merge(t["appointments"][["appointment_id", "vehicle_id"]], on="appointment_id")
                .merge(t["vehicles"][["vehicle_id", "model"]], on="vehicle_id"))

    def test_rizta_never_gets_450_series_parts(self, usage_with_model):
        rizta = usage_with_model[usage_with_model["model"] == "Ather Rizta"]
        assert len(rizta) > 50, "need a meaningful Rizta sample for the check to be non-vacuous"
        assert not (set(rizta["part_id"]) & RIZTA_EXCLUDED)

    def test_apex_body_kit_only_on_apex(self, usage_with_model):
        kit = usage_with_model[usage_with_model["part_id"] == "P033"]
        assert set(kit["model"]) <= {"Ather 450 Apex"}
        assert (usage_with_model["model"] == "Ather 450 Apex").sum() > 0

    def test_every_part_matches_vehicle_model(self, usage_with_model, small_clean_tables):
        compat = small_clean_tables["parts"].set_index("part_id")["compatible_models"]
        c = usage_with_model["part_id"].map(compat)

        def ok(rule, model):
            return rule == "All" or rule == model or (rule == "450 Series" and model.startswith("Ather 450"))

        assert all(ok(r, m) for r, m in zip(c, usage_with_model["model"]))

    def test_rizta_gets_rizta_specific_parts_when_available(self, usage_with_model):
        # sanity check that the filter is not hiding the Rizta equivalents
        rizta = usage_with_model[usage_with_model["model"] == "Ather Rizta"]
        assert set(rizta["part_id"]) & {"P021", "P026"}


# --------------------------------------------------------------------------- #
# inject_defects
# --------------------------------------------------------------------------- #
def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates().reset_index(drop=True)


class TestInjectDefects:
    def test_input_tables_not_mutated(self, small_clean_tables):
        before = {k: v.copy(deep=True) for k, v in small_clean_tables.items()}
        inject_defects(small_clean_tables, seed=9)
        for name in before:
            pd.testing.assert_frame_equal(before[name], small_clean_tables[name], obj=name)

    def test_manifest_shape(self, small_defect_manifest):
        assert set(small_defect_manifest) == {"customers", "vehicles", "appointments", "work_orders",
                                              "financials", "feedback", "part_usage"}
        for table, counts in small_defect_manifest.items():
            assert counts, table
            assert all(isinstance(n, int) and n >= 1 for n in counts.values()), (table, counts)

    def test_unaffected_reference_tables_unchanged(self, small_clean_tables, small_raw_tables):
        for name in ("service_centers", "technicians", "parts"):
            pd.testing.assert_frame_equal(small_clean_tables[name], small_raw_tables[name])

    def test_date_columns_become_text(self, small_raw_tables):
        wo = small_raw_tables["work_orders"]
        for col in ("check_in_time", "start_time", "end_time", "promised_ready_time"):
            non_null = wo[col].dropna()
            assert non_null.map(lambda x: isinstance(x, str)).all(), col
        assert small_raw_tables["vehicles"]["purchase_date"].map(lambda x: isinstance(x, str)).all()

    # ---- duplicates ---------------------------------------------------- #
    @pytest.mark.parametrize("table", ["customers", "appointments", "work_orders", "financials", "feedback"])
    def test_duplicate_rows_match_manifest(self, small_raw_tables, small_defect_manifest, table):
        raw = small_raw_tables[table]
        assert int(raw.duplicated().sum()) == small_defect_manifest[table]["duplicate_rows"]
        assert len(raw) == len(_dedup(raw)) + small_defect_manifest[table]["duplicate_rows"]

    def test_deduplicated_raw_row_counts_equal_clean_counts(self, small_raw_tables, small_clean_tables):
        for table in ("customers", "appointments", "work_orders", "financials", "feedback"):
            assert len(_dedup(small_raw_tables[table])) == len(small_clean_tables[table])

    # ---- customers / vehicles ------------------------------------------ #
    def test_region_variants(self, small_raw_tables, small_defect_manifest):
        c = _dedup(small_raw_tables["customers"])
        bad = ~c["region"].isin(["North", "South", "East", "West"])
        assert int(bad.sum()) == small_defect_manifest["customers"]["region_format_variants"]
        assert (c.loc[bad, "region"].str.strip().str.lower().isin(["north", "south", "east", "west"])).all()

    def test_vehicle_defects(self, small_raw_tables, small_clean_tables, small_defect_manifest):
        raw, clean = small_raw_tables["vehicles"], small_clean_tables["vehicles"]
        man = small_defect_manifest["vehicles"]
        assert len(raw) == len(clean)
        assert int((~raw["model"].isin(list(MODELS))).sum()) == man["model_name_variants"]
        assert int((raw["mileage_km"] != clean["mileage_km"]).sum()) == man["impossible_mileage"]
        assert int(((raw["mileage_km"] < 0) | (raw["mileage_km"] >= 400_000)).sum()) == man["impossible_mileage"]
        assert int((raw["model_year"] != clean["model_year"]).sum()) == man["impossible_model_year"]
        first_year = clean["model"].map({"Ather 450X": 2020, "Ather 450 Apex": 2024, "Ather Rizta": 2024})
        assert int((raw["model_year"] < first_year).sum()) == man["impossible_model_year"]

    # ---- appointments --------------------------------------------------- #
    def test_status_variants(self, small_raw_tables, small_defect_manifest):
        a = _dedup(small_raw_tables["appointments"])
        assert int((~a["status"].isin(VALID_STATUS)).sum()) == small_defect_manifest["appointments"]["status_format_variants"]

    def test_ddmmyyyy_dates(self, small_raw_tables, small_defect_manifest):
        a = _dedup(small_raw_tables["appointments"])
        n = int(a["scheduled_date"].str.fullmatch(r"\d{2}/\d{2}/\d{4}").sum())
        assert n == small_defect_manifest["appointments"]["ddmmyyyy_dates"]
        iso = a["scheduled_date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}")
        assert (iso | a["scheduled_date"].str.fullmatch(r"\d{2}/\d{2}/\d{4}")).all()

    def test_missing_center_ids(self, small_raw_tables, small_defect_manifest):
        a = _dedup(small_raw_tables["appointments"])
        assert int(a["center_id"].isna().sum()) == small_defect_manifest["appointments"]["missing_center_id"]

    def test_missing_center_only_on_appointments_with_work_orders(self, small_raw_tables):
        a = _dedup(small_raw_tables["appointments"])
        with_wo = set(small_raw_tables["work_orders"]["appointment_id"])
        assert a.loc[a["center_id"].isna(), "appointment_id"].isin(with_wo).all()

    def test_orphan_vehicle_ids(self, small_raw_tables, small_defect_manifest):
        a = _dedup(small_raw_tables["appointments"])
        orphan = ~a["vehicle_id"].isin(small_raw_tables["vehicles"]["vehicle_id"])
        assert int(orphan.sum()) == small_defect_manifest["appointments"]["orphan_vehicle_id"]

    # ---- work orders ----------------------------------------------------- #
    def test_swapped_start_end(self, small_raw_tables, small_defect_manifest):
        wo = _dedup(small_raw_tables["work_orders"])
        start, end = pd.to_datetime(wo["start_time"]), pd.to_datetime(wo["end_time"])
        assert int((end < start).sum()) == small_defect_manifest["work_orders"]["start_end_swapped"]

    def test_technician_defects(self, small_raw_tables, small_defect_manifest):
        wo = _dedup(small_raw_tables["work_orders"])
        man = small_defect_manifest["work_orders"]
        assert int(wo["technician_id"].isna().sum()) == man["missing_technician_id"]
        assert int((wo["technician_id"] == "T999").sum()) == man["orphan_technician_id"]
        assert int(wo["start_time"].isna().sum()) == man["missing_start_time"]

    def test_service_type_variants(self, small_raw_tables, small_defect_manifest):
        wo = _dedup(small_raw_tables["work_orders"])
        n = int((~wo["service_type"].isin(list(SERVICE_TYPES))).sum())
        assert n == small_defect_manifest["work_orders"]["service_type_format_variants"]

    # ---- financials ------------------------------------------------------- #
    def test_financial_defects(self, small_raw_tables, small_clean_tables, small_defect_manifest):
        raw = _dedup(small_raw_tables["financials"]).set_index("work_order_id")
        clean = small_clean_tables["financials"].set_index("work_order_id").loc[raw.index]
        man = small_defect_manifest["financials"]
        negative = (raw[["revenue", "labor_cost"]] < 0).any(axis=1)
        assert int(negative.sum()) == man["negative_amounts"]
        assert int(raw["parts_cost"].isna().sum()) == man["missing_parts_cost"]
        shifted = (raw["revenue"] > 0) & (raw["revenue"] != clean["revenue"])
        assert int(shifted.sum()) == man["revenue_decimal_shift_x100"]
        assert ((raw.loc[shifted, "revenue"] / clean.loc[shifted, "revenue"]) .round(6) == 100).all()

    # ---- feedback ---------------------------------------------------------- #
    def test_feedback_defects(self, small_raw_tables, small_defect_manifest):
        fb = _dedup(small_raw_tables["feedback"])
        man = small_defect_manifest["feedback"]
        assert int(fb["rating"].isna().sum()) == man["missing_rating"]
        out = fb["rating"].notna() & ~fb["rating"].between(1, 5)
        assert int(out.sum()) == man["rating_out_of_range"]
        assert set(fb.loc[out, "rating"].astype(float)) <= {0.0, 6.0, 10.0}

    # ---- part usage --------------------------------------------------------- #
    def test_part_usage_defects(self, small_raw_tables, small_defect_manifest):
        pu = small_raw_tables["part_usage"]
        man = small_defect_manifest["part_usage"]
        assert int((pu["quantity"] <= 0).sum()) == man["non_positive_quantity"]
        assert int((pu["part_id"] == "P999").sum()) == man["orphan_part_id"]
        assert not pu["usage_id"].duplicated().any()

    def test_minimum_one_defect_even_for_tiny_tables(self):
        # max(1, int(n * frac)) means every defect class fires at least once.
        tables = ServiceDataGenerator(seed=2, n_vehicles=60).generate()
        _, manifest = inject_defects(tables, seed=2)
        assert all(n >= 1 for counts in manifest.values() for n in counts.values())


# --------------------------------------------------------------------------- #
# main()
# --------------------------------------------------------------------------- #
class TestMain:
    @pytest.fixture
    def small_main(self, monkeypatch, tmp_path):
        raw_dir = tmp_path / "raw_out"
        monkeypatch.setattr(gd, "RAW_DIR", raw_dir)
        real = gd.ServiceDataGenerator
        monkeypatch.setattr(gd, "ServiceDataGenerator", lambda: real(seed=SEED, n_vehicles=150))
        return raw_dir

    def test_main_writes_csvs_and_manifest(self, small_main, capsys):
        assert not small_main.exists()
        gd.main()
        for table in EXPECTED_COLUMNS:
            path = small_main / f"{table}.csv"
            assert path.exists(), table
            df = pd.read_csv(path)
            assert list(df.columns) == EXPECTED_COLUMNS[table]
        manifest = json.loads((small_main / "generation_manifest.json").read_text(encoding="utf-8"))
        assert manifest["seed"] == SEED
        assert manifest["period"] == [PERIOD_START.isoformat(), PERIOD_END.isoformat()]
        assert set(manifest["row_counts"]) == set(EXPECTED_COLUMNS)
        for table, n in manifest["row_counts"].items():
            assert len(pd.read_csv(small_main / f"{table}.csv")) == n
        assert "duplicate_rows" in manifest["injected_defects"]["appointments"]
        out = capsys.readouterr().out
        assert "work_orders" in out and "appointments" in out

    def test_main_does_not_touch_real_raw_dir(self, small_main):
        from src.config import RAW_DIR as real_raw
        before = sorted(p.name for p in real_raw.glob("*")) if real_raw.exists() else []
        gd.main()
        after = sorted(p.name for p in real_raw.glob("*")) if real_raw.exists() else []
        assert before == after

    def test_main_is_reproducible(self, small_main):
        gd.main()
        first = (small_main / "work_orders.csv").read_bytes()
        gd.main()
        assert (small_main / "work_orders.csv").read_bytes() == first

    def test_manifest_counts_match_written_csv(self, small_main):
        gd.main()
        manifest = json.loads((small_main / "generation_manifest.json").read_text(encoding="utf-8"))
        fb = pd.read_csv(small_main / "feedback.csv")
        assert int(fb.duplicated().sum()) == manifest["injected_defects"]["feedback"]["duplicate_rows"]


def test_datetime_format_constant_round_trips():
    ts = datetime(2025, 3, 3, 9, 5, 7)
    assert datetime.strptime(ts.strftime(gd.DT_FMT), gd.DT_FMT) == ts
