import { useEffect, useRef } from "react";
import { getBank } from "../art";
import { H, IntroFight, W } from "../intro/IntroFight";
import { rafLoop } from "../lib/loop";
import { query } from "../lib/route";
import { BigText } from "./common";

/** Integer scale for the 320x180 scene so it fills the content width without blurring. */
function sceneScale(): number { return Math.max(1, Math.min(4, Math.floor(Math.min(innerWidth - 28, 1100) / W))); }

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
      <div className="content">
        <BigText text="GREENHOUSE BENCH" scale={6} width={400} />
        <canvas ref={cv} className="scene" aria-label="Two fighters with icon heads clash a shovel and a pitchfork in a greenhouse" />
        <div className="px-panel lines">
          <div>An AI agent runs a 3-compartment winter greenhouse and its energy centre for 42 simulated days.</div>
          <div>It reads sensors, sets heating, light and CO2, orders stock, plants, harvests and fixes breakdowns through tools.</div>
          <div>It is scored on net profit against doing nothing. Watch any recorded run as a living pixel greenhouse.</div>
        </div>
        <div className="btns">
          <a className="px-btn primary" href="#/runs">Watch a run</a>
          <a className="px-btn" href="#/stats">Stats</a>
          <a className="px-btn" href="#/how">How it works</a>
        </div>
      </div>
    </div>
  );
}
