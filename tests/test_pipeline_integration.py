"""End-to-end pipeline tests: generate -> inject defects -> clean -> report.

Runs on small simulated networks (300 vehicles) so the whole module stays fast, and
repeats the main checks over several seeds so no assertion depends on one lucky draw.
Nothing here touches the real ``data/`` or ``reports/`` folders.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd
import pytest

import src.data_cleaning as dc
import src.generate_data as gd
from src.config import MODEL_FIRST_YEAR, PERIOD_END, PERIOD_START
from src.reference_data import CENTRES, SERVICE_TYPES

pytestmark = pytest.mark.integration

SEEDS = [11, 3, 42]
N_VEHICLES = 300
CLEANED_TABLES = ("customers", "vehicles", "appointments", "work_orders", "part_usage", "financials", "feedback")
OUTPUT_TABLES = [*dc.TABLES, "fact_service", "fact_appointments", "fact_technician_month", "dim_date"]


@dataclass
class Artifacts:
    seed: int
    clean_truth: dict          # defect-free simulation output
    raw: dict                  # defect-injected tables (never mutated)
    manifest: dict
    out: dict                  # run() result
    log: pd.DataFrame          # reports/cleaning_log.csv read back
    clean_dir: object
    reports_dir: object


@pytest.fixture(autouse=True)
def _isolate_pipeline_dirs(monkeypatch, tmp_path):
    """Belt and braces: any accidental write goes to tmp, never to the project's data/ or reports/."""
    monkeypatch.setattr(dc, "RAW_DIR", tmp_path / "guard" / "raw")
    monkeypatch.setattr(dc, "CLEAN_DIR", tmp_path / "guard" / "cleaned")
    monkeypatch.setattr(dc, "REPORTS_DIR", tmp_path / "guard" / "reports")
    monkeypatch.setattr(gd, "RAW_DIR", tmp_path / "guard" / "raw")


@pytest.fixture(scope="module", params=SEEDS, ids=[f"seed{s}" for s in SEEDS])
def art(request, tmp_path_factory) -> Artifacts:
    seed = request.param
    truth = gd.ServiceDataGenerator(seed=seed, n_vehicles=N_VEHICLES).generate()
    raw, manifest = gd.inject_defects(truth, seed=seed)
    root = tmp_path_factory.mktemp(f"pipeline_seed{seed}")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dc, "CLEAN_DIR", root / "cleaned")
        mp.setattr(dc, "REPORTS_DIR", root / "reports")
        out = dc.run({k: v.copy(deep=True) for k, v in raw.items()}, write=True)
    log = pd.read_csv(root / "reports" / "cleaning_log.csv")
    return Artifacts(seed, truth, raw, manifest, out, log, root / "cleaned", root / "reports")


def logged(art: Artifacts, rule: str, table: str, column: str | None = None, action: str | None = None) -> int:
    f = art.log
    mask = (f["rule_id"] == rule) & (f["table"] == table)
    if column is not None:
        mask &= f["column"] == column
    if action is not None:
        mask &= f["action"].str.startswith(action)
    assert mask.any(), f"missing log entry {rule}/{table}/{column}/{action}"
    return int(f.loc[mask, "rows_affected"].sum())


# --------------------------------------------------------------------------- #
# Post-clean invariants
# --------------------------------------------------------------------------- #
class TestPostCleanInvariants:
    def test_all_expected_outputs_present(self, art):
        assert set(art.out) == set(OUTPUT_TABLES)
        assert all(len(df) > 0 for df in art.out.values())

    @pytest.mark.parametrize("table", dc.TABLES)
    def test_no_duplicate_rows_or_keys(self, art, table):
        df = art.out[table]
        assert not df.duplicated().any()
        assert not df.duplicated(subset=dc.PRIMARY_KEYS[table]).any()
        assert df[dc.PRIMARY_KEYS[table]].notna().all()

    def test_no_orphan_foreign_keys(self, art):
        o = art.out
        assert o["vehicles"]["customer_id"].isin(o["customers"]["customer_id"]).all()
        assert o["appointments"]["vehicle_id"].isin(o["vehicles"]["vehicle_id"]).all()
        assert o["appointments"]["center_id"].isin(o["service_centers"]["center_id"]).all()
        assert o["work_orders"]["appointment_id"].isin(o["appointments"]["appointment_id"]).all()
        tech = o["work_orders"]["technician_id"].dropna()
        assert tech.isin(o["technicians"]["technician_id"]).all()
        assert o["part_usage"]["work_order_id"].isin(o["work_orders"]["work_order_id"]).all()
        assert o["part_usage"]["part_id"].isin(o["parts"]["part_id"]).all()
        assert o["financials"]["work_order_id"].isin(o["work_orders"]["work_order_id"]).all()
        assert o["feedback"]["work_order_id"].isin(o["work_orders"]["work_order_id"]).all()

    def test_no_negative_amounts(self, art):
        fin = art.out["financials"]
        assert (fin[["estimated_cost", "labor_cost", "parts_cost", "revenue"]] >= 0).all().all()
        assert fin[["estimated_cost", "labor_cost", "parts_cost", "revenue"]].notna().all().all()
        assert (art.out["part_usage"]["quantity"] > 0).all()

    def test_ratings_in_range_and_integer(self, art):
        r = art.out["feedback"]["rating"]
        assert r.between(1, 5).all()
        assert pd.api.types.is_integer_dtype(r)

    def test_work_order_times_ordered(self, art):
        wo = art.out["work_orders"]
        known = wo["start_time"].notna()
        assert (wo.loc[known, "end_time"] >= wo.loc[known, "start_time"]).all()
        assert (wo["end_time"] >= wo["check_in_time"]).all()

    def test_categoricals_canonical(self, art):
        o = art.out
        assert set(o["customers"]["region"].dropna()) <= {"North", "South", "East", "West"}
        assert o["customers"]["region"].notna().all()
        assert set(o["vehicles"]["model"]) <= set(MODEL_FIRST_YEAR)
        assert set(o["appointments"]["status"]) <= {"Completed", "Cancelled", "No-Show"}
        assert o["appointments"]["status"].notna().all()
        assert set(o["work_orders"]["service_type"].dropna()) <= set(SERVICE_TYPES)
        assert o["work_orders"]["service_type"].notna().all()

    def test_dates_in_period_and_booking_not_after_visit(self, art):
        a = art.out["appointments"]
        assert a["scheduled_date"].map(lambda d: PERIOD_START <= d <= PERIOD_END).all()
        assert (pd.to_datetime(a["booking_date"]) <= pd.to_datetime(a["scheduled_date"])).all()
        assert a["center_id"].notna().all()

    def test_vehicle_fields_plausible(self, art):
        v = art.out["vehicles"]
        first = v["model"].map(MODEL_FIRST_YEAR)
        assert (v["model_year"] >= first).all()
        assert (v["model_year"] <= PERIOD_END.year).all()
        assert (v["mileage_km"].dropna() >= 0).all()

    def test_no_decimal_shifted_revenue_left(self, art):
        fin = art.out["financials"]
        cost = fin["labor_cost"] + fin["parts_cost"]
        assert not ((fin["revenue"] > 10 * cost) & (fin["revenue"] > dc.REVENUE_SHIFT_FLOOR)).any()

    def test_rework_still_free_after_cleaning(self, art):
        fin = art.out["financials"]
        assert (fin.loc[fin["billing_type"] == "Rework (No Charge)", "revenue"] == 0).all()

    def test_fact_service_consistent_with_work_orders(self, art):
        fact = art.out["fact_service"]
        assert len(fact) == len(art.out["work_orders"])
        assert fact["work_order_id"].is_unique
        assert fact["center_id"].notna().all()
        assert fact["revenue"].notna().all()
        known = fact["wait_hours"].dropna()
        assert (known >= 0).all()
        assert (fact["turnaround_hours"] >= 0).all()
        assert fact["on_time_flag"].dtype == bool
        assert fact.groupby("customer_id")["customer_visit_number"].max().eq(
            fact.groupby("customer_id").size()).all()

    def test_fact_appointments_row_per_appointment(self, art):
        fa = art.out["fact_appointments"]
        assert len(fa) == len(art.out["appointments"])
        assert fa["lead_days"].ge(0).all()
        assert fa["lead_time_band"].isin(["Same day", "1-3 days", "4-7 days", "8-14 days", "15+ days"]).all()

    def test_fact_technician_month_grid(self, art):
        tm = art.out["fact_technician_month"]
        assert len(tm) == len(art.out["technicians"]) * 21
        assert tm["utilisation"].ge(0).all()
        assert tm["jobs"].sum() == art.out["fact_service"]["technician_id"].notna().sum()


# --------------------------------------------------------------------------- #
# Cleaning recovers the original (defect-free) values
# --------------------------------------------------------------------------- #
class TestCleaningRoundTrip:
    def test_customers_fully_recovered(self, art):
        truth = art.clean_truth["customers"].set_index("customer_id")
        got = art.out["customers"].set_index("customer_id")
        assert set(got.index) == set(truth.index)
        assert (got["region"] == truth["region"].reindex(got.index)).all()
        assert (got["registration_date"] == truth["registration_date"].reindex(got.index)).all()

    def test_vehicles_fully_recovered_except_unusable_mileage(self, art):
        truth = art.clean_truth["vehicles"].set_index("vehicle_id")
        got = art.out["vehicles"].set_index("vehicle_id")
        assert set(got.index) == set(truth.index)
        assert (got["model"] == truth["model"].reindex(got.index)).all()
        assert (got["model_year"].astype(int) == truth["model_year"].reindex(got.index)).all()
        assert (got["purchase_date"] == truth["purchase_date"].reindex(got.index)).all()
        kept = got["mileage_km"].notna()
        assert (got.loc[kept, "mileage_km"] == truth["mileage_km"].reindex(got.index)[kept]).all()
        # mileage is nulled, never invented
        assert got["mileage_km"].isna().sum() <= art.manifest["vehicles"]["impossible_mileage"]

    def test_surviving_appointments_match_truth(self, art):
        truth = art.clean_truth["appointments"].set_index("appointment_id")
        got = art.out["appointments"].set_index("appointment_id")
        assert set(got.index) <= set(truth.index)
        t = truth.loc[got.index]
        for col in ("vehicle_id", "center_id", "status", "scheduled_date", "booking_date", "booking_channel",
                    "requested_service_type"):
            assert (got[col] == t[col]).all(), col

    def test_only_expected_appointments_are_lost(self, art):
        truth_n = len(art.clean_truth["appointments"])
        lost = truth_n - len(art.out["appointments"])
        man = art.manifest["appointments"]
        assert 0 <= lost <= man["orphan_vehicle_id"] + man["missing_center_id"]

    def test_surviving_work_orders_match_truth(self, art):
        truth = art.clean_truth["work_orders"].set_index("work_order_id")
        got = art.out["work_orders"].set_index("work_order_id")
        assert set(got.index) <= set(truth.index)
        t = truth.loc[got.index]
        assert (got["service_type"] == t["service_type"]).all()
        assert (got["appointment_id"] == t["appointment_id"]).all()
        assert (got["end_time"] == pd.to_datetime(t["end_time"])).all()   # swapped pairs restored
        has_start = got["start_time"].notna()
        assert (got.loc[has_start, "start_time"] == pd.to_datetime(t.loc[has_start, "start_time"])).all()
        has_tech = got["technician_id"].notna()
        assert (got.loc[has_tech, "technician_id"] == t.loc[has_tech, "technician_id"]).all()

    def test_surviving_financials_match_truth(self, art):
        truth = art.clean_truth["financials"].set_index("work_order_id")
        got = art.out["financials"].set_index("work_order_id")
        t = truth.loc[got.index]
        assert (got["revenue"] - t["revenue"]).abs().max() < 0.011      # x100 and sign errors undone
        assert (got["labor_cost"] - t["labor_cost"]).abs().max() < 0.011
        assert (got["estimated_cost"] - t["estimated_cost"]).abs().max() < 0.011
        assert (got["billing_type"] == t["billing_type"]).all()

    def test_surviving_feedback_matches_truth(self, art):
        truth = art.clean_truth["feedback"].set_index("feedback_id")
        got = art.out["feedback"].set_index("feedback_id")
        assert set(got.index) <= set(truth.index)
        assert (got["rating"] == truth["rating"].reindex(got.index).astype(int)).all()
        removed = len(truth) - len(got)
        man = art.manifest["feedback"]
        # unusable ratings are dropped (plus any whose work order was cascade-removed)
        assert removed >= man["rating_out_of_range"] + man["missing_rating"]


# --------------------------------------------------------------------------- #
# Cleaning log vs injected-defect manifest
# --------------------------------------------------------------------------- #
class TestLogMatchesManifest:
    @pytest.mark.parametrize("table", ["customers", "appointments", "work_orders", "financials", "feedback"])
    def test_exact_duplicates_removed_exactly(self, art, table):
        assert logged(art, "DQ01", table) == art.manifest[table]["duplicate_rows"]

    @pytest.mark.parametrize("table", CLEANED_TABLES)
    def test_no_primary_key_conflicts_remain_after_exact_dedup(self, art, table):
        assert logged(art, "DQ02", table, dc.PRIMARY_KEYS[table]) == 0

    def test_category_variants_standardised(self, art):
        m = art.manifest
        assert logged(art, "DQ03", "customers", "region") == m["customers"]["region_format_variants"]
        assert logged(art, "DQ03", "vehicles", "model") == m["vehicles"]["model_name_variants"]
        assert logged(art, "DQ03", "work_orders", "service_type") == m["work_orders"]["service_type_format_variants"]
        assert logged(art, "DQ20", "appointments") == m["appointments"]["status_format_variants"]

    def test_date_format_and_orphan_vehicle_counts(self, art):
        m = art.manifest["appointments"]
        assert logged(art, "DQ04", "appointments") == m["ddmmyyyy_dates"]
        assert logged(art, "DQ05", "appointments", "scheduled_date") == 0
        assert logged(art, "DQ06", "appointments") == m["orphan_vehicle_id"]

    def test_missing_center_all_accounted_for(self, art):
        m = art.manifest["appointments"]["missing_center_id"]
        imputed = logged(art, "DQ07", "appointments", action="Imputed")
        removed = logged(art, "DQ07", "appointments", action="Removed")
        assert imputed + removed == m
        assert imputed >= 1 or m == removed

    def test_vehicle_quality_rules(self, art):
        m = art.manifest["vehicles"]
        raw = art.raw["vehicles"]
        assert logged(art, "DQ15", "vehicles") == m["impossible_model_year"]
        negatives = int((raw["mileage_km"] < 0).sum())
        # Large odometer values are only detectable for vehicles old enough to rule them out.
        assert negatives <= logged(art, "DQ16", "vehicles") <= m["impossible_mileage"]

    def test_feedback_and_part_usage_rules(self, art):
        fb = art.manifest["feedback"]
        assert logged(art, "DQ14", "feedback") == fb["missing_rating"] + fb["rating_out_of_range"]
        pu = art.manifest["part_usage"]
        assert logged(art, "DQ17", "part_usage", "quantity") == pu["non_positive_quantity"]
        assert logged(art, "DQ17", "part_usage", "part_id") == pu["orphan_part_id"]

    def test_work_order_and_financial_rules_detect_at_least_surviving_injections(self, art):
        """Counts can only fall short by rows whose parent appointment was cascade-removed."""
        m = art.manifest
        lost_wo = logged(art, "DQ18", "work_orders")
        lost_fin = logged(art, "DQ18", "financials")
        wo, fin = m["work_orders"], m["financials"]
        assert lost_wo <= m["appointments"]["orphan_vehicle_id"] + m["appointments"]["missing_center_id"]
        assert logged(art, "DQ08", "work_orders") >= wo["start_end_swapped"] - lost_wo
        assert logged(art, "DQ09", "work_orders") >= wo["missing_start_time"] - lost_wo
        assert logged(art, "DQ10", "work_orders") >= wo["missing_technician_id"] + wo["orphan_technician_id"] - lost_wo
        assert logged(art, "DQ11", "financials") >= fin["negative_amounts"] - lost_fin
        assert logged(art, "DQ12", "financials") >= fin["missing_parts_cost"] - lost_fin
        assert logged(art, "DQ13", "financials") >= fin["revenue_decimal_shift_x100"] - lost_fin
        assert lost_fin == lost_wo

    def test_decimal_shift_never_over_triggers(self, art):
        assert logged(art, "DQ13", "financials") <= art.manifest["financials"]["revenue_decimal_shift_x100"]

    def test_parts_cost_reconciliation_flags_removed_usage_lines(self, art):
        pu = art.manifest["part_usage"]
        n = logged(art, "DQ19", "financials")
        assert 1 <= n <= pu["non_positive_quantity"] + pu["orphan_part_id"]

    def test_every_rule_id_present_and_log_is_well_formed(self, art):
        expected = {f"DQ{n:02d}" for n in range(1, 21)}
        assert set(art.log["rule_id"]) == expected
        assert list(art.log.columns) == ["rule_id", "table", "column", "issue", "action", "rows_affected"]
        assert (art.log["rows_affected"] >= 0).all()
        assert art.log["rows_affected"].sum() > 0


# --------------------------------------------------------------------------- #
# Output files and the markdown report
# --------------------------------------------------------------------------- #
class TestOutputsAndReport:
    def test_cleaned_csvs_written_with_matching_row_counts(self, art):
        for name in OUTPUT_TABLES:
            path = art.clean_dir / f"{name}.csv"
            assert path.exists(), name
            assert len(pd.read_csv(path)) == len(art.out[name]), name

    def test_report_files_written(self, art):
        for name in ("data_quality_report.md", "cleaning_log.csv", "data_quality_summary.csv"):
            assert (art.reports_dir / name).exists(), name

    def test_markdown_structure(self, art):
        text = (art.reports_dir / "data_quality_report.md").read_text(encoding="utf-8")
        assert text.startswith("# Data Quality Report")
        for heading in ("## 1. Row counts", "## 2. Cleaning rules applied", "## 3. Post-cleaning validation",
                        "## 4. Raw null profile", "## 5. Notes"):
            assert heading in text, heading
        for table in dc.TABLES:
            assert f"| {table} |" in text
        for rule in (f"DQ{n:02d}" for n in range(1, 21)):
            assert f"| {rule} |" in text, rule
        assert f"{PERIOD_START} to {PERIOD_END}" in text

    def test_markdown_tables_are_well_formed(self, art):
        text = (art.reports_dir / "data_quality_report.md").read_text(encoding="utf-8")
        for block in re.findall(r"(?:^\|.*\|\n?)+", text, flags=re.M):
            lines = block.strip().splitlines()
            assert re.fullmatch(r"\|(---\|)+", lines[1]), lines[1]
            widths = {line.count("|") for line in lines}
            assert len(widths) == 1, "ragged markdown table"

    def test_post_cleaning_validation_section_all_zero(self, art):
        text = (art.reports_dir / "data_quality_report.md").read_text(encoding="utf-8")
        section = text.split("## 3. Post-cleaning validation")[1].split("## 4.")[0]
        rows = [ln for ln in section.splitlines() if ln.startswith("| ") and not ln.startswith("| check")]
        assert len(rows) == 6
        assert all(ln.rstrip().endswith("| 0 |") for ln in rows), rows

    def test_summary_csv_arithmetic(self, art):
        s = pd.read_csv(art.reports_dir / "data_quality_summary.csv").set_index("table")
        assert (s["raw_rows"] - s["clean_rows"] == s["rows_removed"]).all()
        assert s.loc["appointments", "raw_rows"] == len(art.raw["appointments"])
        assert s.loc["appointments", "clean_rows"] == len(art.out["appointments"])
        assert s["pct_retained"].between(0, 100).all()
        assert s.loc["service_centers", "pct_retained"] == 100.0

    def test_cleaning_log_csv_matches_rows_affected_total(self, art):
        assert art.log["rows_affected"].sum() == pd.read_csv(art.reports_dir / "cleaning_log.csv")["rows_affected"].sum()


# --------------------------------------------------------------------------- #
# Behaviour of run() itself
# --------------------------------------------------------------------------- #
class TestRunBehaviour:
    def test_write_false_creates_nothing(self, small_raw_tables, tmp_path, monkeypatch):
        clean_dir, reports_dir = tmp_path / "c", tmp_path / "r"
        monkeypatch.setattr(dc, "CLEAN_DIR", clean_dir)
        monkeypatch.setattr(dc, "REPORTS_DIR", reports_dir)
        out = dc.run(small_raw_tables, write=False)
        assert not clean_dir.exists() and not reports_dir.exists()
        assert set(out) == set(OUTPUT_TABLES)

    def test_run_does_not_mutate_its_input(self, small_raw_tables):
        before = {k: v.copy(deep=True) for k, v in small_raw_tables.items()}
        dc.run(small_raw_tables, write=False)
        for name in before:
            pd.testing.assert_frame_equal(before[name], small_raw_tables[name], obj=name)

    def test_run_is_deterministic(self, small_raw_tables):
        a = dc.run({k: v.copy() for k, v in small_raw_tables.items()}, write=False)
        b = dc.run({k: v.copy() for k, v in small_raw_tables.items()}, write=False)
        for name in a:
            pd.testing.assert_frame_equal(a[name], b[name], obj=name)

    def test_clean_input_passes_through_unharmed(self, small_clean_tables):
        """Feeding defect-free data (as text-serialised raw) must not remove or alter any real record."""
        # Same text serialisation of dates as the injector produces, but with no defects at all.
        pristine = {k: v.copy() for k, v in small_clean_tables.items()}
        for name, cols in dc.DATETIME_COLS.items():
            for c in cols:
                pristine[name][c] = pristine[name][c].map(
                    lambda x: x.strftime(gd.DT_FMT) if hasattr(x, "hour") else x.isoformat())
        out = dc.run(pristine, write=False)
        for name in ("customers", "vehicles", "appointments", "work_orders", "part_usage", "financials", "feedback"):
            assert len(out[name]) == len(small_clean_tables[name]), name

    def test_csv_round_trip_through_load_raw(self, small_raw_tables, tmp_path, monkeypatch):
        raw_dir = tmp_path / "rawcsv"
        raw_dir.mkdir()
        for name, df in small_raw_tables.items():
            df.to_csv(raw_dir / f"{name}.csv", index=False)
        monkeypatch.setattr(dc, "RAW_DIR", raw_dir)
        loaded = dc.load_raw()
        assert set(loaded) == set(dc.TABLES)
        from_csv = dc.run(loaded, write=False)
        in_memory = dc.run(small_raw_tables, write=False)
        for name in ("customers", "vehicles", "appointments", "work_orders", "part_usage", "financials", "feedback"):
            assert len(from_csv[name]) == len(in_memory[name]), name
        assert from_csv["fact_service"]["revenue"].sum() == pytest.approx(in_memory["fact_service"]["revenue"].sum())
        assert from_csv["fact_service"]["on_time_flag"].sum() == in_memory["fact_service"]["on_time_flag"].sum()

    def test_run_with_no_raw_argument_reads_from_raw_dir(self, small_raw_tables, tmp_path, monkeypatch):
        raw_dir = tmp_path / "rawcsv2"
        raw_dir.mkdir()
        for name, df in small_raw_tables.items():
            df.to_csv(raw_dir / f"{name}.csv", index=False)
        monkeypatch.setattr(dc, "RAW_DIR", raw_dir)
        out = dc.run(write=False)
        assert len(out["fact_service"]) > 0

    def test_main_writes_outputs_to_patched_dirs_and_prints_counts(self, small_raw_tables, tmp_path, monkeypatch, capsys):
        raw_dir = tmp_path / "raw_main"
        raw_dir.mkdir()
        for name, df in small_raw_tables.items():
            df.to_csv(raw_dir / f"{name}.csv", index=False)
        monkeypatch.setattr(dc, "RAW_DIR", raw_dir)
        monkeypatch.setattr(dc, "CLEAN_DIR", tmp_path / "clean_main")
        monkeypatch.setattr(dc, "REPORTS_DIR", tmp_path / "reports_main")
        dc.main()
        printed = capsys.readouterr().out
        assert "fact_service" in printed and "dim_date" in printed
        assert (tmp_path / "clean_main" / "fact_service.csv").exists()
        assert (tmp_path / "reports_main" / "data_quality_report.md").exists()

    def test_write_report_standalone(self, small_raw_tables, tmp_path, monkeypatch):
        reports_dir = tmp_path / "standalone_reports"
        monkeypatch.setattr(dc, "REPORTS_DIR", reports_dir)
        out = dc.run(small_raw_tables, write=False)
        log = dc.CleaningLog()
        log.add("DQ99", "customers", "region", "synthetic issue", "synthetic action", 3)
        prof = dc.profile(small_raw_tables)
        tables = {k: out[k] for k in dc.TABLES}
        dc.write_report(prof, log, tables, out["fact_service"])
        text = (reports_dir / "data_quality_report.md").read_text(encoding="utf-8")
        assert "| DQ99 | customers | region | synthetic issue | synthetic action | 3 |" in text
        assert pd.read_csv(reports_dir / "cleaning_log.csv")["rule_id"].tolist() == ["DQ99"]

    def test_write_report_flags_violations_in_validation_section(self, small_raw_tables, tmp_path, monkeypatch):
        reports_dir = tmp_path / "violations"
        monkeypatch.setattr(dc, "REPORTS_DIR", reports_dir)
        out = dc.run(small_raw_tables, write=False)
        fact = out["fact_service"].copy()
        fact.loc[fact.index[:2], "revenue"] = -5.0          # inject two negative revenues
        fact.loc[fact.index[2], "rating"] = 9               # and one invalid rating
        dc.write_report(dc.profile(small_raw_tables), dc.CleaningLog(), {k: out[k] for k in dc.TABLES}, fact)
        text = (reports_dir / "data_quality_report.md").read_text(encoding="utf-8")
        assert "| Negative revenue or cost | 2 |" in text
        assert "| Ratings outside 1-5 | 1 |" in text


class TestGeneratorToCsvToCleaner:
    def test_main_then_cleaner_end_to_end(self, tmp_path, monkeypatch):
        raw_dir = tmp_path / "e2e_raw"
        monkeypatch.setattr(gd, "RAW_DIR", raw_dir)
        monkeypatch.setattr(dc, "RAW_DIR", raw_dir)
        real = gd.ServiceDataGenerator
        monkeypatch.setattr(gd, "ServiceDataGenerator", lambda: real(seed=gd.SEED, n_vehicles=150))
        gd.main()
        manifest = json.loads((raw_dir / "generation_manifest.json").read_text(encoding="utf-8"))
        out = dc.run(write=False)
        raw_counts = manifest["row_counts"]
        assert len(out["customers"]) == raw_counts["customers"] - manifest["injected_defects"]["customers"]["duplicate_rows"]
        assert out["fact_service"]["work_order_id"].is_unique
        assert len(out["service_centers"]) == len(CENTRES)
