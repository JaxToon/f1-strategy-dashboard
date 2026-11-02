"""HTTP and WebSocket API. Holds one active race weekend, served to every screen."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import CIRCUITS, SCENARIOS, TEAMS, catalog_payload
from .session import ROLES, ForbiddenRole, RaceSession

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backend" / "data" / "sessions"
DIST = ROOT / "frontend" / "dist"
TICK_S = 0.2
SEND_TIMEOUT_S = 1.0

app = FastAPI(title="F1 Strategy Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class Hub:
    def __init__(self) -> None:
        self.session = RaceSession("silverstone", "williams", "sc-awal", 42, DATA_DIR)
        self.clients: set[WebSocket] = set()
        self.history_sent = 0

    async def broadcast(self, message: dict) -> None:
        text = json.dumps(message, default=float)
        await asyncio.gather(*(self._send(socket, text) for socket in list(self.clients)))

    async def _send(self, socket: WebSocket, text: str) -> None:
        # A stalled screen must never hold up the race loop; it reconnects and gets a fresh snapshot.
        try:
            await asyncio.wait_for(socket.send_text(text), SEND_TIMEOUT_S)
        except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError):
            self.clients.discard(socket)
            asyncio.create_task(self._close(socket))

    @staticmethod
    async def _close(socket: WebSocket) -> None:
        try:
            await asyncio.wait_for(socket.close(), SEND_TIMEOUT_S)
        except (RuntimeError, asyncio.TimeoutError):
            pass


hub = Hub()


async def race_loop() -> None:
    while True:
        await asyncio.sleep(TICK_S)
        session = hub.session
        try:
            if session.running and session.phase == "race":
                session.advance(TICK_S * session.speed)
                if session.need_recompute and not session.computing:
                    session.need_recompute = False
                    session.computing = True
                    asyncio.create_task(recompute(session))
            if hub.clients:
                laps, session.new_laps = session.new_laps, []
                await hub.broadcast({"type": "state", "state": session.view(), "laps": _slim(laps)})
        except Exception as error:  # the loop must survive anything a model throws
            session.rec_error = f"Kesalahan server: {error}"


async def recompute(session: RaceSession) -> None:
    try:
        await asyncio.to_thread(session.compute_recs)
    except Exception as error:
        session.recs = {}
        session.rec_error = f"Rekomendasi tidak tersedia: {error}"
    finally:
        session.computing = False
        session.compute_started = None


def _slim(laps: list[dict]) -> list[dict]:
    keep = ("code", "lap", "time", "elapsed", "comp", "age", "in_lap", "out_lap", "status")
    return [{k: row[k] for k in keep} for row in laps]


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(race_loop())


def guard(call):
    try:
        return call()
    except ForbiddenRole as error:
        raise HTTPException(403, str(error))
    except ValueError as error:
        raise HTTPException(400, str(error))


class NewSession(BaseModel):
    circuit: str
    team: str
    scenario: str
    seed: int = 42


class Decision(BaseModel):
    car: str
    action: str
    compound: str | None = None
    reason: str = ""


class WhatIf(BaseModel):
    car: str
    stops: list[dict]


class Tag(BaseModel):
    code: str
    tag: str


class Note(BaseModel):
    car: str
    text: str


class Calibration(BaseModel):
    car: str
    deg_mult: float


class Inject(BaseModel):
    kind: str


class Control(BaseModel):
    speed: float | None = None
    running: bool | None = None
    autopilot: bool | None = None


@app.get("/api/catalog")
def catalog() -> dict:
    return catalog_payload() | {"roles": ROLES}


@app.post("/api/session")
def new_session(body: NewSession, x_role: str = Header("strategist")) -> dict:
    if body.circuit not in CIRCUITS or body.scenario not in SCENARIOS or body.team not in {t.id for t in TEAMS}:
        raise HTTPException(400, "Sirkuit, tim, atau skenario tidak dikenal.")
    RaceSession.authorize(x_role, "control") if x_role in ROLES else None
    hub.session = RaceSession(body.circuit, body.team, body.scenario, body.seed, DATA_DIR)
    return hub.session.view()


@app.get("/api/state")
def state() -> dict:
    return hub.session.view()


@app.get("/api/history")
def history() -> list[dict]:
    return hub.session.history_payload()


@app.post("/api/prerace/run")
async def prerace_run() -> dict:
    session = hub.session
    if session.prerace_running:
        raise HTTPException(409, "Simulasi pra-race sedang berjalan.")
    session.prerace_running = True
    try:
        await asyncio.to_thread(session.run_prerace)
    finally:
        session.prerace_running = False
    return session.prerace


@app.get("/api/prerace")
def prerace() -> dict | None:
    return hub.session.prerace


@app.post("/api/prerace/lock")
def prerace_lock(x_role: str = Header("strategist")) -> dict:
    return guard(lambda: hub.session.lock_plans(x_role))


@app.get("/api/prerace/brief", response_class=HTMLResponse)
def prerace_brief() -> str:
    return guard(hub.session.brief_html)


@app.get("/api/undercut")
def undercut(car: str, rival: str) -> dict:
    return guard(lambda: hub.session.undercut(car, rival))


@app.post("/api/race/start")
async def race_start() -> dict:
    session = hub.session
    await asyncio.to_thread(session.start_race)
    return session.view()


@app.post("/api/race/control")
def race_control(body: Control) -> dict:
    session = hub.session
    if body.speed is not None:
        session.speed = max(1.0, min(body.speed, 60.0))
    if body.running is not None:
        session.running = body.running and session.phase == "race"
    if body.autopilot is not None:
        session.autopilot = body.autopilot
    return session.view()


@app.post("/api/race/inject")
def race_inject(body: Inject, x_role: str = Header("strategist")) -> dict:
    guard(lambda: hub.session.inject(x_role, body.kind))
    return {"ok": True}


@app.post("/api/decision")
def decision(body: Decision, x_role: str = Header("strategist")) -> dict:
    return guard(lambda: hub.session.decide(x_role, body.car, body.action, body.compound, body.reason))


@app.post("/api/whatif")
async def what_if(body: WhatIf) -> dict:
    return await asyncio.to_thread(hub.session.apply_whatif, body.car, body.stops)


@app.post("/api/tag")
def tag(body: Tag, x_role: str = Header("strategist")) -> dict:
    return guard(lambda: hub.session.add_tag(x_role, body.code, body.tag))


@app.post("/api/note")
def note(body: Note, x_role: str = Header("strategist")) -> dict:
    return guard(lambda: hub.session.add_note(x_role, body.car, body.text))


@app.post("/api/calibrate")
def calibrate(body: Calibration, x_role: str = Header("strategist")) -> dict:
    return guard(lambda: hub.session.calibrate(x_role, body.car, body.deg_mult))


@app.get("/api/review")
def review() -> dict:
    return hub.session.review()


@app.websocket("/ws")
async def websocket(socket: WebSocket) -> None:
    await socket.accept()
    hub.clients.add(socket)
    session = hub.session
    await socket.send_text(json.dumps({"type": "hello", "state": session.view(), "history": session.history_payload(),
                                       "server_time": time.time()}, default=float))
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        hub.clients.discard(socket)


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = DIST / path
        return FileResponse(target if path and target.is_file() else DIST / "index.html")
