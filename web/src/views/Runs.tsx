import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../lib/api";
import { eur, num } from "../lib/format";
import type { RunMeta } from "../lib/types";
import { Mascot, Topbar } from "./common";

const DEFAULT_SCENARIO = "normal-winter";
const isSmoke = (r: RunMeta) => /smoke/i.test(r.scenario || "");

export function Runs() {
  const [runs, setRuns] = useState<RunMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [status, setStatus] = useState("");
  const [seed, setSeed] = useState("");

  useEffect(() => {
    fetchJson<{ runs: RunMeta[] }>("/api/runs").then((j) => setRuns(j.runs || []), (e: Error) => setError(e.message));
  }, []);

  // Only model runs: scripted reference policies and smoke checks are not listed.
  const agentRuns = useMemo(() => (runs || []).filter((r) => r.kind === "agent" && !isSmoke(r)), [runs]);
  const scenarios = useMemo(() => [...new Set(agentRuns.map((r) => r.scenario || "unknown"))].sort(), [agentRuns]);
  const seeds = useMemo(() => [...new Set(agentRuns.map((r) => r.seed))].sort((a, b) => (a ?? 0) - (b ?? 0)), [agentRuns]);
  const activeScenario = scenarios.includes(scenario) ? scenario : "";
  const list = useMemo(
    () => agentRuns
      .filter((r) => (!activeScenario || (r.scenario || "unknown") === activeScenario)
        && (!status || r.status === status) && (!seed || String(r.seed) === seed))
      .sort((a, b) => (b.started || "").localeCompare(a.started || "")),
    [agentRuns, activeScenario, status, seed],
  );

  return (
    <>
      <Topbar active="runs" />
      <div className="page">
        <h2 className="px-title">Recorded runs</h2>
        {runs && (
          <div className="filters">
            <label>SCENARIO <select value={activeScenario} onChange={(e) => setScenario(e.target.value)}><option value="">all</option>{scenarios.map((s) => <option key={s}>{s}</option>)}</select></label>
            <label>STATUS <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">all</option><option>complete</option><option>partial</option><option>failed</option></select></label>
            <label>SEED <select value={seed} onChange={(e) => setSeed(e.target.value)}><option value="">all</option>{seeds.map((s) => <option key={String(s)}>{s}</option>)}</select></label>
            <span className="dim">{list.length} / {agentRuns.length}</span>
          </div>
        )}
        <div className="cards">
          {error ? <div className="px-panel msg bad">Could not load runs: {error}. Try <a href="?mock=1#/runs">?mock=1</a>.</div>
            : !runs ? <div className="msg dim">Loading runs...</div>
            : !list.length ? <div className="msg dim">No runs match.</div>
            : list.map((r) => <RunCard key={r.id} r={r} />)}
        </div>
      </div>
    </>
  );
}

function RunCard({ r }: { r: RunMeta }) {
  const base = r.baseline_profit_eur, d = r.profit_eur != null && base != null ? r.profit_eur - base : null;
  const st = r.status === "complete" ? "good" : r.status === "partial" ? "warn" : "bad";
  return (
    <a className="card px-panel" href={"#/run/" + encodeURIComponent(r.id)}>
      <div className="face"><Mascot run={r} scale={5} /></div>
      <div>
        <h3>{r.label || r.model || r.id}</h3>
        <div className="row">
          <span className={"px-tag" + (r.kind === "agent" ? " info" : "")}>{r.kind}</span>
          <span className="px-tag">seed {r.seed}</span>
          <span className={"px-tag " + st}>{r.status}</span>
        </div>
        <div className="big">{r.score == null ? "-" : "SCORE " + num(r.score, 2)}</div>
        <div className="dim">PROFIT {eur(r.profit_eur)}</div>
        <div className="dim">BASELINE {eur(base)}</div>
        {d != null && <div className={d >= 0 ? "good" : "bad"}>{eur(d, true)} vs do-nothing</div>}
        {r.failure && <div className="bad">{r.failure}</div>}
      </div>
    </a>
  );
}
