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
    args = parser.parse_args()
    scenarios = ("bersih", "sc-awal", "vsc-sc", "acak")
    circuits = list(CIRCUITS)
    cards = []
    for i in range(args.races):
        cards.append(run_race(circuits[i % len(circuits)], scenarios[i % len(scenarios)], 100 + i))
    print(json.dumps(aggregate(cards), indent=2))


if __name__ == "__main__":
    main()
