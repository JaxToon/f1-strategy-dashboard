"""Vectorised Monte Carlo race simulator for the whole grid.

Each candidate strategy is simulated against the same random draws (common
random numbers), so differences between candidates come from the decision and
not from sampling noise. That makes the confidence figure a paired comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .catalog import Circuit
from .laptime import (GREEN, H, I, M, MAX_AGE, NEUTRAL_LAP_FACTOR, NEUTRAL_PIT_FACTOR, OFFSET, RED, S,
                      SC, SLICK_TO_INTER, STACK_LOSS, STATIONARY_MEAN, STATIONARY_SD, TRACK_EVO_PER_LAP,
                      VSC, WARMUP, Tables, fuel_seconds, life_laps, wet_delta)

POINTS = np.array([25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * 30, dtype=float)
FOLLOW_GAP = 0.25
AUTO_PASS = 1.8
LAP_NOISE = 0.18
DNF_PER_LAP = 0.0007
NO_PIT = 9999


@dataclass
class Snapshot:
    """What the team believes about the race. Holds only observed or estimated values."""
    circuit: Circuit
    tables: Tables
    lap: int
    codes: list[str]
    cum: np.ndarray
    comp: np.ndarray
    age: np.ndarray
    used: np.ndarray            # bitmask of compounds already run
    stops: np.ndarray
    pace: np.ndarray
    pace_sd: np.ndarray
    deg_mult: np.ndarray
    deg_sd: np.ndarray
    soc: np.ndarray
    alive: np.ndarray
    tendency: np.ndarray
    own: list[int]
    own_plans: list[list[tuple[int, int]]]
    neutral_kind: int = GREEN
    neutral_left: int = 0
    wet_now: float = 0.0
    rain: tuple[int, int, float, int] | None = None
    points_weight: float = 1.0
    pit_p: np.ndarray | None = None   # chance each car stops around now, 1.0 if already in the lane
    in_pit: np.ndarray | None = None


@dataclass
class Cand:
    """A candidate: plans for own cars, indexed like Snapshot.own."""
    label: str
    plans: list[list[tuple[int, int]]]
    forced: tuple[int, int, int] | None = None   # (lap, kind, duration in laps)
    rain: tuple[int, int, float, int] | None = None
    reactive: bool = True                        # move a nearby stop into a neutralisation
    start: list[int] | None = None               # starting compound of own cars, pre-race only


@dataclass
class SimOut:
    n_cands: int
    n_sims: int
    pos: np.ndarray        # (rows, own)
    time: np.ndarray       # (rows, own)
    utility: np.ndarray    # (rows,)
    first_pit: np.ndarray  # (rows, cars): first stop lap of each car, NO_PIT if none
    neutral_lap: np.ndarray  # (rows,): first neutralisation lap, NO_PIT if none
    elapsed_ms: float = 0.0

    def rows(self, cand: int) -> np.ndarray:
        return np.arange(cand * self.n_sims, (cand + 1) * self.n_sims)


def _sample_neutral(circuit: Circuit, snap: Snapshot, n_sims: int, n_laps: int,
                    rng: np.random.Generator) -> np.ndarray:
    out = np.zeros((n_sims, n_laps), dtype=np.int8)
    p_sc = circuit.sc_per_race / circuit.laps
    p_vsc = circuit.vsc_per_race / circuit.laps
    p_red = circuit.red_per_race / circuit.laps
    draws = rng.random((n_sims, n_laps))
    durations = rng.integers(3, 6, size=(n_sims, n_laps))
    kind = np.zeros(n_sims, dtype=np.int8)
    left = np.zeros(n_sims, dtype=np.int32)
    if snap.neutral_left > 0:
        kind[:] = snap.neutral_kind
        left[:] = snap.neutral_left
    for k in range(n_laps):
        lapno = snap.lap + 1 + k
        boost = 3.0 if lapno == 1 else 1.0
        free = left <= 0
        new_sc = free & (draws[:, k] < p_sc * boost)
        new_vsc = free & ~new_sc & (draws[:, k] < (p_sc * boost + p_vsc))
        new_red = free & ~new_sc & ~new_vsc & (draws[:, k] < (p_sc * boost + p_vsc + p_red))
        kind[new_sc] = SC
        left[new_sc] = durations[new_sc, k]
        kind[new_vsc] = VSC
        left[new_vsc] = np.minimum(durations[new_vsc, k], 3) - 1
        kind[new_red] = RED
        left[new_red] = 1
        active = left > 0
        out[active, k] = kind[active]
        left[active] -= 1
    return out


def _wet_profile(rain: tuple[int, int, float, int] | None, base_lap: int, n_laps: int, now: float) -> np.ndarray:
    laps = base_lap + 1 + np.arange(n_laps)
    if rain is None:
        return np.maximum(now * np.power(0.85, np.arange(1, n_laps + 1)), 0.0)
    onset, ramp, peak, dry = rain
    rising = np.clip((laps - onset) / max(ramp, 1), 0.0, 1.0) * peak
    falling = np.clip(1.0 - (laps - dry) / 6.0, 0.0, 1.0)
    return np.maximum(rising * falling, now * np.power(0.85, np.arange(1, n_laps + 1)))


def _rival_target(circuit: Circuit, comp: np.ndarray, tendency: np.ndarray, jitter: np.ndarray,
                  life: np.ndarray) -> np.ndarray:
    return life[comp] * (0.80 - 0.07 * tendency) + jitter


def simulate(snap: Snapshot, cands: list[Cand], n_sims: int, seed: int = 0) -> SimOut:
    import time as _time
    started = _time.perf_counter()
    c = snap.circuit
    D = snap.tables.deg
    rng = np.random.default_rng(seed)
    N = len(snap.codes)
    C = len(cands)
    S_ = n_sims
    R = C * S_
    L = max(c.laps - snap.lap, 0)
    sim = np.tile(np.arange(S_), C)
    own = np.array(snap.own, dtype=np.int64)
    n_own = len(own)
    is_own = np.zeros(N, dtype=bool)
    is_own[own] = True
    own_index = np.full(N, -1, dtype=np.int64)
    own_index[own] = np.arange(n_own)
    rows = np.arange(R)

    # Draws are per simulated race and shared across candidates.
    pace_r = (snap.pace + rng.normal(0.0, 1.0, (S_, N)) * snap.pace_sd)[sim]
    mult_r = (snap.deg_mult * np.exp(rng.normal(0.0, 1.0, (S_, N)) * snap.deg_sd))[sim]
    noise = rng.normal(0.0, LAP_NOISE, (S_, max(L, 1), N)).astype(np.float32)
    stationary = (rng.normal(STATIONARY_MEAN, STATIONARY_SD, (S_, max(L, 1), N))
                  + (rng.random((S_, max(L, 1), N)) < 0.03) * rng.exponential(3.0, (S_, max(L, 1), N)))
    u_pass = rng.random((S_, max(L, 1), N)).astype(np.float32)
    u_opp = rng.random((S_, max(L, 1), N)).astype(np.float32)
    jitter = rng.normal(0.0, 2.5, (S_, N))
    retire_lap = snap.lap + rng.geometric(DNF_PER_LAP, (S_, N))

    neutral_s = _sample_neutral(c, snap, S_, max(L, 1), rng)
    neutral = neutral_s[sim].copy()
    wet = np.tile(_wet_profile(snap.rain, snap.lap, max(L, 1), snap.wet_now), (R, 1))
    for i, cand in enumerate(cands):
        rng_rows = slice(i * S_, (i + 1) * S_)
        if cand.forced is not None:
            lap, kind, dur = cand.forced
            start = lap - snap.lap - 1
            neutral[rng_rows, :] = 0
            if 0 <= start < L:
                neutral[rng_rows, start:start + dur] = kind
        if cand.rain is not None:
            wet[rng_rows] = _wet_profile(cand.rain, snap.lap, max(L, 1), snap.wet_now)

    # Own-car plans as padded arrays.
    max_stops = max((len(p) for cand in cands for p in cand.plans), default=0) + 1
    plan_lap = np.full((R, n_own, max_stops), NO_PIT, dtype=np.int32)
    plan_comp = np.zeros((R, n_own, max_stops), dtype=np.int8)
    reactive = np.zeros(R, dtype=bool)
    for i, cand in enumerate(cands):
        rng_rows = np.arange(i * S_, (i + 1) * S_)
        reactive[rng_rows] = cand.reactive
        for o, plan in enumerate(cand.plans):
            for j, (lap, comp) in enumerate(plan):
                plan_lap[rng_rows, o, j] = lap
                plan_comp[rng_rows, o, j] = comp
    plan_i = np.zeros((R, n_own), dtype=np.int32)

    cum = np.tile(snap.cum.astype(float), (R, 1))
    comp = np.tile(snap.comp.astype(np.int8), (R, 1))
    age = np.tile(snap.age.astype(np.int32), (R, 1))
    used = np.tile(snap.used.astype(np.int8), (R, 1))
    soc = np.tile(snap.soc.astype(np.float32), (R, 1))
    alive = np.tile(snap.alive, (R, 1))
    for i, cand in enumerate(cands):
        if cand.start is not None:
            comp[i * S_:(i + 1) * S_, own] = cand.start
            used[i * S_:(i + 1) * S_, own] = [1 << k for k in cand.start]
    first_pit = np.full((R, N), NO_PIT, dtype=np.int32)

    life = np.array([life_laps(c, k) for k in range(5)])
    target = _rival_target(c, comp, snap.tendency, jitter[sim], life)
    next_pit = snap.lap + np.maximum(1.0, target - age)
    remaining0 = c.laps - snap.lap
    fits = (life[comp] * 1.05 >= remaining0 + age) & _two_compounds(used)
    next_pit = np.where(fits, NO_PIT, next_pit)

    prev_status = np.full(R, snap.neutral_kind if snap.neutral_left > 0 else GREEN, dtype=np.int8)
    neutral_lap = np.full(R, NO_PIT, dtype=np.int32)

    pit_factor = NEUTRAL_PIT_FACTOR
    lap_factor = NEUTRAL_LAP_FACTOR
    pass_threshold = 0.25 + 1.4 * c.overtake_difficulty
    with np.errstate(invalid="ignore"):
        for k in range(L):
            lapno = snap.lap + 1 + k
            laps_left = c.laps - lapno
            st = neutral[:, k]
            wet_k = wet[:, k]
            any_wet = wet_k.max() > 0.01
            started_neutral = (st > GREEN) & (prev_status == GREEN)
            neutral_lap = np.where(started_neutral & (neutral_lap == NO_PIT), lapno, neutral_lap)

            alive &= lapno < retire_lap[sim]

            pit = (lapno >= next_pit) & alive & ~is_own
            if started_neutral.any():
                opp = started_neutral[:, None] & (age >= 8) & (laps_left > 6) & (u_opp[sim, k] < 0.6)
                pit |= opp & alive & ~is_own
            if laps_left <= 1:
                pit |= ~_two_compounds(used) & alive & ~is_own & (wet_k[:, None] < 0.05)
            forced_comp = None
            if any_wet:
                on_slick = comp <= H
                to_inter = on_slick & (wet_k[:, None] > SLICK_TO_INTER) & (u_opp[sim, k] < 0.55)
                to_slick = (comp == I) & (wet_k[:, None] < 0.08) & (laps_left > 3)
                pit |= (to_inter | to_slick) & alive & ~is_own
                forced_comp = (to_inter, to_slick)

            own_pit_comp = np.full((R, n_own), -1, dtype=np.int8)
            for o in range(n_own):
                idx = plan_i[:, o]
                planned = plan_lap[rows, o, idx]
                # <= because the loop starts from the leader's lap and a car behind can still be a lap short.
                due = planned <= lapno
                soon = reactive & started_neutral & (planned > lapno) & (planned - lapno <= 8)
                rain_react = reactive & (wet_k > SLICK_TO_INTER) & (comp[:, own[o]] <= H)
                dry_react = reactive & (wet_k < 0.08) & (comp[:, own[o]] == I) & (laps_left > 3)
                go = (due | soon) & alive[:, own[o]]
                own_pit_comp[go, o] = plan_comp[rows[go], o, idx[go]]
                plan_i[go, o] += 1
                own_pit_comp[rain_react & alive[:, own[o]], o] = I
                own_pit_comp[dry_react & alive[:, own[o]], o] = M

            own_pit = np.zeros((R, N), dtype=bool)
            own_pit[:, own] = own_pit_comp >= 0
            pit_all = pit | own_pit

            age_i = np.minimum(age, MAX_AGE - 1)
            lap_time = (c.base_lap + fuel_seconds(c, lapno) - TRACK_EVO_PER_LAP * lapno
                        + pace_r + OFFSET[comp] + D[comp, age_i] * mult_r + noise[sim, k])
            fresh = age == 0
            if fresh.any():
                lap_time = lap_time + fresh * WARMUP[comp]
            if any_wet:
                lap_time = lap_time + wet_delta(comp, wet_k[:, None])
            low_soc = soc < 0.5
            if low_soc.any():
                lap_time = lap_time + low_soc * 0.30

            # Neutralised laps run at a delta, so the pace spread collapses.
            neutral_rows = st > GREEN
            if neutral_rows.any():
                slow = c.base_lap * lap_factor[st[neutral_rows]]
                lap_time[neutral_rows] = slow[:, None]

            cost = np.zeros((R, N))
            if pit_all.any():
                r, n = np.nonzero(pit_all)
                cost[r, n] = c.pit_lane_loss * pit_factor[st[r]] + stationary[sim[r], k, n]
                if n_own == 2:
                    both = pit_all[:, own[0]] & pit_all[:, own[1]]
                    if both.any():
                        behind = np.where(cum[:, own[1]] >= cum[:, own[0]], own[1], own[0])
                        cost[rows[both], behind[both]] += STACK_LOSS
                first_pit[r, n] = np.minimum(first_pit[r, n], lapno)

                new_comp = _rival_choice(comp[r, n], used[r, n], laps_left, life)
                if forced_comp is not None:
                    new_comp = np.where(forced_comp[0][r, n], I, new_comp)
                    new_comp = np.where(forced_comp[1][r, n], M, new_comp)
                own_mask = is_own[n]
                if own_mask.any():
                    new_comp[own_mask] = own_pit_comp[r[own_mask], own_index[n[own_mask]]]
                comp[r, n] = new_comp
                age[r, n] = -1
                used[r, n] |= (1 << new_comp).astype(np.int8)
                fresh_target = _rival_target(c, new_comp, snap.tendency[n], jitter[sim[r], n], life)
                done = (life[new_comp] * 1.05 >= laps_left) & _two_compounds(used[r, n])
                next_pit[r, n] = np.where(done, NO_PIT, lapno + np.maximum(4.0, fresh_target))

            tent = cum + lap_time + cost

            green = st == GREEN
            if green.any():
                tent = _resolve_traffic(cum, tent, soc, alive, green, u_pass[sim, k], pass_threshold,
                                        c.overtake_difficulty)

            sc_rows = st >= SC
            if sc_rows.any():
                lead = np.nanmin(np.where(alive[sc_rows], cum[sc_rows], np.inf), axis=1, keepdims=True)
                keep = np.where(st[sc_rows] == RED, 0.1, 0.35)[:, None]
                squeezed = lead + (cum[sc_rows] - lead) * keep
                tent[sc_rows] = squeezed + lap_time[sc_rows] + cost[sc_rows]

            cum = np.where(alive, tent, np.inf)
            soc = np.clip(soc + 0.12, 0.0, 4.0)
            age = age + (green[:, None] | (age < 0))
            prev_status = st

    final = np.where(alive, cum, np.inf)
    order = np.argsort(final, axis=1)
    pos_all = np.empty_like(order)
    np.put_along_axis(pos_all, order, np.broadcast_to(np.arange(1, N + 1), order.shape), axis=1)
    pos = pos_all[:, own]
    time_own = np.where(np.isfinite(final[:, own]), final[:, own], np.nan)

    # Illegal one-compound finishes earn a DSQ-like result so the optimiser never picks them.
    two = _two_compounds(used[:, own])
    dry_race = wet.max(axis=1, keepdims=True) < 0.05
    pos = np.where(two | ~dry_race, pos, N)

    utility = (POINTS[pos - 1] * snap.points_weight + 0.20 * (N + 1 - pos)).sum(axis=1)
    return SimOut(C, S_, pos, time_own, utility, first_pit, neutral_lap,
                  (_time.perf_counter() - started) * 1000)


def _two_compounds(used: np.ndarray) -> np.ndarray:
    dry = used & 0b111
    wet_used = (used & 0b11000) != 0
    return ((dry & (dry - 1)) != 0) | wet_used


def _rival_choice(comp: np.ndarray, used: np.ndarray, laps_left: int, life: np.ndarray) -> np.ndarray:
    choice = np.where(laps_left <= life[S] * 0.9, S, np.where(laps_left <= life[M] * 0.95, M, H)).astype(np.int8)
    choice = np.broadcast_to(choice, comp.shape).copy()
    same = (choice == comp) & (~_two_compounds(used))
    choice[same] = np.where(comp[same] == H, M, H)
    wet_tyre = comp >= I
    choice[wet_tyre] = M
    return choice


def _resolve_traffic(cum: np.ndarray, tent: np.ndarray, soc: np.ndarray, alive: np.ndarray, green: np.ndarray,
                     u: np.ndarray, threshold: float, difficulty: float) -> np.ndarray:
    """Walk each race front to back: a faster car behind passes or is held up."""
    order = np.argsort(cum, axis=1)
    sorted_tent = np.take_along_axis(tent, order, axis=1)
    sorted_cum = np.take_along_axis(cum, order, axis=1)
    sorted_soc = np.take_along_axis(soc, order, axis=1)
    sorted_u = np.take_along_axis(u, order, axis=1)
    for p in range(1, tent.shape[1]):
        ahead = sorted_tent[:, p - 1]
        mine = sorted_tent[:, p]
        contact = (mine < ahead + FOLLOW_GAP) & green & np.isfinite(mine)
        if not contact.any():
            continue
        advantage = ahead - mine
        # Overtake Mode is earned within the detection gap and needs usable charge.
        within = (sorted_cum[:, p] - sorted_cum[:, p - 1]) < 1.0
        attack = within & (sorted_soc[:, p] > 0.8)
        defended = sorted_soc[:, p - 1] > 1.2
        adjusted = threshold - 0.35 * attack + 0.10 * defended
        prob = 1.0 / (1.0 + np.exp(np.clip(-(advantage - adjusted) / 0.25, -40.0, 40.0)))
        passed = (advantage > AUTO_PASS) | (sorted_u[:, p] < prob)
        held = contact & ~passed
        sorted_tent[held, p] = ahead[held] + FOLLOW_GAP
        spent = contact & attack
        if spent.any():
            sorted_soc[spent, p] -= 0.45
    np.put_along_axis(soc, order, sorted_soc, axis=1)
    out = np.empty_like(tent)
    np.put_along_axis(out, order, sorted_tent, axis=1)
    return out


def summarize(out: SimOut, target: int = 0) -> list[dict]:
    """Per-candidate statistics for one own car (index into Snapshot.own)."""
    results = []
    for i in range(out.n_cands):
        rows = out.rows(i)
        pos = out.pos[rows, target]
        pts = POINTS[pos - 1]
        counts = np.bincount(pos, minlength=out.pos.max() + 2)[1:] / len(rows)
        results.append({
            "e_pos": float(pos.mean()),
            "sd_pos": float(pos.std()),
            "p10": float(np.percentile(pos, 10)),
            "p90": float(np.percentile(pos, 90)),
            "e_pts": float(pts.mean()),
            "p_points": float((pos <= 10).mean()),
            "p_podium": float((pos <= 3).mean()),
            "e_time": float(np.nanmean(out.time[rows, target])),
            "utility": float(out.utility[rows].mean()),
            "hist": [round(float(v), 4) for v in counts],
        })
    return results


def paired_confidence(out: SimOut, best: int, alt: int) -> float:
    """Chance the chosen action beats the alternative in the same simulated race."""
    a = out.utility[out.rows(best)]
    b = out.utility[out.rows(alt)]
    wins = (a > b).mean()
    ties = (a == b).mean()
    return float(wins / (wins + (1.0 - wins - ties)) if wins + (1.0 - wins - ties) > 0 else 0.5)
