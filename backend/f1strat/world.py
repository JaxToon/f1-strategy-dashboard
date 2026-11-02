"""Synthetic race used as the data source until real feeds are available.

The world holds hidden truth (real degradation, rival plans, rival energy) and
publishes frames that follow the feed contract in the PRD: full telemetry for
the two own cars only, and official timing for everyone. Nothing downstream may
read the world directly; `frame()` is the only exit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .catalog import TEAMS, Circuit, Scenario
from .laptime import (COMPOUNDS, FUEL_START_KG, GREEN, H, I, M, OFFSET, RED, S, SC, SLICK_TO_INTER, STACK_LOSS,
                      STATIONARY_MEAN, STATIONARY_SD, TRACK_EVO_PER_LAP, VSC, WARMUP, Tables, build_tables,
                      fuel_seconds, life_laps, wet_delta)

PIT_ENTRY = 0.965
PIT_EXIT = 0.03
STATUS_NAMES = {GREEN: "GREEN", VSC: "VSC", SC: "SC", RED: "RED"}
SOURCES = ("timing", "telemetry", "race_control", "weather")
ENERGY_MODES = {
    "NETRAL": (0.00, 0.0),
    "TABUNG": (0.45, 0.35),
    "BOOST": (-0.70, -0.30),
    "OVERTAKE": (-1.10, -0.50),
}


@dataclass
class Car:
    code: str
    team: str
    color: str
    tendency: float
    has_history: bool
    pace: float
    mult: float
    cliff_shift: float
    own: bool
    grid: int
    comp: int = M
    age: int = 0
    wear: float = 0.0
    stops: int = 0
    used: int = 0
    new_set: bool = True
    dist: float = 0.0
    lap: int = 0
    lap_start: float = 0.0
    lap_target: float = 90.0
    last_lap: float | None = None
    best_lap: float | None = None
    sectors: list = field(default_factory=lambda: [None, None, None])
    sector_marks: int = 0
    sector_t: float = 0.0
    in_pit: bool = False
    pit_rate: float = 0.0
    pit_comp: int | None = None
    pit_request: int | None = None
    plan: list = field(default_factory=list)
    passing_until: float = 0.0
    retired: bool = False
    soc: float = 2.4
    energy_mode: str = "NETRAL"
    instructed_mode: str | None = None
    overtake_ready: bool = False
    harvested: float = 0.0
    deployed: float = 0.0
    clipping: int = 0
    fuel_kg: float = FUEL_START_KG
    trap: float = 318.0
    damage: float = 0.0
    held_laps: int = 0
    in_lap: bool = False
    out_lap: bool = False
    neutral_checked: bool = False
    pit_exit_dist: float = 0.0
    done: bool = False
    finish_t: float | None = None


class RaceWorld:
    def __init__(self, circuit: Circuit, own_team: str, scenario: Scenario, seed: int, track_temp: float | None = None):
        self.c = circuit
        self.scenario = scenario
        self.rng = np.random.default_rng(seed)
        self.track_temp = circuit.track_temp if track_temp is None else track_temp
        self.tables: Tables = build_tables(circuit, self.track_temp)
        self.t = 0.0
        self.seq = 0
        self.status = GREEN
        self.neutral_until = 0
        self.red_timer = 0.0
        self.wetness = 0.0
        self.finished = False
        self.started = False
        self.flag_lap = 0
        self.dropped: set[str] = set()
        self.source_ts = {s: 0.0 for s in SOURCES}
        self.messages: list[dict] = []
        self.pending_laps: list[dict] = []
        self.pending_msgs: list[dict] = []
        self.pit_log: list[dict] = []
        self._scripted = list(scenario.events)
        self._fastest: tuple[float, str] | None = None
        self.cars: list[Car] = []
        rows = []
        for team in TEAMS:
            for driver in team.drivers:
                own = team.id == own_team
                true_pace = team.pace + float(self.rng.normal(0.0, 0.08))
                quali = true_pace + float(self.rng.normal(0.0, 0.10))
                rows.append((quali, team, driver, own, true_pace))
        rows.sort(key=lambda row: row[0])
        for grid, (_, team, driver, own, true_pace) in enumerate(rows):
            car = Car(driver, team.name, team.color, team.tendency, team.has_history, true_pace,
                      float(self.rng.normal(1.0, 0.13)), float(self.rng.normal(0.0, 2.0)), own, grid + 1)
            car.dist = -0.0015 * grid
            self.cars.append(car)
        self._assign_rival_plans()

    # -- setup ----------------------------------------------------------------
    def _assign_rival_plans(self) -> None:
        c = self.c
        for car in self.cars:
            if car.own:
                continue
            draw = self.rng.random()
            mid = life_laps(c, M) * (0.80 - 0.07 * car.tendency)
            if draw < 0.55:
                first = int(mid + self.rng.normal(0, 2.5))
                car.comp, car.plan = M, [(first, H)]
            elif draw < 0.75:
                first = int(life_laps(c, H) * 0.8 + self.rng.normal(0, 3.0))
                car.comp, car.plan = H, [(first, M)]
            else:
                first = int(life_laps(c, M) * 0.65 + self.rng.normal(0, 2.0))
                second = first + int(life_laps(c, H) * 0.6 + self.rng.normal(0, 2.0))
                car.comp, car.plan = M, [(first, H), (min(second, c.laps - 6), M)]
            car.used = 1 << car.comp

    def start(self, own_plans: dict[str, tuple[int, list]]) -> None:
        for car in self.cars:
            if car.own and car.code in own_plans:
                car.comp = own_plans[car.code][0]
            car.used = 1 << car.comp
        for car in self.cars:
            self._new_lap_target(car)
        self.started = True
        self._message("info", "Lampu start padam")

    # -- commands that stand in for radio; a real deployment has no such path --
    def radio_box(self, code: str, compound: int) -> None:
        self._car(code).pit_request = compound

    def radio_cancel_box(self, code: str) -> None:
        self._car(code).pit_request = None

    def radio_energy(self, code: str, mode: str) -> None:
        self._car(code).instructed_mode = None if mode == "NETRAL" else mode

    def inject(self, kind: str) -> None:
        if kind in ("SC", "VSC", "RED"):
            self._start_neutral({"SC": SC, "VSC": VSC, "RED": RED}[kind], 3 if kind == "VSC" else 4)
        elif kind == "RAIN":
            lap = self.leader_lap + 2
            self.scenario = Scenario(self.scenario.id, self.scenario.name, self.scenario.description,
                                     rain=(lap, 5, 0.42, lap + 15))
            self._message("amber", "Radar: hujan mendekat, sekitar 2 lap lagi")
        elif kind == "DAMAGE":
            own = [car for car in self.cars if car.own and not car.retired]
            if own:
                own[0].damage = 0.45
                self._message("amber", f"{own[0].code}: beban aero depan turun, cek sayap")
        elif kind == "RIVAL_DAMAGE":
            rivals = [car for car in self.cars if not car.own and not car.retired]
            if rivals:
                pick = rivals[int(self.rng.integers(len(rivals)))]
                pick.damage = 0.7
        elif kind.startswith("DROP_"):
            source = kind[5:].lower()
            self.dropped ^= {source}

    # -- simulation -----------------------------------------------------------
    @property
    def leader_lap(self) -> int:
        return max((car.lap for car in self.cars if not car.retired), default=0)

    def _car(self, code: str) -> Car:
        return next(car for car in self.cars if car.code == code)

    def _message(self, level: str, text: str) -> None:
        msg = {"t": round(self.t, 1), "lap": self.leader_lap, "level": level, "text": text}
        self.messages.append(msg)
        self.pending_msgs.append(msg)

    def _true_deg(self, car: Car) -> float:
        cliff = life_laps(self.c, car.comp) + car.cliff_shift
        age = min(car.wear, 88.0)
        k = int(age)
        base = self.tables.deg[car.comp, k]
        extra = 0.06 * max(age - cliff, 0.0) ** 2 - 0.06 * max(age - life_laps(self.c, car.comp), 0.0) ** 2
        return float(base * car.mult + extra)

    def _new_lap_target(self, car: Car) -> None:
        c = self.c
        lap = car.lap + 1
        t = (c.base_lap + fuel_seconds(c, lap) - TRACK_EVO_PER_LAP * lap + car.pace + float(OFFSET[car.comp])
             + self._true_deg(car) + float(wet_delta(car.comp, self.wetness)))
        if car.age == 0 and car.lap > 0:
            t += float(WARMUP[car.comp])
        car.energy_mode = self._choose_mode(car)
        net, delta = ENERGY_MODES[car.energy_mode]
        t += delta
        if car.soc < 0.5:
            t += 0.6
            car.clipping += 1
        t += car.damage
        t += float(self.rng.normal(0.0, 0.18))
        car.lap_target = t
        car.deployed = 6.5 - net * 0.5 + float(self.rng.normal(0, 0.1))
        car.harvested = car.deployed + net
        if self.status == GREEN:
            car.soc = float(np.clip(car.soc + net + float(self.rng.normal(0, 0.05)), 0.0, 4.0))
        else:
            car.soc = min(car.soc + 0.9, 4.0)
        trap_base = 322.0 + (6.0 if car.energy_mode in ("BOOST", "OVERTAKE") else 0.0)
        trap_base -= 9.0 if car.soc < 0.8 else 0.0
        car.trap = trap_base - car.pace * 3.0 + float(self.rng.normal(0.0, 1.2))

    def _choose_mode(self, car: Car) -> str:
        if car.instructed_mode:
            mode = car.instructed_mode
            if mode in ("BOOST", "OVERTAKE") and car.soc < 0.7:
                return "TABUNG"
            return "NETRAL" if mode == "OVERTAKE" and not car.overtake_ready else mode
        if car.overtake_ready and car.soc > 1.4:
            return "OVERTAKE"
        if car.soc < 1.0:
            return "TABUNG"
        return "NETRAL"

    def _start_neutral(self, kind: int, laps: int) -> None:
        if self.status != GREEN or self.finished:
            return
        self.status = kind
        self.neutral_until = self.leader_lap + laps
        if kind == RED:
            self.red_timer = 120.0
            self._message("red", "BENDERA MERAH: semua mobil masuk pit lane")
        else:
            rivals = [car for car in self.cars if not car.own and not car.retired]
            victim = rivals[int(self.rng.integers(len(rivals)))]
            victim.retired = True
            label = "Safety Car" if kind == SC else "Virtual Safety Car"
            self._message("red", f"{label} keluar: {victim.code} berhenti di lintasan")

    def _end_neutral(self) -> None:
        self.status = GREEN
        for car in self.cars:
            car.neutral_checked = False
        self._message("info", "Lintasan hijau: restart")

    def _rain_now(self) -> float:
        rain = self.scenario.rain
        if rain is None:
            return max(self.wetness - 0.002, 0.0)
        onset, ramp, peak, dry = rain
        lap = self.leader_lap
        rising = min(max((lap - onset) / max(ramp, 1), 0.0), 1.0) * peak
        falling = min(max(1.0 - (lap - dry) / 6.0, 0.0), 1.0)
        return rising * falling

    def _tick_events(self) -> None:
        lap = self.leader_lap
        for event in list(self._scripted):
            if lap >= event[0] - 1 and self.status == GREEN:
                kind = {"SC": SC, "VSC": VSC, "RED": RED}[event[1]]
                self._scripted.remove(event)
                self._start_neutral(kind, event[2])
        if self.status in (SC, VSC) and lap >= self.neutral_until:
            self._end_neutral()
        self.wetness = self._rain_now()

    def _speed(self, car: Car, rank: int) -> float:
        base = 1.0 / car.lap_target
        ref = 1.0 / (self.c.base_lap + 4.0)
        if self.status == VSC:
            return ref * 0.72
        if self.status == SC:
            return ref * (0.62 if rank == 0 else 0.82)
        if self.status == RED:
            return ref * 0.6
        return base

    def step(self, dt: float) -> None:
        if not self.started or self.finished:
            return
        self.t += dt
        self._tick_events()
        if self.status == RED:
            self.red_timer -= dt
            if self.red_timer <= 0:
                self._restart_from_red()
                return
        alive = sorted((car for car in self.cars if not car.retired and not car.done), key=lambda car: -car.dist)
        prev: Car | None = None
        prev_v = 0.0
        rank = 0
        for car in alive:
            v = self._speed(car, rank)
            if car.in_pit:
                v = car.pit_rate
            elif prev is not None and not prev.in_pit:
                gap_s = (prev.dist - car.dist) / max(v, 1e-6)
                if self.status == GREEN and gap_s < 0.3 and v > prev_v and self.t > car.passing_until:
                    advantage = prev.lap_target - car.lap_target
                    threshold = 0.25 + 1.4 * self.c.overtake_difficulty - (0.35 if car.energy_mode == "OVERTAKE" else 0.0)
                    p_lap = 1.0 / (1.0 + math.exp(max(min(-(advantage - threshold) / 0.25, 40), -40)))
                    hazard = -math.log(max(1.0 - p_lap, 1e-6)) / car.lap_target
                    if self.rng.random() < hazard * dt or advantage > 1.8:
                        car.passing_until = self.t + 4.0
                    else:
                        v = prev_v
                        car.held_laps = max(car.held_laps, 1)
                elif self.status == SC and gap_s < 0.9:
                    v = min(v, prev_v)
            if not car.in_pit:
                rank += 1
            before = car.dist
            car.dist += v * dt
            self._cross(car, before, v, dt)
            if not car.in_pit:
                prev, prev_v = car, v
        for car in self.cars:
            car.overtake_ready = False
        ordered = sorted(alive, key=lambda car: -car.dist)
        for ahead, car in zip(ordered, ordered[1:]):
            lap_s = self.c.base_lap + 4.0
            car.overtake_ready = (ahead.dist - car.dist) * lap_s <= self.c.detection_gap_s and self.status == GREEN

    def _restart_from_red(self) -> None:
        order = sorted((car for car in self.cars if not car.retired), key=lambda car: -car.dist)
        base = float(self.leader_lap)
        for i, car in enumerate(order):
            car.dist = base - 0.0015 * i
            car.lap = int(base)
            car.lap_start = self.t
            car.in_pit = False
            car.pit_comp = None
            target = car.pit_request
            if target is None:
                left = self.c.laps - car.lap
                target = H if left > life_laps(self.c, M) else M
                if target == car.comp and not (car.used & ~(1 << car.comp) & 0b111):
                    target = M if target == H else H
            self._fit(car, target, free=True)
            car.pit_request = None
            self._new_lap_target(car)
        self.status = GREEN
        self._message("info", "Restart dari grid setelah bendera merah")

    def _fit(self, car: Car, comp: int, free: bool = False) -> None:
        car.comp = comp
        car.age = 0
        car.wear = 0.0
        car.used |= 1 << comp
        car.new_set = True
        if not free:
            car.stops += 1
        self.pit_log.append({"lap": car.lap, "code": car.code, "compound": COMPOUNDS[comp]})

    def _wants_pit(self, car: Car) -> bool:
        lap_now = car.lap + 1
        if car.pit_request is not None:
            return True
        if car.own:
            return False
        left = self.c.laps - lap_now
        if car.comp <= H and self.wetness > SLICK_TO_INTER + 0.02:
            car.pit_request = I
            return True
        if car.comp == I and self.wetness < 0.08 and left > 3:
            car.pit_request = M
            return True
        if self.status in (SC, VSC) and not car.neutral_checked:
            car.neutral_checked = True
            if car.age >= 8 and left > 6 and self.rng.random() < 0.6:
                car.pit_request = self._rival_compound(car)
                if car.plan:
                    car.plan.pop(0)
                return True
        if self.wetness < 0.05 and car.plan and lap_now >= car.plan[0][0]:
            car.pit_request = car.plan.pop(0)[1]
            return True
        dry = car.used & 0b111
        needs = (dry & (dry - 1)) == 0 and not (car.used & 0b11000)
        if needs and left <= 2:
            car.pit_request = M if car.comp == H else H
            return True
        return False

    def _rival_compound(self, car: Car) -> int:
        left = self.c.laps - car.lap
        comp = S if left <= life_laps(self.c, S) * 0.9 else (M if left <= life_laps(self.c, M) * 0.95 else H)
        if comp == car.comp:
            comp = H if comp != H else M
        return comp

    def _cross(self, car: Car, before: float, v: float, dt: float) -> None:
        frac = car.dist - math.floor(car.dist)
        if car.in_pit and car.dist >= car.pit_exit_dist:
            car.in_pit = False
            car.out_lap = True
        if not car.in_pit and frac >= PIT_ENTRY and frac < 0.995 and self.status != RED and self._wants_pit(car):
            lane = 0.065 * car.lap_target + self.c.pit_lane_loss
            stationary = float(self.rng.normal(STATIONARY_MEAN, STATIONARY_SD))
            if self.rng.random() < 0.03:
                stationary += float(self.rng.exponential(3.0))
            mate = next((m for m in self.cars if m.team == car.team and m is not car), None)
            if mate is not None and mate.in_pit and mate.pit_comp is not None:
                stationary += STACK_LOSS
            car.in_pit = True
            car.in_lap = True
            car.pit_rate = 0.065 / (lane + stationary)
            car.pit_exit_dist = math.floor(car.dist) + 1 + PIT_EXIT
            car.pit_comp = car.pit_request
            car.pit_request = None
            self.pit_log.append({"lap": car.lap + 1, "code": car.code, "event": "in"})

        marks = int(max(frac, 0.0) * 3) if car.dist >= 0 else 0
        if car.dist >= 0 and marks > car.sector_marks and marks < 3:
            car.sectors[marks - 1] = round(self.t - car.sector_t, 3)
            car.sector_t = self.t
            car.sector_marks = marks

        if math.floor(car.dist) > math.floor(before) and car.dist >= 1.0:
            over = (car.dist - math.floor(car.dist)) / max(v, 1e-6)
            crossing = self.t - over
            lap_time = crossing - car.lap_start
            car.sectors[2] = round(crossing - car.sector_t, 3)
            car.lap += 1
            car.lap_start = crossing
            car.sector_t = crossing
            car.sector_marks = 0
            car.last_lap = round(lap_time, 3)
            neutral = self.status != GREEN
            if not neutral and (car.best_lap is None or lap_time < car.best_lap):
                car.best_lap = round(lap_time, 3)
            self.pending_laps.append({
                "code": car.code, "lap": car.lap, "time": round(lap_time, 3), "elapsed": round(crossing, 3),
                "comp": car.comp, "age": car.age + 1, "in_lap": car.in_lap, "out_lap": car.out_lap,
                "status": self.status, "sectors": list(car.sectors), "energy_delta": ENERGY_MODES[car.energy_mode][1]
                if car.own else 0.0, "held": car.held_laps > 0,
            })
            car.in_lap = False
            car.out_lap = False
            car.held_laps = 0
            car.age += 1
            car.wear += 1.0 if not neutral else 0.3
            if car.own:
                car.fuel_kg = max(FUEL_START_KG * (1 - car.lap / self.c.laps) + 0.4 * math.sin(car.lap / 7), 0.0)
            if car.pit_comp is not None:
                self._fit(car, car.pit_comp)
                car.pit_comp = None
            self._new_lap_target(car)
            if car.lap >= self.c.laps or self.flag_lap:
                self.flag_lap = self.flag_lap or car.lap
                self._finish_car(car, crossing)

    def _finish_car(self, car: Car, crossing: float) -> None:
        # Freeze the classification: earlier finishers stay ahead on the same lap.
        order = sum(1 for other in self.cars if other.done)
        car.done = True
        car.finish_t = crossing
        car.in_pit = False
        car.dist = float(car.lap) - 1e-4 * order
        if all(other.done or other.retired for other in self.cars):
            self.finished = True
            self._message("info", "Bendera finis")

    # -- outbound frames ------------------------------------------------------
    def _timing(self) -> dict:
        lap_s = self.c.base_lap + 4.0
        order = sorted(self.cars, key=lambda car: (car.retired, -car.dist))
        leader_dist = order[0].dist
        rows = []
        prev = None
        for i, car in enumerate(order):
            gap = (leader_dist - car.dist) * lap_s
            interval = None if prev is None else (prev.dist - car.dist) * lap_s
            if car.finish_t is not None and order[0].finish_t is not None and car.lap == order[0].lap:
                gap = car.finish_t - order[0].finish_t
                interval = None if prev is None or prev.finish_t is None else car.finish_t - prev.finish_t
            frac = max(car.dist, 0.0) % 1.0
            rows.append({
                "code": car.code, "team": car.team, "color": car.color, "own": car.own, "pos": i + 1,
                "lap": car.lap, "gap": round(gap, 2), "interval": None if interval is None else round(interval, 2),
                "u": round(frac, 4), "last_lap": car.last_lap, "best_lap": car.best_lap,
                "sectors": car.sectors, "compound": car.comp, "age": car.age, "new_set": car.new_set,
                "stops": car.stops, "used": car.used, "in_pit": car.in_pit, "retired": car.retired, "grid": car.grid,
                "done": car.done,
                "trap": round(car.trap, 1), "tendency": car.tendency, "has_history": car.has_history,
            })
            prev = car
        laps, self.pending_laps = self.pending_laps, []
        return {"ts": round(self.t, 2), "leader_lap": self.leader_lap, "total_laps": self.c.laps, "cars": rows,
                "completed": laps, "finished": self.finished}

    def _telemetry(self) -> dict:
        cars = {}
        for car in self.cars:
            if not car.own:
                continue
            load = 1.0 + car.wear * 0.012
            surface = [round(98 + 6 * load + float(self.rng.normal(0, 1.0)) + d, 1) for d in (2, 0, 4, 1)]
            cars[car.code] = {
                "tyre_surface_c": surface,
                "tyre_core_c": [round(s - 8 + float(self.rng.normal(0, 0.4)), 1) for s in surface],
                "tyre_pressure_psi": [round(21.5 + car.wear * 0.015 + d, 2) for d in (0.2, 0.2, 0, 0)],
                "tyre_wear_pct": round(min(car.wear / max(life_laps(self.c, car.comp) + car.cliff_shift, 1) * 100, 100), 1),
                "soc_mj": round(car.soc, 2),
                "harvested_mj": round(car.harvested, 2),
                "deployed_mj": round(car.deployed, 2),
                "energy_mode": car.energy_mode,
                "overtake_available": car.overtake_ready,
                "clipping_events": car.clipping,
                "fuel_kg": round(car.fuel_kg, 1),
                "fuel_target_kg": round(FUEL_START_KG * (1 - car.lap / self.c.laps), 1),
                "oil_c": round(118 + float(self.rng.normal(0, 0.5)) + car.wear * 0.02, 1),
                "water_c": round(112 + float(self.rng.normal(0, 0.5)), 1),
                "mguk_c": round(96 + (4 if car.energy_mode in ("BOOST", "OVERTAKE") else 0) + float(self.rng.normal(0, 0.6)), 1),
                "battery_c": round(44 + car.soc * 0.7 + float(self.rng.normal(0, 0.2)), 1),
                "brake_c": [round(640 + d + float(self.rng.normal(0, 8)) + (40 if car.held_laps else 0), 0)
                            for d in (30, 25, 0, 5)],
                "brake_wear_pct": round(car.lap / self.c.laps * 70, 1),
                "aero_mode": "lurus" if int(self.t / 7) % 2 else "tikungan",
                "aero_load_delta_pct": round(-car.damage * 13.0 + float(self.rng.normal(0, 0.15)), 1),
            }
        return {"ts": round(self.t, 2), "cars": cars}

    def _race_control(self) -> dict:
        msgs, self.pending_msgs = self.pending_msgs, []
        return {"ts": round(self.t, 2), "status": STATUS_NAMES[self.status], "pit_open": self.status != RED,
                "flags": {"s1": STATUS_NAMES[self.status], "s2": STATUS_NAMES[self.status],
                          "s3": STATUS_NAMES[self.status]},
                "neutral_until": self.neutral_until if self.status != GREEN else None, "messages": msgs}

    def _weather(self) -> dict:
        rain = self.scenario.rain
        eta = None
        if rain is not None and self.leader_lap < rain[0]:
            # Radar reports minutes, not laps, and carries its own error.
            eta = max((rain[0] - self.leader_lap) * (self.c.base_lap + 4) / 60 + float(self.rng.normal(0, 0.5)), 0.0)
        return {"ts": round(self.t, 2), "air_c": self.c.air_temp, "track_c": self.track_temp, "humidity": 52, "wind_kph": 11,
                "wetness": round(self.wetness, 3), "rain_eta_min": None if eta is None else round(eta, 1),
                "rain_forecast": rain if rain is not None and self.leader_lap >= rain[0] - 12 else None}

    def frame(self) -> dict:
        self.seq += 1
        out: dict = {"seq": self.seq, "t": round(self.t, 2)}
        builders = {"timing": self._timing, "telemetry": self._telemetry,
                    "race_control": self._race_control, "weather": self._weather}
        for source, build in builders.items():
            if source not in self.dropped:
                out[source] = build()
        return out

    def fp_report(self) -> dict:
        """Simulated long-run analysis: the priors a team would carry out of practice.

        A sprint weekend has one practice session, so its estimates are wider.
        """
        widen = 1.7 if self.c.weekend == "sprint" else 1.0
        report = {}
        for car in self.cars:
            mult_sd = (0.07 if car.own else 0.16) * widen
            pace_sd = (0.05 if car.own else 0.12) * widen
            report[car.code] = {"pace": car.pace + float(self.rng.normal(0, pace_sd)), "pace_sd": pace_sd,
                                "mult": max(car.mult + float(self.rng.normal(0, mult_sd)), 0.4), "mult_sd": mult_sd}
        return report

    def truth(self) -> dict:
        """Ground truth for scoring only. The live session must never call this."""
        return {car.code: {"mult": car.mult, "pace": car.pace, "cliff_shift": car.cliff_shift, "wear": car.wear,
                           "comp": car.comp, "true_deg": self._true_deg(car), "soc": car.soc}
                for car in self.cars}
