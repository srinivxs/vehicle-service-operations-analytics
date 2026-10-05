-- =============================================================================
-- views.sql  |  Reusable KPI views for the Vehicle Service Operations project
-- Run after schema.sql and the CSV load (python -m src.load_to_db does all three).
--
-- Conventions
--   * Ratios are stored as fractions 0-1 (names end in _rate / _share / utilisation);
--     multiply by 100 for percentages. cost_variance_pct is also a fraction.
--   * Money in INR (NUMERIC). Hours in decimal hours.
--   * KPI definitions match the canonical list used by the Python pipeline
--     (data/cleaned/fact_service.csv) and the dashboard documentation.
--   * Business constants mirrored from src/config.py: period 2025-01-01..2026-09-30,
--     shop open Mon-Sat, 7 productive hours/day, comeback window 30 days.
-- =============================================================================

SET search_path TO service_ops, public;

-- -----------------------------------------------------------------------------
-- vw_period_calendar : single row with the reporting window and capacity basis
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_period_calendar AS
SELECT
    DATE '2025-01-01'                              AS period_start,
    DATE '2026-09-30'                              AS period_end,
    (SELECT COUNT(*)
       FROM generate_series(DATE '2025-01-01', DATE '2026-09-30', INTERVAL '1 day') AS d
      WHERE EXTRACT(ISODOW FROM d) <= 6)::INT     AS working_days,          -- Mon-Sat
    7.0::NUMERIC                                   AS productive_hours_per_day;

COMMENT ON VIEW vw_period_calendar IS 'Reporting period, Mon-Sat working-day count and productive hours per technician-day (KPI 9 denominator).';

-- -----------------------------------------------------------------------------
-- vw_work_order_enriched : one row per work order, all joins + derived metrics
--   Layer 1 (base)     : INNER/LEFT JOINs across service, vehicle, customer, centre,
--                        technician, financial and feedback tables
--   Layer 2 (windowed) : LAG/LEAD/ROW_NUMBER over vehicle + service_type history
--   Layer 3 (final)    : derived KPI columns
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_work_order_enriched AS
WITH base AS (
    SELECT
        wo.work_order_id, wo.appointment_id, wo.technician_id, wo.service_type,
        wo.check_in_time, wo.start_time, wo.end_time, wo.promised_ready_time,
        wo.estimated_hours, wo.actual_hours, wo.parts_wait_hours, wo.odometer_km,
        wo.additional_work_found, wo.qc_passed_first_time,
        a.vehicle_id, a.center_id, a.booking_channel, a.scheduled_date,
        v.customer_id, v.model, v.variant, v.vehicle_category, v.model_year, v.purchase_date,
        c.customer_type, c.region AS customer_region,
        sc.center_name, sc.city, sc.region,
        t.skill_level, t.years_experience,
        f.billing_type, f.estimated_cost, f.labor_cost, f.parts_cost, f.revenue,
        fb.rating, fb.feedback_category
    FROM work_orders        wo
    JOIN appointments       a  ON a.appointment_id = wo.appointment_id          -- INNER: every job has a booking
    JOIN vehicles           v  ON v.vehicle_id     = a.vehicle_id
    JOIN customers          c  ON c.customer_id    = v.customer_id
    JOIN service_centers    sc ON sc.center_id     = a.center_id
    LEFT JOIN technicians   t  ON t.technician_id  = wo.technician_id          -- LEFT: technician may be unassigned
    LEFT JOIN financials    f  ON f.work_order_id  = wo.work_order_id
    LEFT JOIN feedback      fb ON fb.work_order_id = wo.work_order_id           -- LEFT: not every job is rated
),
windowed AS (
    SELECT
        b.*,
        LAG(b.end_time)       OVER w_hist AS prev_same_service_end,
        LEAD(b.check_in_time) OVER w_hist AS next_same_service_check_in,
        ROW_NUMBER()          OVER (PARTITION BY b.customer_id ORDER BY b.check_in_time, b.work_order_id)
                                          AS customer_visit_number
    FROM base b
    WINDOW w_hist AS (PARTITION BY b.vehicle_id, b.service_type ORDER BY b.check_in_time, b.work_order_id)
)
SELECT
    w.work_order_id, w.appointment_id, w.vehicle_id, w.customer_id, w.center_id, w.technician_id,
    w.service_type, w.booking_channel,
    w.model, w.variant, w.vehicle_category, w.model_year, w.purchase_date,
    w.customer_type, w.customer_region,
    w.center_name, w.city, w.region,
    w.skill_level, w.years_experience,
    w.check_in_time, w.start_time, w.end_time, w.promised_ready_time,
    w.check_in_time::DATE                                   AS service_date,
    DATE_TRUNC('month', w.check_in_time)::DATE              AS month_start,
    TO_CHAR(w.check_in_time, 'YYYY-MM')                     AS year_month,
    EXTRACT(YEAR  FROM w.check_in_time)::INT                AS service_year,
    EXTRACT(MONTH FROM w.check_in_time)::INT                AS service_month,
    EXTRACT(ISODOW FROM w.check_in_time)::INT               AS iso_weekday,
    TO_CHAR(w.check_in_time, 'FMDay')                       AS weekday_name,
    w.estimated_hours, w.actual_hours, w.parts_wait_hours, w.odometer_km,
    w.additional_work_found, w.qc_passed_first_time,
    w.billing_type, w.estimated_cost, w.labor_cost, w.parts_cost, w.revenue,
    w.rating, w.feedback_category,
    -- timing KPIs (16: wait, 6: turnaround, 5: on-time)
    ROUND((EXTRACT(EPOCH FROM (w.start_time - w.check_in_time)) / 3600)::NUMERIC, 2)        AS wait_hours,
    ROUND((EXTRACT(EPOCH FROM (w.end_time   - w.check_in_time)) / 3600)::NUMERIC, 2)        AS turnaround_hours,
    ROUND(GREATEST(EXTRACT(EPOCH FROM (w.end_time - w.promised_ready_time)) / 3600, 0)::NUMERIC, 2) AS late_hours,
    (w.end_time <= w.promised_ready_time)                                                   AS on_time_flag,
    -- duration and parts KPIs (13, 14)
    ROUND(w.actual_hours - w.estimated_hours, 2)                                            AS duration_variance_hours,
    (w.parts_wait_hours > 0)                                                                AS parts_delay_flag,
    -- financial KPIs (2, 3, 7)
    ROUND(w.labor_cost + w.parts_cost, 2)                                                   AS total_cost,
    ROUND(w.revenue - (w.labor_cost + w.parts_cost), 2)                                     AS profit,
    ROUND((w.labor_cost + w.parts_cost) - w.estimated_cost, 2)                              AS cost_variance,
    ROUND(((w.labor_cost + w.parts_cost) - w.estimated_cost) / NULLIF(w.estimated_cost, 0), 4) AS cost_variance_pct,
    COALESCE(ROUND(((w.labor_cost + w.parts_cost) - w.estimated_cost) / NULLIF(w.estimated_cost, 0), 4) > 0.10, FALSE)
                                                                                            AS cost_overrun_flag,
    -- comeback / repeat history (12): 30-day window per vehicle + service type
    w.prev_same_service_end,
    w.next_same_service_check_in,
    FLOOR(EXTRACT(EPOCH FROM (w.check_in_time - w.prev_same_service_end)) / 86400)::INT     AS days_since_same_service,
    COALESCE(FLOOR(EXTRACT(EPOCH FROM (w.check_in_time - w.prev_same_service_end)) / 86400) <= 30, FALSE)
                                                                                            AS is_comeback,         -- this job is the return visit
    COALESCE(FLOOR(EXTRACT(EPOCH FROM (w.next_same_service_check_in - w.end_time)) / 86400) <= 30, FALSE)
                                                                                            AS caused_comeback,     -- this job was followed by a return visit
    w.customer_visit_number::INT                                                            AS customer_visit_number
FROM windowed w;

COMMENT ON VIEW vw_work_order_enriched IS 'Grain: work order. All joins plus derived KPIs (wait, turnaround, on-time, variances, profit, comeback flags).';

-- -----------------------------------------------------------------------------
-- vw_appointment_enriched : one row per appointment with lead-time band and flags
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_appointment_enriched AS
SELECT
    a.appointment_id, a.vehicle_id, a.center_id, sc.center_name, sc.city, sc.region,
    v.customer_id, v.model, c.customer_type,
    a.booking_date, a.scheduled_date, a.scheduled_slot,
    a.booking_channel, a.requested_service_type, a.status, a.cancellation_reason,
    (a.scheduled_date - a.booking_date)                       AS lead_days,
    CASE
        WHEN a.scheduled_date - a.booking_date = 0  THEN 'Same day'
        WHEN a.scheduled_date - a.booking_date <= 3 THEN '1-3 days'
        WHEN a.scheduled_date - a.booking_date <= 7 THEN '4-7 days'
        WHEN a.scheduled_date - a.booking_date <= 14 THEN '8-14 days'
        ELSE '15+ days'
    END                                                       AS lead_time_band,
    TO_CHAR(a.scheduled_date, 'YYYY-MM')                      AS year_month,
    DATE_TRUNC('month', a.scheduled_date)::DATE               AS month_start,
    EXTRACT(ISODOW FROM a.scheduled_date)::INT                AS iso_weekday,
    TO_CHAR(a.scheduled_date, 'FMDay')                        AS weekday_name,
    (a.status = 'Cancelled')                                  AS is_cancelled,
    (a.status = 'No-Show')                                    AS is_no_show,
    (a.status = 'Completed')                                  AS is_completed
FROM appointments a
JOIN service_centers sc ON sc.center_id = a.center_id
JOIN vehicles        v  ON v.vehicle_id = a.vehicle_id
JOIN customers       c  ON c.customer_id = v.customer_id;

COMMENT ON VIEW vw_appointment_enriched IS 'Grain: appointment. Adds lead_days, lead_time_band, weekday and status flags.';

-- -----------------------------------------------------------------------------
-- vw_monthly_financials : revenue / cost / profit trend with MoM growth (KPIs 1-5)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_monthly_financials AS
WITH monthly AS (
    SELECT
        month_start, year_month, service_year, service_month,
        COUNT(*)                                   AS work_orders,
        SUM(revenue)                               AS revenue,
        SUM(total_cost)                            AS total_cost,
        SUM(profit)                                AS profit,
        AVG(on_time_flag::INT)                     AS on_time_rate,
        AVG(turnaround_hours)                      AS avg_turnaround_hours,
        AVG(rating)                                AS avg_rating
    FROM vw_work_order_enriched
    GROUP BY month_start, year_month, service_year, service_month
)
SELECT
    m.*,
    ROUND(m.profit / NULLIF(m.revenue, 0), 4)                      AS profit_margin,
    ROUND(m.total_cost / NULLIF(m.work_orders, 0), 2)              AS avg_service_cost,
    ROUND(m.revenue / NULLIF(LAG(m.revenue) OVER (ORDER BY m.month_start), 0) - 1, 4) AS revenue_mom_growth,
    ROUND(m.profit  / NULLIF(LAG(m.profit)  OVER (ORDER BY m.month_start), 0) - 1, 4) AS profit_mom_growth
FROM monthly m;

COMMENT ON VIEW vw_monthly_financials IS 'Grain: calendar month (by check-in). Revenue, cost, profit, margin, MoM growth, service quality.';

-- -----------------------------------------------------------------------------
-- vw_technician_utilisation : per technician over the full period (KPI 9)
--   utilisation = SUM(actual_hours) / (Mon-Sat working days x 7 productive hours)
--   LEFT JOIN so technicians with no work are still listed (utilisation 0).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_technician_utilisation AS
SELECT
    t.technician_id, t.center_id, sc.center_name, t.skill_level, t.years_experience,
    COUNT(w.work_order_id)                                            AS jobs,
    COALESCE(SUM(w.actual_hours), 0)                                  AS service_hours,
    pc.working_days,
    pc.working_days * pc.productive_hours_per_day                     AS available_hours,
    ROUND(COALESCE(SUM(w.actual_hours), 0) / (pc.working_days * pc.productive_hours_per_day), 4) AS utilisation,
    ROUND(AVG(w.on_time_flag::INT), 4)                                AS on_time_rate,
    ROUND(AVG(w.qc_passed_first_time::INT), 4)                        AS qc_first_pass_rate,
    COUNT(*) FILTER (WHERE w.caused_comeback)                         AS comebacks_caused,
    ROUND(AVG(w.caused_comeback::INT), 4)                             AS comeback_rate,
    ROUND(AVG(w.duration_variance_hours), 3)                          AS avg_duration_variance_hours,
    ROUND(AVG(w.rating), 3)                                           AS avg_rating
FROM technicians t
JOIN service_centers sc ON sc.center_id = t.center_id
CROSS JOIN vw_period_calendar pc
LEFT JOIN vw_work_order_enriched w ON w.technician_id = t.technician_id
GROUP BY t.technician_id, t.center_id, sc.center_name, t.skill_level, t.years_experience,
         pc.working_days, pc.productive_hours_per_day;

COMMENT ON VIEW vw_technician_utilisation IS 'Grain: technician. Jobs, hours, utilisation, QC first-pass and comeback rates. Work orders without a technician are excluded.';

-- -----------------------------------------------------------------------------
-- vw_center_performance : per service centre scorecard (KPIs 1-16)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_center_performance AS
WITH jobs AS (
    SELECT
        center_id,
        COUNT(*)                                       AS work_orders,
        SUM(revenue)                                   AS revenue,
        SUM(total_cost)                                AS total_cost,
        SUM(profit)                                    AS profit,
        AVG(turnaround_hours)                          AS avg_turnaround_hours,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY turnaround_hours) AS median_turnaround_hours,
        AVG(on_time_flag::INT)                         AS on_time_rate,
        AVG(wait_hours)                                AS avg_wait_hours,
        AVG(duration_variance_hours)                   AS avg_duration_variance_hours,
        AVG(cost_overrun_flag::INT)                    AS cost_overrun_rate,
        AVG(parts_delay_flag::INT)                     AS parts_delay_rate,
        AVG(qc_passed_first_time::INT)                 AS qc_first_pass_rate,
        AVG(caused_comeback::INT)                      AS comeback_rate,
        AVG(rating)                                    AS avg_rating,
        AVG((rating >= 4)::INT)                        AS csat_rate
    FROM vw_work_order_enriched
    GROUP BY center_id
),
appts AS (
    SELECT
        center_id,
        COUNT(*)                                       AS appointments,
        AVG(is_cancelled::INT)                         AS cancellation_rate,
        AVG(is_no_show::INT)                           AS no_show_rate
    FROM vw_appointment_enriched
    GROUP BY center_id
),
cap AS (
    SELECT
        tu.center_id,
        COUNT(*)                                       AS technicians,
        SUM(tu.service_hours)                          AS technician_hours,
        SUM(tu.available_hours)                        AS available_hours
    FROM vw_technician_utilisation tu
    GROUP BY tu.center_id
)
SELECT
    sc.center_id, sc.center_name, sc.city, sc.region, sc.service_bays, sc.daily_job_capacity,
    cap.technicians,
    j.work_orders,
    a.appointments,
    ROUND(j.revenue, 2)                         AS revenue,
    ROUND(j.total_cost, 2)                      AS total_cost,
    ROUND(j.profit, 2)                          AS profit,
    ROUND(j.profit / NULLIF(j.revenue, 0), 4)   AS profit_margin,
    ROUND(j.total_cost / NULLIF(j.work_orders, 0), 2) AS avg_service_cost,
    ROUND(j.avg_turnaround_hours, 2)            AS avg_turnaround_hours,
    ROUND(j.median_turnaround_hours::NUMERIC, 2) AS median_turnaround_hours,
    ROUND(j.on_time_rate, 4)                    AS on_time_rate,
    ROUND(j.avg_wait_hours, 2)                  AS avg_wait_hours,
    ROUND(j.avg_duration_variance_hours, 3)     AS avg_duration_variance_hours,
    ROUND(j.cost_overrun_rate, 4)               AS cost_overrun_rate,
    ROUND(j.parts_delay_rate, 4)                AS parts_delay_rate,
    ROUND(j.qc_first_pass_rate, 4)              AS qc_first_pass_rate,
    ROUND(j.comeback_rate, 4)                   AS comeback_rate,
    ROUND(j.avg_rating, 3)                      AS avg_rating,
    ROUND(j.csat_rate, 4)                       AS csat_rate,
    ROUND(a.cancellation_rate, 4)               AS cancellation_rate,
    ROUND(a.no_show_rate, 4)                    AS no_show_rate,
    ROUND(cap.technician_hours / NULLIF(cap.available_hours, 0), 4) AS utilisation
FROM service_centers sc
LEFT JOIN jobs  j   ON j.center_id   = sc.center_id
LEFT JOIN appts a   ON a.center_id   = sc.center_id
LEFT JOIN cap       ON cap.center_id = sc.center_id;

COMMENT ON VIEW vw_center_performance IS 'Grain: service centre. Financials, turnaround, on-time, quality, cancellation and utilisation scorecard.';

-- -----------------------------------------------------------------------------
-- vw_service_type_performance : per service type
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_service_type_performance AS
SELECT
    service_type,
    COUNT(*)                                              AS work_orders,
    ROUND(SUM(revenue), 2)                                AS revenue,
    ROUND(SUM(total_cost), 2)                             AS total_cost,
    ROUND(SUM(profit), 2)                                 AS profit,
    ROUND(SUM(profit) / NULLIF(SUM(revenue), 0), 4)       AS profit_margin,
    ROUND(SUM(total_cost) / COUNT(*), 2)                  AS avg_service_cost,
    ROUND(AVG(turnaround_hours), 2)                       AS avg_turnaround_hours,
    ROUND(AVG(on_time_flag::INT), 4)                      AS on_time_rate,
    ROUND(AVG(duration_variance_hours), 3)                AS avg_duration_variance_hours,
    ROUND(AVG(cost_variance), 2)                          AS avg_cost_variance,
    ROUND(AVG(cost_overrun_flag::INT), 4)                 AS cost_overrun_rate,
    ROUND(AVG(parts_delay_flag::INT), 4)                  AS parts_delay_rate,
    ROUND(AVG(qc_passed_first_time::INT), 4)              AS qc_first_pass_rate,
    ROUND(AVG(caused_comeback::INT), 4)                   AS comeback_rate,
    ROUND(AVG(rating), 3)                                 AS avg_rating
FROM vw_work_order_enriched
GROUP BY service_type;

COMMENT ON VIEW vw_service_type_performance IS 'Grain: service type. Volume, financials, timing, quality and satisfaction.';

-- -----------------------------------------------------------------------------
-- vw_appointment_funnel : demand funnel per month and centre (KPI 8)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_appointment_funnel AS
SELECT
    month_start, year_month, center_id, center_name,
    COUNT(*)                                          AS appointments,
    COUNT(*) FILTER (WHERE is_completed)              AS completed,
    COUNT(*) FILTER (WHERE is_cancelled)              AS cancelled,
    COUNT(*) FILTER (WHERE is_no_show)                AS no_shows,
    ROUND(AVG(is_completed::INT), 4)                  AS completion_rate,
    ROUND(AVG(is_cancelled::INT), 4)                  AS cancellation_rate,
    ROUND(AVG(is_no_show::INT), 4)                    AS no_show_rate,
    ROUND(AVG(lead_days), 2)                          AS avg_lead_days
FROM vw_appointment_enriched
GROUP BY month_start, year_month, center_id, center_name;

COMMENT ON VIEW vw_appointment_funnel IS 'Grain: month x centre. Appointment outcomes and cancellation / no-show rates.';

-- -----------------------------------------------------------------------------
-- vw_customer_repeat : customer visit history (KPI 11)
--   Only customers with >= 1 completed work order appear (the KPI denominator).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_customer_repeat AS
SELECT
    w.customer_id,
    w.customer_type,
    w.customer_region,
    COUNT(*)                                        AS completed_visits,
    COUNT(DISTINCT w.vehicle_id)                    AS vehicles_serviced,
    MIN(w.service_date)                             AS first_visit_date,
    MAX(w.service_date)                             AS last_visit_date,
    MAX(w.service_date) - MIN(w.service_date)       AS tenure_days,
    ROUND(SUM(w.revenue), 2)                        AS total_revenue,
    ROUND(AVG(w.rating), 3)                         AS avg_rating,
    COUNT(*) FILTER (WHERE w.is_comeback)           AS comeback_visits,
    (COUNT(*) >= 2)                                 AS is_repeat_customer
FROM vw_work_order_enriched w
GROUP BY w.customer_id, w.customer_type, w.customer_region;

COMMENT ON VIEW vw_customer_repeat IS 'Grain: customer with >= 1 completed work order. is_repeat_customer = >= 2 completed work orders.';

-- -----------------------------------------------------------------------------
-- vw_kpi_summary : single-row headline KPIs (numbers in the spec KPI framework)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_kpi_summary AS
WITH w AS (
    SELECT
        COUNT(*)                                                     AS work_orders,
        SUM(revenue)                                                 AS total_revenue,
        SUM(total_cost)                                              AS total_cost,
        SUM(profit)                                                  AS profit,
        AVG(on_time_flag::INT)                                       AS on_time_rate,
        AVG(turnaround_hours)                                        AS avg_turnaround_hours,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY turnaround_hours) AS median_turnaround_hours,
        AVG(wait_hours)                                              AS avg_wait_hours,
        SUM(cost_variance)                                           AS total_cost_variance,
        AVG(cost_variance)                                           AS avg_cost_variance,
        AVG(cost_overrun_flag::INT)                                  AS cost_overrun_rate,
        AVG(duration_variance_hours)                                 AS avg_duration_variance_hours,
        AVG(parts_delay_flag::INT)                                   AS parts_delay_rate,
        AVG(qc_passed_first_time::INT)                               AS qc_first_pass_rate,
        AVG(caused_comeback::INT)                                    AS comeback_rate,
        AVG(rating)                                                  AS avg_rating,
        AVG((rating >= 4)::INT)                                      AS csat_rate,
        COUNT(rating)                                                AS rated_work_orders
    FROM vw_work_order_enriched
),
a AS (
    SELECT COUNT(*)                          AS appointments,
           COUNT(*) FILTER (WHERE is_cancelled) AS cancelled,
           COUNT(*) FILTER (WHERE is_no_show)   AS no_shows
    FROM vw_appointment_enriched
),
r AS (
    SELECT COUNT(*)                                          AS customers_served,
           COUNT(*) FILTER (WHERE is_repeat_customer)        AS repeat_customers
    FROM vw_customer_repeat
),
u AS (
    SELECT SUM(service_hours) AS technician_hours, SUM(available_hours) AS available_hours
    FROM vw_technician_utilisation
)
SELECT
    w.work_orders,
    ROUND(w.total_revenue, 2)                                        AS total_revenue,
    ROUND(w.total_cost, 2)                                           AS total_cost,
    ROUND(w.profit, 2)                                               AS profit,
    ROUND(w.profit / NULLIF(w.total_revenue, 0), 4)                  AS profit_margin,
    ROUND(w.total_cost / NULLIF(w.work_orders, 0), 2)                AS avg_service_cost,
    ROUND(w.on_time_rate, 4)                                         AS on_time_rate,
    ROUND(w.avg_turnaround_hours, 3)                                 AS avg_turnaround_hours,
    ROUND(w.median_turnaround_hours::NUMERIC, 3)                     AS median_turnaround_hours,
    ROUND(w.avg_wait_hours, 3)                                       AS avg_wait_hours,
    ROUND(w.total_cost_variance, 2)                                  AS total_cost_variance,
    ROUND(w.avg_cost_variance, 2)                                    AS avg_cost_variance,
    ROUND(w.cost_overrun_rate, 4)                                    AS cost_overrun_rate,
    ROUND(w.avg_duration_variance_hours, 3)                          AS avg_duration_variance_hours,
    ROUND(w.parts_delay_rate, 4)                                     AS parts_delay_rate,
    ROUND(w.qc_first_pass_rate, 4)                                   AS qc_first_pass_rate,
    ROUND(w.comeback_rate, 4)                                        AS comeback_rate,
    a.appointments,
    a.cancelled                                                      AS cancelled_appointments,
    a.no_shows                                                       AS no_show_appointments,
    ROUND(a.cancelled::NUMERIC / NULLIF(a.appointments, 0), 4)       AS cancellation_rate,
    ROUND(a.no_shows::NUMERIC  / NULLIF(a.appointments, 0), 4)       AS no_show_rate,
    ROUND(u.technician_hours / NULLIF(u.available_hours, 0), 4)      AS technician_utilisation,
    ROUND(w.avg_rating, 3)                                           AS avg_rating,
    ROUND(w.csat_rate, 4)                                            AS csat_rate,
    w.rated_work_orders,
    r.customers_served,
    r.repeat_customers,
    ROUND(r.repeat_customers::NUMERIC / NULLIF(r.customers_served, 0), 4) AS repeat_visit_rate
FROM w CROSS JOIN a CROSS JOIN r CROSS JOIN u;

COMMENT ON VIEW vw_kpi_summary IS 'Single row: headline KPIs 1-16 (ratios as fractions 0-1).';
