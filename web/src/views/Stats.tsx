import { useEffect, useRef, useState } from "react";
import { PixelStats } from "../legacy/stats";
import { fetchJson } from "../lib/api";
import { Topbar } from "./common";

export function Stats() {
  const root = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!root.current) return;
    try { PixelStats.mount(root.current, { fetchJson }); } catch (e) { setError((e as Error).message); }
  }, []);
  return (
    <>
      <Topbar active="stats" />
      <div className="page">
        {error && <div className="px-panel msg bad">Stats failed: {error}</div>}
        <div ref={root} />
      </div>
    </>
  );
}
