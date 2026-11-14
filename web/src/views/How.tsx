import { Topbar } from "./common";

export function How() {
  return (
    <>
      <Topbar active="how" />
      <div className="page how">
        <div className="px-panel">
          <h2 className="px-title">How it works</h2>
          <p>Greenhouse Bench is an interactive environment. An agent runs three glass greenhouse compartments and a shared energy centre (CHP, boiler, heat buffer, CO2 tank, grid connection) for 42 simulated days. It sees sensor readings and acts through tools: climate setpoints, energy settings, orders, planting, harvesting, hiring, repairs. The score is net profit, compared with doing nothing.</p>
          <h2 className="px-title">What you see</h2>
          <ul>
            <li>Sky, sun and moon follow the hour; clouds, rain, snow and wind follow the weather data.</li>
            <li>Energy building: CHP and BOILER windows glow when running, chimney smoke follows the load, tanks show heat buffer and CO2 stock. Grid arrows show import or export.</li>
            <li>Each greenhouse tints with its temperature, lights its lamps, opens roof vents and closes the thermal screen exactly as recorded. Underground pipes flow with the heat (red) and CO2 (teal) requests.</li>
            <li>Crops grow with age, wilt at low quality and sparkle when ready. The little worker wears the agent's icon head and walks to wherever the current task is.</li>
            <li>A broken window cracks, drops glass and lets cold air and frost in until it is repaired.</li>
          </ul>
          <h2 className="px-title">Controls</h2>
          <p>Space play/pause. Left/Right step one hour (Shift: one day). [ and ] jump to the previous or next event. Click a greenhouse or the energy centre to inspect it. Drag the scrub bar; coloured ticks are events (red bad, yellow warning, blue info).</p>
          <h2 className="px-title">Honesty note</h2>
          <p>Replays are recordings of real simulator hours; with ?mock=1 the data are fabricated for UI testing only.</p>
        </div>
      </div>
    </>
  );
}
