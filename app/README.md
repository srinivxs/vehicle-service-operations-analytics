# Streamlit dashboard

Runnable local mirror of the four Power BI pages (Executive Overview, Operations, Financial Analysis, Customer Experience) with five global slicers (date range, region, service centre, service type, model) shared by every page. Synthetic data for an EV two-wheeler service network modelled on Ather-style models; not affiliated with Ather Energy.

## Run

From the project root, with the project virtual environment:

```bash
# Windows (Git Bash)
./.venv/Scripts/python -m streamlit run app/streamlit_app.py
# Windows (PowerShell)
.\.venv\Scripts\python -m streamlit run app/streamlit_app.py
```

Open http://localhost:8501. For a headless server: add `--server.headless true --server.port 8501`; health check at `http://localhost:8501/_stcore/health` returns `ok`.

The app reads the cleaned CSVs from `data/cleaned/` (`fact_service`, `fact_appointments`, `fact_technician_month`, `part_usage`, `parts`, `service_centers`). If they are missing, generate and clean the data first (`python -m src.generate_data`, `python -m src.data_cleaning`). Set `VSO_DATA_DIR` to point at another folder.

## Tests

```bash
./.venv/Scripts/python -m pytest tests/test_kpis.py --cov=src.kpis --cov-report=term-missing   # KPI unit tests
./.venv/Scripts/python -m pytest tests/test_app_helpers.py                                      # formatting + insights
./.venv/Scripts/python -m pytest tests/test_app_smoke.py                                        # AppTest: every page renders, slicers change KPIs
```

## Layout

| Path | Role |
|---|---|
| `streamlit_app.py` | Entry point: `st.navigation` with four `st.Page` pages, wide layout |
| `shell.py` | Shared shell run on every page: CSS, data check, sidebar slicers |
| `data.py` | Cached loaders (`st.cache_data`), slicer options, filtering of every table |
| `components.py` | Palette, Plotly template, KPI cards, chart builders, styled tables, sidebar slicers |
| `formatting.py` | INR lakh / crore (`7.8 Cr`, `42.3 L`), percentages, hours |
| `insights.py` | Computed "Key insight" sentences (no hardcoded numbers) |
| `views/` | One module per page (`executive_overview`, `operations`, `financial_analysis`, `customer_experience`) |
| `../src/kpis.py` | Framework-free KPI functions shared with the tests and mirrored in DAX |
| `../.streamlit/config.toml` | Theme (accent green `#00A67E`, neutral greys) |

## Behaviour notes

* Slicers live in the entry script, so the selection persists while moving between pages; **Reset filters** restores everything. All KPIs, charts and tables read the same filtered tables.
* Technician utilisation comes from `fact_technician_month`, which has no service type or model, so those two slicers do not affect it (date, region and centre do). The page captions say so.
* Part-category cost is quantity x catalogue unit cost for the selected work orders and reconciles to the parts cost KPI.
* Repeat Visit Rate is customers with 2+ work orders over customers with 1+, evaluated inside the current filters.
* Colours follow one fixed palette (green accent, blue, orange, violet, grey); no dual-axis charts. The same palette is in `powerbi/vehicle_service_theme.json`.
