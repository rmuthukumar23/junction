import { useEffect, useRef } from "react";
import { getBank } from "../art";
import { H, IntroFight, W } from "../intro/IntroFight";
import { rafLoop } from "../lib/loop";
import { query } from "../lib/route";
import { BigText } from "./common";

/** Integer scale for the 320x180 scene: as large as fits the viewport without blurring (at least 2: on narrow phones the sides are cropped, fighters stay centred). */
function sceneScale(): number { return Math.max(2, Math.floor(Math.min(innerWidth / W, innerHeight / H))); }

export function Intro() {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = cv.current;
    if (!canvas) return;
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
    const fit = () => { const s = sceneScale(); canvas.style.width = W * s + "px"; canvas.style.height = H * s + "px"; };
    fit(); addEventListener("resize", fit);
    const scene = new IntroFight(getBank());
    const at = Number(query.get("introAt"));
    if (at > 0) scene.seek(at);
    scene.draw(ctx);
    const stop = rafLoop((dt) => { scene.update(dt); scene.draw(ctx); });
    return () => { stop(); removeEventListener("resize", fit); };
  }, []);
  return (
    <div className="intro">
      <div className="sky" />
      <canvas ref={cv} className="scene" aria-label="Two fighters with icon heads clash a shovel and a pitchfork in a greenhouse" />
      <div className="content">
        <div className="title">
          <BigText text="GREENHOUSE BENCH" scale={3} />
          <p className="sub">AI agents run a winter greenhouse. Scored on net profit.</p>
        </div>
        <nav className="nav">
          <a className="px-btn sm" href="#/stats">Stats</a>
          <a className="px-btn sm" href="#/how">How it works</a>
        </nav>
        <div className="cta"><a className="px-btn primary" href="#/runs">Watch a run</a></div>
      </div>
    </div>
  );
}
