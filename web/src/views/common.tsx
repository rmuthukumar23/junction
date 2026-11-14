import { useEffect, useRef } from "react";
import { Sprites as S } from "../legacy/sprites";

type Nav = "runs" | "stats" | "how" | "";

export function Topbar({ active }: { active: Nav }) {
  const link = (h: Exclude<Nav, "">, t: string) => (
    <a className={"px-btn sm" + (active === h ? " on" : "")} href={"#/" + h}>{t}</a>
  );
  return (
    <div className="topbar">
      <a className="brand" href="#/">GREENHOUSE BENCH</a>
      <nav>{link("runs", "Runs")}{link("stats", "Stats")}{link("how", "How it works")}</nav>
    </div>
  );
}

/** Pixel-font title drawn on a canvas at an integer scale. */
export function BigText({ text, scale, width }: { text: string; scale: number; width?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const tw = S.textWidth(text, scale);
    c.width = width || tw + 4 * scale; c.height = 9 * scale;
    const x = c.getContext("2d") as CanvasRenderingContext2D, ox = ((c.width - tw) / 2) | 0;
    S.text(x, text, ox + scale, scale * 2, "#cbd6b5", scale);
    S.text(x, text, ox, scale, "#2a4631", scale);
    c.style.width = c.width * 2 + "px";
  }, [text, scale, width]);
  return <canvas ref={ref} className="bigtitle" style={{ maxWidth: "100%", height: "auto" }} />;
}

/** A run's mascot (icon head) drawn at an integer scale. */
export function Mascot({ run, scale }: { run: Parameters<typeof S.mascotFor>[0]; scale: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    const c = S.mascotCanvas(S.mascotFor(run), scale);
    host.replaceChildren(c);
  }, [run, scale]);
  return <div ref={ref} style={{ lineHeight: 0 }} />;
}
