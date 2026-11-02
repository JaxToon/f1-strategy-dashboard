import { useEffect, useMemo, useRef, useState } from "react";
import { num, signed } from "./Common";
import type { LapRow } from "../types";

interface Props {
  laps: Record<string, LapRow[]>;
  own: string[];
  threats: string[];
  reference: string;
  totalLaps: number;
  pitCost: number;
  upToLap?: number;
}

const M = { l: 34, r: 44, t: 8, b: 20 };

export function Gapper({ laps, own, threats, reference, totalLaps, pitCost, upToLap }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [{ W, H }, setSize] = useState({ W: 900, H: 300 });

  useEffect(() => {
    const element = svg.current!;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ W: Math.max(entry.contentRect.width, 200), H: Math.max(entry.contentRect.height, 120) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const series = useMemo(() => {
    const leaderByLap = new Map<number, number>();
    for (const rows of Object.values(laps)) {
      for (const row of rows) {
        const best = leaderByLap.get(row.lap);
        if (best === undefined || row.elapsed < best) leaderByLap.set(row.lap, row.elapsed);
      }
    }
    const refByLap = new Map<number, number>();
    if (reference === "leader") leaderByLap.forEach((v, k) => refByLap.set(k, v));
    else for (const row of laps[reference] ?? []) refByLap.set(row.lap, row.elapsed);
    const out: Record<string, { lap: number; gap: number; pit: boolean }[]> = {};
    for (const [code, rows] of Object.entries(laps)) {
      out[code] = rows
        .filter((row) => refByLap.has(row.lap) && (upToLap === undefined || row.lap <= upToLap))
        .map((row) => ({ lap: row.lap, gap: row.elapsed - (refByLap.get(row.lap) ?? 0), pit: row.in_lap }));
    }
    return out;
  }, [laps, reference, upToLap]);

  const mine = series[own[0]] ?? [];
  const center = mine.length ? mine[mine.length - 1].gap : 0;
  const yMin = reference === "leader" ? Math.min(-2, center - 34) : -34;
  const yMax = reference === "leader" ? center + 34 : 34;
  const x = (lap: number) => M.l + (lap / totalLaps) * (W - M.l - M.r);
  const y = (gap: number) => M.t + ((Math.max(Math.min(gap, yMax), yMin) - yMin) / (yMax - yMin)) * (H - M.t - M.b);
  const line = (rows: { lap: number; gap: number }[]) =>
    rows.map((r, i) => `${i ? "L" : "M"}${x(r.lap).toFixed(1)} ${y(r.gap).toFixed(1)}`).join("");

  const ticks: number[] = [];
  const step = 10;
  for (let v = Math.ceil(yMin / step) * step; v <= yMax; v += step) ticks.push(v);
  const lapTicks: number[] = [];
  for (let lap = 10; lap <= totalLaps; lap += 10) lapTicks.push(lap);

  const focus = [...own, ...threats.filter((c) => !own.includes(c))];
  const others = Object.keys(series).filter((code) => !focus.includes(code));

  // Direct labels sit at the end of each line, pushed apart when cars run together.
  const labels = focus
    .filter((code) => series[code]?.length)
    .map((code) => {
      const last = series[code][series[code].length - 1];
      return { code, x: x(last.lap) + 8, y: y(last.gap) + 4 };
    })
    .sort((a, b) => a.y - b.y);
  labels.forEach((label, i) => {
    if (i && label.y - labels[i - 1].y < 13) label.y = labels[i - 1].y + 13;
  });

  const onMove = (event: React.MouseEvent) => {
    const box = svg.current!.getBoundingClientRect();
    const lap = Math.round((((event.clientX - box.left) / box.width) * W - M.l) / ((W - M.l - M.r) / totalLaps));
    setHover(lap >= 1 && lap <= totalLaps ? lap : null);
  };

  const hoverRows = hover === null ? [] : focus
    .map((code) => ({ code, row: series[code]?.find((r) => r.lap === hover) }))
    .filter((item) => item.row);

  return (
    <div className="gapper">
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove}
        onMouseLeave={() => setHover(null)} role="img"
        aria-label="Gapper plot: selisih waktu tiap mobil terhadap referensi per lap">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className={v === 0 ? "axis zero" : "axis"} />
            <text x={M.l - 8} y={y(v) + 4} textAnchor="end" className="tick">{v}</text>
          </g>
        ))}
        {lapTicks.map((lap) => (
          <text key={lap} x={x(lap)} y={H - 6} textAnchor="middle" className="tick">{lap}</text>
        ))}
        {mine.length > 0 && (
          <>
            <path className="zone"
              d={`${line(mine.map((r) => ({ lap: r.lap, gap: r.gap - pitCost })))}L${[...mine].reverse().map((r) => `${x(r.lap).toFixed(1)} ${y(r.gap).toFixed(1)}`).join("L")}Z`} />
            <path className="zone behind"
              d={`${line(mine)}L${[...mine].reverse().map((r) => `${x(r.lap).toFixed(1)} ${y(r.gap + pitCost).toFixed(1)}`).join("L")}Z`} />
          </>
        )}
        {others.map((code) => <path key={code} d={line(series[code])} className="trace rival" />)}
        {threats.filter((c) => series[c]).map((code) => <path key={code} d={line(series[code])} className="trace threat" />)}
        {own.filter((c) => series[c]).map((code, i) => (
          <g key={code}>
            <path d={line(series[code])} className={`trace own own-${i}`} />
            {series[code].filter((r) => r.pit).map((r) => (
              <circle key={r.lap} cx={x(r.lap)} cy={y(r.gap)} r={4} className={`pit-dot own-${i}`} />
            ))}
          </g>
        ))}
        {labels.map((label) => <text key={label.code} x={label.x} y={label.y} className="end-label">{label.code}</text>)}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} className="cross" />}
      </svg>
      {hover !== null && hoverRows.length > 0 && (
        <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <strong>Lap {hover}</strong>
          {hoverRows.map(({ code, row }) => (
            <span key={code}>{code} {signed(row!.gap, 1)} dtk</span>
          ))}
        </div>
      )}
      <div className="legend">
        {own.map((code, i) => <span key={code}><i className={`swatch own-${i}`} />{code}</span>)}
        <span><i className="swatch threat" />Ancaman</span>
        <span><i className="swatch rival" />Lawan lain</span>
        <span><i className="swatch zone" />Zona undercut dan overcut ({num(pitCost, 0)} dtk)</span>
      </div>
    </div>
  );
}
