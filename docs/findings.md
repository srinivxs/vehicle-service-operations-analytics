# Findings Report: Vehicle Service Operations Analytics

**Engagement:** Service operations diagnostic for an 8-centre EV two-wheeler service network (Ather 450X, 450 Apex, Rizta)
**Period analysed:** 1 Jan 2025 to 30 Sep 2026 (21 months; 2026 is Jan to Sep)
**Data:** `data/cleaned/`: 24,092 work orders, 26,769 appointments, 12,186 rated jobs, 18 technicians, 39 part SKUs
**Prepared by:** Operations Analytics
**Status:** Final for management review

> All data is synthetic. It is modelled on an Ather-style EV scooter service network and is **not affiliated with
> or derived from Ather Energy**. Every number below comes from `python -m src.analysis_metrics` (output:
> `reports/analysis_metrics.json`) and `notebooks/03_exploratory_analysis.ipynb`. Charts are in `reports/figures/`.
> The relationships described are **associations** and should be read as hypotheses to confirm operationally, not as
> proven causes.

---

## Executive summary

1. **The network is profitable, but demand has outgrown capacity.** Revenue was **₹7.82 crore** and profit
   **₹1.91 crore** (24.4% margin). Jan to Sep 2026 delivered **47% more jobs** and **41% more revenue** than the same
   months of 2025, with the same 18 technicians. Over that period utilisation rose from **61% to 92%**, on-time
   completion fell from **81% to 67%**, and the share of ratings at 4 or above fell from **80% to 70%**.
2. **Three centres are over capacity.** In 2026 Mumbai - Andheri ran at **125%** of rostered technician hours,
   Chennai - Anna Nagar at **119%** and Delhi - Saket at **102%**. These are the three least punctual centres
   (62%, 65% and 67% on-time against 82-83% at Pune and Hyderabad). Across all centres, on-time drops from about
   **89% to 61%** once a day's booked work goes above 100% of capacity.
3. **Saturday is a structural peak.** Saturday carries **24%** of weekly jobs on the same roster. Mean wait is
   **3.1 h**, compared with 0.5-0.7 h on weekdays, and on-time is **55%**, compared with 76-81%.
4. **Parts stock-outs cause the longest delays, mainly in Kolkata.** **4.7%** of jobs wait for parts. Those jobs
   are **never** on time, their median turnaround is **116 h** (versus 2.5 h for other jobs) and their CSAT is
   **2.95**. Kolkata's parts-delay rate (**11.2%**) is 2-3× that of any other centre. Motor/controller and
   dashboard parts are delayed on about **28%** of the jobs that need them.
5. **Skill mix adds hidden capacity loss.** Junior technicians run **+0.65 h per job** over the labour estimate
   (Seniors +0.14 h), overrun the cost estimate twice as often (56% vs 27%) and pass QC first time less often
   (90.6% vs 94.8%). Mumbai has no Senior or Master technician.
6. **Long booking lead times are associated with cancellations.** Bookings made 15 or more days ahead cancel
   **19.2%** of the time, against 6.4% for 1-3 days. Mumbai's mean lead time (**6.0 days**, about 3 elsewhere) and
   its cancellation rate (**8.6%**, the highest) point back to slot scarcity.
7. **Missing the promised time is the strongest correlate of dissatisfaction** (Spearman ρ = **−0.60** between
   lateness and rating). CSAT% is **91%** for on-time jobs and **45%** for jobs up to 2 hours late.

**Bottlenecks identified (5):** B1 technician capacity (Mumbai, Chennai, Delhi), B2 the Saturday peak queue,
B3 parts availability (Kolkata, plus motor/controller and dashboard parts), B4 the skill mix (labour overruns and
first-pass quality), B5 booking lead time leading to cancellations (Mumbai). Each is investigated in
`docs/root_cause_analysis.md` and addressed in `docs/recommendations.md`.

---

## KPI baseline (network, full period)

| KPI | Value | KPI | Value |
|---|---|---|---|
| Revenue | ₹7.82 crore | On-time % | 73.2% |
| Total cost (labour ₹1.58 cr + parts ₹4.33 cr) | ₹5.91 crore | Avg / median turnaround | 11.2 h / 2.57 h |
| Profit / margin | ₹1.91 crore / 24.4% | Avg wait before work starts | 1.20 h (median 0.32 h) |
| Avg service cost per job | ₹2,454 | Technician utilisation | 75.6% (2026: 91.5%) |
| Avg revenue per job | ₹3,247 | Cancellation / no-show rate | 6.8% / 3.2% |
| Cost overrun rate (>10% over estimate) | 36.7% | CSAT (mean) / CSAT% (≥4) | 4.02 / 74.5% |
| Duration variance (actual − estimate) | +0.31 h per job | Parts delay rate | 4.7% |
| QC first-pass | 93.2% | Comeback rate (30-day) | 4.5% |
| Repeat-visit rate (customers with ≥2 WOs) | 85.7% | Zero-revenue rework jobs | 893 (₹13.2 lakh cost) |

---

## Findings

### F1. Growth has outpaced a fixed roster, and service level is falling as a result

| Metric (Jan-Sep) | 2025 | 2026 | Change |
|---|---|---|---|
| Work orders | 8,414 | 12,390 | +47.3% |
| Revenue | ₹2.81 crore | ₹3.98 crore | +41.4% |
| Profit | ₹68.3 lakh | ₹97.7 lakh | +43.1% |
| Technician utilisation | 61.3% | 91.5% | +30.3 pts |
| On-time % | 80.7% | 67.1% | −13.6 pts |
| Mean wait | 0.68 h | 1.68 h | +148% |
| CSAT% (ratings ≥ 4) | 79.7% | 70.2% | −9.5 pts |
| Parts-delay rate | 4.9% | 4.6% | flat |

* **Evidence:** service level fell while the parts-delay rate stayed flat, so the decline tracks **capacity**, not
  parts. Margin held at about 24% in both years.
* **Charts:** `fig01_monthly_revenue_cost_profit.png`, `fig02_volume_vs_service_level.png`
* **Confidence:** High for the trend. Moderate for the explanation, because demand growth, monsoon seasonality and
  fleet ageing all move together over time. The day-level and centre-level evidence in F2 and F3 is stronger.

### F2. Bottleneck B1: technician capacity at Mumbai, Chennai and Delhi

| Centre | Techs (Senior+) | Utilisation 2026 | Days overloaded 2026 | Jobs per tech per month 2026 | On-time | Mean wait | CSAT |
|---|---|---|---|---|---|---|---|
| **Mumbai - Andheri** | 2 (0) | **124.6%** | **38.0%** | 95 | **62.2%** | 1.84 h | **3.86** |
| **Chennai - Anna Nagar** | 2 (1) | **118.5%** | **48.7%** | **99** | 65.4% | **1.98 h** | 3.89 |
| **Delhi - Saket** | 2 (1) | **101.5%** | 29.2% | 82 | 67.5% | 1.48 h | 3.94 |
| Pune - Baner (benchmark) | 2 (2) | 65.3% | 16.5% | 63 | **83.1%** | 0.96 h | 4.14 |
| Hyderabad - Gachibowli (benchmark) | 2 (1) | 75.6% | 15.5% | 64 | 81.5% | 0.73 h | 4.14 |
| Network | 18 | 91.5% | n/a | n/a | 73.2% | 1.20 h | 4.02 |

* A day counts as **overloaded** when booked estimated hours exceed rostered technicians × 7 productive hours.
* **Technician level:** 7 of 18 technicians logged more service hours than rostered productive hours in 2026. The
  highest were T013 (Mumbai, Junior) at 132%, T016 (Delhi, Junior) at 129% and T007 (Chennai, Mid) at 127%.
  Pune, Hyderabad and Kolkata technicians were at 59-81%.
* **Service mix does not explain it.** Complex-job share is 10.8-12.2% and periodic share 58-61% at every centre.
  Fleet customers are a larger share of jobs at Mumbai (55%) and Chennai (56%) than at Hyderabad (31%).
* **Statistics:** on-time differs across centres (χ² = 635, Cramér's V = 0.16). Mumbai vs Pune on-time gap is
  **−20.9 pts** (95% CI −23.2 to −18.6; Cohen's h = −0.48, small-to-medium). Turnaround differs across centres
  (Kruskal-Wallis H = 578, ε² = 0.024, small). The difference sits in the tail, not the typical job: median waits
  are 0.43 h at Mumbai and 0.31 h elsewhere.
* **Overnight carry-over:** 8.8% of jobs with **no** parts delay still finish on a later day than check-in. The
  rate is 12.8% at Mumbai and 11.9% at Chennai, against 5.2-6.4% at Kolkata, Pune and Hyderabad. Only 29% of
  carried-over jobs are on time.
* **Charts:** `fig03_centre_on_time_utilisation_wait.png`, `fig04_technician_utilisation_heatmap.png`
* **Confidence:** High. The pattern is consistent across centres, months, technicians and days. Caveat: the data
  holds no overtime or attendance records, so utilisation above 100% cannot be split between unrecorded overtime
  and work spilling into the next day.

### F3. Service level holds until booked work reaches about 90% of capacity, then drops sharply

| Daily load (booked h ÷ capacity) | ≤60% | 80-90% | 90-100% | 100-110% | 120-140% | >160% |
|---|---|---|---|---|---|---|
| On-time % | 90.1% | 85.6% | 77.2% | 61.0% | 37.5% | 16.4% |
| Mean wait | 0.23 h | 0.40 h | 0.67 h | 1.03 h | 2.18 h | 8.60 h |
| Mean rating | 4.23 | 4.22 | 4.12 | 3.86 | 3.64 | 3.25 |
| QC first-pass | 94.3% | 93.9% | 93.7% | 92.1% | 91.1% | 90.6% |

* At centre-day level (n = 4,305), load correlates with mean wait at Spearman ρ = **0.63** and with on-time at
  ρ = **−0.56**. Both are large effects.
* **So what:** the target is to keep daily load **below about 90%**, not to maximise utilisation. This curve is
  the response function used in the what-if estimates (`fig14`).
* **Chart:** `fig08_daily_load_vs_service_level.png`
* **Confidence:** High for the association. Load is measured from *estimated* hours, so centres with slower
  technicians are more loaded than the ratio shows.

### F4. Bottleneck B2: Saturday peak-day queue

| Day | Share of jobs | Mean wait | On-time | CSAT | Overnight carry-over* |
|---|---|---|---|---|---|
| **Saturday** | **23.7%** | **3.06 h** | **54.8%** | **3.78** | **15.8%** |
| Tue-Thu | 14.4-14.8% each | 0.56 h | 80.0% | 4.12 | 6.3-7.1% |
| Monday | 16.4% | 0.66 h | 78.5% | 4.09 | 6.4% |

\* Share of jobs with no parts delay that finish after the check-in day. A Saturday carry-over waits over the
Sunday closure.

* Saturday vs other days on-time: χ² = 1,297, Cramér's V = **0.23** (moderate).
* In 2026, **84%** of Saturday booked hours came from scheduled bookings (app, web, call centre), not walk-ins,
  so most of the peak can be planned for.
* **Chart:** `fig10_weekday_peak.png`
* **Confidence:** High.

### F5. Bottleneck B3: parts availability (Kolkata; motor/controller and dashboard parts)

| | Parts-delayed jobs | Other jobs |
|---|---|---|
| Jobs | 1,134 (4.7%) | 22,958 |
| On-time % | **0.0%** | 76.8% |
| Median / mean turnaround | **116 h / 135 h** | 2.5 h / 5.1 h |
| Mean parts wait | 129 h | n/a |
| CSAT / CSAT% | **2.95 / 21%** | 4.08 / 78% |

* **By centre:** Kolkata **11.2%** of jobs parts-delayed (2026: 10.8%), Delhi 6.0%, all others 3.1-4.3%.
  Kolkata vs rest: χ² = 220, Cramér's V = 0.10. Kolkata has the highest delay rate in **every** part category
  (motor & controller 54%, dashboard & display 56%, body & lighting 47%, battery & electrical 34%), and **35.9%**
  of its complex repairs are parts-delayed (7.8% of other jobs). Kolkata therefore has the **highest mean
  turnaround (18.7 h)** despite a median of 2.34 h and only 67% utilisation.
* **By category (network):** dashboard & display 27.9% and motor & controller 27.5% of the jobs using them are
  delayed. Consumables 2.3%, brakes 3.7%.
* **By service type:** motor & controller repair (21.4% parts-delayed, 48.9% on-time) and accident & body repair
  (16.8%, 43.8%) are the least punctual services. Across the 11 service types, Spearman ρ between parts-delay
  rate and on-time is **−0.87**.
* **ABC analysis:** 21 A-class parts make up 81% of consumption value. Several are both A-class and delayed on 20%
  or more of the jobs that use them: P020 motor controller (450 Series), P024 motor assembly, P016 portable
  charger, P011 DC-DC converter, P025 TFT dashboard and P028 LED headlamp.
* **Delay vs promise:** the promise rule (estimate + 1.5 shop hours) does not change when a part is missing, so
  every stock-out becomes a broken promise.
* **Charts:** `fig06_turnaround_and_wait_distributions.png`, `fig11_parts_delay_category_by_centre.png`,
  `fig15_parts_abc_pareto.png`
* **Confidence:** High for the effect of delays on turnaround and satisfaction. Medium for the attribution to
  individual categories, because delay is recorded per job rather than per part line.

### F6. Lateness is the strongest correlate of customer dissatisfaction

| Lateness vs promise | On time | ≤2 h | 2-8 h | 8-24 h | 1-3 days | >3 days |
|---|---|---|---|---|---|---|
| CSAT% (rating ≥4) | **91%** | 45% | 28% | 27% | 23% | 16% |
| Responses | 8,495 | 2,165 | 373 | 215 | 484 | 454 |

* Spearman ρ: rating vs late hours **−0.60** (n = 12,186); rating vs wait hours −0.34.
* On-time jobs average 4.36; late jobs average 3.23.
* **Implication:** a small miss already costs most of the satisfaction. Setting accurate promises, and updating
  the customer proactively when a promise will be missed, matters as much as raw speed.
* **Charts:** `fig09_csat_by_lateness.png`, `fig07_spearman_correlation_matrix.png`
* **Confidence:** High for the association. Feedback is voluntary (50.6% response rate), and the response
  propensity is higher after bad experiences, so absolute CSAT is probably biased downward. The *relative*
  comparison is the robust part.

### F7. Bottleneck B4: skill mix, labour overruns and first-time quality

| Skill | Jobs | Complex-job share | Labour over estimate | Cost overrun rate | QC first-pass | On-time |
|---|---|---|---|---|---|---|
| Junior | 6,323 | 5.0% | **+0.65 h** | **55.7%** | **90.6%** | 65.6% |
| Mid | 6,052 | 10.6% | +0.34 h | 36.9% | 92.5% | 70.7% |
| Senior | 9,526 | 14.7% | +0.14 h | 27.5% | 94.8% | 78.6% |
| Master | 2,119 | 19.2% | −0.02 h | 21.4% | 96.1% | 78.7% |

* **Complex jobs only** (to control for job mix): Junior +1.09 h over estimate and 87.3% QC first-pass; Senior
  +0.25 h and 92.4%.
* Overrun vs skill: Cramér's V = **0.25** (moderate). QC first-pass vs skill: V = 0.08 (small).
* **Where it matters:** juniors handle **50.5%** of Mumbai's jobs and **59.1%** of Delhi's, the two most loaded
  junior rosters. Mumbai has **no** Senior or Master technician, and its complex-job on-time rate is 45.7%. At the
  2026 run-rate, bringing juniors' labour variance to Mid level would release about **113 labour hours per month**
  across the network (≈0.6 of a technician).
* **What we do *not* claim:** comebacks by skill are close once job mix is controlled (complex jobs: Junior 5.7%,
  Senior 6.6%). Juniors also have the **highest** margin (29.3%) because their hourly cost is lower and they do
  simpler jobs. The issue is capacity and first-time quality, not junior cost.
* **Cost of quality:** 893 zero-revenue rework visits cost **₹13.2 lakh** and used 1,177 labour hours.
* **Chart:** `fig12_skill_quality_and_overruns.png`
* **Confidence:** Medium. Jobs are not assigned at random (complex work goes to senior staff), so the skill
  comparison is confounded. The complex-only cut reduces this but does not remove it.

### F8. Bottleneck B5: long booking lead time and cancellations (Mumbai)

| Booking lead time | Same day | 1-3 days | 4-7 days | 8-14 days | 15+ days |
|---|---|---|---|---|---|
| Appointments | 4,083 | 11,457 | 8,050 | 2,893 | 286 |
| Cancellation rate | 0.3% | 6.4% | 8.4% | 11.7% | **19.2%** |

* Lead band vs cancellation: χ² = 486, Cramér's V = **0.13** (small-to-moderate).
* **Mumbai** books **32.1%** of appointments 8 or more days ahead (network 11.9%), has a mean lead of **6.0 days**
  (other centres' median 3.1) and the highest cancellation rate (**8.6%**; other centres' median 6.4%). "Long
  Wait for Slot" is **29%** of Mumbai's cancellations, the highest share in the network.
* **Other cancellation patterns:** Monday 8.9% vs 5.7-6.8% on other days. Software-update visits 10.7%, mostly
  "Issue resolved via OTA update" (capacity freed, if the slot is released quickly). Walk-ins never cancel.
* **Size of prize:** at 2026 volumes, bringing 8+ day bookings to the 4-7 day cancellation rate would recover
  about **6.6 jobs per month** (≈₹21,000 revenue, ₹5,200 profit per month). The value is mainly in customer
  retention and demand signal, not direct revenue.
* **Chart:** `fig13_cancellation_lead_time.png`
* **Confidence:** Medium. Lead time explains part of cancellation behaviour, and most cancellations are still for
  personal or rescheduling reasons.

### F9. Cost overruns come from scope found during service and from low labour estimates

| | Additional work found | No additional work |
|---|---|---|
| Share of jobs | 17.3% | 82.7% |
| Cost overrun rate | **95.3%** | 25.1% |
| Median cost variance | **+70.9%** | +2.4% |
| CSAT | **3.65** | 4.10 |
| Margin | 20.2% | 26.3% |

* **69%** of all jobs take longer than estimated. The mean is +0.31 h per job, so labour estimates are
  systematically optimistic.
* Overrun without additional work is highest at Mumbai (37.9%) and Delhi (31.8%) and lowest at Pune (9.5%). This
  matches the skill and capacity pattern in F2 and F7.
* **Implication:** the estimate fails at two points: scope discovered **after** the quote (an inspection and
  approval gap) and labour time (calibration and skill).
* **Confidence:** High for the description. The CSAT gap may partly reflect bill shock, which the data cannot
  separate from longer job duration.

### F10. Service type and vehicle model: complex repairs are the weak spot; model is not a primary driver

* **Least reliable services:** accident & body repair (43.8% on-time, 42.5 h mean turnaround), motor & controller
  repair (48.9%, 63.3 h), charging system repair (61.8%), electrical diagnostics (63.7%). Periodic service, at 59%
  of volume, is 75.6% on-time.
* **Lowest-margin services:** motor & controller 13.0%, electrical diagnostics 14.7%, charging 16.7%. These are
  warranty-heavy and parts-heavy repairs.
* **Models:** Ather 450 Apex 71.6% on-time and 5.2% parts-delayed. Ather 450X 73.4% and 5.1%. Rizta 73.2% and
  4.1%. The differences are small next to the centre, day and parts effects, so model-specific action is not a
  priority. Apex is 5.4% of volume.
* **Chart:** `fig05_service_type_parts_vs_on_time.png`

### F11. Financial structure: where the margin is made and lost

* Parts are **73%** of cost (₹4.33 crore of ₹5.91 crore).
* Margin by billing type: customer-paid 32.6%, service plan 8.3%, warranty 7.2%. Rework is −₹13.2 lakh.
* Margin by customer type: fleet customers are **48%** of jobs at a 20.3% margin, compared with 27.7% for
  individuals.
* By centre, Mumbai has the **highest** margin (27.1%) and Pune the lowest (21.9%). The cheaper junior-heavy
  roster at Mumbai raises margin while it lowers service level. This trade-off is why the recommendations
  balance capacity cost against service level.
* **Confidence:** High for the arithmetic. Pricing rules (labour billed on estimate, warranty rates) are
  simulation assumptions documented in `docs/assumptions_and_limitations.md` and `src/config.py`.

---

## Bottleneck summary

| ID | Bottleneck | Process stage | Outlier evidence | Benchmark | Outcome association |
|---|---|---|---|---|---|
| B1 | Technician capacity | Service (technician time) | Utilisation 2026: Mumbai 125%, Chennai 119%, Delhi 102% | Pune 65%, Hyderabad 76% | On-time 62% / 65% / 67% vs 82-83%; on-time ≤61% when load is above 100% |
| B2 | Saturday peak queue | Check-in to service start | Wait 3.06 h, on-time 55%, 24% of jobs | Tue-Thu wait 0.56 h, on-time 80% | CSAT 3.78 vs 4.12 |
| B3 | Parts availability | Parts allocation | Kolkata 11.2% parts-delayed; motor/controller and dashboard parts ~28% | Bengaluru-Whitefield 3.1%; network 4.7% | Delayed jobs: 0% on-time, 116 h median turnaround, CSAT 2.95 |
| B4 | Skill mix | Service and quality check | Junior +0.65 h/job, overrun 56%, QC 90.6% | Senior +0.14 h, 27%, 94.8% | About 113 labour h/month of hidden capacity loss |
| B5 | Booking lead time | Appointment | Mumbai lead 6.0 days, cancellation 8.6% | Other centres 3.1 days, 6.4% | 15+ day bookings cancel 19.2% |

B1, B2 and B4 are linked: they are three views of the same constrained resource (productive technician hours).
B3 is independent and location-specific. B5 is a demand-side symptom of B1 at Mumbai.

---

## Limitations and caveats

* **Synthetic data.** Patterns come from simulation mechanics designed to resemble a real network. They show the
  method, not facts about any real operator.
* **Associations only.** None of the tests establishes causation. Each recommendation names the operational data
  that would confirm or reject its hypothesis (`docs/root_cause_analysis.md`).
* **Not captured:** technician attendance and overtime, line-level stock-outs, inspection and approval timestamps,
  payment and handover times. The process map marks these stages as "not captured".
* **Clock hours.** Wait and turnaround include nights and Sundays for jobs that carry over. Medians are reported
  alongside means.
* **Comeback KPI.** `caused_repeat_visit` (1,085 jobs) slightly over-counts true rework compared with jobs billed
  as "Rework (No Charge)" (893), because some same-type revisits within 30 days are coincidental.
* **Feedback bias.** Ratings cover 50.6% of jobs, and dissatisfied customers respond more often.
* **What-if estimates** (`docs/recommendations.md`) use a simple response curve. They are planning estimates,
  not forecasts.

## Reproduce

```bash
python -m src.generate_data          # raw data (seed 42)
python -m src.data_cleaning          # cleaned tables + DQ report
python -m src.analysis_metrics       # every number in this document -> reports/analysis_metrics.json
jupyter nbconvert --to notebook --execute --inplace notebooks/03_exploratory_analysis.ipynb   # charts
```
