/** requestAnimationFrame loop with dt in seconds (clamped to 0.1). Returns a stop function. */
export function rafLoop(fn: (dt: number, now: number) => void): () => void {
  let last = 0, on = true, id = 0;
  const step = (now: number) => {
    if (!on) return;
    const dt = Math.min(0.1, (now - (last || now)) / 1000);
    last = now; fn(dt, now);
    id = requestAnimationFrame(step);
  };
  id = requestAnimationFrame(step);
  return () => { on = false; cancelAnimationFrame(id); };
}
