import { useEffect, useRef, useState } from "react";
import type { LapRow, State } from "./types";

export interface Live {
  state: State | null;
  laps: Record<string, LapRow[]>;
  connected: boolean;
  latencyP95: number | null;
}

function group(rows: LapRow[], into: Record<string, LapRow[]> = {}) {
  for (const row of rows) (into[row.code] ??= []).push(row);
  return into;
}

export function useLive(): Live {
  const [state, setState] = useState<State | null>(null);
  const [laps, setLaps] = useState<Record<string, LapRow[]>>({});
  const [connected, setConnected] = useState(false);
  const [latencyP95, setLatency] = useState<number | null>(null);
  const sessionId = useRef<string | null>(null);
  const samples = useRef<number[]>([]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let retry = 500;
    let timer: number;

    const open = () => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/ws`);
      socket.onopen = () => {
        setConnected(true);
        retry = 500;
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) {
          timer = window.setTimeout(open, retry);
          retry = Math.min(retry * 2, 4000);
        }
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        const next: State = message.state;
        const changed = next.session.id !== sessionId.current;
        sessionId.current = next.session.id;
        if (message.type === "hello") {
          setLaps(group(message.history));
        } else {
          if (changed) setLaps({});
          if (message.laps?.length) {
            setLaps((previous) => {
              const copy = { ...previous };
              for (const row of message.laps as LapRow[]) copy[row.code] = [...(copy[row.code] ?? []), row];
              return copy;
            });
          }
          const ms = (Date.now() / 1000 - next.sent_at) * 1000;
          samples.current.push(ms);
          if (samples.current.length > 200) samples.current.shift();
          if (samples.current.length % 10 === 0) {
            const sorted = [...samples.current].sort((a, b) => a - b);
            setLatency(sorted[Math.floor(sorted.length * 0.95)]);
          }
        }
        setState(next);
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { state, laps, connected, latencyP95 };
}
