"""Reference data: circuits, teams, scenarios.

Values listed in `Circuit.verified` come from public or official documents.
Everything else (pit loss, hazard rates, team pace) is an illustrative default
that must be calibrated from real data before any production use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def id_text(text: str) -> str:
    """Indonesian decimal comma for numbers inside user-facing sentences."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


@dataclass(frozen=True)
class Circuit:
    id: str
    name: str
    laps: int
    length_km: float
    base_lap: float            # clean lap, zero fuel, fresh Soft, reference car
    pit_lane_loss: float       # seconds lost in the pit lane, excluding stationary time
    overtake_difficulty: float # 0 easy, 1 nearly impossible
    sc_per_race: float
    vsc_per_race: float
    red_per_race: float
    tyre_severity: float       # 1.0 is average
    compounds: dict[str, str]
    track_temp: float
    air_temp: float
    recharge_race_mj: float
    recharge_overtake_mj: float
    detection_gap_s: float
    detection_m: int | None
    weekend: str               # "standard" or "sprint"
    outline: tuple[tuple[float, float], ...]
    verified: tuple[str, ...] = ()


CIRCUITS: dict[str, Circuit] = {
    "silverstone": Circuit(
        id="silverstone", name="Silverstone", laps=52, length_km=5.891, base_lap=86.5,
        pit_lane_loss=18.0, overtake_difficulty=0.40, sc_per_race=0.9, vsc_per_race=0.5,
        red_per_race=0.08, tyre_severity=1.15,
        compounds={"S": "C3", "M": "C2", "H": "C1"}, track_temp=34.0, air_temp=22.0,
        recharge_race_mj=8.0, recharge_overtake_mj=8.5, detection_gap_s=1.0, detection_m=5560,
        weekend="sprint",
        # Schematic trace in race direction, starting at the start/finish line.
        outline=((18, 72), (45, 53), (102, 57), (137, 36), (152, 58), (163, 34), (65, 10),
                 (50, 33), (63, 3), (155, 0), (170, 92), (187, 108), (185, 133), (195, 160),
                 (162, 172), (92, 300), (65, 285), (30, 262), (20, 232)),
        verified=("panjang lap", "batas recharge race 8,0/8,5 MJ", "gap deteksi 1,0 dtk",
                  "garis deteksi 5560 m", "akhir pekan sprint"),
    ),
    "monza": Circuit(
        id="monza", name="Monza", laps=53, length_km=5.793, base_lap=79.5,
        pit_lane_loss=21.5, overtake_difficulty=0.25, sc_per_race=0.6, vsc_per_race=0.4,
        red_per_race=0.06, tyre_severity=0.85,
        compounds={"S": "C5", "M": "C4", "H": "C3"}, track_temp=38.0, air_temp=27.0,
        recharge_race_mj=8.5, recharge_overtake_mj=9.0, detection_gap_s=1.0, detection_m=None,
        weekend="standard",
        outline=((60, 250), (60, 130), (56, 52), (68, 44), (58, 30), (84, 8), (138, 10),
                 (176, 40), (182, 58), (196, 66), (194, 86), (160, 118), (176, 138), (150, 152),
                 (118, 148), (92, 184), (112, 196), (96, 216), (120, 262), (96, 292), (66, 286)),
        verified=("panjang lap", "jumlah lap"),
    ),
    "spa": Circuit(
        id="spa", name="Spa-Francorchamps", laps=44, length_km=7.004, base_lap=103.0,
        pit_lane_loss=19.0, overtake_difficulty=0.30, sc_per_race=1.0, vsc_per_race=0.6,
        red_per_race=0.15, tyre_severity=1.0,
        compounds={"S": "C4", "M": "C3", "H": "C2"}, track_temp=26.0, air_temp=18.0,
        recharge_race_mj=8.5, recharge_overtake_mj=9.0, detection_gap_s=1.0, detection_m=None,
        weekend="standard",
        outline=((70, 214), (42, 200), (58, 236), (88, 202), (132, 136), (206, 62), (228, 18),
                 (262, 6), (286, 28), (262, 66), (222, 74), (204, 102), (226, 132), (198, 160),
                 (176, 142), (150, 174), (160, 208), (130, 250), (102, 268), (92, 246)),
        verified=("panjang lap", "jumlah lap"),
    ),
}


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    color: str
    drivers: tuple[str, str]
    pace: float            # illustrative s/lap gap to the reference car
    tendency: float        # -1 stays out long, +1 pits early
    has_history: bool = True


TEAMS: tuple[Team, ...] = (
    Team("mclaren", "McLaren", "#FF8000", ("NOR", "PIA"), 0.05, 0.3),
    Team("mercedes", "Mercedes", "#27F4D2", ("RUS", "ANT"), 0.00, 0.1),
    Team("ferrari", "Ferrari", "#E8002D", ("LEC", "HAM"), 0.10, -0.2),
    Team("redbull", "Red Bull", "#3671C6", ("VER", "HAD"), 0.15, 0.4),
    Team("williams", "Williams", "#64C4FF", ("ALB", "SAI"), 0.55, 0.0),
    Team("racingbulls", "Racing Bulls", "#6692FF", ("LAW", "LIN"), 0.65, 0.2),
    Team("haas", "Haas", "#B6BABD", ("OCO", "BEA"), 0.70, -0.3),
    Team("astonmartin", "Aston Martin", "#229971", ("ALO", "STR"), 0.80, 0.1),
    Team("alpine", "Alpine", "#FF87BC", ("GAS", "COL"), 0.85, -0.1),
    Team("audi", "Audi", "#BB0A30", ("HUL", "BOR"), 0.95, 0.0),
    Team("cadillac", "Cadillac", "#C9A227", ("PER", "BOT"), 1.20, 0.0, has_history=False),
)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    events: tuple[tuple[int, str, int], ...] = ()  # (lap, kind, laps)
    rain: tuple[int, int, float, int] | None = None  # onset lap, ramp laps, peak, dry lap
    random_events: bool = False


SCENARIOS: dict[str, Scenario] = {
    "bersih": Scenario("bersih", "Balapan bersih", "Tanpa gangguan, murni adu strategi ban dan energi."),
    "sc-awal": Scenario("sc-awal", "Safety Car awal", "Safety Car keluar di lap 14.",
                        events=((14, "SC", 4),)),
    "vsc-sc": Scenario("vsc-sc", "VSC lalu Safety Car", "VSC di lap 11, Safety Car di lap 33.",
                       events=((11, "VSC", 2), (33, "SC", 4))),
    "hujan": Scenario("hujan", "Hujan di tengah race", "Hujan mulai lap 26 dan mereda lap 42.",
                      rain=(26, 5, 0.42, 42)),
    "bendera-merah": Scenario("bendera-merah", "Bendera merah", "Red flag di lap 20.",
                              events=((20, "RED", 1),)),
    "acak": Scenario("acak", "Acak", "Kejadian diundi dari statistik sirkuit.", random_events=True),
}


def team_by_id(team_id: str) -> Team:
    for team in TEAMS:
        if team.id == team_id:
            return team
    raise KeyError(team_id)


def catalog_payload() -> dict:
    return {
        "circuits": [
            {"id": c.id, "name": c.name, "laps": c.laps, "length_km": c.length_km,
             "weekend": c.weekend, "compounds": c.compounds, "outline": c.outline,
             "verified": c.verified, "recharge_race_mj": c.recharge_race_mj,
             "recharge_overtake_mj": c.recharge_overtake_mj, "pit_lane_loss": c.pit_lane_loss}
            for c in CIRCUITS.values()
        ],
        "teams": [{"id": t.id, "name": t.name, "color": t.color, "drivers": t.drivers,
                   "has_history": t.has_history} for t in TEAMS],
        "scenarios": [{"id": s.id, "name": s.name, "description": s.description}
                      for s in SCENARIOS.values()],
    }
