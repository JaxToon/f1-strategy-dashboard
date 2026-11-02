import type { ReactNode } from "react";
import type { Source } from "../types";

export const num = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "–"
    : value.toLocaleString("id-ID", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const signed = (value: number, digits = 1) => `${value > 0 ? "+" : ""}${num(value, digits)}`;

export const lapTime = (seconds: number | null) => {
  if (seconds === null) return "–";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, "0").replace(".", ",")}`;
};

export const percent = (value: number) => `${Math.round(value * 100)}%`;

export function Compound({ code, size = "md" }: { code: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`tyre tyre-${code} tyre-${size}`} role="img" aria-label={`Kompon ${code}`}>
      {code}
    </span>
  );
}

const labels: Record<string, string> = { tinggi: "Tinggi", sedang: "Sedang", rendah: "Rendah" };

export function Confidence({ level }: { level: string }) {
  const filled = { rendah: 1, sedang: 2, tinggi: 3 }[level] ?? 0;
  return (
    <span className="confidence" title={`Keyakinan ${level}`}>
      <span className="pips" aria-hidden>
        {[1, 2, 3].map((i) => (
          <i key={i} className={i <= filled ? "on" : ""} />
        ))}
      </span>
      {labels[level] ?? level}
    </span>
  );
}

interface PanelProps {
  title: string;
  source?: Source;
  aside?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Panel({ title, source, aside, className = "", children }: PanelProps) {
  const stale = source?.stale ?? false;
  return (
    <section className={`panel ${className} ${stale ? "is-stale" : ""}`} aria-label={title}>
      <header className="panel-head">
        <h2>{title}</h2>
        {aside}
        {source && (
          <span className={`freshness ${stale ? "late" : ""}`}>
            {stale ? `Data basi ${num(source.age_s, 0)} dtk` : `${num(source.age_s, 1)} dtk`}
          </span>
        )}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
