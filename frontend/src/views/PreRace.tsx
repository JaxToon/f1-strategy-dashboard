import { useEffect, useState } from "react";
import { allowed, get, post } from "../api";
import { Compound, Empty, Panel, num, percent, signed } from "../components/Common";
import type { Catalog, PlanCard, PlaybookRow, PreRaceData, State, WindowStop } from "../types";

interface Props {
  state: State;
  catalog: Catalog;
  role: string;
  prerace: PreRaceData | null;
  setPrerace: (data: PreRaceData | null) => void;
}

export function PreRace({ state, catalog, role, prerace, setPrerace }: Props) {
  const own = state.session.own;
  const [car, setCar] = useState(own[0]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [rival, setRival] = useState("");
  const [cut, setCut] = useState<{ gap: number; rows: { laps: number; undercut_gain: number; undercut_net: number; overcut_gain: number; overcut_net: number; undercut_works: boolean; overcut_works: boolean }[] } | null>(null);
  const selected = own.includes(car) ? car : own[0];
  const others = catalog.teams.flatMap((team) => team.drivers).filter((code) => !own.includes(code));
  const raced = state.phase !== "prerace";

  useEffect(() => {
    if (state.prerace_ready && !prerace) get<PreRaceData>("/api/prerace").then(setPrerace);
  }, [state.prerace_ready, state.session.id]);

  useEffect(() => {
    if (!rival && others.length) setRival(others[0]);
  }, [others.join()]);

  useEffect(() => {
    if (rival) get<NonNullable<typeof cut>>(`/api/undercut?car=${selected}&rival=${rival}`).then(setCut).catch(() => setCut(null));
  }, [rival, selected, state.prerace_ready]);

  const configure = async (patch: Partial<{ circuit: string; team: string; scenario: string; seed: number }>) => {
    setPrerace(null);
    setProblem(null);
    await post("/api/session", {
      circuit: state.session.circuit, team: state.session.team_id, scenario: state.session.scenario_id,
      seed: state.session.seed, ...patch,
    });
  };

  const run = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setPrerace(await post<PreRaceData>("/api/prerace/run"));
    } catch (failure) {
      setProblem((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const lock = async () => {
    if (!confirm("Kunci Plan A, B, dan C untuk race ini? Setelah terkunci, perubahan plan hanya lewat pemicu.")) return;
    try {
      await post("/api/prerace/lock");
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  };

  const circuit = catalog.circuits.find((c) => c.id === state.session.circuit);
  const plans = prerace?.plans[selected] ?? [];

  return (
    <main className="prerace">
      <section className="setup" aria-label="Pengaturan akhir pekan">
        <label>Sirkuit
          <select disabled={raced} value={state.session.circuit} onChange={(event) => configure({ circuit: event.target.value })}>
            {catalog.circuits.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>Tim
          <select disabled={raced} value={state.session.team_id} onChange={(event) => configure({ team: event.target.value })}>
            {catalog.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
        <label>Skenario latihan
          <select disabled={raced} value={state.session.scenario_id} onChange={(event) => configure({ scenario: event.target.value })}>
            {catalog.scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <div className="facts">
          <span>{circuit?.laps} lap, {num(circuit?.length_km, 3)} km</span>
          <span>S {state.session.compounds.S}, M {state.session.compounds.M}, H {state.session.compounds.H}</span>
          <span>Recharge {num(circuit?.recharge_race_mj, 1)} MJ, Overtake {num(circuit?.recharge_overtake_mj, 1)} MJ</span>
          {state.session.weekend === "sprint" && <span className="warn-text">Akhir pekan sprint: data FP lebih sedikit, prior lebih lebar</span>}
        </div>
        <button className="primary" onClick={run} disabled={busy || raced}>
          {busy ? "Menjalankan ribuan race" : prerace ? "Hitung ulang" : "Jalankan simulasi"}
        </button>
      </section>
      {problem && <p className="error banner">{problem}</p>}

      {!prerace ? (
        <section className="start-card">
          <h2>{busy ? "Mensimulasikan seluruh grid" : `Rencanakan ${state.session.circuit_name}`}</h2>
          <p>{busy ? "Biasanya selesai dalam 15 sampai 25 detik." : "Simulasi menghasilkan Plan A, B, C untuk kedua mobil, lengkap dengan playbook SC, VSC, dan bendera merah."}</p>
          {circuit && <p className="verified">Sudah cocok dengan dokumen resmi: {circuit.verified.join(", ")}. Nilai lain contoh, perlu dikalibrasi.</p>}
        </section>
      ) : (
        <>
          <div className="board-head">
            <div className="car-switch" role="tablist" aria-label="Pilih mobil">
              {own.map((code) => (
                <button key={code} role="tab" aria-selected={code === selected} onClick={() => setCar(code)}>{code}</button>
              ))}
            </div>
            <p>{prerace.n_races.toLocaleString("id-ID")} race, {num(prerace.elapsed_s, 1)} dtk</p>
            <a className="button" href="/api/prerace/brief" target="_blank" rel="noreferrer">Buka brief pra-race</a>
            {state.locked
              ? <span className="locked">Terkunci oleh {state.locked.by}, {state.locked.at}</span>
              : <button disabled={!allowed(role, "lock")} onClick={lock} title={allowed(role, "lock") ? "" : "Hanya Chief of Strategy"}>Kunci Plan A/B/C</button>}
          </div>
          <div className="plans">
            {plans.map((plan) => <PlanColumn key={plan.name} plan={plan} teamCount={22} />)}
          </div>
          <div className="prerace-grid">
            <Panel title="Grafik jendela pit">
              {prerace.windows[selected].map((stop) => <WindowStrip key={stop.stop} stop={stop} />)}
              <div className="legend">
                <span><i className="swatch z-optimal" />Optimal</span>
                <span><i className="swatch z-layak" />Layak</span>
                <span><i className="swatch z-buruk" />Rugi waktu</span>
                <span><i className="swatch z-lalu-lintas" />Keluar di lalu lintas</span>
              </div>
            </Panel>
            <Panel title="Playbook SC, VSC, bendera merah">
              <Playbook rows={prerace.playbook[selected]} />
            </Panel>
            <Panel title="Kalkulator undercut dan overcut"
              aside={<select aria-label="Lawan" value={rival} onChange={(event) => setRival(event.target.value)}>{others.map((code) => <option key={code}>{code}</option>)}</select>}>
              {cut ? (
                <>
                  <p className="hint">Gap sekarang {num(cut.gap, 1)} dtk, positif berarti {rival} di depan. Dihitung bila pit lebih dulu atau lebih lambat sekian lap.</p>
                  <table className="plain">
                    <thead><tr><th>Lap</th><th>Undercut</th><th>Bersih</th><th>Overcut</th><th>Bersih</th></tr></thead>
                    <tbody>
                      {cut.rows.map((row) => (
                        <tr key={row.laps}>
                          <td>{row.laps}</td>
                          <td>{signed(row.undercut_gain, 2)}</td>
                          <td className={row.undercut_works ? "good" : ""}>{signed(row.undercut_net, 2)}</td>
                          <td>{signed(row.overcut_gain, 2)}</td>
                          <td className={row.overcut_works ? "good" : ""}>{signed(row.overcut_net, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : <Empty>Pilih lawan untuk melihat perhitungan.</Empty>}
            </Panel>
            <Panel title="Skenario cuaca">
              {prerace.weather[selected].length ? (
                <table className="plain">
                  <thead><tr><th>Hujan mulai</th><th>Ganti ke inter</th><th>Posisi harapan</th><th>Bila tetap slick</th></tr></thead>
                  <tbody>
                    {prerace.weather[selected].map((row) => (
                      <tr key={row.minute}>
                        <td>Menit {row.minute}, lap {row.onset_lap}</td>
                        <td><Compound code="I" size="sm" /> lap {row.crossover_lap}</td>
                        <td>{num(row.e_pos, 1)}</td>
                        <td>{num(row.e_pos_stay, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty>Tidak ada skenario cuaca untuk race ini.</Empty>}
            </Panel>
          </div>
        </>
      )}
    </main>
  );
}

function PlanColumn({ plan, teamCount }: { plan: PlanCard; teamCount: number }) {
  const hist = plan.hist.slice(0, teamCount);
  const peak = Math.max(...hist, 0.001);
  return (
    <article className={`plan plan-${plan.name}`}>
      <header>
        <span className="plan-name">{plan.name}</span>
        <div className="plan-seq">
          <Compound code={plan.start} />
          {plan.plan.map((stop) => (
            <span key={stop.lap} className="stint"><b>{stop.lap}</b><Compound code={stop.compound} /></span>
          ))}
        </div>
      </header>
      <dl className="figures">
        <div><dt>Posisi harapan</dt><dd>{num(plan.e_pos, 1)}</dd></div>
        <div><dt>Rentang P10-P90</dt><dd>{plan.p10}-{plan.p90}</dd></div>
        <div><dt>Peluang poin</dt><dd>{percent(plan.p_points)}</dd></div>
      </dl>
      <div className="hist" role="img" aria-label={`Sebaran posisi finis plan ${plan.name}. Puncak di posisi ${hist.indexOf(Math.max(...hist)) + 1}.`}>
        {hist.map((value, i) => (
          <span key={i} title={`P${i + 1}: ${percent(value)}`} style={{ height: `${(value / peak) * 100}%` }} />
        ))}
      </div>
      <div className="hist-axis"><span>P1</span><span>P10</span><span>P22</span></div>
      <ul className="triggers">
        {plan.triggers.length ? plan.triggers.map((t) => <li key={t.text}>{t.text}</li>) : <li>Rencana utama</li>}
      </ul>
    </article>
  );
}

function WindowStrip({ stop }: { stop: WindowStop }) {
  return (
    <div className="window">
      <h3>Stop {stop.stop} <Compound code={stop.compound} size="sm" /></h3>
      <div className="cells">
        {stop.laps.map((cell) => (
          <div key={cell.lap} className={`cell z-${cell.zone} ${cell.lap === stop.planned ? "planned" : ""}`}
            title={`Lap ${cell.lap}: posisi harapan ${num(cell.e_pos, 1)}, ${cell.traffic} mobil di titik keluar`}>
            <b>{cell.lap}</b>
            <span>{num(cell.e_pos, 1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Playbook({ rows }: { rows: PlaybookRow[] }) {
  const laps = [...new Set(rows.map((r) => r.lap))].sort((a, b) => a - b);
  const lookup = new Map(rows.map((r) => [`${r.event}-${r.lap}`, r]));
  const names: [string, string][] = [["SC", "SC"], ["VSC", "VSC"], ["RED", "Merah"]];
  return (
    <div className="playbook">
      <table>
        <thead>
          <tr><th>Lap</th>{laps.map((lap) => <th key={lap}>{lap}</th>)}</tr>
        </thead>
        <tbody>
          {names.map(([event, label]) => (
            <tr key={event}>
              <th>{label}</th>
              {laps.map((lap) => {
                const row = lookup.get(`${event}-${lap}`);
                const box = row?.action === "BOX";
                return (
                  <td key={lap} className={box ? "box" : ""}
                    title={row ? `${box ? `Box ke ${row.compound}` : "Stay"}: ${signed(row.gain_pos, 2)} posisi, keyakinan ${percent(row.confidence)}` : ""}>
                    {box ? row?.compound : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">Sel berisi kompon berarti box bila kejadian keluar di lap itu. Sel kosong berarti stay.</p>
    </div>
  );
}
