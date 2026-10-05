-- =============================================================================
-- kpi_queries.sql  |  Business analysis queries (PostgreSQL 16, schema service_ops)
--
-- Each query starts with a "-- Qxx: title" header and a business question, and is
-- terminated by a semicolon. src/run_sql_reports.py splits this file on those
-- headers and writes one CSV per query. Run interactively with:
--     SET search_path TO service_ops, public;
--
-- Techniques demonstrated: INNER / LEFT JOIN, GROUP BY / HAVING, CASE, CTEs,
-- window functions (LAG, RANK, DENSE_RANK, NTILE, PERCENT_RANK, running and
-- moving aggregates), ROLLUP / GROUPING SETS, FILTER, LATERAL, percentiles,
-- DATE_TRUNC / EXTRACT / generate_series, and the reusable vw_* KPI views.
-- Ratios in the views are fractions; these reports show percentages (_pct).
-- =============================================================================

SET search_path TO service_ops, public;

-- Q01: Headline KPI scorecard
-- Business question: What are the 16 canonical KPIs for the whole network over Jan 2025 - Sep 2026?
-- Technique: single-row view unpivoted with a LATERAL VALUES list.
SELECT k.kpi_no, k.kpi, k.value, k.unit
FROM vw_kpi_summary s
CROSS JOIN LATERAL (VALUES
    (1,  'Total revenue',                     s.total_revenue,                 'INR'),
    (2,  'Total cost (labour + parts)',       s.total_cost,                    'INR'),
    (3,  'Profit',                            s.profit,                        'INR'),
    (3,  'Profit margin',                     s.profit_margin * 100,           '%'),
    (4,  'Average service cost',              s.avg_service_cost,              'INR / job'),
    (5,  'On-time completion',                s.on_time_rate * 100,            '%'),
    (6,  'Average turnaround',                s.avg_turnaround_hours,          'hours'),
    (6,  'Median turnaround',                 s.median_turnaround_hours,       'hours'),
    (7,  'Total cost variance (actual - est.)', s.total_cost_variance,          'INR'),
    (7,  'Average cost variance',             s.avg_cost_variance,             'INR / job'),
    (7,  'Cost overrun rate (> 10% over est.)', s.cost_overrun_rate * 100,     '%'),
    (8,  'Cancellation rate',                 s.cancellation_rate * 100,       '%'),
    (8,  'No-show rate',                      s.no_show_rate * 100,            '%'),
    (9,  'Technician utilisation',            s.technician_utilisation * 100,  '%'),
    (10, 'Average customer rating',           s.avg_rating,                    '1-5'),
    (10, 'CSAT (rating >= 4)',                s.csat_rate * 100,               '%'),
    (11, 'Repeat visit rate (customers)',     s.repeat_visit_rate * 100,       '%'),
    (12, 'Comeback (rework) rate',            s.comeback_rate * 100,           '%'),
    (13, 'Duration variance (actual - est.)', s.avg_duration_variance_hours,   'hours / job'),
    (14, 'Parts delay rate',                  s.parts_delay_rate * 100,        '%'),
    (15, 'First-time QC pass rate',           s.qc_first_pass_rate * 100,      '%'),
    (16, 'Average wait before work starts',   s.avg_wait_hours,                'hours')
) AS k(kpi_no, kpi, value, unit)
ORDER BY k.kpi_no, k.kpi;

-- Q02: Monthly revenue, cost and profit with month-over-month growth
-- Business question: How are revenue, cost and profit trending, and how fast is each month growing versus the prior month?
-- Technique: DATE_TRUNC, CTE, LAG window, running total.
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', check_in_time)::DATE AS month_start,
        COUNT(*)                                 AS work_orders,
        SUM(revenue)                             AS revenue,
        SUM(total_cost)                          AS total_cost,
        SUM(profit)                              AS profit
    FROM vw_work_order_enriched
    GROUP BY DATE_TRUNC('month', check_in_time)
)
SELECT
    TO_CHAR(month_start, 'YYYY-MM')                                                    AS year_month,
    work_orders,
    ROUND(revenue, 2)                                                                  AS revenue,
    ROUND(total_cost, 2)                                                               AS total_cost,
    ROUND(profit, 2)                                                                   AS profit,
    ROUND(100 * profit / NULLIF(revenue, 0), 2)                                        AS profit_margin_pct,
    ROUND(100 * (revenue / NULLIF(LAG(revenue) OVER (ORDER BY month_start), 0) - 1), 2) AS revenue_mom_growth_pct,
    ROUND(100 * (total_cost / NULLIF(LAG(total_cost) OVER (ORDER BY month_start), 0) - 1), 2) AS cost_mom_growth_pct,
    ROUND(100 * (profit / NULLIF(LAG(profit) OVER (ORDER BY month_start), 0) - 1), 2)  AS profit_mom_growth_pct,
    ROUND(SUM(revenue) OVER (ORDER BY month_start), 2)                                 AS cumulative_revenue
FROM monthly
ORDER BY month_start;

-- Q03: Turnaround time by service centre
-- Business question: Which centres take longest to return a vehicle, and how skewed is turnaround (mean vs median vs P90)?
-- Technique: INNER JOINs on raw tables, EXTRACT(EPOCH), PERCENTILE_CONT, RANK.
SELECT
    sc.center_name,
    COUNT(*)                                                                           AS work_orders,
    ROUND(AVG(EXTRACT(EPOCH FROM (wo.end_time - wo.check_in_time)) / 3600)::NUMERIC, 2) AS avg_turnaround_hours,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (wo.end_time - wo.check_in_time)) / 3600))::NUMERIC, 2) AS median_turnaround_hours,
    ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (wo.end_time - wo.check_in_time)) / 3600))::NUMERIC, 2) AS p90_turnaround_hours,
    ROUND(100.0 * AVG((wo.end_time::DATE = wo.check_in_time::DATE)::INT), 1)           AS same_day_return_pct,
    RANK() OVER (ORDER BY AVG(EXTRACT(EPOCH FROM (wo.end_time - wo.check_in_time))) ASC) AS speed_rank
FROM work_orders wo
JOIN appointments    a  ON a.appointment_id = wo.appointment_id
JOIN service_centers sc ON sc.center_id     = a.center_id
GROUP BY sc.center_name
ORDER BY speed_rank;

-- Q04: On-time completion rate by centre (with network total)
-- Business question: What share of jobs finish by the promised ready time, and how late are the late ones?
-- Technique: ROLLUP for a network total row, FILTER for late-job averages.
SELECT
    COALESCE(center_name, 'ALL CENTRES')                                       AS center_name,
    COUNT(*)                                                                   AS work_orders,
    COUNT(*) FILTER (WHERE on_time_flag)                                       AS on_time_jobs,
    ROUND(100.0 * AVG(on_time_flag::INT), 2)                                   AS on_time_pct,
    ROUND(AVG(late_hours) FILTER (WHERE NOT on_time_flag), 2)                  AS avg_hours_late_when_late,
    ROUND(100.0 * AVG(parts_delay_flag::INT) FILTER (WHERE NOT on_time_flag), 2) AS pct_of_late_jobs_with_parts_delay
FROM vw_work_order_enriched
GROUP BY ROLLUP (center_name)
ORDER BY (center_name IS NULL), on_time_pct DESC;

-- Q05: Technician workload with rank inside each centre
-- Business question: How is work distributed across technicians, and who carries the heaviest load in each centre?
-- Technique: LEFT JOIN (idle technicians stay visible), RANK vs DENSE_RANK, partitioned SUM share.
WITH workload AS (
    SELECT
        sc.center_name,
        t.technician_id,
        t.skill_level,
        COUNT(wo.work_order_id)           AS jobs,
        COALESCE(SUM(wo.actual_hours), 0) AS service_hours
    FROM technicians t
    JOIN service_centers sc       ON sc.center_id    = t.center_id
    LEFT JOIN work_orders wo      ON wo.technician_id = t.technician_id
    GROUP BY sc.center_name, t.technician_id, t.skill_level
)
SELECT
    w.center_name,
    w.technician_id,
    w.skill_level,
    w.jobs,
    ROUND(w.service_hours, 1)                                                           AS service_hours,
    ROUND(100 * w.service_hours / (pc.working_days * pc.productive_hours_per_day), 1)   AS utilisation_pct,
    RANK()       OVER (PARTITION BY w.center_name ORDER BY w.service_hours DESC)        AS hours_rank_in_centre,
    DENSE_RANK() OVER (PARTITION BY w.center_name ORDER BY w.jobs DESC)                 AS jobs_dense_rank_in_centre,
    ROUND(100 * w.service_hours / NULLIF(SUM(w.service_hours) OVER (PARTITION BY w.center_name), 0), 1) AS pct_of_centre_hours
FROM workload w
CROSS JOIN vw_period_calendar pc
ORDER BY w.center_name, hours_rank_in_centre, w.technician_id;

-- Q06: Top service types by revenue and profit
-- Business question: Which service types drive the business, and how concentrated is revenue?
-- Technique: view + RANK, share-of-total and cumulative share window functions.
SELECT
    service_type,
    work_orders,
    revenue,
    profit,
    ROUND(100 * profit_margin, 2)                                           AS profit_margin_pct,
    avg_service_cost,
    RANK() OVER (ORDER BY revenue DESC)                                     AS revenue_rank,
    RANK() OVER (ORDER BY profit DESC)                                      AS profit_rank,
    ROUND(100 * revenue / SUM(revenue) OVER (), 2)                          AS revenue_share_pct,
    ROUND(100 * SUM(revenue) OVER (ORDER BY revenue DESC) / SUM(revenue) OVER (), 2) AS cumulative_revenue_share_pct
FROM vw_service_type_performance
ORDER BY revenue_rank;

-- Q07: Cancellation and no-show rate by centre
-- Business question: Where is demand being lost to cancellations and no-shows?
-- Technique: appointments LEFT JOIN work orders (completed jobs), conditional counts, RANK.
SELECT
    sc.center_name,
    COUNT(*)                                                                    AS appointments,
    COUNT(*) FILTER (WHERE a.status = 'Completed')                              AS completed,
    COUNT(*) FILTER (WHERE a.status = 'Cancelled')                              AS cancelled,
    COUNT(*) FILTER (WHERE a.status = 'No-Show')                                AS no_shows,
    ROUND(100.0 * COUNT(*) FILTER (WHERE a.status = 'Cancelled') / COUNT(*), 2) AS cancellation_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE a.status = 'No-Show')   / COUNT(*), 2) AS no_show_rate_pct,
    COUNT(*) FILTER (WHERE a.status = 'Completed' AND wo.work_order_id IS NULL) AS completed_without_work_order,
    RANK() OVER (ORDER BY COUNT(*) FILTER (WHERE a.status = 'Cancelled')::NUMERIC / COUNT(*) DESC) AS cancellation_rank
FROM appointments a
JOIN service_centers sc       ON sc.center_id = a.center_id
LEFT JOIN work_orders wo      ON wo.appointment_id = a.appointment_id
GROUP BY sc.center_name
ORDER BY cancellation_rank;

-- Q08: Cancellation rate by booking lead-time band
-- Business question: Do appointments booked far in advance get cancelled more often?
-- Technique: CASE to bucket lead days, conditional aggregation, ordered bands.
WITH banded AS (
    SELECT
        CASE
            WHEN scheduled_date - booking_date = 0   THEN '1. Same day'
            WHEN scheduled_date - booking_date <= 3  THEN '2. 1-3 days'
            WHEN scheduled_date - booking_date <= 7  THEN '3. 4-7 days'
            WHEN scheduled_date - booking_date <= 14 THEN '4. 8-14 days'
            ELSE                                          '5. 15+ days'
        END AS lead_time_band,
        status
    FROM appointments
)
SELECT
    lead_time_band,
    COUNT(*)                                                                    AS appointments,
    COUNT(*) FILTER (WHERE status = 'Cancelled')                                AS cancelled,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'Cancelled') / COUNT(*), 2)   AS cancellation_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'No-Show')   / COUNT(*), 2)   AS no_show_rate_pct,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                          AS share_of_bookings_pct
FROM banded
GROUP BY lead_time_band
ORDER BY lead_time_band;

-- Q09: Customer rating by service type
-- Business question: Which services delight or disappoint customers, and how complete is rating coverage?
-- Technique: LEFT JOIN feedback (not every job is rated), AVG / COUNT, CSAT, RANK.
SELECT
    wo.service_type,
    COUNT(*)                                                                   AS work_orders,
    COUNT(fb.rating)                                                           AS rated_jobs,
    ROUND(100.0 * COUNT(fb.rating) / COUNT(*), 1)                              AS rating_coverage_pct,
    ROUND(AVG(fb.rating), 3)                                                   AS avg_rating,
    ROUND(100.0 * AVG((fb.rating >= 4)::INT), 1)                               AS csat_pct,
    ROUND(100.0 * AVG((fb.rating <= 2)::INT), 1)                               AS low_rating_pct,
    RANK() OVER (ORDER BY AVG(fb.rating) DESC)                                 AS rating_rank
FROM work_orders wo
LEFT JOIN feedback fb ON fb.work_order_id = wo.work_order_id
GROUP BY wo.service_type
HAVING COUNT(fb.rating) > 0
ORDER BY rating_rank;

-- Q10: Highest-cost part categories
-- Business question: Which part categories consume the most parts spend, and do a few categories dominate (Pareto)?
-- Technique: INNER JOINs part_usage - parts - work_orders, SUM(quantity x unit_cost), cumulative share window.
WITH category_cost AS (
    SELECT
        p.part_category,
        COUNT(DISTINCT pu.work_order_id)    AS work_orders_using,
        SUM(pu.quantity)                    AS units_used,
        SUM(pu.quantity * p.unit_cost)      AS parts_spend
    FROM part_usage pu
    JOIN parts       p  ON p.part_id        = pu.part_id
    JOIN work_orders wo ON wo.work_order_id = pu.work_order_id
    GROUP BY p.part_category
)
SELECT
    part_category,
    work_orders_using,
    units_used,
    ROUND(parts_spend, 2)                                                         AS parts_spend,
    ROUND(parts_spend / work_orders_using, 2)                                     AS spend_per_work_order,
    ROUND(100 * parts_spend / SUM(parts_spend) OVER (), 2)                        AS share_of_spend_pct,
    ROUND(100 * SUM(parts_spend) OVER (ORDER BY parts_spend DESC) / SUM(parts_spend) OVER (), 2) AS cumulative_share_pct,
    RANK() OVER (ORDER BY parts_spend DESC)                                       AS spend_rank
FROM category_cost
ORDER BY spend_rank;

-- Q11: Estimated versus actual duration variance by service type
-- Business question: Where do technicians take longer than estimated, and how often is a job badly under-estimated?
-- Technique: CASE classification of variance, FILTER counts, view-based aggregation.
SELECT
    service_type,
    COUNT(*)                                                                      AS work_orders,
    ROUND(AVG(estimated_hours), 2)                                                AS avg_estimated_hours,
    ROUND(AVG(actual_hours), 2)                                                   AS avg_actual_hours,
    ROUND(AVG(duration_variance_hours), 3)                                        AS avg_variance_hours,
    ROUND(100.0 * AVG(duration_variance_hours / NULLIF(estimated_hours, 0)), 1)   AS avg_variance_pct_of_estimate,
    ROUND(100.0 * COUNT(*) FILTER (WHERE duration_variance_hours > 0.25 * estimated_hours) / COUNT(*), 1) AS jobs_over_estimate_by_25pct_pct,
    CASE
        WHEN AVG(duration_variance_hours) >= 0.5  THEN 'Under-estimated'
        WHEN AVG(duration_variance_hours) >= 0.2  THEN 'Slightly under-estimated'
        WHEN AVG(duration_variance_hours) > -0.2  THEN 'Accurate'
        ELSE                                           'Over-estimated'
    END                                                                           AS estimate_quality
FROM vw_work_order_enriched
GROUP BY service_type
ORDER BY avg_variance_hours DESC;

-- Q12: Repeat-visit rate by customer type
-- Business question: What share of customers come back for a second (or later) completed service?
-- Technique: customer-level view, ROLLUP for the overall figure, conditional counts.
SELECT
    COALESCE(customer_type, 'ALL CUSTOMERS')                                       AS customer_type,
    COUNT(*)                                                                       AS customers_served,
    COUNT(*) FILTER (WHERE is_repeat_customer)                                     AS repeat_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_repeat_customer) / COUNT(*), 2)        AS repeat_visit_rate_pct,
    ROUND(AVG(completed_visits), 2)                                                AS avg_visits_per_customer,
    ROUND(AVG(total_revenue), 2)                                                   AS avg_revenue_per_customer,
    ROUND(100.0 * SUM(comeback_visits) / NULLIF(SUM(completed_visits), 0), 2)      AS comeback_visits_pct_of_visits
FROM vw_customer_repeat
GROUP BY ROLLUP (customer_type)
ORDER BY (customer_type IS NULL), repeat_visit_rate_pct DESC;

-- Q13: Year-over-year comparison, January-September 2025 vs 2026
-- Business question: Is the same nine-month period of 2026 ahead of 2025 on volume, money and service quality?
-- Technique: CTE filtered on EXTRACT(MONTH), conditional aggregation by year, LATERAL unpivot, percentage change.
WITH ytd AS (
    SELECT
        service_year,
        COUNT(*)                         AS work_orders,
        SUM(revenue)                     AS revenue,
        SUM(profit)                      AS profit,
        SUM(profit) / SUM(revenue) * 100 AS profit_margin_pct,
        AVG(revenue)                     AS revenue_per_job,
        AVG(on_time_flag::INT) * 100     AS on_time_pct,
        AVG(turnaround_hours)            AS avg_turnaround_hours,
        AVG(rating)                      AS avg_rating,
        AVG(parts_delay_flag::INT) * 100 AS parts_delay_pct
    FROM vw_work_order_enriched
    WHERE EXTRACT(MONTH FROM check_in_time) <= 9
    GROUP BY service_year
),
appt AS (
    SELECT
        EXTRACT(YEAR FROM scheduled_date)::INT                AS service_year,
        COUNT(*)                                              AS appointments,
        100.0 * AVG((status = 'Cancelled')::INT)              AS cancellation_pct
    FROM appointments
    WHERE EXTRACT(MONTH FROM scheduled_date) <= 9
    GROUP BY EXTRACT(YEAR FROM scheduled_date)
),
by_year AS (
    SELECT y.service_year, y.work_orders, y.revenue, y.profit, y.profit_margin_pct, y.revenue_per_job,
           y.on_time_pct, y.avg_turnaround_hours, y.avg_rating, y.parts_delay_pct,
           a.appointments, a.cancellation_pct
    FROM ytd y
    JOIN appt a ON a.service_year = y.service_year
),
metrics AS (
    SELECT m.metric, m.sort_order,
           MAX(m.value) FILTER (WHERE b.service_year = 2025) AS jan_sep_2025,
           MAX(m.value) FILTER (WHERE b.service_year = 2026) AS jan_sep_2026
    FROM by_year b
    CROSS JOIN LATERAL (VALUES
        (1, 'Appointments',                 b.appointments::NUMERIC),
        (2, 'Completed work orders',        b.work_orders::NUMERIC),
        (3, 'Revenue (INR)',                b.revenue),
        (4, 'Profit (INR)',                 b.profit),
        (5, 'Profit margin (%)',            b.profit_margin_pct),
        (6, 'Revenue per job (INR)',        b.revenue_per_job),
        (7, 'On-time (%)',                  b.on_time_pct),
        (8, 'Avg turnaround (hours)',       b.avg_turnaround_hours),
        (9, 'Avg rating (1-5)',             b.avg_rating),
        (10,'Parts delay rate (%)',         b.parts_delay_pct),
        (11,'Cancellation rate (%)',        b.cancellation_pct)
    ) AS m(sort_order, metric, value)
    GROUP BY m.metric, m.sort_order
)
SELECT
    metric,
    ROUND(jan_sep_2025, 2)                                                     AS jan_sep_2025,
    ROUND(jan_sep_2026, 2)                                                     AS jan_sep_2026,
    ROUND(jan_sep_2026 - jan_sep_2025, 2)                                      AS abs_change,
    ROUND(100 * (jan_sep_2026 / NULLIF(jan_sep_2025, 0) - 1), 2)               AS pct_change
FROM metrics
ORDER BY sort_order;

-- Q14: Centre ranking with quartiles and performance category
-- Business question: How do centres compare on a balanced scorecard, and which need attention?
-- Technique: PERCENT_RANK per metric, composite score, NTILE quartile, CASE performance category.
WITH ranked AS (
    SELECT
        center_name, work_orders, revenue, profit_margin, on_time_rate, avg_turnaround_hours,
        avg_rating, comeback_rate, utilisation,
        PERCENT_RANK() OVER (ORDER BY on_time_rate)          AS p_on_time,
        PERCENT_RANK() OVER (ORDER BY avg_rating)            AS p_rating,
        PERCENT_RANK() OVER (ORDER BY profit_margin)         AS p_margin,
        PERCENT_RANK() OVER (ORDER BY comeback_rate DESC)    AS p_quality,      -- fewer comebacks is better
        PERCENT_RANK() OVER (ORDER BY avg_turnaround_hours DESC) AS p_speed     -- shorter turnaround is better
    FROM vw_center_performance
),
scored AS (
    SELECT *, ((p_on_time + p_rating + p_margin + p_quality + p_speed) / 5.0)::NUMERIC AS composite_score
    FROM ranked
)
SELECT
    RANK() OVER (ORDER BY composite_score DESC)                  AS overall_rank,
    center_name,
    ROUND(composite_score, 3)                                    AS composite_score,
    NTILE(4) OVER (ORDER BY composite_score DESC)                AS quartile,
    CASE
        WHEN composite_score >= 0.70 THEN 'Leader'
        WHEN composite_score >= 0.45 THEN 'Solid'
        WHEN composite_score >= 0.25 THEN 'Watch'
        ELSE                              'Needs attention'
    END                                                          AS performance_category,
    ROUND(100 * on_time_rate, 2)                                 AS on_time_pct,
    ROUND(avg_rating, 3)                                         AS avg_rating,
    ROUND(100 * profit_margin, 2)                                AS profit_margin_pct,
    ROUND(100 * comeback_rate, 2)                                AS comeback_rate_pct,
    avg_turnaround_hours,
    ROUND(100 * utilisation, 1)                                  AS utilisation_pct
FROM scored
ORDER BY overall_rank, center_name;

-- Q15: Impact of parts delays on on-time completion and customer rating
-- Business question: How much do parts waits hurt promise-keeping, turnaround and satisfaction?
-- Technique: CASE bands on parts_wait_hours, rating averages from the view, delta vs the no-wait baseline via FIRST_VALUE.
WITH banded AS (
    SELECT
        CASE
            WHEN parts_wait_hours = 0   THEN '1. No parts wait'
            WHEN parts_wait_hours <= 72 THEN '2. Up to 3 days'
            WHEN parts_wait_hours <= 168 THEN '3. 3 to 7 days'
            ELSE                             '4. Over 7 days'
        END AS parts_wait_band,
        on_time_flag, turnaround_hours, late_hours, rating, cost_variance
    FROM vw_work_order_enriched
)
SELECT
    parts_wait_band,
    COUNT(*)                                                      AS work_orders,
    ROUND(100.0 * AVG(on_time_flag::INT), 2)                      AS on_time_pct,
    ROUND(100.0 * AVG(on_time_flag::INT) - FIRST_VALUE(100.0 * AVG(on_time_flag::INT)) OVER (ORDER BY parts_wait_band), 2) AS on_time_pts_vs_no_wait,
    ROUND(AVG(turnaround_hours), 2)                               AS avg_turnaround_hours,
    ROUND(AVG(rating), 3)                                         AS avg_rating,
    ROUND(AVG(rating) - FIRST_VALUE(AVG(rating)) OVER (ORDER BY parts_wait_band), 3) AS rating_vs_no_wait,
    COUNT(rating)                                                 AS rated_jobs,
    ROUND(AVG(cost_variance), 2)                                  AS avg_cost_variance
FROM banded
GROUP BY parts_wait_band
ORDER BY parts_wait_band;

-- Q16: Technician skill level versus comeback rate and quality
-- Business question: Do more experienced technicians produce fewer comebacks and rework?
-- Technique: INNER JOIN technicians, CASE sort key, rates via AVG of booleans, jobs without a technician excluded.
SELECT
    t.skill_level,
    COUNT(DISTINCT t.technician_id)                                          AS technicians,
    COUNT(*)                                                                 AS jobs,
    ROUND(100.0 * AVG(w.caused_comeback::INT), 2)                            AS comeback_rate_pct,
    ROUND(100.0 * AVG(w.qc_passed_first_time::INT), 2)                       AS qc_first_pass_pct,
    ROUND(AVG(w.duration_variance_hours), 3)                                 AS avg_duration_variance_hours,
    ROUND(100.0 * AVG(w.on_time_flag::INT), 2)                               AS on_time_pct,
    ROUND(AVG(w.rating), 3)                                                  AS avg_rating,
    ROUND(AVG(w.profit), 2)                                                  AS avg_profit_per_job
FROM vw_work_order_enriched w
JOIN technicians t ON t.technician_id = w.technician_id
GROUP BY t.skill_level
ORDER BY CASE t.skill_level WHEN 'Junior' THEN 1 WHEN 'Mid' THEN 2 WHEN 'Senior' THEN 3 ELSE 4 END;

-- Q17: Weekday load versus customer wait time
-- Business question: Does a busier weekday mean longer waits before work starts?
-- Technique: EXTRACT(ISODOW), distinct-day counts, per-day load, window rank of load and wait, CORR across weekdays.
WITH daily AS (
    SELECT
        EXTRACT(ISODOW FROM check_in_time)::INT AS iso_weekday,
        check_in_time::DATE                     AS service_date,
        COUNT(*)                                AS jobs,
        AVG(wait_hours)                         AS avg_wait_hours
    FROM vw_work_order_enriched
    GROUP BY EXTRACT(ISODOW FROM check_in_time), check_in_time::DATE
),
weekday AS (
    SELECT
        iso_weekday,
        COUNT(*)                         AS open_days,
        SUM(jobs)                        AS work_orders,
        AVG(jobs)                        AS avg_jobs_per_day,
        AVG(avg_wait_hours)              AS avg_wait_hours
    FROM daily
    GROUP BY iso_weekday
)
SELECT
    TRIM(TO_CHAR(DATE '2024-12-29' + iso_weekday, 'Day'))                  AS weekday,
    open_days,
    work_orders,
    ROUND(avg_jobs_per_day, 1)                                             AS avg_jobs_per_day,
    ROUND(avg_wait_hours, 2)                                               AS avg_wait_hours,
    RANK() OVER (ORDER BY avg_jobs_per_day DESC)                           AS load_rank,
    RANK() OVER (ORDER BY avg_wait_hours DESC)                             AS wait_rank,
    ROUND((CORR(avg_jobs_per_day, avg_wait_hours) OVER ())::NUMERIC, 3)    AS corr_load_vs_wait_across_weekdays
FROM weekday
ORDER BY iso_weekday;

-- Q18: Cost variance (actual vs estimated) by service type and billing type
-- Business question: Where do actual costs overrun the estimate, and which billing categories carry the overruns?
-- Technique: GROUPING SETS for two cuts in one pass, GROUPING() label, overrun share, rank within cut.
SELECT
    CASE WHEN GROUPING(service_type) = 0 THEN 'Service type' ELSE 'Billing type' END AS cut,
    COALESCE(service_type, billing_type)                                       AS segment,
    COUNT(*)                                                                   AS work_orders,
    ROUND(SUM(cost_variance), 2)                                               AS total_cost_variance,
    ROUND(AVG(cost_variance), 2)                                               AS avg_cost_variance,
    ROUND(100.0 * AVG(cost_overrun_flag::INT), 2)                              AS overrun_rate_pct,
    ROUND(100.0 * SUM(cost_variance) / NULLIF(SUM(estimated_cost), 0), 2)      AS variance_pct_of_estimate,
    RANK() OVER (PARTITION BY GROUPING(service_type) ORDER BY SUM(cost_variance) DESC) AS rank_in_cut
FROM vw_work_order_enriched
GROUP BY GROUPING SETS ((service_type), (billing_type))
ORDER BY cut DESC, rank_in_cut;

-- Q19: Vehicle model profile including vehicles that were never serviced
-- Business question: How does service demand, revenue and quality differ by model, and how much of the base never visits?
-- Technique: LEFT JOIN from vehicles (anti-join counting), two-level aggregation in CTEs, CASE vehicle-age band.
WITH vehicle_activity AS (
    SELECT
        v.vehicle_id,
        v.model,
        COUNT(w.work_order_id)    AS visits,
        COALESCE(SUM(w.revenue), 0) AS revenue,
        COALESCE(SUM(w.profit), 0)  AS profit
    FROM vehicles v
    LEFT JOIN vw_work_order_enriched w ON w.vehicle_id = v.vehicle_id
    GROUP BY v.vehicle_id, v.model
),
model_rollup AS (
    SELECT
        model,
        COUNT(*)                                       AS vehicles_in_base,
        COUNT(*) FILTER (WHERE visits = 0)             AS never_serviced,
        SUM(visits)                                    AS visits,
        SUM(revenue)                                   AS revenue,
        SUM(profit)                                    AS profit
    FROM vehicle_activity
    GROUP BY model
),
model_quality AS (
    SELECT
        model,
        AVG(rating)                                    AS avg_rating,
        AVG(caused_comeback::INT)                      AS comeback_rate,
        AVG(CASE WHEN (service_date - purchase_date) / 365.25 >= 2 THEN 1.0 ELSE 0.0 END) AS share_jobs_on_vehicles_2plus_years_old
    FROM vw_work_order_enriched
    GROUP BY model
)
SELECT
    r.model,
    r.vehicles_in_base,
    r.never_serviced,
    ROUND(100.0 * r.never_serviced / r.vehicles_in_base, 1)   AS never_serviced_pct,
    r.visits,
    ROUND(r.visits::NUMERIC / r.vehicles_in_base, 2)          AS visits_per_vehicle,
    ROUND(r.revenue / r.vehicles_in_base, 2)                  AS revenue_per_vehicle,
    ROUND(100 * r.profit / NULLIF(r.revenue, 0), 2)           AS profit_margin_pct,
    ROUND(q.avg_rating, 3)                                    AS avg_rating,
    ROUND(100 * q.comeback_rate, 2)                           AS comeback_rate_pct,
    ROUND(100 * q.share_jobs_on_vehicles_2plus_years_old, 1)  AS jobs_on_2plus_year_old_vehicles_pct
FROM model_rollup r
JOIN model_quality q USING (model)
ORDER BY r.revenue DESC;

-- Q20: Centre utilisation by month with a 3-month moving average
-- Business question: Is capacity being used evenly through the year, and which centres run hot?
-- Technique: generate_series for Mon-Sat working days per month, JOIN to technician hours, moving-average window.
WITH months AS (
    SELECT
        DATE_TRUNC('month', d)::DATE                                  AS month_start,
        COUNT(*) FILTER (WHERE EXTRACT(ISODOW FROM d) <= 6)           AS working_days
    FROM generate_series(DATE '2025-01-01', DATE '2026-09-30', INTERVAL '1 day') AS d
    GROUP BY DATE_TRUNC('month', d)
),
centre_techs AS (
    SELECT center_id, COUNT(*) AS technicians FROM technicians GROUP BY center_id
),
centre_hours AS (
    SELECT
        t.center_id,
        DATE_TRUNC('month', wo.check_in_time)::DATE AS month_start,
        SUM(wo.actual_hours)                        AS service_hours
    FROM work_orders wo
    JOIN technicians t ON t.technician_id = wo.technician_id
    GROUP BY t.center_id, DATE_TRUNC('month', wo.check_in_time)
),
monthly AS (
    SELECT
        sc.center_name,
        m.month_start,
        COALESCE(h.service_hours, 0)                                                 AS service_hours,
        ct.technicians * m.working_days * 7.0                                        AS available_hours
    FROM service_centers sc
    JOIN centre_techs ct   ON ct.center_id = sc.center_id
    CROSS JOIN months m
    LEFT JOIN centre_hours h ON h.center_id = sc.center_id AND h.month_start = m.month_start
)
SELECT
    center_name,
    TO_CHAR(month_start, 'YYYY-MM')                                                  AS year_month,
    ROUND(service_hours, 1)                                                          AS service_hours,
    ROUND(available_hours, 1)                                                        AS available_hours,
    ROUND(100 * service_hours / available_hours, 1)                                  AS utilisation_pct,
    ROUND(100 * AVG(service_hours / available_hours)
          OVER (PARTITION BY center_name ORDER BY month_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) AS utilisation_3m_avg_pct
FROM monthly
ORDER BY center_name, month_start;

-- Q21: Customer revenue concentration by decile
-- Business question: How much of revenue comes from the top 10 percent of customers?
-- Technique: NTILE(10) over customer revenue, decile roll-up, cumulative share.
WITH customer_rev AS (
    SELECT
        customer_id,
        total_revenue,
        completed_visits,
        NTILE(10) OVER (ORDER BY total_revenue DESC) AS revenue_decile
    FROM vw_customer_repeat
),
deciles AS (
    SELECT
        revenue_decile,
        COUNT(*)              AS customers,
        SUM(total_revenue)    AS revenue,
        AVG(completed_visits) AS avg_visits
    FROM customer_rev
    GROUP BY revenue_decile
)
SELECT
    revenue_decile,
    customers,
    ROUND(revenue, 2)                                                        AS revenue,
    ROUND(avg_visits, 2)                                                     AS avg_visits,
    ROUND(100 * revenue / SUM(revenue) OVER (), 2)                           AS revenue_share_pct,
    ROUND(100 * SUM(revenue) OVER (ORDER BY revenue_decile) / SUM(revenue) OVER (), 2) AS cumulative_share_pct
FROM deciles
ORDER BY revenue_decile;
