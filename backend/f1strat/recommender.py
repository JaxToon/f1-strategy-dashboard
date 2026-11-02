"""Turns the simulator into a single, explainable call for one car."""
from __future__ import annotations

import numpy as np

from .catalog import id_text
from .laptime import (COMPOUNDS, GREEN, H, I, M, S, SC, SLICK_TO_INTER, SLICKS, VSC, W, deg_rate, life_laps, pit_cost)
from .montecarlo import Cand, Snapshot, SimOut, paired_confidence, simulate, summarize
from .strategy import Plan, best_continuation, plan_cost, project_exit

MIN_EDGE = 0.15  # below this the gap is simulation noise, and a stop is a real cost to pay for it


def _other(snap: Snapshot, target: int, plan: Plan) -> list[Plan]:
    plans = [list(p) for p in snap.own_plans]
    plans[target] = plan
    return plans


def live_options(snap: Snapshot, target: int, box_lap: int) -> list[dict]:
    """Candidate actions: stay, box now on each compound, box next lap."""
    c = snap.circuit
    idx = snap.own[target]
    comp, age, used = int(snap.comp[idx]), int(snap.age[idx]), int(snap.used[idx])
    mult = float(snap.deg_mult[idx])
    lap = box_lap - 1
    wet_soon = snap.wet_now > 0.10 or (snap.rain is not None and snap.rain[0] - lap <= 2)
    compounds: tuple[int, ...] = SLICKS
    if wet_soon and snap.wet_now > 0.08:
        compounds = (I,) if comp <= H else (M, H)
    elif comp >= I:
        compounds = (M, H)

    current = [s for s in snap.own_plans[target] if s[0] > box_lap]
    stay_plan = current or best_continuation(c, snap.tables, lap, comp, age, used, mult, earliest=box_lap + 2)
    options = [{"key": "STAY", "action": "STAY", "compound": None, "plan": stay_plan, "label": "Tetap di lintasan"}]
    if box_lap > c.laps - 1:
        return options

    costs = []
    for k in compounds:
        tail = [] if k >= I else best_continuation(c, snap.tables, box_lap, k, 0, used | (1 << k), mult,
                                                   earliest=box_lap + 6)
        plan = [(box_lap, k)] + tail
        costs.append((plan_cost(c, snap.tables, lap, comp, age, plan, mult), k, plan))
        options.append({"key": f"BOX-{COMPOUNDS[k]}", "action": "BOX", "compound": k, "plan": plan,
                        "label": f"Box sekarang, {COMPOUNDS[k]}"})
    costs.sort(key=lambda row: row[0])
    if box_lap + 1 <= c.laps - 1 and costs:
        k = costs[0][1]
        tail = [] if k >= I else best_continuation(c, snap.tables, box_lap + 1, k, 0, used | (1 << k), mult,
                                                   earliest=box_lap + 7)
        options.append({"key": "NEXT", "action": "BOX_NEXT", "compound": k, "plan": [(box_lap + 1, k)] + tail,
                        "label": f"Box lap depan, {COMPOUNDS[k]}"})
    return options


def _split_effect(out: SimOut, best: int, alt: int, mask: np.ndarray) -> tuple[float, float] | None:
    """Utility edge of best over alt, in the sims where a condition does and does not happen."""
    a = out.utility[out.rows(best)]
    b = out.utility[out.rows(alt)]
    if mask.mean() < 0.05 or mask.mean() > 0.95:
        return None
    diff = a - b
    return float(diff[mask].mean()), float(diff[~mask].mean())


def _conditions(snap: Snapshot, out: SimOut, best: int, alt: int, box_lap: int, threats: list[dict]) -> tuple[str, str]:
    """Which assumption matters most, and what would overturn the call."""
    rows = out.rows(best)
    tests: list[tuple[str, float, float]] = []
    neutral_soon = out.neutral_lap[rows] <= box_lap + 5
    effect = _split_effect(out, best, alt, neutral_soon)
    if effect:
        tests.append((f"Safety Car atau VSC sebelum lap {box_lap + 5}", *effect))
    for threat in threats[:3]:
        j = snap.codes.index(threat["code"])
        early = out.first_pit[rows, j] <= box_lap + 2
        effect = _split_effect(out, best, alt, early)
        if effect:
            tests.append((f"{threat['code']} pit sebelum lap {box_lap + 3}", *effect))
    if not tests:
        return ("Tidak ada asumsi tunggal yang menggeser hasil.",
                f"Batal bila degradasi aktual jauh di atas estimasi atau ada kejadian baru.")
    tests.sort(key=lambda row: -abs(row[1] - row[2]))
    name, when, otherwise = tests[0]
    sensitive = f"Paling sensitif: {name} (selisih {when:+.1f} vs {otherwise:+.1f} poin-setara)."
    flip = next((row for row in tests if row[1] < 0 <= row[2]), None)
    return sensitive, (f"Batal bila {flip[0]}." if flip else "Tidak ada kondisi yang membalik keputusan pada sampel ini.")


def _reasons(snap: Snapshot, target: int, option: dict, best_stat: dict, alt_stat: dict, status: int,
             exit_view: dict, threats: list[dict]) -> list[str]:
    c = snap.circuit
    idx = snap.own[target]
    comp, age = int(snap.comp[idx]), int(snap.age[idx])
    rate = deg_rate(snap.tables, comp, age, float(snap.deg_mult[idx]))
    life = life_laps(c, comp)
    reasons: list[tuple[float, str]] = []
    if status != GREEN and option["action"] != "STAY":
        saved = pit_cost(c, GREEN) - pit_cost(c, status)
        reasons.append((3.0, f"{'Safety Car' if status == SC else 'VSC'} memangkas biaya pit {saved:.0f} dtk."))
    if life - age <= 4:
        reasons.append((2.5, f"Ban {COMPOUNDS[comp]} umur {age}, tebing diperkirakan dalam {max(life - age, 0):.0f} lap."))
    else:
        reasons.append((1.0, f"Ban {COMPOUNDS[comp]} umur {age} kehilangan {rate:.2f} dtk/lap, sisa hidup sekitar {life - age:.0f} lap."))
    if option["action"] != "STAY":
        if exit_view["traffic"] and exit_view["ahead"]:
            reasons.append((2.0, f"Keluar P{exit_view['position']} tepat di belakang {exit_view['ahead']['code']}, risiko tertahan."))
        else:
            reasons.append((1.8, f"Keluar P{exit_view['position']} di udara bersih."))
    else:
        reasons.append((1.5, f"Bila box sekarang keluar P{exit_view['position']}"
                             + (f" di belakang {exit_view['ahead']['code']}." if exit_view["ahead"] else ".")))
    if threats:
        top = threats[0]
        reasons.append((1.6 + top["p_pit"], f"{top['code']} ancaman {top['kind']}, peluang pit {top['p_pit'] * 100:.0f}% (estimasi)."))
    used = int(snap.used[idx])
    dry = used & 0b111
    if (dry & (dry - 1)) == 0 and not (used & 0b11000):
        reasons.append((1.2, "Aturan dua kompon belum terpenuhi."))
    reasons.append((0.5, f"Ekspektasi posisi {best_stat['e_pos']:.1f} dibanding {alt_stat['e_pos']:.1f} untuk opsi kedua."))
    reasons.sort(key=lambda row: -row[0])
    return [text for _, text in reasons[:3]]


def recommend(snap: Snapshot, target: int, box_lap: int, status: int, threats: list[dict], seed: int,
              n_sims: int = 300) -> dict:
    # The simulation counts laps from the leader, so "now" can be no earlier than its first lap.
    options = live_options(snap, target, max(box_lap, snap.lap + 1))
    cands = [Cand(o["label"], _other(snap, target, o["plan"])) for o in options]
    out = simulate(snap, cands, n_sims, seed)
    stats = summarize(out, target)

    ranked = sorted(range(len(options)), key=lambda i: -stats[i]["utility"])
    best = ranked[0]
    stay = 0
    # Keep the current course unless a change clearly earns its risk.
    if best != stay and stats[best]["utility"] - stats[stay]["utility"] < MIN_EDGE:
        best = stay
    alt = next((i for i in ranked if options[i]["action"] != options[best]["action"]), ranked[-1])
    if alt == best:
        alt = stay

    idx = snap.own[target]
    exit_view = project_exit(snap, idx, status)
    sensitive, invalidate = _conditions(snap, out, best, alt, box_lap, threats)
    option = options[best]
    table = [{"key": o["key"], "label": o["label"], "action": o["action"],
              "compound": None if o["compound"] is None else COMPOUNDS[o["compound"]],
              "e_pos": round(s["e_pos"], 2), "p10": s["p10"], "p90": s["p90"], "e_pts": round(s["e_pts"], 2),
              "p_points": round(s["p_points"], 2), "utility": round(s["utility"], 2),
              "plan": [{"lap": l, "compound": COMPOUNDS[k]} for l, k in o["plan"]], "hist": s["hist"]}
             for o, s in zip(options, stats)]
    time_gain = stats[alt]["e_time"] - stats[best]["e_time"]
    return {
        "car": snap.codes[idx],
        "lap": snap.lap,
        "box_lap": box_lap,
        "action": option["action"],
        "compound": None if option["compound"] is None else COMPOUNDS[option["compound"]],
        "compound_idx": option["compound"],
        "plan_after": table[best]["plan"],
        "gain_s": round(float(time_gain), 1),
        "gain_pos": round(stats[alt]["e_pos"] - stats[best]["e_pos"], 2),
        "confidence": round(paired_confidence(out, best, alt), 2),
        "alternative": options[alt]["label"],
        "reasons": [id_text(r) for r in _reasons(snap, target, option, stats[best], stats[alt], status, exit_view, threats)],
        "sensitive": id_text(sensitive),
        "invalidate": id_text(invalidate),
        "exit": exit_view,
        "options": table,
        "n_sims": n_sims * len(options),
        "compute_ms": round(out.elapsed_ms),
        "source": "monte-carlo",
    }


def whatif(snap: Snapshot, target: int, plan: Plan, seed: int, n_sims: int = 300) -> dict:
    """Compare a hand-edited plan against the current one in the same simulated races."""
    cands = [Cand("Plan aktif", _other(snap, target, list(snap.own_plans[target]))),
             Cand("What-if", _other(snap, target, plan))]
    out = simulate(snap, cands, n_sims, seed)
    base, edited = summarize(out, target)
    keys = ("e_pos", "p10", "p90", "e_pts", "p_points", "hist")
    return {
        "base": {k: base[k] for k in keys},
        "whatif": {k: edited[k] for k in keys},
        "delta_pos": round(base["e_pos"] - edited["e_pos"], 2),
        "delta_pts": round(edited["e_pts"] - base["e_pts"], 2),
        "delta_s": round(base["e_time"] - edited["e_time"], 1),
        "confidence": round(paired_confidence(out, 1, 0), 2),
        "compute_ms": round(out.elapsed_ms),
        "n_sims": n_sims * 2,
    }
