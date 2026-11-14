import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../lib/api";
import { eur, num } from "../lib/format";
import type { RunMeta } from "../lib/types";
import { Mascot, Topbar } from "./common";

export function Runs() {
  const [runs, setRuns] = useState<RunMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("");
  const [seed, setSeed] = useState("");

  useEffect(() => {
    fetchJson<{ runs: RunMeta[] }>("/api/runs").then((j) => setRuns(j.runs || []), (e: Error) => setError(e.message));
  }, []);

  const seeds = useMemo(() => [...new Set((runs || []).map((r) => r.seed))].sort((a, b) => (a ?? 0) - (b ?? 0)), [runs]);
  const list = useMemo(
    () => (runs || [])
      .filter((r) => (!kind || r.kind === kind) && (!seed || String(r.seed) === seed))
      .sort((a, b) => Number(b.score == null) - Number(a.score == null) || (b.score ?? 0) - (a.score ?? 0)),
    [runs, kind, seed],
  );

  return (
    <>
      <Topbar active="runs" />
      <div className="page">
        <h2 className="px-title">Recorded runs</h2>
        {runs && (
          <div className="filters">
            <label>KIND <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">all</option><option>agent</option><option>policy</option></select></label>
            <label>SEED <select value={seed} onChange={(e) => setSeed(e.target.value)}><option value="">all</option>{seeds.map((s) => <option key={String(s)}>{s}</option>)}</select></label>
            <span className="dim">{list.length} / {runs.length}</span>
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
