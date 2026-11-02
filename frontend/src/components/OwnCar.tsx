import { Compound, Confidence, Panel, Empty, num } from "./Common";
import type { OwnView, Source } from "../types";

const wheels = ["KD", "KN", "BK", "BN"];

interface Props {
  code: string;
  view: OwnView | undefined;
  source: Source;
  canDecide: boolean;
  onEnergy: (mode: string) => void;
}

export function OwnCar({ code, view, source, canDecide, onEnergy }: Props) {
  const tele = view?.telemetry;
  if (!view || !tele) {
    return <Panel title={`Kondisi ${code}`} source={source} className="owncar"><Empty>Menunggu telemetri mobil.</Empty></Panel>;
  }
  const fuelDelta = tele.fuel_kg - tele.fuel_target_kg;
  return (
    <Panel title={`Kondisi ${code}, telemetri`} source={source} className="owncar">
      <div className="own-grid">
        <div className="group">
          <h3>Ban <Compound code={view.row.compound} size="sm" /> {view.row.age} lap</h3>
          <table className="wheels">
            <thead><tr><th /><th>Pmk</th><th>Inti</th><th>Psi</th></tr></thead>
            <tbody>
              {wheels.map((wheel, i) => (
                <tr key={wheel}>
                  <th>{wheel}</th>
                  <td>{num(tele.tyre_surface_c[i], 0)}</td>
                  <td>{num(tele.tyre_core_c[i], 0)}</td>
                  <td>{num(tele.tyre_pressure_psi[i], 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>Aus {num(tele.tyre_wear_pct, 0)}%, deg <b>{view.tyre ? num(view.tyre.deg_s_lap, 2) : "–"}</b> dtk/lap</p>
          <Confidence level={view.tyre_confidence} />
        </div>
        <div className="group energy">
          <h3>Energi</h3>
          <div className="soc" role="meter" aria-valuemin={0} aria-valuemax={4} aria-valuenow={tele.soc_mj} aria-label="State of charge">
            <span style={{ width: `${(tele.soc_mj / 4) * 100}%` }} className={tele.soc_mj < 1 ? "low" : ""} />
            <b>{num(tele.soc_mj, 1)} / 4,0 MJ</b>
          </div>
          <p>Panen {num(tele.harvested_mj, 1)} MJ dari batas {num(view.energy.recharge_limit, 1)}, deploy {num(tele.deployed_mj, 1)} MJ</p>
          <p>Mode {tele.energy_mode.toLowerCase()}, clipping {tele.clipping_events}x{tele.overtake_available ? ", Overtake siap" : ""}</p>
          <div className="energy-btns">
            {["TABUNG", "NETRAL", "BOOST"].map((mode) => (
              <button key={mode} disabled={!canDecide} onClick={() => onEnergy(mode)}>
                {mode[0] + mode.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="group">
          <h3>Bahan bakar</h3>
          <p className="big">{num(tele.fuel_kg, 1)} kg</p>
          <p>{fuelDelta >= 0 ? "+" : ""}{num(fuelDelta, 1)} kg vs target{fuelDelta < -0.5 ? ", perlu lift-and-coast" : ""}</p>
          <h3>Aero</h3>
          <p>Mode {tele.aero_mode}</p>
          <p className={tele.aero_load_delta_pct < -3 ? "warn-text" : ""}>
            Beban {num(tele.aero_load_delta_pct, 1)}%{tele.aero_load_delta_pct < -3 ? ", pertimbangkan ganti sayap" : ""}
          </p>
        </div>
        <div className="group">
          <h3>Power unit</h3>
          <dl className="mini">
            <dt>Oli</dt><dd>{num(tele.oil_c, 0)}°</dd>
            <dt>Air</dt><dd>{num(tele.water_c, 0)}°</dd>
            <dt>MGU-K</dt><dd>{num(tele.mguk_c, 0)}°</dd>
            <dt>Baterai</dt><dd>{num(tele.battery_c, 0)}°</dd>
          </dl>
          <h3>Rem</h3>
          <dl className="mini">
            <dt>Depan</dt><dd>{num(tele.brake_c[0], 0)}°</dd>
            <dt>Blkg</dt><dd>{num(tele.brake_c[2], 0)}°</dd>
            <dt>Aus</dt><dd>{num(tele.brake_wear_pct, 0)}%</dd>
          </dl>
        </div>
      </div>
    </Panel>
  );
}
