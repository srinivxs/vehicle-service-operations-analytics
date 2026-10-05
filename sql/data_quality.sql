-- =============================================================================
-- data_quality.sql  |  SQL-side validation mirroring spec section 7
--
-- Every query returns one labelled row: (check_id, check_name, check_type, issue_count).
--   integrity     = must be 0 on the cleaned data
--   informational = documented gap / reconciliation count; non-zero is expected and explained
-- Foreign keys, CHECK constraints and PKs in schema.sql already block most integrity
-- violations, so these queries double as a regression test and can be pointed at
-- staging / raw loads that lack constraints.
-- SQL-DQ99 is the UNION ALL summary of everything above (run by src/run_sql_reports.py).
-- IDs are prefixed SQL- so they do not collide with the Python cleaning rules DQ01-DQ20 (reports/cleaning_log.csv).
-- =============================================================================

SET search_path TO service_ops, public;


-- SQL-DQ01: Duplicate appointment_id
-- Spec ref: 7: duplicate IDs
SELECT 'SQL-DQ01' AS check_id, 'Duplicate appointment_id' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT appointment_id FROM appointments GROUP BY appointment_id HAVING COUNT(*) > 1) d;

-- SQL-DQ02: Duplicate work_order_id
-- Spec ref: 7: duplicate IDs
SELECT 'SQL-DQ02' AS check_id, 'Duplicate work_order_id' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT work_order_id FROM work_orders GROUP BY work_order_id HAVING COUNT(*) > 1) d;

-- SQL-DQ03: Duplicate keys in other tables (customer, vehicle, usage, feedback, financials)
-- Spec ref: 7: duplicate IDs
SELECT 'SQL-DQ03' AS check_id, 'Duplicate keys in other tables (customer, vehicle, usage, feedback, financials)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT customer_id   AS k FROM customers  GROUP BY customer_id   HAVING COUNT(*) > 1
    UNION ALL SELECT vehicle_id  FROM vehicles  GROUP BY vehicle_id  HAVING COUNT(*) > 1
    UNION ALL SELECT usage_id    FROM part_usage GROUP BY usage_id   HAVING COUNT(*) > 1
    UNION ALL SELECT feedback_id FROM feedback  GROUP BY feedback_id HAVING COUNT(*) > 1
    UNION ALL SELECT work_order_id FROM feedback   GROUP BY work_order_id HAVING COUNT(*) > 1
    UNION ALL SELECT work_order_id FROM financials GROUP BY work_order_id HAVING COUNT(*) > 1
) d;

-- SQL-DQ04: Appointments linked to more than one work order
-- Spec ref: 6: 1 appointment : 1 work order
SELECT 'SQL-DQ04' AS check_id, 'Appointments linked to more than one work order' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT appointment_id FROM work_orders GROUP BY appointment_id HAVING COUNT(*) > 1) d;

-- SQL-DQ05: Orphan vehicles (customer missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ05' AS check_id, 'Orphan vehicles (customer missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles v LEFT JOIN customers c ON c.customer_id = v.customer_id WHERE c.customer_id IS NULL;

-- SQL-DQ06: Orphan appointments (vehicle missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ06' AS check_id, 'Orphan appointments (vehicle missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN vehicles v ON v.vehicle_id = a.vehicle_id WHERE v.vehicle_id IS NULL;

-- SQL-DQ07: Orphan appointments (service centre missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ07' AS check_id, 'Orphan appointments (service centre missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN service_centers sc ON sc.center_id = a.center_id WHERE sc.center_id IS NULL;

-- SQL-DQ08: Orphan technicians (service centre missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ08' AS check_id, 'Orphan technicians (service centre missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM technicians t LEFT JOIN service_centers sc ON sc.center_id = t.center_id WHERE sc.center_id IS NULL;

-- SQL-DQ09: Orphan work orders (appointment missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ09' AS check_id, 'Orphan work orders (appointment missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN appointments a ON a.appointment_id = wo.appointment_id WHERE a.appointment_id IS NULL;

-- SQL-DQ10: Work orders with a technician_id that is not in the technician master
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ10' AS check_id, 'Work orders with a technician_id that is not in the technician master' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN technicians t ON t.technician_id = wo.technician_id
WHERE wo.technician_id IS NOT NULL AND t.technician_id IS NULL;

-- SQL-DQ11: Orphan part_usage rows (work order missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ11' AS check_id, 'Orphan part_usage rows (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage pu LEFT JOIN work_orders wo ON wo.work_order_id = pu.work_order_id WHERE wo.work_order_id IS NULL;

-- SQL-DQ12: Orphan part_usage rows (part missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ12' AS check_id, 'Orphan part_usage rows (part missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage pu LEFT JOIN parts p ON p.part_id = pu.part_id WHERE p.part_id IS NULL;

-- SQL-DQ13: Orphan financials (work order missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ13' AS check_id, 'Orphan financials (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials f LEFT JOIN work_orders wo ON wo.work_order_id = f.work_order_id WHERE wo.work_order_id IS NULL;

-- SQL-DQ14: Orphan feedback (work order missing)
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ14' AS check_id, 'Orphan feedback (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback fb LEFT JOIN work_orders wo ON wo.work_order_id = fb.work_order_id WHERE wo.work_order_id IS NULL;

-- SQL-DQ15: Work orders without a financials row
-- Spec ref: 7: missing foreign keys
SELECT 'SQL-DQ15' AS check_id, 'Work orders without a financials row' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN financials f ON f.work_order_id = wo.work_order_id WHERE f.work_order_id IS NULL;

-- SQL-DQ16: Null required fields in appointments
-- Spec ref: 7: required fields
SELECT 'SQL-DQ16' AS check_id, 'Null required fields in appointments' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE vehicle_id IS NULL OR center_id IS NULL OR booking_date IS NULL OR scheduled_date IS NULL OR status IS NULL OR requested_service_type IS NULL;

-- SQL-DQ17: Null required fields in work_orders (technician_id and start_time are optional by design)
-- Spec ref: 7: required fields
SELECT 'SQL-DQ17' AS check_id, 'Null required fields in work_orders (technician_id and start_time are optional by design)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE appointment_id IS NULL OR service_type IS NULL OR check_in_time IS NULL OR end_time IS NULL OR promised_ready_time IS NULL OR estimated_hours IS NULL OR actual_hours IS NULL;

-- SQL-DQ18: Null required fields in financials
-- Spec ref: 7: required fields
SELECT 'SQL-DQ18' AS check_id, 'Null required fields in financials' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE billing_type IS NULL OR estimated_cost IS NULL OR labor_cost IS NULL OR parts_cost IS NULL OR revenue IS NULL;

-- SQL-DQ19: Null required fields in feedback
-- Spec ref: 7: required fields
SELECT 'SQL-DQ19' AS check_id, 'Null required fields in feedback' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback WHERE work_order_id IS NULL OR rating IS NULL OR feedback_category IS NULL OR feedback_date IS NULL;

-- SQL-DQ20: Null required fields in customers / vehicles (mileage_km is optional by design)
-- Spec ref: 7: required fields
SELECT 'SQL-DQ20' AS check_id, 'Null required fields in customers / vehicles (mileage_km is optional by design)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT customer_id FROM customers WHERE customer_type IS NULL OR region IS NULL OR city IS NULL OR registration_date IS NULL
    UNION ALL
    SELECT vehicle_id FROM vehicles WHERE customer_id IS NULL OR model IS NULL OR model_year IS NULL OR purchase_date IS NULL
) d;

-- SQL-DQ21: Work orders where end_time is earlier than start_time
-- Spec ref: 7: completion not earlier than start
SELECT 'SQL-DQ21' AS check_id, 'Work orders where end_time is earlier than start_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE end_time < start_time;

-- SQL-DQ22: Work orders where end_time is earlier than check_in_time
-- Spec ref: 7: completion not earlier than start
SELECT 'SQL-DQ22' AS check_id, 'Work orders where end_time is earlier than check_in_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE end_time < check_in_time;

-- SQL-DQ23: Work orders where start_time is earlier than check_in_time
-- Spec ref: 7: time sequence
SELECT 'SQL-DQ23' AS check_id, 'Work orders where start_time is earlier than check_in_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE start_time < check_in_time;

-- SQL-DQ24: Work orders promised before check-in
-- Spec ref: 7: time sequence
SELECT 'SQL-DQ24' AS check_id, 'Work orders promised before check-in' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE promised_ready_time < check_in_time;

-- SQL-DQ25: Negative costs or revenue (financials, parts, technicians)
-- Spec ref: 7: non-negative amounts
SELECT 'SQL-DQ25' AS check_id, 'Negative costs or revenue (financials, parts, technicians)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT work_order_id AS k FROM financials WHERE estimated_cost < 0 OR labor_cost < 0 OR parts_cost < 0 OR revenue < 0
    UNION ALL SELECT part_id FROM parts WHERE unit_cost < 0
    UNION ALL SELECT technician_id FROM technicians WHERE hourly_cost < 0
) d;

-- SQL-DQ26: Part usage with zero or negative quantity
-- Spec ref: 7: non-negative amounts
SELECT 'SQL-DQ26' AS check_id, 'Part usage with zero or negative quantity' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage WHERE quantity <= 0;

-- SQL-DQ27: Negative or zero durations (estimated_hours <= 0, actual_hours < 0, parts_wait_hours < 0)
-- Spec ref: 7: non-negative amounts
SELECT 'SQL-DQ27' AS check_id, 'Negative or zero durations (estimated_hours <= 0, actual_hours < 0, parts_wait_hours < 0)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE estimated_hours <= 0 OR actual_hours < 0 OR parts_wait_hours < 0;

-- SQL-DQ28: Customer ratings outside 1-5
-- Spec ref: 7: ratings within 1-5
SELECT 'SQL-DQ28' AS check_id, 'Customer ratings outside 1-5' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback WHERE rating NOT BETWEEN 1 AND 5;

-- SQL-DQ29: Values outside allowed domains (status, billing_type, customer_type, region, skill_level)
-- Spec ref: 7: standardised values
SELECT 'SQL-DQ29' AS check_id, 'Values outside allowed domains (status, billing_type, customer_type, region, skill_level)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT appointment_id AS k FROM appointments WHERE status NOT IN ('Completed', 'Cancelled', 'No-Show')
    UNION ALL SELECT work_order_id FROM financials WHERE billing_type NOT IN ('Customer Paid', 'Service Plan', 'Warranty', 'Rework (No Charge)')
    UNION ALL SELECT customer_id FROM customers WHERE customer_type NOT IN ('Individual', 'Corporate', 'Fleet') OR region NOT IN ('North', 'South', 'East', 'West')
    UNION ALL SELECT technician_id FROM technicians WHERE skill_level NOT IN ('Junior', 'Mid', 'Senior', 'Master')
) d;

-- SQL-DQ30: Appointments scheduled outside the reporting period (2025-01-01..2026-09-30)
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ30' AS check_id, 'Appointments scheduled outside the reporting period (2025-01-01..2026-09-30)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE scheduled_date NOT BETWEEN DATE '2025-01-01' AND DATE '2026-09-30';

-- SQL-DQ31: Appointments booked after their scheduled date
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ31' AS check_id, 'Appointments booked after their scheduled date' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE booking_date > scheduled_date;

-- SQL-DQ32: Work orders checked in outside the reporting period
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ32' AS check_id, 'Work orders checked in outside the reporting period' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE check_in_time::DATE NOT BETWEEN DATE '2025-01-01' AND DATE '2026-09-30';

-- SQL-DQ33: Work orders whose check-in date differs from the scheduled date by more than 7 days
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ33' AS check_id, 'Work orders whose check-in date differs from the scheduled date by more than 7 days' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
WHERE ABS(wo.check_in_time::DATE - a.scheduled_date) > 7;

-- SQL-DQ34: Feedback dated before the work order finished
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ34' AS check_id, 'Feedback dated before the work order finished' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback fb JOIN work_orders wo ON wo.work_order_id = fb.work_order_id WHERE fb.feedback_date < wo.end_time::DATE;

-- SQL-DQ35: Vehicles purchased after the end of the reporting period, or before the customer registered (information only)
-- Spec ref: 7: date ranges
SELECT 'SQL-DQ35' AS check_id, 'Vehicles purchased after the end of the reporting period, or before the customer registered (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM vehicles v JOIN customers c ON c.customer_id = v.customer_id WHERE v.purchase_date > DATE '2026-09-30' OR v.purchase_date < c.registration_date - 365;

-- SQL-DQ36: Model year earlier than model launch (450X >= 2020, Apex/Rizta >= 2024)
-- Spec ref: 7: impossible model-year
SELECT 'SQL-DQ36' AS check_id, 'Model year earlier than model launch (450X >= 2020, Apex/Rizta >= 2024)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles
WHERE (model = 'Ather 450X' AND model_year < 2020)
   OR (model IN ('Ather 450 Apex', 'Ather Rizta') AND model_year < 2024);

-- SQL-DQ37: Model year more than 1 year after purchase year
-- Spec ref: 7: impossible model-year
SELECT 'SQL-DQ37' AS check_id, 'Model year more than 1 year after purchase year' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE model_year > EXTRACT(YEAR FROM purchase_date) + 1;

-- SQL-DQ38: Implausible mileage (negative, or above 250 km per day since purchase)
-- Spec ref: 7: impossible mileage
SELECT 'SQL-DQ38' AS check_id, 'Implausible mileage (negative, or above 250 km per day since purchase)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE mileage_km < 0 OR mileage_km > GREATEST(DATE '2026-09-30' - purchase_date, 1) * 250;

-- SQL-DQ39: Odometer reading lower than the same vehicle at its previous visit (information only)
-- Spec ref: 7: impossible mileage
SELECT 'SQL-DQ39' AS check_id, 'Odometer reading lower than the same vehicle at its previous visit (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT wo.odometer_km,
           LAG(wo.odometer_km) OVER (PARTITION BY a.vehicle_id ORDER BY wo.check_in_time, wo.work_order_id) AS prev_odometer_km
    FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
) o
WHERE o.odometer_km < o.prev_odometer_km;

-- SQL-DQ40: Completed appointments without a work order
-- Spec ref: 8: completed appointments need a job
SELECT 'SQL-DQ40' AS check_id, 'Completed appointments without a work order' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN work_orders wo ON wo.appointment_id = a.appointment_id
WHERE a.status = 'Completed' AND wo.work_order_id IS NULL;

-- SQL-DQ41: Work orders attached to a Cancelled / No-Show appointment
-- Spec ref: 8: only completed appointments are serviced
SELECT 'SQL-DQ41' AS check_id, 'Work orders attached to a Cancelled / No-Show appointment' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
WHERE a.status <> 'Completed';

-- SQL-DQ42: Cancelled appointments without a cancellation reason (information only)
-- Spec ref: 7: required fields
SELECT 'SQL-DQ42' AS check_id, 'Cancelled appointments without a cancellation reason (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE status = 'Cancelled' AND cancellation_reason IS NULL;

-- SQL-DQ43: Financial parts_cost differs from SUM(part_usage.quantity x parts.unit_cost) by more than INR 1 (reconciliation, information only)
-- Spec ref: 7: billing system of record vs usage ledger
SELECT 'SQL-DQ43' AS check_id, 'Financial parts_cost differs from SUM(part_usage.quantity x parts.unit_cost) by more than INR 1 (reconciliation, information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM financials f
LEFT JOIN (
    SELECT pu.work_order_id, SUM(pu.quantity * p.unit_cost) AS usage_cost
    FROM part_usage pu JOIN parts p ON p.part_id = pu.part_id
    GROUP BY pu.work_order_id
) u ON u.work_order_id = f.work_order_id
WHERE ABS(f.parts_cost - COALESCE(u.usage_cost, 0)) > 1;

-- SQL-DQ44: Rework (No Charge) rows with non-zero revenue
-- Spec ref: 10: rework billing rule
SELECT 'SQL-DQ44' AS check_id, 'Rework (No Charge) rows with non-zero revenue' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE billing_type = 'Rework (No Charge)' AND revenue <> 0;

-- SQL-DQ45: Revenue above 10x job cost and INR 50,000 (possible decimal-shift remnants)
-- Spec ref: 7: outliers
SELECT 'SQL-DQ45' AS check_id, 'Revenue above 10x job cost and INR 50,000 (possible decimal-shift remnants)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE revenue > 10 * (labor_cost + parts_cost) AND revenue > 50000;

-- SQL-DQ46: Work orders without an assigned technician (documented gap, excluded from technician KPIs)
-- Spec ref: 7: missing data risk
SELECT 'SQL-DQ46' AS check_id, 'Work orders without an assigned technician (documented gap, excluded from technician KPIs)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE technician_id IS NULL;

-- SQL-DQ47: Work orders without a recorded start_time (documented gap, excluded from wait KPI)
-- Spec ref: 7: missing data risk
SELECT 'SQL-DQ47' AS check_id, 'Work orders without a recorded start_time (documented gap, excluded from wait KPI)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE start_time IS NULL;

-- SQL-DQ48: Vehicles with unknown mileage (set to NULL during cleaning)
-- Spec ref: 7: missing data risk
SELECT 'SQL-DQ48' AS check_id, 'Vehicles with unknown mileage (set to NULL during cleaning)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE mileage_km IS NULL;

-- SQL-DQ49: Appointment slot outside shop hours (09:00-19:00) or not a valid time
-- Spec ref: 7: date/time formats
SELECT 'SQL-DQ49' AS check_id, 'Appointment slot outside shop hours (09:00-19:00) or not a valid time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE scheduled_slot IS NOT NULL AND scheduled_slot NOT BETWEEN TIME '09:00' AND TIME '19:00';

-- SQL-DQ50: Completed work orders without customer feedback (rating coverage gap)
-- Spec ref: 7: missing data risk
SELECT 'SQL-DQ50' AS check_id, 'Completed work orders without customer feedback (rating coverage gap)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN feedback fb ON fb.work_order_id = wo.work_order_id WHERE fb.feedback_id IS NULL;

-- SQL-DQ99: Data-quality summary (all checks, UNION ALL)
-- Spec ref: 7: summary of every check with PASS / INFO / FAIL status
SELECT s.*,
       CASE WHEN s.issue_count = 0 THEN 'PASS'
            WHEN s.check_type = 'informational' THEN 'INFO'
            ELSE 'FAIL' END AS status
FROM (
SELECT 'SQL-DQ01' AS check_id, 'Duplicate appointment_id' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT appointment_id FROM appointments GROUP BY appointment_id HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'SQL-DQ02' AS check_id, 'Duplicate work_order_id' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT work_order_id FROM work_orders GROUP BY work_order_id HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'SQL-DQ03' AS check_id, 'Duplicate keys in other tables (customer, vehicle, usage, feedback, financials)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT customer_id   AS k FROM customers  GROUP BY customer_id   HAVING COUNT(*) > 1
    UNION ALL SELECT vehicle_id  FROM vehicles  GROUP BY vehicle_id  HAVING COUNT(*) > 1
    UNION ALL SELECT usage_id    FROM part_usage GROUP BY usage_id   HAVING COUNT(*) > 1
    UNION ALL SELECT feedback_id FROM feedback  GROUP BY feedback_id HAVING COUNT(*) > 1
    UNION ALL SELECT work_order_id FROM feedback   GROUP BY work_order_id HAVING COUNT(*) > 1
    UNION ALL SELECT work_order_id FROM financials GROUP BY work_order_id HAVING COUNT(*) > 1
) d
UNION ALL
SELECT 'SQL-DQ04' AS check_id, 'Appointments linked to more than one work order' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (SELECT appointment_id FROM work_orders GROUP BY appointment_id HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'SQL-DQ05' AS check_id, 'Orphan vehicles (customer missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles v LEFT JOIN customers c ON c.customer_id = v.customer_id WHERE c.customer_id IS NULL
UNION ALL
SELECT 'SQL-DQ06' AS check_id, 'Orphan appointments (vehicle missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN vehicles v ON v.vehicle_id = a.vehicle_id WHERE v.vehicle_id IS NULL
UNION ALL
SELECT 'SQL-DQ07' AS check_id, 'Orphan appointments (service centre missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN service_centers sc ON sc.center_id = a.center_id WHERE sc.center_id IS NULL
UNION ALL
SELECT 'SQL-DQ08' AS check_id, 'Orphan technicians (service centre missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM technicians t LEFT JOIN service_centers sc ON sc.center_id = t.center_id WHERE sc.center_id IS NULL
UNION ALL
SELECT 'SQL-DQ09' AS check_id, 'Orphan work orders (appointment missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN appointments a ON a.appointment_id = wo.appointment_id WHERE a.appointment_id IS NULL
UNION ALL
SELECT 'SQL-DQ10' AS check_id, 'Work orders with a technician_id that is not in the technician master' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN technicians t ON t.technician_id = wo.technician_id
WHERE wo.technician_id IS NOT NULL AND t.technician_id IS NULL
UNION ALL
SELECT 'SQL-DQ11' AS check_id, 'Orphan part_usage rows (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage pu LEFT JOIN work_orders wo ON wo.work_order_id = pu.work_order_id WHERE wo.work_order_id IS NULL
UNION ALL
SELECT 'SQL-DQ12' AS check_id, 'Orphan part_usage rows (part missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage pu LEFT JOIN parts p ON p.part_id = pu.part_id WHERE p.part_id IS NULL
UNION ALL
SELECT 'SQL-DQ13' AS check_id, 'Orphan financials (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials f LEFT JOIN work_orders wo ON wo.work_order_id = f.work_order_id WHERE wo.work_order_id IS NULL
UNION ALL
SELECT 'SQL-DQ14' AS check_id, 'Orphan feedback (work order missing)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback fb LEFT JOIN work_orders wo ON wo.work_order_id = fb.work_order_id WHERE wo.work_order_id IS NULL
UNION ALL
SELECT 'SQL-DQ15' AS check_id, 'Work orders without a financials row' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN financials f ON f.work_order_id = wo.work_order_id WHERE f.work_order_id IS NULL
UNION ALL
SELECT 'SQL-DQ16' AS check_id, 'Null required fields in appointments' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE vehicle_id IS NULL OR center_id IS NULL OR booking_date IS NULL OR scheduled_date IS NULL OR status IS NULL OR requested_service_type IS NULL
UNION ALL
SELECT 'SQL-DQ17' AS check_id, 'Null required fields in work_orders (technician_id and start_time are optional by design)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE appointment_id IS NULL OR service_type IS NULL OR check_in_time IS NULL OR end_time IS NULL OR promised_ready_time IS NULL OR estimated_hours IS NULL OR actual_hours IS NULL
UNION ALL
SELECT 'SQL-DQ18' AS check_id, 'Null required fields in financials' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE billing_type IS NULL OR estimated_cost IS NULL OR labor_cost IS NULL OR parts_cost IS NULL OR revenue IS NULL
UNION ALL
SELECT 'SQL-DQ19' AS check_id, 'Null required fields in feedback' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback WHERE work_order_id IS NULL OR rating IS NULL OR feedback_category IS NULL OR feedback_date IS NULL
UNION ALL
SELECT 'SQL-DQ20' AS check_id, 'Null required fields in customers / vehicles (mileage_km is optional by design)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT customer_id FROM customers WHERE customer_type IS NULL OR region IS NULL OR city IS NULL OR registration_date IS NULL
    UNION ALL
    SELECT vehicle_id FROM vehicles WHERE customer_id IS NULL OR model IS NULL OR model_year IS NULL OR purchase_date IS NULL
) d
UNION ALL
SELECT 'SQL-DQ21' AS check_id, 'Work orders where end_time is earlier than start_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE end_time < start_time
UNION ALL
SELECT 'SQL-DQ22' AS check_id, 'Work orders where end_time is earlier than check_in_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE end_time < check_in_time
UNION ALL
SELECT 'SQL-DQ23' AS check_id, 'Work orders where start_time is earlier than check_in_time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE start_time < check_in_time
UNION ALL
SELECT 'SQL-DQ24' AS check_id, 'Work orders promised before check-in' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE promised_ready_time < check_in_time
UNION ALL
SELECT 'SQL-DQ25' AS check_id, 'Negative costs or revenue (financials, parts, technicians)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT work_order_id AS k FROM financials WHERE estimated_cost < 0 OR labor_cost < 0 OR parts_cost < 0 OR revenue < 0
    UNION ALL SELECT part_id FROM parts WHERE unit_cost < 0
    UNION ALL SELECT technician_id FROM technicians WHERE hourly_cost < 0
) d
UNION ALL
SELECT 'SQL-DQ26' AS check_id, 'Part usage with zero or negative quantity' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM part_usage WHERE quantity <= 0
UNION ALL
SELECT 'SQL-DQ27' AS check_id, 'Negative or zero durations (estimated_hours <= 0, actual_hours < 0, parts_wait_hours < 0)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE estimated_hours <= 0 OR actual_hours < 0 OR parts_wait_hours < 0
UNION ALL
SELECT 'SQL-DQ28' AS check_id, 'Customer ratings outside 1-5' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback WHERE rating NOT BETWEEN 1 AND 5
UNION ALL
SELECT 'SQL-DQ29' AS check_id, 'Values outside allowed domains (status, billing_type, customer_type, region, skill_level)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT appointment_id AS k FROM appointments WHERE status NOT IN ('Completed', 'Cancelled', 'No-Show')
    UNION ALL SELECT work_order_id FROM financials WHERE billing_type NOT IN ('Customer Paid', 'Service Plan', 'Warranty', 'Rework (No Charge)')
    UNION ALL SELECT customer_id FROM customers WHERE customer_type NOT IN ('Individual', 'Corporate', 'Fleet') OR region NOT IN ('North', 'South', 'East', 'West')
    UNION ALL SELECT technician_id FROM technicians WHERE skill_level NOT IN ('Junior', 'Mid', 'Senior', 'Master')
) d
UNION ALL
SELECT 'SQL-DQ30' AS check_id, 'Appointments scheduled outside the reporting period (2025-01-01..2026-09-30)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE scheduled_date NOT BETWEEN DATE '2025-01-01' AND DATE '2026-09-30'
UNION ALL
SELECT 'SQL-DQ31' AS check_id, 'Appointments booked after their scheduled date' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE booking_date > scheduled_date
UNION ALL
SELECT 'SQL-DQ32' AS check_id, 'Work orders checked in outside the reporting period' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE check_in_time::DATE NOT BETWEEN DATE '2025-01-01' AND DATE '2026-09-30'
UNION ALL
SELECT 'SQL-DQ33' AS check_id, 'Work orders whose check-in date differs from the scheduled date by more than 7 days' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
WHERE ABS(wo.check_in_time::DATE - a.scheduled_date) > 7
UNION ALL
SELECT 'SQL-DQ34' AS check_id, 'Feedback dated before the work order finished' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM feedback fb JOIN work_orders wo ON wo.work_order_id = fb.work_order_id WHERE fb.feedback_date < wo.end_time::DATE
UNION ALL
SELECT 'SQL-DQ35' AS check_id, 'Vehicles purchased after the end of the reporting period, or before the customer registered (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM vehicles v JOIN customers c ON c.customer_id = v.customer_id WHERE v.purchase_date > DATE '2026-09-30' OR v.purchase_date < c.registration_date - 365
UNION ALL
SELECT 'SQL-DQ36' AS check_id, 'Model year earlier than model launch (450X >= 2020, Apex/Rizta >= 2024)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles
WHERE (model = 'Ather 450X' AND model_year < 2020)
   OR (model IN ('Ather 450 Apex', 'Ather Rizta') AND model_year < 2024)
UNION ALL
SELECT 'SQL-DQ37' AS check_id, 'Model year more than 1 year after purchase year' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE model_year > EXTRACT(YEAR FROM purchase_date) + 1
UNION ALL
SELECT 'SQL-DQ38' AS check_id, 'Implausible mileage (negative, or above 250 km per day since purchase)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE mileage_km < 0 OR mileage_km > GREATEST(DATE '2026-09-30' - purchase_date, 1) * 250
UNION ALL
SELECT 'SQL-DQ39' AS check_id, 'Odometer reading lower than the same vehicle at its previous visit (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM (
    SELECT wo.odometer_km,
           LAG(wo.odometer_km) OVER (PARTITION BY a.vehicle_id ORDER BY wo.check_in_time, wo.work_order_id) AS prev_odometer_km
    FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
) o
WHERE o.odometer_km < o.prev_odometer_km
UNION ALL
SELECT 'SQL-DQ40' AS check_id, 'Completed appointments without a work order' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments a LEFT JOIN work_orders wo ON wo.appointment_id = a.appointment_id
WHERE a.status = 'Completed' AND wo.work_order_id IS NULL
UNION ALL
SELECT 'SQL-DQ41' AS check_id, 'Work orders attached to a Cancelled / No-Show appointment' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo JOIN appointments a ON a.appointment_id = wo.appointment_id
WHERE a.status <> 'Completed'
UNION ALL
SELECT 'SQL-DQ42' AS check_id, 'Cancelled appointments without a cancellation reason (information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE status = 'Cancelled' AND cancellation_reason IS NULL
UNION ALL
SELECT 'SQL-DQ43' AS check_id, 'Financial parts_cost differs from SUM(part_usage.quantity x parts.unit_cost) by more than INR 1 (reconciliation, information only)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM financials f
LEFT JOIN (
    SELECT pu.work_order_id, SUM(pu.quantity * p.unit_cost) AS usage_cost
    FROM part_usage pu JOIN parts p ON p.part_id = pu.part_id
    GROUP BY pu.work_order_id
) u ON u.work_order_id = f.work_order_id
WHERE ABS(f.parts_cost - COALESCE(u.usage_cost, 0)) > 1
UNION ALL
SELECT 'SQL-DQ44' AS check_id, 'Rework (No Charge) rows with non-zero revenue' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE billing_type = 'Rework (No Charge)' AND revenue <> 0
UNION ALL
SELECT 'SQL-DQ45' AS check_id, 'Revenue above 10x job cost and INR 50,000 (possible decimal-shift remnants)' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM financials WHERE revenue > 10 * (labor_cost + parts_cost) AND revenue > 50000
UNION ALL
SELECT 'SQL-DQ46' AS check_id, 'Work orders without an assigned technician (documented gap, excluded from technician KPIs)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE technician_id IS NULL
UNION ALL
SELECT 'SQL-DQ47' AS check_id, 'Work orders without a recorded start_time (documented gap, excluded from wait KPI)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders WHERE start_time IS NULL
UNION ALL
SELECT 'SQL-DQ48' AS check_id, 'Vehicles with unknown mileage (set to NULL during cleaning)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM vehicles WHERE mileage_km IS NULL
UNION ALL
SELECT 'SQL-DQ49' AS check_id, 'Appointment slot outside shop hours (09:00-19:00) or not a valid time' AS check_name, 'integrity' AS check_type, COUNT(*) AS issue_count
FROM appointments WHERE scheduled_slot IS NOT NULL AND scheduled_slot NOT BETWEEN TIME '09:00' AND TIME '19:00'
UNION ALL
SELECT 'SQL-DQ50' AS check_id, 'Completed work orders without customer feedback (rating coverage gap)' AS check_name, 'informational' AS check_type, COUNT(*) AS issue_count
FROM work_orders wo LEFT JOIN feedback fb ON fb.work_order_id = wo.work_order_id WHERE fb.feedback_id IS NULL
) s
ORDER BY s.check_id;
