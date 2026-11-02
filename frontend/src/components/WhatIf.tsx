import { useEffect, useState } from "react";
import { post } from "../api";
import { Compound, num, percent, signed } from "./Common";
import type { Stop, WhatIfResult } from "../types";

interface Props {
  car: string;
  lap: number;
  totalLaps: number;
  plan: Stop[];
}

export function WhatIf({ car, lap, totalLaps, plan }: Props) {
  const [stops, setStops] = useState<Stop[]>(plan.length ? plan : [{ lap: lap + 3, compound: "H" }]);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStops(plan.length ? plan.map((s) => ({ ...s })) : [{ lap: lap + 3, compound: "H" }]);
    setResult(null);
  }, [car]);

  const update = (index: number, patch: Partial<Stop>) => {
    setStops(stops.map((stop, i) => (i === index ? { ...stop, ...patch } : stop)));
    setResult(null);
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await post<WhatIfResult>("/api/whatif", { car, stops }));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="whatif">
      <div className="stops">
        {stops.map((stop, i) => (
          <div key={i} className="stop">
            <label>Stop {i + 1}, lap
              <input type="number" min={lap + 1} max={totalLaps - 1} value={stop.lap}
                onChange={(event) => update(i, { lap: Number(event.target.value) })} />
            </label>
            <div className="tyre-pick" role="radiogroup" aria-label={`Kompon stop ${i + 1}`}>
              {["S", "M", "H"].map((code) => (
                <button key={code} role="radio" aria-checked={stop.compound === code}
                  className={stop.compound === code ? "on" : ""} onClick={() => update(i, { compound: code })}>
                  <Compound code={code} size="sm" />
                </button>
              ))}
            </div>
            <button className="link" onClick={() => { setStops(stops.filter((_, k) => k !== i)); setResult(null); }}>Hapus</button>
          </div>
        ))}
        {stops.length < 3 && (
          <button className="link" onClick={() => setStops([...stops, { lap: Math.min((stops.at(-1)?.lap ?? lap) + 12, totalLaps - 2), compound: "M" }])}>
            Tambah stop
          </button>
        )}
      </div>
      <button className="primary run" onClick={run} disabled={busy}>{busy ? "Menghitung" : "Simulasikan untuk " + car}</button>
      {error && <p className="error">{error}</p>}
      {result && (
        <dl className="figures compare">
          <div><dt>Posisi harapan</dt><dd>{num(result.whatif.e_pos, 1)} <small>sekarang {num(result.base.e_pos, 1)}</small></dd></div>
          <div><dt>Poin harapan</dt><dd>{signed(result.delta_pts, 2)}</dd></div>
          <div><dt>Waktu</dt><dd>{signed(result.delta_s)} dtk</dd></div>
          <div><dt>Keyakinan lebih baik</dt><dd>{percent(result.confidence)}</dd></div>
          <p className="provenance">{result.n_sims.toLocaleString("id-ID")} race berpasangan, {result.compute_ms} ms</p>
        </dl>
      )}
    </div>
  );
}
