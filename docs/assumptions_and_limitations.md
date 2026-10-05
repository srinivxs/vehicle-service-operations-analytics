# Assumptions and Limitations

| | |
|---|---|
| Project | Vehicle Service Operations Analytics & Process Optimization |
| Version | 1.0 |
| Date | 2026-10-05 |
| Author | Analytics Team |
| Read with | [business_requirements.md](business_requirements.md) (sections 11-13), [data_lineage.md](data_lineage.md) (section 7 for data-handling assumptions), [data_dictionary.md](data_dictionary.md) |

The data is **synthetic**. It models an EV two-wheeler service network in the style of Ather's range (Ather 450X, 450 Apex, Rizta) and is not Ather Energy data. Constants named below live in `src/config.py` or `src/reference_data.py`. Assumption IDs A-01 to A-09 match the BRD.

## 1. Modelling assumptions

### 1.1 Calendar and capacity

| ID | Assumption | Value | Consequence for KPIs |
|---|---|---|---|
| A-01 | All data is simulated by `src/generate_data.py` (seed 42, 21 months, 8 centres, 18 technicians, 5,300 vehicles) | Fixed | Operational behaviour is whatever the simulation encodes (section 2) |
| A-02 | Centres open Monday to Saturday, 09:00-19:00; Sunday closed. Each technician has 7 productive hours per working day (paid shift is 8) | `SHOP_OPEN_HOUR=9`, `SHOP_CLOSE_HOUR=19`, `PRODUCTIVE_HOURS_PER_DAY=7.0` | Utilisation = actual hours / (Mon-Sat days x 7). No public holidays, leave or sickness are modelled, so available hours are slightly overstated and utilisation slightly understated |
| A-10 | Technician utilisation counts `actual_hours` (labour including rework time) of jobs by check-in month; idle waiting and parts waiting are not counted | n/a | Values above 100% occur (68 of 378 technician-months): the model lets a technician accumulate more labour hours than 7 per day; read them as overload, not as an error |

### 1.2 Time and promise

| ID | Assumption | Value | Consequence |
|---|---|---|---|
| A-03 | Promised ready time = check-in + estimated hours + 1.5 hours, counted in shop hours only | `PROMISE_BUFFER_HOURS=1.5` | On-time % depends on this buffer; a different buffer changes every on-time figure |
| A-11 | `turnaround_hours` and `wait_hours` are elapsed clock hours (include nights and Sundays) | n/a | A job that straddles closing time shows 14 or more hours of turnaround; the mean (11.2 h) is far above the median (2.6 h). Use the median or on-time rate for typical performance |
| A-12 | Parts waiting is measured in calendar hours (up to 571 h) while the promise is in shop hours | n/a | Every parts-delayed job is late by construction (0% on-time for the 1,134 delayed jobs), so on-time % and parts-delay rate are mechanically linked |

### 1.3 Pricing, cost and estimates

| ID | Assumption | Value | Consequence |
|---|---|---|---|
| A-04 | Customer-paid labour is billed at a flat rate on **estimated** hours (x1.35 when additional work is found) | INR 750 per hour (`LABOUR_BILL_RATE`) | A job that runs longer than estimated earns no extra revenue, so overruns directly reduce profit |
| A-04 | Parts are billed at cost plus a mark-up | 1.30 customer paid (`PARTS_MARKUP`); 1.05 warranty (`WARRANTY_PARTS_MARKUP`) | Parts margin is constant across categories |
| A-04 | Warranty labour rate; service-plan fee; fleet discount | INR 500 per hour; INR 950 flat; 10% off | Warranty and rework jobs are often loss-making (2,647 jobs have negative profit) |
| A-13 | Labour cost = `actual_hours` x the technician's hourly cost | INR 210 / 280 / 360 / 450 for Junior / Mid / Senior / Master | Technician cost is a rate card, not payroll; one rate applies in every city |
| A-14 | `estimated_cost` = `estimated_hours` x technician rate + quoted parts at unit cost | n/a | Parts found necessary during inspection are not in the estimate, so the cost overrun rate (36.7%) is partly structural. Compare overruns between groups, not against zero |
| A-15 | All prices are constant over 21 months; INR excluding GST | n/a | No inflation, price changes, or regional price differences |

### 1.4 Warranty, service plan and rework rules

| ID | Rule | Effect |
|---|---|---|
| A-16 | Warranty billing applies when the service type is warranty-eligible (Battery Health Check, Motor & Controller Repair, Charging System Repair, Electrical Diagnostics), parts are used, the vehicle is under 3 years old, and a random 85% test passes | 1,211 warranty jobs (5.0%) |
| A-17 | Service Plan billing applies to Periodic Service for a plan-enrolled vehicle (30% of individual, 60% of fleet, 50% of corporate vehicles) | 6,379 plan jobs; flat fee regardless of work done |
| A-05 | A comeback is a completed visit for the same vehicle and service type within 30 days of the previous completed visit (`REPEAT_VISIT_WINDOW_DAYS=30`). The simulation also creates "Rework (No Charge)" return visits (revenue 0) | The 30-day rule flags 1,085 jobs, while 893 rework visits were simulated; the difference (at least 192) is ordinary same-service returns inside 30 days. The rule is a proxy, not an audited rework flag |

### 1.5 Demand, bookings and customers

| ID | Assumption | Effect |
|---|---|---|
| A-18 | Walk-ins (about 14% of bookings) are same-day and never cancelled or no-show. Cancellation probability grows with booking lead time (and on Mondays and for software-update jobs); no-show probability also grows with lead time | Cancellation rate (6.8%) and its link to lead time are properties of the model. Cancellation reasons are drawn from a fixed list with "Long Wait for Slot" weighted by lead time |
| A-19 | 93.5% of customers are individuals with 1-2 vehicles; fleet (3.5%) and corporate (3%) accounts own 4-20 and 2-6 vehicles and visit more often (fleet accounts generate 48% of work orders) | Network averages are dominated by fleet behaviour: a 85.7% repeat-visit rate reflects scheduled periodic service and fleet cycles (every 91 days), not loyalty. Interpret by customer type |
| A-20 | Repair demand follows a seasonal curve (higher in June-September) and a weekday curve (Saturday busiest); periodic service peaks in October-November | Trends over the 21 months contain only one full Oct-Dec season; year-on-year comparison is limited to January-September |
| A-21 | 92% of visits are at the customer's home centre; the rest go to another centre in the same region | Centre loads are therefore mostly determined by customer allocation (`demand_weight`) |

### 1.6 Workshop execution

| ID | Assumption | Effect |
|---|---|---|
| A-22 | Technicians are assigned randomly, weighted by skill fit (complex jobs favour Senior and Master; routine jobs favour Junior and Mid) and by how much work they already have that day. Absence and shift patterns are not modelled | Technician workload and skill-mix results reflect this allocation rule |
| A-23 | Skill level changes labour time (Junior 22% slower than estimate, Master 10% faster), QC failure risk and comeback risk | Skill-level differences in rework and duration are expected by construction |
| A-24 | Daily load (scheduled hours / roster capacity) above 100% lengthens waits and adds labour time, QC failures and comebacks | Centres with few technicians relative to demand show longer waits and lower on-time rates by design |
| A-25 | Parts stock-outs are random per part with category-based probability, multiplied by a centre factor (higher for distant centres) and, for model-specific parts, a model factor. A stock-out pauses the job until a replacement arrives (supplier lead days x a random factor) | Parts-delay differences between centres and categories are built in |
| A-26 | `daily_job_capacity`, `service_bays` and `opened_date` are descriptive; the simulation constrains work by technician hours, not by bays or job capacity | Do not use bays or job capacity to explain performance |

### 1.7 Customer feedback

| ID | Assumption | Effect |
|---|---|---|
| A-08 | Feedback is optional. Response rates differ by customer type (individual 62%, corporate 50%, fleet 35%) and are 10 points higher after a late job or comeback | 49.4% of jobs have no rating; the score describes responders and is biased toward customers with strong reactions |
| A-27 | Rating = 4.5 minus penalties (late delivery, long wait, comeback, additional work) plus noise, rounded to 1-5. Feedback categories are assigned by rule (section 6.5 of the data dictionary) | The link between lateness and rating, and the frequency of each feedback theme, are consequences of these rules |

### 1.8 Data handling and governance

| ID | Assumption | Effect |
|---|---|---|
| A-06 | Cleaning treatments: duplicates removed (keep first); swapped start and end times corrected; negative amounts converted to absolute value; revenue above 10x cost and INR 50,000 divided by 100; missing parts cost recomputed from part usage; out-of-range ratings removed; orphan keys removed | Documented in [data_lineage.md](data_lineage.md) section 2.2 and `reports/cleaning_log.csv`; real-world data would need business confirmation of each rule |
| A-07 | `financials` is the system of record for money; where it differs from part-usage lines (114 jobs) it is kept | Parts-category drill-downs may not tie exactly to billed parts cost |
| A-09 | KPI targets and alert thresholds in BRD section 10 are proposals set by the analytics team | Not industry benchmarks |
| A-28 | No personal data is stored; all IDs are surrogate keys | Customer-level analysis is limited to IDs and attributes in the data dictionary |

## 2. Mechanisms built into the simulation

The generator contains explicit cause-and-effect rules (section 1). Findings that match them are **expected recoveries of known mechanisms**, not independent discoveries about real operations. They demonstrate the analytical method and the traceability from metric to recommendation.

| Mechanism | Where encoded | Metrics it shapes |
|---|---|---|
| Roster capacity vs demand (centres with 2 technicians and high `demand_weight`, junior-heavy roster at one centre, longer booking lead at another) | `CENTRES` in `src/reference_data.py` | Wait, on-time %, utilisation, cancellation, rework |
| Supply-chain distance (`parts_risk`) and part category stock-out probabilities | `CENTRES`, `STOCKOUT_BASE` | Parts-delay rate, turnaround tail, parts-availability feedback |
| Skill level effects on labour time, QC and rework | `SKILL_LEVELS` | Duration variance, QC first-pass, comeback rate |
| Early-life electrical and motor issues on a newer model; thin supply of model-specific parts during ramp-up | `_repair_type`, `_stockout_prob` | Service mix by model, parts delays for newer models, falling then normalising availability |
| Seasonal and weekday demand curves | `REPAIR_SEASON`, `DOW_WEIGHT` | Monthly volume, waits on peak days, 2026 vs 2025 on-time |
| Lead-time-driven cancellations | `_status` | Cancellation by lead-time band |

Recommendations derived from these metrics are scenario-based: the expected impact is an estimate of what the metric would do if the mechanism were removed, calculated on this synthetic data.

## 3. Limitations

### 3.1 Data limitations

| # | Limitation | Why it matters |
|---|---|---|
| L-01 | Synthetic data from a single generator and seed | Not evidence of real-world performance; no external validation |
| L-02 | 21-month window (Jan 2025 - Sep 2026), 24,092 completed jobs | Only one full Oct-Dec; year-on-year only for Jan-Sep; 2026 vs 2025 comparisons use unequal months unless aligned |
| L-03 | 18 technicians, 2-3 per centre | Technician rankings and centre utilisation are unstable; one absence is not modelled; avoid performance management conclusions |
| L-04 | 49.4% of jobs have no feedback | CSAT is a responder score; centre differences in response rate can mask or create gaps |
| L-05 | Cancelled and no-show appointments have no cost or revenue | Lost revenue is not measurable; only volume and reasons |
| L-06 | 72 work orders with no valid technician, 23 with no start time, 40 appointments with an imputed centre, 24 revenue values rescaled | Documented; effect below 0.5% of work orders; technician KPIs exclude the 72 |
| L-07 | Turnaround is elapsed clock time, parts waits are calendar time, promises are in shop hours | Mean turnaround and on-time % must be read with the median, the delay distribution and the parts-delay split |
| L-08 | Mileage and odometer values derive from a daily-distance model; some reach 260,000 km | Not suitable for reliability or battery-wear analysis |
| L-09 | `scheduled_slot` contains 34 values with minute `:60`; 60 feedback dates fall after the period end | Cosmetic; not used in KPIs |
| L-10 | No telemetry, battery state-of-health, fault codes or warranty claims data | Cannot analyse failure causes beyond service type and part category |
| L-11 | No inflation, price changes or regional pricing; INR excluding GST | Financial trends reflect volume and mix, not price |

### 3.2 Analytical limitations

| # | Limitation |
|---|---|
| L-12 | Observed relationships (workload vs delay, parts vs lateness, skill vs rework) are associations. They are treated as hypotheses for operational investigation (spec section 9), not proven causes. Many are partly mechanical because of the definitions in section 1.2 |
| L-13 | Repeat-visit rate is high (85.7%) because periodic service is scheduled and fleet accounts visit every few months. It is not a loyalty or retention measure and has no churn counterpart |
| L-14 | The comeback rate uses a 30-day, same-vehicle, same-service proxy; it cannot separate true rework from a genuine new fault of the same type |
| L-15 | Cost overrun rate compares actual cost with an estimate that excludes unquoted parts, so it overstates overrun risk and is best used to compare groups |
| L-16 | Targets and thresholds in the BRD are proposals; changing them changes red/amber/green status but not the data |
| L-17 | Statistical tests (where used) assume independent jobs; jobs from the same vehicle, customer or technician are correlated, so p-values are indicative |

### 3.3 What cannot be concluded from this project

- Anything about Ather Energy, its service network, customers or products.
- Causal effects of any operational factor or of any recommended change; expected impacts are model-based scenarios.
- The revenue lost to cancellations, or customer lifetime value and churn.
- Individual technician performance suitable for employment decisions.
- Vehicle reliability, battery health or component failure rates.
- Price elasticity, competitive position, or demand forecasts beyond September 2026.
- Real-world benchmark values for any KPI (the targets here are analyst proposals).

## 4. Known data quirks (no action required)

| Quirk | Detail |
|---|---|
| Generator comment vs data | The docstring of `src/generate_data.py` mentions a 10-centre network; the data has 8 centres |
| Column spelling | `labor_cost` (American, per the specification) coexists with `utilisation` (British) |
| SQL vs Python names | The same comeback concept is `caused_repeat_visit` (Python) and `caused_comeback` (SQL) |
| Rule IDs | Python cleaning rules are DQ01-DQ20; `sql/data_quality.sql` has its own check IDs with a similar prefix |
| Negative `days_since_same_service` | 7 rows where the next job started before the previous ended |
