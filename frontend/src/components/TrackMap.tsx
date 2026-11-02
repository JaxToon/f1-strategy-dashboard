import { useEffect, useMemo, useRef } from "react";
import { Panel } from "./Common";
import type { CircuitInfo, ExitView, Row, Source } from "../types";

interface Point { x: number; y: number }

function spline(points: [number, number][], perSegment = 24): Point[] {
  const out: Point[] = [];
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const [p0, p1, p2, p3] = [points[(i - 1 + n) % n], points[i], points[(i + 1) % n], points[(i + 2) % n]];
    for (let t = 0; t < perSegment; t++) {
      const s = t / perSegment;
      const s2 = s * s;
      const s3 = s2 * s;
      const axis = (k: 0 | 1) =>
        0.5 * (2 * p1[k] + (p2[k] - p0[k]) * s + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * s2
          + (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * s3);
      out.push({ x: axis(0), y: axis(1) });
    }
  }
  return out;
}

function arcTable(path: Point[]) {
  const lengths = [0];
  for (let i = 1; i <= path.length; i++) {
    const a = path[i - 1];
    const b = path[i % path.length];
    lengths.push(lengths[i - 1] + Math.hypot(b.x - a.x, b.y - a.y));
  }
  return lengths;
}

function at(path: Point[], lengths: number[], u: number): Point {
  const target = ((u % 1) + 1) % 1 * lengths[lengths.length - 1];
  let low = 0;
  let high = lengths.length - 1;
  while (high - low > 1) {
    const mid = (low + high) >> 1;
    if (lengths[mid] <= target) low = mid;
    else high = mid;
  }
  const span = lengths[high] - lengths[low] || 1;
  const t = (target - lengths[low]) / span;
  const a = path[low % path.length];
  const b = path[high % path.length];
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

interface Props {
  circuit: CircuitInfo | undefined;
  rows: Row[];
  source: Source;
  selected: string;
  exit: ExitView | undefined;
  threats: string[];
  theme: string;
}

export function TrackMap({ circuit, rows, source, selected, exit, threats, theme }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef({ rows, selected, exit, threats });
  latest.current = { rows, selected, exit, threats };
  const shown = useRef<Record<string, number>>({});

  const geometry = useMemo(() => {
    if (!circuit) return null;
    const path = spline(circuit.outline);
    const xs = path.map((p) => p.x);
    const ys = path.map((p) => p.y);
    return { path, lengths: arcTable(path), minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }, [circuit]);

  useEffect(() => {
    const element = canvas.current;
    if (!element || !geometry) return;
    const context = element.getContext("2d")!;
    let frame = 0;
    let lastDraw = 0;
    let palette: Record<string, string> | null = null;

    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      // Twenty frames a second reads as smooth here and leaves the CPU to the simulator.
      if (now - lastDraw < 50) return;
      lastDraw = now;
      const box = element.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (element.width !== Math.round(box.width * dpr) || element.height !== Math.round(box.height * dpr)) {
        element.width = Math.round(box.width * dpr);
        element.height = Math.round(box.height * dpr);
      }
      if (!palette) {
        const css = getComputedStyle(element);
        palette = Object.fromEntries(["--track", "--ink", "--red", "--rival", "--panel", "--amber"]
          .map((name) => [name, css.getPropertyValue(name).trim()]));
      }
      const colors = palette;
      const color = (name: string) => colors[name];
      const { path, lengths, minX, maxX, minY, maxY } = geometry;
      const pad = 22;
      const scale = Math.min((box.width - pad * 2) / (maxX - minX), (box.height - pad * 2) / (maxY - minY));
      const offsetX = (box.width - (maxX - minX) * scale) / 2 - minX * scale;
      const offsetY = (box.height - (maxY - minY) * scale) / 2 - minY * scale;
      const map = (p: Point) => ({ x: p.x * scale + offsetX, y: p.y * scale + offsetY });

      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, box.width, box.height);
      context.lineJoin = "round";
      context.beginPath();
      path.forEach((p, i) => {
        const m = map(p);
        if (i) context.lineTo(m.x, m.y);
        else context.moveTo(m.x, m.y);
      });
      context.closePath();
      context.strokeStyle = color("--track");
      context.lineWidth = 7;
      context.stroke();

      const line = map(at(path, lengths, 0));
      context.fillStyle = color("--ink");
      context.fillRect(line.x - 5, line.y - 1.5, 10, 3);

      const { rows, selected, exit, threats } = latest.current;
      const lapSeconds = 90;
      const me = rows.find((r) => r.code === selected);
      if (me && exit && !me.in_pit) {
        const m = map(at(path, lengths, me.u - exit.cost / lapSeconds));
        context.beginPath();
        context.arc(m.x, m.y, 10, 0, Math.PI * 2);
        context.setLineDash([3, 3]);
        context.strokeStyle = color(exit.traffic ? "--red" : "--ink");
        context.lineWidth = 2;
        context.stroke();
        context.setLineDash([]);
        context.fillStyle = color("--ink");
        context.font = "600 12px 'Archivo Variable', sans-serif";
        context.fillText(`Keluar P${exit.position}`, m.x + 14, m.y + 4);
      }

      for (const row of [...rows].reverse()) {
        if (row.retired || row.done) continue;
        const previous = shown.current[row.code] ?? row.u;
        let delta = row.u - previous;
        if (delta < -0.5) delta += 1;
        if (delta > 0.5) delta -= 1;
        const eased = (previous + delta * 0.45 + 1) % 1;
        shown.current[row.code] = eased;
        const m = map(at(path, lengths, eased));
        const threat = threats.includes(row.code);
        context.beginPath();
        context.arc(m.x, m.y, row.own ? 7 : threat ? 5.5 : 4, 0, Math.PI * 2);
        context.fillStyle = row.own ? color("--ink") : color("--rival");
        context.fill();
        context.lineWidth = 2;
        context.strokeStyle = color("--panel");
        context.stroke();
        if (threat) {
          context.beginPath();
          context.arc(m.x, m.y, 9, 0, Math.PI * 2);
          context.setLineDash([2, 3]);
          context.strokeStyle = color("--amber");
          context.stroke();
          context.setLineDash([]);
        }
        if (row.own || threat) {
          context.fillStyle = color("--ink");
          context.font = `${row.own ? 700 : 500} 12px 'Archivo Variable', sans-serif`;
          context.fillText(row.code, m.x + 11, m.y - 7);
        }
      }
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [geometry, theme]);

  return (
    <Panel title="Peta lintasan" source={source} className="map"
      aside={<span className="hint">Skematik. Lingkaran putus-putus: titik keluar pit {selected}</span>}>
      <canvas ref={canvas} className="map-canvas" role="img"
        aria-label={`Peta ${circuit?.name ?? ""} dengan posisi semua mobil`} />
    </Panel>
  );
}
