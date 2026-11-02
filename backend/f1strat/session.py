"""A race weekend: pre-race plans, live ingest, models, decisions and audit trail."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np

from . import MODEL_VERSION
from .catalog import CIRCUITS, SCENARIOS, team_by_id
from .estimators import (DegFilter, confidence_label, energy_advice, energy_range, lap_residual, pit_probability,
                         tyre_card)
from .laptime import COMPOUNDS, GREEN, H, I, M, RED, S, SC, VSC, build_tables, deg_rate, life_laps, pit_cost
from .montecarlo import Snapshot, Cand
from .recommender import recommend, whatif
from .strategy import (build_playbook, build_weather, build_windows, choose_plans, enumerate_candidates,
                       plan_label, project_exit, run_candidates, undercut_table)
from .world import PIT_ENTRY, RaceWorld

STALE_AFTER_S = {"timing": 3.0, "telemetry": 2.0, "race_control": 3.0, "weather": 60.0}
RADIO_MARGIN_S = 4.0
SIM_BUDGET_MAX = 300
SIM_BUDGET_MIN = 60
RECOMPUTE_TARGET_MS = 1500.0  # half the 3 s limit, leaving room for a slow moment
STATUS_CODES = {"GREEN": GREEN, "VSC": VSC, "SC": SC, "RED": RED}

ROLES = {
    "chief": "Chief of Strategy",
    "strategist": "Race strategist",
    "race_engineer": "Race engineer",
    "tyre_engineer": "Tyre engineer",
    "analyst": "Analis rival",
    "principal": "Team principal",
}
PERMISSIONS = {
    "lock": {"chief"},
    "decide": {"chief", "strategist"},
    "note": {"chief", "strategist", "race_engineer"},
    "calibrate": {"chief", "tyre_engineer"},
    "tag": {"chief", "strategist", "analyst"},
    "control": {"chief", "strategist", "race_engineer", "tyre_engineer", "analyst"},
}


class ForbiddenRole(Exception):
    pass


class RaceSession:
    def __init__(self, circuit_id: str, own_team: str, scenario_id: str, seed: int, data_dir: Path | None = None):
        self.id = uuid.uuid4().hex[:8]
        self.circuit = CIRCUITS[circuit_id]
        self.team = team_by_id(own_team)
        self.scenario = SCENARIOS[scenario_id]
        self.seed = seed
        self.world = RaceWorld(self.circuit, own_team, self.scenario, seed)
        self.tables = self.world.tables
        self.codes = [car.code for car in self.world.cars]
        self.own_codes = [car.code for car in self.world.cars if car.own]
        self.tendency = np.array([car.tendency for car in self.world.cars])

        self.fp = self.world.fp_report()
        self.filters = {}
        for code in self.codes:
            prior = self.fp[code]
            rival = code not in self.own_codes
            self.filters[code] = DegFilter(prior["pace"], prior["pace_sd"], prior["mult"], prior["mult_sd"],
                                           0.32 if rival else 0.20)

        # Tyre allocation after practice and qualifying. A real team reads this from its tyre log.
        sprint = self.circuit.weekend == "sprint"
        self.sets = {S: 1, M: 2, H: 2} if sprint else {S: 2, M: 2, H: 2}

        self.phase = "prerace"
        self.prerace: dict | None = None
        self.prerace_running = False
        self.locked: dict | None = None
        self.active_plan: dict[str, str] = {}
        self.start_comp: dict[str, int] = {}
        self.plans_raw: dict[str, list] = {}

        self.running = False
        self.speed = 10.0
        self.autopilot = False
        self.model_failed = False

        self.latest: dict = {"timing": None, "telemetry": None, "race_control": None, "weather": None}
        self.source_wall: dict[str, float] = {}
        self.history: list[dict] = []
        self.new_laps: list[dict] = []
        self.eff_age = {code: 0 for code in self.codes}
        self.traffic_laps = {code: 0 for code in self.codes}
        self.status = GREEN
        self.recs: dict[str, dict] = {}
        self.rec_log: list[dict] = []
        self.rec_error: str | None = None
        self.need_recompute = True
        self.computing = False
        self.compute_ms: list[float] = []
        self.event_ms: list[float] = []
        self.event_started: float | None = None
        self.alerts: list[dict] = []
        self.decisions: list[dict] = []
        self.notes: list[dict] = []
        self.tags: list[dict] = []
        self.fired: set[str] = set()
        self.calibrations: list[dict] = []
        self.pit_probs: dict[str, float] = {}
        self.trap_base: dict[str, list[float]] = {code: [] for code in self.codes}
        self.sector_baseline: dict[str, list[float]] = {code: [] for code in self.codes}
        self.exit_preds: dict[str, dict] = {}
        self.was_in_pit: dict[str, bool] = {code: False for code in self.codes}
        self.scores = {"exit": [], "rival": [], "deg_rate": [], "deg_level": []}
        self.pending_rival: list[dict] = []
        self.pit_laps: dict[str, set[int]] = {code: set() for code in self.codes}
        self.pending_box: dict[str, dict] = {}
        self.neutral_lap = 0
        self.compute_started: float | None = None
        self.sim_budget = SIM_BUDGET_MAX

        self.audit_path = None
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            self.audit_path = data_dir / f"{self.id}.jsonl"
        self._audit("session", {"circuit": circuit_id, "team": own_team, "scenario": scenario_id, "seed": seed})

    # -- audit ----------------------------------------------------------------
    def _audit(self, kind: str, payload: dict) -> None:
        if self.audit_path is None:
            return
        row = {"wall": time.time(), "sim_t": self.world.t, "model": MODEL_VERSION, "kind": kind, **payload}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def authorize(role: str, permission: str) -> None:
        if role not in PERMISSIONS[permission]:
            raise ForbiddenRole(f"Peran {ROLES.get(role, role)} tidak boleh melakukan aksi ini.")

    # -- snapshots ------------------------------------------------------------
    def _base_snapshot(self) -> Snapshot:
        f = self.filters
        n = len(self.codes)
        own = [self.codes.index(code) for code in self.own_codes]
        return Snapshot(
            circuit=self.circuit, tables=self.tables, lap=0, codes=self.codes,
            cum=np.array([car.grid * 0.22 for car in self.world.cars]),
            comp=np.full(n, M), age=np.zeros(n, dtype=int), used=np.full(n, 1 << M), stops=np.zeros(n, dtype=int),
            pace=np.array([f[c].pace for c in self.codes]), pace_sd=np.array([f[c].pace_sd for c in self.codes]),
            deg_mult=np.array([f[c].mult for c in self.codes]),
            deg_sd=np.array([f[c].mult_sd / f[c].mult for c in self.codes]),
            soc=np.full(n, 2.4), alive=np.ones(n, dtype=bool), tendency=self.tendency, own=own,
            own_plans=[[] for _ in own],
        )

    def live_snapshot(self) -> Snapshot:
        snap = self._base_snapshot()
        timing = self.latest["timing"]
        rows = {row["code"]: row for row in timing["cars"]}
        for i, code in enumerate(self.codes):
            row = rows[code]
            snap.cum[i] = row["gap"]
            snap.comp[i] = row["compound"]
            snap.age[i] = self.eff_age[code]
            snap.used[i] = row["used"]
            snap.stops[i] = row["stops"]
            snap.alive[i] = not row["retired"] and not row["done"]
        snap.lap = timing["leader_lap"]
        telemetry = (self.latest["telemetry"] or {}).get("cars", {})
        for code in self.own_codes:
            if code in telemetry:
                snap.soc[self.codes.index(code)] = telemetry[code]["soc_mj"]
        snap.own_plans = [[(l, k) for l, k in self.plans_raw.get(code, []) if l > snap.lap] for code in self.own_codes]
        snap.in_pit = np.array([rows[code]["in_pit"] for code in self.codes])
        snap.pit_p = np.array([self._live_pit_p(code, rows[code]) for code in self.codes])
        rc = self.latest["race_control"]
        if rc is not None and rc["status"] != "GREEN":
            snap.neutral_kind = STATUS_CODES[rc["status"]]
            snap.neutral_left = max((rc.get("neutral_until") or snap.lap + 2) - snap.lap, 1)
        weather = self.latest["weather"]
        if weather is not None:
            snap.wet_now = weather["wetness"]
            forecast = weather.get("rain_forecast")
            snap.rain = tuple(forecast) if forecast else None
        return snap

    def _live_pit_p(self, code: str, row: dict) -> float:
        if row["in_pit"]:
            return 1.0
        p = self.pit_probs.get(code, 0.0)
        # Lap-based odds lag a neutralisation; most cars on used tyres take the cheap stop.
        if self.status != GREEN and self.eff_age[code] >= 8 and self.circuit.laps - row["lap"] > 6:
            p = max(p, 0.6)
        return p

    # -- pre-race -------------------------------------------------------------
    def run_prerace(self, n_sims: int = 800) -> dict:
        started = time.perf_counter()
        snap = self._base_snapshot()
        candidates, plans, playbooks, windows, weather = {}, {}, {}, {}, {}
        for target, code in enumerate(self.own_codes):
            idx = snap.own[target]
            options = enumerate_candidates(self.circuit, self.tables, self.sets, float(snap.deg_mult[idx]))
            rows = run_candidates(snap, target, options, n_sims, self.seed + target)
            candidates[code] = rows
            top = rows[0]
            snap.comp[idx] = top["start_idx"]
            snap.used[idx] = 1 << top["start_idx"]
            snap.own_plans[target] = top["plan_raw"]
        for target, code in enumerate(self.own_codes):
            top = candidates[code][0]
            start, plan = top["start_idx"], top["plan_raw"]
            playbooks[code] = build_playbook(snap, target, start, plan, self.seed + 10 + target)
            windows[code] = build_windows(snap, target, start, plan, self.seed + 20 + target)
            weather[code] = build_weather(snap, target, start, plan, self.seed + 30 + target)
            plans[code] = choose_plans(candidates[code], playbooks[code])
            self.start_comp[code] = start
            self.plans_raw[code] = plan
            self.active_plan[code] = "A"
        n_races = n_sims * sum(len(rows) for rows in candidates.values())
        self.prerace = {"candidates": candidates, "plans": plans, "playbook": playbooks, "windows": windows,
                        "weather": weather, "elapsed_s": round(time.perf_counter() - started, 1), "n_races": n_races}
        self._audit("prerace", {"elapsed_s": self.prerace["elapsed_s"], "plans": {
            code: [p["label"] for p in plans[code]] for code in plans}})
        return self.prerace

    def lock_plans(self, role: str) -> dict:
        self.authorize(role, "lock")
        if self.prerace is None:
            raise ValueError("Jalankan simulasi pra-race sebelum mengunci plan.")
        self.locked = {"by": ROLES[role], "at": time.strftime("%H:%M:%S")}
        self._audit("lock", self.locked)
        return self.locked

    def undercut(self, code: str, rival: str) -> dict:
        snap = self.live_snapshot() if self.latest["timing"] else self._base_snapshot()
        return {"me": code, "rival": rival, "gap": round(float(snap.cum[self.codes.index(code)]
                                                              - snap.cum[self.codes.index(rival)]), 2),
                "rows": undercut_table(snap, self.codes.index(code), self.codes.index(rival))}

    # -- live -----------------------------------------------------------------
    def start_race(self) -> None:
        if self.prerace is None:
            self.run_prerace(n_sims=300)
        plans = {code: (self.start_comp[code], self.plans_raw[code]) for code in self.own_codes}
        self.world.start(plans)
        self.phase = "race"
        self.running = True
        self.ingest(self.world.frame())
        self.need_recompute = True
        self._audit("start", {"locked": self.locked is not None})

    def advance(self, sim_seconds: float, step: float = 0.5) -> None:
        remaining = sim_seconds
        while remaining > 0:
            self.world.step(min(step, remaining))
            remaining -= step
        self.ingest(self.world.frame())
        if self.world.finished and self.phase == "race":
            self.phase = "review"
            self.running = False
            self._audit("finish", {"classification": [r["code"] for r in self.latest["timing"]["cars"]]})

    def ingest(self, frame: dict) -> None:
        now = time.time()
        for source in ("timing", "telemetry", "race_control", "weather"):
            if source in frame:
                self.source_wall[source] = now
        if "weather" in frame:
            self.latest["weather"] = frame["weather"]
        if "telemetry" in frame:
            self.latest["telemetry"] = frame["telemetry"]
        if "race_control" in frame:
            rc = frame["race_control"]
            self.latest["race_control"] = rc
            for msg in rc["messages"]:
                self._alert(msg["level"], msg["text"], kind="race-control")
            self._status_change(STATUS_CODES[rc["status"]])
        if "timing" in frame:
            timing = frame["timing"]
            self.latest["timing"] = timing
            self._track_pits(timing)
            own_crossed = False
            for row in timing["completed"]:
                self._on_lap(row)
                own_crossed = own_crossed or row["code"] in self.own_codes
            if own_crossed:
                self._update_rival_probs()
                self._check_triggers()
                self.need_recompute = True

    def _status_change(self, status: int) -> None:
        if status == self.status:
            return
        self.status = status
        if status == GREEN:
            return
        self.neutral_lap = self.latest["timing"]["leader_lap"] if self.latest["timing"] else 0
        self.event_started = time.perf_counter()
        self.need_recompute = True
        if self.prerace is None or self.latest["timing"] is None:
            return
        # The playbook answers immediately; Monte Carlo refines it moments later.
        lap = self.latest["timing"]["leader_lap"]
        name = {SC: "SC", VSC: "VSC", RED: "RED"}[status]
        saved = pit_cost(self.circuit) - pit_cost(self.circuit, status) if status != RED else 0.0
        snap = self.live_snapshot()
        for target, code in enumerate(self.own_codes):
            rows = [r for r in self.prerace["playbook"][code] if r["event"] == name]
            if not rows:
                continue
            entry = min(rows, key=lambda r: abs(r["lap"] - lap))
            view = project_exit(snap, snap.own[target], status)
            if entry["action"] == "BOX":
                text = f"Playbook {code}: box sekarang, untung {saved:.0f} dtk, keluar P{view['position']} ({entry['compound']})"
                self._alert("red", text, kind="event", car=code)
            else:
                self._alert("amber", f"Playbook {code}: stay. Bila box, keluar P{view['position']}", kind="event",
                            car=code)

    def _track_pits(self, timing: dict) -> None:
        cars = timing["cars"]
        snap = None
        for row in cars:
            code = row["code"]
            if row["in_pit"] and not self.was_in_pit[code] and not row["retired"]:
                self.pit_laps[code].add(row["lap"] + 1)
                self.eff_age[code] = 0
                snap = snap or self.live_snapshot()
                view = project_exit(snap, self.codes.index(code), self.status)
                self.exit_preds[code] = {"predicted": view["position"], "range": view["range"], "status": self.status,
                                         "lap": row["lap"] + 1}
                self.filters[code].new_stint()
            if not row["in_pit"] and self.was_in_pit[code]:
                if self.pending_box.pop(code, None) is not None:
                    self.need_recompute = True
                pred = self.exit_preds.pop(code, None)
                if pred is not None:
                    self.scores["exit"].append({"code": code, "lap": pred["lap"], "predicted": pred["predicted"],
                                                "actual": row["pos"], "status": pred["status"],
                                                "in_range": pred["range"][0] <= row["pos"] <= pred["range"][1]})
            self.was_in_pit[code] = row["in_pit"]

    def _on_lap(self, row: dict) -> None:
        code = row["code"]
        self.history.append(row)
        self.new_laps.append(row)
        status = row["status"]
        age = self.eff_age[code]
        if status == GREEN:
            self.eff_age[code] = age + 1
        clean = status == GREEN and not row["in_lap"] and not row["out_lap"] and row["lap"] > 1
        timing = {r["code"]: r for r in self.latest["timing"]["cars"]}[code]
        interval = timing["interval"]
        follows = interval is not None and interval < 1.2
        # Close behind someone only counts as held up when the lap was slower than this car's own pace.
        base_comp = min(row["comp"], H)
        pred = self.filters[code].pace + self.filters[code].mult * float(self.tables.deg[base_comp, min(age, 88)])
        slowed = lap_residual(self.circuit, row["lap"], base_comp, row["time"], row["energy_delta"]) - pred > 0.25
        held = interval is not None and interval < 0.8 and slowed and row["lap"] >= 5 and status == GREEN
        self.traffic_laps[code] = self.traffic_laps[code] + 1 if held else 0
        if clean and row["comp"] <= H:
            rival = code not in self.own_codes
            y = lap_residual(self.circuit, row["lap"], row["comp"], row["time"], row["energy_delta"])
            x = float(self.tables.deg[row["comp"], min(age, 88)])
            # Rival energy use is invisible and leaks into lap time, so rival laps count for less.
            scale = (1.5 if follows else 1.0) * (1.25 if rival else 1.0)
            self.filters[code].update(x, y, scale)
        sectors = row.get("sectors")
        if clean and sectors and all(sectors):
            self.sector_baseline[code].append(sum(sectors))
        trap = timing.get("trap")
        if trap:
            self.trap_base[code].append(trap)
        self._score_prediction(code, row, age)

    def _score_prediction(self, code: str, row: dict, age: int) -> None:
        # Scoring reads simulator truth to measure the models; it never feeds back into them.
        for pending in self.pending_rival:
            # The call covers the two laps after the one it was made on.
            if pending["code"] == code and pending["lap"] + 2 == row["lap"]:
                pending["actual"] = bool({row["lap"], row["lap"] - 1} & self.pit_laps[code])
        if age < 5 or row["status"] != GREEN or row["in_lap"] or row["out_lap"] or row["comp"] > H:
            return
        truth = self.world.truth()[code]
        flt = self.filters[code]
        table = self.tables.deg[row["comp"]]
        k = min(age, 87)
        rate_est = float(table[k + 1] - table[k]) * flt.mult
        rate_true = float(table[k + 1] - table[k]) * truth["mult"]
        self.scores["deg_rate"].append({"code": code, "own": code in self.own_codes, "error": abs(rate_est - rate_true)})
        self.scores["deg_level"].append({"code": code, "own": code in self.own_codes,
                                         "error": abs(float(table[k]) * flt.mult - truth["true_deg"])})

    def _update_rival_probs(self) -> None:
        timing = self.latest["timing"]
        lap = timing["leader_lap"]
        rows = timing["cars"]
        order = {row["code"]: row for row in rows}
        for i, row in enumerate(rows):
            code = row["code"]
            if row["retired"] or row["done"] or row["in_pit"]:
                self.pit_probs[code] = 0.0
                continue
            ahead = rows[i - 1] if i > 0 else None
            neighbour = ahead is not None and ahead["in_pit"]
            dry = row["used"] & 0b111
            needs = (dry & (dry - 1)) == 0 and not (row["used"] & 0b11000)
            p = pit_probability(self.circuit, row["compound"], self.eff_age[code], row["tendency"],
                                self.circuit.laps - lap, needs, neighbour, self.status, row["stops"])
            self.pit_probs[code] = p
            if code not in self.own_codes:
                if not any(q["code"] == code and q["lap"] == row["lap"] for q in self.pending_rival):
                    self.pending_rival.append({"code": code, "lap": row["lap"], "p": p, "actual": None})

    def _threats(self, target: int, snap: Snapshot) -> list[dict]:
        me = snap.own[target]
        out = []
        for j, code in enumerate(self.codes):
            if j == me or not snap.alive[j] or code in self.own_codes:
                continue
            gap = float(snap.cum[me] - snap.cum[j])  # positive: rival is ahead of us
            p = self.pit_probs.get(code, 0.0)
            if -pit_cost(self.circuit) < gap < 0:
                gain = undercut_table(snap, j, me, 2)[-1]["undercut_gain"]
                if gain + gap > -0.5:
                    out.append({"code": code, "kind": "undercut", "gap": round(-gap, 1), "gain": round(gain, 1),
                                "p_pit": round(p, 2), "score": round(p * (1 + max(gain + gap, 0.0)), 3)})
            elif 0 < gap < 3.0:
                rows = undercut_table(snap, j, me, 3)
                gain = rows[-1]["overcut_gain"]
                if gain > 0.3:
                    out.append({"code": code, "kind": "overcut", "gap": round(gap, 1), "gain": round(gain, 1),
                                "p_pit": round(p, 2), "score": round((1 - p) * 0.3 * (1 + gain), 3)})
        out.sort(key=lambda row: -row["score"])
        return out[:5]

    def box_lap(self, code: str) -> int:
        row = next(r for r in self.latest["timing"]["cars"] if r["code"] == code)
        passed = row["u"] >= PIT_ENTRY
        return row["lap"] + (2 if passed else 1)

    def _adapt_budget(self, elapsed_ms: float) -> None:
        """Trade precision for time: a late answer is worth less than a coarser one."""
        if elapsed_ms > RECOMPUTE_TARGET_MS:
            scaled = self.sim_budget * RECOMPUTE_TARGET_MS / elapsed_ms
            self.sim_budget = max(SIM_BUDGET_MIN, int(scaled))
        elif elapsed_ms < RECOMPUTE_TARGET_MS * 0.5:
            self.sim_budget = min(SIM_BUDGET_MAX, int(self.sim_budget * 1.3))

    def compute_recs(self, n_sims: int | None = None) -> None:
        """Runs in a worker thread during a live session."""
        n_sims = n_sims or self.sim_budget
        if self.model_failed:
            self.recs = {}
            self.rec_error = "Model gagal"
            return
        started = time.perf_counter()
        self.compute_started = time.time()
        event_started, self.event_started = self.event_started, None
        snap = self.live_snapshot()
        status = self.status
        results = {}
        held = {}
        for target, code in enumerate(self.own_codes):
            if not snap.alive[snap.own[target]]:
                continue
            # A car with a stop already called or under way has no decision to make until it rejoins.
            if code in self.pending_box or snap.in_pit[snap.own[target]]:
                if code in self.recs:
                    held[code] = self.recs[code]
                continue
            threats = self._threats(target, snap)
            rec = recommend(snap, target, self.box_lap(code), status, threats, seed=self.seed + snap.lap * 7 + target,
                            n_sims=n_sims)
            rec["id"] = uuid.uuid4().hex[:8]
            rec["threats"] = threats
            rec["model_version"] = MODEL_VERSION
            results[code] = rec
        # The race kept moving while this ran: a call for a car that has since stopped is void.
        for code in list(results):
            row = next(r for r in self.latest["timing"]["cars"] if r["code"] == code)
            if row["stops"] != snap.stops[self.codes.index(code)] or row["in_pit"] or code in self.pending_box:
                del results[code]
                self.need_recompute = True
        self.recs = results | held
        self.rec_error = None
        self.compute_started = None
        self.compute_ms.append((time.perf_counter() - started) * 1000)
        self._adapt_budget(self.compute_ms[-1])
        if event_started is not None:
            self.event_ms.append((time.perf_counter() - event_started) * 1000)
        for rec in results.values():
            brief = {k: rec[k] for k in ("id", "car", "lap", "action", "compound", "gain_s", "gain_pos", "confidence",
                                         "reasons", "invalidate", "model_version")}
            brief["options"] = [{k: o[k] for k in ("label", "e_pos", "e_pts")} for o in rec["options"]]
            self.rec_log.append(brief)
            self._audit("recommendation", brief)
            if self.autopilot and self._should_autobox(rec):
                self.decide("strategist", rec["car"], "BOX", rec["compound"], "Autopilot demo", source="auto")

    @staticmethod
    def _should_autobox(rec: dict) -> bool:
        return rec["action"] == "BOX" and rec["confidence"] >= 0.55

    # -- decisions and manual input ------------------------------------------
    def decide(self, role: str, code: str, action: str, compound: str | None = None, reason: str = "",
               source: str = "strategist") -> dict:
        self.authorize(role, "decide")
        timing = self.latest["timing"]
        in_lane = bool(timing) and next(r for r in timing["cars"] if r["code"] == code)["in_pit"]
        if action == "BOX" and (code in self.pending_box or in_lane):
            raise ValueError(f"{code} sudah dipanggil masuk pit.")
        rec = self.recs.get(code)
        lap = self.latest["timing"]["leader_lap"] if self.latest["timing"] else 0
        entry = {
            "id": uuid.uuid4().hex[:8], "wall": time.strftime("%H:%M:%S"), "t": round(self.world.t, 1), "lap": lap,
            "car": code, "action": action, "compound": compound, "reason": reason, "role": ROLES[role], "source": source,
            "rec_id": rec["id"] if rec else None, "rec_action": rec["action"] if rec else None,
            "rec_compound": rec["compound"] if rec else None, "rec_confidence": rec["confidence"] if rec else None,
            "rec_options": [{k: o[k] for k in ("label", "e_pos", "e_pts")} for o in rec["options"]] if rec else [],
            "model_version": MODEL_VERSION,
        }
        entry["followed"] = None if rec is None else (rec["action"] == action
                                                      or (rec["action"] == "BOX_NEXT" and action == "BOX"))
        self.decisions.append(entry)
        self._audit("decision", entry)
        # Radio stand-in: in a real deployment this log is the end of the line.
        if action == "BOX" and compound in COMPOUNDS:
            self._apply_plan_after_box(code, COMPOUNDS.index(compound), rec)
            self.pending_box[code] = {"compound": compound, "lap": self.box_lap(code)}
            self.world.radio_box(code, COMPOUNDS.index(compound))
        elif action == "STAY":
            self.pending_box.pop(code, None)
            self.world.radio_cancel_box(code)
        elif action in ("TABUNG", "NETRAL", "BOOST", "OVERTAKE"):
            self.world.radio_energy(code, action)
        elif action.startswith("PLAN-"):
            self._switch_plan(code, action[-1])
        self.need_recompute = True
        return entry

    def _apply_plan_after_box(self, code: str, comp: int, rec: dict | None) -> None:
        lap = self.box_lap(code)
        tail: list[tuple[int, int]] = []
        if rec:
            option = next((o for o in rec["options"] if o["compound"] == COMPOUNDS[comp] and o["action"] == "BOX"), None)
            if option:
                tail = [(s["lap"], COMPOUNDS.index(s["compound"])) for s in option["plan"] if s["lap"] > lap]
        self.plans_raw[code] = [(lap, comp)] + tail

    def _switch_plan(self, code: str, name: str) -> None:
        plans = (self.prerace or {}).get("plans", {}).get(code, [])
        plan = next((p for p in plans if p["name"] == name), None)
        if plan is None:
            return
        self.active_plan[code] = name
        lap = self.latest["timing"]["leader_lap"] if self.latest["timing"] else 0
        self.plans_raw[code] = [(l, k) for l, k in plan["plan_raw"] if l > lap]

    def apply_whatif(self, code: str, stops: list[dict]) -> dict:
        snap = self.live_snapshot() if self.latest["timing"] else self._base_snapshot()
        if self.latest["timing"] is None:
            snap.own_plans = [list(self.plans_raw.get(c, [])) for c in self.own_codes]
        plan = sorted((int(s["lap"]), COMPOUNDS.index(s["compound"])) for s in stops)
        target = self.own_codes.index(code)
        result = whatif(snap, target, plan, seed=self.seed + 99)
        self._audit("whatif", {"car": code, "plan": plan, "delta_pos": result["delta_pos"]})
        return result

    def add_tag(self, role: str, code: str, tag: str) -> dict:
        self.authorize(role, "tag")
        history = [r for r in self.history if r["code"] == code and r["status"] == GREEN]
        loss = None
        if len(history) >= 6:
            recent = np.mean([r["time"] for r in history[-2:]])
            before = np.mean([r["time"] for r in history[-6:-2]])
            loss = round(float(recent - before), 2)
        evidence = "didukung data" if loss is not None and loss > 0.25 else "belum tampak di lap time"
        entry = {"code": code, "tag": tag, "role": ROLES[role], "lap": history[-1]["lap"] if history else 0,
                 "loss_s": loss, "evidence": evidence}
        self.tags.append(entry)
        self._audit("tag", entry)
        return entry

    def add_note(self, role: str, code: str, text: str) -> dict:
        self.authorize(role, "note")
        entry = {"car": code, "text": text, "role": ROLES[role], "wall": time.strftime("%H:%M:%S")}
        self.notes.append(entry)
        self._audit("note", entry)
        return entry

    def calibrate(self, role: str, code: str, deg_mult: float) -> dict:
        self.authorize(role, "calibrate")
        flt = self.filters[code]
        before = flt.mult
        flt.x[1] = deg_mult
        entry = {"car": code, "before": round(before, 3), "after": deg_mult, "role": ROLES[role],
                 "wall": time.strftime("%H:%M:%S")}
        self.calibrations.append(entry)
        self.need_recompute = True
        self._audit("calibration", entry)
        return entry

    def inject(self, role: str, kind: str) -> None:
        self.authorize(role, "control")
        if kind == "MODEL_FAIL":
            self.model_failed = not self.model_failed
            self.need_recompute = True
        else:
            self.world.inject(kind)
        self._audit("inject", {"kind": kind})

    # -- triggers and alerts --------------------------------------------------
    def _alert(self, level: str, text: str, kind: str = "info", car: str | None = None, action: dict | None = None) -> None:
        lap = self.latest["timing"]["leader_lap"] if self.latest["timing"] else 0
        self.alerts.append({"id": uuid.uuid4().hex[:6], "level": level, "text": text, "kind": kind, "car": car,
                            "lap": lap, "action": action})
        self.alerts = self.alerts[-14:]

    def _current_alerts(self, lap: int) -> list[dict]:
        """An alert stops being useful once its moment has passed."""
        def live(alert: dict) -> bool:
            if alert["kind"] == "trigger":
                return lap - alert["lap"] <= 4
            # Neutralised laps are slow, so these last as long as the neutralisation they belong to.
            if alert["level"] == "red" or alert["kind"] == "event":
                return self.status != GREEN and alert["lap"] >= self.neutral_lap
            return lap - alert["lap"] <= 2
        return [alert for alert in reversed(self.alerts) if live(alert)][:8]

    def _check_triggers(self) -> None:
        if self.prerace is None:
            return
        lap = self.latest["timing"]["leader_lap"]
        rc = self.latest["race_control"]["status"] if self.latest["race_control"] else "GREEN"
        for code in self.own_codes:
            for plan in self.prerace["plans"].get(code, []):
                for trig in plan["triggers"]:
                    key = f"{code}:{plan['name']}:{trig['kind']}"
                    if key in self.fired or self.active_plan.get(code) == plan["name"]:
                        continue
                    hit = False
                    if trig["kind"] in ("SC", "VSC"):
                        hit = rc == trig["kind"] and trig["lap_from"] <= lap <= trig["lap_to"]
                    elif trig["kind"] == "TRAFFIC":
                        hit = self.traffic_laps[code] >= 3
                    if hit:
                        self.fired.add(key)
                        self._alert("amber", f"{code}: pemicu terpenuhi. {trig['text']}", kind="trigger", car=code,
                                    action={"label": f"Pindah ke Plan {plan['name']}", "action": f"PLAN-{plan['name']}"})

    # -- views ----------------------------------------------------------------
    def _rival_card(self, row: dict) -> dict:
        code = row["code"]
        flt = self.filters[code]
        age = self.eff_age[code]
        traps = self.trap_base[code]
        deficit = 0.0
        if len(traps) >= 4:
            deficit = float(np.median(traps[:-2]) - np.mean(traps[-2:]))
        low, high = energy_range(deficit)
        tags = [t for t in self.tags if t["code"] == code][-2:]
        return {
            "code": code, "pos": row["pos"], "color": row["color"], "team": row["team"],
            "gap": row["gap"], "interval": row["interval"], "compound": COMPOUNDS[row["compound"]], "age": row["age"],
            "tyre": tyre_card(self.tables, row["compound"], age, flt) if row["compound"] <= H else None,
            "tyre_confidence": confidence_label(flt.mult_sd, True),
            "energy_low": low, "energy_high": high, "energy_confidence": "rendah" if not traps else "sedang",
            "p_pit": round(self.pit_probs.get(code, 0.0), 2),
            "history_note": None if row["has_history"] else "Tim baru: belum ada riwayat strategi",
            "tags": tags,
        }

    def _deadline(self, row: dict) -> dict:
        """Seconds left to relay a box call before the car passes the pit entry."""
        lap_s = self.circuit.base_lap * {GREEN: 1.0, VSC: 1.3, SC: 1.45, RED: 1.45}[self.status] + 4.0
        to_entry = (PIT_ENTRY - row["u"]) * lap_s
        if to_entry < 0:
            to_entry += lap_s
            missed = True
        else:
            missed = False
        return {"seconds": round(max(to_entry - RADIO_MARGIN_S, 0.0), 1), "to_entry": round(to_entry, 1),
                "missed": missed or to_entry <= RADIO_MARGIN_S}

    def _focus_rivals(self, own_rows: list[dict]) -> list[dict]:
        rows = self.latest["timing"]["cars"]
        wanted: list[str] = []
        for rec in self.recs.values():
            wanted += [t["code"] for t in rec.get("threats", [])]
        positions = {r["pos"] for own in own_rows for r in rows if abs(r["pos"] - own["pos"]) <= 1 and not r["own"]}
        wanted += [r["code"] for r in rows if r["pos"] in positions]
        wanted += [t["code"] for t in self.tags]
        seen, out = set(), []
        by_code = {r["code"]: r for r in rows}
        for code in wanted:
            if code not in seen and code in by_code and not by_code[code]["retired"]:
                seen.add(code)
                out.append(self._rival_card(by_code[code]))
        return out[:6]

    def view(self) -> dict:
        timing = self.latest["timing"]
        now = time.time()
        sources = {}
        for source, limit in STALE_AFTER_S.items():
            age = now - self.source_wall[source] if source in self.source_wall else None
            sources[source] = {"age_s": None if age is None else round(age, 2), "limit_s": limit,
                               "stale": age is None or age > limit}
        view: dict = {
            "session": {"id": self.id, "circuit": self.circuit.id, "circuit_name": self.circuit.name,
                        "team": self.team.name, "team_id": self.team.id, "team_color": self.team.color,
                        "scenario": self.scenario.name, "scenario_id": self.scenario.id, "own": self.own_codes,
                        "total_laps": self.circuit.laps, "weekend": self.circuit.weekend, "seed": self.seed,
                        "model_version": MODEL_VERSION, "compounds": self.circuit.compounds},
            "phase": self.phase, "running": self.running, "speed": self.speed, "autopilot": self.autopilot,
            "sources": sources, "locked": self.locked, "active_plan": self.active_plan,
            "plans_live": {code: [{"lap": l, "compound": COMPOUNDS[k]} for l, k in self.plans_raw.get(code, [])]
                           for code in self.own_codes},
            "prerace_ready": self.prerace is not None, "prerace_running": self.prerace_running,
            "pending_box": self.pending_box,
            "sent_at": now,
        }
        if timing is None:
            return view
        rows = []
        lap = timing["leader_lap"]
        for row in timing["cars"]:
            code = row["code"]
            flt = self.filters[code]
            age = self.eff_age[code]
            est = None
            if row["compound"] <= H:
                est = deg_rate(self.tables, row["compound"], age, flt.mult)
            rows.append({k: row[k] for k in ("code", "team", "color", "own", "pos", "lap", "gap", "interval", "u",
                                             "last_lap", "best_lap", "age", "stops", "in_pit", "retired", "done",
                                             "new_set", "grid")}
                        | {"compound": COMPOUNDS[row["compound"]], "deg": None if est is None else round(est, 3),
                           "p_pit": round(self.pit_probs.get(code, 0.0), 2)})
        own_rows = [r for r in rows if r["own"]]
        by_code = {r["code"]: r for r in rows}
        telemetry = (self.latest["telemetry"] or {}).get("cars", {})
        own_view = {}
        for code in self.own_codes:
            row = by_code[code]
            flt = self.filters[code]
            tele = telemetry.get(code)
            rank = row["pos"] - 1
            ahead = rows[rank - 1] if rank > 0 else None
            behind = rows[rank + 1] if rank + 1 < len(rows) else None
            soc = tele["soc_mj"] if tele else 0.0
            own_view[code] = {
                "row": row,
                "telemetry": tele,
                "tyre": tyre_card(self.tables, COMPOUNDS.index(row["compound"]), self.eff_age[code], flt)
                if COMPOUNDS.index(row["compound"]) <= H else None,
                "tyre_confidence": confidence_label(flt.mult_sd, False),
                "deadline": self._deadline(row),
                "energy": energy_advice(self.circuit, soc, None if row["interval"] is None else row["interval"],
                                        None if behind is None else behind["interval"],
                                        None if ahead is None else ahead["code"], None if behind is None else behind["code"],
                                        self.status),
            }
        recs = {}
        for code, rec in self.recs.items():
            recs[code] = dict(rec)
            recs[code]["age_laps"] = lap - rec["lap"]
            # Finish-position histograms belong to the review, not to a 5 Hz stream.
            recs[code]["options"] = [{k: v for k, v in o.items() if k != "hist"} for o in rec["options"]]
        view.update({
            "lap": lap, "status": (self.latest["race_control"] or {}).get("status", "GREEN"),
            "neutral_until": (self.latest["race_control"] or {}).get("neutral_until"),
            "pit_open": (self.latest["race_control"] or {}).get("pit_open", True),
            "weather": self.latest["weather"], "rows": rows, "own": own_view, "recs": recs,
            "rec_error": self.rec_error, "rivals": self._focus_rivals(own_rows),
            "alerts": self._current_alerts(lap), "decisions": list(reversed(self.decisions))[:12],
            "notes": list(reversed(self.notes))[:6], "calibrations": self.calibrations[-4:],
            "compute": {"last_ms": round(self.compute_ms[-1]) if self.compute_ms else None,
                        "event_ms": round(self.event_ms[-1]) if self.event_ms else None,
                        "running_s": round(now - self.compute_started, 1) if self.compute_started else None,
                        "sim_budget": self.sim_budget},
            "time": round(self.world.t, 1),
        })
        return view

    def session_scorecard(self) -> dict:
        def mean(rows: list[dict], own: bool | None = None) -> float | None:
            picked = [r["error"] for r in rows if own is None or r["own"] == own]
            return round(float(np.mean(picked)), 3) if picked else None

        exits = self.scores["exit"]
        within = [abs(e["predicted"] - e["actual"]) <= 1 for e in exits]
        green = [abs(e["predicted"] - e["actual"]) <= 1 for e in exits if e["status"] == GREEN]
        neutral = [e["in_range"] for e in exits if e["status"] != GREEN]
        rival = [p for p in self.pending_rival if p["actual"] is not None]
        predicted = [p for p in rival if p["p"] >= 0.5]
        true_pos = sum(1 for p in predicted if p["actual"])
        actual = sum(1 for p in rival if p["actual"])
        ms = sorted(self.compute_ms)
        return {
            "exit_within_1": round(float(np.mean(within)), 3) if within else None,
            "exit_within_1_green": round(float(np.mean(green)), 3) if green else None,
            "exit_neutral_in_range": round(float(np.mean(neutral)), 3) if neutral else None,
            "exit_samples": len(exits),
            "deg_rate_mae_own": mean(self.scores["deg_rate"], True),
            "deg_rate_mae_rival": mean(self.scores["deg_rate"], False),
            "deg_level_mae_own": mean(self.scores["deg_level"], True),
            "rival_precision": round(true_pos / len(predicted), 3) if predicted else None,
            "rival_recall": round(true_pos / actual, 3) if actual else None,
            "rival_samples": len(rival),
            "recompute_p95_ms": round(ms[int(0.95 * (len(ms) - 1))]) if ms else None,
            "event_recompute_max_ms": round(max(self.event_ms)) if self.event_ms else None,
        }

    def review(self) -> dict:
        timing = self.latest["timing"]
        return {
            "classification": [] if timing is None else [
                {"pos": r["pos"], "code": r["code"], "team": r["team"], "color": r["color"], "own": r["own"], "grid": r["grid"],
                 "stops": r["stops"], "gap": r["gap"], "lap": r["lap"], "retired": r["retired"]} for r in timing["cars"]],
            "decisions": self.decisions,
            "recommendations": self.rec_log[-400:],
            "scorecard": self.session_scorecard(),
            "tags": self.tags,
            "notes": self.notes,
        }

    def history_payload(self) -> list[dict]:
        keep = ("code", "lap", "time", "elapsed", "comp", "age", "in_lap", "out_lap", "status")
        return [{k: row[k] for k in keep} for row in self.history]

    def brief_html(self) -> str:
        if self.prerace is None:
            raise ValueError("Belum ada hasil pra-race.")
        c = self.circuit
        parts = [f"<h1>Brief pra-race: {c.name}</h1>",
                 f"<p>{self.team.name}. {c.laps} lap, {c.length_km} km. Status: "
                 f"{'terkunci oleh ' + self.locked['by'] if self.locked else 'belum dikunci'}. "
                 f"Kompon: S {c.compounds['S']}, M {c.compounds['M']}, H {c.compounds['H']}. "
                 f"Data simulasi, bukan data tim.</p>"]
        for code in self.own_codes:
            parts.append(f"<h2>{code}</h2><table><tr><th>Plan</th><th>Strategi</th><th>Posisi harapan</th>"
                         f"<th>Peluang poin</th><th>Pemicu</th></tr>")
            for plan in self.prerace["plans"][code]:
                triggers = "<br>".join(t["text"] for t in plan["triggers"]) or "Default"
                parts.append(f"<tr><td>{plan['name']}</td><td>{plan['label']}</td><td>{plan['e_pos']:.1f}</td>"
                             f"<td>{plan['p_points'] * 100:.0f}%</td><td>{triggers}</td></tr>")
            parts.append("</table>")
            box = [r for r in self.prerace["playbook"][code] if r["event"] == "SC" and r["action"] == "BOX"]
            laps = ", ".join(str(r["lap"]) for r in box) or "tidak ada"
            parts.append(f"<p>Playbook SC: box pada lap {laps}.</p>")
            weather = self.prerace["weather"][code]
            if weather:
                parts.append("<p>Cuaca: " + "; ".join(w["text"] for w in weather) + ".</p>")
        style = ("<style>body{font:15px/1.5 system-ui;max-width:800px;margin:32px auto;padding:0 16px;color:#111}"
                 "table{border-collapse:collapse;width:100%}td,th{border:1px solid #999;padding:6px 8px;text-align:left}"
                 "h1{font-size:24px}h2{font-size:18px;margin-top:24px}@media print{body{margin:0}}</style>")
        return f"<!doctype html><html lang=id><meta charset=utf-8><title>Brief pra-race</title>{style}{''.join(parts)}</html>"
