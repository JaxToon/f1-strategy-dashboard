import json
import time

import numpy as np
import pytest

from f1strat.catalog import CIRCUITS, SCENARIOS
from f1strat.estimators import DegFilter, energy_advice, pit_probability
from f1strat.laptime import GREEN, H, M, S, SC, build_tables, pit_cost, wet_delta
from f1strat.montecarlo import Cand, paired_confidence, simulate
from f1strat.recommender import live_options, recommend
from f1strat.session import ForbiddenRole, RaceSession
from f1strat.strategy import best_continuation, enumerate_candidates, project_exit
from f1strat.world import RaceWorld

CIRCUIT = CIRCUITS["silverstone"]


@pytest.fixture(scope="module")
def session():
    s = RaceSession("silverstone", "williams", "bersih", 5)
    s.run_prerace(n_sims=60)
    return s


def test_prerace_produces_three_distinct_plans(session):
    for code in session.own_codes:
        plans = session.prerace["plans"][code]
        assert [p["name"] for p in plans] == ["A", "B", "C"]
        assert len({p["label"] for p in plans}) == 3


def test_prerace_plans_are_legal_two_compound(session):
    for rows in session.prerace["candidates"].values():
        for row in rows:
            compounds = {row["start"]} | {s["compound"] for s in row["plan"]}
            assert len(compounds) >= 2


def test_playbook_covers_every_neutralisation(session):
    code = session.own_codes[0]
    events = {r["event"] for r in session.prerace["playbook"][code]}
    assert events == {"SC", "VSC", "RED"}


def test_one_compound_race_is_punished():
    s = RaceSession("silverstone", "williams", "bersih", 1)
    snap = s._base_snapshot()
    legal = Cand("legal", [[(25, H)], [(25, H)]], start=[M, M])
    illegal = Cand("illegal", [[], [(25, H)]], start=[M, M])
    out = simulate(snap, [legal, illegal], 60, 1)
    assert out.pos[out.rows(1), 0].mean() > out.pos[out.rows(0), 0].mean()


def test_common_random_numbers_make_identical_candidates_tie():
    s = RaceSession("silverstone", "williams", "bersih", 1)
    snap = s._base_snapshot()
    plan = [[(25, H)], [(27, H)]]
    out = simulate(snap, [Cand("a", plan), Cand("b", plan)], 80, 3)
    assert np.array_equal(out.pos[out.rows(0)], out.pos[out.rows(1)])
    assert paired_confidence(out, 0, 1) == 0.5


def test_safety_car_makes_pitting_cheaper():
    assert pit_cost(CIRCUIT, SC) < pit_cost(CIRCUIT, GREEN) * 0.6


def test_simulation_meets_latency_budget():
    s = RaceSession("silverstone", "williams", "bersih", 1)
    snap = s._base_snapshot()
    snap.own_plans = [[(22, H)], [(24, H)]]
    started = time.perf_counter()
    simulate(snap, [Cand(str(i), snap.own_plans) for i in range(6)], 300, 1)
    assert time.perf_counter() - started < 3.0


def test_filter_converges_to_true_degradation():
    tables = build_tables(CIRCUIT, CIRCUIT.track_temp)
    flt = DegFilter(0.0, 0.3, 1.0, 0.2, 0.2)
    rng = np.random.default_rng(0)
    true_mult = 1.3
    for age in range(1, 22):
        x = float(tables.deg[M, age])
        flt.update(x, 0.1 + true_mult * x + rng.normal(0, 0.18))
    assert abs(flt.mult - true_mult) < 0.12


def test_stint_logic_extends_when_tyres_are_fresh():
    tables = build_tables(CIRCUIT, CIRCUIT.track_temp)
    plan = best_continuation(CIRCUIT, tables, 1, M, 1, 1 << M)
    assert plan and plan[0][0] > 5


def test_rival_pit_probability_rises_with_tyre_age():
    young = pit_probability(CIRCUIT, M, 4, 0.0, 40, True, False, GREEN)
    old = pit_probability(CIRCUIT, M, 20, 0.0, 30, True, False, GREEN)
    assert old > young


def test_rival_pit_probability_low_when_finish_is_reachable():
    assert pit_probability(CIRCUIT, H, 10, 0.0, 12, False, False, GREEN) < 0.05


def test_energy_advice_warns_when_attack_leaves_car_exposed():
    advice = energy_advice(CIRCUIT, 1.8, 0.7, 0.9, "ALO", "HAM", GREEN)
    assert advice["mode"] == "SERANG" and advice["vulnerable"]


def test_energy_advice_saves_under_safety_car():
    assert energy_advice(CIRCUIT, 1.8, 0.7, 0.9, "ALO", "HAM", SC)["mode"] == "TABUNG"


def test_inter_beats_slick_above_crossover():
    assert float(wet_delta(3, 0.3)) < float(wet_delta(M, 0.3))
    assert float(wet_delta(3, 0.05)) > float(wet_delta(M, 0.05))


# -- regulatory boundary -------------------------------------------------------

def test_feed_exposes_no_rival_telemetry_or_hidden_state():
    world = RaceWorld(CIRCUIT, "williams", SCENARIOS["bersih"], 1)
    world.start({})
    for _ in range(50):
        world.step(0.5)
    frame = world.frame()
    own = {car.code for car in world.cars if car.own}
    assert set(frame["telemetry"]["cars"]) == own
    hidden = {"mult", "pace", "soc", "cliff_shift", "wear", "plan", "energy_mode", "harvested"}
    for row in frame["timing"]["cars"]:
        assert not hidden & set(row)


def test_session_source_never_reads_truth_for_decisions():
    import f1strat.recommender
    import f1strat.strategy
    import inspect
    for module in (f1strat.recommender, f1strat.strategy):
        assert "truth(" not in inspect.getsource(module)


def test_decision_does_not_touch_car_without_radio_step(session):
    source = open(RaceSession.decide.__code__.co_filename, encoding="utf-8").read()
    assert "radio_box" in source  # the only route, and it exists only in the simulated world
    assert not hasattr(RaceWorld, "send_command")


# -- live session --------------------------------------------------------------

def run_to_lap(session: RaceSession, lap: int) -> None:
    while session.phase == "race" and session.latest["timing"]["leader_lap"] < lap:
        session.advance(4.0)


@pytest.fixture(scope="module")
def live():
    s = RaceSession("silverstone", "williams", "sc-awal", 11)
    s.run_prerace(n_sims=60)
    s.start_race()
    run_to_lap(s, 8)
    s.compute_recs(n_sims=60)
    return s


def test_recommendation_card_has_required_fields(live):
    rec = next(iter(live.recs.values()))
    assert rec["action"] in ("BOX", "STAY", "BOX_NEXT")
    assert len(rec["reasons"]) == 3
    assert 0 <= rec["confidence"] <= 1
    assert rec["invalidate"] and rec["sensitive"]
    assert rec["model_version"]


def test_both_own_cars_get_a_recommendation(live):
    assert set(live.recs) == set(live.own_codes)


def test_view_is_json_serialisable(live):
    payload = json.dumps(live.view())
    assert '"hist"' not in payload  # histograms stay out of the 5 Hz stream


def test_rival_estimates_are_labelled(live):
    cards = live.view()["rivals"]
    assert cards
    for card in cards:
        assert card["tyre_confidence"] in ("sedang", "rendah")
        assert card["energy_low"] < card["energy_high"]


def test_model_failure_keeps_raw_data(live):
    live.inject("chief", "MODEL_FAIL")
    live.compute_recs(n_sims=30)
    view = live.view()
    assert view["rec_error"] and not view["recs"] and view["rows"]
    live.inject("chief", "MODEL_FAIL")
    live.compute_recs(n_sims=30)
    assert live.view()["recs"]


def test_dropped_feed_is_marked_stale(live):
    live.world.inject("DROP_TIMING")
    live.source_wall["timing"] = time.time() - 10
    live.advance(1.0)
    assert live.view()["sources"]["timing"]["stale"]
    live.world.inject("DROP_TIMING")
    live.advance(1.0)
    assert not live.view()["sources"]["timing"]["stale"]


def test_only_chief_can_lock(session):
    with pytest.raises(ForbiddenRole):
        session.lock_plans("strategist")
    assert session.lock_plans("chief")["by"] == "Chief of Strategy"


def test_principal_cannot_decide(live):
    with pytest.raises(ForbiddenRole):
        live.decide("principal", live.own_codes[0], "BOX", "H")


def test_decision_logs_recommendation_context(live):
    entry = live.decide("strategist", live.own_codes[0], "STAY", None, "Tunggu SC")
    assert entry["rec_id"] and entry["rec_confidence"] is not None
    assert entry["model_version"]


def test_safety_car_raises_alert_and_counts_down(live):
    run_to_lap(live, 15)
    assert any(a["kind"] in ("event", "race-control") for a in live.view()["alerts"])
    deadline = live.view()["own"][live.own_codes[0]]["deadline"]
    assert deadline["seconds"] >= 0


def test_box_decision_reaches_car_and_changes_tyres():
    s = RaceSession("monza", "haas", "bersih", 3)
    s.run_prerace(n_sims=40)
    s.start_race()
    run_to_lap(s, 5)
    code = s.own_codes[0]
    before = next(r for r in s.latest["timing"]["cars"] if r["code"] == code)
    comp = "H" if before["compound"] != 2 else "M"
    s.compute_recs(n_sims=30)
    s.decide("strategist", code, "BOX", comp)
    run_to_lap(s, 8)
    after = next(r for r in s.latest["timing"]["cars"] if r["code"] == code)
    assert after["stops"] == before["stops"] + 1


def test_called_car_cannot_be_boxed_twice():
    s = RaceSession("monza", "haas", "bersih", 4)
    s.run_prerace(n_sims=40)
    s.start_race()
    run_to_lap(s, 5)
    code = s.own_codes[0]
    before = next(r for r in s.latest["timing"]["cars"] if r["code"] == code)
    s.compute_recs(n_sims=30)
    s.decide("strategist", code, "BOX", "H")
    with pytest.raises(ValueError):
        s.decide("strategist", code, "BOX", "H")
    # While the stop is under way the card must not ask for another one.
    s.compute_recs(n_sims=30)
    assert s.recs.get(code) is None or s.recs[code]["lap"] <= 5
    run_to_lap(s, 12)
    s.compute_recs(n_sims=30)
    after = next(r for r in s.latest["timing"]["cars"] if r["code"] == code)
    assert after["stops"] == before["stops"] + 1
    assert code not in s.pending_box


def test_result_for_a_car_that_stopped_meanwhile_is_discarded(monkeypatch):
    import f1strat.session as module
    s = RaceSession("monza", "haas", "bersih", 4)
    s.run_prerace(n_sims=40)
    s.start_race()
    run_to_lap(s, 5)
    s.autopilot = True
    code = s.own_codes[0]
    real = module.recommend

    def slow_recommend(snap, target, *args, **kwargs):
        rec = real(snap, target, *args, **kwargs)
        rec |= {"action": "BOX", "compound": "H", "confidence": 0.9}
        next(r for r in s.latest["timing"]["cars"] if r["code"] == code)["stops"] += 1
        return rec

    monkeypatch.setattr(module, "recommend", slow_recommend)
    s.recs = {}
    s.compute_recs(n_sims=30)
    assert code not in s.recs
    assert not [d for d in s.decisions if d["car"] == code]
    assert s.need_recompute


def test_stay_cancels_a_pending_call():
    s = RaceSession("monza", "haas", "bersih", 4)
    s.run_prerace(n_sims=40)
    s.start_race()
    run_to_lap(s, 3)
    code = s.own_codes[0]
    s.compute_recs(n_sims=30)
    s.decide("strategist", code, "BOX", "H")
    s.decide("strategist", code, "STAY")
    assert code not in s.pending_box
    stops = next(r for r in s.latest["timing"]["cars"] if r["code"] == code)["stops"]
    run_to_lap(s, 6)
    assert next(r for r in s.latest["timing"]["cars"] if r["code"] == code)["stops"] == stops


def test_event_alert_clears_after_green(live):
    run_to_lap(live, 24)
    assert not [a for a in live.view()["alerts"] if a["kind"] == "event"]


def test_race_finishes_and_review_has_classification():
    s = RaceSession("spa", "alpine", "bersih", 2)
    s.run_prerace(n_sims=40)
    s.start_race()
    guard = 0
    while s.phase == "race" and guard < 8000:
        s.advance(4.0)
        guard += 1
    assert s.phase == "review"
    review = s.review()
    assert len(review["classification"]) == 22
    assert review["scorecard"]["rival_samples"] > 100


def test_undercut_table_grows_with_laps(session):
    me, rival = session.own_codes[0], next(c for c in session.codes if c not in session.own_codes)
    rows = session.undercut(me, rival)["rows"]
    assert len(rows) == 6
    assert rows[-1]["laps"] == 6


def test_box_next_lap_when_pit_entry_passed(live):
    code = live.own_codes[0]
    row = next(r for r in live.latest["timing"]["cars"] if r["code"] == code)
    assert live.box_lap(code) in (row["lap"] + 1, row["lap"] + 2)


def test_project_exit_counts_field(live):
    snap = live.live_snapshot()
    view = project_exit(snap, snap.own[0])
    assert 1 <= view["position"] <= 22


def test_candidates_respect_tyre_allocation():
    tables = build_tables(CIRCUIT, CIRCUIT.track_temp)
    options = enumerate_candidates(CIRCUIT, tables, {S: 0, M: 1, H: 1}, 1.0)
    assert options
    for start, plan in options:
        seq = [start] + [k for _, k in plan]
        assert S not in seq and seq.count(M) <= 1 and seq.count(H) <= 1
