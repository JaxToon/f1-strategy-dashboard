"""Lap-time model shared by the simulator, the estimators and the synthetic feed.

t_lap = t_base + k_fuel*m_fuel + offset(compound) + m*f_deg(compound, age, T_track)
        + warmup(compound, age) + wet(compound, wetness) + track_evo*lap
        + delta_traffic + delta_energy

The PRD formula lacks warm-up, track evolution and wetness; delta_traffic and
delta_energy are resolved car-by-car inside the simulator because they depend
on the cars around each other.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .catalog import Circuit

COMPOUNDS = ("S", "M", "H", "I", "W")
S, M, H, I, W = range(5)
SLICKS = (S, M, H)

OFFSET = np.array([0.0, 0.42, 0.85, 0.0, 0.0])
DEG_LIN = np.array([0.075, 0.045, 0.028, 0.05, 0.04])
DEG_QUAD = np.array([0.0016, 0.0008, 0.0004, 0.001, 0.001])
CLIFF_AGE = np.array([17.0, 27.0, 38.0, 30.0, 35.0])
WARMUP = np.array([0.35, 0.7, 1.1, 0.6, 0.6])

FUEL_S_PER_KG = 0.032
FUEL_START_KG = 75.0        # assumption: 2026 race fuel load, calibrate per circuit
TRACK_EVO_PER_LAP = 0.012
STATIONARY_MEAN = 2.45
STATIONARY_SD = 0.20
STACK_LOSS = 4.0            # second car of a double stack waits for the first
MAX_AGE = 90

GREEN, VSC, SC, RED = 0, 1, 2, 3
NEUTRAL_PIT_FACTOR = np.array([1.0, 0.60, 0.45, 0.0])
NEUTRAL_LAP_FACTOR = np.array([1.0, 1.30, 1.45, 1.45])

# Wetness where the fastest tyre changes, derived from wet_delta().
SLICK_TO_INTER = 0.155
INTER_TO_WET = 0.60


def wet_delta(comp: np.ndarray, wetness: np.ndarray | float) -> np.ndarray:
    """Seconds added to a lap for a compound at a given track wetness (0..1)."""
    comp = np.asarray(comp)
    w = np.asarray(wetness, dtype=float)
    slick = 34.0 * w
    inter = 7.0 - 16.0 * w + 30.0 * w * w
    wet = 13.0 - 8.0 * w
    return np.where(comp == I, inter, np.where(comp == W, wet, slick))


def fuel_seconds(circuit: Circuit, lap: float) -> float:
    remaining = max(0.0, 1.0 - lap / circuit.laps)
    return FUEL_S_PER_KG * FUEL_START_KG * remaining


def life_laps(circuit: Circuit, comp: int) -> float:
    """Stint length where the tyre stops being competitive."""
    return float(CLIFF_AGE[comp] / circuit.tyre_severity)


@dataclass(frozen=True)
class Tables:
    """Pre-computed degradation curves for one circuit at one track temperature."""
    deg: np.ndarray       # (compounds, age): seconds lost at that age
    deg_cum: np.ndarray   # (compounds, age+1): cumulative seconds over a stint


def build_tables(circuit: Circuit, track_temp: float) -> Tables:
    ages = np.arange(MAX_AGE, dtype=float)
    temp_factor = 1.0 + 0.015 * (track_temp - 35.0)
    sev = circuit.tyre_severity
    cliff = CLIFF_AGE[:, None] / sev
    over = np.clip(ages[None, :] - cliff, 0.0, None)
    deg = (DEG_LIN[:, None] * ages + DEG_QUAD[:, None] * ages * ages) * sev * temp_factor
    deg = deg + 0.06 * over * over
    deg_cum = np.concatenate([np.zeros((5, 1)), np.cumsum(deg, axis=1)], axis=1)
    return Tables(deg=deg, deg_cum=deg_cum)


def deg_rate(tables: Tables, comp: int, age: int, mult: float = 1.0) -> float:
    """Current degradation in s/lap, the form shown to the strategist."""
    a = min(max(age, 0), MAX_AGE - 2)
    return float((tables.deg[comp, a + 1] - tables.deg[comp, a]) * mult)


def pit_cost(circuit: Circuit, status: int = GREEN) -> float:
    return float(circuit.pit_lane_loss * NEUTRAL_PIT_FACTOR[status] + STATIONARY_MEAN)
