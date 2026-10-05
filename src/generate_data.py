"""Generate the synthetic Ather EV service-operations dataset.

The generator simulates an 8-centre service network from vehicle sales through
bookings, workshop execution, billing, and customer feedback. Operational
patterns (capacity pressure, parts stock-outs, skill-driven rework) emerge
from the simulation rather than being written into the outputs directly, so
the downstream analysis has genuine signal to discover.

After simulation, a small, documented share of data-entry defects is injected
so the data-quality pipeline has realistic problems to detect and repair.

Usage:
    python -m src.generate_data
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from src.config import (
    FLEET_DISCOUNT,
    LABOUR_BILL_RATE,
    PARTS_MARKUP,
    PERIOD_END,
    PERIOD_START,
    PRODUCTIVE_HOURS_PER_DAY,
    PROMISE_BUFFER_HOURS,
    RAW_DIR,
    SEED,
    SERVICE_PLAN_FEE,
    SHOP_CLOSE_HOUR,
    SHOP_OPEN_HOUR,
    WARRANTY_LABOUR_RATE,
    WARRANTY_PARTS_MARKUP,
)
from src.reference_data import (
    BOOKING_CHANNELS,
    CANCELLATION_REASONS,
    CENTRES,
    FEEDBACK_NEUTRAL,
    FEEDBACK_POSITIVE,
    MODEL_SHARE,
    MODELS,
    PARTS,
    REPAIR_MIX,
    ROLE_PARTS,
    SERVICE_TYPES,
    SKILL_LEVELS,
    STOCKOUT_BASE,
    Centre,
)

N_VEHICLES = 5300
DOW_WEIGHT = np.array([1.10, 0.95, 0.95, 1.00, 1.05, 1.55, 0.0])  # Mon..Sun (closed Sunday)
REPAIR_SEASON = {1: 0.9, 2: 0.9, 3: 0.95, 4: 1.0, 5: 1.05, 6: 1.3, 7: 1.4, 8: 1.35, 9: 1.2, 10: 1.1, 11: 1.05, 12: 0.9}
PERIODIC_SEASON = {10: 1.15, 11: 1.10}
COMPLEX_COMEBACK_TYPES = {"Electrical Diagnostics", "Motor & Controller Repair", "Charging System Repair"}
DT_FMT = "%Y-%m-%d %H:%M:%S"

PART_INDEX = {p[0]: p for p in PARTS}


# --------------------------------------------------------------------------- #
# Shop-hours clock
# --------------------------------------------------------------------------- #
def align_to_open(ts: datetime) -> datetime:
    """Return the earliest moment at or after ``ts`` when the workshop is open."""
    while True:
        if ts.weekday() == 6:
            ts = datetime.combine(ts.date() + timedelta(days=1), datetime.min.time()).replace(hour=SHOP_OPEN_HOUR)
            continue
        opening = ts.replace(hour=SHOP_OPEN_HOUR, minute=0, second=0, microsecond=0)
        closing = ts.replace(hour=SHOP_CLOSE_HOUR, minute=0, second=0, microsecond=0)
        if ts < opening:
            return opening
        if ts >= closing:
            ts = opening + timedelta(days=1)
            continue
        return ts


def add_work_hours(ts: datetime, hours: float) -> datetime:
    """Advance ``ts`` by ``hours`` of workshop time (Mon-Sat, open hours only)."""
    ts = align_to_open(ts)
    remaining = max(hours, 0.0)
    while remaining > 1e-9:
        closing = ts.replace(hour=SHOP_CLOSE_HOUR, minute=0, second=0, microsecond=0)
        available = (closing - ts).total_seconds() / 3600
        if remaining <= available:
            return ts + timedelta(hours=remaining)
        remaining -= available
        ts = align_to_open(closing)
    return ts


def round_quarter(x: float) -> float:
    return max(0.25, round(x * 4) / 4)


# --------------------------------------------------------------------------- #
# Internal simulation records
# --------------------------------------------------------------------------- #
@dataclass
class Visit:
    vehicle_idx: int
    center_id: str
    day: date
    service_type: str
    channel: str
    lead_days: int
    slot_hour: float
    status: str = "Completed"
    cancellation_reason: str | None = None
    quoted_parts: list[tuple[str, int]] = field(default_factory=list)
    estimated_hours: float = 0.0
    is_comeback: bool = False


class ServiceDataGenerator:
    def __init__(self, seed: int = SEED, n_vehicles: int = N_VEHICLES) -> None:
        self.rng = np.random.default_rng(seed)
        self.n_vehicles = n_vehicles
        self.centres = {c.center_id: c for c in CENTRES}
        self.days = [PERIOD_START + timedelta(days=i) for i in range((PERIOD_END - PERIOD_START).days + 1)]
        dow = np.array([DOW_WEIGHT[d.weekday()] for d in self.days])
        self.cw_repair = np.cumsum(dow * np.array([REPAIR_SEASON[d.month] for d in self.days]))
        self.day_w_periodic = dow * np.array([PERIODIC_SEASON.get(d.month, 1.0) for d in self.days])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _choice(self, options: dict[str, float]) -> str:
        keys = list(options)
        p = np.array([options[k] for k in keys], dtype=float)
        return keys[self.rng.choice(len(keys), p=p / p.sum())]

    def _day_idx(self, d: date) -> int:
        return (d - PERIOD_START).days

    def _sample_repair_day(self, start_idx: int, end_idx: int) -> int:
        lo = self.cw_repair[start_idx - 1] if start_idx > 0 else 0.0
        hi = self.cw_repair[end_idx]
        u = self.rng.uniform(lo, hi)
        return int(np.clip(np.searchsorted(self.cw_repair, u, side="left"), start_idx, end_idx))

    def _snap_working_day(self, target_idx: int, start_idx: int, end_idx: int) -> int | None:
        lo, hi = max(start_idx, target_idx - 3), min(end_idx, target_idx + 3)
        if lo > hi:
            return None
        w = self.day_w_periodic[lo : hi + 1]
        if w.sum() == 0:
            return None
        return lo + int(self.rng.choice(len(w), p=w / w.sum()))

    # ------------------------------------------------------------------ #
    # Masters
    # ------------------------------------------------------------------ #
    def _build_customers_and_vehicles(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        centre_ids = [c.center_id for c in CENTRES]
        centre_p = np.array([c.demand_weight for c in CENTRES])
        centre_p /= centre_p.sum()
        customers, vehicles = [], []
        cust_n = 0
        while len(vehicles) < self.n_vehicles:
            cust_n += 1
            ctype = self._choice({"Individual": 0.935, "Fleet": 0.035, "Corporate": 0.03})
            if ctype == "Individual":
                n_veh = 2 if self.rng.random() < 0.06 else 1
            elif ctype == "Fleet":
                n_veh = int(self.rng.integers(4, 21))
            else:
                n_veh = int(self.rng.integers(2, 7))
            home = self.centres[centre_ids[self.rng.choice(len(centre_ids), p=centre_p)]]
            customer_id = f"CU{cust_n:05d}"
            purchase_dates = []
            for _ in range(n_veh):
                share = MODEL_SHARE if ctype != "Fleet" else {"Ather 450X": 0.5, "Ather Rizta": 0.5}
                model = self._choice(share)
                category, variants, launch = MODELS[model]
                v_idx = self.rng.choice(len(variants), p=np.array([v[2] for v in variants]))
                variant, battery_kwh, _ = variants[v_idx]
                launch_d = date.fromisoformat(launch)
                span = (PERIOD_END - timedelta(days=20) - launch_d).days
                purchase = launch_d + timedelta(days=int(span * self.rng.random() ** 0.9))
                daily_km = {
                    "Individual": float(np.clip(self.rng.normal(26, 7), 8, 60)),
                    "Fleet": float(np.clip(self.rng.normal(80, 18), 40, 140)),
                    "Corporate": float(np.clip(self.rng.normal(38, 10), 15, 80)),
                }[ctype]
                plan_p = {"Individual": 0.30, "Fleet": 0.60, "Corporate": 0.50}[ctype]
                vehicles.append(
                    {
                        "vehicle_id": f"V{len(vehicles) + 1:05d}",
                        "customer_id": customer_id,
                        "model": model,
                        "variant": variant,
                        "vehicle_category": category,
                        "battery_kwh": battery_kwh,
                        "model_year": purchase.year,
                        "purchase_date": purchase,
                        "mileage_km": int((PERIOD_END - purchase).days * daily_km),
                        "sim_daily_km": daily_km,
                        "sim_home": home.center_id,
                        "sim_ctype": ctype,
                        "sim_plan": bool(self.rng.random() < plan_p),
                    }
                )
                purchase_dates.append(purchase)
            customers.append(
                {
                    "customer_id": customer_id,
                    "customer_type": ctype,
                    "city": home.city,
                    "region": home.region,
                    "registration_date": min(purchase_dates),
                }
            )
        return pd.DataFrame(customers), pd.DataFrame(vehicles)

    # ------------------------------------------------------------------ #
    # Demand
    # ------------------------------------------------------------------ #
    def _repair_type(self, model: str, age_years: float, month: int, ctype: str, odometer: float) -> str:
        w = dict(REPAIR_MIX)
        if model == "Ather 450X":
            w["Battery Health Check"] *= 1 + 0.25 * age_years
        else:
            w["Software Update Support"] *= 1.6
        if model == "Ather 450 Apex":  # newer platform, early-life electrical teething issues
            w["Electrical Diagnostics"] *= 1.4
            w["Motor & Controller Repair"] *= 1.3
        if month in (6, 7, 8, 9):
            w["Brake Service"] *= 1.5
            w["Tyre Replacement"] *= 1.3
            w["Electrical Diagnostics"] *= 1.6
        if ctype == "Fleet":
            w["Tyre Replacement"] *= 1.8
            w["Brake Service"] *= 1.4
            w["Belt Drive Service"] *= 1.3
        if odometer > 20000:
            w["Belt Drive Service"] *= 1.5
            w["Suspension Service"] *= 1.3
        return self._choice(w)

    def _pick_centre(self, home_id: str) -> str:
        if self.rng.random() < 0.92:
            return home_id
        region = self.centres[home_id].region
        same = [c.center_id for c in CENTRES if c.region == region and c.center_id != home_id]
        pool = same or [c.center_id for c in CENTRES if c.center_id != home_id]
        return pool[self.rng.integers(len(pool))]

    def _booking(self, centre: Centre) -> tuple[str, int, float]:
        channel = self._choice(BOOKING_CHANNELS)
        if channel == "Walk-in":
            return channel, 0, float(self.rng.uniform(9.5, 17.0))
        base = {"Ather App": 0.35, "Website": 0.30, "Call Centre": 0.25}[channel]
        lead = int(self.rng.geometric(base)) + int(self.rng.poisson(centre.extra_lead_days))
        slots = np.arange(9.0, 17.0, 0.5)
        slot_w = np.linspace(1.6, 0.6, len(slots))
        return channel, lead, float(self.rng.choice(slots, p=slot_w / slot_w.sum()))

    def _status(self, visit: Visit) -> None:
        if visit.channel == "Walk-in":
            p_cancel, p_noshow = 0.0, 0.0
        else:
            p_cancel = 0.045 + 0.007 * visit.lead_days + (0.02 if visit.day.weekday() == 0 else 0.0)
            if visit.service_type == "Software Update Support":
                p_cancel += 0.05
            p_noshow = 0.03 + 0.002 * visit.lead_days
        r = self.rng.random()
        if r < p_cancel:
            visit.status = "Cancelled"
            w = {reason: 1.0 for reason in CANCELLATION_REASONS}
            w["Long Wait for Slot"] = 0.3 + 0.25 * visit.lead_days
            w["Customer Rescheduled"] = 2.0
            w["Issue Resolved via OTA Update"] = 3.0 if visit.service_type == "Software Update Support" else 0.15
            visit.cancellation_reason = self._choice(w)
        elif r < p_cancel + p_noshow:
            visit.status = "No-Show"

    def _quote_parts(self, service_type: str, model: str) -> list[tuple[str, int]]:
        parts = []
        for role, prob, max_qty in SERVICE_TYPES[service_type].parts:
            part_id = ROLE_PARTS[role].get(model, ROLE_PARTS[role].get("*"))
            if part_id and self.rng.random() < prob:
                parts.append((part_id, int(self.rng.integers(1, max_qty + 1))))
        if service_type == "Tyre Replacement" and not any(p in ("P005", "P006") for p, _ in parts):
            parts.append(("P006", 1))
        return parts

    def _estimate_hours(self, service_type: str, parts: list[tuple[str, int]]) -> float:
        base = SERVICE_TYPES[service_type].base_hours
        return round_quarter(base * self.rng.uniform(0.95, 1.1) + 0.25 * max(0, len(parts) - 1))

    def _build_visits(self, vehicles: pd.DataFrame) -> list[Visit]:
        visits: list[Visit] = []
        end_idx = len(self.days) - 1
        base_rate = {"Ather 450X": 1.10, "Ather 450 Apex": 1.25, "Ather Rizta": 0.90}
        for v_idx, v in enumerate(vehicles.itertuples(index=False)):
            start = max(PERIOD_START, v.purchase_date + timedelta(days=15))
            if start > PERIOD_END:
                continue
            start_idx = self._day_idx(start)
            days_list: list[tuple[int, str]] = []

            interval = {"Individual": 182, "Fleet": 91, "Corporate": 120}[v.sim_ctype]
            compliance = {"Individual": 0.75, "Fleet": 0.88, "Corporate": 0.82}[v.sim_ctype]
            due = v.purchase_date + timedelta(days=30)
            while due <= PERIOD_END:
                if due >= start and self.rng.random() < compliance:
                    target = self._day_idx(due) + int(self.rng.normal(0, 12))
                    idx = self._snap_working_day(target, start_idx, end_idx)
                    if idx is not None:
                        days_list.append((idx, "Periodic Service"))
                due += timedelta(days=interval)

            years = (PERIOD_END - start).days / 365.25
            age_mid = ((start - v.purchase_date).days + (PERIOD_END - start).days / 2) / 365.25
            rate = base_rate[v.model] * (1 + 0.12 * age_mid) * (1.8 if v.sim_ctype == "Fleet" else 1.0)
            for _ in range(int(self.rng.poisson(rate * years))):
                idx = self._sample_repair_day(start_idx, end_idx)
                d = self.days[idx]
                odo = (d - v.purchase_date).days * v.sim_daily_km
                age = (d - v.purchase_date).days / 365.25
                days_list.append((idx, self._repair_type(v.model, age, d.month, v.sim_ctype, odo)))

            for idx, stype in days_list:
                centre = self.centres[self._pick_centre(v.sim_home)]
                channel, lead, slot = self._booking(centre)
                visit = Visit(v_idx, centre.center_id, self.days[idx], stype, channel, lead, slot)
                self._status(visit)
                visit.quoted_parts = self._quote_parts(stype, v.model)
                visit.estimated_hours = self._estimate_hours(stype, visit.quoted_parts)
                visits.append(visit)
        return visits

    # ------------------------------------------------------------------ #
    # Technicians
    # ------------------------------------------------------------------ #
    def _build_technicians(self) -> pd.DataFrame:
        rows, n = [], 0
        for c in CENTRES:
            n_tech = c.technicians
            if c.junior_heavy_roster:
                skills = ["Junior"] * (n_tech - 1) + ["Mid"]
            else:
                skills = [self._choice({"Junior": 0.25, "Mid": 0.35, "Senior": 0.28, "Master": 0.12}) for _ in range(n_tech)]
                if not any(s in ("Senior", "Master") for s in skills):
                    skills[0] = "Senior"
            for skill in skills:
                n += 1
                cost, _, _, _, (y_lo, y_hi) = SKILL_LEVELS[skill]
                years = int(self.rng.integers(y_lo, y_hi + 1))
                cert = {"Junior": "EV Level 1", "Mid": "EV Level 2", "Senior": "EV Level 3", "Master": "EV Level 4"}[skill]
                rows.append(
                    {
                        "technician_id": f"T{n:03d}",
                        "center_id": c.center_id,
                        "skill_level": skill,
                        "years_experience": years,
                        "certification": cert,
                        "hourly_cost": cost,
                        "shift_hours_per_day": 8,
                    }
                )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    # Workshop execution
    # ------------------------------------------------------------------ #
    def _stockout_prob(self, part_id: str, centre: Centre, model: str, d: date) -> float:
        _, _, category, _, compat, _ = PART_INDEX[part_id]
        p = STOCKOUT_BASE[category] * centre.parts_risk
        if compat == "Ather 450 Apex":
            p *= 1.6
        elif compat == "Ather Rizta":
            # Rizta-specific supply was thin during the 2025 ramp-up and normalised over 2026.
            months_in = (d.year - PERIOD_START.year) * 12 + d.month - 1
            p *= max(1.0, 2.0 - months_in / 18)
        return min(p, 0.6)

    def _execute(
        self,
        visits: list[Visit],
        vehicles: pd.DataFrame,
        techs: pd.DataFrame,
        load: dict[tuple[str, date], float],
    ) -> list[dict]:
        tech_by_centre = {cid: g.to_dict("records") for cid, g in techs.groupby("center_id")}
        assigned: dict[tuple[str, date], float] = {}
        results = []
        order = sorted((i for i, v in enumerate(visits) if v.status == "Completed"),
                       key=lambda i: (visits[i].center_id, visits[i].day, visits[i].slot_hour))
        for i in order:
            vis = visits[i]
            veh = self.vrec[vis.vehicle_idx]
            centre = self.centres[vis.center_id]
            stype = SERVICE_TYPES[vis.service_type]
            centre_techs = tech_by_centre[vis.center_id]
            day_load = load[(vis.center_id, vis.day)] / (len(centre_techs) * PRODUCTIVE_HOURS_PER_DAY)

            check_in = datetime.combine(vis.day, datetime.min.time()) + timedelta(
                hours=max(SHOP_OPEN_HOUR, vis.slot_hour + float(self.rng.normal(0.05, 0.2))))
            wait_mean = 0.2 + 2.8 * max(0.0, day_load - 0.8) + (0.3 if vis.day.weekday() == 5 else 0.0)
            wait = min(float(self.rng.gamma(2.0, wait_mean / 2)), 30.0)
            start = add_work_hours(check_in, wait)

            fit = {"Junior": 0.5, "Mid": 1.0, "Senior": 1.6, "Master": 1.8} if stype.complex_job else \
                  {"Junior": 1.5, "Mid": 1.2, "Senior": 0.8, "Master": 0.5}
            w = np.array([fit[t["skill_level"]] / (1 + assigned.get((t["technician_id"], vis.day), 0.0))
                          for t in centre_techs])
            tech = centre_techs[self.rng.choice(len(centre_techs), p=w / w.sum())]
            _, mult, qc_extra, cb_extra, _ = SKILL_LEVELS[tech["skill_level"]]

            age = (vis.day - veh.purchase_date).days / 365.25
            additional = self.rng.random() < (0.10 + (0.06 if stype.complex_job else 0.0) + 0.03 * age)
            parts = list(vis.quoted_parts)
            if additional:
                candidates = [ROLE_PARTS[r].get(veh.model, ROLE_PARTS[r].get("*")) for r, _, _ in stype.parts]
                candidates = [p for p in candidates if p and p not in {q for q, _ in parts}]
                if candidates:
                    parts.append((candidates[self.rng.integers(len(candidates))], 1))

            labour = vis.estimated_hours * mult * float(self.rng.lognormal(0, 0.15))
            labour *= (1.05 if day_load > 1.0 else 1.0) * (1.3 if additional else 1.0)
            qc_fail = self.rng.random() < (0.04 + qc_extra + (0.03 if stype.complex_job else 0.0)
                                           + (0.03 if day_load > 1.0 else 0.0))
            if qc_fail:
                labour += float(self.rng.uniform(0.5, 1.5))
            labour = max(0.25, round(labour, 2))
            assigned[(tech["technician_id"], vis.day)] = assigned.get((tech["technician_id"], vis.day), 0.0) + labour

            lead_days = [PART_INDEX[p][5] for p, _ in parts
                         if self.rng.random() < self._stockout_prob(p, centre, veh.model, vis.day)]
            if lead_days:
                diag = labour * 0.3
                paused = add_work_hours(start, diag)
                arrival = paused + timedelta(days=max(lead_days) * float(self.rng.uniform(0.6, 1.3)))
                resume = align_to_open(arrival)
                end = add_work_hours(resume, labour - diag)
                parts_wait = round((resume - paused).total_seconds() / 3600, 2)
            else:
                end = add_work_hours(start, labour)
                parts_wait = 0.0

            promised = add_work_hours(check_in, vis.estimated_hours + PROMISE_BUFFER_HOURS)
            comeback = (not vis.is_comeback) and self.rng.random() < (
                0.02 + cb_extra + (0.03 if vis.service_type in COMPLEX_COMEBACK_TYPES else 0.0)
                + (0.03 if qc_fail else 0.0) + (0.02 if day_load > 1.0 else 0.0))

            results.append(
                {
                    "visit_idx": i,
                    "technician_id": tech["technician_id"],
                    "hourly_cost": tech["hourly_cost"],
                    "check_in_time": check_in.replace(microsecond=0),
                    "start_time": start.replace(microsecond=0),
                    "end_time": end.replace(microsecond=0),
                    "promised_ready_time": promised.replace(microsecond=0),
                    "actual_hours": labour,
                    "parts_wait_hours": parts_wait,
                    "parts": parts,
                    "stockout": bool(lead_days),
                    "additional_work_found": bool(additional),
                    "qc_passed_first_time": not qc_fail,
                    "odometer_km": int((vis.day - veh.purchase_date).days * veh.sim_daily_km),
                    "spawn_comeback": bool(comeback),
                    "vehicle_age_years": age,
                }
            )
        return results

    def _comeback_visits(self, visits: list[Visit], work: list[dict], vehicles: pd.DataFrame) -> list[Visit]:
        new = []
        end_idx = len(self.days) - 1
        for w in work:
            if not w["spawn_comeback"]:
                continue
            src = visits[w["visit_idx"]]
            target = self._day_idx(w["end_time"].date()) + int(self.rng.integers(3, 26))
            if target > end_idx:
                continue
            idx = self._snap_working_day(target, target, min(end_idx, target + 3))
            if idx is None:
                continue
            channel = "Call Centre" if self.rng.random() < 0.5 else "Ather App"
            vis = Visit(src.vehicle_idx, src.center_id, self.days[idx], src.service_type, channel,
                        int(self.rng.integers(0, 3)), float(self.rng.choice(np.arange(9.0, 12.0, 0.5))),
                        is_comeback=True)
            if self.rng.random() < 0.03:
                vis.status, vis.cancellation_reason = "Cancelled", "Personal Reasons"
            model = self.vrec[src.vehicle_idx].model
            vis.quoted_parts = [p for p in self._quote_parts(src.service_type, model) if self.rng.random() < 0.3]
            vis.estimated_hours = round_quarter(SERVICE_TYPES[src.service_type].base_hours * 0.6)
            new.append(vis)
        return new

    # ------------------------------------------------------------------ #
    # Billing & feedback
    # ------------------------------------------------------------------ #
    def _financials(self, vis: Visit, w: dict, veh) -> dict:
        unit = {p[0]: p[3] for p in PARTS}
        parts_cost = sum(unit[p] * q for p, q in w["parts"])
        quoted_cost = sum(unit[p] * q for p, q in vis.quoted_parts)
        labour_cost = w["actual_hours"] * w["hourly_cost"]
        estimated_cost = vis.estimated_hours * w["hourly_cost"] + quoted_cost
        stype = SERVICE_TYPES[vis.service_type]

        if vis.is_comeback:
            billing, revenue = "Rework (No Charge)", 0.0
        elif stype.warranty_eligible and w["parts"] and w["vehicle_age_years"] < 3 and self.rng.random() < 0.85:
            billing = "Warranty"
            revenue = vis.estimated_hours * WARRANTY_LABOUR_RATE + parts_cost * WARRANTY_PARTS_MARKUP
        elif vis.service_type == "Periodic Service" and veh.sim_plan:
            billing = "Service Plan"
            extra_parts = sum(unit[p] * q for p, q in w["parts"] if p not in ("P037", "P038"))
            revenue = SERVICE_PLAN_FEE + extra_parts * PARTS_MARKUP
        else:
            billing = "Customer Paid"
            billed_hours = vis.estimated_hours * (1.35 if w["additional_work_found"] else 1.0)
            revenue = billed_hours * LABOUR_BILL_RATE + parts_cost * PARTS_MARKUP
            if veh.sim_ctype == "Fleet":
                revenue *= 1 - FLEET_DISCOUNT
        return {
            "billing_type": billing,
            "estimated_cost": round(estimated_cost, 2),
            "labor_cost": round(labour_cost, 2),
            "parts_cost": round(parts_cost, 2),
            "revenue": round(revenue, 2),
        }

    def _feedback(self, vis: Visit, w: dict, ctype: str) -> dict | None:
        late_h = (w["end_time"] - w["promised_ready_time"]).total_seconds() / 3600
        late = late_h > 0
        wait_h = (w["start_time"] - w["check_in_time"]).total_seconds() / 3600
        respond = {"Individual": 0.62, "Fleet": 0.35, "Corporate": 0.50}[ctype] + (0.10 if late or vis.is_comeback else 0.0)
        if self.rng.random() >= respond:
            return None
        score = 4.5
        if late:
            score -= 0.8 + 0.15 * min(late_h / 24, 5)
        if wait_h > 1.5:
            score -= 0.4
        if vis.is_comeback:
            score -= 1.2
        if w["additional_work_found"]:
            score -= 0.25
        rating = int(np.clip(round(score + self.rng.normal(0, 0.6)), 1, 5))

        if rating >= 4:
            category = self._choice(FEEDBACK_POSITIVE)
        elif vis.is_comeback:
            category = "Repeat Issue"
        elif w["stockout"]:
            category = "Parts Availability"
        elif late:
            category = "Turnaround Time"
        elif wait_h > 1.5:
            category = "Waiting Time"
        elif w["additional_work_found"]:
            category = "Pricing"
        else:
            category = self._choice(FEEDBACK_NEUTRAL)
        return {"rating": rating, "feedback_category": category,
                "feedback_date": (w["end_time"] + timedelta(days=int(self.rng.integers(0, 4)))).date()}

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #
    def generate(self) -> dict[str, pd.DataFrame]:
        customers, vehicles = self._build_customers_and_vehicles()
        self.vrec = list(vehicles.itertuples(index=False))
        visits = self._build_visits(vehicles)
        techs = self._build_technicians()

        load: dict[tuple[str, date], float] = {}
        for vis in visits:
            if vis.status == "Completed":
                load[(vis.center_id, vis.day)] = load.get((vis.center_id, vis.day), 0.0) + vis.estimated_hours
        work = self._execute(visits, vehicles, techs, load)

        comebacks = self._comeback_visits(visits, work, vehicles)
        base_n = len(visits)
        visits.extend(comebacks)
        for vis in comebacks:
            if vis.status == "Completed":
                load[(vis.center_id, vis.day)] = load.get((vis.center_id, vis.day), 0.0) + vis.estimated_hours
        work_cb = self._execute(visits[base_n:], vehicles, techs, load)
        for w in work_cb:
            w["visit_idx"] += base_n
        work.extend(work_cb)

        return self._assemble(customers, vehicles, techs, visits, work)

    def _assemble(self, customers, vehicles, techs, visits, work) -> dict[str, pd.DataFrame]:
        order = sorted(range(len(visits)), key=lambda i: (visits[i].day, visits[i].slot_hour, visits[i].center_id))
        appt_id = {i: f"AP{n + 1:06d}" for n, i in enumerate(order)}
        appointments = []
        for i in order:
            vis = visits[i]
            slot_minutes = int(round(vis.slot_hour * 60))  # round once so 15:59.6 carries to 16:00
            appointments.append(
                {
                    "appointment_id": appt_id[i],
                    "vehicle_id": self.vrec[vis.vehicle_idx].vehicle_id,
                    "center_id": vis.center_id,
                    "booking_date": vis.day - timedelta(days=vis.lead_days),
                    "scheduled_date": vis.day,
                    "scheduled_slot": f"{slot_minutes // 60:02d}:{slot_minutes % 60:02d}",
                    "booking_channel": vis.channel,
                    "requested_service_type": vis.service_type,
                    "status": vis.status,
                    "cancellation_reason": vis.cancellation_reason,
                }
            )

        work.sort(key=lambda w: (w["check_in_time"], w["visit_idx"]))
        work_orders, financials, part_usage, feedback = [], [], [], []
        for n, w in enumerate(work, start=1):
            vis = visits[w["visit_idx"]]
            veh = self.vrec[vis.vehicle_idx]
            wo_id = f"WO{n:06d}"
            work_orders.append(
                {
                    "work_order_id": wo_id,
                    "appointment_id": appt_id[w["visit_idx"]],
                    "technician_id": w["technician_id"],
                    "service_type": vis.service_type,
                    "check_in_time": w["check_in_time"],
                    "start_time": w["start_time"],
                    "end_time": w["end_time"],
                    "promised_ready_time": w["promised_ready_time"],
                    "estimated_hours": vis.estimated_hours,
                    "actual_hours": w["actual_hours"],
                    "parts_wait_hours": w["parts_wait_hours"],
                    "odometer_km": w["odometer_km"],
                    "additional_work_found": w["additional_work_found"],
                    "qc_passed_first_time": w["qc_passed_first_time"],
                }
            )
            financials.append({"work_order_id": wo_id, **self._financials(vis, w, veh)})
            for part_id, qty in w["parts"]:
                part_usage.append({"usage_id": f"PU{len(part_usage) + 1:06d}", "work_order_id": wo_id,
                                   "part_id": part_id, "quantity": qty})
            fb = self._feedback(vis, w, veh.sim_ctype)
            if fb:
                feedback.append({"feedback_id": f"FB{len(feedback) + 1:06d}", "work_order_id": wo_id, **fb})

        centres = pd.DataFrame(
            [{"center_id": c.center_id, "center_name": c.center_name, "city": c.city, "state": c.state,
              "region": c.region, "service_bays": c.service_bays, "daily_job_capacity": c.daily_job_capacity,
              "opened_date": c.opened_date} for c in CENTRES]
        )
        parts = pd.DataFrame(PARTS, columns=["part_id", "part_name", "part_category", "unit_cost",
                                             "compatible_models", "supplier_lead_days"])
        vehicles_out = vehicles[[c for c in vehicles.columns if not c.startswith("sim_")]]
        return {
            "customers": customers,
            "vehicles": vehicles_out,
            "service_centers": centres,
            "technicians": techs,
            "appointments": pd.DataFrame(appointments),
            "work_orders": pd.DataFrame(work_orders),
            "parts": parts,
            "part_usage": pd.DataFrame(part_usage),
            "financials": pd.DataFrame(financials),
            "feedback": pd.DataFrame(feedback),
        }


# --------------------------------------------------------------------------- #
# Data-entry defect injection
# --------------------------------------------------------------------------- #
def _sample_idx(rng: np.random.Generator, df: pd.DataFrame, frac: float) -> np.ndarray:
    n = max(1, int(len(df) * frac))
    return rng.choice(df.index.to_numpy(), size=n, replace=False)


def _append_duplicates(rng, df: pd.DataFrame, frac: float) -> tuple[pd.DataFrame, int]:
    dup = df.loc[_sample_idx(rng, df, frac)]
    out = pd.concat([df, dup], ignore_index=True)
    return out.sample(frac=1.0, random_state=int(rng.integers(1_000_000))).reset_index(drop=True), len(dup)


def inject_defects(tables: dict[str, pd.DataFrame], seed: int = SEED) -> tuple[dict[str, pd.DataFrame], dict]:
    """Inject realistic, documented data-entry defects into a copy of the clean tables."""
    rng = np.random.default_rng(seed + 1)
    t = {k: v.copy() for k, v in tables.items()}
    m: dict[str, dict[str, int]] = {}

    # Datetimes/dates are written as text so that format defects can be mixed in.
    for name, cols in {
        "appointments": ["booking_date", "scheduled_date"],
        "work_orders": ["check_in_time", "start_time", "end_time", "promised_ready_time"],
        "feedback": ["feedback_date"],
        "vehicles": ["purchase_date"],
        "customers": ["registration_date"],
    }.items():
        for c in cols:
            t[name][c] = t[name][c].map(lambda x: x.strftime(DT_FMT) if isinstance(x, datetime) else x.isoformat())

    # customers
    df = t["customers"]
    idx = _sample_idx(rng, df, 0.01)
    df.loc[idx, "region"] = df.loc[idx, "region"].map(lambda r: rng.choice([r.upper(), r.lower(), f" {r} "]))
    t["customers"], n_dup = _append_duplicates(rng, df, 0.004)
    m["customers"] = {"region_format_variants": len(idx), "duplicate_rows": n_dup}

    # vehicles
    df = t["vehicles"]
    first_bad = {"Ather 450X": [2017, 2018, 2019], "Ather 450 Apex": [2021, 2022, 2023], "Ather Rizta": [2021, 2022, 2023]}
    idx_year = _sample_idx(rng, df, 0.004)
    df.loc[idx_year, "model_year"] = [int(rng.choice(first_bad[mdl])) for mdl in df.loc[idx_year, "model"]]
    rest = df.index.difference(idx_year)
    idx_km = rng.choice(rest, size=max(1, int(len(df) * 0.003)), replace=False)
    df.loc[idx_km, "mileage_km"] = [int(rng.choice([-1, -1]) * rng.integers(100, 5000)) if rng.random() < 0.5
                                    else int(rng.integers(400_000, 900_000)) for _ in idx_km]
    idx_name = _sample_idx(rng, df, 0.005)
    variants = {"Ather 450X": ["ather 450x", "450X", "Ather 450x "], "Ather 450 Apex": ["Ather 450 apex", "450 Apex", "ATHER 450 APEX"],
                "Ather Rizta": ["ather rizta", "Rizta", " Ather Rizta"]}
    df.loc[idx_name, "model"] = [str(rng.choice(variants[mdl])) for mdl in df.loc[idx_name, "model"]]
    m["vehicles"] = {"impossible_model_year": len(idx_year), "impossible_mileage": len(idx_km),
                     "model_name_variants": len(idx_name)}

    # appointments
    df = t["appointments"]
    idx_status = _sample_idx(rng, df, 0.004)
    status_variants = {"Completed": ["completed", "COMPLETED", " Completed"], "Cancelled": ["cancelled", "Canceled", "CANCELLED "],
                       "No-Show": ["No Show", "no-show", "NO-SHOW"]}
    df.loc[idx_status, "status"] = [str(rng.choice(status_variants[s])) for s in df.loc[idx_status, "status"]]
    idx_date = _sample_idx(rng, df, 0.008)
    df.loc[idx_date, "scheduled_date"] = df.loc[idx_date, "scheduled_date"].map(
        lambda s: datetime.fromisoformat(s).strftime("%d/%m/%Y"))
    completed_ids = set(t["work_orders"]["appointment_id"])
    cand = df.index[df["appointment_id"].isin(completed_ids)]
    idx_center = rng.choice(cand, size=max(1, int(len(df) * 0.0015)), replace=False)
    df.loc[idx_center, "center_id"] = None
    rest = df.index.difference(idx_center)
    idx_orphan = rng.choice(rest, size=max(1, int(len(df) * 0.001)), replace=False)
    df.loc[idx_orphan, "vehicle_id"] = [f"V9{int(rng.integers(0, 9999)):04d}" for _ in idx_orphan]
    t["appointments"], n_dup = _append_duplicates(rng, df, 0.006)
    m["appointments"] = {"status_format_variants": len(idx_status), "ddmmyyyy_dates": len(idx_date),
                         "missing_center_id": len(idx_center), "orphan_vehicle_id": len(idx_orphan),
                         "duplicate_rows": n_dup}

    # work_orders
    df = t["work_orders"]
    idx_swap = _sample_idx(rng, df, 0.0025)
    df.loc[idx_swap, ["start_time", "end_time"]] = df.loc[idx_swap, ["end_time", "start_time"]].to_numpy()
    rest = df.index.difference(idx_swap)
    idx_tech_null = rng.choice(rest, size=max(1, int(len(df) * 0.002)), replace=False)
    df.loc[idx_tech_null, "technician_id"] = None
    rest = rest.difference(idx_tech_null)
    idx_tech_orphan = rng.choice(rest, size=max(1, int(len(df) * 0.001)), replace=False)
    df.loc[idx_tech_orphan, "technician_id"] = "T999"
    rest = rest.difference(idx_tech_orphan)
    idx_start_null = rng.choice(rest, size=max(1, int(len(df) * 0.001)), replace=False)
    df.loc[idx_start_null, "start_time"] = None
    idx_stype = _sample_idx(rng, df, 0.005)
    df.loc[idx_stype, "service_type"] = df.loc[idx_stype, "service_type"].map(
        lambda s: str(rng.choice([s.lower(), s.upper(), s.replace(" ", "  "), f"{s} "])))
    t["work_orders"], n_dup = _append_duplicates(rng, df, 0.004)
    m["work_orders"] = {"start_end_swapped": len(idx_swap), "missing_technician_id": len(idx_tech_null),
                        "orphan_technician_id": len(idx_tech_orphan), "missing_start_time": len(idx_start_null),
                        "service_type_format_variants": len(idx_stype), "duplicate_rows": n_dup}

    # financials
    df = t["financials"]
    paid = df.index[df["revenue"] > 0]
    idx_neg = rng.choice(paid, size=max(1, int(len(df) * 0.002)), replace=False)
    for i in idx_neg:
        col = "revenue" if rng.random() < 0.5 else "labor_cost"
        df.loc[i, col] = -abs(df.loc[i, col])
    rest = paid.difference(idx_neg)
    idx_null = rng.choice(rest, size=max(1, int(len(df) * 0.0015)), replace=False)
    df.loc[idx_null, "parts_cost"] = np.nan
    rest = rest.difference(idx_null)
    idx_x100 = rng.choice(rest, size=max(1, int(len(df) * 0.001)), replace=False)
    df.loc[idx_x100, "revenue"] = df.loc[idx_x100, "revenue"] * 100
    t["financials"], n_dup = _append_duplicates(rng, df, 0.003)
    m["financials"] = {"negative_amounts": len(idx_neg), "missing_parts_cost": len(idx_null),
                       "revenue_decimal_shift_x100": len(idx_x100), "duplicate_rows": n_dup}

    # feedback
    df = t["feedback"]
    df["rating"] = df["rating"].astype("Float64")
    idx_bad = _sample_idx(rng, df, 0.004)
    df.loc[idx_bad, "rating"] = [float(rng.choice([0, 6, 10])) for _ in idx_bad]
    rest = df.index.difference(idx_bad)
    idx_null = rng.choice(rest, size=max(1, int(len(df) * 0.002)), replace=False)
    df.loc[idx_null, "rating"] = pd.NA
    t["feedback"], n_dup = _append_duplicates(rng, df, 0.003)
    m["feedback"] = {"rating_out_of_range": len(idx_bad), "missing_rating": len(idx_null), "duplicate_rows": n_dup}

    # part_usage
    df = t["part_usage"]
    idx_qty = _sample_idx(rng, df, 0.002)
    df.loc[idx_qty, "quantity"] = [int(rng.choice([0, -1])) for _ in idx_qty]
    rest = df.index.difference(idx_qty)
    idx_part = rng.choice(rest, size=max(1, int(len(df) * 0.0005)), replace=False)
    df.loc[idx_part, "part_id"] = "P999"
    m["part_usage"] = {"non_positive_quantity": len(idx_qty), "orphan_part_id": len(idx_part)}

    return t, m


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tables = ServiceDataGenerator().generate()
    raw, manifest = inject_defects(tables)
    for name, df in raw.items():
        df.to_csv(RAW_DIR / f"{name}.csv", index=False)
    summary = {name: len(df) for name, df in raw.items()}
    (RAW_DIR / "generation_manifest.json").write_text(
        json.dumps({"seed": SEED, "period": [PERIOD_START.isoformat(), PERIOD_END.isoformat()],
                    "row_counts": summary, "injected_defects": manifest}, indent=2),
        encoding="utf-8",
    )
    for name, n in summary.items():
        print(f"{name:<16} {n:>7,}")


if __name__ == "__main__":
    main()
