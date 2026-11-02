import { Empty, percent } from "./Common";
import type { DecisionEntry } from "../types";

const actionNames: Record<string, string> = {
  BOX: "Box", STAY: "Tetap", TABUNG: "Tabung energi", NETRAL: "Energi netral", BOOST: "Boost",
  "PLAN-A": "Plan A", "PLAN-B": "Plan B", "PLAN-C": "Plan C",
};

export function DecisionLog({ entries }: { entries: DecisionEntry[] }) {
  if (!entries.length) return <Empty>Belum ada keputusan. Tekan B atau S untuk mencatat keputusan pertama.</Empty>;
  return (
    <table className="log">
      <thead>
        <tr><th>Waktu</th><th>Lap</th><th>Mobil</th><th>Keputusan</th><th>Rekomendasi saat itu</th><th>Oleh</th></tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.id}>
            <td>{entry.wall}</td>
            <td>{entry.lap}</td>
            <td>{entry.car}</td>
            <td>{actionNames[entry.action] ?? entry.action}{entry.compound ? ` ${entry.compound}` : ""}</td>
            <td>
              {entry.rec_action ? `${entry.rec_action === "STAY" ? "Tetap" : "Box"}${entry.rec_compound ? ` ${entry.rec_compound}` : ""}, ${percent(entry.rec_confidence ?? 0)}` : "Tidak ada"}
              {entry.followed === false && <span className="tag">beda</span>}
            </td>
            <td>{entry.role}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
