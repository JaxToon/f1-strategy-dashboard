import { Compound, num, percent, signed } from "./Common";
import type { OwnView, Rec } from "../types";

const words: Record<string, string> = { BOX: "BOX", STAY: "STAY", BOX_NEXT: "BOX" };

interface Props {
  own: string[];
  selected: string;
  recs: Record<string, Rec>;
  views: Record<string, OwnView>;
  status: string;
  error: string | null | undefined;
  canDecide: boolean;
  onSelect: (code: string) => void;
  onBox: (code: string, compound: string) => void;
  onStay: (code: string) => void;
  lastAction: string | null;
  pending: Record<string, { compound: string; lap: number }>;
  computingFor: number | null;
}

export function RecCard({ own, selected, recs, views, status, error, canDecide, onSelect, onBox, onStay, lastAction, pending, computingFor }: Props) {
  const rec = recs[selected];
  const called = pending[selected];
  const inLane = views[selected]?.row.in_pit;
  const deadline = views[selected]?.deadline;
  const neutral = status === "SC" || status === "VSC";
  const urgent = rec && !called && !inLane && rec.action === "BOX" && (neutral || rec.confidence >= 0.65);
  const stack = own.every((code) => recs[code]?.action === "BOX");

  return (
    <section className={`board ${urgent ? "urgent" : ""}`} aria-label="Kartu rekomendasi" aria-live="polite">
      <div className="car-switch" role="tablist" aria-label="Pilih mobil">
        {own.map((code, i) => (
          <button key={code} role="tab" aria-selected={code === selected} onClick={() => onSelect(code)}>
            <kbd>{i + 1}</kbd> {code}
            <span>P{views[code]?.row.pos ?? "–"}</span>
            {recs[code] && <em>{recs[code].action === "STAY" ? "stay" : "box"}</em>}
          </button>
        ))}
      </div>

      {called || inLane ? (
        <div className="called">
          <div className="call">
            <span className="word">{inLane ? "PIT" : "BOX"}</span>
            {called && <Compound code={called.compound} size="lg" />}
          </div>
          <p>{inLane ? "Mobil di pit lane. Rekomendasi kembali setelah keluar." : `Dipanggil untuk lap ${called.lap}. Pastikan terkirim lewat radio.`}</p>
          {!inLane && <button disabled={!canDecide} onClick={() => onStay(selected)}><kbd>S</kbd> Batalkan panggilan</button>}
          {lastAction && <p className="logged">{lastAction}</p>}
        </div>
      ) : !rec ? (
        <div className="board-empty">
          <strong>{error ? "Rekomendasi tidak tersedia" : "Menghitung rekomendasi"}</strong>
          <p>{error ? `${error}. Data mentah tetap tampil, putuskan dari timing dan telemetri.` : "Hasil pertama muncul setelah simulasi selesai."}</p>
        </div>
      ) : (
        <>
          <div className="call">
            <span className="word">{words[rec.action]}</span>
            <div className="call-side">
              {rec.compound && <Compound code={rec.compound} size="lg" />}
              {rec.action !== "STAY" && <span>{rec.action === "BOX_NEXT" ? `lap depan, lap ${rec.box_lap + 1}` : `lap ${rec.box_lap}`}</span>}
            </div>
          </div>

          <p className="runner-up">Opsi kedua: {rec.alternative}</p>
          {(rec.age_laps >= 2 || (computingFor ?? 0) > 3) && (
            <p className="late-rec">
              {(computingFor ?? 0) > 3 ? `Hitung ulang lambat, ${num(computingFor, 0)} dtk. ` : ""}
              Kartu ini dari lap {rec.lap}, cek timing sebelum memutuskan.
            </p>
          )}

          {neutral && rec.action !== "STAY" && deadline && (
            <p className="deadline">
              {deadline.missed
                ? "Pintu pit sudah terlewat, box lap berikutnya"
                : `Panggil dalam ${num(deadline.seconds, 0)} dtk, pintu pit ${num(deadline.to_entry, 0)} dtk lagi`}
            </p>
          )}

          <dl className="figures">
            <div><dt>Keyakinan</dt><dd>{percent(rec.confidence)}</dd></div>
            <div><dt>Waktu</dt><dd>{signed(rec.gain_s)} dtk</dd></div>
            <div><dt>Posisi</dt><dd>{signed(rec.gain_pos)}</dd></div>
            <div>
              <dt>Bila box</dt>
              <dd>P{rec.exit.position}{rec.exit.range[1] !== rec.exit.range[0] && <small> ({rec.exit.range[0]}-{rec.exit.range[1]})</small>}</dd>
            </div>
          </dl>

          <ol className="reasons">
            {rec.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ol>
          <p className="invalidate">{rec.invalidate}</p>

          {stack && <p className="stack">Kedua mobil disarankan box. Jarakkan satu lap atau terima antre sekitar 4 dtk.</p>}

          <div className="decide">
            {rec.options.filter((o) => o.action === "BOX").map((option, i) => (
              <button key={option.key} disabled={!canDecide} onClick={() => onBox(selected, option.compound!)}
                className={rec.compound === option.compound && rec.action !== "STAY" ? "primary" : ""}>
                {i === 0 && <kbd>B</kbd>} Box <Compound code={option.compound!} size="sm" />
              </button>
            ))}
            <button disabled={!canDecide} onClick={() => onStay(selected)}><kbd>S</kbd> Tetap</button>
          </div>
          {lastAction && <p className="logged">{lastAction}</p>}
          <p className="provenance">
            {rec.n_sims.toLocaleString("id-ID")} race, {rec.compute_ms} ms, dihitung lap {rec.lap}
          </p>
        </>
      )}
    </section>
  );
}
