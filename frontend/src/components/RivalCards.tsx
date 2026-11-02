import { useState } from "react";
import { Compound, Confidence, Empty, Panel, num, percent } from "./Common";
import type { RivalCard, Source } from "../types";

interface Props {
  rivals: RivalCard[];
  source: Source;
  canTag: boolean;
  onTag: (code: string, tag: string) => void;
}

export function RivalCards({ rivals, source, canTag, onTag }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Kartu lawan" source={source} className="rivals" aside={<span className="hint">Semua nilai estimasi dari timing dan GPS resmi</span>}>
      {rivals.length === 0 ? <Empty>Kartu muncul setelah lap pertama.</Empty> : (
        <div className="rival-row">
          {rivals.map((rival) => (
            <article key={rival.code} className="rival">
              <header>
                <strong>P{rival.pos} {rival.code}</strong>
                <Compound code={rival.compound} size="sm" />
                <span>{rival.age} lap</span>
              </header>
              <dl>
                <dt>Deg</dt>
                <dd className="est">{rival.tyre ? `${num(rival.tyre.deg_low, 2)} sampai ${num(rival.tyre.deg_high, 2)}` : "–"}</dd>
                <dt>Energi</dt>
                <dd className="est">{num(rival.energy_low, 1)} sampai {num(rival.energy_high, 1)} MJ</dd>
                <dt>Pit</dt>
                <dd className="est">{percent(rival.p_pit)}</dd>
              </dl>
              <Confidence level={rival.tyre_confidence} />
              {rival.history_note && <p className="note">{rival.history_note}</p>}
              {rival.tags.map((tag, i) => (
                <p key={i} className="note">{tag.tag}: {tag.evidence}{tag.loss_s !== null ? ` (${num(tag.loss_s, 2)} dtk)` : ""}</p>
              ))}
              {canTag && (open === rival.code ? (
                <form onSubmit={(event) => {
                  event.preventDefault();
                  const input = event.currentTarget.elements.namedItem("tag") as HTMLInputElement;
                  if (input.value.trim()) onTag(rival.code, input.value.trim());
                  setOpen(null);
                }}>
                  <input name="tag" autoFocus placeholder="Sayap depan rusak" aria-label={`Tag untuk ${rival.code}`} />
                </form>
              ) : <button className="link" onClick={() => setOpen(rival.code)}>Tandai kerusakan</button>)}
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
