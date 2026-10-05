-- =============================================================================
-- schema.sql  |  Vehicle Service Operations Analytics & Process Optimization
-- Synthetic data modelled on an EV two-wheeler service network (Ather-style
-- models). Not affiliated with Ather Energy. Currency: INR.
--
-- Idempotent: drops and recreates the service_ops schema (tables AND views).
-- Run order: schema.sql -> (load CSVs) -> views.sql
-- =============================================================================

DROP SCHEMA IF EXISTS service_ops CASCADE;
CREATE SCHEMA service_ops;
SET search_path TO service_ops, public;

-- -----------------------------------------------------------------------------
-- Master data
-- -----------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id        VARCHAR(10)  PRIMARY KEY,
    customer_type      VARCHAR(20)  NOT NULL
        CONSTRAINT ck_customers_type CHECK (customer_type IN ('Individual', 'Corporate', 'Fleet')),
    city               VARCHAR(60)  NOT NULL,
    region             VARCHAR(10)  NOT NULL
        CONSTRAINT ck_customers_region CHECK (region IN ('North', 'South', 'East', 'West')),
    registration_date  DATE         NOT NULL
);
COMMENT ON TABLE customers IS 'Customer master (synthetic, no PII): one row per customer.';

CREATE TABLE service_centers (
    center_id           VARCHAR(10)  PRIMARY KEY,
    center_name         VARCHAR(80)  NOT NULL UNIQUE,
    city                VARCHAR(60)  NOT NULL,
    state               VARCHAR(60)  NOT NULL,
    region              VARCHAR(10)  NOT NULL
        CONSTRAINT ck_centers_region CHECK (region IN ('North', 'South', 'East', 'West')),
    service_bays        SMALLINT     NOT NULL CONSTRAINT ck_centers_bays CHECK (service_bays > 0),
    daily_job_capacity  SMALLINT     NOT NULL CONSTRAINT ck_centers_capacity CHECK (daily_job_capacity > 0),
    opened_date         DATE         NOT NULL
);
COMMENT ON TABLE service_centers IS 'Service centre master with bay count and daily job capacity.';

CREATE TABLE technicians (
    technician_id        VARCHAR(10)   PRIMARY KEY,
    center_id            VARCHAR(10)   NOT NULL REFERENCES service_centers (center_id),
    skill_level          VARCHAR(10)   NOT NULL
        CONSTRAINT ck_tech_skill CHECK (skill_level IN ('Junior', 'Mid', 'Senior', 'Master')),
    years_experience     SMALLINT      NOT NULL CONSTRAINT ck_tech_exp CHECK (years_experience >= 0),
    certification        VARCHAR(40),
    hourly_cost          NUMERIC(10,2) NOT NULL CONSTRAINT ck_tech_cost CHECK (hourly_cost >= 0),
    shift_hours_per_day  SMALLINT      NOT NULL CONSTRAINT ck_tech_shift CHECK (shift_hours_per_day BETWEEN 1 AND 24)
);
COMMENT ON TABLE technicians IS 'Technician master; each technician belongs to one service centre.';

CREATE TABLE vehicles (
    vehicle_id        VARCHAR(10)   PRIMARY KEY,
    customer_id       VARCHAR(10)   NOT NULL REFERENCES customers (customer_id),
    model             VARCHAR(30)   NOT NULL
        CONSTRAINT ck_vehicles_model CHECK (model IN ('Ather 450X', 'Ather 450 Apex', 'Ather Rizta')),
    variant           VARCHAR(60)   NOT NULL,
    vehicle_category  VARCHAR(20)   NOT NULL,
    battery_kwh       NUMERIC(4,1)  NOT NULL CONSTRAINT ck_vehicles_battery CHECK (battery_kwh > 0),
    model_year        SMALLINT      NOT NULL,
    purchase_date     DATE          NOT NULL,
    mileage_km        NUMERIC(10,1)
        CONSTRAINT ck_vehicles_mileage CHECK (mileage_km IS NULL OR mileage_km >= 0),  -- NULL = implausible/missing
    CONSTRAINT ck_vehicles_model_year CHECK (
        model_year >= CASE model WHEN 'Ather 450X' THEN 2020 ELSE 2024 END
    )
);
COMMENT ON TABLE vehicles IS 'Vehicle master; model_year may not precede the model launch year (450X 2020, Apex/Rizta 2024).';

-- -----------------------------------------------------------------------------
-- Transactions
-- -----------------------------------------------------------------------------
CREATE TABLE appointments (
    appointment_id          VARCHAR(12)  PRIMARY KEY,
    vehicle_id              VARCHAR(10)  NOT NULL REFERENCES vehicles (vehicle_id),
    center_id               VARCHAR(10)  NOT NULL REFERENCES service_centers (center_id),
    booking_date            DATE         NOT NULL,
    scheduled_date          DATE         NOT NULL,
    scheduled_slot          TIME,
    booking_channel         VARCHAR(30)  NOT NULL,
    requested_service_type  VARCHAR(50)  NOT NULL,
    status                  VARCHAR(12)  NOT NULL
        CONSTRAINT ck_appt_status CHECK (status IN ('Completed', 'Cancelled', 'No-Show')),
    cancellation_reason     VARCHAR(60),
    CONSTRAINT ck_appt_dates  CHECK (booking_date <= scheduled_date),
    CONSTRAINT ck_appt_reason CHECK (cancellation_reason IS NULL OR status = 'Cancelled')
);
COMMENT ON TABLE appointments IS 'Bookings of every status; only Completed appointments have a work order.';

CREATE TABLE work_orders (
    work_order_id          VARCHAR(12)   PRIMARY KEY,
    appointment_id         VARCHAR(12)   NOT NULL UNIQUE REFERENCES appointments (appointment_id),
    technician_id          VARCHAR(10)   REFERENCES technicians (technician_id),  -- NULL = unassigned / invalid
    service_type           VARCHAR(50)   NOT NULL,
    check_in_time          TIMESTAMP     NOT NULL,
    start_time             TIMESTAMP,                                             -- NULL = not recorded
    end_time               TIMESTAMP     NOT NULL,
    promised_ready_time    TIMESTAMP     NOT NULL,
    estimated_hours        NUMERIC(6,2)  NOT NULL CONSTRAINT ck_wo_est_hours CHECK (estimated_hours > 0),
    actual_hours           NUMERIC(6,2)  NOT NULL CONSTRAINT ck_wo_act_hours CHECK (actual_hours >= 0),
    parts_wait_hours       NUMERIC(6,2)  NOT NULL DEFAULT 0 CONSTRAINT ck_wo_parts_wait CHECK (parts_wait_hours >= 0),
    odometer_km            INTEGER       CONSTRAINT ck_wo_odometer CHECK (odometer_km >= 0),
    additional_work_found  BOOLEAN       NOT NULL,
    qc_passed_first_time   BOOLEAN       NOT NULL,
    CONSTRAINT ck_wo_end_after_start       CHECK (end_time >= start_time),
    CONSTRAINT ck_wo_end_after_checkin     CHECK (end_time >= check_in_time),
    CONSTRAINT ck_wo_promise_after_checkin CHECK (promised_ready_time >= check_in_time)
);
COMMENT ON TABLE work_orders IS 'Actual service jobs (1:1 with a Completed appointment). NULL technician_id/start_time are documented data gaps.';

CREATE TABLE parts (
    part_id              VARCHAR(10)   PRIMARY KEY,
    part_name            VARCHAR(80)   NOT NULL,
    part_category        VARCHAR(40)   NOT NULL,
    unit_cost            NUMERIC(12,2) NOT NULL CONSTRAINT ck_parts_cost CHECK (unit_cost >= 0),
    compatible_models    VARCHAR(30)   NOT NULL,
    supplier_lead_days   SMALLINT      NOT NULL CONSTRAINT ck_parts_lead CHECK (supplier_lead_days >= 0)
);
COMMENT ON TABLE parts IS 'Parts catalogue with unit cost (INR) and supplier lead time.';

CREATE TABLE part_usage (
    usage_id       VARCHAR(12) PRIMARY KEY,
    work_order_id  VARCHAR(12) NOT NULL REFERENCES work_orders (work_order_id),
    part_id        VARCHAR(10) NOT NULL REFERENCES parts (part_id),
    quantity       INTEGER     NOT NULL CONSTRAINT ck_usage_qty CHECK (quantity > 0)
);
COMMENT ON TABLE part_usage IS 'Parts consumed per work order (line level).';

CREATE TABLE financials (
    work_order_id   VARCHAR(12)   PRIMARY KEY REFERENCES work_orders (work_order_id),
    billing_type    VARCHAR(30)   NOT NULL
        CONSTRAINT ck_fin_billing CHECK (billing_type IN ('Customer Paid', 'Service Plan', 'Warranty', 'Rework (No Charge)')),
    estimated_cost  NUMERIC(12,2) NOT NULL CONSTRAINT ck_fin_est CHECK (estimated_cost >= 0),
    labor_cost      NUMERIC(12,2) NOT NULL CONSTRAINT ck_fin_labor CHECK (labor_cost >= 0),
    parts_cost      NUMERIC(12,2) NOT NULL CONSTRAINT ck_fin_parts CHECK (parts_cost >= 0),
    revenue         NUMERIC(12,2) NOT NULL CONSTRAINT ck_fin_rev CHECK (revenue >= 0)
);
COMMENT ON TABLE financials IS 'Billing system of record per work order (INR, excl. GST); Rework (No Charge) rows carry zero revenue.';

CREATE TABLE feedback (
    feedback_id        VARCHAR(12) PRIMARY KEY,
    work_order_id      VARCHAR(12) NOT NULL UNIQUE REFERENCES work_orders (work_order_id),
    rating             SMALLINT    NOT NULL CONSTRAINT ck_feedback_rating CHECK (rating BETWEEN 1 AND 5),
    feedback_category  VARCHAR(40) NOT NULL,
    feedback_date      DATE        NOT NULL
);
COMMENT ON TABLE feedback IS 'Customer rating (1-5) for a work order; at most one per work order, not every job is rated.';

-- -----------------------------------------------------------------------------
-- Indexes (FK columns and common filter / grouping columns)
-- -----------------------------------------------------------------------------
CREATE INDEX ix_vehicles_customer   ON vehicles (customer_id);
CREATE INDEX ix_vehicles_model      ON vehicles (model);
CREATE INDEX ix_technicians_center  ON technicians (center_id);
CREATE INDEX ix_appt_vehicle        ON appointments (vehicle_id);
CREATE INDEX ix_appt_center_date    ON appointments (center_id, scheduled_date);
CREATE INDEX ix_appt_status         ON appointments (status);
CREATE INDEX ix_wo_technician       ON work_orders (technician_id);
CREATE INDEX ix_wo_service_type     ON work_orders (service_type);
CREATE INDEX ix_wo_check_in         ON work_orders (check_in_time);
CREATE INDEX ix_part_usage_wo       ON part_usage (work_order_id);
CREATE INDEX ix_part_usage_part     ON part_usage (part_id);
CREATE INDEX ix_parts_category      ON parts (part_category);
CREATE INDEX ix_feedback_rating     ON feedback (rating);
