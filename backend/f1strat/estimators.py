"""Online estimators: tyre degradation, rival pit timing, energy.

Own cars use the lower-noise sensor-informed filter. Rivals are read only from
official timing, so their estimates stay wider and are always labelled.
"""
from __future__ import annotations

import math

import numpy as np

from .catalog import Circuit, id_text
from .laptime import (GREEN, OFFSET, TRACK_EVO_PER_LAP, Tables, deg_rate, fuel_seconds, life_laps)


class DegFilter:
    """Bayesian linear model: y = a + m * f_deg(compound, age) + noise.

    `a` is the car's clean pace offset and `m` scales the degradation curve.
    The FP long-run result is the prior; each clean lap tightens the posterior.
    """

    def __init__(self, a0: float, a_sd: float, m0: float, m_sd: float, sigma: float):
        self.x = np.array([a0, m0], dtype=float)
        self.P = np.diag([a_sd ** 2, m_sd ** 2])
        self.sigma = sigma
        self.laps_used = 0

    def update(self, deg_x: float, y: float, sigma_scale: float = 1.0) -> None:
        h = np.array([1.0, deg_x])
        r = (self.sigma * sigma_scale) ** 2
        s = float(h @ self.P @ h + r)
        gain = self.P @ h / s
        self.x = self.x + gain * (y - float(h @ self.x))
        self.P = self.P - np.outer(gain, h) @ self.P
        self.laps_used += 1

    def new_stint(self) -> None:
        # The tyre set changed: keep what we learned but admit it may not carry over.
        self.P = self.P + np.diag([0.02 ** 2, 0.10 ** 2])

    @property
    def pace(self) -> float:
        return float(self.x[0])

    @property
    def mult(self) -> float:
        return float(np.clip(self.x[1], 0.3, 3.0))

    @property
    def pace_sd(self) -> float:
        return float(math.sqrt(max(self.P[0, 0], 1e-6)))

    @property
    def mult_sd(self) -> float:
        return float(math.sqrt(max(self.P[1, 1], 1e-6)))


def lap_residual(circuit: Circuit, lap: int, comp: int, lap_time: float, energy_delta: float = 0.0) -> float:
    """Remove everything but pace and degradation from a measured lap."""
    return (lap_time - circuit.base_lap - fuel_seconds(circuit, lap) + TRACK_EVO_PER_LAP * lap
            - float(OFFSET[comp]) - energy_delta)


def confidence_label(mult_sd: float, rival: bool) -> str:
    # The PRD caps rival tyre estimates at "sedang"; they are never directly measured.
    if mult_sd < 0.10 and not rival:
        return "tinggi"
    if mult_sd < 0.22:
        return "sedang"
    return "rendah"


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def pit_probability(circuit: Circuit, comp: int, age: int, tendency: float, laps_left: int, needs_stop: bool,
                    neighbour_pitted: bool, status: int, stops: int = 0) -> float:
    """Chance a car pits on this lap or the next, from its stint-length distribution."""
    if laps_left <= 1:
        return 1.0 if needs_stop else 0.0
    life = life_laps(circuit, comp)
    if not needs_stop and life * 1.05 >= age + laps_left:
        return 0.02
    mean = life * (0.80 - 0.07 * tendency)
    sd = 4.0
    survive = max(1.0 - _norm_cdf((age - mean) / sd), 1e-3)
    window = _norm_cdf((age + 2 - mean) / sd) - _norm_cdf((age - mean) / sd)
    p = min(window / survive, 0.97)
    # Once a car is legal, a further stop is the exception and needs a reason to happen.
    if not needs_stop:
        reach = age + laps_left
        p *= 0.35 if stops == 1 and reach > life * 1.35 else 0.08
    if neighbour_pitted and age > 0.6 * life:
        p = 1.0 - (1.0 - p) * 0.60
    if status != GREEN and age >= 8 and laps_left > 6:
        p = 1.0 - (1.0 - p) * 0.40
    return float(p)


def energy_range(trap_deficit_kph: float) -> tuple[float, float]:
    """Rival charge as a range (MJ). End-of-straight speed is a weak proxy, so never one number."""
    if trap_deficit_kph > 7.0:
        return (0.0, 1.0)
    if trap_deficit_kph > 3.0:
        return (0.5, 2.0)
    if trap_deficit_kph < -3.0:
        return (1.5, 4.0)
    return (1.0, 3.0)


def tyre_card(tables: Tables, comp: int, age: int, flt: DegFilter) -> dict:
    return {
        "deg_s_lap": round(deg_rate(tables, comp, age, flt.mult), 3),
        "deg_low": round(deg_rate(tables, comp, age, max(flt.mult - flt.mult_sd, 0.1)), 3),
        "deg_high": round(deg_rate(tables, comp, age, flt.mult + flt.mult_sd), 3),
    }


def energy_advice(circuit: Circuit, soc: float, gap_ahead: float | None, gap_behind: float | None,
                  ahead: str | None, behind: str | None, status: int) -> dict:
    """Turn charge state and gaps into one instruction the race engineer can relay."""
    advice = _energy_advice(circuit, soc, gap_ahead, gap_behind, ahead, behind, status)
    return advice | {"detail": id_text(advice["detail"])}


def _energy_advice(circuit: Circuit, soc: float, gap_ahead: float | None, gap_behind: float | None,
                   ahead: str | None, behind: str | None, status: int) -> dict:
    attack_cost = 1.1
    limit = circuit.recharge_race_mj
    payload = {"soc": round(soc, 2), "recharge_limit": limit, "recharge_overtake": circuit.recharge_overtake_mj,
               "soc_after_attack": round(max(soc - attack_cost, 0.0), 2), "vulnerable": False}
    if status != GREEN:
        return payload | {"mode": "TABUNG", "headline": "Isi baterai selama netralisasi",
                          "detail": f"Targetkan penuh 4,0 MJ sebelum restart. Sekarang {soc:.1f} MJ."}
    if gap_ahead is not None and gap_ahead <= circuit.detection_gap_s:
        if soc >= 1.6:
            after = soc - attack_cost
            risky = gap_behind is not None and gap_behind < 1.2 and after < 1.2
            detail = f"{ahead} dalam {gap_ahead:.1f} dtk di garis deteksi. Sisa setelah serangan {after:.1f} MJ."
            if risky:
                detail += f" {behind} {gap_behind:.1f} dtk di belakang bisa membalas di straight berikutnya."
            return payload | {"mode": "SERANG", "headline": "Pakai Overtake Mode lap depan", "detail": detail,
                              "vulnerable": risky}
        return payload | {"mode": "TABUNG", "headline": "Tabung dulu, belum cukup untuk menyerang",
                          "detail": f"Butuh sekitar 1,6 MJ, sekarang {soc:.1f} MJ. Serang satu lap lagi."}
    if gap_behind is not None and gap_behind <= circuit.detection_gap_s:
        if soc >= 1.0:
            return payload | {"mode": "BERTAHAN", "headline": "Boost di zona keluar tikungan",
                              "detail": f"{behind} {gap_behind:.1f} dtk di belakang. Sisakan minimal 1,0 MJ."}
        return payload | {"mode": "TABUNG", "headline": "Baterai rendah saat ditekan",
                          "detail": f"{behind} mengancam dan baterai {soc:.1f} MJ. Panen di tikungan lambat."}
    if gap_ahead is not None and gap_ahead <= 2.0:
        return payload | {"mode": "TABUNG", "headline": "Siapkan serangan",
                          "detail": f"{ahead} {gap_ahead:.1f} dtk di depan. Tabung agar masuk jarak deteksi dengan 2,5 MJ."}
    return payload | {"mode": "NETRAL", "headline": "Jaga ritme", "detail": "Tidak ada duel dekat. Deploy netral."}
