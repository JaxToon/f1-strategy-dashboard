import { useEffect, useState } from "react";
import { get } from "../api";
import { Empty, Panel, num, percent } from "../components/Common";
import { DecisionLog } from "../components/DecisionLog";
import { Gapper } from "../components/Gapper";
import type { Live } from "../useLive";
import type { Review, State } from "../types";

export function ReviewView({ live, state }: { live: Live; state: State }) {
  const [review, setReview] = useState<Review | null>(null);
  const [lap, setLap] = useState(state.session.total_laps);

  useEffect(() => {
    get<Review>("/api/review").then(setReview);
  }, [state.phase, state.session.id, state.decisions?.length]);

  useEffect(() => setLap(state.lap ?? state.session.total_laps), [state.phase, state.lap]);

  if (state.phase === "prerace") {
    return <main className="review"><section className="start-card"><h2>Belum ada race untuk ditinjau</h2><p>Replay dan penilaian keputusan muncul setelah race berjalan.</p></section></main>;
  }

  const score = review?.scorecard;
  const rows: [string, string, string, boolean | null][] = score ? [
    ["Posisi keluar pit, kondisi hijau, dalam 1 posisi", score.exit_within_1_green === null ? "–" : percent(score.exit_within_1_green), "≥ 90%", score.exit_within_1_green === null ? null : score.exit_within_1_green >= 0.9],
    ["Posisi keluar pit, SC/VSC, dalam rentang tampil", score.exit_neutral_in_range === null ? "–" : percent(score.exit_neutral_in_range), "≥ 80%", score.exit_neutral_in_range === null ? null : score.exit_neutral_in_range >= 0.8],
    ["Error degradasi mobil sendiri, setelah 5 lap", score.deg_rate_mae_own === null ? "–" : `${num(score.deg_rate_mae_own, 3)} dtk/lap`, "< 0,15", score.deg_rate_mae_own === null ? null : score.deg_rate_mae_own < 0.15],
    ["Presisi prediksi pit lawan, 2 lap", score.rival_precision === null ? "–" : percent(score.rival_precision), "≥ 70%", score.rival_precision === null ? null : score.rival_precision >= 0.7],
    ["Recall prediksi pit lawan", score.rival_recall === null ? "–" : percent(score.rival_recall), "≥ 40%", score.rival_recall === null ? null : score.rival_recall >= 0.4],
    ["Hitung ulang p95", score.recompute_p95_ms === null ? "–" : `${score.recompute_p95_ms} ms`, "< 3.000 ms", score.recompute_p95_ms === null ? null : score.recompute_p95_ms < 3000],
    ["Latensi layar p95", live.latencyP95 === null ? "–" : `${Math.round(live.latencyP95)} ms`, "< 500 ms", live.latencyP95 === null ? null : live.latencyP95 < 500],
  ] : [];

  return (
    <main className="review">
      <div className="review-grid">
        <Panel title="Klasifikasi" className="class">
          <table className="plain">
            <thead><tr><th>P</th><th>Mobil</th><th>Grid</th><th>Stop</th><th>Gap</th></tr></thead>
            <tbody>
              {review?.classification.map((row) => (
                <tr key={row.code} className={row.own ? "own" : ""}>
                  <td>{row.retired ? "×" : row.pos}</td>
                  <td>{row.code}</td>
                  <td>{row.grid}</td>
                  <td>{row.stops}</td>
                  <td>{row.retired ? "keluar" : row.pos === 1 ? "" : num(row.gap, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Replay gapper" className="replay"
          aside={<label className="slider">Sampai lap {lap}
            <input type="range" min={1} max={Math.max(state.lap ?? 1, 1)} value={lap} onChange={(event) => setLap(Number(event.target.value))} />
          </label>}>
          <Gapper laps={live.laps} own={state.session.own} threats={[]} reference="leader" totalLaps={state.session.total_laps} pitCost={22} upToLap={lap} />
        </Panel>
        <Panel title="Rapor model race ini" className="score">
          {rows.length ? (
            <table className="plain">
              <thead><tr><th>Ukuran</th><th>Hasil</th><th>Target</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map(([label, value, target, pass]) => (
                  <tr key={label}>
                    <td>{label}</td><td>{value}</td><td>{target}</td>
                    <td>{pass === null ? "Belum ada data" : pass ? "Lolos" : "Belum lolos"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>Memuat rapor.</Empty>}
          <p className="hint">Diukur terhadap data simulasi. Model dan simulator berbagi struktur, jadi ini batas atas, bukan bukti akurasi di race nyata.</p>
        </Panel>
        <Panel title="Keputusan dibanding alternatif" className="decisions">
          <DecisionLog entries={review?.decisions ?? []} />
          {review?.decisions.filter((d) => d.rec_options.length).slice(-4).map((decision) => (
            <div key={decision.id} className="alt">
              <strong>Lap {decision.lap}, {decision.car}</strong>
              <ul>
                {decision.rec_options.map((option) => (
                  <li key={option.label}>{option.label}: posisi {num(option.e_pos, 1)}, {num(option.e_pts, 1)} poin</li>
                ))}
              </ul>
            </div>
          ))}
        </Panel>
      </div>
    </main>
  );
}
