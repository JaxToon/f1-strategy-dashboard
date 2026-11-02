import { useEffect, useState } from "react";
import { allowed, get, post, setRole } from "./api";
import { num } from "./components/Common";
import { useLive } from "./useLive";
import { PreRace } from "./views/PreRace";
import { Race } from "./views/Race";
import { ReviewView } from "./views/ReviewView";
import type { Catalog, PreRaceData } from "./types";

type Mode = "prerace" | "race" | "review";

const statusNames: Record<string, string> = { GREEN: "Hijau", VSC: "VSC", SC: "Safety Car", RED: "Bendera merah" };

function savedTheme() {
  try {
    return localStorage.getItem("theme") ?? "dark";
  } catch {
    return "dark";
  }
}

export function App() {
  const live = useLive();
  const { state } = live;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [mode, setMode] = useState<Mode>("prerace");
  const [role, setRoleState] = useState("strategist");
  const [theme, setTheme] = useState(savedTheme);
  const [prerace, setPrerace] = useState<PreRaceData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    get<Catalog>("/api/catalog").then(setCatalog).catch(() => setProblem("Server belum bisa dihubungi. Jalankan backend lalu muat ulang."));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* the theme simply is not remembered */
    }
  }, [theme]);

  useEffect(() => setRole(role), [role]);

  const phase = state?.phase;
  useEffect(() => {
    if (phase) setMode(phase);
  }, [phase, state?.session.id]);

  useEffect(() => setPrerace(null), [state?.session.id]);

  if (!state || !catalog) {
    return <div className="boot"><p>{problem ?? "Menghubungkan ke server trackside"}</p></div>;
  }

  const startRace = async () => {
    try {
      await post("/api/race/start");
      setMode("race");
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  };

  const newWeekend = async () => {
    await post("/api/session", {
      circuit: state.session.circuit, team: state.session.team_id, scenario: state.session.scenario_id,
      seed: state.session.seed + 1,
    });
    setMode("prerace");
  };

  const circuit = catalog.circuits.find((c) => c.id === state.session.circuit);
  const status = state.status ?? "GREEN";
  const lapsLeft = state.session.total_laps - (state.lap ?? 0);
  const staleAny = Object.values(state.sources).some((s) => s.stale) && state.phase === "race";

  return (
    <div className="app" data-status={status}>
      <header className="status">
        <div className="race-id">
          <strong>{state.session.circuit_name}</strong>
          <span>{state.session.team}</span>
        </div>
        {state.phase !== "prerace" ? (
          <>
            <div className="lapcount">
              <b>{state.lap ?? 0}</b><span>/{state.session.total_laps}</span>
              <small>sisa {lapsLeft}</small>
            </div>
            <div className={`flag flag-${status}`} role="status">{statusNames[status]}</div>
            <dl className="conditions">
              <div><dt>Lintasan</dt><dd>{num(state.weather?.track_c, 0)}°</dd></div>
              <div><dt>Udara</dt><dd>{num(state.weather?.air_c, 0)}°</dd></div>
              <div><dt>Radar hujan</dt><dd>{state.weather?.rain_eta_min != null ? `${num(state.weather.rain_eta_min, 0)} mnt` : (state.weather?.wetness ?? 0) > 0.03 ? "Basah" : "Kering"}</dd></div>
              <div><dt>Pit lane</dt><dd>{state.pit_open === false ? "Tutup" : "Buka"}</dd></div>
            </dl>
          </>
        ) : <p className="prerace-note">Rencanakan strategi, kunci plan, lalu mulai race.</p>}

        <div className="status-right">
          <span className="sim-badge" title="Tidak ada feed tim yang terhubung. Semua data berasal dari simulator.">Data simulasi</span>
          {staleAny && <span className="stale-badge">Feed terlambat</span>}
          {!live.connected && <span className="stale-badge">Terputus dari server</span>}
          {live.latencyP95 !== null && state.phase === "race" && <span className="latency">{Math.round(live.latencyP95)} ms</span>}
          <nav className="modes" aria-label="Mode">
            {([["prerace", "Pra-Race"], ["race", "Race"], ["review", "Pasca-Race"]] as const).map(([id, label]) => (
              <button key={id} aria-current={mode === id} onClick={() => setMode(id)} disabled={id === "race" && state.phase === "prerace"}>{label}</button>
            ))}
          </nav>
          {state.phase === "prerace" ? (
            <button className="primary" onClick={startRace} disabled={!allowed(role, "control")}>Mulai race</button>
          ) : state.phase === "review" ? (
            <button onClick={newWeekend}>Akhir pekan baru</button>
          ) : null}
          <select aria-label="Peran" value={role} onChange={(event) => setRoleState(event.target.value)}>
            {Object.entries(catalog.roles).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <button aria-label="Ganti tema" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "Siang" : "Malam"}</button>
        </div>
      </header>

      {problem && <p className="error banner">{problem}</p>}
      {mode === "prerace" && <PreRace state={state} catalog={catalog} role={role} prerace={prerace} setPrerace={setPrerace} />}
      {mode === "race" && <Race live={live} state={state} circuit={circuit} role={role} theme={theme} prerace={prerace} />}
      {mode === "review" && <ReviewView live={live} state={state} />}
    </div>
  );
}
