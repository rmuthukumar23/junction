// Shapes of the Python API (scripts/pixel/server.py, docs/features/pixel-site.md).

export type RunKind = "agent" | "policy";
export type RunStatus = "complete" | "partial" | "failed";
export type Severity = "info" | "warn" | "bad";

export interface RunMeta {
  id: string;
  label: string | null;
  kind: RunKind;
  model: string | null;
  policy: string | null;
  scenario: string | null;
  seed: number | null;
  score: number | null;
  profit_eur: number | null;
  baseline_profit_eur: number | null;
  days: number | null;
  status: RunStatus;
  failure: string | null;
  started: string | null;
  source: string | null;
  [extra: string]: unknown;
}

export interface ReplayMeta extends RunMeta {
  shift?: string | null;
  max_calls?: number | null;
  compartments?: Record<string, { crop?: string | null }>;
  crops?: Record<string, unknown>;
  objective?: string | null;
  hours?: number;
  replay_verified?: boolean | null;
  mismatches?: unknown;
  end_reason?: string | null;
  calls_used?: number | null;
  ledger_score?: number | null;
}

export interface Compartment {
  t: number; rh: number; co2: number; par: number; dli?: number; vent: number; screen: boolean | number;
  lamp: number; heat: number; co2req?: number; sp_day: number; sp_night: number; sp_co2: number; free?: number;
  [extra: string]: unknown;
}

export interface Batch {
  id: string; crop: string; c: string; area: number; age: number; st: string; q?: boolean; w?: number;
  qual: number; ready?: number; units?: number; [extra: string]: unknown;
}

export interface Frame {
  h: number;
  day: number;
  hod: number;
  out: { t: number; rh: number; sun: number; wind: number; [extra: string]: unknown };
  c: Record<string, Compartment>;
  ec: Record<string, number | string | boolean | null> & { buffer?: number; co2?: number; chp?: number; imp?: number; exp?: number; gas?: number; boiler?: unknown };
  faults: string[];
  money: { cash_eur?: number; profit_so_far_eur?: number; harvest_revenue_eur?: number; [extra: string]: number | undefined };
  b: Batch[];
  damage?: Record<string, number>;
  [extra: string]: unknown;
}

export interface Action {
  h: number; day: number; tool: string; args: Record<string, unknown> | null; ok: boolean; err: string | null; resp_summary?: string | null;
}

export interface SimEvent {
  h: number; day: number; kind: string; target: string; text: string; severity: Severity;
}

export interface Alarm { h: number; kind?: string; target?: string; text: string; [extra: string]: unknown }

export interface DailyRow { day: number; cash: number; profit: number; revenue: number; costs: number; harvested_kg: number; alarms: number }

export interface Replay {
  meta: ReplayMeta;
  frames: Frame[];
  actions: Action[];
  events: SimEvent[];
  alarms: Alarm[];
  daily: DailyRow[];
}
