import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../lib/api";
import type { Replay } from "../lib/types";
import { Topbar } from "./common";
import { mountReplay } from "./replayController";

export function RunView({ id }: { id: string }) {
  const [data, setData] = useState<Replay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    fetchJson<Replay>("/api/runs/" + encodeURIComponent(id)).then((d) => live && setData(d), (e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (!data || !host.current) return;
    return mountReplay(host.current, data);
  }, [data]);

  return (
    <>
      <Topbar active="" />
      {error ? <div className="page"><div className="px-panel msg bad">Could not load run: {error}</div></div>
        : !data ? <div className="msg dim">Loading run...</div>
        : <div ref={host} />}
    </>
  );
}
