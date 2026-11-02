"""Strategy calculations: stint optimiser, Plan A/B/C, playbook, pit windows,
undercut calculator, weather scenarios and the pit-exit projection."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np

from .catalog import Circuit
from .laptime import (COMPOUNDS, GREEN, H, I, M, OFFSET, RED, S, SC, SLICK_TO_INTER, SLICKS, VSC, WARMUP, Tables,
                      life_laps, pit_cost)
from .montecarlo import Cand, Snapshot, paired_confidence, simulate, summarize

Plan = list[tuple[int, int]]
STOP_TRAFFIC_COST = 1.5  # average time lost rejoining traffic per extra stop


def plan_cost(c: Circuit, t: Tables, lap: int, comp: int, age: int, plan: Plan, mult: float = 1.0) -> float:
    """Tyre and pit time of a plan from `lap` to the flag, without traffic."""
    total = 0.0
    cur_lap, cur_comp, cur_age = lap, comp, age
    for stop_lap, next_comp in plan:
        n = stop_lap - cur_lap
        total += (t.deg_cum[cur_comp, cur_age + n] - t.deg_cum[cur_comp, cur_age]) * mult + OFFSET[cur_comp] * n
        total += pit_cost(c) + STOP_TRAFFIC_COST + WARMUP[next_comp]
        cur_lap, cur_comp, cur_age = stop_lap, next_comp, 0
    n = c.laps - cur_lap
    total += (t.deg_cum[cur_comp, cur_age + n] - t.deg_cum[cur_comp, cur_age]) * mult + OFFSET[cur_comp] * n
    return float(total)


def _legal(comp: int, used: int, plan: Plan) -> bool:
    mask = used | (1 << comp)
    for _, k in plan:
        mask |= 1 << k
    dry = mask & 0b111
    return (dry & (dry - 1)) != 0 or (mask & 0b11000) != 0


def best_continuation(c: Circuit, t: Tables, lap: int, comp: int, age: int, used: int, mult: float = 1.0,
                      earliest: int | None = None, allowed: tuple[int, ...] = SLICKS) -> Plan:
    """Cheapest remaining plan with at most two more stops, honouring the two-compound rule."""
    first = max(earliest if earliest is not None else lap + 1, lap + 1)
    last = c.laps - 2
    best: Plan = []
    best_cost = plan_cost(c, t, lap, comp, age, []) if _legal(comp, used, []) else float("inf")
    if comp >= I:
        return []
    for a in allowed:
        for l1 in range(first, last + 1):
            plan = [(l1, a)]
            if _legal(comp, used, plan):
                cost = plan_cost(c, t, lap, comp, age, plan, mult)
                if cost < best_cost:
                    best, best_cost = plan, cost
            if l1 + 6 > last:
                continue
            for b in allowed:
                for l2 in range(l1 + 6, last + 1, 2):
                    plan2 = [(l1, a), (l2, b)]
                    if _legal(comp, used, plan2):
                        cost = plan_cost(c, t, lap, comp, age, plan2, mult)
                        if cost < best_cost:
                            best, best_cost = plan2, cost
    return best


def _best_split(c: Circuit, t: Tables, seq: tuple[int, ...], mult: float) -> tuple[Plan, float]:
    """Best stop laps for a fixed compound sequence, on the deterministic model."""
    n_stops = len(seq) - 1
    laps = range(4, c.laps - 3)
    best: Plan = []
    best_cost = float("inf")
    if n_stops == 1:
        options = ((l,) for l in laps)
    else:
        options = ((a, b) for a in laps for b in range(a + 6, c.laps - 3, 1))
    for choice in options:
        plan = [(lap, seq[i + 1]) for i, lap in enumerate(choice)]
        cost = plan_cost(c, t, 0, seq[0], 0, plan, mult)
        if cost < best_cost:
            best, best_cost = plan, cost
    return best, best_cost


def enumerate_candidates(c: Circuit, t: Tables, sets: dict[int, int], mult: float, top: int = 10) -> list[tuple[int, Plan]]:
    """(start compound, plan) pairs, keeping one-stop and two-stop options alive."""
    scored: list[tuple[float, int, int, Plan]] = []
    for n in (2, 3):
        for seq in product(SLICKS, repeat=n):
            if len(set(seq)) < 2:
                continue
            if any(seq.count(k) > sets.get(k, 0) for k in set(seq)):
                continue
            plan, cost = _best_split(c, t, seq, mult)
            if plan:
                scored.append((cost, n - 1, seq[0], plan))
    scored.sort(key=lambda row: row[0])
    picked = [row for row in scored if row[1] == 1][: top // 2 + 1] + [row for row in scored if row[1] == 2][: top // 2]
    return [(start, plan) for _, _, start, plan in picked]


def plan_label(start: int, plan: Plan) -> str:
    seq = "-".join(COMPOUNDS[k] for k in [start] + [p[1] for p in plan])
    laps = ", ".join(str(p[0]) for p in plan)
    return f"{len(plan)}-stop {seq} (lap {laps})" if plan else f"Tanpa stop {seq}"


def project_exit(snap: Snapshot, idx: int, status: int = GREEN) -> dict:
    """Where a car rejoins if it boxes now.

    Rivals may stop too, most of all under a neutralisation, so each counts as
    ahead only with the probability that it stays out. A Safety Car also closes
    the field up, which is why gaps are compressed before the pit cost is added.
    """
    c = snap.circuit
    cost = pit_cost(c, status)
    n = len(snap.codes)
    alive = np.array([j != idx and snap.alive[j] for j in range(n)])
    cum = snap.cum.astype(float).copy()
    lead = float(np.min(cum[snap.alive])) if snap.alive.any() else 0.0
    keep = 0.35 if status >= SC else 1.0
    gaps = lead + (cum - lead) * keep
    exit_time = float(gaps[idx]) + cost
    pit_p = np.zeros(n) if snap.pit_p is None else snap.pit_p
    lane = np.zeros(n, dtype=bool) if snap.in_pit is None else snap.in_pit
    # A car already in the lane has paid about half of its stop.
    their_cost = np.where(lane, cost * 0.5, cost)
    stays_ahead = gaps < exit_time
    stops_ahead = gaps + their_cost < exit_time
    p_ahead = (1.0 - pit_p) * stays_ahead + pit_p * stops_ahead
    position = 1 + int(round(float(p_ahead[alive].sum())))
    others = sorted((float(gaps[j]), snap.codes[j]) for j in range(n) if alive[j] and pit_p[j] < 0.5)
    ahead = next(((code, exit_time - time) for time, code in reversed(others) if time < exit_time), None)
    behind = next(((code, time - exit_time) for time, code in others if time >= exit_time), None)
    close = sum(1 for time, _ in others if abs(time - exit_time) < 0.7)
    in_traffic = ahead is not None and ahead[1] < 1.5
    # Uncertainty comes from cars whose order against us depends on whether they stop.
    undecided = (pit_p * (1.0 - pit_p) * (stays_ahead != stops_ahead))[alive].sum()
    spread = max(1 if close or status != GREEN else 0, int(np.ceil(1.65 * np.sqrt(undecided))))
    return {
        "position": position,
        "range": [max(position - spread, 1), position + spread],
        "ahead": {"code": ahead[0], "gap": round(ahead[1], 1)} if ahead else None,
        "behind": {"code": behind[0], "gap": round(behind[1], 1)} if behind else None,
        "traffic": in_traffic,
        "cost": round(cost, 1),
    }


def _lap_estimate(snap: Snapshot, idx: int, comp: int, age: int) -> float:
    k = min(max(age, 0), 88)
    return float(snap.pace[idx] + OFFSET[comp] + snap.tables.deg[comp, k] * snap.deg_mult[idx])


def undercut_table(snap: Snapshot, me: int, rival: int, max_laps: int = 6) -> list[dict]:
    """Seconds gained or lost if `me` pits n laps before (undercut) or after (overcut) the rival."""
    c = snap.circuit
    gap = float(snap.cum[me] - snap.cum[rival])  # positive: rival is ahead
    me_comp, me_age = int(snap.comp[me]), int(snap.age[me])
    rv_comp, rv_age = int(snap.comp[rival]), int(snap.age[rival])
    fresh = M if int(snap.comp[me]) != M else H
    rows = []
    under, over = 0.0, 0.0
    for n in range(1, max_laps + 1):
        # Undercut: we run fresh tyres while the rival stays on old ones.
        under += _lap_estimate(snap, rival, rv_comp, rv_age + n) - _lap_estimate(snap, me, fresh, n - 1)
        if n == 1:
            under -= float(WARMUP[fresh])
        # Overcut: the rival is on fresh tyres while we extend.
        over += _lap_estimate(snap, rival, fresh, n - 1) - _lap_estimate(snap, me, me_comp, me_age + n)
        if n == 1:
            over += float(WARMUP[fresh])
        rows.append({
            "laps": n,
            "undercut_gain": round(under, 2),
            "undercut_net": round(under - gap, 2),
            "overcut_gain": round(over, 2),
            "overcut_net": round(over - gap, 2),
            "undercut_works": under - gap > 0.3,
            "overcut_works": over - gap > 0.3,
        })
    return rows


@dataclass
class PreRaceResult:
    plans: dict
    candidates: dict
    playbook: dict
    windows: dict
    weather: dict
    elapsed_s: float


def _other_plans(snap: Snapshot, target: int, own_plan: Plan) -> list[Plan]:
    plans = list(snap.own_plans)
    plans[target] = own_plan
    return plans


def run_candidates(snap: Snapshot, target: int, options: list[tuple[int, Plan]], n_sims: int, seed: int) -> list[dict]:
    cands = []
    for start, plan in options:
        starts = [int(snap.comp[i]) for i in snap.own]
        starts[target] = start
        cands.append(Cand(plan_label(start, plan), _other_plans(snap, target, plan), start=starts))
    out = simulate(snap, cands, n_sims, seed)
    stats = summarize(out, target)
    rows = []
    for (start, plan), cand, stat in zip(options, cands, stats):
        rows.append({"label": cand.label, "start": COMPOUNDS[start], "start_idx": start, "stops": len(plan),
                     "plan": [{"lap": l, "compound": COMPOUNDS[k]} for l, k in plan], "plan_raw": plan, **stat})
    rows.sort(key=lambda r: -r["utility"])
    return rows


def build_playbook(snap: Snapshot, target: int, start: int, plan: Plan, seed: int, n_sims: int = 50) -> list[dict]:
    """For each lap and each neutralisation: box or stay, and on which compound."""
    c = snap.circuit
    idx = snap.own[target]
    cands: list[Cand] = []
    index: list[tuple[int, int, str, int]] = []
    laps = list(range(2, c.laps - 2, 2))
    for lap in laps:
        cur_comp, cur_age = start, lap - 1
        before = [s for s in plan if s[0] < lap]
        used = 1 << start
        for stop_lap, k in before:
            cur_comp, cur_age = k, lap - stop_lap - 1
            used |= 1 << k
        after = [s for s in plan if s[0] >= lap]
        for kind, name in ((SC, "SC"), (VSC, "VSC"), (RED, "RED")):
            starts = [int(snap.comp[i]) for i in snap.own]
            starts[target] = start
            cands.append(Cand("stay", _other_plans(snap, target, before + after), forced=(lap, kind, 4 if kind == SC else 2),
                              reactive=False, start=starts))
            index.append((lap, kind, name, -1))
            for option in (M, H):
                tail = best_continuation(c, snap.tables, lap, option, 0, used | (1 << option),
                                         float(snap.deg_mult[idx]), earliest=lap + 6)
                cands.append(Cand("box", _other_plans(snap, target, before + [(lap, option)] + tail),
                                  forced=(lap, kind, 4 if kind == SC else 2), reactive=False, start=starts))
                index.append((lap, kind, name, option))
    out = simulate(snap, cands, n_sims, seed)
    grouped: dict[tuple[int, str], dict] = {}
    for i, (lap, kind, name, option) in enumerate(index):
        rows = out.rows(i)
        entry = grouped.setdefault((lap, name), {"lap": lap, "event": name, "stay": None, "boxes": []})
        record = {"i": i, "u": float(out.utility[rows].mean()), "pos": float(out.pos[rows, target].mean()),
                  "t": float(np.nanmean(out.time[rows, target]))}
        if option < 0:
            entry["stay"] = record
        else:
            entry["boxes"].append(record | {"compound": COMPOUNDS[option]})
    table = []
    for entry in grouped.values():
        best_box = max(entry["boxes"], key=lambda b: b["u"])
        stay = entry["stay"]
        box_better = best_box["u"] > stay["u"] + 0.02
        table.append({
            "lap": entry["lap"], "event": entry["event"],
            "action": "BOX" if box_better else "STAY",
            "compound": best_box["compound"] if box_better else None,
            "gain_pos": round(stay["pos"] - best_box["pos"], 2),
            "gain_s": round(stay["t"] - best_box["t"], 1),
            "confidence": round(paired_confidence(out, best_box["i"] if box_better else stay["i"],
                                                  stay["i"] if box_better else best_box["i"]), 2),
        })
    return table


def build_windows(snap: Snapshot, target: int, start: int, plan: Plan, seed: int, n_sims: int = 150) -> list[dict]:
    """Optimal range per stop, red where the car would rejoin in traffic."""
    c = snap.circuit
    idx = snap.own[target]
    windows = []
    for stop_i, (lap, comp) in enumerate(plan):
        laps = [l for l in range(lap - 8, lap + 9, 2) if 3 <= l <= c.laps - 3]
        cands = []
        for l in laps:
            shifted = list(plan)
            shifted[stop_i] = (l, comp)
            starts = [int(snap.comp[i]) for i in snap.own]
            starts[target] = start
            cands.append(Cand(str(l), _other_plans(snap, target, shifted), start=starts))
        out = simulate(snap, cands, n_sims, seed + stop_i)
        stats = summarize(out, target)
        best = max(s["utility"] for s in stats)
        rows = []
        for l, stat in zip(laps, stats):
            traffic = _traffic_at(snap, idx, l, start, plan[:stop_i])
            delta = best - stat["utility"]
            zone = "lalu-lintas" if traffic >= 2 else ("optimal" if delta < 0.25 else ("layak" if delta < 0.7 else "buruk"))
            rows.append({"lap": l, "e_pos": round(stat["e_pos"], 2), "delta_u": round(delta, 2),
                         "traffic": traffic, "zone": zone})
        windows.append({"stop": stop_i + 1, "compound": COMPOUNDS[comp], "planned": lap, "laps": rows})
    return windows


def _traffic_at(snap: Snapshot, idx: int, lap: int, start: int, earlier: Plan) -> int:
    """Cars within reach of the pit exit at `lap`, projected with each car's typical stint."""
    c = snap.circuit
    n = len(snap.codes)
    projected = np.empty(n)
    for j in range(n):
        comp = int(snap.comp[j])
        life = life_laps(c, comp) * (0.80 - 0.07 * float(snap.tendency[j]))
        pits = lap > life
        projected[j] = snap.cum[j] + lap * (snap.pace[j] + OFFSET[comp]) + (pit_cost(c) if pits else 0.0)
    mine = float(snap.cum[idx]) + lap * float(snap.pace[idx] + OFFSET[start]) + pit_cost(c) * (1 + len(earlier))
    return int(((projected - mine > -1.5) & (projected - mine < 1.5) & (np.arange(n) != idx)).sum())


def build_weather(snap: Snapshot, target: int, start: int, plan: Plan, seed: int, n_sims: int = 150) -> list[dict]:
    """When rain comes at a given time, which lap to cross over to intermediates."""
    c = snap.circuit
    lap_s = c.base_lap + 3.0
    rows = []
    for minute in (15, 30, 45, 60):
        onset = int(minute * 60 / lap_s)
        if onset >= c.laps - 6:
            continue
        ramp, peak, dry = 4, 0.40, onset + 15
        rain = (onset, ramp, peak, dry)
        crossover = onset + max(int(np.ceil(SLICK_TO_INTER / peak * ramp)), 1)
        options = [crossover - 1, crossover, crossover + 1]
        before = [s for s in plan if s[0] < crossover - 1]
        return_lap = min(dry + 3, c.laps - 2)
        cands = []
        for lap in options:
            legal_tail = [(return_lap, M)] if return_lap > lap + 1 else []
            starts = [int(snap.comp[i]) for i in snap.own]
            starts[target] = start
            cands.append(Cand(f"inter lap {lap}", _other_plans(snap, target, before + [(lap, I)] + legal_tail),
                              rain=rain, reactive=False, start=starts))
        starts = [int(snap.comp[i]) for i in snap.own]
        starts[target] = start
        cands.append(Cand("tetap slick", _other_plans(snap, target, plan), rain=rain, reactive=False, start=starts))
        out = simulate(snap, cands, n_sims, seed + minute)
        stats = summarize(out, target)
        best = int(np.argmax([s["utility"] for s in stats[:3]]))
        rows.append({
            "minute": minute, "onset_lap": onset, "crossover_lap": options[best],
            "e_pos": round(stats[best]["e_pos"], 2), "e_pos_stay": round(stats[3]["e_pos"], 2),
            "text": f"Hujan menit {minute} (lap {onset}): masuk intermediate di lap {options[best]}",
        })
    return rows


def _early_box_limit(playbook: list[dict], event: str) -> tuple[int, int] | None:
    """Longest run of laps where the playbook says box for this event."""
    rows = sorted((r for r in playbook if r["event"] == event), key=lambda r: r["lap"])
    best: tuple[int, int] | None = None
    start = None
    for i, row in enumerate(rows):
        if row["action"] == "BOX":
            start = row["lap"] if start is None else start
            end = row["lap"]
            if best is None or end - start > best[1] - best[0]:
                best = (start, end)
        else:
            start = None
    return best


def choose_plans(rows: list[dict], playbook: list[dict]) -> list[dict]:
    """Plan A is the best expected result; B and C are the best genuinely different options."""
    if not rows:
        return []
    a = rows[0]
    b = next((r for r in rows[1:] if r["stops"] != a["stops"]), rows[min(1, len(rows) - 1)])
    c = next((r for r in rows[1:] if r is not b and (r["start"] != a["start"] or r["stops"] != a["stops"])),
             rows[min(2, len(rows) - 1)])
    triggers_b, triggers_c = [], []
    run = _early_box_limit(playbook, "SC")
    if run:
        triggers_b.append({"kind": "SC", "lap_from": run[0], "lap_to": run[1], "target": "B",
                           "text": f"SC pada lap {run[0]}-{run[1]} → box, pindah ke Plan B"})
    vsc = _early_box_limit(playbook, "VSC")
    if vsc:
        triggers_b.append({"kind": "VSC", "lap_from": vsc[0], "lap_to": vsc[1], "target": "B",
                           "text": f"VSC pada lap {vsc[0]}-{vsc[1]} → box, pindah ke Plan B"})
    triggers_c.append({"kind": "TRAFFIC", "lap_from": 1, "lap_to": 999, "target": "C",
                       "text": "Tertahan di belakang mobil lebih lambat 3 lap berturut → Plan C"})
    plans = []
    for name, row, triggers in (("A", a, []), ("B", b, triggers_b), ("C", c, triggers_c)):
        plans.append({"name": name, **row, "triggers": triggers})
    return plans
