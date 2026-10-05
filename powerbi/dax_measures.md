# DAX measures

All measures reproduce the canonical KPI definitions in `src/kpis.py` (the Streamlit app) so the two dashboards reconcile. The plain-text version for copy/paste is [`dax_measures.dax`](dax_measures.dax); calculated columns are listed at the top of that file.

**Setup:** create an empty table `_Measures` (Home > Enter data), paste the measures into it and set each measure's *Display folder* and *Format* from the tables below. Mark `DimDate` as the date table (Table tools > Mark as date table > `date`). Rates are fractions (0-1) formatted as percentages.

Synthetic data - not affiliated with Ather Energy.

## KPI to measure map

| # | KPI | Definition | Measure |
|---|---|---|---|
| 1 | Total Revenue | SUM(revenue) | `Total Revenue` |
| 2 | Total Cost | SUM(labor_cost + parts_cost) | `Total Cost` |
| 3 | Profit / Margin % | Revenue - Cost; Profit / Revenue | `Profit`, `Profit Margin %` |
| 4 | Avg Service Cost | Total Cost / work orders | `Avg Service Cost` |
| 5 | On-Time % | mean(on_time_flag) | `On-Time %` |
| 6 | Avg Turnaround | mean(turnaround_hours) (+ median) | `Avg Turnaround Hours`, `Median Turnaround Hours` |
| 7 | Cost Variance | SUM(cost_variance); overrun rate = mean(cost_overrun_flag) | `Cost Variance`, `Cost Overrun Rate` |
| 8 | Cancellation Rate | Cancelled / all appointments (no-show separate) | `Cancellation Rate`, `No-Show Rate` |
| 9 | Technician Utilisation | SUM(service_hours) / SUM(available_hours) | `Technician Utilisation %` |
| 10 | Customer Satisfaction | mean(rating); CSAT % = share rating >= 4 | `Avg Rating`, `CSAT %` |
| 11 | Repeat Visit Rate | customers with >= 2 work orders / customers with >= 1 (in filter) | `Repeat Visit Rate` |
| 12 | Comeback Rate | mean(caused_repeat_visit) | `Comeback Rate` |
| 13 | Duration variance | mean(duration_variance_hours) | `Avg Duration Variance Hours` |
| 14 | Parts delay rate | mean(parts_delay_flag) | `Parts Delay Rate` |
| 15 | QC first-pass | mean(qc_passed_first_time) | `QC First-Pass %` |
| 16 | Avg wait | mean(wait_hours) | `Avg Wait Hours` |

## Measure catalogue

| Display folder | Measure | Format string | KPI # |
|---|---|---|---|
| 1 Financial | `Total Revenue` | `#,0` | 1 |
| 1 Financial | `Labour Cost` | `#,0` |  |
| 1 Financial | `Parts Cost` | `#,0` |  |
| 1 Financial | `Total Cost` | `#,0` | 2 |
| 1 Financial | `Profit` | `#,0` | 3 |
| 1 Financial | `Profit Margin %` | `0.0%` | 3 |
| 1 Financial | `Avg Service Cost` | `#,0` | 4 |
| 1 Financial | `Parts Share of Cost %` | `0.0%` |  |
| 1 Financial | `Total Estimated Cost` | `#,0` |  |
| 1 Financial | `Cost Variance` | `#,0` | 7 |
| 1 Financial | `Cost Variance %` | `0.0%` |  |
| 1 Financial | `Cost Overrun Rate` | `0.0%` | 7 |
| 1 Financial | `Parts Cost (Catalogue)` | `#,0` |  |
| 2 Operations | `Completed Services` | `#,0` |  |
| 2 Operations | `On-Time %` | `0.0%` | 5 |
| 2 Operations | `Avg Turnaround Hours` | `0.0 "h"` | 6 |
| 2 Operations | `Median Turnaround Hours` | `0.0 "h"` | 6 |
| 2 Operations | `Avg Wait Hours` | `0.0 "h"` | 16 |
| 2 Operations | `Avg Estimated Hours` | `0.00 "h"` |  |
| 2 Operations | `Avg Actual Hours` | `0.00 "h"` |  |
| 2 Operations | `Avg Duration Variance Hours` | `0.00 "h"` | 13 |
| 2 Operations | `Parts Delay Rate` | `0.0%` | 14 |
| 2 Operations | `QC First-Pass %` | `0.0%` | 15 |
| 2 Operations | `Comeback Rate` | `0.0%` | 12 |
| 2 Operations | `Service Hours` | `#,0` |  |
| 2 Operations | `Available Hours` | `#,0` |  |
| 2 Operations | `Technician Utilisation %` | `0.0%` | 9 |
| 3 Customer | `Avg Rating` | `0.00` | 10 |
| 3 Customer | `Rated Services` | `#,0` |  |
| 3 Customer | `CSAT %` | `0.0%` | 10 |
| 3 Customer | `Appointments` | `#,0` |  |
| 3 Customer | `Cancelled Appointments` | `#,0` |  |
| 3 Customer | `No-Show Appointments` | `#,0` |  |
| 3 Customer | `Cancellation Rate` | `0.0%` | 8 |
| 3 Customer | `No-Show Rate` | `0.0%` | 8 |
| 3 Customer | `Customers` | `#,0` |  |
| 3 Customer | `Repeat Customers` | `#,0` |  |
| 3 Customer | `Repeat Visit Rate` | `0.0%` | 11 |
| 4 Time Intelligence | `Revenue PM` | `#,0` |  |
| 4 Time Intelligence | `Revenue MoM %` | `+0.0%;-0.0%;0.0%` |  |
| 4 Time Intelligence | `Profit PM` | `#,0` |  |
| 4 Time Intelligence | `Profit MoM %` | `+0.0%;-0.0%;0.0%` |  |
| 4 Time Intelligence | `Revenue PY` | `#,0` |  |
| 4 Time Intelligence | `Revenue YoY %` | `+0.0%;-0.0%;0.0%` |  |
| 4 Time Intelligence | `Profit PY` | `#,0` |  |
| 4 Time Intelligence | `Profit YoY %` | `+0.0%;-0.0%;0.0%` |  |
| 4 Time Intelligence | `Revenue YTD` | `#,0` |  |
| 5 Display | `INR Short Revenue` | `text` |  |
| 5 Display | `INR Short Cost` | `text` |  |
| 5 Display | `INR Short Profit` | `text` |  |
| 6 Ranking | `Centre Performance Index` | `0` |  |
| 6 Ranking | `Centre Rank` | `0` |  |
| 6 Ranking | `Key Insight - Executive` | `text` |  |
| 6 Ranking | `Key Insight - Operations` | `text` |  |
| 6 Ranking | `Key Insight - Financial` | `text` |  |
| 6 Ranking | `Key Insight - Customer` | `text` |  |
| 7 Titles | `Selection Label` | `text` |  |
| 7 Titles | `Title - Revenue and Profit Trend` | `text` |  |
| 7 Titles | `Title - Turnaround by Centre` | `text` |  |
| 7 Titles | `Title - Profit by Centre` | `text` |  |
| 7 Titles | `Title - Rating Trend` | `text` |  |
| 7 Titles | `Footer Disclaimer` | `text` |  |
| 7 Titles | `Colour - On-Time vs Network` | `text` |  |
| 7 Titles | `Colour - Profit Sign` | `text` |  |
| 7 Titles | `Colour - Skill Level` | `text` |  |

## Definitions

### 1 Financial

**Total Revenue** - format `#,0`

```dax
Total Revenue = SUM ( fact_service[revenue] )
```

**Labour Cost** - format `#,0`

```dax
Labour Cost = SUM ( fact_service[labor_cost] )
```

**Parts Cost** - format `#,0`

```dax
Parts Cost = SUM ( fact_service[parts_cost] )
```

**Total Cost** - format `#,0`

```dax
Total Cost = [Labour Cost] + [Parts Cost]
```

**Profit** - format `#,0`

```dax
Profit = [Total Revenue] - [Total Cost]
```

**Profit Margin %** - format `0.0%`

```dax
Profit Margin % = DIVIDE ( [Profit], [Total Revenue] )
```

**Avg Service Cost** - format `#,0`

```dax
Avg Service Cost = DIVIDE ( [Total Cost], [Completed Services] )
```

**Parts Share of Cost %** - format `0.0%`

```dax
Parts Share of Cost % = DIVIDE ( [Parts Cost], [Total Cost] )
```

**Total Estimated Cost** - format `#,0`

```dax
Total Estimated Cost = SUM ( fact_service[estimated_cost] )
```

**Cost Variance** - format `#,0`

```dax
Cost Variance = SUM ( fact_service[cost_variance] )
```

**Cost Variance %** - format `0.0%`

```dax
Cost Variance % = DIVIDE ( [Cost Variance], [Total Estimated Cost] )
```

**Cost Overrun Rate** - format `0.0%`

```dax
Cost Overrun Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[cost_overrun_flag] = TRUE () ),
    [Completed Services]
)
```

**Parts Cost (Catalogue)** - format `#,0`

```dax
Parts Cost (Catalogue) = SUMX ( part_usage, part_usage[quantity] * RELATED ( parts[unit_cost] ) )
```

### 2 Operations

**Completed Services** - format `#,0`

```dax
Completed Services = COUNTROWS ( fact_service )
```

**On-Time %** - format `0.0%`

```dax
On-Time % =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[on_time_flag] = TRUE () ),
    [Completed Services]
)
```

**Avg Turnaround Hours** - format `0.0 "h"`

```dax
Avg Turnaround Hours = AVERAGE ( fact_service[turnaround_hours] )
```

**Median Turnaround Hours** - format `0.0 "h"`

```dax
Median Turnaround Hours = MEDIAN ( fact_service[turnaround_hours] )
```

**Avg Wait Hours** - format `0.0 "h"`

```dax
Avg Wait Hours = AVERAGE ( fact_service[wait_hours] )
```

**Avg Estimated Hours** - format `0.00 "h"`

```dax
Avg Estimated Hours = AVERAGE ( fact_service[estimated_hours] )
```

**Avg Actual Hours** - format `0.00 "h"`

```dax
Avg Actual Hours = AVERAGE ( fact_service[actual_hours] )
```

**Avg Duration Variance Hours** - format `0.00 "h"`

```dax
Avg Duration Variance Hours = AVERAGE ( fact_service[duration_variance_hours] )
```

**Parts Delay Rate** - format `0.0%`

```dax
Parts Delay Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[parts_delay_flag] = TRUE () ),
    [Completed Services]
)
```

**QC First-Pass %** - format `0.0%`

```dax
QC First-Pass % =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[qc_passed_first_time] = TRUE () ),
    [Completed Services]
)
```

**Comeback Rate** - format `0.0%`

```dax
Comeback Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[caused_repeat_visit] = TRUE () ),
    [Completed Services]
)
```

**Service Hours** - format `#,0`

```dax
Service Hours = SUM ( fact_technician_month[service_hours] )
```

**Available Hours** - format `#,0`

```dax
Available Hours = SUM ( fact_technician_month[available_hours] )
```

**Technician Utilisation %** - format `0.0%`

```dax
Technician Utilisation % = DIVIDE ( [Service Hours], [Available Hours] )
// Note: filtered by DimDate (month overlap), DimCentre and DimTechnician only. DimServiceType / DimModel
// do not relate to fact_technician_month, so those slicers do not change this measure (same as the Streamlit app).
```

### 3 Customer

**Avg Rating** - format `0.00`

```dax
Avg Rating = AVERAGE ( fact_service[rating] )
```

**Rated Services** - format `#,0`

```dax
Rated Services = COUNT ( fact_service[rating] )
```

**CSAT %** - format `0.0%`

```dax
CSAT % =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_service ), fact_service[rating] >= 4 ),
    [Rated Services]
)
```

**Appointments** - format `#,0`

```dax
Appointments = COUNTROWS ( fact_appointments )
```

**Cancelled Appointments** - format `#,0`

```dax
Cancelled Appointments =
CALCULATE ( COUNTROWS ( fact_appointments ), fact_appointments[status] = "Cancelled" )
```

**No-Show Appointments** - format `#,0`

```dax
No-Show Appointments =
CALCULATE ( COUNTROWS ( fact_appointments ), fact_appointments[status] = "No-Show" )
```

**Cancellation Rate** - format `0.0%`

```dax
Cancellation Rate = DIVIDE ( [Cancelled Appointments], [Appointments] )
```

**No-Show Rate** - format `0.0%`

```dax
No-Show Rate = DIVIDE ( [No-Show Appointments], [Appointments] )
```

**Customers** - format `#,0`

```dax
Customers = DISTINCTCOUNT ( fact_service[customer_id] )
```

**Repeat Customers** - format `#,0`

```dax
Repeat Customers =
COUNTROWS (
    FILTER (
        ADDCOLUMNS ( VALUES ( fact_service[customer_id] ), "@Orders", CALCULATE ( COUNTROWS ( fact_service ) ) ),
        [@Orders] >= 2
    )
)
```

**Repeat Visit Rate** - format `0.0%`

```dax
Repeat Visit Rate = DIVIDE ( [Repeat Customers], [Customers] )
// Customers with >= 2 work orders / customers with >= 1, counted inside the current filter context.
```

### 4 Time Intelligence

**Revenue PM** - format `#,0`

```dax
Revenue PM = CALCULATE ( [Total Revenue], DATEADD ( DimDate[date], -1, MONTH ) )
```

**Revenue MoM %** - format `+0.0%;-0.0%;0.0%`

```dax
Revenue MoM % = DIVIDE ( [Total Revenue] - [Revenue PM], [Revenue PM] )
```

**Profit PM** - format `#,0`

```dax
Profit PM = CALCULATE ( [Profit], DATEADD ( DimDate[date], -1, MONTH ) )
```

**Profit MoM %** - format `+0.0%;-0.0%;0.0%`

```dax
Profit MoM % = DIVIDE ( [Profit] - [Profit PM], [Profit PM] )
```

**Revenue PY** - format `#,0`

```dax
Revenue PY = CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( DimDate[date] ) )
```

**Revenue YoY %** - format `+0.0%;-0.0%;0.0%`

```dax
Revenue YoY % = DIVIDE ( [Total Revenue] - [Revenue PY], [Revenue PY] )
```

**Profit PY** - format `#,0`

```dax
Profit PY = CALCULATE ( [Profit], SAMEPERIODLASTYEAR ( DimDate[date] ) )
```

**Profit YoY %** - format `+0.0%;-0.0%;0.0%`

```dax
Profit YoY % = DIVIDE ( [Profit] - [Profit PY], [Profit PY] )
```

**Revenue YTD** - format `#,0`

```dax
Revenue YTD = TOTALYTD ( [Total Revenue], DimDate[date] )
```

### 5 Display

**INR Short Revenue** - format `text`

```dax
INR Short Revenue =
VAR v = [Total Revenue]
RETURN
    IF (
        ISBLANK ( v ), "-",
        IF ( ABS ( v ) >= 10000000, FORMAT ( v / 10000000, "\₹0.0" ) & " Cr",
        IF ( ABS ( v ) >= 100000, FORMAT ( v / 100000, "\₹0.0" ) & " L", FORMAT ( v, "\₹#,0" ) ) )
    )
```

**INR Short Cost** - format `text`

```dax
INR Short Cost =
VAR v = [Total Cost]
RETURN
    IF (
        ISBLANK ( v ), "-",
        IF ( ABS ( v ) >= 10000000, FORMAT ( v / 10000000, "\₹0.0" ) & " Cr",
        IF ( ABS ( v ) >= 100000, FORMAT ( v / 100000, "\₹0.0" ) & " L", FORMAT ( v, "\₹#,0" ) ) )
    )
```

**INR Short Profit** - format `text`

```dax
INR Short Profit =
VAR v = [Profit]
RETURN
    IF (
        ISBLANK ( v ), "-",
        IF ( ABS ( v ) >= 10000000, FORMAT ( v / 10000000, "\₹0.0" ) & " Cr",
        IF ( ABS ( v ) >= 100000, FORMAT ( v / 100000, "\₹0.0" ) & " L", FORMAT ( v, "\₹#,0" ) ) )
    )
```

### 6 Ranking

**Centre Performance Index** - format `0`

```dax
Centre Performance Index =
VAR Centres = ALLSELECTED ( DimCentre[center_name] )
VAR N = COUNTROWS ( Centres )
VAR RankOnTime = RANKX ( Centres, [On-Time %], , ASC, Skip )
VAR RankRating = RANKX ( Centres, [Avg Rating], , ASC, Skip )
VAR RankMargin = RANKX ( Centres, [Profit Margin %], , ASC, Skip )
VAR RankTurn = RANKX ( Centres, [Avg Turnaround Hours], , DESC, Skip )
VAR RankCancel = RANKX ( Centres, [Cancellation Rate], , DESC, Skip )
RETURN
    IF (
        HASONEVALUE ( DimCentre[center_name] ),
        100 * DIVIDE ( RankOnTime + RankRating + RankMargin + RankTurn + RankCancel, 5 * N )
    )
```

**Centre Rank** - format `0`

```dax
Centre Rank =
IF (
    HASONEVALUE ( DimCentre[center_name] ),
    RANKX ( ALLSELECTED ( DimCentre[center_name] ), [Centre Performance Index], , DESC, Skip )
)
```

**Key Insight - Executive** - format `text`

```dax
Key Insight - Executive =
VAR T = ADDCOLUMNS ( VALUES ( DimCentre[center_name] ), "@OnTime", [On-Time %] )
VAR Worst = TOPN ( 1, FILTER ( T, NOT ISBLANK ( [@OnTime] ) ), [@OnTime], ASC )
RETURN
    IF (
        COUNTROWS ( T ) < 2,
        BLANK (),
        MAXX ( Worst, DimCentre[center_name] ) & " has the lowest on-time rate at "
            & FORMAT ( MINX ( Worst, [@OnTime] ), "0.0%" ) & " (network " & FORMAT ( [On-Time %], "0.0%" ) & ")."
    )
```

**Key Insight - Operations** - format `text`

```dax
Key Insight - Operations =
VAR T = ADDCOLUMNS ( VALUES ( DimCentre[center_name] ), "@Turn", [Avg Turnaround Hours] )
VAR Slowest = TOPN ( 1, FILTER ( T, NOT ISBLANK ( [@Turn] ) ), [@Turn], DESC )
RETURN
    IF (
        COUNTROWS ( T ) < 2,
        BLANK (),
        MAXX ( Slowest, DimCentre[center_name] ) & " is slowest, averaging "
            & FORMAT ( MAXX ( Slowest, [@Turn] ), "0.0" ) & " h turnaround."
    )
```

**Key Insight - Financial** - format `text`

```dax
Key Insight - Financial =
VAR T = ADDCOLUMNS ( VALUES ( DimServiceType[service_type] ), "@Margin", [Profit Margin %] )
VAR Best = TOPN ( 1, FILTER ( T, NOT ISBLANK ( [@Margin] ) ), [@Margin], DESC )
VAR Worst = TOPN ( 1, FILTER ( T, NOT ISBLANK ( [@Margin] ) ), [@Margin], ASC )
RETURN
    IF (
        COUNTROWS ( T ) < 2,
        BLANK (),
        MAXX ( Best, DimServiceType[service_type] ) & " earns the best margin (" & FORMAT ( MAXX ( Best, [@Margin] ), "0.0%" )
            & ") while " & MAXX ( Worst, DimServiceType[service_type] ) & " earns the lowest ("
            & FORMAT ( MAXX ( Worst, [@Margin] ), "0.0%" ) & ")."
    )
```

**Key Insight - Customer** - format `text`

```dax
Key Insight - Customer =
VAR T = ADDCOLUMNS ( VALUES ( DimCentre[center_name] ), "@Rating", [Avg Rating] )
VAR Lowest = TOPN ( 1, FILTER ( T, NOT ISBLANK ( [@Rating] ) ), [@Rating], ASC )
RETURN
    IF (
        COUNTROWS ( T ) < 2,
        BLANK (),
        MAXX ( Lowest, DimCentre[center_name] ) & " has the lowest average rating ("
            & FORMAT ( MINX ( Lowest, [@Rating] ), "0.00" ) & " / 5)."
    )
```

### 7 Titles

**Selection Label** - format `text`

```dax
Selection Label =
VAR Centre =
    IF ( ISFILTERED ( DimCentre[center_name] ),
         IF ( HASONEVALUE ( DimCentre[center_name] ), SELECTEDVALUE ( DimCentre[center_name] ), "Selected centres" ),
         "All centres" )
VAR Region =
    IF ( ISFILTERED ( DimCentre[region] ),
         IF ( HASONEVALUE ( DimCentre[region] ), SELECTEDVALUE ( DimCentre[region] ), "Selected regions" ),
         "All regions" )
VAR D0 = MIN ( DimDate[date] )
VAR D1 = MAX ( DimDate[date] )
RETURN
    Centre & " | " & Region & " | " & FORMAT ( D0, "dd mmm yyyy" ) & " - " & FORMAT ( D1, "dd mmm yyyy" )
```

**Title - Revenue and Profit Trend** - format `text`

```dax
Title - Revenue and Profit Trend = "Monthly revenue and profit - " & [Selection Label]
```

**Title - Turnaround by Centre** - format `text`

```dax
Title - Turnaround by Centre = "Turnaround time by centre (hours) - " & [Selection Label]
```

**Title - Profit by Centre** - format `text`

```dax
Title - Profit by Centre = "Profit by service centre - " & [Selection Label]
```

**Title - Rating Trend** - format `text`

```dax
Title - Rating Trend = "Rating trend - " & [Selection Label]
```

**Footer Disclaimer** - format `text`

```dax
Footer Disclaimer =
"Synthetic data for demonstration. Modelled on an EV two-wheeler service network; not affiliated with Ather Energy. Amounts in INR."

// Conditional-format helpers (use "Format by: Field value" on the table / bar colour)
```

**Colour - On-Time vs Network** - format `text`

```dax
Colour - On-Time vs Network =
VAR Network = CALCULATE ( [On-Time %], ALLSELECTED ( DimCentre ) )
RETURN IF ( [On-Time %] >= Network, "#00A67E", "#EB6834" )
```

**Colour - Profit Sign** - format `text`

```dax
Colour - Profit Sign = IF ( [Profit] >= 0, "#00A67E", "#EB6834" )
```

**Colour - Skill Level** - format `text`

```dax
Colour - Skill Level =
SWITCH (
    SELECTEDVALUE ( DimTechnician[skill_level] ),
    "Junior", "#EB6834",
    "Mid", "#2A78D6",
    "Senior", "#00A67E",
    "Master", "#4A3AA7",
    "#A9B4B0"
)
```

## Notes

- **Utilisation scope.** `fact_technician_month` relates to `DimDate` (month overlap), `DimCentre` and `DimTechnician`. Service-type and model slicers cannot filter capacity data, so `Technician Utilisation %` ignores them (identical behaviour in the Streamlit app).
- **Repeat Visit Rate** is evaluated inside the current filter context: a narrow date range lowers it because fewer customers have a second visit in the window.
- **INR lakh / crore.** Custom number formats cannot divide by 10^5 or 10^7, so KPI cards use the `INR Short ...` text measures (for example 78,238,663 renders as 7.8 Cr).
- **Colour helpers** (`Colour - ...`) return hex codes from the report theme; use them in *Conditional formatting > Format style: Field value*.
- **Insight measures** (`Key Insight - ...`) are computed text and update with every slicer, mirroring the Key insight captions in the Streamlit app.
