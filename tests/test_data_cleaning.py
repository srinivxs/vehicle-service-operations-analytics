"""Unit tests for src.data_cleaning: helpers, DQ01-DQ20 rules, fact builders.

All inputs are tiny hand-built DataFrames so each rule can be asserted in isolation.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import data_cleaning as dc
from src.config import PERIOD_END, PERIOD_START, PRODUCTIVE_HOURS_PER_DAY
from src.data_cleaning import CleaningLog

pytestmark = pytest.mark.unit

NA = pd.NA


def affected(log: CleaningLog, rule: str, table: str | None = None, column: str | None = None) -> int:
    """Total rows_affected for matching log entries."""
    frame = log.frame()
    mask = frame["rule_id"] == rule
    if table is not None:
        mask &= frame["table"] == table
    if column is not None:
        mask &= frame["column"] == column
    assert mask.any(), f"no log entry for {rule}/{table}/{column}"
    return int(frame.loc[mask, "rows_affected"].sum())


# --------------------------------------------------------------------------- #
# Builders for tiny raw tables
# --------------------------------------------------------------------------- #
def vehicles_df(*overrides: dict) -> pd.DataFrame:
    base = dict(vehicle_id="V1", customer_id="C1", model="Ather 450X", variant="450X 3.7kWh",
                vehicle_category="Performance", battery_kwh=3.7, model_year=2024,
                purchase_date="2024-03-01", mileage_km=5000)
    rows = []
    for i, o in enumerate(overrides or ({},), start=1):
        rows.append({**base, "vehicle_id": f"V{i}", **o})
    return pd.DataFrame(rows)


def appointments_df(*overrides: dict) -> pd.DataFrame:
    base = dict(appointment_id="A1", vehicle_id="V1", center_id="C001", booking_date="2025-03-01",
                scheduled_date="2025-03-03", scheduled_slot="10:00", booking_channel="Ather App",
                requested_service_type="Brake Service", status="Completed", cancellation_reason=None)
    rows = []
    for i, o in enumerate(overrides or ({},), start=1):
        rows.append({**base, "appointment_id": f"A{i}", **o})
    return pd.DataFrame(rows)


def work_orders_df(*overrides: dict) -> pd.DataFrame:
    base = dict(work_order_id="W1", appointment_id="A1", technician_id="T1", service_type="Brake Service",
                check_in_time="2025-03-03 09:00:00", start_time="2025-03-03 09:30:00",
                end_time="2025-03-03 12:00:00", promised_ready_time="2025-03-03 13:00:00",
                estimated_hours=2.0, actual_hours=2.0, parts_wait_hours=0.0, odometer_km=1000,
                additional_work_found=False, qc_passed_first_time=True)
    rows = []
    for i, o in enumerate(overrides or ({},), start=1):
        rows.append({**base, "work_order_id": f"W{i}", "appointment_id": f"A{i}", **o})
    return pd.DataFrame(rows)


def technicians_df() -> pd.DataFrame:
    return pd.DataFrame({"technician_id": ["T1", "T2"], "center_id": ["C001", "C002"],
                         "skill_level": ["Senior", "Junior"]})


def parts_df() -> pd.DataFrame:
    return pd.DataFrame({"part_id": ["P1", "P2", "P3"], "unit_cost": [100.0, 50.0, 1000.0]})


def part_usage_df(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame([{"usage_id": f"U{i}", "work_order_id": w, "part_id": p, "quantity": q}
                         for i, (w, p, q) in enumerate(rows, start=1)],
                        columns=["usage_id", "work_order_id", "part_id", "quantity"])


def financials_df(*overrides: dict) -> pd.DataFrame:
    base = dict(work_order_id="W1", billing_type="Customer Paid", estimated_cost=1000.0,
                labor_cost=600.0, parts_cost=400.0, revenue=2000.0)
    rows = []
    for i, o in enumerate(overrides or ({},), start=1):
        rows.append({**base, "work_order_id": f"W{i}", **o})
    return pd.DataFrame(rows)


def ids(prefix: str, n: int) -> pd.DataFrame:
    return pd.DataFrame({f"{'work_order' if prefix == 'W' else 'appointment'}_id": [f"{prefix}{i}" for i in range(1, n + 1)]})


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class TestCleaningLog:
    def test_add_records_entry_with_int_rows(self):
        log = CleaningLog()
        log.add("DQ99", "t", "c", "issue", "action", np.int64(7))
        entry = log.entries[0]
        assert entry == {"rule_id": "DQ99", "table": "t", "column": "c", "issue": "issue",
                         "action": "action", "rows_affected": 7}
        assert type(entry["rows_affected"]) is int

    def test_frame_columns_even_when_empty(self):
        frame = CleaningLog().frame()
        assert list(frame.columns) == ["rule_id", "table", "column", "issue", "action", "rows_affected"]
        assert frame.empty

    def test_entries_are_not_shared_between_instances(self):
        a, b = CleaningLog(), CleaningLog()
        a.add("DQ01", "t", "*", "i", "a", 1)
        assert b.entries == []


class TestNormaliseText:
    def test_trims_and_collapses_whitespace(self):
        out = dc.normalise_text(pd.Series(["  hello   world ", "a\t\tb\n c", "x"]))
        assert out.tolist() == ["hello world", "a b c", "x"]

    def test_keeps_missing_missing(self):
        out = dc.normalise_text(pd.Series(["x ", None, np.nan, pd.NA]))
        assert out.isna().tolist() == [False, True, True, True]
        assert out.iloc[0] == "x"

    def test_empty_and_whitespace_only(self):
        assert dc.normalise_text(pd.Series(["", "   "])).tolist() == ["", ""]

    def test_empty_series(self):
        assert len(dc.normalise_text(pd.Series([], dtype="object"))) == 0

    def test_non_string_input_is_stringified(self):
        assert dc.normalise_text(pd.Series([1, 20])).tolist() == ["1", "20"]

    def test_unicode_and_sql_characters_survive(self):
        out = dc.normalise_text(pd.Series([" Zoë  ☃ ", "'; DROP TABLE x;--  "]))
        assert out.tolist() == ["Zoë ☃", "'; DROP TABLE x;--"]


class TestParseDatetime:
    def test_iso_date_and_datetime(self):
        out = dc.parse_datetime(pd.Series(["2025-03-04", "2025-03-04 10:15:30", "2025-03-04T10:15:30"]))
        assert out.tolist() == [pd.Timestamp("2025-03-04"), pd.Timestamp("2025-03-04 10:15:30"),
                                pd.Timestamp("2025-03-04 10:15:30")]

    def test_indian_day_first_format(self):
        out = dc.parse_datetime(pd.Series(["04/03/2025", "31/12/2025", "01/02/2025"]))
        assert out.tolist() == [pd.Timestamp("2025-03-04"), pd.Timestamp("2025-12-31"), pd.Timestamp("2025-02-01")]

    def test_month_first_is_not_accepted(self):
        assert dc.parse_datetime(pd.Series(["12/31/2025"])).isna().all()

    def test_garbage_and_missing_become_nat(self):
        out = dc.parse_datetime(pd.Series(["not a date", "", None, np.nan, "2025-13-45"]))
        assert out.isna().all()

    def test_mixed_series_keeps_positions(self):
        out = dc.parse_datetime(pd.Series(["2025-01-02", "03/01/2025", "bad", "2025-01-04"]))
        assert out.isna().tolist() == [False, False, True, False]
        assert out.iloc[1] == pd.Timestamp("2025-01-03")

    def test_result_is_datetime_dtype(self):
        out = dc.parse_datetime(pd.Series(["2025-01-02", "03/01/2025"]))
        assert pd.api.types.is_datetime64_any_dtype(out)


class TestCanonicalCase:
    def test_maps_case_and_whitespace_variants(self):
        out = dc.canonical_case(pd.Series(["SOUTH", " north ", "East", "wEsT"]), dc.CANONICAL_REGIONS)
        assert out.tolist() == ["South", "North", "East", "West"]

    def test_unknown_and_missing_become_na(self):
        out = dc.canonical_case(pd.Series(["Central", None]), ["North"])
        assert out.isna().all()

    def test_internal_whitespace_collapsed_before_lookup(self):
        out = dc.canonical_case(pd.Series(["Periodic   Service"]), ["Periodic Service"])
        assert out.tolist() == ["Periodic Service"]


class TestDuplicateHelpers:
    def test_exact_duplicates_removed_and_logged(self):
        log = CleaningLog()
        df = pd.DataFrame({"k": [1, 1, 2], "v": ["a", "a", "b"]})
        out = dc.drop_exact_duplicates(df, "t", log)
        assert out["k"].tolist() == [1, 2]
        assert out.index.tolist() == [0, 1]  # index reset
        assert affected(log, "DQ01", "t") == 1

    def test_exact_duplicates_none_logged_as_zero(self):
        log = CleaningLog()
        dc.drop_exact_duplicates(pd.DataFrame({"k": [1, 2]}), "t", log)
        assert affected(log, "DQ01", "t") == 0

    def test_exact_duplicates_treat_nulls_as_equal(self):
        log = CleaningLog()
        out = dc.drop_exact_duplicates(pd.DataFrame({"k": [1, 1], "v": [None, None]}), "t", log)
        assert len(out) == 1

    def test_duplicate_key_keeps_first_even_with_conflicting_values(self):
        log = CleaningLog()
        df = pd.DataFrame({"customer_id": ["C1", "C1", "C2"], "city": ["Pune", "Delhi", "Goa"]})
        out = dc.drop_duplicate_keys(df, "customers", log)
        assert out["city"].tolist() == ["Pune", "Goa"]
        assert affected(log, "DQ02", "customers", "customer_id") == 1

    def test_duplicate_key_uses_table_specific_key(self):
        log = CleaningLog()
        df = pd.DataFrame({"work_order_id": ["W1", "W1"], "revenue": [1, 2]})
        out = dc.drop_duplicate_keys(df, "financials", log)
        assert out["revenue"].tolist() == [1]
        assert log.entries[0]["column"] == "work_order_id"


class TestProfile:
    def test_profile_counts(self):
        raw = {
            "customers": pd.DataFrame({"customer_id": ["C1", "C1", "C2", "C3"],
                                       "region": ["N", "N", None, "S"],
                                       "city": [None, None, None, "X"]}),
            "parts": pd.DataFrame({"part_id": ["P1", "P1"], "unit_cost": [1, 2]}),
        }
        prof = dc.profile(raw).set_index("table")
        c = prof.loc["customers"]
        assert (c["raw_rows"], c["exact_duplicates"], c["duplicate_keys"], c["null_cells"]) == (4, 1, 1, 4)
        assert c["columns_with_nulls"] == "region (1), city (3)"
        p = prof.loc["parts"]
        assert (p["exact_duplicates"], p["duplicate_keys"], p["null_cells"]) == (0, 1, 0)
        assert p["columns_with_nulls"] == "-"


class TestWorkingDays:
    @pytest.mark.parametrize(
        "start, end, expected",
        [
            ("2025-03-03", "2025-03-09", 6),   # Mon..Sun
            ("2025-03-02", "2025-03-02", 0),   # a lone Sunday
            ("2025-03-03", "2025-03-03", 1),   # a lone Monday
            ("2025-03-08", "2025-03-10", 2),   # Sat, (Sun), Mon
            ("2025-03-05", "2025-03-04", 0),   # reversed range is empty
            ("2025-03-01", "2025-03-31", 26),  # March 2025: 5 Sundays
        ],
    )
    def test_counts_monday_to_saturday(self, start, end, expected):
        assert dc.working_days(pd.Timestamp(start), pd.Timestamp(end)) == expected


# --------------------------------------------------------------------------- #
# customers
# --------------------------------------------------------------------------- #
class TestCleanCustomers:
    def _df(self):
        return pd.DataFrame({
            "customer_id": ["C1", "C2", "C3", "C4", "C4"],
            "customer_type": ["Individual", " Fleet ", "Corporate", "Individual", "Individual"],
            "city": ["Pune"] * 5,
            "region": ["West", "SOUTH", " north ", "East", "East"],
            "registration_date": ["2024-01-05", "05/01/2024", "2024-02-01", "2024-03-01", "2024-03-01"],
        })

    def test_dq01_exact_duplicate_removed(self):
        log = CleaningLog()
        out = dc.clean_customers(self._df(), log)
        assert out["customer_id"].tolist() == ["C1", "C2", "C3", "C4"]
        assert affected(log, "DQ01", "customers") == 1

    def test_dq03_region_standardised_and_counted(self):
        log = CleaningLog()
        out = dc.clean_customers(self._df(), log)
        assert out["region"].tolist() == ["West", "South", "North", "East"]
        assert affected(log, "DQ03", "customers", "region") == 2

    def test_customer_type_trimmed_and_dates_parsed_to_date(self):
        out = dc.clean_customers(self._df(), CleaningLog())
        assert out["customer_type"].tolist() == ["Individual", "Fleet", "Corporate", "Individual"]
        assert out["registration_date"].tolist() == [date(2024, 1, 5), date(2024, 1, 5), date(2024, 2, 1),
                                                     date(2024, 3, 1)]

    def test_dq02_conflicting_duplicate_key_keeps_first(self):
        df = pd.DataFrame({"customer_id": ["C1", "C1"], "customer_type": ["Individual", "Fleet"],
                           "city": ["Pune", "Pune"], "region": ["West", "West"],
                           "registration_date": ["2024-01-01", "2024-01-02"]})
        log = CleaningLog()
        out = dc.clean_customers(df, log)
        assert out["customer_type"].tolist() == ["Individual"]
        assert affected(log, "DQ02", "customers") == 1


# --------------------------------------------------------------------------- #
# vehicles
# --------------------------------------------------------------------------- #
class TestCleanVehicles:
    def test_dq03_model_aliases_mapped(self):
        df = vehicles_df(
            {"model": "ather 450x"}, {"model": "450X"}, {"model": " Ather 450 apex ", "model_year": 2025,
                                                         "purchase_date": "2025-01-01"},
            {"model": "450 Apex", "model_year": 2025, "purchase_date": "2025-01-01"},
            {"model": "Rizta", "model_year": 2025, "purchase_date": "2025-01-01"},
            {"model": "ATHER RIZTA", "model_year": 2025, "purchase_date": "2025-01-01"},
            {"model": "Ather 450X"},
        )
        log = CleaningLog()
        out = dc.clean_vehicles(df, log)
        assert out["model"].tolist() == ["Ather 450X", "Ather 450X", "Ather 450 Apex", "Ather 450 Apex",
                                         "Ather Rizta", "Ather Rizta", "Ather 450X"]
        assert affected(log, "DQ03", "vehicles", "model") == 6

    def test_unknown_model_becomes_na_and_is_counted_by_current_rule(self):
        log = CleaningLog()
        out = dc.clean_vehicles(vehicles_df({"model": "Scooty"}), log)
        assert out["model"].isna().all()

    @pytest.mark.parametrize(
        "model, year, purchase, expected_year, flagged",
        [
            ("Ather 450X", 2019, "2023-05-01", 2023, True),    # before 450X launch year (2020)
            ("Ather 450X", 2020, "2020-06-01", 2020, False),   # first valid year
            ("Ather 450X", 2025, "2023-05-01", 2023, True),    # more than a year after purchase
            ("Ather 450X", 2024, "2023-05-01", 2024, False),   # next model year is allowed
            ("Ather 450X", 2027, "2026-02-01", 2026, True),    # beyond reporting year
            ("Ather 450 Apex", 2023, "2024-03-01", 2024, True),
            ("Ather Rizta", 2023, "2024-08-01", 2024, True),
            ("Ather Rizta", 2024, "2024-08-01", 2024, False),
        ],
    )
    def test_dq15_model_year_imputation(self, model, year, purchase, expected_year, flagged):
        log = CleaningLog()
        out = dc.clean_vehicles(vehicles_df({"model": model, "model_year": year, "purchase_date": purchase}), log)
        assert int(out["model_year"].iloc[0]) == expected_year
        assert affected(log, "DQ15", "vehicles") == int(flagged)
        assert str(out["model_year"].dtype) == "Int64"

    @pytest.mark.parametrize(
        "km, nulled",
        [(0, False), (5000, False), (-1, True), (-4000, True),
         (159_000, False), (160_000, True), (700_000, True)],
    )
    def test_dq16_mileage_nulling(self, km, nulled):
        # Purchased 2025-01-01: 637 days to period end -> 637 * 250 = 159,250 km ceiling.
        df = vehicles_df({"purchase_date": "2025-01-01", "model_year": 2025, "mileage_km": km})
        log = CleaningLog()
        out = dc.clean_vehicles(df, log)
        assert bool(out["mileage_km"].isna().iloc[0]) is nulled
        assert affected(log, "DQ16", "vehicles") == int(nulled)
        if not nulled:
            assert out["mileage_km"].iloc[0] == km

    def test_dq16_vehicle_bought_on_period_end_has_one_day_ceiling(self):
        df = vehicles_df({"purchase_date": PERIOD_END.isoformat(), "model_year": PERIOD_END.year, "mileage_km": 251},
                         {"purchase_date": PERIOD_END.isoformat(), "model_year": PERIOD_END.year, "mileage_km": 250})
        out = dc.clean_vehicles(df, CleaningLog())
        assert out["mileage_km"].isna().tolist() == [True, False]

    def test_purchase_date_converted_to_date_and_dd_mm_yyyy_accepted(self):
        out = dc.clean_vehicles(vehicles_df({"purchase_date": "01/03/2024"}), CleaningLog())
        assert out["purchase_date"].iloc[0] == date(2024, 3, 1)

    def test_exact_duplicate_and_duplicate_key(self):
        df = pd.concat([vehicles_df(), vehicles_df(), vehicles_df({"mileage_km": 9999})], ignore_index=True)
        log = CleaningLog()
        out = dc.clean_vehicles(df, log)
        assert len(out) == 1
        assert out["mileage_km"].iloc[0] == 5000          # first occurrence wins
        assert affected(log, "DQ01", "vehicles") == 1
        assert affected(log, "DQ02", "vehicles") == 1


# --------------------------------------------------------------------------- #
# appointments
# --------------------------------------------------------------------------- #
class TestCleanAppointments:
    @staticmethod
    def run(appts, vehicles=None, raw_wo=None, techs=None):
        log = CleaningLog()
        vehicles = vehicles if vehicles is not None else vehicles_df()
        raw_wo = raw_wo if raw_wo is not None else work_orders_df()
        techs = techs if techs is not None else technicians_df()
        return dc.clean_appointments(appts, vehicles, raw_wo, techs, log), log

    def test_dq20_status_variants(self):
        appts = appointments_df(*[{"status": s} for s in
                                  ["completed", " COMPLETED", "Cancelled", "Canceled", "CANCELLED ", "no-show",
                                   "No Show", "NO-SHOW", "noshow", "No-Show", "Completed"]])
        out, log = self.run(appts)
        assert out["status"].tolist() == ["Completed", "Completed", "Cancelled", "Cancelled", "Cancelled",
                                          "No-Show", "No-Show", "No-Show", "No-Show", "No-Show", "Completed"]
        assert affected(log, "DQ20", "appointments", "status") == 8  # canonical spellings not counted

    def test_dq20_unknown_status_becomes_na(self):
        out, _ = self.run(appointments_df({"status": "Rescheduled"}))
        assert out["status"].isna().all()

    def test_dq04_dd_mm_yyyy_parsed_and_counted(self):
        appts = appointments_df({"scheduled_date": "04/03/2025", "booking_date": "2025-03-01"},
                                {"scheduled_date": "2025-03-04"},
                                {"scheduled_date": "31/01/2025", "booking_date": "2025-01-20"})
        out, log = self.run(appts)
        assert out["scheduled_date"].tolist() == [date(2025, 3, 4), date(2025, 3, 4), date(2025, 1, 31)]
        assert affected(log, "DQ04", "appointments", "scheduled_date") == 2

    def test_dq05_out_of_period_and_unparseable_removed(self):
        appts = appointments_df(
            {"scheduled_date": "2024-12-31"}, {"scheduled_date": "2026-10-01"},
            {"scheduled_date": "garbage"}, {"scheduled_date": None},
            {"scheduled_date": "2025-01-01", "booking_date": "2025-01-01"},   # first day: kept
            {"scheduled_date": "2026-09-30"},                                  # last day: kept
        )
        out, log = self.run(appts)
        assert out["appointment_id"].tolist() == ["A5", "A6"]
        assert affected(log, "DQ05", "appointments", "scheduled_date") == 4

    def test_dq05_booking_after_scheduled_is_capped(self):
        appts = appointments_df({"booking_date": "2025-05-10", "scheduled_date": "2025-05-05"},
                                {"booking_date": "2025-05-05", "scheduled_date": "2025-05-05"},
                                {"booking_date": "2025-05-01", "scheduled_date": "2025-05-05"})
        out, log = self.run(appts)
        assert out["booking_date"].tolist() == [date(2025, 5, 5), date(2025, 5, 5), date(2025, 5, 1)]
        assert affected(log, "DQ05", "appointments", "booking_date") == 1

    def test_dq06_orphan_vehicle_removed(self):
        appts = appointments_df({"vehicle_id": "V1"}, {"vehicle_id": "V90001"}, {"vehicle_id": None})
        out, log = self.run(appts)
        assert out["appointment_id"].tolist() == ["A1"]
        assert affected(log, "DQ06", "appointments") == 2

    def test_dq07_center_imputed_from_technician(self):
        appts = appointments_df({"center_id": None}, {"center_id": "C001"})
        wo = work_orders_df({"technician_id": "T2"}, {"technician_id": "T1"})
        out, log = self.run(appts, raw_wo=wo)
        assert out.set_index("appointment_id")["center_id"].to_dict() == {"A1": "C002", "A2": "C001"}
        entries = log.frame()
        imputed = entries[(entries["rule_id"] == "DQ07") & (entries["action"].str.startswith("Imputed"))]
        removed = entries[(entries["rule_id"] == "DQ07") & (entries["action"] == "Removed")]
        assert imputed["rows_affected"].iloc[0] == 1
        assert removed["rows_affected"].iloc[0] == 0

    def test_dq07_unrecoverable_center_removed(self):
        appts = appointments_df({"center_id": None},                 # no work order at all
                                {"center_id": None},                 # work order with null technician
                                {"center_id": None},                 # work order with orphan technician
                                {"center_id": None},                 # recoverable
                                {"center_id": "C001"})
        wo = work_orders_df({"appointment_id": "A9", "technician_id": "T1"},
                            {"appointment_id": "A2", "technician_id": None},
                            {"appointment_id": "A3", "technician_id": "T999"},
                            {"appointment_id": "A4", "technician_id": "T1"})
        out, log = self.run(appts, raw_wo=wo)
        assert out["appointment_id"].tolist() == ["A4", "A5"]
        assert out["center_id"].tolist() == ["C001", "C001"]
        assert affected(log, "DQ07", column="center_id") == 4   # 1 imputed + 3 removed
        removed = log.frame().query("rule_id == 'DQ07' and action == 'Removed'")
        assert int(removed["rows_affected"].iloc[0]) == 3

    def test_dq07_duplicate_work_orders_for_one_appointment_do_not_duplicate_rows(self):
        appts = appointments_df({"center_id": None})
        wo = pd.concat([work_orders_df({"technician_id": "T2"}), work_orders_df({"technician_id": "T2"})],
                       ignore_index=True)
        out, _ = self.run(appts, raw_wo=wo)
        assert len(out) == 1 and out["center_id"].iloc[0] == "C002"

    def test_dq01_exact_duplicate_removed_and_text_trimmed(self):
        a = appointments_df({"booking_channel": "  Ather   App ", "cancellation_reason": " Price  Concern "})
        out, log = self.run(pd.concat([a, a], ignore_index=True))
        assert len(out) == 1
        assert out["booking_channel"].iloc[0] == "Ather App"
        assert out["cancellation_reason"].iloc[0] == "Price Concern"
        assert affected(log, "DQ01", "appointments") == 1

    def test_dq02_conflicting_duplicate_id_keeps_first(self):
        a = pd.concat([appointments_df({"status": "Completed"}),
                       appointments_df({"status": "Cancelled"})], ignore_index=True)
        a["appointment_id"] = "A1"
        out, log = self.run(a)
        assert out["status"].tolist() == ["Completed"]
        assert affected(log, "DQ02", "appointments") == 1


# --------------------------------------------------------------------------- #
# work orders
# --------------------------------------------------------------------------- #
class TestCleanWorkOrders:
    STYPES = ["Brake Service", "Periodic Service"]

    def run(self, wo, appts=None, techs=None):
        log = CleaningLog()
        appts = appts if appts is not None else ids("A", 10)
        techs = techs if techs is not None else technicians_df()
        return dc.clean_work_orders(wo, appts, techs, self.STYPES, log), log

    def test_dq03_service_type_variants(self):
        wo = work_orders_df({"service_type": "brake service"}, {"service_type": "BRAKE SERVICE"},
                            {"service_type": "Brake  Service"}, {"service_type": "Brake Service "},
                            {"service_type": "Brake Service"}, {"service_type": "periodic service"})
        out, log = self.run(wo)
        assert out["service_type"].tolist() == ["Brake Service"] * 5 + ["Periodic Service"]
        assert affected(log, "DQ03", "work_orders", "service_type") == 5

    def test_datetimes_parsed(self):
        out, _ = self.run(work_orders_df())
        for col in dc.DATETIME_COLS["work_orders"]:
            assert pd.api.types.is_datetime64_any_dtype(out[col]), col

    def test_dq18_orphan_appointment_cascades(self):
        wo = work_orders_df({}, {"appointment_id": "A404"}, {})
        wo["appointment_id"] = ["A1", "A404", "A3"]
        out, log = self.run(wo)
        assert out["work_order_id"].tolist() == ["W1", "W3"]
        assert affected(log, "DQ18", "work_orders") == 1

    def test_dq08_end_before_start_is_swapped(self):
        wo = work_orders_df({"start_time": "2025-03-03 15:00:00", "end_time": "2025-03-03 10:00:00"},
                            {})
        out, log = self.run(wo)
        assert out.loc[0, "start_time"] == pd.Timestamp("2025-03-03 10:00:00")
        assert out.loc[0, "end_time"] == pd.Timestamp("2025-03-03 15:00:00")
        assert out.loc[1, "start_time"] == pd.Timestamp("2025-03-03 09:30:00")   # untouched
        assert affected(log, "DQ08", "work_orders") == 1

    def test_dq08_equal_start_and_end_not_swapped(self):
        wo = work_orders_df({"start_time": "2025-03-03 10:00:00", "end_time": "2025-03-03 10:00:00"})
        _, log = self.run(wo)
        assert affected(log, "DQ08", "work_orders") == 0

    def test_dq08_swap_with_missing_start_is_noop(self):
        wo = work_orders_df({"start_time": None})
        out, log = self.run(wo)
        assert pd.isna(out.loc[0, "start_time"])
        assert out.loc[0, "end_time"] == pd.Timestamp("2025-03-03 12:00:00")
        assert affected(log, "DQ08", "work_orders") == 0

    def test_dq09_missing_start_retained_and_counted(self):
        wo = work_orders_df({"start_time": None}, {"start_time": ""}, {})
        out, log = self.run(wo)
        assert len(out) == 3
        assert out["start_time"].isna().tolist() == [True, True, False]
        assert affected(log, "DQ09", "work_orders") == 2

    def test_dq10_missing_and_invalid_technicians_nulled(self):
        wo = work_orders_df({"technician_id": "T1"}, {"technician_id": None}, {"technician_id": "T999"},
                            {"technician_id": "T2"})
        wo["technician_id"] = wo["technician_id"].astype("string")
        out, log = self.run(wo)
        assert out["technician_id"].isna().tolist() == [False, True, True, False]
        assert out.loc[0, "technician_id"] == "T1"
        assert affected(log, "DQ10", "work_orders") == 2
        assert len(out) == 4  # rows kept for financial KPIs

    def test_boolean_columns_coerced_from_text(self):
        wo = work_orders_df({"additional_work_found": "True", "qc_passed_first_time": " false "},
                            {"additional_work_found": False, "qc_passed_first_time": True},
                            {"additional_work_found": "maybe", "qc_passed_first_time": "TRUE"})
        out, _ = self.run(wo)
        assert out["additional_work_found"].tolist()[:2] == [True, False]
        assert pd.isna(out["additional_work_found"].iloc[2])          # unrecognised text -> null
        assert out["qc_passed_first_time"].tolist() == [False, True, True]

    def test_dq01_and_dq02(self):
        a = work_orders_df({})
        conflicting = work_orders_df({"actual_hours": 9.0})
        out, log = self.run(pd.concat([a, a, conflicting], ignore_index=True))
        assert len(out) == 1
        assert out["actual_hours"].iloc[0] == 2.0
        assert affected(log, "DQ01", "work_orders") == 1
        assert affected(log, "DQ02", "work_orders") == 1


# --------------------------------------------------------------------------- #
# part usage
# --------------------------------------------------------------------------- #
class TestCleanPartUsage:
    def run(self, rows, work_orders=None):
        log = CleaningLog()
        wo = work_orders if work_orders is not None else ids("W", 5)
        return dc.clean_part_usage(part_usage_df(rows), wo, parts_df(), log), log

    def test_dq17_non_positive_quantities_removed(self):
        out, log = self.run([("W1", "P1", 2), ("W1", "P2", 0), ("W2", "P1", -1), ("W2", "P2", 1)])
        assert out["usage_id"].tolist() == ["U1", "U4"]
        assert affected(log, "DQ17", "part_usage", "quantity") == 2

    def test_dq17_unknown_part_removed(self):
        out, log = self.run([("W1", "P1", 1), ("W1", "P999", 1)])
        assert out["part_id"].tolist() == ["P1"]
        assert affected(log, "DQ17", "part_usage", "part_id") == 1

    def test_dq17_zero_quantity_with_unknown_part_counted_once_under_quantity(self):
        _, log = self.run([("W1", "P999", 0)])
        assert affected(log, "DQ17", "part_usage", "quantity") == 1
        assert affected(log, "DQ17", "part_usage", "part_id") == 0

    def test_dq18_cascade_when_work_order_missing(self):
        out, log = self.run([("W1", "P1", 1), ("W77", "P1", 1)])
        assert out["work_order_id"].tolist() == ["W1"]
        assert affected(log, "DQ18", "part_usage") == 1

    def test_clean_input_unchanged(self):
        out, log = self.run([("W1", "P1", 1), ("W2", "P2", 3)])
        assert len(out) == 2
        assert sum(e["rows_affected"] for e in log.entries) == 0

    def test_empty_input(self):
        out, _ = self.run([])
        assert out.empty


# --------------------------------------------------------------------------- #
# financials
# --------------------------------------------------------------------------- #
class TestCleanFinancials:
    @staticmethod
    def run(fin, usage=None, wo=None):
        log = CleaningLog()
        usage = usage if usage is not None else part_usage_df([])
        wo = wo if wo is not None else ids("W", 20)
        return dc.clean_financials(fin, wo, usage, parts_df(), log), log

    def test_dq18_orphan_work_order_removed(self):
        fin = financials_df({}, {"work_order_id": "W404"})
        fin["work_order_id"] = ["W1", "W404"]
        out, log = self.run(fin)
        assert out["work_order_id"].tolist() == ["W1"]
        assert affected(log, "DQ18", "financials") == 1

    def test_dq11_negative_amounts_made_absolute_per_column(self):
        fin = financials_df({"revenue": -1000.0, "labor_cost": -50.0},
                            {"estimated_cost": -3.5, "parts_cost": -20.0},
                            {"revenue": 0.0, "labor_cost": 0.0})
        out, log = self.run(fin)
        assert out.loc[0, ["revenue", "labor_cost"]].tolist() == [1000.0, 50.0]
        assert out.loc[1, ["estimated_cost", "parts_cost"]].tolist() == [3.5, 20.0]
        assert out.loc[2, ["revenue", "labor_cost"]].tolist() == [0.0, 0.0]
        assert affected(log, "DQ11", "financials", "revenue") == 1
        assert affected(log, "DQ11", "financials", "labor_cost") == 1
        assert affected(log, "DQ11", "financials", "estimated_cost") == 1
        assert affected(log, "DQ11", "financials", "parts_cost") == 1
        assert (out[["estimated_cost", "labor_cost", "parts_cost", "revenue"]] >= 0).all().all()

    def test_dq12_missing_parts_cost_recomputed_from_usage(self):
        usage = part_usage_df([("W1", "P1", 2), ("W1", "P2", 1), ("W1", "P999", 5), ("W3", "P3", 1)])
        fin = financials_df({"parts_cost": np.nan}, {"parts_cost": np.nan}, {"parts_cost": np.nan},
                            {"parts_cost": 123.0})
        out, log = self.run(fin, usage)
        costs = out.set_index("work_order_id")["parts_cost"]
        assert costs["W1"] == 250.0          # 2*100 + 1*50, unknown part ignored
        assert costs["W2"] == 0.0            # no usage lines at all
        assert costs["W3"] == 1000.0
        assert costs["W4"] == 123.0          # present value untouched
        assert affected(log, "DQ12", "financials", "parts_cost") == 3

    def test_dq19_parts_cost_mismatch_reported_not_fixed(self):
        usage = part_usage_df([("W1", "P1", 3), ("W2", "P1", 3), ("W3", "P1", 3)])
        fin = financials_df({"parts_cost": 500.0},    # off by 200 -> mismatch
                            {"parts_cost": 300.9},    # within the INR 1 tolerance
                            {"parts_cost": 301.5})    # just outside tolerance
        out, log = self.run(fin, usage)
        assert out["parts_cost"].tolist() == [500.0, 300.9, 301.5]
        assert affected(log, "DQ19", "financials", "parts_cost") == 2

    def test_dq13_decimal_shift_corrected(self):
        fin = financials_df({"revenue": 120_000.0, "labor_cost": 800.0, "parts_cost": 400.0})
        out, log = self.run(fin)
        assert out["revenue"].iloc[0] == 1200.0
        assert affected(log, "DQ13", "financials", "revenue") == 1

    def test_dq13_not_triggered_for_legitimately_large_revenue(self):
        # INR 60k job costing INR 50k (e.g. motor assembly replacement): ratio 1.2 -> untouched.
        fin = financials_df({"revenue": 60_000.0, "labor_cost": 20_000.0, "parts_cost": 30_000.0},
                            {"revenue": 250_000.0, "labor_cost": 120_000.0, "parts_cost": 100_000.0})
        out, log = self.run(fin)
        assert out["revenue"].tolist() == [60_000.0, 250_000.0]
        assert affected(log, "DQ13", "financials", "revenue") == 0

    @pytest.mark.parametrize(
        "revenue, cost, shifted",
        [
            (50_001.0, 5_000.0, True),    # just above both thresholds (ratio 10.0002)
            (50_000.0, 4_000.0, False),   # ratio fine but revenue not above the INR 50k floor
            (60_000.0, 6_000.0, False),   # ratio exactly 10 is not "more than 10x"
            (60_000.0, 5_999.0, True),
            (49_999.0, 100.0, False),     # below the floor even though ratio is huge
            (0.0, 0.0, False),            # free rework job
        ],
    )
    def test_dq13_threshold_boundaries(self, revenue, cost, shifted):
        fin = financials_df({"revenue": revenue, "labor_cost": cost, "parts_cost": 0.0})
        out, log = self.run(fin)
        expected = round(revenue / 100, 2) if shifted else revenue
        assert out["revenue"].iloc[0] == pytest.approx(expected)
        assert affected(log, "DQ13", "financials") == int(shifted)

    def test_dq13_uses_recomputed_parts_cost_and_absolute_values(self):
        # Negative revenue is fixed by DQ11 first, then recognised as a x100 shift.
        usage = part_usage_df([("W1", "P1", 4)])      # parts cost 400
        fin = financials_df({"revenue": -150_000.0, "labor_cost": 500.0, "parts_cost": np.nan})
        out, log = self.run(fin, usage)
        assert out["revenue"].iloc[0] == 1500.0
        assert out["parts_cost"].iloc[0] == 400.0

    def test_billing_type_trimmed(self):
        out, _ = self.run(financials_df({"billing_type": "  Customer   Paid "}))
        assert out["billing_type"].iloc[0] == "Customer Paid"

    def test_dq01_exact_duplicate(self):
        fin = financials_df({})
        out, log = self.run(pd.concat([fin, fin], ignore_index=True))
        assert len(out) == 1
        assert affected(log, "DQ01", "financials") == 1

    def test_clean_values_untouched(self):
        out, log = self.run(financials_df({}, {"revenue": 0.0, "billing_type": "Rework (No Charge)"}),
                            part_usage_df([("W1", "P1", 4)]))
        assert out["revenue"].tolist() == [2000.0, 0.0]
        assert sum(e["rows_affected"] for e in log.entries
                   if e["rule_id"] in {"DQ11", "DQ12", "DQ13"}) == 0


# --------------------------------------------------------------------------- #
# feedback
# --------------------------------------------------------------------------- #
class TestCleanFeedback:
    @staticmethod
    def df(*rows):
        return pd.DataFrame([{"feedback_id": f"F{i}", "work_order_id": w, "rating": r,
                              "feedback_category": " Service  Quality ", "feedback_date": d}
                             for i, (w, r, d) in enumerate(rows, start=1)])

    def run(self, fb, wo=None):
        log = CleaningLog()
        return dc.clean_feedback(fb, wo if wo is not None else ids("W", 20), log), log

    def test_dq14_missing_and_out_of_range_ratings_removed(self):
        fb = self.df(("W1", 5.0, "2025-03-04"), ("W2", 0.0, "2025-03-04"), ("W3", 6.0, "2025-03-04"),
                     ("W4", np.nan, "2025-03-04"), ("W5", 3.0, "2025-03-04"), ("W6", 1.0, "2025-03-04"),
                     ("W7", 10.0, "2025-03-04"), ("W8", -2.0, "2025-03-04"))
        out, log = self.run(fb)
        assert out["work_order_id"].tolist() == ["W1", "W5", "W6"]
        assert out["rating"].tolist() == [5, 3, 1]
        assert affected(log, "DQ14", "feedback") == 5
        entries = log.frame().query("rule_id == 'DQ14'")
        assert entries["rows_affected"].tolist() == [1, 4]  # missing first, then out-of-range

    def test_dq14_works_with_nullable_float_ratings(self):
        fb = self.df(("W1", 4.0, "2025-03-04"), ("W2", 6.0, "2025-03-04"), ("W3", np.nan, "2025-03-04"))
        fb["rating"] = fb["rating"].astype("Float64")
        out, _ = self.run(fb)
        assert out["rating"].tolist() == [4]
        assert out["rating"].dtype == np.dtype(int)

    @pytest.mark.parametrize("rating", [1, 5])
    def test_dq14_boundaries_kept(self, rating):
        out, _ = self.run(self.df(("W1", float(rating), "2025-03-04")))
        assert out["rating"].tolist() == [rating]

    def test_dq18_orphan_work_order_removed(self):
        out, log = self.run(self.df(("W1", 4.0, "2025-03-04"), ("W404", 4.0, "2025-03-04")))
        assert out["work_order_id"].tolist() == ["W1"]
        assert affected(log, "DQ18", "feedback") == 1

    def test_dates_parsed_and_category_trimmed(self):
        out, _ = self.run(self.df(("W1", 4.0, "04/03/2025"), ("W2", 4.0, "2025-03-05")))
        assert out["feedback_date"].tolist() == [date(2025, 3, 4), date(2025, 3, 5)]
        assert set(out["feedback_category"]) == {"Service Quality"}

    def test_dq02_second_feedback_for_same_work_order_dropped(self):
        out, log = self.run(self.df(("W1", 5.0, "2025-03-04"), ("W1", 2.0, "2025-03-05")))
        assert out["rating"].tolist() == [5]
        assert affected(log, "DQ02", "feedback", "work_order_id") == 1

    def test_dq01_exact_duplicate(self):
        row = self.df(("W1", 4.0, "2025-03-04"))
        out, log = self.run(pd.concat([row, row], ignore_index=True))
        assert len(out) == 1
        assert affected(log, "DQ01", "feedback") == 1


# --------------------------------------------------------------------------- #
# Fact builders
# --------------------------------------------------------------------------- #
def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def fact_tables(jobs: list[dict], feedback: list[dict] | None = None) -> dict[str, pd.DataFrame]:
    """Cleaned-form tables for build_fact_* tests; every job becomes one appointment + work order + financials row."""
    vehicles = pd.DataFrame({
        "vehicle_id": ["V1", "V2", "V3"], "customer_id": ["C1", "C1", "C2"],
        "model": ["Ather 450X", "Ather Rizta", "Ather 450 Apex"], "variant": ["a", "b", "c"],
        "vehicle_category": ["Performance", "Family", "Performance"],
        "purchase_date": [date(2024, 3, 3), date(2024, 6, 1), date(2024, 9, 1)],
    })
    customers = pd.DataFrame({"customer_id": ["C1", "C2"], "customer_type": ["Individual", "Fleet"]})
    centres = pd.DataFrame({"center_id": ["C001"], "center_name": ["Bengaluru - Indiranagar"],
                            "city": ["Bengaluru"], "region": ["South"]})
    techs = pd.DataFrame({"technician_id": ["T1", "T2", "T3"], "center_id": ["C001"] * 3,
                          "skill_level": ["Senior", "Junior", "Mid"]})
    wo, appts, fin = [], [], []
    for i, j in enumerate(jobs, start=1):
        j = dict(j)
        wid, aid = f"W{i}", f"A{i}"
        check_in = ts(j.pop("check_in"))
        start = j.pop("start", "default")      # None means "start time missing"
        end = j.pop("end", None)
        promised = j.pop("promised", None)
        wo.append(dict(
            work_order_id=wid, appointment_id=aid, technician_id=j.pop("technician_id", "T1"),
            service_type=j.pop("service_type", "Brake Service"), check_in_time=check_in,
            start_time=(check_in + pd.Timedelta(minutes=30)) if start == "default"
            else (pd.NaT if start is None else ts(start)),
            end_time=ts(end) if end else check_in + pd.Timedelta(hours=3),
            promised_ready_time=ts(promised) if promised else check_in + pd.Timedelta(hours=5),
            estimated_hours=j.pop("estimated_hours", 2.0), actual_hours=j.pop("actual_hours", 2.0),
            parts_wait_hours=j.pop("parts_wait_hours", 0.0), odometer_km=1000,
            additional_work_found=False, qc_passed_first_time=j.pop("qc", True)))
        appts.append(dict(appointment_id=aid, vehicle_id=j.pop("vehicle_id", "V1"), center_id="C001",
                          booking_channel="Ather App", booking_date=date(2025, 3, 1),
                          scheduled_date=check_in.date(), status="Completed"))
        fin.append(dict(work_order_id=wid, billing_type="Customer Paid",
                        estimated_cost=j.pop("estimated_cost", 1000.0), labor_cost=j.pop("labor_cost", 600.0),
                        parts_cost=j.pop("parts_cost", 400.0), revenue=j.pop("revenue", 2000.0)))
        assert not j, f"unused job keys {j}"
    fb = pd.DataFrame(feedback or [], columns=["work_order_id", "rating", "feedback_category"])
    return {"work_orders": pd.DataFrame(wo), "appointments": pd.DataFrame(appts), "vehicles": vehicles,
            "customers": customers, "service_centers": centres, "technicians": techs,
            "financials": pd.DataFrame(fin), "feedback": fb}


class TestBuildFactServiceMetrics:
    @pytest.fixture
    def fact(self):
        jobs = [
            # W1: 30 min wait, 3h turnaround, ready an hour early
            dict(check_in="2025-03-03 09:00", start="2025-03-03 09:30", end="2025-03-03 12:00",
                 promised="2025-03-03 13:00", vehicle_id="V1", service_type="Brake Service",
                 estimated_hours=2.0, actual_hours=2.5, parts_wait_hours=0.0,
                 revenue=2000.0, labor_cost=600.0, parts_cost=400.0, estimated_cost=800.0),
            # W2: 1.5h late, 5.5h turnaround, parts delay
            dict(check_in="2025-03-04 09:00", start="2025-03-04 10:00", end="2025-03-04 14:30",
                 promised="2025-03-04 13:00", vehicle_id="V2", service_type="Tyre Replacement",
                 parts_wait_hours=4.0, revenue=3000.0, labor_cost=700.0, parts_cost=300.0, estimated_cost=1000.0),
            # W3: finished exactly at promised time; cost variance exactly 10%
            dict(check_in="2025-03-05 09:00", start="2025-03-05 09:15", end="2025-03-05 13:00",
                 promised="2025-03-05 13:00", vehicle_id="V3", service_type="Periodic Service",
                 revenue=1000.0, labor_cost=700.0, parts_cost=400.0, estimated_cost=1000.0),
            # W4: missing start time and zero estimate
            dict(check_in="2025-03-06 09:00", start=None, end="2025-03-06 12:00", promised="2025-03-06 12:00",
                 vehicle_id="V3", service_type="Battery Health Check",
                 revenue=0.0, labor_cost=100.0, parts_cost=0.0, estimated_cost=0.0),
        ]
        t = fact_tables(jobs, feedback=[dict(work_order_id="W2", rating=2, feedback_category="Turnaround Time")])
        return dc.build_fact_service(t).set_index("work_order_id")

    def test_one_row_per_work_order_sorted_by_check_in(self, fact):
        assert fact.index.tolist() == ["W1", "W2", "W3", "W4"]

    def test_wait_and_turnaround_hours(self, fact):
        assert fact.loc["W1", "wait_hours"] == 0.5
        assert fact.loc["W1", "turnaround_hours"] == 3.0
        assert fact.loc["W2", "wait_hours"] == 1.0
        assert fact.loc["W2", "turnaround_hours"] == 5.5

    def test_missing_start_gives_null_wait_but_valid_turnaround(self, fact):
        assert pd.isna(fact.loc["W4", "wait_hours"])
        assert fact.loc["W4", "turnaround_hours"] == 3.0

    def test_on_time_flag_and_late_hours(self, fact):
        assert fact["on_time_flag"].to_dict() == {"W1": True, "W2": False, "W3": True, "W4": True}
        assert fact["late_hours"].to_dict() == {"W1": 0.0, "W2": 1.5, "W3": 0.0, "W4": 0.0}

    def test_duration_variance_and_parts_delay_flag(self, fact):
        assert fact.loc["W1", "duration_variance_hours"] == 0.5
        assert fact.loc["W3", "duration_variance_hours"] == 0.0
        assert fact["parts_delay_flag"].to_dict() == {"W1": False, "W2": True, "W3": False, "W4": False}

    def test_profit_and_total_cost(self, fact):
        assert fact["total_cost"].to_dict() == {"W1": 1000.0, "W2": 1000.0, "W3": 1100.0, "W4": 100.0}
        assert fact["profit"].to_dict() == {"W1": 1000.0, "W2": 2000.0, "W3": -100.0, "W4": -100.0}

    def test_cost_variance_pct_and_overrun_flag(self, fact):
        assert fact["cost_variance"].to_dict() == {"W1": 200.0, "W2": 0.0, "W3": 100.0, "W4": 100.0}
        assert fact.loc["W1", "cost_variance_pct"] == 0.25
        assert fact.loc["W2", "cost_variance_pct"] == 0.0
        assert fact.loc["W3", "cost_variance_pct"] == 0.1
        assert pd.isna(fact.loc["W4", "cost_variance_pct"])    # zero estimate -> undefined, not inf
        assert fact["cost_overrun_flag"].to_dict() == {"W1": True, "W2": False, "W3": False, "W4": False}

    def test_calendar_fields(self, fact):
        assert fact.loc["W1", "service_date"] == date(2025, 3, 3)
        assert set(fact["month"]) == {"2025-03"}
        assert set(fact["year"]) == {2025}

    def test_vehicle_age_years(self, fact):
        # V1 bought 2024-03-03 and serviced 2025-03-03 -> 365 days / 365.25
        assert fact.loc["W1", "vehicle_age_years"] == pytest.approx(1.0, abs=0.01)
        assert fact.loc["W2", "vehicle_age_years"] == pytest.approx((ts("2025-03-04") - ts("2024-06-01")).days / 365.25,
                                                                   abs=0.01)
        assert "purchase_date" not in fact.columns

    def test_joined_dimensions_and_feedback(self, fact):
        assert fact.loc["W1", "model"] == "Ather 450X"
        assert fact.loc["W3", "customer_type"] == "Fleet"
        assert fact.loc["W1", "center_name"] == "Bengaluru - Indiranagar"
        assert fact.loc["W1", "skill_level"] == "Senior"
        assert fact.loc["W2", "rating"] == 2
        assert fact.loc["W2", "feedback_category"] == "Turnaround Time"
        assert pd.isna(fact.loc["W1", "rating"])


class TestRepeatVisitLogic:
    @staticmethod
    def build(jobs):
        return dc.build_fact_service(fact_tables(jobs)).set_index("work_order_id")

    def test_exactly_30_days_counts_as_repeat_and_31_does_not(self):
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),     # W1 original
            dict(check_in="2025-04-02 12:00", end="2025-04-02 15:00"),     # W2: exactly 30 days after W1 ends
            dict(check_in="2025-05-03 15:00", end="2025-05-03 18:00"),     # W3: 31 days after W2 ends
        ])
        assert f["is_repeat_visit"].to_dict() == {"W1": False, "W2": True, "W3": False}
        assert f.loc["W1", "days_since_same_service"] != f.loc["W1", "days_since_same_service"]  # NaN
        assert f.loc["W2", "days_since_same_service"] == 30
        assert f.loc["W3", "days_since_same_service"] == 31

    def test_caused_repeat_visit_attributed_to_original_job(self):
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
            dict(check_in="2025-04-02 12:00", end="2025-04-02 15:00"),
            dict(check_in="2025-05-03 15:00", end="2025-05-03 18:00"),
        ])
        # W1 caused W2 (exactly 30 days); W2 did not cause W3 (31 days); W3 has no successor.
        assert f["caused_repeat_visit"].to_dict() == {"W1": True, "W2": False, "W3": False}

    def test_one_day_inside_and_outside_boundary(self):
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
            dict(check_in="2025-04-01 12:00", end="2025-04-01 15:00"),     # 29 days
        ])
        assert f["is_repeat_visit"].tolist() == [False, True]
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
            dict(check_in="2025-04-03 12:00", end="2025-04-03 15:00"),     # 31 days
        ])
        assert f["is_repeat_visit"].tolist() == [False, False]
        assert f["caused_repeat_visit"].tolist() == [False, False]

    def test_partial_days_are_floored(self):
        # Characterisation: elapsed time is floored to whole days, so 30d 23h still counts as "within 30 days".
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
            dict(check_in="2025-04-03 11:00", end="2025-04-03 15:00"),     # 31 days minus 1 hour
        ])
        assert f.loc["W2", "days_since_same_service"] == 30
        assert bool(f.loc["W2", "is_repeat_visit"]) is True

    def test_different_service_type_or_vehicle_is_not_a_repeat(self):
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00", vehicle_id="V1", service_type="Brake Service"),
            dict(check_in="2025-03-10 09:00", end="2025-03-10 12:00", vehicle_id="V1", service_type="Tyre Replacement"),
            dict(check_in="2025-03-10 13:00", end="2025-03-10 15:00", vehicle_id="V2", service_type="Brake Service"),
        ])
        assert not f["is_repeat_visit"].any()
        assert not f["caused_repeat_visit"].any()

    def test_chain_of_repeats_compares_with_previous_visit_only(self):
        f = self.build([
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
            dict(check_in="2025-03-20 09:00", end="2025-03-20 12:00"),     # 17 days after W1
            dict(check_in="2025-04-15 09:00", end="2025-04-15 12:00"),     # 26 days after W2, 43 after W1
        ])
        assert f["is_repeat_visit"].to_dict() == {"W1": False, "W2": True, "W3": True}
        assert f["caused_repeat_visit"].to_dict() == {"W1": True, "W2": True, "W3": False}

    def test_input_order_does_not_matter(self):
        jobs = [
            dict(check_in="2025-04-02 12:00", end="2025-04-02 15:00"),
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00"),
        ]
        f = self.build(jobs)
        assert f["is_repeat_visit"].to_dict() == {"W1": True, "W2": False}
        assert f["caused_repeat_visit"].to_dict() == {"W1": False, "W2": True}

    def test_customer_visit_number_counts_across_vehicles_in_time_order(self):
        f = self.build([
            dict(check_in="2025-05-01 09:00", end="2025-05-01 12:00", vehicle_id="V1"),    # C1 third
            dict(check_in="2025-03-01 09:00", end="2025-03-01 12:00", vehicle_id="V2"),    # C1 first
            dict(check_in="2025-04-01 09:00", end="2025-04-01 12:00", vehicle_id="V1"),    # C1 second
            dict(check_in="2025-06-01 09:00", end="2025-06-01 12:00", vehicle_id="V3"),    # C2 first
            dict(check_in="2025-06-02 09:00", end="2025-06-02 12:00", vehicle_id="V3"),    # C2 second
        ])
        assert f["customer_visit_number"].to_dict() == {"W1": 3, "W2": 1, "W3": 2, "W4": 1, "W5": 2}


class TestBuildFactTechnicianMonth:
    @pytest.fixture
    def tm(self):
        jobs = [
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00", technician_id="T1", actual_hours=7.0, qc=True),
            dict(check_in="2025-03-10 09:00", end="2025-03-10 12:00", technician_id="T1", actual_hours=14.0, qc=False),
            dict(check_in="2025-04-07 09:00", end="2025-04-07 12:00", technician_id="T1", actual_hours=3.5),
            dict(check_in="2025-03-05 09:00", end="2025-03-05 12:00", technician_id="T2", actual_hours=1.0,
                 vehicle_id="V3", service_type="Tyre Replacement"),
            dict(check_in="2025-03-06 09:00", end="2025-03-06 12:00", technician_id=None, actual_hours=50.0,
                 vehicle_id="V3", service_type="Periodic Service"),
        ]
        t = fact_tables(jobs)
        fact = dc.build_fact_service(t)
        return dc.build_fact_technician_month(t, fact).set_index(["technician_id", "month"])

    def test_grid_covers_every_technician_month_pair(self, tm):
        n_months = len(pd.period_range(PERIOD_START, PERIOD_END, freq="M"))
        assert n_months == 21
        assert len(tm) == 3 * n_months

    def test_service_hours_and_utilisation(self, tm):
        row = tm.loc[("T1", "2025-03")]
        assert row["jobs"] == 2
        assert row["service_hours"] == 21.0
        assert row["working_days"] == 26
        assert row["available_hours"] == 26 * PRODUCTIVE_HOURS_PER_DAY
        assert row["utilisation"] == pytest.approx(21.0 / (26 * PRODUCTIVE_HOURS_PER_DAY), abs=1e-4)
        assert row["utilisation"] == pytest.approx(0.1154, abs=1e-4)

    def test_month_split(self, tm):
        april = tm.loc[("T1", "2025-04")]
        assert april["jobs"] == 1
        assert april["service_hours"] == 3.5
        assert april["working_days"] == 26   # April 2025 has 4 Sundays
        assert april["utilisation"] == pytest.approx(3.5 / 182, abs=1e-4)

    def test_qc_first_pass_rate(self, tm):
        assert tm.loc[("T1", "2025-03"), "qc_first_pass"] == 0.5
        assert tm.loc[("T1", "2025-04"), "qc_first_pass"] == 1.0

    def test_idle_technician_month_is_zero_not_missing(self, tm):
        row = tm.loc[("T3", "2025-03")]
        assert row["jobs"] == 0 and row["service_hours"] == 0 and row["utilisation"] == 0
        assert row["comebacks_caused"] == 0
        assert pd.isna(row["qc_first_pass"])

    def test_jobs_without_technician_excluded(self, tm):
        assert tm["jobs"].sum() == 4
        assert tm["service_hours"].sum() == pytest.approx(25.5)

    def test_comebacks_caused_summed(self):
        jobs = [
            dict(check_in="2025-03-03 09:00", end="2025-03-03 12:00", technician_id="T1"),
            dict(check_in="2025-03-10 09:00", end="2025-03-10 12:00", technician_id="T2"),   # repeat of W1
        ]
        t = fact_tables(jobs)
        tm = dc.build_fact_technician_month(t, dc.build_fact_service(t)).set_index(["technician_id", "month"])
        assert tm.loc[("T1", "2025-03"), "comebacks_caused"] == 1
        assert tm.loc[("T2", "2025-03"), "comebacks_caused"] == 0

    def test_available_hours_follow_calendar(self, tm):
        sept_2026 = tm.loc[("T1", "2026-09")]
        assert sept_2026["working_days"] == 26   # 30 days, Sundays on 6, 13, 20, 27
        feb_2025 = tm.loc[("T1", "2025-02")]
        assert feb_2025["working_days"] == 24    # 28 days, 4 Sundays


class TestBuildFactAppointments:
    @pytest.fixture
    def fa(self):
        t = fact_tables([dict(check_in="2025-03-03 09:00") for _ in range(8)])
        appts = t["appointments"]
        lead = [0, 1, 3, 4, 7, 8, 14, 15]
        appts["scheduled_date"] = date(2025, 3, 17)
        appts["booking_date"] = [date(2025, 3, 17) - pd.Timedelta(days=d) for d in lead]
        appts["booking_date"] = appts["booking_date"].map(lambda x: x.date() if hasattr(x, "date") else x)
        appts["status"] = ["Completed", "Cancelled", "No-Show", "Completed", "Cancelled", "No-Show",
                           "Completed", "Completed"]
        return dc.build_fact_appointments(t)

    def test_lead_days_and_bands_on_boundaries(self, fa):
        assert fa["lead_days"].tolist() == [0, 1, 3, 4, 7, 8, 14, 15]
        assert fa["lead_time_band"].tolist() == ["Same day", "1-3 days", "1-3 days", "4-7 days", "4-7 days",
                                                  "8-14 days", "8-14 days", "15+ days"]

    def test_status_flags_are_mutually_exclusive(self, fa):
        assert fa["is_cancelled"].sum() == 2
        assert fa["is_no_show"].sum() == 2
        assert fa["is_completed"].sum() == 4
        assert ((fa[["is_cancelled", "is_no_show", "is_completed"]].sum(axis=1)) == 1).all()

    def test_weekday_and_month(self, fa):
        assert set(fa["weekday"]) == {"Monday"}
        assert set(fa["month"]) == {"2025-03"}

    def test_dimensions_joined(self, fa):
        assert set(fa["model"]) == {"Ather 450X"}
        assert set(fa["customer_type"]) == {"Individual"}
        assert set(fa["center_name"]) == {"Bengaluru - Indiranagar"}
        assert len(fa) == 8

    def test_unknown_vehicle_keeps_row_with_null_dimensions(self):
        t = fact_tables([dict(check_in="2025-03-03 09:00")])
        t["appointments"].loc[0, "vehicle_id"] = "V404"
        fa = dc.build_fact_appointments(t)
        assert len(fa) == 1 and pd.isna(fa.loc[0, "model"])


class TestBuildDimDate:
    @pytest.fixture(scope="module")
    def dim(self):
        return dc.build_dim_date()

    def test_covers_full_period_once(self, dim):
        assert len(dim) == (PERIOD_END - PERIOD_START).days + 1 == 638
        assert dim["date"].is_unique
        assert dim["date"].iloc[0] == PERIOD_START and dim["date"].iloc[-1] == PERIOD_END

    def test_sunday_is_the_only_non_working_day(self, dim):
        weekday_name = dim["weekday_name"]
        assert dim.loc[weekday_name == "Sunday", "is_working_day"].eq(False).all()
        assert dim.loc[weekday_name != "Sunday", "is_working_day"].eq(True).all()

    def test_known_dates(self, dim):
        row = dim.set_index("date")
        sun = row.loc[date(2025, 3, 2)]
        assert (sun["weekday_name"], sun["weekday_number"], bool(sun["is_working_day"])) == ("Sunday", 7, False)
        mon = row.loc[date(2025, 3, 3)]
        assert (mon["weekday_name"], mon["weekday_number"], bool(mon["is_working_day"])) == ("Monday", 1, True)
        sat = row.loc[date(2025, 3, 8)]
        assert (sat["weekday_name"], bool(sat["is_working_day"])) == ("Saturday", True)
        last = row.loc[date(2026, 9, 30)]
        assert (last["quarter"], last["month_name"], last["year_month"], last["year"]) == ("Q3", "Sep", "2026-09", 2026)
        first = row.loc[date(2025, 1, 1)]
        assert (first["quarter"], first["month_number"], first["month_name"]) == ("Q1", 1, "Jan")

    def test_working_days_agree_with_working_days_helper(self, dim):
        total = dc.working_days(pd.Timestamp(PERIOD_START), pd.Timestamp(PERIOD_END))
        assert int(dim["is_working_day"].sum()) == total
