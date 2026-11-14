import { useEffect, useRef } from "react";
import { PixelScene } from "../legacy/scene";
import { buildMock } from "../lib/mock";
import { rafLoop } from "../lib/loop";
import { BigText } from "./common";

export function Intro() {
  const bg = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = bg.current;
    if (!cv) return;
    // Background: the greenhouse world playing fabricated mock weather, purely decorative.
    const sc = PixelScene.create(cv, {}), scale = Math.max(1, Math.ceil(innerWidth / 480));
    cv.style.width = 480 * scale + "px"; cv.style.height = 270 * scale + "px";
    sc.setData(buildMock("intro"));
    let hf = 380;
    return rafLoop((dt) => { hf += dt * 12; if (hf > 1000) { hf = 0; sc.reset(0); } sc.render(hf, dt, 12, true); });
  }, []);
  return (
    <div className="intro">
      <canvas className="bg" ref={bg} />
      <div className="content">
        <BigText text="GREENHOUSE BENCH" scale={6} width={400} />
        <img className="hero" src={import.meta.env.BASE_URL + "hero.png"} alt="Two pixel fighters with icon heads clash a shovel and a pitchfork in a greenhouse" />
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
