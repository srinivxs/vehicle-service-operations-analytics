"""Unit tests for the Power BI Project generator (powerbi/generate_pbip.py)."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("generate_pbip", ROOT / "powerbi" / "generate_pbip.py")
gp = importlib.util.module_from_spec(_spec)
sys.modules["generate_pbip"] = gp  # dataclasses resolve their module via sys.modules
_spec.loader.exec_module(gp)


@pytest.fixture(scope="module")
def measures():
    return gp.parse_measures(gp.DAX_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pages():
    return gp.build_pages()


def _columns() -> set[tuple[str, str]]:
    return {(t.name, c) for t in gp.TABLES for c in [*t.columns, *(a[0] for a in t.added)]}


def _refs(node, kind: str):
    if isinstance(node, dict):
        if kind in node and isinstance(node[kind], dict) and "Property" in node[kind]:
            yield node[kind]
        for v in node.values():
            yield from _refs(v, kind)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v, kind)


def test_parses_every_measure_with_clean_names(measures):
    assert len(measures) == 65
    names = [m.name for m in measures]
    assert len(set(names)) == len(names)
    assert not any(n.endswith("=") or n != n.strip() for n in names)
    assert "Repeat Customers" in names and "Cost Overrun Rate" in names


def test_multiline_measure_keeps_full_expression(measures):
    repeat = next(m for m in measures if m.name == "Repeat Customers")
    assert repeat.expression.startswith("COUNTROWS")
    assert repeat.expression.count("(") == repeat.expression.count(")")


def test_text_formats_are_dropped_and_hour_suffix_removed(measures):
    by_name = {m.name: m for m in measures}
    assert by_name["Selection Label"].format_string is None
    assert by_name["Avg Turnaround Hours"].format_string == "0.0"
    assert by_name["On-Time %"].format_string == "0.0%"


def test_relationships_reference_existing_columns():
    cols = _columns()
    for many, one, _ in gp.RELATIONSHIPS:
        for ref in (many, one):
            table, col = ref.split(".")
            assert (table, col) in cols, ref


def test_only_the_month_relationship_is_many_to_many():
    m2m = [r for r in gp.RELATIONSHIPS if r[2]]
    assert m2m == [("fact_technician_month.month_start", "DimDate.month_start", True)]


def test_csv_partition_types_every_column_and_converts_blanks():
    table = next(t for t in gp.TABLES if t.name == "fact_service")
    m = gp.csv_partition_m(table)
    assert 'Table.ReplaceValue(Promoted, "", null' in m
    for col in table.columns:
        assert f'{{"{col}", ' in m
    assert '"technician_id", each if _ = null then "UNASSIGNED" else _, type text' in m
    assert m.strip().endswith(f"Added{len(table.added)}")


def test_unassigned_technician_row_is_appended():
    tech = next(t for t in gp.TABLES if t.name == "DimTechnician")
    m = gp.csv_partition_m(tech)
    assert 'Appended = Table.InsertRows(Typed' in m and 'technician_id = "UNASSIGNED"' in m


def test_tmdl_quotes_names_and_marks_date_table(measures):
    dim_date = next(t for t in gp.TABLES if t.name == "DimDate")
    text = gp.table_tmdl(dim_date, measures)
    assert text.startswith("table 'DimDate'")
    assert "\tdataCategory: Time" in text and "\t\tisKey" in text
    assert "\t\tsortByColumn: 'month_start'" in text
    measures_tmdl = gp.table_tmdl(next(t for t in gp.TABLES if t.name == "_Measures"), measures)
    assert measures_tmdl.count("\tmeasure '") == len(measures)


def test_report_has_four_spec_pages(pages):
    assert [p.display for p in pages] == ["Executive Overview", "Operations", "Financial Analysis",
                                          "Customer Experience"]


def test_every_visual_field_resolves_to_the_model(pages, measures):
    names = {m.name for m in measures}
    cols = _columns()
    for page in pages:
        for visual in page.visuals:
            for ref in _refs(visual, "Measure"):
                assert ref["Property"] in names, (page.name, ref["Property"])
            for ref in _refs(visual, "Column"):
                assert (ref["Expression"]["SourceRef"]["Entity"], ref["Property"]) in cols


def test_visuals_fit_on_their_page_with_unique_names(pages):
    for page in pages:
        names = [v["name"] for v in page.visuals]
        assert len(set(names)) == len(names)
        for v in page.visuals:
            pos = v["position"]
            assert pos["x"] + pos["width"] <= 1280 and pos["y"] + pos["height"] <= page.height, v["name"]


def test_every_page_has_the_five_synced_slicers(pages):
    for page in pages:
        groups = {v["visual"]["syncGroup"]["groupName"] for v in page.visuals if v["visual"]["visualType"] == "slicer"}
        assert groups == {"sync_date", "sync_region", "sync_center_name", "sync_service_type", "sync_model"}


def test_single_series_colour_is_unscoped():
    assert gp.series_colours({"Profit": "#000000"}) == [{"properties": {"fill": gp.solid("#000000")}}]
    multi = gp.series_colours({"A": "#111111", "B": "#222222"})
    assert [c["selector"]["metadata"] for c in multi] == ["_Measures.A", "_Measures.B"]


def test_text_literal_escapes_quotes():
    assert gp.text_lit("O'Brien")["expr"]["Literal"]["Value"] == "'O''Brien'"
    assert gp.q("it's") == "'it''s'"


def test_main_writes_complete_project(tmp_path, monkeypatch):
    monkeypatch.setattr(gp, "POWERBI_DIR", tmp_path)
    monkeypatch.setattr(gp, "MODEL_DIR", tmp_path / f"{gp.NAME}.SemanticModel")
    monkeypatch.setattr(gp, "REPORT_DIR", tmp_path / f"{gp.NAME}.Report")
    gp.main()
    pbip = json.loads((tmp_path / f"{gp.NAME}.pbip").read_text(encoding="utf-8"))
    assert pbip["artifacts"] == [{"report": {"path": f"{gp.NAME}.Report"}}]
    tables = sorted(p.stem for p in (tmp_path / f"{gp.NAME}.SemanticModel" / "definition" / "tables").glob("*.tmdl"))
    assert tables == sorted(t.name for t in gp.TABLES)
    rel = (tmp_path / f"{gp.NAME}.SemanticModel" / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    assert len(re.findall(r"^relationship ", rel, re.M)) == len(gp.RELATIONSHIPS)
    report = tmp_path / f"{gp.NAME}.Report"
    assert (report / "StaticResources" / "RegisteredResources" / gp.THEME_FILE.name).is_file()
    assert len(list((report / "definition" / "pages").glob("*/visuals/*/visual.json"))) == 104
    gp.main()  # regenerating over an existing project is idempotent
    assert len(list((report / "definition" / "pages").glob("*/page.json"))) == 4
