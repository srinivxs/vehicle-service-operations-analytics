"""Unit tests for the database layer (no database required).

Covers ``src.db`` (settings + connection helper), ``src.load_to_db`` (loader helpers
and CLI) and ``src.run_sql_reports`` (SQL parsing, report writing and CLI). Every
database interaction is replaced by a fake connection / cursor.
"""
from __future__ import annotations

import re
import runpy
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import psycopg
import pytest

from src import db, load_to_db, run_sql_reports
from src.db import DbSettings, load_settings

pytestmark = pytest.mark.unit

SECRET = "S3cr3t-Pa$$w0rd!"
ENV_VALUES = {
    "POSTGRES_HOST": "db.example.test",
    "POSTGRES_PORT": "6543",
    "POSTGRES_DB": "unit_db",
    "POSTGRES_USER": "unit_user",
    "POSTGRES_PASSWORD": SECRET,
}
NO_ENV_FILE_NAME = "does-not-exist.env"


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def clean_env(monkeypatch):
    """Remove all POSTGRES_* vars, restoring the original environment on teardown.

    ``load_dotenv`` writes to ``os.environ`` directly; registering every variable
    with monkeypatch first guarantees they are reverted afterwards.
    """
    for name in db.REQUIRED_VARS:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def full_env(clean_env):
    for name, value in ENV_VALUES.items():
        clean_env.setenv(name, value)
    return clean_env


@pytest.fixture
def no_env_file(tmp_path) -> Path:
    """Path of a ``.env`` that does not exist, so the real project ``.env`` is never read."""
    return tmp_path / NO_ENV_FILE_NAME


def make_settings(**overrides) -> DbSettings:
    values = dict(host="h", port=5432, dbname="d", user="u", password=SECRET)
    values.update(overrides)
    return DbSettings(**values)


# --------------------------------------------------------------------------- #
# src.db : settings
# --------------------------------------------------------------------------- #
class TestLoadSettings:
    def test_reads_all_values_from_environment(self, full_env, no_env_file):
        s = load_settings(no_env_file)
        assert s == DbSettings("db.example.test", 6543, "unit_db", "unit_user", SECRET)

    def test_port_is_converted_to_int(self, full_env, no_env_file):
        assert isinstance(load_settings(no_env_file).port, int)

    @pytest.mark.parametrize("missing", db.REQUIRED_VARS)
    def test_missing_variable_is_named_and_password_not_leaked(self, full_env, no_env_file, missing):
        full_env.delenv(missing)
        with pytest.raises(SystemExit) as exc:
            load_settings(no_env_file)
        message = str(exc.value)
        assert missing in message
        assert SECRET not in message

    def test_all_missing_lists_every_variable(self, clean_env, no_env_file):
        with pytest.raises(SystemExit) as exc:
            load_settings(no_env_file)
        message = str(exc.value)
        for name in db.REQUIRED_VARS:
            assert name in message

    def test_only_missing_variables_are_listed(self, full_env, no_env_file):
        full_env.delenv("POSTGRES_DB")
        with pytest.raises(SystemExit) as exc:
            load_settings(no_env_file)
        assert "POSTGRES_DB" in str(exc.value)
        assert "POSTGRES_HOST" not in str(exc.value)
        assert "POSTGRES_USER" not in str(exc.value)

    def test_empty_string_counts_as_missing(self, full_env, no_env_file):
        full_env.setenv("POSTGRES_USER", "")
        with pytest.raises(SystemExit, match="POSTGRES_USER"):
            load_settings(no_env_file)

    def test_non_integer_port_gives_clear_error_without_password(self, full_env, no_env_file):
        full_env.setenv("POSTGRES_PORT", "not-a-port")
        with pytest.raises(SystemExit) as exc:
            load_settings(no_env_file)
        assert "POSTGRES_PORT" in str(exc.value)
        assert SECRET not in str(exc.value)

    def test_error_message_points_to_setup_docs(self, clean_env, no_env_file):
        with pytest.raises(SystemExit, match=r"\.env"):
            load_settings(no_env_file)

    def test_env_file_is_loaded(self, clean_env, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(f"{k}={v}" for k, v in ENV_VALUES.items()) + "\n", encoding="utf-8"
        )
        s = load_settings(env_file)
        assert (s.host, s.port, s.dbname, s.user, s.password) == (
            "db.example.test", 6543, "unit_db", "unit_user", SECRET)

    def test_real_environment_takes_precedence_over_env_file(self, full_env, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("POSTGRES_HOST=from-file\n", encoding="utf-8")
        assert load_settings(env_file).host == "db.example.test"

    def test_default_env_file_is_project_root_dotenv(self, clean_env, monkeypatch):
        seen = []
        monkeypatch.setattr(db, "load_dotenv", lambda path: seen.append(path))
        for name, value in ENV_VALUES.items():
            monkeypatch.setenv(name, value)
        load_settings()
        assert seen == [db.PROJECT_ROOT / ".env"]


class TestDbSettings:
    def test_repr_hides_password(self):
        text = repr(make_settings())
        assert SECRET not in text
        assert "password" not in text.lower()
        assert "host='h'" in text and "port=5432" in text and "user='u'" in text

    def test_str_hides_password(self):
        assert SECRET not in str(make_settings())

    def test_display_format(self):
        s = make_settings(host="localhost", port=5432, dbname="vehicle_service", user="analyst")
        assert s.display == "analyst@localhost:5432/vehicle_service"
        assert SECRET not in s.display

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            make_settings().host = "other"  # type: ignore[misc]

    def test_equality_and_hashable(self):
        assert make_settings() == make_settings()
        assert len({make_settings(), make_settings()}) == 1

    def test_constants(self):
        assert db.DB_SCHEMA == "service_ops"
        assert db.SQL_DIR == db.PROJECT_ROOT / "sql"
        assert db.SQL_DIR.is_dir()
        assert "POSTGRES_PASSWORD" in db.REQUIRED_VARS


# --------------------------------------------------------------------------- #
# src.db : connect
# --------------------------------------------------------------------------- #
class TestConnect:
    def test_builds_connection_kwargs(self, monkeypatch):
        captured = {}
        sentinel = object()

        def fake_connect(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(db.psycopg, "connect", fake_connect)
        result = db.connect(make_settings(host="h", port=1234, dbname="d", user="u"))
        assert result is sentinel
        assert captured == {
            "host": "h", "port": 1234, "dbname": "d", "user": "u", "password": SECRET,
            "options": "-c search_path=service_ops,public",
            "autocommit": False, "connect_timeout": 10,
        }

    def test_autocommit_flag_is_forwarded(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(db.psycopg, "connect", lambda **kw: captured.update(kw))
        db.connect(make_settings(), autocommit=True)
        assert captured["autocommit"] is True

    def test_autocommit_is_keyword_only(self):
        with pytest.raises(TypeError):
            db.connect(make_settings(), True)  # type: ignore[misc]

    def test_defaults_to_load_settings(self, monkeypatch):
        settings = make_settings(host="from-load-settings")
        monkeypatch.setattr(db, "load_settings", lambda: settings)
        captured = {}
        monkeypatch.setattr(db.psycopg, "connect", lambda **kw: captured.update(kw))
        db.connect()
        assert captured["host"] == "from-load-settings"

    def test_operational_error_becomes_friendly_exit_without_password(self, monkeypatch):
        def boom(**kwargs):
            raise psycopg.OperationalError("connection refused\n")

        monkeypatch.setattr(db.psycopg, "connect", boom)
        with pytest.raises(SystemExit) as exc:
            db.connect(make_settings(host="dbhost", port=5555, dbname="mydb", user="me"))
        message = str(exc.value)
        assert "me@dbhost:5555/mydb" in message
        assert "connection refused" in message
        assert "docker compose up -d" in message
        assert SECRET not in message
        assert isinstance(exc.value.__cause__, psycopg.OperationalError)

    def test_other_errors_are_not_swallowed(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(db.psycopg, "connect", boom)
        with pytest.raises(RuntimeError):
            db.connect(make_settings())


# --------------------------------------------------------------------------- #
# src.run_sql_reports : slugify / parsing
# --------------------------------------------------------------------------- #
class TestSlugify:
    @pytest.mark.parametrize("text, expected", [
        ("Headline KPI scorecard", "headline_kpi_scorecard"),
        ("  Leading and trailing  ", "leading_and_trailing"),
        ("Mixed CASE & symbols!!", "mixed_case_symbols"),
        ("a---b___c", "a_b_c"),
        ("Year-over-year 2025 vs 2026", "year_over_year_2025_vs_2026"),
        ("", ""),
        ("!!!", ""),
        ("Unicode café ☃ emoji \U0001F697", "unicode_caf_emoji"),
        ("(parens) [brackets] {braces}", "parens_brackets_braces"),
    ])
    def test_examples(self, text, expected):
        assert run_sql_reports.slugify(text) == expected

    def test_truncates_to_max_len(self):
        assert len(run_sql_reports.slugify("a" * 100)) == 48
        assert run_sql_reports.slugify("abcdef", max_len=3) == "abc"

    def test_truncation_never_leaves_trailing_underscore(self):
        # "ab_cd": cutting at 3 chars would end with "_".
        assert run_sql_reports.slugify("ab cd", max_len=3) == "ab"

    def test_result_is_filename_safe(self):
        slug = run_sql_reports.slugify("Weird/\\:*?\"<>| name | with `quotes`")
        assert re.fullmatch(r"[a-z0-9_]*", slug)

    def test_sql_injection_chars_are_stripped(self):
        slug = run_sql_reports.slugify("x'; DROP TABLE users; --")
        assert re.fullmatch(r"[a-z0-9_]*", slug)

    def test_idempotent(self):
        once = run_sql_reports.slugify("Some Title, With Stuff (2025)")
        assert run_sql_reports.slugify(once) == once


KPI_TEXT = """\
-- preamble comment that is not a header
-- Q01 is mentioned here but without a colon
SET search_path TO service_ops, public;

-- Q01: First query title
-- Business question: How many things?
-- Technique: COUNT
SELECT 1 AS n;

-- Q02: Second | query
-- Spec ref: 7: something
SELECT 2 AS n;
"""


class TestParseSections:
    def test_splits_on_headers_and_ignores_preamble(self):
        sections = run_sql_reports.parse_sections(KPI_TEXT)
        assert [s.qid for s in sections] == ["Q01", "Q02"]
        assert [s.title for s in sections] == ["First query title", "Second | query"]

    def test_section_sql_starts_at_header_and_excludes_next_section(self):
        first, second = run_sql_reports.parse_sections(KPI_TEXT)
        assert first.sql.startswith("-- Q01: First query title")
        assert "SELECT 1 AS n;" in first.sql
        assert "Q02" not in first.sql
        assert "SET search_path" not in first.sql
        assert second.sql.endswith("SELECT 2 AS n;")

    def test_question_and_technique_extracted(self):
        first, _ = run_sql_reports.parse_sections(KPI_TEXT)
        assert first.question == "How many things?"
        assert first.technique == "COUNT"

    def test_spec_ref_used_when_no_business_question(self):
        _, second = run_sql_reports.parse_sections(KPI_TEXT)
        assert second.question == "7: something"
        assert second.technique == ""

    def test_business_question_wins_over_spec_ref(self):
        text = "-- Q01: T\n-- Spec ref: spec\n-- Business question: biz\nSELECT 1;"
        assert run_sql_reports.parse_sections(text)[0].question == "biz"

    def test_labels_are_case_insensitive(self):
        text = "-- Q01: T\n-- business QUESTION: why?\n-- technique: cte\nSELECT 1;"
        s = run_sql_reports.parse_sections(text)[0]
        assert (s.question, s.technique) == ("why?", "cte")

    def test_empty_text_has_no_sections(self):
        assert run_sql_reports.parse_sections("") == []

    def test_text_without_headers_has_no_sections(self):
        assert run_sql_reports.parse_sections("SELECT 1;\n-- just a comment\n") == []

    def test_header_without_body(self):
        sections = run_sql_reports.parse_sections("-- Q01: Lonely header")
        assert len(sections) == 1
        assert sections[0].sql == "-- Q01: Lonely header"
        assert sections[0].question == ""

    def test_consecutive_headers_each_become_a_section(self):
        sections = run_sql_reports.parse_sections("-- Q01: A\n-- Q02: B\nSELECT 2;")
        assert [s.qid for s in sections] == ["Q01", "Q02"]
        assert sections[0].sql == "-- Q01: A"
        assert "SELECT 2;" in sections[1].sql

    def test_dq_headers(self):
        text = ("-- SQL-DQ01: Dup ids\nSELECT 'SQL-DQ01';\n"
                "-- SQL-DQ99: Summary\nSELECT 'all';\n")
        sections = run_sql_reports.parse_sections(text)
        assert [s.qid for s in sections] == ["SQL-DQ01", "SQL-DQ99"]

    def test_dq_mention_without_colon_is_not_a_header(self):
        text = "-- SQL-DQ99 is the summary of everything above\n-- SQL-DQ01: Real\nSELECT 1;"
        sections = run_sql_reports.parse_sections(text)
        assert [s.qid for s in sections] == ["SQL-DQ01"]

    def test_header_must_start_the_line(self):
        text = "SELECT 1; -- Q01: trailing comment, not a header\n"
        assert run_sql_reports.parse_sections(text) == []

    def test_extra_whitespace_in_header(self):
        s = run_sql_reports.parse_sections("--   Q07:    Spaced   title   \nSELECT 1;")[0]
        assert (s.qid, s.title) == ("Q07", "Spaced   title")

    def test_title_with_colon_keeps_everything_after_first_colon(self):
        s = run_sql_reports.parse_sections("-- Q03: Shop hours (09:00-19:00)\nSELECT 1;")[0]
        assert s.title == "Shop hours (09:00-19:00)"

    def test_header_with_empty_title_does_not_steal_body_line_as_title(self):
        sections = run_sql_reports.parse_sections("-- Q01:\nSELECT 1;")
        assert not sections or sections[0].title != "SELECT 1;"

    def test_crlf_line_endings(self):
        text = "-- Q01: Windows\r\n-- Technique: JOIN\r\nSELECT 1;\r\n-- Q02: Next\r\nSELECT 2;\r\n"
        sections = run_sql_reports.parse_sections(text)
        assert [s.title for s in sections] == ["Windows", "Next"]
        assert sections[0].technique == "JOIN"

    def test_comment_inside_body_does_not_split(self):
        text = "-- Q01: T\nSELECT 1; -- inline Q99: nope\n-- more commentary\nSELECT 2;"
        sections = run_sql_reports.parse_sections(text)
        assert len(sections) == 1
        assert "SELECT 2;" in sections[0].sql

    def test_unicode_title(self):
        s = run_sql_reports.parse_sections("-- Q01: Café ₹ revenue\nSELECT 1;")[0]
        assert s.title == "Café ₹ revenue"

    def test_multi_digit_ids(self):
        sections = run_sql_reports.parse_sections("-- Q100: Big\nSELECT 1;")
        assert sections[0].qid == "Q100"

    def test_real_kpi_file_parses_to_21_sequential_queries(self):
        text = (db.SQL_DIR / "kpi_queries.sql").read_text(encoding="utf-8")
        sections = run_sql_reports.parse_sections(text)
        assert [s.qid for s in sections] == [f"Q{i:02d}" for i in range(1, 22)]
        assert all(s.title and "SELECT" in s.sql.upper() for s in sections)

    def test_real_data_quality_file_parses_to_50_checks_plus_summary(self):
        text = (db.SQL_DIR / "data_quality.sql").read_text(encoding="utf-8")
        sections = run_sql_reports.parse_sections(text)
        ids = [s.qid for s in sections]
        assert ids == [f"SQL-DQ{i:02d}" for i in range(1, 51)] + [run_sql_reports.SUMMARY_ID]
        assert len(set(ids)) == len(ids)


class TestCommentValue:
    def test_missing_label_returns_empty(self):
        assert run_sql_reports._comment_value("-- nothing here", "Technique") == ""

    def test_value_is_stripped(self):
        assert run_sql_reports._comment_value("-- Technique:    CTE   ", "Technique") == "CTE"

    def test_label_must_be_at_line_start(self):
        assert run_sql_reports._comment_value("SELECT 1; -- Technique: X", "Technique") == ""


# --------------------------------------------------------------------------- #
# src.run_sql_reports : formatting helpers
# --------------------------------------------------------------------------- #
class TestFormatting:
    def test_plain_converts_decimal_only(self):
        assert run_sql_reports._plain(Decimal("1.50")) == 1.5
        assert isinstance(run_sql_reports._plain(Decimal("1.50")), float)
        assert run_sql_reports._plain(3) == 3
        assert run_sql_reports._plain("x") == "x"
        assert run_sql_reports._plain(None) is None

    @pytest.mark.parametrize("value, expected", [
        (None, ""),
        (float("nan"), ""),
        (0.0, "0"),
        (100.0, "100"),
        (1234.5, "1,234.5"),
        (0.123456, "0.1235"),
        (1_000_000.0, "1,000,000"),
        (-2.50, "-2.5"),
        (7, "7"),
        ("text", "text"),
        ("a|b", "a\\|b"),
        (True, "True"),
    ])
    def test_fmt(self, value, expected):
        assert run_sql_reports._fmt(value) == expected

    def test_markdown_table_shape(self):
        frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y|z", None]})
        lines = run_sql_reports.markdown_table(frame).splitlines()
        assert lines[0] == "| a | b |"
        assert lines[1] == "|---|---|"
        assert lines[2] == "| 1 | x |"
        assert lines[3] == "| 2 | y\\|z |"
        assert lines[4] == "| 3 |  |"

    def test_markdown_table_limits_rows(self):
        frame = pd.DataFrame({"n": range(20)})
        lines = run_sql_reports.markdown_table(frame).splitlines()
        assert len(lines) == 2 + run_sql_reports.PREVIEW_ROWS

    def test_markdown_table_custom_and_unlimited_rows(self):
        frame = pd.DataFrame({"n": range(20)})
        assert len(run_sql_reports.markdown_table(frame, max_rows=2).splitlines()) == 4
        assert len(run_sql_reports.markdown_table(frame, max_rows=None).splitlines()) == 22

    def test_markdown_table_empty_frame(self):
        lines = run_sql_reports.markdown_table(pd.DataFrame({"a": [], "b": []})).splitlines()
        assert lines == ["| a | b |", "|---|---|"]

    def test_markdown_table_float_formatting(self):
        frame = pd.DataFrame({"pct": [12.3456789, 50.0]})
        body = run_sql_reports.markdown_table(frame).splitlines()[2:]
        assert body == ["| 12.3457 |", "| 50 |"]


# --------------------------------------------------------------------------- #
# src.run_sql_reports : running sections with a fake connection
# --------------------------------------------------------------------------- #
class FakeCursor:
    def __init__(self, columns=("a", "b"), rows=(), error: Exception | None = None, no_description=False):
        self._columns = columns
        self._rows = list(rows)
        self._error = error
        self._no_description = no_description
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self.executed.append(query)
        if self._error is not None:
            raise self._error
        return self

    @property
    def description(self):
        if self._no_description:
            return None
        return [SimpleNamespace(name=c) for c in self._columns]

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, cursor: FakeCursor | None = None):
        self._cursor = cursor or FakeCursor()
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rollbacks += 1


class TestRunSection:
    def test_returns_dataframe_with_converted_decimals(self):
        cur = FakeCursor(columns=("name", "amt"), rows=[("x", Decimal("1.5")), ("y", Decimal("2"))])
        result = run_sql_reports.run_section(FakeConn(cur), run_sql_reports.Section("Q01", "T", "SELECT 1"))
        assert result.error is None
        assert list(result.frame.columns) == ["name", "amt"]
        assert result.frame["amt"].tolist() == [1.5, 2.0]
        assert result.frame["amt"].dtype.kind == "f"
        assert cur.executed == ["SELECT 1"]

    def test_empty_result_keeps_columns(self):
        cur = FakeCursor(columns=("a", "b"), rows=[])
        result = run_sql_reports.run_section(FakeConn(cur), run_sql_reports.Section("Q01", "T", "SELECT"))
        assert result.frame is not None and result.frame.empty
        assert list(result.frame.columns) == ["a", "b"]

    def test_database_error_is_captured_and_rolled_back(self):
        cur = FakeCursor(error=psycopg.Error("relation \"nope\" does not exist\nLINE 1: SELECT"))
        conn = FakeConn(cur)
        result = run_sql_reports.run_section(conn, run_sql_reports.Section("Q09", "Bad", "SELECT"))
        assert result.frame is None
        assert result.error == 'relation "nope" does not exist'
        assert conn.rollbacks == 1

    def test_non_database_errors_propagate(self):
        cur = FakeCursor(error=ValueError("bug"))
        with pytest.raises(ValueError):
            run_sql_reports.run_section(FakeConn(cur), run_sql_reports.Section("Q01", "T", "SELECT"))

    def test_statement_without_result_set_is_handled_by_description_none(self):
        cur = FakeCursor(rows=[], no_description=True)
        result = run_sql_reports.run_section(FakeConn(cur), run_sql_reports.Section("Q01", "T", "SET x"))
        assert result.frame is not None and result.frame.shape == (0, 0)


def ok_result(qid: str, title: str = "T", frame: pd.DataFrame | None = None) -> run_sql_reports.QueryResult:
    section = run_sql_reports.Section(qid, title, "SELECT 1")
    if frame is None:
        frame = pd.DataFrame({"n": [1, 2]})
    return run_sql_reports.QueryResult(section, frame=frame)


def failed_result(qid: str, error: str = "boom") -> run_sql_reports.QueryResult:
    return run_sql_reports.QueryResult(run_sql_reports.Section(qid, "T", "SELECT 1"), error=error)


def dq_frame(rows: list[tuple[str, int]], with_status: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame(
        [(cid, f"name {cid}", "integrity", n) for cid, n in rows],
        columns=["check_id", "check_name", "check_type", "issue_count"],
    )
    if with_status:
        frame["status"] = ["PASS" if n == 0 else "FAIL" for _, n in rows]
    return frame


class TestSaveResults:
    def test_save_kpi_results_writes_named_csvs(self, tmp_path):
        results = [ok_result("Q01", "Headline KPI scorecard"), failed_result("Q02"), ok_result("Q03", "Third")]
        run_sql_reports.save_kpi_results(results, tmp_path)
        assert results[0].csv_name == "Q01_headline_kpi_scorecard.csv"
        assert results[1].csv_name == ""
        assert results[2].csv_name == "Q03_third.csv"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["Q01_headline_kpi_scorecard.csv", "Q03_third.csv"]
        assert pd.read_csv(tmp_path / "Q03_third.csv")["n"].tolist() == [1, 2]

    def test_save_kpi_results_has_no_index_column(self, tmp_path):
        run_sql_reports.save_kpi_results([ok_result("Q01", "x")], tmp_path)
        assert (tmp_path / "Q01_x.csv").read_text().splitlines()[0] == "n"

    def test_save_kpi_results_with_no_results(self, tmp_path):
        run_sql_reports.save_kpi_results([], tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_save_dq_combines_and_saves_summary(self, tmp_path, capsys):
        a = ok_result("SQL-DQ01", frame=dq_frame([("SQL-DQ01", 0)]))
        b = ok_result("SQL-DQ02", frame=dq_frame([("SQL-DQ02", 3)]))
        summary = ok_result("SQL-DQ99", frame=dq_frame([("SQL-DQ01", 0), ("SQL-DQ02", 3)], with_status=True))
        saved = run_sql_reports.save_dq_results([a, b, summary], tmp_path)
        assert saved == [summary]
        assert summary.csv_name == "SQL-DQ99_data_quality_summary.csv"
        combined = pd.read_csv(tmp_path / "SQL_DQ_all_checks.csv")
        assert combined["check_id"].tolist() == ["SQL-DQ01", "SQL-DQ02"]
        assert (tmp_path / summary.csv_name).exists()
        assert "== SQL-DQ99 summary: yes" in capsys.readouterr().out

    def test_save_dq_reports_mismatch(self, tmp_path, capsys):
        a = ok_result("SQL-DQ01", frame=dq_frame([("SQL-DQ01", 0)]))
        summary = ok_result("SQL-DQ99", frame=dq_frame([("SQL-DQ01", 5)], with_status=True))
        run_sql_reports.save_dq_results([a, summary], tmp_path)
        assert "NO (investigate)" in capsys.readouterr().out

    def test_save_dq_without_summary_returns_empty_but_still_writes_combined(self, tmp_path):
        a = ok_result("SQL-DQ01", frame=dq_frame([("SQL-DQ01", 0)]))
        assert run_sql_reports.save_dq_results([a], tmp_path) == []
        assert (tmp_path / "SQL_DQ_all_checks.csv").exists()
        assert not (tmp_path / "SQL-DQ99_data_quality_summary.csv").exists()

    def test_save_dq_skips_failed_checks(self, tmp_path):
        a = ok_result("SQL-DQ01", frame=dq_frame([("SQL-DQ01", 0)]))
        results = [a, failed_result("SQL-DQ02")]
        run_sql_reports.save_dq_results(results, tmp_path)
        assert pd.read_csv(tmp_path / "SQL_DQ_all_checks.csv")["check_id"].tolist() == ["SQL-DQ01"]

    def test_save_dq_with_no_results_writes_empty_combined(self, tmp_path):
        assert run_sql_reports.save_dq_results([], tmp_path) == []
        assert (tmp_path / "SQL_DQ_all_checks.csv").exists()

    def test_save_dq_summary_only_does_not_crash(self, tmp_path):
        """Summary succeeded while every individual check failed: should still save the summary."""
        summary = ok_result("SQL-DQ99", frame=dq_frame([("SQL-DQ01", 0)], with_status=True))
        saved = run_sql_reports.save_dq_results([failed_result("SQL-DQ01"), summary], tmp_path)
        assert saved == [summary]


class TestBuildReadme:
    def test_lists_queries_with_row_counts_and_csv_names(self):
        kpi = [ok_result("Q01", "First", pd.DataFrame({"n": range(1234)})), failed_result("Q02", "bad sql")]
        kpi[0].csv_name = "Q01_first.csv"
        text = run_sql_reports.build_readme(kpi, [])
        assert "# SQL query results" in text
        assert "| Q01 | First | 1,234 | `Q01_first.csv` |" in text
        assert "| Q02 | T | FAILED | `` |" in text
        assert "**FAILED:** bad sql" in text
        assert "1,234 rows x 1 columns - first 5 rows:" in text

    def test_includes_question_and_technique_when_present(self):
        r = ok_result("Q01")
        r.section.question = "What is up?"
        r.section.technique = "CTE"
        text = run_sql_reports.build_readme([r], [])
        assert "*What is up?*" in text
        assert "Technique: CTE" in text

    def test_omits_question_and_technique_when_absent(self):
        text = run_sql_reports.build_readme([ok_result("Q01")], [])
        assert "Technique:" not in text
        assert "*What" not in text

    def test_preview_row_count_is_capped_by_frame_size(self):
        text = run_sql_reports.build_readme([ok_result("Q01", frame=pd.DataFrame({"n": [1, 2]}))], [])
        assert "2 rows x 1 columns - first 2 rows:" in text

    def test_dq_section_with_frame(self):
        dq = ok_result("SQL-DQ99", frame=dq_frame([("SQL-DQ01", 0)], with_status=True))
        dq.csv_name = "SQL-DQ99_data_quality_summary.csv"
        text = run_sql_reports.build_readme([], [dq])
        assert "## Data-quality checks" in text
        assert "`SQL-DQ99_data_quality_summary.csv`" in text
        assert "| SQL-DQ01 | name SQL-DQ01 | integrity | 0 | PASS |" in text

    def test_dq_section_with_failure(self):
        text = run_sql_reports.build_readme([], [failed_result("SQL-DQ99", "kaput")])
        assert "**SQL-DQ99 FAILED:** kaput" in text

    def test_pipe_in_title_is_not_escaped_in_the_index_table_but_values_are_escaped_in_previews(self):
        frame = pd.DataFrame({"v": ["a|b"]})
        text = run_sql_reports.build_readme([ok_result("Q01", frame=frame)], [])
        assert "a\\|b" in text

    def test_empty_inputs_still_produce_document(self):
        text = run_sql_reports.build_readme([], [])
        assert text.startswith("# SQL query results")
        assert "## Business queries" in text and "## Data-quality checks" in text


# --------------------------------------------------------------------------- #
# src.run_sql_reports : main()
# --------------------------------------------------------------------------- #
class _CtxConn:
    """Connection usable as a context manager, recording how it was opened."""

    def __init__(self):
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False


@pytest.fixture
def report_env(tmp_path, monkeypatch):
    """Tiny SQL dir + tmp output dir + fake connect/run_section wired into run_sql_reports."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "kpi_queries.sql").write_text(
        "-- Q01: Alpha query\n-- Technique: JOIN\nSELECT 1;\n-- Q02: Beta query\nSELECT 2;\n", encoding="utf-8")
    (sql_dir / "data_quality.sql").write_text(
        "-- SQL-DQ01: First\nSELECT 1;\n-- SQL-DQ99: Summary\nSELECT 99;\n", encoding="utf-8")
    out_dir = tmp_path / "out" / "sql_results"  # does not exist yet: main() must create it
    conn = _CtxConn()
    connect_calls = []

    def fake_connect(*args, **kwargs):
        connect_calls.append(kwargs)
        return conn

    monkeypatch.setattr(run_sql_reports, "SQL_DIR", sql_dir)
    monkeypatch.setattr(run_sql_reports, "OUT_DIR", out_dir)
    monkeypatch.setattr(run_sql_reports, "connect", fake_connect)

    def fake_run_section(_conn, section):
        assert _conn is conn
        if section.qid.startswith("SQL-DQ"):
            frame = dq_frame([("SQL-DQ01", 0)], with_status=section.qid == "SQL-DQ99")
            return run_sql_reports.QueryResult(section, frame=frame)
        return run_sql_reports.QueryResult(section, frame=pd.DataFrame({"n": [1, 2, 3]}))

    monkeypatch.setattr(run_sql_reports, "run_section", fake_run_section)
    return SimpleNamespace(sql_dir=sql_dir, out_dir=out_dir, conn=conn, connect_calls=connect_calls,
                           monkeypatch=monkeypatch)


class TestRunSqlReportsMain:
    def test_success_writes_all_artifacts(self, report_env, capsys):
        assert run_sql_reports.main() == 0
        out = report_env.out_dir
        names = sorted(p.name for p in out.iterdir())
        assert names == [
            "Q01_alpha_query.csv", "Q02_beta_query.csv", "README.md",
            "SQL-DQ99_data_quality_summary.csv", "SQL_DQ_all_checks.csv",
        ]
        readme = (out / "README.md").read_text(encoding="utf-8")
        assert "| Q01 | Alpha query | 3 |" in readme
        assert "Technique: JOIN" in readme
        printed = capsys.readouterr().out
        assert "Running 2 business queries and 2 data-quality queries" in printed
        assert "Saved results and README.md" in printed

    def test_uses_autocommit_connection_and_closes_it(self, report_env):
        run_sql_reports.main()
        assert report_env.connect_calls == [{"autocommit": True}]
        assert report_env.conn.entered and report_env.conn.exited

    def test_failed_query_returns_exit_code_1_and_is_reported(self, report_env, capsys):
        original = run_sql_reports.run_section

        def sometimes_fail(conn, section):
            if section.qid == "Q02":
                return run_sql_reports.QueryResult(section, error="relation missing")
            return original(conn, section)

        report_env.monkeypatch.setattr(run_sql_reports, "run_section", sometimes_fail)
        assert run_sql_reports.main() == 1
        assert "FAILED: relation missing" in capsys.readouterr().out
        assert not (report_env.out_dir / "Q02_beta_query.csv").exists()
        assert "**FAILED:** relation missing" in (report_env.out_dir / "README.md").read_text(encoding="utf-8")

    def test_failed_dq_query_is_printed_and_returns_1(self, report_env, capsys):
        original = run_sql_reports.run_section

        def fail_dq99(conn, section):
            if section.qid == "SQL-DQ99":
                return run_sql_reports.QueryResult(section, error="dq99 broke")
            return original(conn, section)

        report_env.monkeypatch.setattr(run_sql_reports, "run_section", fail_dq99)
        assert run_sql_reports.main() == 1
        assert "SQL-DQ99 FAILED: dq99 broke" in capsys.readouterr().out
        readme = (report_env.out_dir / "README.md").read_text(encoding="utf-8")
        assert "**SQL-DQ99 FAILED:** dq99 broke" in readme

    def test_missing_sql_file_raises_before_connecting(self, report_env):
        (report_env.sql_dir / "kpi_queries.sql").unlink()
        with pytest.raises(FileNotFoundError):
            run_sql_reports.main()
        assert report_env.connect_calls == []

    def test_existing_output_dir_is_fine(self, report_env):
        report_env.out_dir.mkdir(parents=True)
        assert run_sql_reports.main() == 0

    def test_never_touches_real_reports_dir(self, report_env):
        real = run_sql_reports.REPORTS_DIR / "sql_results"
        before = {p.name: p.stat().st_mtime_ns for p in real.glob("*")} if real.exists() else {}
        run_sql_reports.main()
        after = {p.name: p.stat().st_mtime_ns for p in real.glob("*")} if real.exists() else {}
        assert before == after

    def test_module_constants(self):
        assert run_sql_reports.SUMMARY_ID == "SQL-DQ99"
        assert run_sql_reports.PREVIEW_ROWS == 5


# --------------------------------------------------------------------------- #
# src.load_to_db : helpers
# --------------------------------------------------------------------------- #
def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def schema_foreign_keys() -> dict[str, set[str]]:
    """Parse sql/schema.sql: table -> set of tables it references (excluding itself)."""
    text = (db.SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    text = re.sub(r"--[^\n]*", "", text)
    deps: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE\s+(\w+)\s*\((.*?)\n\);", text, re.DOTALL | re.IGNORECASE):
        table, body = m.group(1), m.group(2)
        deps[table] = {r for r in re.findall(r"REFERENCES\s+(\w+)", body, re.IGNORECASE) if r != table}
    return deps


class TestLoadOrder:
    def test_has_ten_unique_tables(self):
        assert len(load_to_db.LOAD_ORDER) == 10
        assert len(set(load_to_db.LOAD_ORDER)) == 10

    def test_matches_tables_defined_in_schema(self):
        assert set(load_to_db.LOAD_ORDER) == set(schema_foreign_keys())

    def test_parents_are_loaded_before_children(self):
        position = {t: i for i, t in enumerate(load_to_db.LOAD_ORDER)}
        for child, parents in schema_foreign_keys().items():
            for parent in parents:
                assert position[parent] < position[child], f"{parent} must load before {child}"

    def test_schema_parser_finds_known_foreign_keys(self):
        deps = schema_foreign_keys()
        assert deps["work_orders"] == {"appointments", "technicians"}
        assert deps["customers"] == set()

    @pytest.mark.parametrize("table", load_to_db.LOAD_ORDER)
    def test_every_table_has_a_cleaned_csv(self, table):
        assert (load_to_db.CLEAN_DIR / f"{table}.csv").is_file()

    def test_constants(self):
        assert load_to_db.CHUNK_BYTES == 1 << 20
        assert load_to_db.CLEAN_DIR.name == "cleaned"


class TestCsvHelpers:
    def test_csv_columns(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id", "name", "city"], [["1", "a", "b"]])
        assert load_to_db.csv_columns(p) == ["id", "name", "city"]

    def test_csv_columns_header_only(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id"], [])
        assert load_to_db.csv_columns(p) == ["id"]

    def test_csv_columns_quoted_and_unicode(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["a,b", "café", 'q"uote'], [])
        assert load_to_db.csv_columns(p) == ["a,b", "café", 'q"uote']

    def test_csv_columns_empty_file_raises(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        with pytest.raises(StopIteration):
            load_to_db.csv_columns(p)

    def test_csv_columns_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_to_db.csv_columns(tmp_path / "nope.csv")

    def test_csv_row_count_excludes_header(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id"], [["1"], ["2"], ["3"]])
        assert load_to_db.csv_row_count(p) == 3

    def test_csv_row_count_header_only_is_zero(self, tmp_path):
        assert load_to_db.csv_row_count(write_csv(tmp_path / "t.csv", ["id"], [])) == 0

    def test_csv_row_count_counts_records_not_physical_lines(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id", "note"], [["1", "line one\nline two"], ["2", "x"]])
        assert len(p.read_text(encoding="utf-8").splitlines()) == 4
        assert load_to_db.csv_row_count(p) == 2

    def test_csv_row_count_no_trailing_newline(self, tmp_path):
        p = tmp_path / "t.csv"
        p.write_bytes(b"id\n1\n2")
        assert load_to_db.csv_row_count(p) == 2

    def test_csv_row_count_crlf(self, tmp_path):
        p = tmp_path / "t.csv"
        p.write_bytes(b"id\r\n1\r\n2\r\n")
        assert load_to_db.csv_row_count(p) == 2

    def test_csv_row_count_large_file(self, tmp_path):
        p = write_csv(tmp_path / "big.csv", ["id", "v"], [[str(i), "x"] for i in range(20_000)])
        assert load_to_db.csv_row_count(p) == 20_000


class FakeCopy:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data):
        self.chunks.append(bytes(data))


class FakeCopyCursor:
    def __init__(self):
        self.copy_obj = FakeCopy()
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def copy(self, statement):
        self.statement = statement
        yield self.copy_obj


class CopyConn:
    def __init__(self):
        self.cur = FakeCopyCursor()

    def cursor(self):
        return self.cur


class TestCopyCsv:
    def test_statement_uses_quoted_identifiers_from_csv_header(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id", "Odd Name", 'we"ird'], [["1", "2", "3"]])
        conn = CopyConn()
        load_to_db.copy_csv(conn, "my_table", p)
        stmt = conn.cur.statement.as_string(None)
        assert stmt == ('COPY "my_table" ("id", "Odd Name", "we""ird") '
                        "FROM STDIN WITH (FORMAT csv, HEADER true)")

    def test_streams_whole_file_content(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id", "v"], [["1", "café"], ["2", "x"]])
        conn = CopyConn()
        load_to_db.copy_csv(conn, "t", p)
        assert b"".join(conn.cur.copy_obj.chunks) == p.read_bytes()

    def test_chunking_splits_large_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(load_to_db, "CHUNK_BYTES", 16)
        p = write_csv(tmp_path / "t.csv", ["id", "v"], [[str(i), "payload"] for i in range(30)])
        conn = CopyConn()
        load_to_db.copy_csv(conn, "t", p)
        chunks = conn.cur.copy_obj.chunks
        assert len(chunks) > 1
        assert all(len(c) <= 16 for c in chunks)
        assert b"".join(chunks) == p.read_bytes()

    def test_header_only_file_still_sends_header(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id"], [])
        conn = CopyConn()
        load_to_db.copy_csv(conn, "t", p)
        assert b"".join(conn.cur.copy_obj.chunks) == b"id\r\n"

    def test_table_name_is_quoted_not_interpolated(self, tmp_path):
        p = write_csv(tmp_path / "t.csv", ["id"], [])
        conn = CopyConn()
        load_to_db.copy_csv(conn, 'x"; DROP TABLE y; --', p)
        stmt = conn.cur.statement.as_string(None)
        assert stmt.startswith('COPY "x""; DROP TABLE y; --" (')

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_to_db.copy_csv(CopyConn(), "t", tmp_path / "nope.csv")


class TestRunSqlFile:
    def test_executes_file_contents(self, tmp_path):
        script = tmp_path / "s.sql"
        script.write_text("SELECT 'café';\nSELECT 2;", encoding="utf-8")
        executed = []
        conn = SimpleNamespace(execute=lambda text: executed.append(text))
        load_to_db.run_sql_file(conn, script)
        assert executed == ["SELECT 'café';\nSELECT 2;"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_to_db.run_sql_file(SimpleNamespace(execute=lambda t: None), tmp_path / "x.sql")


class TestLoadAll:
    def test_copies_every_table_in_order(self, tmp_path, monkeypatch):
        for table in load_to_db.LOAD_ORDER:
            write_csv(tmp_path / f"{table}.csv", ["id"], [["1"]])
        calls = []
        monkeypatch.setattr(load_to_db, "copy_csv", lambda conn, table, path: calls.append((conn, table, path)))
        conn = object()
        load_to_db.load_all(conn, tmp_path)
        assert [c[1] for c in calls] == list(load_to_db.LOAD_ORDER)
        assert all(c[0] is conn for c in calls)
        assert [c[2] for c in calls] == [tmp_path / f"{t}.csv" for t in load_to_db.LOAD_ORDER]

    def test_missing_csv_exits_with_helpful_message(self, tmp_path, monkeypatch):
        for table in load_to_db.LOAD_ORDER[:3]:
            write_csv(tmp_path / f"{table}.csv", ["id"], [["1"]])
        calls = []
        monkeypatch.setattr(load_to_db, "copy_csv", lambda conn, table, path: calls.append(table))
        with pytest.raises(SystemExit) as exc:
            load_to_db.load_all(object(), tmp_path)
        missing = load_to_db.LOAD_ORDER[3]
        assert f"{missing}.csv" in str(exc.value)
        assert "data_cleaning" in str(exc.value)
        assert calls == list(load_to_db.LOAD_ORDER[:3])  # stopped at the first missing file

    def test_default_dir_is_config_clean_dir(self, monkeypatch):
        seen = []
        monkeypatch.setattr(load_to_db, "copy_csv", lambda conn, table, path: seen.append(path.parent))
        load_to_db.load_all(object())
        assert set(seen) == {load_to_db.CLEAN_DIR}


class CountConn:
    """Fake connection answering ``SELECT COUNT(*) FROM <table>`` / information_schema queries."""

    def __init__(self, counts: dict[str, int] | None = None, views: list[str] | None = None,
                 empty_rows_for: set[str] = frozenset()):
        self.counts = counts or {}
        self.views = views or []
        self.empty_rows_for = empty_rows_for
        self.queries: list = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        text = query if isinstance(query, str) else query.as_string(None)
        m = re.match(r'SELECT COUNT\(\*\) FROM "(\w+)"', text)
        if m:
            table = m.group(1)
            row = None if table in self.empty_rows_for else (self.counts.get(table, 0),)
            return SimpleNamespace(fetchone=lambda: row)
        return SimpleNamespace(fetchall=lambda: [(v,) for v in self.views])


class TestTableCounts:
    def test_returns_count_for_every_table(self):
        counts = {t: i * 10 for i, t in enumerate(load_to_db.LOAD_ORDER)}
        assert load_to_db.table_counts(CountConn(counts)) == counts

    def test_queries_follow_load_order(self):
        conn = CountConn()
        load_to_db.table_counts(conn)
        tables = [re.search(r'"(\w+)"', q.as_string(None)).group(1) for q, _ in conn.queries]
        assert tables == list(load_to_db.LOAD_ORDER)

    def test_missing_row_counts_as_zero(self):
        conn = CountConn({"customers": 5}, empty_rows_for={"customers"})
        assert load_to_db.table_counts(conn)["customers"] == 0

    def test_decimal_like_counts_become_int(self):
        conn = CountConn({t: 1 for t in load_to_db.LOAD_ORDER})
        assert all(type(v) is int for v in load_to_db.table_counts(conn).values())


class TestListViews:
    def test_returns_names_and_passes_schema_parameter(self):
        conn = CountConn(views=["vw_a", "vw_b"])
        assert load_to_db.list_views(conn) == ["vw_a", "vw_b"]
        query, params = conn.queries[0]
        assert "information_schema.views" in query
        assert params == (db.DB_SCHEMA,)

    def test_no_views(self):
        assert load_to_db.list_views(CountConn(views=[])) == []


@pytest.fixture
def clean_dir_with_rows(tmp_path):
    """A clean dir where each table CSV has (index + 1) data rows."""
    expected = {}
    for i, table in enumerate(load_to_db.LOAD_ORDER):
        write_csv(tmp_path / f"{table}.csv", ["id"], [[str(n)] for n in range(i + 1)])
        expected[table] = i + 1
    return tmp_path, expected


class TestVerifyCounts:
    def test_true_when_all_match(self, clean_dir_with_rows, capsys):
        directory, expected = clean_dir_with_rows
        assert load_to_db.verify_counts(expected, directory) is True
        out = capsys.readouterr().out
        assert out.count("OK") == len(load_to_db.LOAD_ORDER)
        assert "MISMATCH" not in out

    def test_false_when_one_table_differs_and_others_still_reported(self, clean_dir_with_rows, capsys):
        directory, expected = clean_dir_with_rows
        counts = dict(expected, vehicles=expected["vehicles"] + 1)
        assert load_to_db.verify_counts(counts, directory) is False
        out = capsys.readouterr().out
        assert out.count("MISMATCH") == 1
        assert out.count("OK") == len(load_to_db.LOAD_ORDER) - 1
        assert re.search(r"vehicles\s+4\s+5\s+MISMATCH", out)

    def test_all_mismatching(self, clean_dir_with_rows, capsys):
        directory, expected = clean_dir_with_rows
        counts = {t: 0 for t in expected}
        assert load_to_db.verify_counts(counts, directory) is False
        assert capsys.readouterr().out.count("MISMATCH") == len(expected)

    def test_prints_header_and_thousands_separators(self, tmp_path, capsys):
        for table in load_to_db.LOAD_ORDER:
            write_csv(tmp_path / f"{table}.csv", ["id"], [["1"]] * 1)
        write_csv(tmp_path / "customers.csv", ["id"], [[str(i)] for i in range(1500)])
        counts = {t: 1 for t in load_to_db.LOAD_ORDER}
        counts["customers"] = 1500
        assert load_to_db.verify_counts(counts, tmp_path) is True
        out = capsys.readouterr().out
        assert "table" in out and "csv rows" in out and "db rows" in out
        assert "1,500" in out

    def test_missing_csv_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_to_db.verify_counts({t: 0 for t in load_to_db.LOAD_ORDER}, tmp_path)

    def test_missing_table_in_counts_raises_keyerror(self, clean_dir_with_rows):
        directory, expected = clean_dir_with_rows
        expected.pop("feedback")
        with pytest.raises(KeyError):
            load_to_db.verify_counts(expected, directory)

    def test_empty_table_matches_header_only_csv(self, tmp_path, capsys):
        for table in load_to_db.LOAD_ORDER:
            write_csv(tmp_path / f"{table}.csv", ["id"], [])
        assert load_to_db.verify_counts({t: 0 for t in load_to_db.LOAD_ORDER}, tmp_path) is True


# --------------------------------------------------------------------------- #
# src.load_to_db : CLI
# --------------------------------------------------------------------------- #
class TestParseArgs:
    def test_defaults(self):
        assert load_to_db.parse_args([]).no_views is False

    def test_no_views_flag(self):
        assert load_to_db.parse_args(["--no-views"]).no_views is True

    def test_unknown_flag_exits_with_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            load_to_db.parse_args(["--bogus"])
        assert exc.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err

    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            load_to_db.parse_args(["--help"])
        assert exc.value.code == 0
        assert "--no-views" in capsys.readouterr().out

    def test_reads_sys_argv_when_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--no-views"])
        assert load_to_db.parse_args().no_views is True


@pytest.fixture
def main_env(monkeypatch):
    """Replace every DB-touching collaborator of ``load_to_db.main`` with recorders."""
    log: list[tuple] = []
    settings = make_settings(host="mainhost", port=1, dbname="maindb", user="mainuser")

    class Conn:
        def __enter__(self):
            log.append(("enter",))
            return self

        def __exit__(self, exc_type, exc, tb):
            log.append(("exit", exc_type))
            return False

        def rollback(self):
            log.append(("rollback",))

    state = SimpleNamespace(log=log, counts={t: 1 for t in load_to_db.LOAD_ORDER}, views=["vw_one", "vw_two"],
                            verify_result=True, connect_settings=None)

    monkeypatch.setattr(load_to_db, "load_settings", lambda: settings)

    def fake_connect(s):
        state.connect_settings = s
        return Conn()

    monkeypatch.setattr(load_to_db, "connect", fake_connect)
    monkeypatch.setattr(load_to_db, "run_sql_file", lambda conn, path: log.append(("sql", path.name)))
    monkeypatch.setattr(load_to_db, "load_all", lambda conn: log.append(("load_all",)))
    monkeypatch.setattr(load_to_db, "table_counts", lambda conn: state.counts)
    monkeypatch.setattr(load_to_db, "list_views", lambda conn: state.views)
    monkeypatch.setattr(load_to_db, "verify_counts", lambda counts: (log.append(("verify", counts)), state.verify_result)[1])
    state.settings = settings
    return state


class TestLoadToDbMain:
    def test_full_run_executes_steps_in_order_and_returns_zero(self, main_env, capsys):
        assert load_to_db.main([]) == 0
        steps = [e[0] if e[0] != "sql" else f"sql:{e[1]}" for e in main_env.log]
        # Verification runs inside the transaction so a mismatch can roll back before commit.
        assert steps == ["enter", "sql:schema.sql", "load_all", "sql:views.sql", "verify", "exit"]
        assert ("rollback",) not in main_env.log
        assert main_env.connect_settings is main_env.settings
        out = capsys.readouterr().out
        assert "Connecting to mainuser@mainhost:1/maindb" in out
        assert "Views (2): vw_one, vw_two" in out
        assert "Load complete." in out

    def test_no_views_skips_views_sql_and_listing(self, main_env, capsys):
        assert load_to_db.main(["--no-views"]) == 0
        sql_steps = [e[1] for e in main_env.log if e[0] == "sql"]
        assert sql_steps == ["schema.sql"]
        out = capsys.readouterr().out
        assert "Views (" not in out
        assert "views.sql" not in out
        assert "Load complete." in out

    def test_mismatch_returns_one(self, main_env, capsys):
        main_env.verify_result = False
        assert load_to_db.main([]) == 1
        steps = [e[0] for e in main_env.log]
        assert steps.index("verify") < steps.index("rollback") < steps.index("exit")
        assert "load rolled back, previous data kept" in capsys.readouterr().out

    def test_connection_exits_cleanly_on_success(self, main_env):
        load_to_db.main([])
        assert ("exit", None) in main_env.log

    def test_error_inside_transaction_propagates_through_context_manager(self, main_env, monkeypatch):
        def boom(conn):
            raise RuntimeError("copy failed")

        monkeypatch.setattr(load_to_db, "load_all", boom)
        with pytest.raises(RuntimeError, match="copy failed"):
            load_to_db.main([])
        assert ("exit", RuntimeError) in main_env.log
        assert not any(e[0] == "verify" for e in main_env.log)

    def test_empty_view_list_prints_no_view_line(self, main_env, capsys):
        main_env.views = []
        assert load_to_db.main([]) == 0
        assert "Views (" not in capsys.readouterr().out

    def test_missing_env_exits_before_connecting(self, monkeypatch):
        called = []
        monkeypatch.setattr(load_to_db, "load_settings", lambda: (_ for _ in ()).throw(SystemExit("Missing POSTGRES_HOST")))
        monkeypatch.setattr(load_to_db, "connect", lambda s: called.append(s))
        with pytest.raises(SystemExit, match="POSTGRES_HOST"):
            load_to_db.main([])
        assert called == []

    def test_main_never_prints_password(self, main_env, capsys):
        load_to_db.main([])
        captured = capsys.readouterr()
        assert SECRET not in captured.out + captured.err

    def test_uses_project_sql_files(self, main_env):
        load_to_db.main([])
        assert (db.SQL_DIR / "schema.sql").is_file() and (db.SQL_DIR / "views.sql").is_file()


def test_load_to_db_module_entrypoint_runs_main_and_exits_with_its_code(monkeypatch):
    """``python -m src.load_to_db`` -> sys.exit(main()); exercised with --help so no DB is needed."""
    monkeypatch.setattr(sys, "argv", ["load_to_db", "--help"])
    sys.modules.pop("src.load_to_db", None)
    try:
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("src.load_to_db", run_name="__main__")
    finally:
        sys.modules["src.load_to_db"] = load_to_db  # restore the originally imported module
    assert exc.value.code == 0


def test_run_sql_reports_module_entrypoint_exits_with_main_code(monkeypatch, tmp_path):
    """``python -m src.run_sql_reports`` -> sys.exit(main()); DB connection replaced via psycopg stub."""
    def refuse(**kwargs):
        raise psycopg.OperationalError("no database in unit tests")

    monkeypatch.setattr(psycopg, "connect", refuse)
    for name, value in ENV_VALUES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys.modules["src.config"], "REPORTS_DIR", tmp_path)  # OUT_DIR computed at import
    sys.modules.pop("src.run_sql_reports", None)
    try:
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("src.run_sql_reports", run_name="__main__")
    finally:
        sys.modules["src.run_sql_reports"] = run_sql_reports
    assert "Could not connect" in str(exc.value)
    assert SECRET not in str(exc.value)
    assert not (tmp_path / "sql_results" / "README.md").exists()
