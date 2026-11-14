// ?mock=1: a fabricated run for UI testing with no backend. Never presented as an agent result.
import { clamp, hashStr } from "./format";
import type { Action, Alarm, Batch, Compartment, DailyRow, Frame, Replay, RunMeta, SimEvent, Severity } from "./types";

function rng(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

type MockRow = [id: string, label: string, kind: "agent" | "policy", model: string, policy: string | null, seed: number, score: number | null, profit: number | null];
const MOCK_RUNS: MockRow[] = [
  ["mock", "Agent: scout-1", "agent", "scout-1", null, 3, 0.71, 9120],
  ["mock-2", "Agent: northwind-large", "agent", "northwind-large", null, 3, 0.55, 6400],
  ["mock-3", "Agent: opencode-mini", "agent", "opencode-mini", null, 5, 0.18, 1800],
  ["mock-4", "Reference planner", "policy", "reference", "reference", 3, 0.8, 11200],
  ["mock-5", "Do nothing", "policy", "do-nothing", "do-nothing", 3, 0, 0],
  ["mock-6", "Agent: scout-1", "agent", "scout-1", null, 101, null, null],
];

export function mockList(): { runs: RunMeta[] } {
  return {
    runs: MOCK_RUNS.map((r, i) => ({
      id: r[0], label: r[1], kind: r[2], model: r[3], policy: r[4], scenario: "normal-winter", seed: r[5], score: r[6], profit_eur: r[7],
      baseline_profit_eur: 0, days: 42, status: r[6] == null ? "partial" : "complete", failure: r[6] == null ? "ran out of tool calls on day 30" : null,
      started: "2026-11-1" + (i + 1) + "T10:00:00Z", source: "mock",
    })),
  };
}

const cache: Record<string, Replay> = {};

export function buildMock(id: string): Replay {
  if (cache[id]) return cache[id];
  const R = rng(hashStr(id)), HOURS = 1008, cids = ["A", "B", "C"];
  const crops: Record<string, string> = { A: "lettuce_butterhead", B: "lettuce_butterhead", C: "broccoli_micro" };
  const dur: Record<string, number> = { A: 21, B: 21, C: 11 };
  const events: SimEvent[] = [], actions: Action[] = [], alarms: Alarm[] = [], daily: DailyRow[] = [], frames: Frame[] = [];
  const tasks: { h0: number; h1: number; kind: string; target: string }[] = [];
  const add = (h: number, kind: string, target: string, text: string, severity: Severity = "info") =>
    events.push({ h, day: Math.floor(h / 24) + 1, kind, target, text, severity });
  const act = (h: number, tool: string, args: Record<string, unknown>, ok = true, err: string | null = null, resp = "ok") =>
    actions.push({ h, day: Math.floor(h / 24) + 1, tool, args, ok, err, resp_summary: resp });
  const task = (h0: number, h1: number, kind: string, target: string) => tasks.push({ h0, h1, kind, target });

  for (const c of cids) for (let j = 0; j < 2; j++) {
    const period = dur[c] * 24, phase = j * dur[c] * 12;
    for (let h = 6; h < HOURS; h += 24) if (h > 6 && (h - 6 + phase) % period === 0) {
      add(h, "harvest", c, "Harvested bed " + c + j + " (" + (40 + j * 6) + " kg)"); add(h, "plant", c, "Planted bed " + c + j);
      act(h, "harvest", { batch_id: c + j + "-" + Math.floor((h - 6 + phase) / period - 1) }); act(h, "plant", { compartment: c, area_m2: 40 });
      task(h, h + 3, "harvest", c); task(h + 3, h + 6, "plant", c);
    }
  }
  const BRK = 17 * 24 + 9, REP = 19 * 24 + 11, TRIP = 12 * 24 + 4, FIX = 12 * 24 + 15;
  add(17 * 24 + 3, "storm", "", "Storm warning: gusts up to 18 m/s", "warn"); add(17 * 24 + 8, "storm_damage", "B", "Wind damage to roof of B", "bad");
  add(BRK, "window_break", "B", "A window in B broke in the storm", "bad"); add(BRK + 3, "alarm", "B", "B is cooling fast: 9.1 C", "bad");
  alarms.push({ h: BRK + 3, kind: "temp", target: "B", text: "B is cooling fast: 9.1 C" });
  add(REP, "window_repaired", "B", "Window in B repaired"); task(19 * 24 + 6, REP, "repair", "B"); act(19 * 24 + 6, "repair", { target: "B" }, true, null, "contractor not needed");
  add(TRIP, "equipment", "boiler", "boiler tripped. Needs a manual restart", "bad"); alarms.push({ h: TRIP, kind: "equipment", target: "boiler", text: "boiler tripped" });
  add(FIX, "equipment", "boiler", "boiler working again"); task(12 * 24 + 6, 12 * 24 + 15, "repair", "boiler"); act(12 * 24 + 6, "repair", { target: "boiler" });
  add(7 * 24 + 6, "order_placed", "", "Ordered 800 kg CO2"); act(7 * 24 + 6, "place_order", { item: "co2_kg", quantity: 800 });
  add(8 * 24 + 10, "late_delivery", "", "CO2 delivery is late", "warn"); add(8 * 24 + 13, "order_arrived", "", "Order arrived: 800 kg CO2");
  add(3 * 24 + 6, "hire", "", "Hired 1 worker"); act(3 * 24 + 6, "hire", { workers: 1 }); add(30 * 24 + 6, "release", "", "Released 1 worker"); act(30 * 24 + 6, "release", { workers: 1 });
  for (let d = 0; d < 42; d++) {
    const h = d * 24 + 6, c = cids[Math.floor(R() * 3)];
    act(h, "set_climate", { compartment: c, heat_day_c: 19 + Math.floor(R() * 3), co2_ppm: 700 + 50 * Math.floor(R() * 4) });
    if (R() < 0.12) act(h, "plant", { compartment: c, area_m2: 400 }, false, "area exceeds free space");
    act(h, "submit_day", {}, true, null, "day " + (d + 1) + " submitted");
  }
  events.sort((a, b) => a.h - b.h); actions.sort((a, b) => a.h - b.h);
  let rev = 0, costs = 0, kg = 0, evi = 0;
  const baseline = -1500;
  for (let h = 0; h < HOURS; h++) {
    const hod = h % 24, d = Math.floor(h / 24), storm = h >= 410 && h <= 432, snow = d >= 20 && d <= 23;
    const t = -2 + 4 * Math.sin(((hod - 14) / 24) * 6.283) + 3 * Math.sin(d / 5) + (storm ? 3 : 0) - (snow ? 3 : 0);
    const sunBase = hod >= 8 && hod <= 16 ? 95 * Math.sin((Math.PI * (hod - 8)) / 8) : 0;
    const out = { t: +t.toFixed(1), rh: storm ? 96 : snow ? 90 : 78 + 8 * Math.sin(h / 9), sun: +(sunBase * (storm || snow ? 0.2 : 0.4 + 0.6 * Math.abs(Math.sin(d * 1.7)))).toFixed(1), wind: storm ? 16 + 2 * Math.sin(h) : 3 + 2 * Math.sin(h / 7) };
    const trip = h >= TRIP && h < FIX, c: Record<string, Compartment> = {}, b: Batch[] = [];
    let lampTot = 0, heatTot = 0;
    for (const id of cids) {
      const broken = id === "B" && h >= BRK && h < REP, since = id === "B" && h >= BRK ? Math.min(h - BRK, 20) : 0;
      let ti = 18.5 + 1.5 * Math.sin(((hod - 14) / 24) * 6.283) + R() * 0.2;
      if (broken) ti = ti - (ti - out.t) * (since / 28);
      if (id === "B" && h >= REP && h < REP + 10) ti -= (REP + 10 - h) * 0.5;
      if (trip) ti -= 0.4 * Math.min(h - TRIP, 6);
      const lamp = id === "C" ? 0 : (hod < 7 || hod >= 16) && hod !== 15 ? 8 : 0, heat = Math.max(0, (19 - out.t) * 1.6) * (broken ? 1.6 : 1) * (trip ? 0.3 : 1);
      lampTot += lamp; heatTot += heat;
      const cr = hod >= 8 && hod < 16 ? 0.6 : 0;
      c[id] = { t: +ti.toFixed(1), rh: +(72 + 8 * Math.sin(h / 6) + (broken ? 8 : 0)).toFixed(1), co2: Math.round(700 + 140 * Math.sin(h / 11) + (hod >= 8 && hod < 16 ? 100 : 0)),
        par: +(lamp * 6 + out.sun * 0.9).toFixed(1), dli: +((h % 24) * 0.8).toFixed(1), vent: broken ? 0 : sunBase > 60 && out.t > -2 ? 35 : out.t > 3 ? 15 : 0,
        screen: hod < 7 || hod >= 17, lamp, heat: +heat.toFixed(1), co2req: cr, sp_day: 20, sp_night: 16, sp_co2: 800, free: 6 };
      for (let j = 0; j < 2; j++) {
        const period = dur[id] * 24, tt = h - 6 + j * dur[id] * 12 + period * 4, cyc = Math.floor(tt / period), age = (tt % period) / 24;
        const g = clamp(age / dur[id], 0.03, 1), ready = age >= dur[id] - 2, dmg = id === "B" && h > REP && h < REP + 300 ? 0.42 : 0.94 - 0.02 * j;
        b.push({ id: id + j + "-" + cyc, crop: crops[id], c: id, area: 40 - j * 4, age: +age.toFixed(1), st: ready ? "ready" : "growing", q: false,
          w: +(8 + 130 * g * g).toFixed(1), qual: +dmg.toFixed(3), ready: ready ? 0 : +(dur[id] - age).toFixed(1), units: 240 });
      }
    }
    while (evi < events.length && events[evi].h <= h) { const e = events[evi++]; if (e.kind === "harvest") { rev += 160 + R() * 120; kg += 42; } }
    costs += 3 + lampTot * 0.1 + heatTot * 0.06;
    const imp = lampTot > 0 ? Math.round(lampTot * 0.7) : 0;
    const tk = tasks.filter((x) => h >= x.h0 && h < x.h1).map((x) => ({ kind: x.kind, target: x.target, done: h - x.h0, need: x.h1 - x.h0, st: "active" }));
    const co2tank = 900 - (h % 190) * 3.5 + (h >= 205 ? 400 : 0);
    frames.push({ h, day: d + 1, hod, out, c,
      ec: { buffer: Math.round(220 + 150 * Math.sin(h / 14) + (trip ? -120 : 0)), co2: Math.max(60, Math.round(co2tank)), chp: trip ? 0.6 : hod >= 7 && hod < 22 ? 0.8 : 0,
        boiler: trip ? 0 : heatTot > 22 ? 1 : 0, bufmode: "charge", extco2: 0, gas: +(1 + heatTot * 0.1).toFixed(1), imp, exp: hod >= 7 && hod < 22 && !lampTot ? 40 : 0,
        heat: +heatTot.toFixed(1), lost: 4, p_gas: 0.4, p_imp: 0.2, p_exp: 0.1 },
      faults: trip ? ["boiler"] : [], money: { cash_eur: +(20000 + rev - costs).toFixed(0), profit_so_far_eur: +(rev - costs).toFixed(0), harvest_revenue_eur: +rev.toFixed(0) },
      staff: 2, tasks: tk, orders: [], stock: {}, b, damage: { B: c.B && h >= BRK && h < REP + 24 ? 0.7 : 0 } });
    if (hod === 23) daily.push({ day: d + 1, cash: +(20000 + rev - costs).toFixed(0), profit: +(rev - costs).toFixed(0), revenue: +rev.toFixed(0), costs: +costs.toFixed(0),
      harvested_kg: kg, alarms: alarms.filter((a) => a.h >= d * 24 && a.h < d * 24 + 24).length });
  }
  const final = frames[HOURS - 1].money.profit_so_far_eur ?? null, row = MOCK_RUNS.find((r) => r[0] === id) || MOCK_RUNS[0];
  const meta = { id, label: row[1], kind: row[2], model: row[3], policy: row[4], scenario: "normal-winter", seed: row[5], score: row[6], profit_eur: final,
    baseline_profit_eur: baseline, days: 42, status: "complete" as const, failure: null, started: "2026-11-10T10:00:00Z", source: "mock",
    shift: "07:00-15:00", max_calls: 400, compartments: { A: { crop: crops.A }, B: { crop: crops.B }, C: { crop: crops.C } }, crops: {},
    objective: "Maximise net profit over 42 simulated days.", hours: HOURS, replay_verified: true };
  return (cache[id] = { meta, frames, actions, events, alarms, daily });
}
