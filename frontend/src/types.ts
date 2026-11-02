export interface Row {
  code: string; team: string; color: string; own: boolean; pos: number; lap: number;
  gap: number; interval: number | null; u: number; last_lap: number | null; best_lap: number | null;
  age: number; stops: number; in_pit: boolean; retired: boolean; done: boolean; new_set: boolean;
  grid: number; compound: string; deg: number | null; p_pit: number;
}

export interface ExitView {
  position: number; range: [number, number];
  ahead: { code: string; gap: number } | null;
  behind: { code: string; gap: number } | null;
  traffic: boolean; cost: number;
}

export interface Option {
  key: string; label: string; action: string; compound: string | null; e_pos: number; p10: number; p90: number;
  e_pts: number; p_points: number; utility: number; plan: Stop[];
}

export interface Threat { code: string; kind: string; gap: number; gain: number; p_pit: number; score: number }

export interface Rec {
  id: string; car: string; lap: number; box_lap: number; action: "BOX" | "STAY" | "BOX_NEXT";
  compound: string | null; plan_after: Stop[]; gain_s: number; gain_pos: number; confidence: number;
  alternative: string; reasons: string[]; sensitive: string; invalidate: string; exit: ExitView;
  options: Option[]; n_sims: number; compute_ms: number; source: string; threats: Threat[];
  model_version: string; age_laps: number;
}

export interface Stop { lap: number; compound: string }

export interface Telemetry {
  tyre_surface_c: number[]; tyre_core_c: number[]; tyre_pressure_psi: number[]; tyre_wear_pct: number;
  soc_mj: number; harvested_mj: number; deployed_mj: number; energy_mode: string; overtake_available: boolean;
  clipping_events: number; fuel_kg: number; fuel_target_kg: number; oil_c: number; water_c: number; mguk_c: number;
  battery_c: number; brake_c: number[]; brake_wear_pct: number; aero_mode: string; aero_load_delta_pct: number;
}

export interface OwnView {
  row: Row; telemetry: Telemetry | null;
  tyre: { deg_s_lap: number; deg_low: number; deg_high: number } | null;
  tyre_confidence: string;
  deadline: { seconds: number; to_entry: number; missed: boolean };
  energy: {
    mode: string; headline: string; detail: string; soc: number; recharge_limit: number;
    recharge_overtake: number; soc_after_attack: number; vulnerable: boolean;
  };
}

export interface RivalCard {
  code: string; pos: number; color: string; team: string; gap: number; interval: number | null; compound: string;
  age: number; tyre: { deg_s_lap: number; deg_low: number; deg_high: number } | null; tyre_confidence: string;
  energy_low: number; energy_high: number; energy_confidence: string; p_pit: number; history_note: string | null;
  tags: { tag: string; evidence: string; loss_s: number | null }[];
}

export interface Alert {
  id: string; level: "red" | "amber" | "info"; text: string; kind: string; car: string | null; lap: number;
  action: { label: string; action: string } | null;
}

export interface DecisionEntry {
  id: string; wall: string; t: number; lap: number; car: string; action: string; compound: string | null;
  reason: string; role: string; source: string; rec_action: string | null; rec_compound: string | null;
  rec_confidence: number | null; followed: boolean | null; rec_options: { label: string; e_pos: number; e_pts: number }[];
}

export interface Source { age_s: number | null; limit_s: number; stale: boolean }

export interface State {
  session: {
    id: string; circuit: string; circuit_name: string; team: string; team_id: string; team_color: string;
    scenario: string; scenario_id: string; own: string[]; total_laps: number; weekend: string; seed: number;
    model_version: string; compounds: Record<string, string>;
  };
  phase: "prerace" | "race" | "review"; running: boolean; speed: number; autopilot: boolean;
  sources: Record<string, Source>; locked: { by: string; at: string } | null;
  active_plan: Record<string, string>; plans_live: Record<string, Stop[]>;
  prerace_ready: boolean; prerace_running: boolean; sent_at: number;
  pending_box: Record<string, { compound: string; lap: number }>;
  lap?: number; status?: string; neutral_until?: number | null; pit_open?: boolean;
  weather?: {
    air_c: number; track_c: number; humidity: number; wind_kph: number; wetness: number; rain_eta_min: number | null;
  } | null;
  rows?: Row[]; own?: Record<string, OwnView>; recs?: Record<string, Rec>; rec_error?: string | null;
  rivals?: RivalCard[]; alerts?: Alert[]; decisions?: DecisionEntry[];
  notes?: { car: string; text: string; role: string; wall: string }[];
  compute?: { last_ms: number | null; event_ms: number | null; running_s: number | null };
}

export interface LapRow {
  code: string; lap: number; time: number; elapsed: number; comp: number; age: number; in_lap: boolean;
  out_lap: boolean; status: number;
}

export interface CircuitInfo {
  id: string; name: string; laps: number; length_km: number; weekend: string; compounds: Record<string, string>;
  outline: [number, number][]; verified: string[]; recharge_race_mj: number; recharge_overtake_mj: number;
  pit_lane_loss: number;
}

export interface Catalog {
  circuits: CircuitInfo[];
  teams: { id: string; name: string; color: string; drivers: string[]; has_history: boolean }[];
  scenarios: { id: string; name: string; description: string }[];
  roles: Record<string, string>;
}

export interface Candidate {
  label: string; start: string; stops: number; plan: Stop[]; e_pos: number; sd_pos: number; p10: number; p90: number;
  e_pts: number; p_points: number; p_podium: number; e_time: number; utility: number; hist: number[];
}

export interface PlanCard extends Candidate {
  name: string;
  triggers: { kind: string; text: string; target: string }[];
}

export interface PlaybookRow {
  lap: number; event: string; action: string; compound: string | null; gain_pos: number; gain_s: number; confidence: number;
}

export interface WindowStop {
  stop: number; compound: string; planned: number;
  laps: { lap: number; e_pos: number; delta_u: number; traffic: number; zone: string }[];
}

export interface PreRaceData {
  candidates: Record<string, Candidate[]>;
  plans: Record<string, PlanCard[]>;
  playbook: Record<string, PlaybookRow[]>;
  windows: Record<string, WindowStop[]>;
  weather: Record<string, { minute: number; onset_lap: number; crossover_lap: number; e_pos: number; e_pos_stay: number; text: string }[]>;
  elapsed_s: number; n_races: number;
}

export interface WhatIfResult {
  base: { e_pos: number; p10: number; p90: number; e_pts: number; p_points: number; hist: number[] };
  whatif: { e_pos: number; p10: number; p90: number; e_pts: number; p_points: number; hist: number[] };
  delta_pos: number; delta_pts: number; delta_s: number; confidence: number; compute_ms: number; n_sims: number;
}

export interface Scorecard {
  exit_within_1: number | null; exit_within_1_green: number | null; exit_neutral_in_range: number | null;
  exit_samples: number; deg_rate_mae_own: number | null; deg_rate_mae_rival: number | null;
  deg_level_mae_own: number | null; rival_precision: number | null; rival_recall: number | null;
  rival_samples: number; recompute_p95_ms: number | null; event_recompute_max_ms: number | null;
}

export interface Review {
  classification: { pos: number; code: string; team: string; color: string; own: boolean; grid: number; stops: number;
    gap: number; lap: number; retired: boolean }[];
  decisions: DecisionEntry[];
  scorecard: Scorecard;
}
