"""Integration tests for the database layer against the live PostgreSQL container.

SAFETY: ``src.load_to_db.main`` has no schema / target override -- ``sql/schema.sql``
runs ``DROP SCHEMA IF EXISTS service_ops CASCADE`` -- so it is deliberately *never*
executed here. Instead:

* every check against the existing ``service_ops`` schema is read-only (the shared
  connection is switched to ``default_transaction_read_only``);
* the loader helpers (``copy_csv``, ``load_all``, ``table_counts``, ``run_sql_file``)
  are exercised against session-private TEMP tables that shadow the real tables
  (``pg_temp`` is searched first) and vanish when the connection closes;
* ``run_sql_reports.main`` runs with its output directory redirected to ``tmp_path``.

The whole module is skipped when the database is unreachable or not yet loaded.
"""
from __future__ import annotations

import dataclasses
import re
import socket

import pandas as pd
import psycopg
import pytest

from src import db, load_to_db, run_sql_reports
from src.config import CLEAN_DIR

pytestmark = pytest.mark.integration

CONNECT_TIMEOUT_S = 3
EXPECTED_VIEWS = (
    "vw_period_calendar", "vw_work_order_enriched", "vw_appointment_enriched", "vw_monthly_financials",
    "vw_technician_utilisation", "vw_center_performance", "vw_service_type_performance",
    "vw_appointment_funnel", "vw_customer_repeat", "vw_kpi_summary",
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _open(settings: db.DbSettings, **kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.host, port=settings.port, dbname=settings.dbname, user=settings.user,
        password=settings.password, options=f"-c search_path={db.DB_SCHEMA},public",
        connect_timeout=CONNECT_TIMEOUT_S, **kwargs,
    )


@pytest.fixture(scope="module")
def settings() -> db.DbSettings:
    try:
        return db.load_settings()
    except SystemExit as exc:
        pytest.skip(f"database settings not configured: {exc}")


@pytest.fixture(scope="module")
def conn(settings):
    """Read-only autocommit connection to the existing, already loaded database."""
    try:
        connection = _open(settings, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable ({settings.display}): {str(exc).strip()[:120]}")
    try:
        connection.execute("SET default_transaction_read_only = on")
        loaded = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (db.DB_SCHEMA,)
        ).fetchone()[0]
        if loaded == 0:
            pytest.skip(f"schema {db.DB_SCHEMA!r} is not loaded; run `python -m src.load_to_db` first")
        yield connection
    finally:
        connection.close()


@pytest.fixture
def temp_conn(settings, conn):
    """Writable session whose TEMP tables shadow the real ones; nothing persists after close."""
    connection = _open(settings)
    try:
        try:
            for table in load_to_db.LOAD_ORDER:
                connection.execute(
                    f'CREATE TEMP TABLE "{table}" (LIKE {db.DB_SCHEMA}."{table}" INCLUDING DEFAULTS)'
                )
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("role may not create temporary tables")
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _require_database(conn):
    """Make every test in this module depend on a reachable, loaded database (skips otherwise)."""


@pytest.fixture(scope="module")
def kpi_sections():
    return run_sql_reports.parse_sections((db.SQL_DIR / "kpi_queries.sql").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dq_sections():
    return run_sql_reports.parse_sections((db.SQL_DIR / "data_quality.sql").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dq_results(conn, dq_sections):
    return {s.qid: run_sql_reports.run_section(conn, s) for s in dq_sections}


def _real_reports_snapshot() -> dict[str, int]:
    root = run_sql_reports.REPORTS_DIR / "sql_results"
    return {p.name: p.stat().st_mtime_ns for p in root.glob("*")} if root.exists() else {}


# --------------------------------------------------------------------------- #
# src.db.connect
# --------------------------------------------------------------------------- #
class TestConnect:
    def test_connect_uses_project_schema_search_path(self, settings, conn):
        with db.connect(settings) as c:
            path = c.execute("SHOW search_path").fetchone()[0]
            assert path.replace(" ", "") == f"{db.DB_SCHEMA},public"

    def test_connect_default_settings_come_from_env(self, conn):
        with db.connect() as c:
            assert c.execute("SELECT 1").fetchone() == (1,)

    def test_autocommit_flag(self, settings, conn):
        with db.connect(settings, autocommit=True) as c:
            assert c.autocommit is True
        with db.connect(settings) as c:
            assert c.autocommit is False

    def test_unqualified_table_names_resolve(self, conn):
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0

    def test_wrong_password_exits_without_leaking_it(self, settings, conn):
        bad = dataclasses.replace(settings, password="definitely-wrong-pw-xyz")
        with pytest.raises(SystemExit) as exc:
            db.connect(bad)
        message = str(exc.value)
        assert "Could not connect" in message
        assert settings.display in message
        assert "definitely-wrong-pw-xyz" not in message
        assert settings.password not in message

    def test_unknown_database_exits_cleanly(self, settings, conn):
        bad = dataclasses.replace(settings, dbname="no_such_db_for_tests")
        with pytest.raises(SystemExit, match="Could not connect"):
            db.connect(bad)

    @pytest.mark.slow
    def test_closed_port_exits_with_hint(self, settings, conn):
        with socket.socket() as probe:  # grab a free port, then release it so nothing listens there
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        bad = dataclasses.replace(settings, host="127.0.0.1", port=free_port)
        with pytest.raises(SystemExit, match="docker compose up -d"):
            db.connect(bad)


# --------------------------------------------------------------------------- #
# loaded data vs cleaned CSVs (read-only)
# --------------------------------------------------------------------------- #
class TestLoadedData:
    @pytest.mark.parametrize("table", load_to_db.LOAD_ORDER)
    def test_row_count_equals_cleaned_csv(self, conn, table):
        db_rows = conn.execute(f'SELECT COUNT(*) FROM {db.DB_SCHEMA}."{table}"').fetchone()[0]
        assert db_rows == load_to_db.csv_row_count(CLEAN_DIR / f"{table}.csv") > 0

    def test_table_counts_helper_and_verify_counts_agree(self, conn, capsys):
        counts = load_to_db.table_counts(conn)
        assert set(counts) == set(load_to_db.LOAD_ORDER)
        assert load_to_db.verify_counts(counts) is True
        out = capsys.readouterr().out
        assert "MISMATCH" not in out and out.count("OK") == len(load_to_db.LOAD_ORDER)

    def test_verify_counts_detects_a_perturbed_count(self, conn, capsys):
        counts = load_to_db.table_counts(conn)
        counts["parts"] += 1
        assert load_to_db.verify_counts(counts) is False
        assert capsys.readouterr().out.count("MISMATCH") == 1

    @pytest.mark.parametrize("table", load_to_db.LOAD_ORDER)
    def test_csv_header_matches_table_columns(self, conn, table):
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (db.DB_SCHEMA, table),
        ).fetchall()
        assert {r[0] for r in rows} == set(load_to_db.csv_columns(CLEAN_DIR / f"{table}.csv"))

    def test_only_expected_tables_exist(self, conn):
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (db.DB_SCHEMA,),
        ).fetchall()
        assert {r[0] for r in rows} == set(load_to_db.LOAD_ORDER)

    def test_foreign_keys_enforced_in_database(self, conn):
        n = conn.execute(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE constraint_schema = %s AND constraint_type = 'FOREIGN KEY'", (db.DB_SCHEMA,)
        ).fetchone()[0]
        assert n >= 9


# --------------------------------------------------------------------------- #
# views (read-only)
# --------------------------------------------------------------------------- #
class TestViews:
    def test_list_views_returns_every_view_in_views_sql(self, conn):
        defined = re.findall(r"CREATE OR REPLACE VIEW\s+(\w+)", (db.SQL_DIR / "views.sql").read_text(encoding="utf-8"))
        assert tuple(defined) == EXPECTED_VIEWS
        assert load_to_db.list_views(conn) == sorted(EXPECTED_VIEWS)

    @pytest.mark.parametrize("view", EXPECTED_VIEWS)
    def test_view_is_selectable_and_non_empty(self, conn, view):
        cur = conn.execute(f'SELECT * FROM {db.DB_SCHEMA}."{view}" LIMIT 5')
        assert cur.description, f"{view} returned no column metadata"
        assert len(cur.fetchall()) >= 1

    def test_kpi_summary_is_a_single_row(self, conn):
        assert conn.execute("SELECT COUNT(*) FROM vw_kpi_summary").fetchone()[0] == 1

    def test_work_order_view_row_count_matches_work_orders(self, conn):
        wo = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
        vw = conn.execute("SELECT COUNT(*) FROM vw_work_order_enriched").fetchone()[0]
        assert vw == wo


# --------------------------------------------------------------------------- #
# analytical queries (read-only)
# --------------------------------------------------------------------------- #
class TestKpiQueries:
    def test_all_21_queries_execute_and_return_rows(self, conn, kpi_sections):
        assert len(kpi_sections) == 21
        problems = []
        for section in kpi_sections:
            result = run_sql_reports.run_section(conn, section)
            if result.frame is None:
                problems.append(f"{section.qid}: {result.error}")
            elif len(result.frame) < 1:
                problems.append(f"{section.qid}: returned no rows")
        assert not problems, "; ".join(problems)

    def test_results_have_no_decimal_objects(self, conn, kpi_sections):
        from decimal import Decimal
        frame = run_sql_reports.run_section(conn, kpi_sections[0]).frame
        assert not any(isinstance(v, Decimal) for v in frame.to_numpy().ravel())

    def test_failed_query_is_reported_and_connection_stays_usable(self, conn):
        bad = run_sql_reports.Section("Q99", "Bad", "SELECT * FROM table_that_does_not_exist")
        result = run_sql_reports.run_section(conn, bad)
        assert result.frame is None
        assert "table_that_does_not_exist" in result.error
        good = run_sql_reports.run_section(conn, run_sql_reports.Section("Q98", "Good", "SELECT 1 AS one"))
        assert good.frame["one"].tolist() == [1]

    def test_q01_scorecard_has_metric_columns(self, conn, kpi_sections):
        frame = run_sql_reports.run_section(conn, kpi_sections[0]).frame
        assert len(frame) >= 1
        assert frame.shape[1] >= 2


class TestDataQualityChecks:
    def test_there_are_50_checks_and_a_summary(self, dq_sections):
        assert [s.qid for s in dq_sections] == [f"SQL-DQ{i:02d}" for i in range(1, 51)] + ["SQL-DQ99"]

    def test_every_check_returns(self, dq_results):
        failed = {qid: r.error for qid, r in dq_results.items() if r.frame is None}
        assert not failed, failed

    def test_each_individual_check_returns_one_labelled_row(self, dq_results):
        for qid, result in dq_results.items():
            if qid == run_sql_reports.SUMMARY_ID:
                continue
            frame = result.frame
            assert list(frame.columns) == ["check_id", "check_name", "check_type", "issue_count"], qid
            assert len(frame) == 1, qid
            assert frame.loc[0, "check_id"] == qid
            assert frame.loc[0, "check_type"] in {"integrity", "informational"}
            assert frame.loc[0, "issue_count"] >= 0

    def test_summary_has_status_column_for_all_checks(self, dq_results):
        summary = dq_results[run_sql_reports.SUMMARY_ID].frame
        assert list(summary.columns) == ["check_id", "check_name", "check_type", "issue_count", "status"]
        assert len(summary) == 50
        assert set(summary["status"]) <= {"PASS", "INFO", "FAIL"}

    def test_all_integrity_checks_pass(self, dq_results):
        summary = dq_results[run_sql_reports.SUMMARY_ID].frame
        integrity = summary[summary["check_type"] == "integrity"]
        assert len(integrity) > 0
        failing = integrity[integrity["status"] != "PASS"]
        assert failing.empty, failing[["check_id", "check_name", "issue_count"]].to_string()

    def test_no_check_has_fail_status(self, dq_results):
        summary = dq_results[run_sql_reports.SUMMARY_ID].frame
        assert "FAIL" not in set(summary["status"])

    def test_informational_checks_are_pass_or_info(self, dq_results):
        summary = dq_results[run_sql_reports.SUMMARY_ID].frame
        info = summary[summary["check_type"] == "informational"]
        assert set(info["status"]) <= {"PASS", "INFO"}
        assert ((info["status"] == "PASS") == (info["issue_count"] == 0)).all()

    def test_individual_checks_equal_summary(self, dq_results):
        individual = pd.concat(
            [r.frame for qid, r in dq_results.items() if qid != run_sql_reports.SUMMARY_ID], ignore_index=True)
        summary = dq_results[run_sql_reports.SUMMARY_ID].frame
        pd.testing.assert_frame_equal(
            individual[["check_id", "issue_count"]].reset_index(drop=True),
            summary[["check_id", "issue_count"]].reset_index(drop=True),
        )


# --------------------------------------------------------------------------- #
# run_sql_reports.main end-to-end (output redirected to tmp_path)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def outcome(conn, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("sql_results")
    before = _real_reports_snapshot()
    mp = pytest.MonkeyPatch()
    mp.setattr(run_sql_reports, "OUT_DIR", out_dir)
    try:
        code = run_sql_reports.main()
    finally:
        mp.undo()
    return {"code": code, "out": out_dir, "before": before, "after": _real_reports_snapshot()}


class TestRunSqlReportsMainLive:
    def test_exit_code_zero(self, outcome):
        assert outcome["code"] == 0

    def test_writes_one_csv_per_kpi_query(self, outcome):
        names = sorted(p.name for p in outcome["out"].glob("Q*.csv"))
        assert len(names) == 21
        assert [n[:3] for n in names] == [f"Q{i:02d}" for i in range(1, 22)]
        for p in outcome["out"].glob("Q*.csv"):
            assert len(pd.read_csv(p)) >= 1, p.name

    def test_writes_dq_csvs(self, outcome):
        combined = pd.read_csv(outcome["out"] / "SQL_DQ_all_checks.csv")
        summary = pd.read_csv(outcome["out"] / "SQL-DQ99_data_quality_summary.csv")
        assert len(combined) == 50 and len(summary) == 50
        assert combined["check_id"].tolist() == summary["check_id"].tolist()
        assert (summary.loc[summary["check_type"] == "integrity", "status"] == "PASS").all()

    def test_readme_lists_every_query(self, outcome):
        readme = (outcome["out"] / "README.md").read_text(encoding="utf-8")
        for i in range(1, 22):
            assert f"| Q{i:02d} |" in readme
        assert "FAILED" not in readme
        assert "## Data-quality checks" in readme
        assert "SQL-DQ50" in readme

    def test_real_reports_folder_is_untouched(self, outcome):
        assert outcome["before"] == outcome["after"]

    def test_only_expected_files_were_written(self, outcome):
        names = {p.name for p in outcome["out"].iterdir()}
        assert names == (
            {p.name for p in outcome["out"].glob("Q*.csv")}
            | {"README.md", "SQL_DQ_all_checks.csv", "SQL-DQ99_data_quality_summary.csv"}
        )


# --------------------------------------------------------------------------- #
# loader helpers against TEMP tables (real schema untouched)
# --------------------------------------------------------------------------- #
class TestLoaderHelpersOnTempTables:
    def test_copy_csv_loads_rows_into_shadow_table_only(self, temp_conn, conn):
        real_before = conn.execute(f"SELECT COUNT(*) FROM {db.DB_SCHEMA}.customers").fetchone()[0]
        load_to_db.copy_csv(temp_conn, "customers", CLEAN_DIR / "customers.csv")
        loaded = temp_conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert loaded == load_to_db.csv_row_count(CLEAN_DIR / "customers.csv")
        assert conn.execute(f"SELECT COUNT(*) FROM {db.DB_SCHEMA}.customers").fetchone()[0] == real_before

    def test_copy_csv_roundtrips_values(self, temp_conn):
        load_to_db.copy_csv(temp_conn, "service_centers", CLEAN_DIR / "service_centers.csv")
        db_ids = [r[0] for r in temp_conn.execute("SELECT center_id FROM service_centers ORDER BY 1").fetchall()]
        csv_ids = sorted(pd.read_csv(CLEAN_DIR / "service_centers.csv")["center_id"])
        assert db_ids == csv_ids

    def test_copy_csv_with_small_chunks(self, temp_conn, monkeypatch):
        monkeypatch.setattr(load_to_db, "CHUNK_BYTES", 257)  # forces many chunk boundaries (incl. mid-row/UTF-8)
        load_to_db.copy_csv(temp_conn, "parts", CLEAN_DIR / "parts.csv")
        assert temp_conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == \
            load_to_db.csv_row_count(CLEAN_DIR / "parts.csv")

    def test_copy_csv_with_bad_data_raises(self, temp_conn, tmp_path):
        bad = tmp_path / "customers.csv"
        bad.write_text("customer_id,customer_type,city,region,registration_date\nC1,X,Y,Z,not-a-date\n",
                       encoding="utf-8")
        with pytest.raises(psycopg.Error):
            load_to_db.copy_csv(temp_conn, "customers", bad)

    def test_copy_csv_unknown_column_raises(self, temp_conn, tmp_path):
        bad = tmp_path / "customers.csv"
        bad.write_text("customer_id,no_such_column\nC1,x\n", encoding="utf-8")
        with pytest.raises(psycopg.errors.UndefinedColumn):
            load_to_db.copy_csv(temp_conn, "customers", bad)

    def test_load_all_and_table_counts_match_csvs(self, temp_conn, capsys):
        load_to_db.load_all(temp_conn)
        counts = load_to_db.table_counts(temp_conn)
        assert counts == {t: load_to_db.csv_row_count(CLEAN_DIR / f"{t}.csv") for t in load_to_db.LOAD_ORDER}
        assert load_to_db.verify_counts(counts) is True

    def test_load_all_from_incomplete_directory_exits(self, temp_conn, tmp_path):
        (tmp_path / "customers.csv").write_bytes((CLEAN_DIR / "customers.csv").read_bytes())
        with pytest.raises(SystemExit, match="service_centers.csv"):
            load_to_db.load_all(temp_conn, tmp_path)

    def test_run_sql_file_executes_multi_statement_script(self, temp_conn, tmp_path):
        script = tmp_path / "script.sql"
        script.write_text(
            "CREATE TEMP TABLE scratch_t (n int);\nINSERT INTO scratch_t VALUES (1), (2), (3);\n", encoding="utf-8")
        load_to_db.run_sql_file(temp_conn, script)
        assert temp_conn.execute("SELECT SUM(n) FROM scratch_t").fetchone()[0] == 6

    def test_run_sql_file_error_propagates(self, temp_conn, tmp_path):
        script = tmp_path / "bad.sql"
        script.write_text("SELECT * FROM table_that_does_not_exist;", encoding="utf-8")
        with pytest.raises(psycopg.errors.UndefinedTable):
            load_to_db.run_sql_file(temp_conn, script)

    def test_transaction_rollback_discards_load(self, settings, conn):
        c = _open(settings)  # fresh session, own TEMP table
        try:
            c.execute(f'CREATE TEMP TABLE "customers" (LIKE {db.DB_SCHEMA}."customers" INCLUDING DEFAULTS)')
            load_to_db.copy_csv(c, "customers", CLEAN_DIR / "customers.csv")
            c.rollback()  # temp table creation is part of the transaction too
            with pytest.raises(psycopg.errors.Error):
                c.execute("SELECT COUNT(*) FROM pg_temp.customers")
        finally:
            c.close()
