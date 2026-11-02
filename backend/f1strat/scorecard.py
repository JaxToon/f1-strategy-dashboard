"""Shadow-mode scorecard: run many simulated races and measure the PRD targets.

    python -m f1strat.scorecard --races 12

The models share structure with the synthetic world, so these figures show the
pipeline works; they are an upper bound and do not prove accuracy on real data.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from .catalog import CIRCUITS
from .montecarlo import POINTS
from .session import RaceSession


def run_race(circuit: str, scenario: str, seed: int, team: str = "williams") -> dict:
    session = RaceSession(circuit, team, scenario, seed)
    session.run_prerace(n_sims=120)
    session.start_race()
    session.autopilot = False
    next_compute = 0
    while session.phase == "race":
        session.advance(2.0)
        # Execute the active plan so the race is realistic without a person at the desk.
        for code in session.own_codes:
            plan = session.plans_raw.get(code, [])
            row = next(r for r in session.latest["timing"]["cars"] if r["code"] == code)
            for lap, comp in plan:
                if lap == row["lap"] + 1 and session.world._car(code).pit_request is None and not row["in_pit"]:
                    session.world.radio_box(code, comp)
    return session.session_scorecard()


def run_policy(circuit: str, scenario: str, seed: int, follow_recommendations: bool, team: str = "williams") -> dict:
    """One full race driven by a fixed policy, for comparing policies on the same seeds."""
    session = RaceSession(circuit, team, scenario, seed)
    session.run_prerace(n_sims=120)
    session.start_race()
    session.autopilot = follow_recommendations
    last = -1
    while session.phase == "race":
        session.advance(2.0)
        timing = session.latest["timing"]
        if follow_recommendations:
            if timing["leader_lap"] != last:
                last = timing["leader_lap"]
                session.compute_recs(150)
            continue
        for code in session.own_codes:
            row = next(r for r in timing["cars"] if r["code"] == code)
            for lap, comp in session.plans_raw.get(code, []):
                if lap == row["lap"] + 1 and not row["in_pit"]:
                    session.world.radio_box(code, comp)
    rows = [r for r in session.latest["timing"]["cars"] if r["own"]]
    points = [POINTS[r["pos"] - 1] if not r["retired"] else 0.0 for r in rows]
    return {"points": float(sum(points)), "pos": float(np.mean([r["pos"] for r in rows])),
            "stops": float(np.mean([r["stops"] for r in rows])), "max_stops": max(r["stops"] for r in rows)}


def compare_policies(races: int) -> dict:
    scenarios = ("bersih", "sc-awal", "vsc-sc", "acak")
    circuits = list(CIRCUITS)
    plan, rec = [], []
    for i in range(races):
        args = (circuits[i % len(circuits)], scenarios[i % len(scenarios)], 300 + i)
        plan.append(run_policy(*args, follow_recommendations=False))
        rec.append(run_policy(*args, follow_recommendations=True))

    def summary(rows: list[dict]) -> dict:
        return {key: round(float(np.mean([r[key] for r in rows])), 2) for key in ("points", "pos", "stops")} | {
            "max_stops": max(r["max_stops"] for r in rows)}

    wins = sum(r["points"] > p["points"] for r, p in zip(rec, plan))
    losses = sum(r["points"] < p["points"] for r, p in zip(rec, plan))
    return {"races": races, "plan_only": summary(plan), "follow_recommendations": summary(rec),
            "better": wins, "worse": losses, "per_race_points": [(p["points"], r["points"]) for p, r in zip(plan, rec)]}


def aggregate(cards: list[dict]) -> dict:
    def mean(key: str):
        values = [c[key] for c in cards if c[key] is not None]
        return round(float(np.mean(values)), 3) if values else None

    keys = ("exit_within_1", "exit_within_1_green", "exit_neutral_in_range", "deg_rate_mae_own", "deg_rate_mae_rival", "deg_level_mae_own",
            "rival_precision", "rival_recall")
    return {k: mean(k) for k in keys} | {"races": len(cards), "exit_samples": sum(c["exit_samples"] for c in cards),
                                         "rival_samples": sum(c["rival_samples"] for c in cards)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--races", type=int, default=12)
    parser.add_argument("--compare", action="store_true", help="follow live calls vs follow the pre-race plan")
    args = parser.parse_args()
    if args.compare:
        print(json.dumps(compare_policies(args.races), indent=2))
        return
    scenarios = ("bersih", "sc-awal", "vsc-sc", "acak")
    circuits = list(CIRCUITS)
    cards = []
    for i in range(args.races):
        cards.append(run_race(circuits[i % len(circuits)], scenarios[i % len(scenarios)], 100 + i))
    print(json.dumps(aggregate(cards), indent=2))


if __name__ == "__main__":
    main()
