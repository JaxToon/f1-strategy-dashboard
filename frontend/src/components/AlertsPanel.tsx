import { Empty, num, percent } from "./Common";
import type { Alert, OwnView, Rec } from "../types";

const modeNames: Record<string, string> = { SERANG: "Serang", BERTAHAN: "Bertahan", TABUNG: "Tabung", NETRAL: "Netral" };

interface Props {
  alerts: Alert[];
  rec: Rec | undefined;
  view: OwnView | undefined;
  canDecide: boolean;
  onPlan: (car: string, action: string) => void;
}

export function AlertsPanel({ alerts, rec, view, canDecide, onPlan }: Props) {
  const important = alerts.filter((a) => a.level !== "info").slice(0, 4);
  const energy = view?.energy;
  return (
    <section className="panel alerts" aria-label="Alert dan ancaman">
      <header className="panel-head"><h2>Alert dan ancaman</h2></header>
      <div className="panel-body">
        {important.map((alert) => (
          <div key={alert.id} className={`alert ${alert.level}`} role={alert.level === "red" ? "alert" : undefined}>
            <span className="alert-mark" aria-hidden>{alert.level === "red" ? "!" : "▲"}</span>
            <p>{alert.text}</p>
            {alert.action && alert.car && (
              <button disabled={!canDecide} onClick={() => onPlan(alert.car!, alert.action!.action)}>{alert.action.label}</button>
            )}
          </div>
        ))}
        {rec && rec.threats.length > 0 ? (
          <ul className="threats">
            {rec.threats.slice(0, 3).map((threat) => (
              <li key={threat.code}>
                <strong>{threat.code}</strong>
                <span>{threat.kind}, {num(threat.gap, 1)} dtk</span>
                <span className="est" title="Estimasi">pit {percent(threat.p_pit)}</span>
              </li>
            ))}
          </ul>
        ) : important.length === 0 && <Empty>Tidak ada ancaman undercut saat ini.</Empty>}
        {energy && (
          <div className={`energy-tip ${energy.vulnerable ? "warn" : ""}`}>
            <span>{modeNames[energy.mode]}</span>
            <strong>{energy.headline}</strong>
            <p>{energy.detail}</p>
          </div>
        )}
      </div>
    </section>
  );
}
