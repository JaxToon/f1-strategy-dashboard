import { useCallback, useEffect, useState } from "react";
import { allowed, post } from "../api";
import { AlertsPanel } from "../components/AlertsPanel";
import { Panel, num, percent } from "../components/Common";
import { DecisionLog } from "../components/DecisionLog";
import { Gapper } from "../components/Gapper";
import { OwnCar } from "../components/OwnCar";
import { RecCard } from "../components/RecCard";
import { RivalCards } from "../components/RivalCards";
import { TimingTower } from "../components/TimingTower";
import { TrackMap } from "../components/TrackMap";
import { WhatIf } from "../components/WhatIf";
import type { Live } from "../useLive";
import type { CircuitInfo, DecisionEntry, PreRaceData, State } from "../types";

const injections: [string, string][] = [
  ["SC", "Safety Car"], ["VSC", "VSC"], ["RED", "Bendera merah"], ["RAIN", "Hujan"], ["DAMAGE", "Sayap kita rusak"],
  ["DROP_TIMING", "Putus timing"], ["DROP_TELEMETRY", "Putus telemetri"], ["MODEL_FAIL", "Model gagal"],
];

interface Props {
  live: Live;
  state: State;
  circuit: CircuitInfo | undefined;
  role: string;
  theme: string;
  prerace: PreRaceData | null;
}

export function Race({ live, state, circuit, role, theme, prerace }: Props) {
  const own = state.session.own;
  const [selected, setSelected] = useState(own[0]);
  const [tab, setTab] = useState<"gapper" | "whatif" | "log" | "notes">("gapper");
  const [reference, setReference] = useState("leader");
  const [drawer, setDrawer] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const car = own.includes(selected) ? selected : own[0];
  const canDecide = allowed(role, "decide");
  const recs = state.recs ?? {};
  const rec = recs[car];
  const threats = rec?.threats.slice(0, 3).map((t) => t.code) ?? [];
  const pitCost = (circuit?.pit_lane_loss ?? 20) + 2.45;

  const act = useCallback(async (body: Record<string, unknown>, done: string) => {
    try {
      const entry = await post<DecisionEntry>("/api/decision", body);
      setLastAction(`${done}. Tercatat ${entry.wall}, teruskan lewat radio.`);
      setProblem(null);
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  }, []);

  const box = useCallback((code: string, compound: string) => act({ car: code, action: "BOX", compound }, `Box ${code} dengan ${compound}`), [act]);
  const stay = useCallback((code: string) => act({ car: code, action: "STAY" }, `${code} tetap di lintasan`), [act]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).matches("input, textarea, select")) return;
      const key = event.key.toLowerCase();
      if (key === "1" || key === "2") setSelected(own[Number(key) - 1]);
      if (key === "w") setTab("whatif");
      if (key === "g") setTab("gapper");
      if (key === "l") setTab("log");
      if (!canDecide) return;
      if (key === "b" && rec && !state.pending_box[car]) {
        const compound = rec.compound ?? rec.options.find((o) => o.action === "BOX")?.compound;
        if (compound) box(car, compound);
      }
      if (key === "s" && rec) stay(car);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [own, car, rec, canDecide, box, stay, state.pending_box]);

  const rows = state.rows ?? [];
  const activePlan = state.plans_live[car] ?? [];
  const planName = state.active_plan[car] ?? "A";
  const triggers = prerace?.plans[car]?.flatMap((plan) => plan.name === planName ? [] : plan.triggers) ?? [];

  return (
    <main className="race">
      <div className="rail">
        <div className="plan-line">
          <strong>Plan {planName} {car}</strong>
          <span>{activePlan.length ? activePlan.map((s) => `lap ${s.lap} ${s.compound}`).join(", ") : "tidak ada stop lagi"}</span>
          {triggers.slice(0, 1).map((t) => <span key={t.text} className="trigger">Pemicu: {t.text}</span>)}
        </div>
        <button onClick={() => setDrawer(!drawer)} aria-expanded={drawer}>Kontrol latihan</button>
      </div>
      {drawer && (
        <div className="drawer">
          <label>Kecepatan
            <select value={state.speed} onChange={(event) => post("/api/race/control", { speed: Number(event.target.value) })}>
              {[1, 5, 10, 20, 40, 60].map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
            </select>
          </label>
          <button onClick={() => post("/api/race/control", { running: !state.running })}>{state.running ? "Jeda" : "Lanjut"}</button>
          <label className="check">
            <input type="checkbox" checked={state.autopilot} onChange={(event) => post("/api/race/control", { autopilot: event.target.checked })} />
            Ikuti rekomendasi otomatis
          </label>
          {injections.map(([kind, label]) => (
            <button key={kind} disabled={!allowed(role, "control")} onClick={() => post("/api/race/inject", { kind })}>{label}</button>
          ))}
        </div>
      )}
      {problem && <p className="error banner">{problem}</p>}
      <div className="race-grid">
        <TimingTower rows={rows} source={state.sources.timing} selected={car} threats={threats} onSelect={setSelected} />
        <div className="evidence">
          <TrackMap circuit={circuit} rows={rows} source={state.sources.timing} selected={car} exit={rec?.exit} threats={threats} theme={theme} />
        <Panel title={{ gapper: "Gapper plot", whatif: "What-if", log: "Log keputusan", notes: "Catatan" }[tab]} className="center"
          aside={
            <div className="tabs" role="tablist">
              {([["gapper", "Gapper", "G"], ["whatif", "What-if", "W"], ["log", "Log", "L"], ["notes", "Catatan", ""]] as const).map(([id, label, key]) => (
                <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{key && <kbd>{key}</kbd>} {label}</button>
              ))}
              {tab === "gapper" && (
                <select aria-label="Referensi gapper" value={reference} onChange={(event) => setReference(event.target.value)}>
                  <option value="leader">Terhadap pemimpin</option>
                  {own.map((code) => <option key={code} value={code}>Terhadap {code}</option>)}
                </select>
              )}
            </div>
          }>
          {tab === "gapper" && <Gapper laps={live.laps} own={own} threats={threats} reference={reference} totalLaps={state.session.total_laps} pitCost={pitCost} />}
          {tab === "whatif" && <WhatIf car={car} lap={state.lap ?? 0} totalLaps={state.session.total_laps} plan={activePlan} />}
          {tab === "log" && <DecisionLog entries={state.decisions ?? []} />}
          {tab === "notes" && <Notes car={car} role={role} state={state} />}
        </Panel>
        </div>
        <div className="command">
        <RecCard own={own} selected={car} recs={recs} views={state.own ?? {}} status={state.status ?? "GREEN"} error={state.rec_error}
          canDecide={canDecide} onSelect={setSelected} onBox={box} onStay={stay} lastAction={lastAction} pending={state.pending_box} computingFor={state.compute?.running_s ?? null} />
        <AlertsPanel alerts={state.alerts ?? []} rec={rec} view={state.own?.[car]} canDecide={canDecide}
          onPlan={(code, action) => act({ car: code, action }, `${code} pindah plan`)} />
        </div>
        <div className="bottom">
        <OwnCar code={car} view={state.own?.[car]} source={state.sources.telemetry} canDecide={canDecide}
          onEnergy={(mode) => act({ car, action: mode }, `Energi ${car}: ${mode.toLowerCase()}`)} />
        <RivalCards rivals={state.rivals ?? []} source={state.sources.timing} canTag={allowed(role, "tag")}
          onTag={(code, tag) => post("/api/tag", { code, tag })} />
        </div>
      </div>
      <p className="sr-summary">
        {rec ? `${rec.car}: ${rec.action}, keyakinan ${percent(rec.confidence)}. Ekspektasi ${num(rec.options[0]?.e_pos, 1)}.` : ""}
      </p>
    </main>
  );
}

function Notes({ car, role, state }: { car: string; role: string; state: State }) {
  const [text, setText] = useState("");
  const can = allowed(role, "note");
  return (
    <div className="notes">
      <form onSubmit={(event) => {
        event.preventDefault();
        if (text.trim()) post("/api/note", { car, text: text.trim() });
        setText("");
      }}>
        <input value={text} onChange={(event) => setText(event.target.value)} disabled={!can}
          placeholder={can ? `Catatan untuk ${car}` : "Peran ini hanya bisa melihat catatan"} aria-label="Catatan" />
        <button disabled={!can || !text.trim()}>Kirim catatan</button>
      </form>
      <ul>
        {(state.notes ?? []).map((note, i) => <li key={i}><b>{note.car}</b> {note.text} <span>{note.role}, {note.wall}</span></li>)}
      </ul>
    </div>
  );
}
