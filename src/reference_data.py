"""Static reference data for the synthetic Ather service network.

All values are invented for portfolio use. Model names describe the vehicle
mix being simulated; no figures here come from Ather Energy.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Centre:
    center_id: str
    center_name: str
    city: str
    state: str
    region: str
    service_bays: int
    daily_job_capacity: int
    opened_date: str
    demand_weight: float  # relative share of customers served
    technicians: int  # rostered technicians
    parts_risk: float  # multiplier on stock-out probability (supply-chain distance)
    extra_lead_days: float  # mean extra booking lead time when slots are scarce
    junior_heavy_roster: bool  # roster staffed mainly by junior technicians


CENTRES: tuple[Centre, ...] = (
    Centre("C001", "Bengaluru - Indiranagar", "Bengaluru", "Karnataka", "South", 8, 22, "2019-06-01", 1.50, 3, 0.8, 1.5, False),
    Centre("C002", "Bengaluru - Whitefield", "Bengaluru", "Karnataka", "South", 7, 18, "2020-02-15", 1.25, 3, 0.8, 0.5, False),
    Centre("C003", "Chennai - Anna Nagar", "Chennai", "Tamil Nadu", "South", 6, 16, "2020-09-01", 0.98, 2, 0.9, 0.5, False),
    Centre("C004", "Hyderabad - Gachibowli", "Hyderabad", "Telangana", "South", 6, 15, "2021-03-10", 0.90, 2, 0.9, 0.5, False),
    Centre("C005", "Pune - Baner", "Pune", "Maharashtra", "West", 6, 15, "2021-07-01", 0.82, 2, 1.0, 0.5, False),
    Centre("C006", "Mumbai - Andheri", "Mumbai", "Maharashtra", "West", 5, 12, "2021-11-15", 0.96, 2, 1.0, 4.0, True),
    Centre("C007", "Delhi - Saket", "New Delhi", "Delhi", "North", 6, 15, "2021-05-01", 0.92, 2, 1.3, 0.8, False),
    Centre("C008", "Kolkata - Salt Lake", "Kolkata", "West Bengal", "East", 4, 10, "2022-09-01", 0.82, 2, 2.8, 0.5, False),
)

# model -> (category, [(variant, battery_kwh, share)], first sale date, last-sale weight growth)
MODELS = {
    "Ather 450X": ("Performance", [("450X 2.9kWh", 2.9, 0.45), ("450X 3.7kWh", 3.7, 0.55)], "2020-01-15"),
    "Ather 450 Apex": ("Performance", [("450 Apex 3.7kWh", 3.7, 1.0)], "2024-02-01"),
    "Ather Rizta": ("Family", [("Rizta S 2.9kWh", 2.9, 0.40), ("Rizta Z 2.9kWh", 2.9, 0.30), ("Rizta Z 3.7kWh", 3.7, 0.30)], "2024-06-01"),
}
MODEL_SHARE = {"Ather 450X": 0.44, "Ather 450 Apex": 0.11, "Ather Rizta": 0.45}

# Part catalogue: part_id, name, category, unit_cost (INR), compatible_models, supplier_lead_days
PARTS = (
    ("P001", "Brake Pad Set - Front", "Brakes", 650, "All", 3),
    ("P002", "Brake Pad Set - Rear", "Brakes", 600, "All", 3),
    ("P003", "Brake Fluid DOT4 250ml", "Brakes", 180, "All", 2),
    ("P004", "Brake Disc - Front", "Brakes", 1450, "All", 5),
    ("P005", "Front Tyre 12-inch", "Tyres", 1700, "All", 4),
    ("P006", "Rear Tyre 12-inch", "Tyres", 2100, "All", 4),
    ("P007", "Tubeless Valve Kit", "Tyres", 90, "All", 2),
    ("P008", "Drive Belt", "Drivetrain", 2300, "All", 6),
    ("P009", "Belt Pulley Set", "Drivetrain", 3800, "All", 7),
    ("P010", "12V Auxiliary Battery", "Battery & Electrical", 2200, "All", 5),
    ("P011", "DC-DC Converter", "Battery & Electrical", 5500, "All", 8),
    ("P012", "Main Wiring Harness", "Battery & Electrical", 4200, "All", 9),
    ("P013", "Battery Management System Board", "Battery & Electrical", 9800, "All", 10),
    ("P014", "Battery Cell Module", "Battery & Electrical", 18500, "All", 14),
    ("P015", "Battery Thermal Pad Kit", "Battery & Electrical", 850, "All", 5),
    ("P016", "Portable Charger", "Charging", 6500, "All", 7),
    ("P017", "Charging Cable", "Charging", 1400, "All", 5),
    ("P018", "Charging Port Assembly", "Charging", 2600, "All", 8),
    ("P019", "Onboard Charger Module", "Charging", 7800, "450 Series", 12),
    ("P020", "Motor Controller - 450 Series", "Motor & Controller", 14500, "450 Series", 12),
    ("P021", "Motor Controller - Rizta", "Motor & Controller", 13200, "Ather Rizta", 12),
    ("P022", "Motor Bearing Kit", "Motor & Controller", 1200, "All", 6),
    ("P023", "Motor Hall Sensor", "Motor & Controller", 1800, "All", 8),
    ("P024", "Motor Assembly", "Motor & Controller", 32000, "All", 18),
    ("P025", "TFT Dashboard - 450 Series", "Dashboard & Display", 11500, "450 Series", 14),
    ("P026", "Dashboard Display - Rizta", "Dashboard & Display", 9800, "Ather Rizta", 12),
    ("P027", "Handlebar Switch Cluster", "Dashboard & Display", 1900, "All", 7),
    ("P028", "LED Headlamp Assembly", "Body & Lighting", 4800, "All", 8),
    ("P029", "Front Panel", "Body & Lighting", 2700, "All", 7),
    ("P030", "Side Panel Set", "Body & Lighting", 3400, "All", 7),
    ("P031", "Rear View Mirror Pair", "Body & Lighting", 650, "All", 3),
    ("P032", "Tail Lamp Assembly", "Body & Lighting", 1600, "All", 6),
    ("P033", "Apex Body Panel Kit", "Body & Lighting", 4900, "Ather 450 Apex", 15),
    ("P034", "Front Fork Oil Seal Kit", "Suspension", 550, "All", 4),
    ("P035", "Rear Shock Absorber", "Suspension", 3100, "All", 7),
    ("P036", "Front Fork Assembly", "Suspension", 7200, "All", 10),
    ("P037", "Service Consumables Kit", "Consumables", 250, "All", 1),
    ("P038", "Fastener Kit", "Consumables", 120, "All", 1),
    ("P039", "Dust Seal Kit", "Consumables", 200, "All", 2),
)

# Base probability that a required part is out of stock at a centre.
STOCKOUT_BASE = {
    "Consumables": 0.004,
    "Brakes": 0.02,
    "Tyres": 0.03,
    "Drivetrain": 0.05,
    "Battery & Electrical": 0.08,
    "Charging": 0.10,
    "Motor & Controller": 0.16,
    "Dashboard & Display": 0.18,
    "Body & Lighting": 0.06,
    "Suspension": 0.05,
}

# Part "roles" resolve to a concrete part based on the vehicle model.
ROLE_PARTS = {
    "pad_front": {"*": "P001"},
    "pad_rear": {"*": "P002"},
    "brake_fluid": {"*": "P003"},
    "brake_disc": {"*": "P004"},
    "tyre_front": {"*": "P005"},
    "tyre_rear": {"*": "P006"},
    "valve": {"*": "P007"},
    "belt": {"*": "P008"},
    "pulley": {"*": "P009"},
    "aux_battery": {"*": "P010"},
    "dcdc": {"*": "P011"},
    "harness": {"*": "P012"},
    "bms": {"*": "P013"},
    "cell_module": {"*": "P014"},
    "thermal_pad": {"*": "P015"},
    "charger": {"*": "P016"},
    "charge_cable": {"*": "P017"},
    "charge_port": {"*": "P018"},
    "onboard_charger": {"Ather 450X": "P019", "Ather 450 Apex": "P019"},
    "controller": {"Ather 450X": "P020", "Ather 450 Apex": "P020", "Ather Rizta": "P021"},
    "motor_bearing": {"*": "P022"},
    "hall_sensor": {"*": "P023"},
    "motor_assembly": {"*": "P024"},
    "dashboard": {"Ather 450X": "P025", "Ather 450 Apex": "P025", "Ather Rizta": "P026"},
    "switch_cluster": {"*": "P027"},
    "headlamp": {"*": "P028"},
    "front_panel": {"*": "P029"},
    "side_panel": {"*": "P030"},
    "mirror": {"*": "P031"},
    "tail_lamp": {"*": "P032"},
    "apex_body_kit": {"Ather 450 Apex": "P033"},
    "fork_seal": {"*": "P034"},
    "shock": {"*": "P035"},
    "fork_assembly": {"*": "P036"},
    "consumables": {"*": "P037"},
    "fasteners": {"*": "P038"},
    "dust_seal": {"*": "P039"},
}


@dataclass(frozen=True)
class ServiceType:
    name: str
    base_hours: float
    complex_job: bool
    warranty_eligible: bool
    parts: tuple[tuple[str, float, int], ...]  # (role, probability, max quantity)


SERVICE_TYPES: dict[str, ServiceType] = {
    s.name: s
    for s in (
        ServiceType("Periodic Service", 1.5, False, False, (
            ("consumables", 1.0, 1), ("brake_fluid", 0.35, 1), ("pad_front", 0.18, 1),
            ("pad_rear", 0.15, 1), ("fasteners", 0.30, 2), ("dust_seal", 0.20, 1))),
        ServiceType("Battery Health Check", 1.0, False, True, (
            ("thermal_pad", 0.15, 1), ("aux_battery", 0.12, 1), ("bms", 0.04, 1), ("cell_module", 0.02, 1))),
        ServiceType("Software Update Support", 0.75, False, False, (("harness", 0.03, 1),)),
        ServiceType("Brake Service", 1.5, False, False, (
            ("pad_front", 0.70, 1), ("pad_rear", 0.60, 1), ("brake_fluid", 0.80, 1), ("brake_disc", 0.15, 1))),
        ServiceType("Tyre Replacement", 1.0, False, False, (
            ("tyre_front", 0.55, 1), ("tyre_rear", 0.65, 1), ("valve", 0.80, 2))),
        ServiceType("Belt Drive Service", 2.0, False, False, (("belt", 0.85, 1), ("pulley", 0.20, 1))),
        ServiceType("Motor & Controller Repair", 4.0, True, True, (
            ("controller", 0.45, 1), ("hall_sensor", 0.35, 1), ("motor_bearing", 0.30, 1), ("motor_assembly", 0.07, 1))),
        ServiceType("Charging System Repair", 2.5, True, True, (
            ("charger", 0.35, 1), ("charge_cable", 0.35, 1), ("charge_port", 0.30, 1), ("onboard_charger", 0.15, 1))),
        ServiceType("Electrical Diagnostics", 2.0, True, True, (
            ("harness", 0.25, 1), ("dcdc", 0.20, 1), ("switch_cluster", 0.25, 1),
            ("dashboard", 0.12, 1), ("aux_battery", 0.15, 1))),
        ServiceType("Suspension Service", 2.5, False, False, (
            ("fork_seal", 0.70, 2), ("shock", 0.35, 1), ("fork_assembly", 0.08, 1))),
        ServiceType("Accident & Body Repair", 5.0, True, False, (
            ("front_panel", 0.50, 1), ("side_panel", 0.45, 1), ("mirror", 0.40, 1), ("headlamp", 0.30, 1),
            ("tail_lamp", 0.25, 1), ("apex_body_kit", 0.50, 1), ("fork_assembly", 0.10, 1))),
    )
}

# Relative frequency of unplanned (non-periodic) visits by type.
REPAIR_MIX = {
    "Battery Health Check": 14,
    "Software Update Support": 10,
    "Brake Service": 14,
    "Tyre Replacement": 12,
    "Belt Drive Service": 8,
    "Motor & Controller Repair": 5,
    "Charging System Repair": 8,
    "Electrical Diagnostics": 10,
    "Suspension Service": 6,
    "Accident & Body Repair": 7,
}

SKILL_LEVELS = {
    # level: (hourly_cost INR, labour-time multiplier, extra QC-failure prob, extra comeback prob, years range)
    "Junior": (210.0, 1.22, 0.05, 0.030, (0, 2)),
    "Mid": (280.0, 1.06, 0.02, 0.012, (2, 5)),
    "Senior": (360.0, 0.97, 0.00, 0.004, (5, 9)),
    "Master": (450.0, 0.90, -0.01, 0.000, (9, 15)),
}

BOOKING_CHANNELS = {"Ather App": 0.55, "Call Centre": 0.20, "Walk-in": 0.15, "Website": 0.10}

CANCELLATION_REASONS = (
    "Customer Rescheduled",
    "Long Wait for Slot",
    "Issue Resolved via OTA Update",
    "Price Concern",
    "Visited Another Workshop",
    "Personal Reasons",
)

FEEDBACK_POSITIVE = {"Positive Experience": 0.6, "Service Quality": 0.25, "Staff Behaviour": 0.15}
FEEDBACK_NEUTRAL = {"Communication": 0.35, "Staff Behaviour": 0.2, "Service Quality": 0.25, "Pricing": 0.2}
