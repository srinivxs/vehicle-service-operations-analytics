"""Generate the Power BI Project (PBIP) for the vehicle service dashboard.

Writes a semantic model in TMDL (tables loaded from data/cleaned via Power Query, star-schema
relationships, every measure from powerbi/dax_measures.dax) and a 4-page report in the
enhanced report format (PBIR). Open ``powerbi/VehicleServiceDashboard.pbip`` in Power BI
Desktop, click Refresh, then File > Save As to produce a .pbix.

Usage:
    python powerbi/generate_pbip.py
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

POWERBI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = POWERBI_DIR.parent
DATA_FOLDER = str(PROJECT_ROOT / "data" / "cleaned") + "\\"
NAME = "VehicleServiceDashboard"
MODEL_DIR = POWERBI_DIR / f"{NAME}.SemanticModel"
REPORT_DIR = POWERBI_DIR / f"{NAME}.Report"
DAX_FILE = POWERBI_DIR / "dax_measures.dax"
THEME_FILE = POWERBI_DIR / "vehicle_service_theme.json"
NS = uuid.UUID("6f1c2a52-6a0e-4a8e-9a43-3d7f1f3b9a10")

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VERSIONS = {"report": "3.1.0", "page": "2.0.0", "visual": "2.5.0"}

GREEN, BLUE, ORANGE, VIOLET, GREY, INK = "#00A67E", "#2A78D6", "#EB6834", "#4A3AA7", "#A9B4B0", "#1F2A27"
PAGE_BG = "#F4F7F6"


def tag(*parts: str) -> str:
    """Deterministic lineage tag so regenerating produces identical files."""
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL object name."""
    return "'" + name.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Semantic model
# --------------------------------------------------------------------------- #
M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number",
           "dateTime": "type datetime", "date": "type date", "boolean": "type logical"}


@dataclass
class Table:
    name: str
    source: str | None  # CSV file name, or None for a custom M expression
    columns: dict[str, str]  # column -> type key in M_TYPES (CSV columns, typed on load)
    added: list[tuple[str, str, str]] = field(default_factory=list)  # (column, M expression, type)
    custom_m: str | None = None
    fill_null: dict[str, str] = field(default_factory=dict)  # column -> replacement for nulls
    extra_rows: list[dict[str, object]] = field(default_factory=list)  # rows appended after typing
    sort_by: dict[str, str] = field(default_factory=dict)
    hidden: set[str] = field(default_factory=set)
    is_date_table: bool = False
    hide_table: bool = False


def _cols(spec: str, kind: str) -> dict[str, str]:
    return {c.strip(): kind for c in spec.split(",") if c.strip()}


TABLES: list[Table] = [
    Table("fact_service", "fact_service.csv", {
        **_cols("work_order_id,appointment_id,technician_id,service_type,vehicle_id,center_id,booking_channel,"
                "customer_id,model,variant,vehicle_category,customer_type,center_name,city,region,skill_level,"
                "billing_type,feedback_category,month", "string"),
        **_cols("check_in_time,start_time,end_time,promised_ready_time", "dateTime"),
        **_cols("service_date", "date"),
        **_cols("estimated_hours,actual_hours,parts_wait_hours,estimated_cost,labor_cost,parts_cost,revenue,"
                "wait_hours,turnaround_hours,late_hours,duration_variance_hours,total_cost,profit,cost_variance,"
                "cost_variance_pct,vehicle_age_years,days_since_same_service", "double"),
        **_cols("odometer_km,rating,year,customer_visit_number", "int64"),
        **_cols("additional_work_found,qc_passed_first_time,on_time_flag,parts_delay_flag,cost_overrun_flag,"
                "is_repeat_visit,caused_repeat_visit", "boolean"),
    }, fill_null={"technician_id": "UNASSIGNED", "skill_level": "Unassigned"}, added=[
        ("Delay Band", 'if [late_hours] = null then null else if [late_hours] <= 0 then "On time" '
                       'else if [late_hours] <= 1 then "0-1h" else if [late_hours] <= 2 then "1-2h" '
                       'else if [late_hours] <= 4 then "2-4h" else if [late_hours] <= 8 then "4-8h" '
                       'else if [late_hours] <= 24 then "8-24h" else "> 24h"', "string"),
        ("Delay Band Sort", 'List.PositionOf({"On time","0-1h","1-2h","2-4h","4-8h","8-24h","> 24h"}, [Delay Band]) + 1',
         "int64"),
        ("Turnaround Band", 'if [turnaround_hours] = null then null else if [turnaround_hours] <= 2 then "<= 2h" '
                            'else if [turnaround_hours] <= 4 then "2-4h" else if [turnaround_hours] <= 8 then "4-8h" '
                            'else if [turnaround_hours] <= 24 then "8-24h" else if [turnaround_hours] <= 72 '
                            'then "24-72h" else "> 72h"', "string"),
        ("Turnaround Band Sort", 'List.PositionOf({"<= 2h","2-4h","4-8h","8-24h","24-72h","> 72h"}, [Turnaround Band]) + 1',
         "int64"),
    ], sort_by={"Delay Band": "Delay Band Sort", "Turnaround Band": "Turnaround Band Sort"},
        hidden={"Delay Band Sort", "Turnaround Band Sort"}),
    Table("fact_appointments", "fact_appointments.csv", {
        **_cols("appointment_id,vehicle_id,center_id,scheduled_slot,booking_channel,requested_service_type,status,"
                "cancellation_reason,customer_id,model,vehicle_category,customer_type,center_name,region,"
                "lead_time_band,weekday,month", "string"),
        **_cols("booking_date,scheduled_date", "date"),
        **_cols("lead_days", "int64"),
        **_cols("is_cancelled,is_no_show,is_completed", "boolean"),
    }, added=[("Lead Band Sort", 'List.PositionOf({"Same day","1-3 days","4-7 days","8-14 days","15+ days"}, '
                                 '[lead_time_band]) + 1', "int64")],
        sort_by={"lead_time_band": "Lead Band Sort"}, hidden={"Lead Band Sort"}),
    Table("fact_technician_month", "fact_technician_month.csv", {
        **_cols("technician_id,center_id,skill_level,month", "string"),
        **_cols("working_days,jobs", "int64"),
        **_cols("service_hours,qc_first_pass,comebacks_caused,available_hours,utilisation", "double"),
    }, added=[("month_start", 'Date.FromText([month] & "-01", [Format="yyyy-MM-dd", Culture="en-US"])', "date")]),
    Table("DimDate", "dim_date.csv", {
        **_cols("date", "date"),
        **_cols("year,month_number,weekday_number", "int64"),
        **_cols("quarter,month_name,year_month,weekday_name", "string"),
        **_cols("is_working_day", "boolean"),
    }, added=[("month_start", "Date.StartOfMonth([date])", "date"),
              ("Month Label", 'Date.ToText([date], [Format="MMM yy", Culture="en-US"])', "string")],
        sort_by={"Month Label": "month_start", "weekday_name": "weekday_number", "month_name": "month_number"},
        is_date_table=True),
    Table("DimCentre", "service_centers.csv", {
        **_cols("center_id,center_name,city,state,region", "string"),
        **_cols("service_bays,daily_job_capacity", "int64"),
        **_cols("opened_date", "date"),
    }),
    Table("DimTechnician", "technicians.csv", {
        **_cols("technician_id,center_id,skill_level,certification", "string"),
        **_cols("years_experience,shift_hours_per_day", "int64"),
        **_cols("hourly_cost", "double"),
    }, extra_rows=[{"technician_id": "UNASSIGNED", "center_id": None, "skill_level": "Unassigned",
                    "certification": "Not recorded", "years_experience": None, "shift_hours_per_day": None,
                    "hourly_cost": None}],
        added=[("Skill Sort", 'List.PositionOf({"Junior","Mid","Senior","Master","Unassigned"}, [skill_level]) + 1',
                "int64")],
        sort_by={"skill_level": "Skill Sort"}, hidden={"Skill Sort"}),
    Table("DimServiceType", None, {"service_type": "string"}, custom_m=(
        "let\n"
        "    Source = Csv.Document(File.Contents(DataFolder & \"fact_appointments.csv\"), "
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        "    Selected = Table.SelectColumns(Promoted, {\"requested_service_type\"}),\n"
        "    Renamed = Table.RenameColumns(Selected, {{\"requested_service_type\", \"service_type\"}}),\n"
        "    Distinct = Table.Distinct(Renamed),\n"
        "    Typed = Table.TransformColumnTypes(Distinct, {{\"service_type\", type text}})\n"
        "in\n"
        "    Typed")),
    Table("DimModel", None, {"model": "string", "vehicle_category": "string"}, custom_m=(
        "let\n"
        "    Source = Csv.Document(File.Contents(DataFolder & \"vehicles.csv\"), "
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        "    Selected = Table.SelectColumns(Promoted, {\"model\", \"vehicle_category\"}),\n"
        "    Distinct = Table.Distinct(Selected, {\"model\"}),\n"
        "    Typed = Table.TransformColumnTypes(Distinct, {{\"model\", type text}, {\"vehicle_category\", type text}})\n"
        "in\n"
        "    Typed")),
    Table("parts", "parts.csv", {
        **_cols("part_id,part_name,part_category,compatible_models", "string"),
        **_cols("unit_cost", "double"),
        **_cols("supplier_lead_days", "int64"),
    }),
    Table("part_usage", "part_usage.csv", {
        **_cols("usage_id,work_order_id,part_id", "string"),
        **_cols("quantity", "int64"),
    }),
    Table("_Measures", None, {"Measure Holder": "string"}, custom_m=(
        "let\n    Source = #table(type table [#\"Measure Holder\" = text], {})\nin\n    Source"),
        hidden={"Measure Holder"}),
]

# (many-side table.column, one-side table.column, many-to-many?)
RELATIONSHIPS = [
    ("fact_service.service_date", "DimDate.date", False),
    ("fact_appointments.scheduled_date", "DimDate.date", False),
    ("fact_technician_month.month_start", "DimDate.month_start", True),
    ("fact_service.center_id", "DimCentre.center_id", False),
    ("fact_appointments.center_id", "DimCentre.center_id", False),
    ("fact_technician_month.center_id", "DimCentre.center_id", False),
    ("fact_service.technician_id", "DimTechnician.technician_id", False),
    ("fact_technician_month.technician_id", "DimTechnician.technician_id", False),
    ("fact_service.service_type", "DimServiceType.service_type", False),
    ("fact_appointments.requested_service_type", "DimServiceType.service_type", False),
    ("fact_service.model", "DimModel.model", False),
    ("fact_appointments.model", "DimModel.model", False),
    ("part_usage.work_order_id", "fact_service.work_order_id", False),
    ("part_usage.part_id", "parts.part_id", False),
]


def csv_partition_m(t: Table) -> str:
    types = ", ".join(f'{{"{c}", {M_TYPES[k]}}}' for c, k in t.columns.items())
    lines = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{t.source}"), '
        '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        "    Blanks = Table.ReplaceValue(Promoted, \"\", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),",
        f'    Typed = Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")',
    ]
    last = "Typed"
    if t.fill_null:
        pairs = ", ".join(f'{{"{c}", each if _ = null then "{v}" else _, type text}}' for c, v in t.fill_null.items())
        lines[-1] += ","
        lines.append(f"    Filled = Table.TransformColumns({last}, {{{pairs}}})")
        last = "Filled"
    if t.extra_rows:
        recs = ", ".join("[" + ", ".join(f'{k} = {json.dumps(v) if v is not None else "null"}' for k, v in r.items()) + "]"
                         for r in t.extra_rows)
        lines[-1] += ","
        lines.append(f"    Appended = Table.InsertRows({last}, Table.RowCount({last}), {{{recs}}})")
        last = "Appended"
    for i, (col, expr, kind) in enumerate(t.added, start=1):
        lines[-1] += ","
        lines.append(f'    Added{i} = Table.AddColumn({last}, "{col}", each {expr}, {M_TYPES[kind]})')
        last = f"Added{i}"
    lines += ["in", f"    {last}"]
    return "\n".join(lines)


def column_tmdl(t: Table, col: str, kind: str) -> list[str]:
    data_type = "dateTime" if kind == "date" else kind
    out = [f"\tcolumn {q(col)}", f"\t\tdataType: {data_type}"]
    if kind == "date":
        out.append("\t\tformatString: yyyy-mm-dd")
    elif kind == "dateTime":
        out.append("\t\tformatString: yyyy-mm-dd hh:nn")
    elif kind == "double":
        out.append("\t\tformatString: #,0.00")
    elif kind == "int64":
        out.append("\t\tformatString: 0")
    if t.is_date_table and col == "date":
        out.append("\t\tisKey")
    if col in t.hidden or t.hide_table:
        out.append("\t\tisHidden")
    out += [f"\t\tlineageTag: {tag(t.name, col)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {col}"]
    if col in t.sort_by:
        out.append(f"\t\tsortByColumn: {q(t.sort_by[col])}")
    out += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
    return out


@dataclass
class Measure:
    name: str
    expression: str
    folder: str
    format_string: str | None


def parse_measures(text: str) -> list[Measure]:
    """Read measures from dax_measures.dax: a '// Folder: X | Format: Y' line precedes each one."""
    measures: list[Measure] = []
    lines = text.splitlines()
    i = 0
    header = re.compile(r"^// Folder: (.+?) \| Format: (.+)$")
    while i < len(lines):
        m = header.match(lines[i].strip())
        if not m:
            i += 1
            continue
        folder, fmt = m.group(1).strip(), m.group(2).strip()
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("//"):
            body.append(lines[i].rstrip())
            i += 1
        # "Name = expr" on one line, or "Name =" with the expression on the following lines.
        name, first = re.match(r"^(.*?)\s*=(?:\s+(.*))?$", body[0]).groups()
        expr_lines = ([first] if first and first.strip() else []) + body[1:]
        fmt = None if fmt == "text" else re.sub(r'\s*"h"$', "", fmt)
        measures.append(Measure(name.strip(), "\n".join(expr_lines), folder, fmt))
    return measures


def measure_tmdl(m: Measure) -> list[str]:
    expr_lines = m.expression.splitlines()
    if len(expr_lines) == 1:
        out = [f"\tmeasure {q(m.name)} = {expr_lines[0].strip()}"]
    else:
        out = [f"\tmeasure {q(m.name)} ="] + [f"\t\t\t{line}" for line in expr_lines]
    if m.format_string:
        out.append(f"\t\tformatString: {m.format_string}")
    out += [f"\t\tdisplayFolder: {m.folder}", f"\t\tlineageTag: {tag('measure', m.name)}", ""]
    return out


def table_tmdl(t: Table, measures: list[Measure]) -> str:
    out = [f"table {q(t.name)}", f"\tlineageTag: {tag(t.name)}"]
    if t.is_date_table:
        out.append("\tdataCategory: Time")
    out.append("")
    if t.name == "_Measures":
        for m in measures:
            out += measure_tmdl(m)
    all_cols = {**t.columns, **{c: k for c, _, k in t.added}}
    for col, kind in all_cols.items():
        out += column_tmdl(t, col, kind)
    m_code = t.custom_m or csv_partition_m(t)
    out += [f"\tpartition {q(t.name)} = m", "\t\tmode: import", "\t\tsource ="]
    out += [f"\t\t\t\t{line}" for line in m_code.splitlines()]
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def relationships_tmdl() -> str:
    out = []
    for many, one, m2m in RELATIONSHIPS:
        out.append(f"relationship {tag('rel', many, one)}")
        if m2m:
            out.append("\ttoCardinality: many")
        out += [f"\tfromColumn: {many}", f"\ttoColumn: {one}", ""]
    return "\n".join(out)


def write_model(measures: list[Measure]) -> None:
    d = MODEL_DIR / "definition"
    (d / "tables").mkdir(parents=True)
    (MODEL_DIR / "definition.pbism").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {}}, indent=2), encoding="utf-8")
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n", encoding="utf-8")
    order = json.dumps(["DataFolder"] + [t.name for t in TABLES])
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "\tdataAccessOptions",
             "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
             f"annotation PBI_QueryOrder = {order}", "", "annotation __PBI_TimeIntelligenceEnabled = 0", ""]
    model += [f"ref table {q(t.name)}" for t in TABLES] + [""]
    (d / "model.tmdl").write_text("\n".join(model), encoding="utf-8")
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", '
        'IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag('DataFolder')}\n\n\tannotation PBI_ResultType = Text\n", encoding="utf-8")
    (d / "relationships.tmdl").write_text(relationships_tmdl(), encoding="utf-8")
    for t in TABLES:
        (d / "tables" / f"{t.name}.tmdl").write_text(table_tmdl(t, measures), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Report (PBIR)
# --------------------------------------------------------------------------- #
def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text_lit(s: str) -> dict:
    return lit("'" + s.replace("'", "''") + "'")


def measure_ref(name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def column_ref(table: str, col: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}}


def proj_m(name: str, display: str | None = None) -> dict:
    p = {"field": measure_ref(name), "queryRef": f"_Measures.{name}", "nativeQueryRef": name}
    if display:
        p["displayName"] = display
    return p


def proj_c(table: str, col: str, display: str | None = None) -> dict:
    p = {"field": column_ref(table, col), "queryRef": f"{table}.{col}", "nativeQueryRef": col}
    if display:
        p["displayName"] = display
    return p


def solid(color: str) -> dict:
    return {"solid": {"color": text_lit(color)}}


def title_objects(title: str | None, size: int = 11) -> dict:
    if not title:
        return {"title": [{"properties": {"show": lit("false")}}]}
    return {"title": [{"properties": {"show": lit("true"), "text": text_lit(title), "fontSize": lit(f"{size}D"),
                                      "fontColor": solid(INK)}}]}


def series_colours(colours: dict[str, str]) -> list[dict]:
    if len(colours) == 1:  # Power BI ignores a per-series selector when the chart has a single series
        return [{"properties": {"fill": solid(next(iter(colours.values())))}}]
    return [{"properties": {"fill": solid(c)}, "selector": {"metadata": f"_Measures.{m}"}} for m, c in colours.items()]


def measure_fill(measure: str) -> list[dict]:
    return [{"properties": {"fill": {"solid": {"color": {"expr": measure_ref(measure)}}}},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]


class Page:
    def __init__(self, key: str, display: str, height: int = 720):
        self.name = key
        self.display = display
        self.height = height
        self.visuals: list[dict] = []

    def add(self, x: int, y: int, w: int, h: int, visual: dict) -> None:
        n = len(self.visuals)
        self.visuals.append({
            "$schema": f"{SCHEMA}/item/report/definition/visualContainer/{VERSIONS['visual']}/schema.json",
            "name": f"{self.name}_v{n:02d}",
            "position": {"x": x, "y": y, "z": n * 1000, "width": w, "height": h, "tabOrder": n * 1000},
            "visual": visual,
        })

    # ---- visual builders -------------------------------------------------
    def textbox(self, x, y, w, h, text: str, size: int = 20, bold: bool = True, color: str = INK) -> None:
        style = {"fontSize": f"{size}pt", "color": color}
        if bold:
            style["fontWeight"] = "bold"
        self.add(x, y, w, h, {"visualType": "textbox", "objects": {
            "general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": style}]}]}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": lit("false")}}]}})

    def card(self, x, y, w, h, measure: str, label: str, size: int = 20, show_label: bool = True) -> None:
        self.add(x, y, w, h, {
            "visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj_m(measure, label)]}}},
            "objects": {"labels": [{"properties": {"fontSize": lit(f"{size}D"), "color": solid(INK)}}],
                        "categoryLabels": [{"properties": {"show": lit(str(show_label).lower()), "fontSize": lit("9D")}}]},
            "visualContainerObjects": title_objects(None),
            "drillFilterOtherVisuals": True})

    def insight(self, x, y, w, h, measure: str) -> None:
        self.add(x, y, w, h, {
            "visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj_m(measure, "Key insight")]}}},
            "objects": {"labels": [{"properties": {"fontSize": lit("11D"), "color": solid(INK)}}],
                        "categoryLabels": [{"properties": {"show": lit("true"), "fontSize": lit("8D"),
                                                           "color": solid(GREEN)}}],
                        "wordWrap": [{"properties": {"show": lit("true")}}]},
            "visualContainerObjects": {**title_objects(None),
                                       "border": [{"properties": {"show": lit("true"), "color": solid(GREEN)}}]}})

    def slicer(self, x, y, w, h, table: str, col: str, label: str, mode: str = "Dropdown") -> None:
        self.add(x, y, w, h, {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj_c(table, col, label)]}}},
            "objects": {"data": [{"properties": {"mode": text_lit(mode)}}],
                        "header": [{"properties": {"show": lit("true"), "text": text_lit(label)}}]},
            "syncGroup": {"groupName": f"sync_{col}", "fieldChanges": True, "filterChanges": True},
            "visualContainerObjects": title_objects(None),
            "drillFilterOtherVisuals": True})

    def chart(self, x, y, w, h, vtype: str, title: str, category: dict, values: list[dict], *,
              colours: dict[str, str] | None = None, fill_measure: str | None = None,
              sort: tuple[dict, str] | None = None, labels: bool = False) -> None:
        objects: dict = {}
        if colours:
            objects["dataPoint"] = series_colours(colours)
        if fill_measure:
            objects["dataPoint"] = measure_fill(fill_measure)
        if labels:
            objects["labels"] = [{"properties": {"show": lit("true")}}]
        query: dict = {"queryState": {"Category": {"projections": [category]}, "Y": {"projections": values}}}
        if sort:
            query["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}
        self.add(x, y, w, h, {"visualType": vtype, "query": query, "objects": objects,
                              "visualContainerObjects": title_objects(title), "drillFilterOtherVisuals": True})

    def table(self, x, y, w, h, title: str, fields: list[dict], sort: tuple[dict, str] | None = None) -> None:
        query: dict = {"queryState": {"Values": {"projections": fields}}}
        if sort:
            query["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": False}
        self.add(x, y, w, h, {"visualType": "tableEx", "query": query,
                              "visualContainerObjects": title_objects(title), "drillFilterOtherVisuals": True})

    def matrix(self, x, y, w, h, title: str, rows: dict, cols: dict, value: str, display: str) -> None:
        gradient = {"FillRule": {
            "Input": measure_ref(value),
            "FillRule": {"linearGradient2": {"min": {"color": {"Literal": {"Value": "'#F1FAF7'"}}},
                                             "max": {"color": {"Literal": {"Value": "'#4DBB98'"}}},
                                             "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}
        self.add(x, y, w, h, {
            "visualType": "pivotTable",
            "query": {"queryState": {"Rows": {"projections": [rows]}, "Columns": {"projections": [cols]},
                                     "Values": {"projections": [proj_m(value, display)]}}},
            "objects": {"values": [{"properties": {"backColor": {"solid": {"color": {"expr": gradient}}}},
                                    "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                                 "metadata": f"_Measures.{value}"}}]},
            "visualContainerObjects": title_objects(title), "drillFilterOtherVisuals": True})

    def json(self) -> dict:
        return {
            "$schema": f"{SCHEMA}/item/report/definition/page/{VERSIONS['page']}/schema.json",
            "name": self.name, "displayName": self.display,
            "displayOption": "FitToPage" if self.height == 720 else "FitToWidth",
            "height": self.height, "width": 1280,
            "objects": {"background": [{"properties": {"color": solid(PAGE_BG), "transparency": lit("0D")}}],
                        "outspace": [{"properties": {"color": solid(PAGE_BG)}}]},
        }


MONTH = proj_c("DimDate", "Month Label", "Month")
MONTH_SORT = (column_ref("DimDate", "Month Label"), "Ascending")
CENTRE = proj_c("DimCentre", "center_name", "Service centre")
STYPE = proj_c("DimServiceType", "service_type", "Service type")


def frame(page: Page, title: str, insight_measure: str) -> None:
    """Title, dynamic selection label, key insight, synced slicers and footer shared by every page."""
    page.textbox(216, 8, 700, 40, title)
    page.card(860, 12, 396, 34, "Selection Label", "Current selection", size=9, show_label=False)
    page.insight(216, 52, 1040, 52, insight_measure)
    page.textbox(24, 14, 180, 30, "Filters", size=14)
    page.slicer(24, 52, 176, 90, "DimDate", "date", "Date range", mode="Between")
    page.slicer(24, 150, 176, 60, "DimCentre", "region", "Region")
    page.slicer(24, 218, 176, 60, "DimCentre", "center_name", "Service centre")
    page.slicer(24, 286, 176, 60, "DimServiceType", "service_type", "Service type")
    page.slicer(24, 354, 176, 60, "DimModel", "model", "Model")
    page.textbox(24, page.height - 30, 1232, 28,
                 "Synthetic data for demonstration. Modelled on an EV two-wheeler service network; "
                 "not affiliated with Ather Energy. Amounts in INR.", size=8, bold=False, color="#52605B")


def kpi_strip(page: Page, y: int, items: list[tuple[str, str]]) -> None:
    gap, x0, total = 8, 216, 1040
    w = (total - gap * (len(items) - 1)) // len(items)
    for i, (measure, label) in enumerate(items):
        page.card(x0 + i * (w + gap), y, w, 72, measure, label)


def build_pages() -> list[Page]:
    p1 = Page("executive_overview", "Executive Overview")
    frame(p1, "Executive Overview", "Key Insight - Executive")
    kpi_strip(p1, 112, [("INR Short Revenue", "Total revenue"), ("INR Short Cost", "Total cost"),
                        ("INR Short Profit", "Profit"), ("Profit Margin %", "Profit margin"),
                        ("Completed Services", "Completed services")])
    kpi_strip(p1, 190, [("On-Time %", "On-time %"), ("Avg Turnaround Hours", "Avg turnaround (h)"),
                        ("Avg Rating", "Avg rating (1-5)"), ("Cancellation Rate", "Cancellation rate")])
    p1.chart(216, 270, 516, 210, "lineChart", "Monthly revenue and profit (INR)", MONTH,
             [proj_m("Total Revenue", "Revenue"), proj_m("Profit")],
             colours={"Total Revenue": GREEN, "Profit": VIOLET}, sort=MONTH_SORT)
    p1.chart(740, 270, 516, 210, "lineChart", "Profit margin and on-time % by month", MONTH,
             [proj_m("Profit Margin %", "Profit margin"), proj_m("On-Time %")],
             colours={"Profit Margin %": VIOLET, "On-Time %": GREEN}, sort=MONTH_SORT)
    p1.chart(216, 488, 380, 206, "clusteredBarChart", "Centre performance index (0-100)", CENTRE,
             [proj_m("Centre Performance Index", "Performance index")],
             fill_measure="Colour - On-Time vs Network", sort=(measure_ref("Centre Performance Index"), "Descending"),
             labels=True)
    p1.table(604, 488, 652, 206, "Service-centre ranking", [
        proj_m("Centre Rank", "Rank"), CENTRE,
        proj_m("Completed Services", "Services"), proj_m("Total Revenue", "Revenue"),
        proj_m("Profit Margin %", "Margin"), proj_m("On-Time %", "On-time"),
        proj_m("Avg Turnaround Hours", "Turnaround h"), proj_m("Avg Rating", "Rating"),
        proj_m("Cancellation Rate", "Cancel rate")], sort=(measure_ref("Centre Rank"), "Ascending"))

    p2 = Page("operations", "Operations", height=1200)
    frame(p2, "Operations", "Key Insight - Operations")
    kpi_strip(p2, 112, [("Avg Turnaround Hours", "Avg turnaround (h)"), ("Median Turnaround Hours", "Median turnaround (h)"),
                        ("Avg Wait Hours", "Avg wait (h)"), ("On-Time %", "On-time %"),
                        ("Technician Utilisation %", "Utilisation"), ("Parts Delay Rate", "Parts delay rate"),
                        ("Avg Duration Variance Hours", "Duration var. (h)"), ("QC First-Pass %", "QC first-pass")])
    p2.chart(216, 192, 400, 240, "clusteredBarChart", "Turnaround time by centre (hours): mean vs median", CENTRE,
             [proj_m("Avg Turnaround Hours", "Mean"), proj_m("Median Turnaround Hours", "Median")],
             colours={"Avg Turnaround Hours": GREEN, "Median Turnaround Hours": GREY},
             sort=(measure_ref("Avg Turnaround Hours"), "Descending"))
    p2.chart(624, 192, 632, 240, "clusteredBarChart", "Technician workload: utilisation (service h / available h)",
             proj_c("DimTechnician", "technician_id", "Technician"), [proj_m("Technician Utilisation %", "Utilisation")],
             fill_measure="Colour - Skill Level", sort=(measure_ref("Technician Utilisation %"), "Descending"),
             labels=True)
    p2.matrix(216, 440, 1040, 280, "Technician utilisation by month",
              proj_c("DimTechnician", "technician_id", "Technician"), MONTH, "Technician Utilisation %", "Utilisation")
    p2.chart(216, 728, 400, 260, "clusteredBarChart", "Estimated vs actual labour hours by service type", STYPE,
             [proj_m("Avg Estimated Hours", "Estimated"), proj_m("Avg Actual Hours", "Actual")],
             colours={"Avg Estimated Hours": GREY, "Avg Actual Hours": GREEN},
             sort=(measure_ref("Avg Actual Hours"), "Descending"))
    p2.chart(624, 728, 310, 126, "clusteredColumnChart", "Delay distribution: hours past promised time",
             proj_c("fact_service", "Delay Band", "Delay"), [proj_m("Completed Services", "Services")],
             colours={"Completed Services": GREEN}, sort=(column_ref("fact_service", "Delay Band"), "Ascending"))
    p2.chart(942, 728, 314, 126, "clusteredColumnChart", "Turnaround time bands",
             proj_c("fact_service", "Turnaround Band", "Turnaround"), [proj_m("Completed Services", "Services")],
             colours={"Completed Services": BLUE}, sort=(column_ref("fact_service", "Turnaround Band"), "Ascending"))
    p2.chart(624, 862, 632, 126, "clusteredColumnChart", "Average wait before work starts by weekday (hours)",
             proj_c("DimDate", "weekday_name", "Weekday"), [proj_m("Avg Wait Hours", "Avg wait")],
             colours={"Avg Wait Hours": GREEN}, sort=(column_ref("DimDate", "weekday_name"), "Ascending"))
    p2.table(216, 996, 1040, 180, "Service-type performance", [
        STYPE, proj_m("Completed Services", "Services"), proj_m("Avg Turnaround Hours", "Turnaround h"),
        proj_m("On-Time %", "On-time"), proj_m("Avg Estimated Hours", "Est. h"), proj_m("Avg Actual Hours", "Actual h"),
        proj_m("Avg Duration Variance Hours", "Variance h"), proj_m("Parts Delay Rate", "Parts delay"),
        proj_m("Avg Rating", "Rating"), proj_m("Total Revenue", "Revenue")],
        sort=(measure_ref("Completed Services"), "Descending"))

    p3 = Page("financial_analysis", "Financial Analysis", height=1100)
    frame(p3, "Financial Analysis", "Key Insight - Financial")
    kpi_strip(p3, 112, [("INR Short Revenue", "Total revenue"), ("INR Short Cost", "Total cost"),
                        ("INR Short Profit", "Profit"), ("Profit Margin %", "Profit margin"),
                        ("Avg Service Cost", "Avg service cost"), ("Cost Variance", "Cost variance"),
                        ("Cost Overrun Rate", "Cost overrun rate"), ("Parts Share of Cost %", "Parts share of cost")])
    p3.chart(216, 192, 516, 210, "lineChart", "Revenue vs cost by month (INR)", MONTH,
             [proj_m("Total Revenue", "Revenue"), proj_m("Total Cost", "Total cost")],
             colours={"Total Revenue": GREEN, "Total Cost": BLUE}, sort=MONTH_SORT)
    p3.chart(740, 192, 516, 210, "clusteredColumnChart", "Monthly profit (INR)", MONTH, [proj_m("Profit")],
             fill_measure="Colour - Profit Sign", sort=MONTH_SORT)
    p3.chart(216, 410, 516, 170, "lineChart", "Profit margin and cost-overrun rate by month", MONTH,
             [proj_m("Profit Margin %", "Profit margin"), proj_m("Cost Overrun Rate", "Cost overrun rate")],
             colours={"Profit Margin %": VIOLET, "Cost Overrun Rate": ORANGE}, sort=MONTH_SORT)
    p3.chart(740, 410, 516, 170, "clusteredColumnChart", "Monthly cost variance: actual minus estimate (INR)", MONTH,
             [proj_m("Cost Variance")], colours={"Cost Variance": ORANGE}, sort=MONTH_SORT)
    p3.chart(216, 588, 330, 250, "clusteredBarChart", "Profit by service centre (INR)", CENTRE, [proj_m("Profit")],
             fill_measure="Colour - Profit Sign", sort=(measure_ref("Profit"), "Descending"), labels=True)
    p3.chart(554, 588, 330, 250, "clusteredBarChart", "Profit by service type (INR)", STYPE, [proj_m("Profit")],
             fill_measure="Colour - Profit Sign", sort=(measure_ref("Profit"), "Descending"), labels=True)
    p3.chart(892, 588, 364, 250, "clusteredBarChart", "Cost variance by service type (INR)", STYPE,
             [proj_m("Cost Variance")], colours={"Cost Variance": ORANGE},
             sort=(measure_ref("Cost Variance"), "Descending"))
    p3.chart(216, 846, 250, 228, "clusteredBarChart", "Cost variance by skill level (INR)",
             proj_c("DimTechnician", "skill_level", "Skill level"), [proj_m("Cost Variance")],
             colours={"Cost Variance": ORANGE}, sort=(column_ref("DimTechnician", "skill_level"), "Ascending"))
    p3.chart(474, 846, 300, 228, "barChart", "Parts vs labour cost by centre (INR)", CENTRE,
             [proj_m("Parts Cost", "Parts"), proj_m("Labour Cost", "Labour")],
             colours={"Parts Cost": BLUE, "Labour Cost": ORANGE}, sort=(measure_ref("Parts Cost"), "Descending"))
    p3.chart(782, 846, 230, 228, "clusteredBarChart", "Revenue by billing type (INR)",
             proj_c("fact_service", "billing_type", "Billing type"), [proj_m("Total Revenue", "Revenue")],
             colours={"Total Revenue": GREEN}, sort=(measure_ref("Total Revenue"), "Descending"))
    p3.chart(1020, 846, 236, 228, "clusteredBarChart", "Parts cost by part category (INR)",
             proj_c("parts", "part_category", "Part category"), [proj_m("Parts Cost (Catalogue)", "Parts cost")],
             colours={"Parts Cost (Catalogue)": GREEN}, sort=(measure_ref("Parts Cost (Catalogue)"), "Descending"))

    p4 = Page("customer_experience", "Customer Experience", height=1260)
    frame(p4, "Customer Experience", "Key Insight - Customer")
    kpi_strip(p4, 112, [("Avg Rating", "Avg rating (1-5)"), ("CSAT %", "CSAT % (rating 4-5)"),
                        ("Cancellation Rate", "Cancellation rate"), ("No-Show Rate", "No-show rate"),
                        ("Repeat Visit Rate", "Repeat visit rate"), ("Comeback Rate", "Comeback rate")])
    p4.chart(216, 192, 516, 200, "lineChart", "Average rating by month (1-5)", MONTH, [proj_m("Avg Rating", "Avg rating")],
             colours={"Avg Rating": GREEN}, sort=MONTH_SORT)
    p4.chart(740, 192, 516, 200, "lineChart", "CSAT % by month", MONTH, [proj_m("CSAT %")],
             colours={"CSAT %": BLUE}, sort=MONTH_SORT)
    p4.matrix(216, 400, 1040, 236, "Average rating by service type and centre", STYPE, CENTRE, "Avg Rating", "Rating")
    p4.chart(216, 644, 330, 176, "clusteredBarChart", "Cancellation rate by centre", CENTRE,
             [proj_m("Cancellation Rate")], colours={"Cancellation Rate": ORANGE},
             sort=(measure_ref("Cancellation Rate"), "Descending"), labels=True)
    p4.chart(554, 644, 330, 176, "clusteredColumnChart", "Cancellation rate by booking lead time",
             proj_c("fact_appointments", "lead_time_band", "Lead time"), [proj_m("Cancellation Rate")],
             colours={"Cancellation Rate": BLUE}, sort=(column_ref("fact_appointments", "lead_time_band"), "Ascending"),
             labels=True)
    p4.chart(892, 644, 364, 176, "clusteredBarChart", "Cancellation reasons (appointments)",
             proj_c("fact_appointments", "cancellation_reason", "Reason"),
             [proj_m("Cancelled Appointments", "Cancelled")], colours={"Cancelled Appointments": ORANGE},
             sort=(measure_ref("Cancelled Appointments"), "Descending"), labels=True)
    p4.chart(216, 828, 330, 210, "clusteredBarChart", "Repeat visit rate by centre", CENTRE,
             [proj_m("Repeat Visit Rate")], colours={"Repeat Visit Rate": GREEN},
             sort=(measure_ref("Repeat Visit Rate"), "Descending"), labels=True)
    p4.chart(554, 828, 330, 210, "clusteredBarChart", "Comeback (30-day rework) rate by centre", CENTRE,
             [proj_m("Comeback Rate")], colours={"Comeback Rate": ORANGE},
             sort=(measure_ref("Comeback Rate"), "Descending"), labels=True)
    p4.chart(892, 828, 364, 210, "clusteredBarChart", "Comeback rate by technician skill level",
             proj_c("DimTechnician", "skill_level", "Skill level"), [proj_m("Comeback Rate")],
             fill_measure="Colour - Skill Level", sort=(column_ref("DimTechnician", "skill_level"), "Ascending"),
             labels=True)
    p4.chart(216, 1046, 1040, 180, "clusteredBarChart", "Feedback categories (rated work orders)",
             proj_c("fact_service", "feedback_category", "Feedback category"), [proj_m("Rated Services", "Rated services")],
             colours={"Rated Services": GREEN}, sort=(measure_ref("Rated Services"), "Descending"), labels=True)
    return [p1, p2, p3, p4]


def write_report(pages: list[Page]) -> None:
    d = REPORT_DIR / "definition"
    (d / "pages").mkdir(parents=True)
    (REPORT_DIR / "definition.pbir").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2),
        encoding="utf-8")
    (d / "version.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"},
        indent=2), encoding="utf-8")
    theme_name = THEME_FILE.name
    res_dir = REPORT_DIR / "StaticResources" / "RegisteredResources"
    res_dir.mkdir(parents=True)
    shutil.copyfile(THEME_FILE, res_dir / theme_name)
    report = {
        "$schema": f"{SCHEMA}/item/report/definition/report/{VERSIONS['report']}/schema.json",
        "themeCollection": {"customTheme": {
            "name": theme_name, "type": "RegisteredResources",
            "reportVersionAtImport": {"visual": VERSIONS["visual"], "page": VERSIONS["page"],
                                      "report": VERSIONS["report"]}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": theme_name, "path": theme_name, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True},
    }
    (d / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}, indent=2), encoding="utf-8")
    for p in pages:
        pd_ = d / "pages" / p.name
        pd_.mkdir()
        (pd_ / "page.json").write_text(json.dumps(p.json(), indent=2), encoding="utf-8")
        for v in p.visuals:
            vd = pd_ / "visuals" / v["name"]
            vd.mkdir(parents=True)
            (vd / "visual.json").write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    for path in (MODEL_DIR, REPORT_DIR):
        if path.exists():
            shutil.rmtree(path)
    measures = parse_measures(DAX_FILE.read_text(encoding="utf-8"))
    write_model(measures)
    pages = build_pages()
    write_report(pages)
    (POWERBI_DIR / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2), encoding="utf-8")
    print(f"Semantic model: {len(TABLES)} tables, {len(RELATIONSHIPS)} relationships, {len(measures)} measures")
    print(f"Report: {len(pages)} pages, {sum(len(p.visuals) for p in pages)} visuals")
    print(f"Open: {POWERBI_DIR / (NAME + '.pbip')}")


if __name__ == "__main__":
    main()
