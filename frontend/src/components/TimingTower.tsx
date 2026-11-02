import { Compound, Panel, lapTime, num, percent } from "./Common";
import type { Row, Source } from "../types";

interface Props {
  rows: Row[];
  source: Source;
  selected: string;
  threats: string[];
  onSelect: (code: string) => void;
}

export function TimingTower({ rows, source, selected, threats, onSelect }: Props) {
  return (
    <Panel title="Timing tower" source={source} className="tower">
      <table className="timing">
        <thead>
          <tr>
            <th className="p">P</th>
            <th>Mobil</th>
            <th className="n">Gap</th>
            <th className="n">Int</th>
            <th>Ban</th>
            <th className="n" title="Estimasi degradasi, detik per lap">Deg</th>
            <th className="n" title="Estimasi peluang pit lap ini atau lap depan">Pit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.code}
              className={[row.own ? "own" : "", row.code === selected ? "selected" : "",
                threats.includes(row.code) ? "threat" : "", row.retired ? "out" : ""].join(" ")}
              onClick={() => row.own && onSelect(row.code)}
              title={`${row.team}. Lap terakhir ${lapTime(row.last_lap)}`}
            >
              <td className="p">{row.retired ? "×" : row.pos}</td>
              <td className="driver">
                <i style={{ background: row.color }} aria-hidden />
                {row.code}
              </td>
              <td className="n">{row.retired ? "keluar" : row.pos === 1 ? "pemimpin" : num(row.gap, 1)}</td>
              <td className="n">{row.pos === 1 || row.retired ? "" : num(row.interval, 1)}</td>
              <td className="tyre-cell">
                {row.in_pit ? <span className="pit-flag">PIT</span> : <Compound code={row.compound} size="sm" />}
                <span className="age">{row.age}</span>
              </td>
              <td className="n est">{row.retired ? "" : num(row.deg, 2)}</td>
              <td className="n est">{row.retired || row.own ? "" : percent(row.p_pit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
