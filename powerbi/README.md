# Power BI report

A 4-page Power BI report (Executive Overview, Operations, Financial Analysis, Customer Experience) that mirrors
the Streamlit dashboard in `app/`: same KPI definitions, same slicers, same palette.

Synthetic data for an EV two-wheeler service network modelled on Ather-style models (Ather 450X, 450 Apex, Rizta);
8 Indian service centres, Jan 2025 - Sep 2026, INR. Not affiliated with Ather Energy.

| File | Purpose |
|---|---|
| `vehicle_service_dashboard.pbix` | **The report, ready to open** in Power BI Desktop (data embedded) |
| `VehicleServiceDashboard.pbip` + `.SemanticModel/` + `.Report/` | The same report as a Power BI Project: text files (TMDL model, PBIR pages) that diff cleanly in Git |
| `generate_pbip.py` | Generates the Power BI Project from `dax_measures.dax` and the layout spec below (`python powerbi/generate_pbip.py`) |
| `dax_measures.md` / `dax_measures.dax` | All 65 measures with display folders and format strings |
| `vehicle_service_theme.json` | Report theme (palette, fonts, visual defaults) matching the Streamlit app |

## Quick start

* **Just view it:** open `vehicle_service_dashboard.pbix` in Power BI Desktop (free).
* **Refresh with new data:** run the pipeline (`python -m src.pipeline`), open the `.pbix` and click **Home > Refresh**.
  If the repository lives somewhere other than `C:\Vehicle_Service_Operations_Analytics`, first change the
  `DataFolder` parameter (Home > Transform data > Edit parameters) to your `data\cleaned\` folder.
* **Change the report as code:** edit `generate_pbip.py` or `dax_measures.dax`, run `python powerbi/generate_pbip.py`,
  open `VehicleServiceDashboard.pbip`, click **Refresh**, then **File > Save As > Power BI file (*.pbix)**.

## Verification

The generated report was opened in Power BI Desktop 2.158 and checked in two ways:

* Every page was rendered and inspected; all 104 visuals load with no errors.
* DAX queries were run against the report's in-memory model and compared with `src/kpis.py`: all 25 full-range KPIs
  and all centre + date-range KPIs in section 8 (Pune - Baner, Jun-Dec 2025) match exactly, and conflicting filters
  (Region = North with Service centre = Pune - Baner) return empty results rather than errors.

The 72 work orders with no recorded technician appear as an explicit **Unassigned** technician and skill level
instead of a blank member. Sections 1-7 below document how the model and pages are built, for anyone rebuilding the
report by hand.

---

## 1. Get Data

### Option A - CSV folder (recommended; matches the Streamlit numbers exactly)

Home > Get data > Text/CSV, or Get data > Folder and pick `data/cleaned/`. Load these files:

| File | Model table name |
|---|---|
| `fact_service.csv` | `fact_service` |
| `fact_appointments.csv` | `fact_appointments` |
| `fact_technician_month.csv` | `fact_technician_month` |
| `part_usage.csv` | `part_usage` |
| `parts.csv` | `parts` |
| `dim_date.csv` | `DimDate` |
| `service_centers.csv` | `DimCentre` |
| `technicians.csv` | `DimTechnician` |
| `vehicles.csv` | used only to build `DimModel` (section 2.4) |

Use a Power BI parameter `DataFolder` (Home > Transform data > Manage parameters, text, default `C:\Vehicle_Service_Operations_Analytics\data\cleaned\`) so the path changes in one place: `Source = Csv.Document(File.Contents(DataFolder & "fact_service.csv"), [Delimiter=",", Encoding=65001])`, then `Table.PromoteHeaders`.

### Option B - PostgreSQL (schema `service_ops`)

Another part of this project loads the cleaned data into PostgreSQL 16 (`docker compose up -d`, `python -m src.load_to_db`; see `sql/README.md`). In Power BI: Get data > PostgreSQL database, Server `localhost:5432`, Database `vehicle_service`, Data Connectivity mode **Import**, credentials = the `POSTGRES_USER` / `POSTGRES_PASSWORD` from your local `.env` (never save them in the file or commit them). Select schema `service_ops`.

* Dimensions and `parts` / `part_usage` load straight from the tables `service_centers`, `technicians`, `parts`, `part_usage`.
* For the facts use the views `vw_work_order_enriched` (instead of `fact_service`) and `vw_appointment_enriched` (instead of `fact_appointments`). Their column names differ slightly (for example `caused_comeback` vs `caused_repeat_visit`, `is_comeback` vs `is_repeat_visit`): rename in Power Query so they match the names the measures expect (`dax_measures.dax`), and add `center_name` / `region` only if you want them on the fact (not required, the dimension supplies them).
* `fact_technician_month` has no database table (the SQL layer aggregates per technician). Load it from the CSV, or rebuild it in a view with the same columns: `technician_id, center_id, skill_level, month, working_days, jobs, service_hours, available_hours, ...`.

---

## 2. Power Query (Transform data)

Apply in this order; steps are `Table.TransformColumnTypes` unless noted.

### 2.1 fact_service
| Column(s) | Type |
|---|---|
| `service_date` | Date |
| `check_in_time, start_time, end_time, promised_ready_time` | Date/Time |
| `estimated_hours, actual_hours, parts_wait_hours, wait_hours, turnaround_hours, late_hours, duration_variance_hours` | Decimal number |
| `estimated_cost, labor_cost, parts_cost, revenue, total_cost, profit, cost_variance, cost_variance_pct` | Decimal number (or Fixed decimal) |
| `rating` | Whole number (blanks stay null; do **not** replace nulls with 0) |
| `on_time_flag, parts_delay_flag, cost_overrun_flag, qc_passed_first_time, is_repeat_visit, caused_repeat_visit, additional_work_found` | True/False |
| `customer_visit_number, odometer_km` | Whole number |
| everything else (ids, names, categories) | Text |

Leave `technician_id` and `skill_level` blank where missing (72 work orders have no technician recorded); do not fill them. Remove nothing: the 24,092 rows are already cleaned.

### 2.2 fact_appointments
`booking_date, scheduled_date` Date; `lead_days` Whole number; `is_cancelled, is_no_show, is_completed` True/False; rest Text. Blank `cancellation_reason` stays null.

### 2.3 fact_technician_month
`working_days, jobs, comebacks_caused` Whole number; `service_hours, qc_first_pass, available_hours, utilisation` Decimal; `month` Text (`2025-01`). Add a custom column for the date relationship:

```m
= Table.AddColumn(#"Changed Type", "month_start", each Date.FromText([month] & "-01"), type date)
```

### 2.4 Dimensions
* **DimDate** (from `dim_date.csv`): `date` Date, `year`/`quarter`/`month_number`/`weekday_number` types as appropriate, `is_working_day` True/False. Add `month_start` (custom column `Date.StartOfMonth([date])`). If you prefer a generated calendar instead, use `List.Dates(#date(2025,1,1), 639, #duration(1,0,0,0))` (2025-01-01 to 2026-09-30) and add the same columns. Mark as date table on `date`.
* **DimCentre** (`service_centers.csv`): types only. Columns used: `center_id, center_name, city, state, region`.
* **DimTechnician** (`technicians.csv`): `technician_id, center_id, skill_level, years_experience, certification`. Sort `skill_level` with a helper column (Junior 1, Mid 2, Senior 3, Master 4).
* **DimServiceType**: reference `fact_service`, keep `service_type`, `Remove Duplicates`, Add a column `service_group` if desired (for example Periodic / Repair / Diagnostics). One row per service type (11).
* **DimModel**: reference `vehicles`, keep `model, vehicle_category`, `Remove Duplicates` on `model` (3 rows: Ather 450X, Ather 450 Apex, Ather Rizta). Disable load for the `vehicles` query itself.
* **parts / part_usage**: `unit_cost` Decimal, `quantity` Whole number.

Disable "Auto date/time" (File > Options > Current file > Data load) so only `DimDate` is used.

---

## 3. Star-schema relationships (Model view)

All relationships are **single direction** (dimension filters fact), cross-filter direction `Single`, never bi-directional.

| From (one side) | To (many side) | Join columns | Cardinality |
|---|---|---|---|
| `DimDate` | `fact_service` | `DimDate[date]` -> `fact_service[service_date]` | 1:* |
| `DimDate` | `fact_appointments` | `DimDate[date]` -> `fact_appointments[scheduled_date]` | 1:* |
| `DimDate` | `fact_technician_month` | `DimDate[month_start]` -> `fact_technician_month[month_start]` | *:* (many-to-many, single direction DimDate -> fact; a date range selects every month it overlaps, as the Streamlit app does) |
| `DimCentre` | `fact_service` | `center_id` | 1:* |
| `DimCentre` | `fact_appointments` | `center_id` | 1:* |
| `DimCentre` | `fact_technician_month` | `center_id` | 1:* |
| `DimTechnician` | `fact_service` | `technician_id` | 1:* |
| `DimTechnician` | `fact_technician_month` | `technician_id` | 1:* |
| `DimServiceType` | `fact_service` | `service_type` | 1:* |
| `DimServiceType` | `fact_appointments` | `service_type` -> `requested_service_type` | 1:* |
| `DimModel` | `fact_service` | `model` | 1:* |
| `DimModel` | `fact_appointments` | `model` | 1:* |
| `fact_service` | `part_usage` | `work_order_id` | 1:* (single, fact_service filters part_usage) |
| `parts` | `part_usage` | `part_id` | 1:* |

Do **not** relate `DimCentre` to `DimTechnician` (it would create two filter paths to `fact_service`). Slicers on `DimCentre[region]` and `DimCentre[center_name]` therefore filter every fact. Hide the foreign-key columns on the fact tables and the `_Measures` helper column. Mark `DimDate` as date table.

Known limitation (documented, not a bug): `fact_technician_month` has no service-type or model, so those two slicers do not change `Technician Utilisation %`. The measure's tooltip should say so.

---

## 4. Theme, measures and fonts

1. View > Themes > Browse for themes > `vehicle_service_theme.json`. Palette (colour-blind validated, fixed entity order): green `#00A67E`, blue `#2A78D6`, orange `#EB6834`, violet `#4A3AA7`, magenta `#E87BA4`, yellow `#EDA100`, neutral `#A9B4B0`.
2. Create the `_Measures` table and paste the measures from `dax_measures.dax`; set display folders and format strings per `dax_measures.md`.
3. Canvas: 16:9, 1280 x 720 per page, background `#F4F7F6` (from theme), visuals white cards. Font Segoe UI.

Colour conventions: revenue = green, cost = blue, profit = violet, parts = blue, labour = orange, estimated = grey, actual = green; bars use green when better than the network and orange when worse (`Colour - ...` measures, Conditional formatting > Format style > Field value). Single-axis charts only (no dual axis).

---

## 5. Pages - layout specification

Coordinates are `x, y, width, height` in pixels on the 1280 x 720 canvas. Every page repeats the same left filter column (section 6) and a footer text box with `Footer Disclaimer`.

Common elements on every page:
* Title text box `(24, 12, 700, 36)`: page name, Segoe UI Semibold 20.
* Subtitle card `(24, 48, 1000, 22)`: measure `Selection Label` (dynamic text, 11 pt grey).
* Key insight card `(24, 74, 1232, 30)`: the page's `Key Insight - ...` measure, green left border.
* Footer text box `(24, 700, 1232, 16)`: `Footer Disclaimer`, 9 pt grey.
* Slicers (synced) in the column `x = 24..200` (sizes in section 6).

### Page 1 - Executive Overview
| Visual | Type | Fields | Position |
|---|---|---|---|
| Revenue | Card (new card) | `INR Short Revenue` | 216, 112, 200, 74 |
| Total cost | Card | `INR Short Cost` | 424, 112, 200, 74 |
| Profit | Card | `INR Short Profit` | 632, 112, 200, 74 |
| Profit margin | Card | `Profit Margin %` | 840, 112, 200, 74 |
| Completed services | Card | `Completed Services` | 1048, 112, 208, 74 |
| On-time % | Card | `On-Time %` | 216, 194, 250, 74 |
| Avg turnaround | Card | `Avg Turnaround Hours` | 474, 194, 250, 74 |
| Avg rating | Card | `Avg Rating` | 732, 194, 250, 74 |
| Cancellation rate | Card | `Cancellation Rate` | 990, 194, 266, 74 |
| Monthly revenue & profit | Line chart | X `DimDate[Month Label]` (sorted by `month_start`); Y `Total Revenue`, `Profit`; title `Title - Revenue and Profit Trend` | 216, 276, 520, 200 |
| Margin & on-time trend | Line chart | X `DimDate[Month Label]`; Y `Profit Margin %`, `On-Time %`; axis 0-100% | 744, 276, 512, 200 |
| Centre ranking bar | Clustered bar | Y `DimCentre[center_name]`; X `Centre Performance Index`; sort descending; colour by `Colour - On-Time vs Network` rule (field value) | 216, 484, 400, 208 |
| Centre ranking table | Table | `Centre Rank`, `center_name`, `region`, `Completed Services`, `Total Revenue`, `Profit Margin %`, `On-Time %`, `Avg Turnaround Hours`, `Avg Rating`, `Cancellation Rate`; conditional formatting: background colour rules (green best third / amber worst third) on margin, on-time, rating; reverse for turnaround and cancellation; sort by `Centre Rank` ascending | 624, 484, 632, 208 |

### Page 2 - Operations
Canvas: custom 1280 x 1200 (Format page > Canvas settings > Type: Custom). Footer at y = 1180.

| Visual | Type | Fields | Position |
|---|---|---|---|
| KPI strip | 8 cards (125 px each) | `Avg Turnaround Hours`, `Median Turnaround Hours`, `Avg Wait Hours`, `On-Time %`, `Technician Utilisation %`, `Parts Delay Rate`, `Avg Duration Variance Hours`, `QC First-Pass %` | 216, 112, 1040, 70 |
| Turnaround by centre | Clustered bar | Y `center_name`; X `Avg Turnaround Hours`, `Median Turnaround Hours`; title `Title - Turnaround by Centre` | 216, 190, 400, 230 |
| Technician workload | Clustered bar | Y `DimTechnician[technician_id]`; X `Technician Utilisation %`; colour `Colour - Skill Level`; tooltip `Service Hours`, `Available Hours`, `Completed Services` | 624, 190, 632, 230 |
| Technician x month utilisation | Matrix | Rows `technician_id`; Columns `DimDate[Month Label]`; Values `Technician Utilisation %`; background gradient `#E6F6F1` to `#00573F` | 216, 428, 1040, 260 |
| Estimated vs actual duration | Clustered bar | Y `DimServiceType[service_type]`; X `Avg Estimated Hours` (grey), `Avg Actual Hours` (green) | 216, 696, 400, 260 |
| Delay distribution | Clustered column | X `fact_service[Delay Band]` (sort by `Delay Band Sort`); Y `Completed Services` | 624, 696, 310, 125 |
| Turnaround bands | Clustered column | X `Turnaround Band` (sort by `Turnaround Band Sort`); Y `Completed Services` | 942, 696, 314, 125 |
| Wait by weekday | Clustered column | X `DimDate[weekday_name]` (sort by `Weekday Sort`); Y `Avg Wait Hours` | 624, 829, 632, 127 |
| Service-type performance | Table | `service_type`, `Completed Services`, `Avg Turnaround Hours`, `On-Time %`, `Avg Estimated Hours`, `Avg Actual Hours`, `Avg Duration Variance Hours`, `Parts Delay Rate`, `Avg Rating`, `Total Revenue`; conditional formatting as on page 1 | 216, 964, 1040, 200 |

### Page 3 - Financial Analysis
Canvas: custom 1280 x 1100. Footer at y = 1080.

| Visual | Type | Fields | Position |
|---|---|---|---|
| KPI strip | 8 cards | `INR Short Revenue`, `INR Short Cost`, `INR Short Profit`, `Profit Margin %`, `Avg Service Cost`, `Cost Variance`, `Cost Overrun Rate`, `Parts Share of Cost %` | 216, 112, 1040, 70 |
| Revenue vs cost | Line chart | X `Month Label`; Y `Total Revenue`, `Total Cost` | 216, 190, 520, 200 |
| Monthly profit | Clustered column | X `Month Label`; Y `Profit`; colour `Colour - Profit Sign` | 744, 190, 512, 200 |
| Monthly financial trend | Line chart | X `Month Label`; Y `Profit Margin %`, `Cost Overrun Rate`; axis 0-100% | 216, 398, 520, 160 |
| Monthly cost variance | Clustered column | X `Month Label`; Y `Cost Variance` (orange) | 744, 398, 512, 160 |
| Profit by centre | Clustered bar | Y `center_name`; X `Profit`; colour `Colour - Profit Sign`; title `Title - Profit by Centre` | 216, 566, 300, 260 |
| Profit by service type | Clustered bar | Y `service_type`; X `Profit`; colour `Colour - Profit Sign` | 524, 566, 300, 260 |
| Cost variance by service type | Clustered bar | Y `service_type`; X `Cost Variance`; tooltip `Cost Overrun Rate` | 832, 566, 424, 260 |
| Cost variance by skill level | Clustered bar | Y `DimTechnician[skill_level]`; X `Cost Variance`; tooltip `Cost Overrun Rate` | 216, 834, 250, 230 |
| Parts vs labour | Stacked bar | Y `center_name`; X `Parts Cost`, `Labour Cost` | 474, 834, 300, 230 |
| Revenue by billing type | Clustered bar | Y `fact_service[billing_type]`; X `Total Revenue` | 782, 834, 230, 230 |
| Parts cost by part category | Clustered bar | Y `parts[part_category]`; X `Parts Cost (Catalogue)` | 1020, 834, 236, 230 |

### Page 4 - Customer Experience
Canvas: custom 1280 x 1260. Footer at y = 1240.

| Visual | Type | Fields | Position |
|---|---|---|---|
| KPI strip | 6 cards | `Avg Rating`, `CSAT %`, `Cancellation Rate`, `No-Show Rate`, `Repeat Visit Rate`, `Comeback Rate` | 216, 112, 1040, 70 |
| Rating trend | Line chart | X `Month Label`; Y `Avg Rating`; axis auto between 3 and 5; title `Title - Rating Trend` | 216, 190, 520, 190 |
| CSAT trend | Line chart | X `Month Label`; Y `CSAT %` | 744, 190, 512, 190 |
| Rating heatmap | Matrix | Rows `service_type`; Columns `center_name`; Values `Avg Rating`; gradient `#E6F6F1` -> `#00573F` | 216, 388, 520, 304 |
| Cancellation by centre | Clustered bar | Y `center_name`; X `Cancellation Rate` | 744, 388, 250, 150 |
| Cancellation by lead time | Clustered column | X `fact_appointments[lead_time_band]` (sort: Same day, 1-3, 4-7, 8-14, 15+ days via helper column); Y `Cancellation Rate` | 1002, 388, 254, 150 |
| Cancellation reasons | Clustered bar | Y `fact_appointments[cancellation_reason]`; X `Cancelled Appointments` | 744, 546, 250, 146 |
| Repeat visits | Clustered bar | Y `center_name`; X `Repeat Visit Rate` (a second identical visual with X `Comeback Rate` and one by `DimTechnician[skill_level]` sit beside it, separate visuals avoid the scale mismatch between ~86% and ~4.5%) | 1002, 546, 254, 146 |
| Comeback by centre / skill | Clustered bar x2 | Y `center_name` and Y `skill_level`; X `Comeback Rate` | 216, 700, 510, 250 and 734, 700, 522, 250 |
| Feedback categories | Clustered bar | Y `fact_service[feedback_category]`; X `Rated Services` (Positive Experience green, rest blue via conditional colour) | 216, 958, 1040, 250 |

---

## 6. Slicers and sync (filters apply on every page)

Create five slicers on page 1 in the left column, then sync them to all pages.

| Slicer | Field | Style | Position (page 1) |
|---|---|---|---|
| Date range | `DimDate[date]` | Between (date slider) | 24, 112, 176, 70 |
| Region | `DimCentre[region]` | Dropdown, multi-select | 24, 190, 176, 52 |
| Service centre | `DimCentre[center_name]` | Dropdown, multi-select | 24, 250, 176, 52 |
| Service type | `DimServiceType[service_type]` | Dropdown, multi-select | 24, 310, 176, 52 |
| Model | `DimModel[model]` | Dropdown, multi-select | 24, 370, 176, 52 |

Sync: View > **Sync slicers**. Select each slicer in turn and tick both **Sync** (eye / sync column) and **Visible** for all four pages, with the same group name (for example `slicer_date`). Then copy-paste the slicers onto pages 2-4 (they are the same synced group, so any change updates all pages), or leave them only on page 1 and keep Sync ticked on the others (hidden but active) if you want a cleaner layout. Add a **Clear all slicers** bookmark button (Insert > Buttons > Clear all slicers) beside them.

Page settings: do not use "Edit interactions" to disconnect any visual from the slicers, and disable cross-highlight between charts only if you want KPIs to stay on the slicer selection alone.

---

## 7. Dynamic titles and conditional formatting
* Dynamic titles: select a visual > Format > General > Title > fx > Field value > pick the `Title - ...` measure.
* Conditional colours: Format > Visuals > Bars/Columns > Colors > fx > Format style `Field value`, based on the `Colour - ...` measure.
* Card tooltips: set Format > General > Tooltips text to the definition from `dax_measures.md` KPI map.
* Accessibility: set alt text on each visual and check the tab order; colour is never the only encoding (value labels are on).

---

## 8. Acceptance test checklist

Run these after building (mirrors the project acceptance criterion: selecting a service centre and date range must update all relevant KPIs and visualisations to show only the selected records).

**A. Page and slicer structure**
- [ ] Four pages named Executive Overview, Operations, Financial Analysis, Customer Experience.
- [ ] Date, Region, Service centre, Service type and Model slicers exist and are synced across all four pages (change on page 1, confirm page 3 reflects it without touching it).
- [ ] Clear-all-slicers button restores the full data set on every page.

**B. Full-range reconciliation (no slicers; values from the Streamlit app / `src/kpis.py`)**

| KPI | Expected |
|---|---|
| Completed services | 24,092 |
| Total revenue | 78,238,663 (7.8 Cr) |
| Total cost | 59,112,552 (5.9 Cr) |
| Profit | 19,126,111 (1.9 Cr); margin 24.4% |
| Avg service cost | 2,454 |
| On-Time % | 73.2% |
| Avg / median turnaround | 11.2 h / 2.6 h |
| Cost variance / overrun rate | 10,956,492 / 36.7% |
| Avg rating / CSAT % | 4.02 / 74.5% |
| Appointments / cancellation rate / no-show rate | 26,769 / 6.8% / 3.2% |
| Technician utilisation | 75.6% |
| Repeat visit rate | 85.7% |
| Comeback rate | 4.5% |
| Avg duration variance / parts delay / QC first-pass / avg wait | 0.31 h / 4.7% / 93.2% / 1.2 h |

**C. Centre + date-range test** - select Service centre = `Pune - Baner` and Date range 1 Jun 2025 - 31 Dec 2025:

| KPI | Expected |
|---|---|
| Completed services | 657 |
| Total revenue / cost / profit | 1,902,225 / 1,476,619 / 425,607 (margin 22.4%) |
| On-Time % | 87.4% |
| Avg turnaround | 9.7 h |
| Cost variance / overrun rate | 173,164 / 23.6% |
| Avg rating | 4.24 |
| Appointments / cancellation rate | 727 / 6.7% |
| Technician utilisation | 49.9% |
| Repeat visit rate | 44.1% |

- [ ] Every card, chart, matrix and table on all four pages changes and shows only Pune - Baner (for example the centre ranking shows a single centre; technician charts show only its 2 technicians).
- [ ] Dynamic titles and the `Selection Label` subtitle show "Pune - Baner" and the chosen dates.
- [ ] Key insight text updates (it falls back to blank when only one centre is selected, by design).
- [ ] Selecting Region = North together with Service centre = Pune - Baner yields empty visuals, not errors.

**D. Behavioural checks**
- [ ] Rating averages ignore blank ratings (about half of work orders are unrated); CSAT % uses only rated work orders.
- [ ] `Total Cost` = labour + parts everywhere; profit by centre sums to total profit.
- [ ] Parts cost by part category (`Parts Cost (Catalogue)`, from part lines) totals 43,145,980 on the full range, versus the billed `Parts Cost` KPI of 43,269,120. The 123,140 gap is expected: cleaning rule DQ17 removed 115 invalid part lines whose cost stays in the billed financials (reported as DQ19 in `reports/cleaning_log.csv`).
- [ ] Month axis sorts chronologically (Jan 25 ... Sep 26), weekday axis Monday to Saturday.
- [ ] Footer disclaimer visible on every page; no personal data fields are used.

---

## 9. Troubleshooting
* Measures show a flat total across a dimension: a relationship is missing or inactive; compare with section 3.
* `Technician Utilisation %` blank: `month_start` types must be Date on both sides of the many-to-many relationship.
* Repeat Visit Rate looks too high: this is the specified definition (customers with at least two work orders over those with at least one) over the whole 21-month window; narrow the date range and it falls.
* Slicer sync not applied: ensure each slicer's sync group is identical and that Sync is ticked for every page.
