"""Execute every analytical SQL query and save the results.

Usage:  python -m src.run_sql_reports

* ``sql/kpi_queries.sql``  is split on ``-- Qxx: title`` headers; each query -> ``reports/sql_results/Qxx_<slug>.csv``
* ``sql/data_quality.sql`` is split on ``-- SQL-DQxx: title`` headers; the individual checks are combined into
  ``SQL_DQ_all_checks.csv`` and the UNION ALL summary (SQL-DQ99) is saved as ``SQL-DQ99_data_quality_summary.csv``
* ``reports/sql_results/README.md`` lists every query with its row count and first rows.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from src.config import REPORTS_DIR
from src.db import SQL_DIR, connect

OUT_DIR = REPORTS_DIR / "sql_results"
# Horizontal whitespace only after the colon, so an empty title never captures the next line.
HEADER_RE = re.compile(r"^--[ \t]*((?:SQL-DQ|Q)\d+):[ \t]*(\S.*?)[ \t\r]*$", re.MULTILINE)
PREVIEW_ROWS = 5
SUMMARY_ID = "SQL-DQ99"


@dataclass
class Section:
    """One query block of a SQL file."""

    qid: str
    title: str
    sql: str
    question: str = ""
    technique: str = ""


@dataclass
class QueryResult:
    section: Section
    frame: pd.DataFrame | None = None
    error: str | None = None
    csv_name: str = field(default="")


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len].rstrip("_")


def _comment_value(block: str, label: str) -> str:
    match = re.search(rf"^--\s*{label}:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_sections(text: str) -> list[Section]:
    """Split a SQL file into sections on ``-- Qxx:`` / ``-- SQL-DQxx:`` headers (preamble is ignored)."""
    matches = list(HEADER_RE.finditer(text))
    sections: list[Section] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.start():end].strip()
        sections.append(Section(
            qid=m.group(1), title=m.group(2), sql=block,
            question=_comment_value(block, "Business question") or _comment_value(block, "Spec ref"),
            technique=_comment_value(block, "Technique"),
        ))
    return sections


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def run_section(conn: psycopg.Connection, section: Section) -> QueryResult:
    try:
        with conn.cursor() as cur:
            cur.execute(section.sql)
            columns = [d.name for d in cur.description or []]
            rows = [tuple(_plain(v) for v in row) for row in cur.fetchall()]
    except psycopg.Error as exc:
        conn.rollback()
        return QueryResult(section, error=str(exc).strip().splitlines()[0])
    return QueryResult(section, frame=pd.DataFrame(rows, columns=columns))


def save_kpi_results(results: list[QueryResult], out_dir: Path) -> None:
    for r in results:
        if r.frame is not None:
            r.csv_name = f"{r.section.qid}_{slugify(r.section.title)}.csv"
            r.frame.to_csv(out_dir / r.csv_name, index=False)


def save_dq_results(results: list[QueryResult], out_dir: Path) -> list[QueryResult]:
    """Combine the individual DQ checks, save the SQL-DQ99 summary, and return the saved result rows."""
    ok = [r for r in results if r.frame is not None]
    individual = [r for r in ok if r.section.qid != SUMMARY_ID]
    summary = next((r for r in ok if r.section.qid == SUMMARY_ID), None)
    combined = pd.concat([r.frame for r in individual], ignore_index=True) if individual else pd.DataFrame()
    combined.to_csv(out_dir / "SQL_DQ_all_checks.csv", index=False)
    saved: list[QueryResult] = []
    if summary is not None:
        summary.csv_name = f"{SUMMARY_ID}_data_quality_summary.csv"
        summary.frame.to_csv(out_dir / summary.csv_name, index=False)
        saved.append(summary)
        same = not combined.empty and (combined[["check_id", "issue_count"]].reset_index(drop=True)
                                       .equals(summary.frame[["check_id", "issue_count"]].reset_index(drop=True)))
        print(f"  DQ individual checks == SQL-DQ99 summary: {'yes' if same else 'NO (investigate)'}")
    return saved


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value).replace("|", "\\|")


def markdown_table(frame: pd.DataFrame, max_rows: int | None = PREVIEW_ROWS) -> str:
    shown = frame if max_rows is None else frame.head(max_rows)
    lines = ["| " + " | ".join(map(str, shown.columns)) + " |", "|" + "|".join("---" for _ in shown.columns) + "|"]
    lines += ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in shown.itertuples(index=False)]
    return "\n".join(lines)


def build_readme(kpi: list[QueryResult], dq: list[QueryResult]) -> str:
    parts = [
        "# SQL query results",
        "",
        "Generated by `python -m src.run_sql_reports` from `sql/kpi_queries.sql` and `sql/data_quality.sql`.",
        "Synthetic data only (EV two-wheeler service network, INR). Ratios in the views are fractions; "
        "these queries report percentages (`_pct`).",
        "",
        "## Business queries",
        "",
        "| Query | Title | Rows | CSV |",
        "|---|---|---:|---|",
    ]
    for r in kpi:
        rows = "FAILED" if r.frame is None else f"{len(r.frame):,}"
        parts.append(f"| {r.section.qid} | {r.section.title} | {rows} | `{r.csv_name}` |")
    parts.append("")
    for r in kpi:
        parts += [f"### {r.section.qid}: {r.section.title}", ""]
        if r.section.question:
            parts += [f"*{r.section.question}*", ""]
        if r.section.technique:
            parts += [f"Technique: {r.section.technique}", ""]
        if r.frame is None:
            parts += [f"**FAILED:** {r.error}", ""]
            continue
        parts += [f"{len(r.frame):,} rows x {len(r.frame.columns)} columns - first {min(PREVIEW_ROWS, len(r.frame))} rows:", "",
                  markdown_table(r.frame), ""]
    parts += ["## Data-quality checks", ""]
    for r in dq:
        if r.frame is None:
            parts += [f"**{r.section.qid} FAILED:** {r.error}", ""]
        else:
            parts += [f"Full results: `{r.csv_name}` (50 checks, PASS = 0 issues, INFO = documented informational count).", "",
                      markdown_table(r.frame, max_rows=None), ""]
    return "\n".join(parts)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kpi_sections = parse_sections((SQL_DIR / "kpi_queries.sql").read_text(encoding="utf-8"))
    dq_sections = parse_sections((SQL_DIR / "data_quality.sql").read_text(encoding="utf-8"))
    print(f"Running {len(kpi_sections)} business queries and {len(dq_sections)} data-quality queries ...")
    with connect(autocommit=True) as conn:
        kpi = [run_section(conn, s) for s in kpi_sections]
        dq = [run_section(conn, s) for s in dq_sections]
    save_kpi_results(kpi, OUT_DIR)
    for r in kpi:
        status = f"{len(r.frame):>4} rows" if r.frame is not None else f"FAILED: {r.error}"
        print(f"  {r.section.qid}  {r.section.title[:70]:<70} {status}")
    dq_saved = save_dq_results(dq, OUT_DIR)
    failed = [r for r in kpi + dq if r.frame is None]
    for r in dq:
        if r.frame is None:
            print(f"  {r.section.qid} FAILED: {r.error}")
    (OUT_DIR / "README.md").write_text(build_readme(kpi, dq_saved or dq), encoding="utf-8")
    print(f"Saved results and README.md to {OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
