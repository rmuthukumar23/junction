// The greenhouse site in 3D: an orthographic (isometric) camera, rendered at low resolution
// and scaled up without smoothing for a voxel/pixel look. Drag to rotate, scroll to zoom.
const Scene = (() => {
  const PIX = 3, HW = 10, HD = 14, WALL = 3.4, RIDGE = 2.2, GAP = 3.5, ROAD_Z = HD / 2 + 8;
  const SLOPE = Math.atan2(2.2, 5);              // roof pitch: RIDGE over half the width
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, k) => a + (b - a) * k;
  const col = (h) => new THREE.Color(h);
  const mixc = (a, b, k) => col(a).lerp(col(b), clamp(k, 0, 1));
  let seed = 11; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  let renderer, scene, camera, canvas, stage, meta = {}, t = 0, ids = [], houses = {}, ec = {}, world = {};
  let az = Math.PI / 4, zoom = 1, layerLbl, bubbles = [], workers = [], lastHour = -1;
  const lambert = (c, extra = {}) => new THREE.MeshLambertMaterial({ color: c, ...extra });
  const basic = (c, extra = {}) => new THREE.MeshBasicMaterial({ color: c, ...extra });
  const box = (w, h, d, m) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);

  // ---------------- building the world ----------------
  function init(cv) {
    canvas = cv; stage = cv.parentElement;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
    renderer.setPixelRatio(1);
    scene = new THREE.Scene();
    camera = new THREE.OrthographicCamera(-10, 10, 10, -10, -200, 400);
    world.amb = new THREE.AmbientLight(0xffffff, 0.4); scene.add(world.amb);
    world.hemi = new THREE.HemisphereLight(0xbfdfff, 0x3a5030, 0.35); scene.add(world.hemi);
    world.sun = new THREE.DirectionalLight(0xfff2d0, 0.9); world.sun.position.set(-30, 40, 20); scene.add(world.sun);
    layerLbl = document.createElement("div"); layerLbl.className = "scene-labels"; stage.appendChild(layerLbl);
    // drag to rotate, wheel to zoom; a click without a drag opens details
    let down = null;
    canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, az, moved: false }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => { if (!down) return; const dx = e.clientX - down.x; if (Math.abs(dx) > 3) down.moved = true; az = down.az - dx * 0.008; });
    canvas.addEventListener("pointerup", (e) => { if (down && !down.moved) canvas.dispatchEvent(new CustomEvent("scenepick", { detail: pick(e) })); down = null; });
    const qz = +new URLSearchParams(location.search).get("zoom"); if (qz) zoom = clamp(qz, 0.6, 3);
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoom = clamp(zoom * (e.deltaY > 0 ? 0.9 : 1.1), 0.6, 3); }, { passive: false });
  }

  function clearWorld() {
    while (scene.children.length > 3) scene.remove(scene.children[3]);
    layerLbl.innerHTML = ""; houses = {}; ec = {}; workers = []; bubbles = []; lastHour = -1;
  }

  function setData(m) {
    meta = m; ids = Object.keys(m.compartments).sort(); clearWorld();
    const span = ids.length * HW + (ids.length - 1) * GAP;
    world.x0 = -span / 2 - 6; world.span = span + 22;
    // ground, path and road
    world.ground = new THREE.Mesh(new THREE.BoxGeometry(world.span + 30, 1, 46), lambert(0x3d5a3a)); world.ground.position.set(world.x0 + world.span / 2, -0.5, 2); scene.add(world.ground);
    const road = box(world.span + 30, 0.06, 4, lambert(0x3c3f48)); road.position.set(world.x0 + world.span / 2, 0.03, ROAD_Z); scene.add(road);
    for (let x = world.x0 - 12; x < world.x0 + world.span + 14; x += 3) { const d = box(1.4, 0.07, 0.18, basic(0x9a9da6)); d.position.set(x, 0.05, ROAD_Z); scene.add(d); }
    const path = box(world.span, 0.04, 1.6, lambert(0x7a6a52)); path.position.set(world.x0 + world.span / 2, 0.02, HD / 2 + 3.2); scene.add(path);
    ids.forEach((id, i) => buildHouse(id, world.x0 + 6 + i * (HW + GAP) + HW / 2));
    buildEnergy(world.x0 + 6 + span + 6.5);
    // main heat pipe along the front of the houses
    world.pipe = box(span + 7, 0.25, 0.25, lambert(0x40454f, { emissive: 0x000000 }));
    world.pipe.position.set(world.x0 + 6 + span / 2 + 3, 0.15, HD / 2 + 1.2); scene.add(world.pipe);
    // weather particles
    const n = 700, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { pos[i * 3] = world.x0 - 10 + rnd() * (world.span + 20); pos[i * 3 + 1] = rnd() * 22; pos[i * 3 + 2] = -20 + rnd() * 44; }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    world.flakes = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, sizeAttenuation: false })); scene.add(world.flakes);
    // truck
    const tr = new THREE.Group();
    const cargo = box(3.6, 1.8, 1.8, lambert(0xe8eef4)); cargo.position.set(0, 1.3, 0); tr.add(cargo);
    const cab = box(1.3, 1.4, 1.8, lambert(0xd84a3a)); cab.position.set(2.5, 1.1, 0); tr.add(cab);
    const glass = box(0.1, 0.6, 1.5, basic(0x9cd0f0)); glass.position.set(3.16, 1.4, 0); tr.add(glass);
    for (const wx of [-1.1, 1.0, 2.5]) for (const wz of [-0.9, 0.9]) { const w = box(0.7, 0.7, 0.2, lambert(0x1a1d24)); w.position.set(wx, 0.35, wz); tr.add(w); }
    tr.visible = false; tr.position.z = ROAD_Z; scene.add(tr); world.truck = tr;
  }

  function buildHouse(id, cx) {
    const h = { id, cx, group: new THREE.Group() }; h.group.position.set(cx, 0, 0); scene.add(h.group);
    const G = h.group, frameMat = new THREE.LineBasicMaterial({ color: 0xdfeee9 });
    const floor = box(HW, 0.1, HD, lambert(0x4a3a2c)); floor.position.y = 0.05; G.add(floor);
    // glass walls and gable roof (ridge runs front to back)
    const glass = lambert(0xbfe6ff, { transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide });
    const walls = box(HW, WALL, HD, glass); walls.position.y = WALL / 2; G.add(walls);
    const shape = new THREE.Shape([new THREE.Vector2(-HW / 2, 0), new THREE.Vector2(HW / 2, 0), new THREE.Vector2(0, RIDGE)]);
    const roofG = new THREE.ExtrudeGeometry(shape, { depth: HD, bevelEnabled: false }); roofG.translate(0, WALL, -HD / 2);
    G.add(new THREE.Mesh(roofG, glass));
    G.add(new THREE.LineSegments(new THREE.EdgesGeometry(walls.geometry), frameMat).translateY(WALL / 2));
    G.add(new THREE.LineSegments(new THREE.EdgesGeometry(roofG), frameMat));
    for (let z = -HD / 2 + 2; z < HD / 2; z += 2) {           // mullions and rafters
      const pts = [[-HW / 2, 0, z], [-HW / 2, WALL, z], [0, WALL + RIDGE, z], [HW / 2, WALL, z], [HW / 2, 0, z]].map((p) => new THREE.Vector3(...p));
      G.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xdfeee9, transparent: true, opacity: 0.45 })));
    }
    // air tint volume, energy screen, roof vent
    h.tint = box(HW - 0.2, WALL - 0.2, HD - 0.2, basic(0x5aa0ff, { transparent: true, opacity: 0, depthWrite: false })); h.tint.position.y = WALL / 2; G.add(h.tint);
    h.screen = box(HW - 0.1, 0.05, HD - 0.1, lambert(0xd8c79a, { transparent: true, opacity: 0.4, depthWrite: false })); h.screen.position.y = WALL - 0.08; G.add(h.screen);
    // roof vents: small glass windows hinged at the ridge, lying flush on the slope when shut
    h.vents = [];
    const ventMat = lambert(0xcfe9f2, { transparent: true, opacity: 0.55 }), ventEdge = new THREE.LineBasicMaterial({ color: 0xdfeee9 });
    [[-4.5, 1], [0, -1], [4.5, 1]].forEach(([vz, side]) => {
      const pivot = new THREE.Group(); pivot.position.set(0, WALL + RIDGE + 0.03, vz);
      const pane = box(1.8, 0.06, 2.2, ventMat); pane.position.x = side * 0.95; pivot.add(pane);
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(pane.geometry), ventEdge); edge.position.copy(pane.position); pivot.add(edge);
      pivot.userData.side = side; G.add(pivot); h.vents.push(pivot);
    });
    // lamps with light cones and one point light
    h.lampMat = basic(0x3a3f48); const housing = lambert(0x2b2f38);
    h.coneMat = basic(0xffe680, { transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending });
    for (const lx of [-2.5, 2.5]) for (const lz of [-4.5, 0, 4.5]) {
      const l = box(0.8, 0.14, 0.36, housing); l.position.set(lx, WALL - 0.45, lz); G.add(l);
      const bulb = box(0.6, 0.04, 0.22, h.lampMat); bulb.position.set(lx, WALL - 0.54, lz); G.add(bulb);
      const c = new THREE.Mesh(new THREE.ConeGeometry(1.6, WALL - 0.4, 6, 1, true), h.coneMat); c.position.set(lx, (WALL - 0.4) / 2, lz); G.add(c);
    }
    h.light = new THREE.PointLight(0xffe7a0, 0, 14); h.light.position.set(0, WALL - 0.6, 0); G.add(h.light);
    // heating pipes along both walls
    h.pipeMat = lambert(0x40454f, { emissive: 0x000000 });
    for (const px of [-HW / 2 + 0.35, HW / 2 - 0.35]) { const p = box(0.2, 0.2, HD - 0.6, h.pipeMat); p.position.set(px, 0.25, 0); G.add(p); }
    // plants: one instanced voxel per spot, re-laid out every hour
    h.plants = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), lambert(0xffffff), MAXV); h.plants.count = 0;
    h.plants.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(MAXV * 3).fill(1), 3); G.add(h.plants);
    h.beds = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), lambert(0x6b4630), 12); h.beds.count = 0; G.add(h.beds);
    h.crates = new THREE.InstancedMesh(new THREE.BoxGeometry(0.7, 0.45, 0.5), lambert(0xa0703c), 12); h.crates.count = 0; G.add(h.crates);
    h.marks = []; for (let i = 0; i < 6; i++) { const m = new THREE.Mesh(new THREE.OctahedronGeometry(0.35), basic(0xffd84a)); m.visible = false; G.add(m); h.marks.push(m); }
    // CO2 particles
    const pos = new Float32Array(60 * 3); for (let i = 0; i < 60; i++) { pos[i * 3] = (rnd() - 0.5) * (HW - 1); pos[i * 3 + 1] = 0.8 + rnd() * (WALL - 1.2); pos[i * 3 + 2] = (rnd() - 0.5) * (HD - 1); }
    const pg = new THREE.BufferGeometry(); pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    h.co2 = new THREE.Points(pg, new THREE.PointsMaterial({ color: 0xbcd7ff, size: 2, sizeAttenuation: false })); G.add(h.co2);
    h.hit = box(HW, WALL + RIDGE, HD, basic(0, { visible: false })); h.hit.position.y = (WALL + RIDGE) / 2; h.hit.userData.pick = id; G.add(h.hit);
    // label
    h.lbl = document.createElement("div"); h.lbl.className = "lbl"; layerLbl.appendChild(h.lbl);
    houses[id] = h;
  }

  function buildEnergy(x) {
    const G = new THREE.Group(); G.position.set(x, 0, -1); scene.add(G); ec.group = G; ec.x = x;
    const b = box(6, 4, 6, lambert(0x8a4b3a)); b.position.y = 2; G.add(b);
    const roof = box(6.6, 0.4, 6.6, lambert(0x3a2a26)); roof.position.y = 4.2; G.add(roof);
    ec.winMat = basic(0x9cc8e0); for (const wx of [-1.6, 0.2]) { const w = box(1.2, 0.9, 0.05, ec.winMat); w.position.set(wx, 2.8, 3.03); G.add(w); }
    const door = box(1.1, 2, 0.05, lambert(0x3a2a26)); door.position.set(1.8, 1, 3.03); G.add(door);
    const ch = box(0.9, 5, 0.9, lambert(0x6e3b2e)); ch.position.set(1.8, 6.6, -1.5); G.add(ch);
    ec.chimneyTop = new THREE.Vector3(x + 1.8, 9.2, -2.5);
    ec.beacon = new THREE.Mesh(new THREE.SphereGeometry(0.3, 6, 4), basic(0x5ee06a)); ec.beacon.position.set(-2.5, 4.7, 2.5); G.add(ec.beacon);
    // CHP unit with a spinning fan
    const chp = box(2.4, 1.6, 2, lambert(0x5a6270)); chp.position.set(-1.6, 0.8, 4.3); G.add(chp);
    ec.fan = box(1.4, 0.12, 0.25, lambert(0xc0c8d4)); ec.fan.position.set(-1.6, 1.0, 5.32); G.add(ec.fan);
    // tanks: hot-water buffer (orange) and CO2 (blue)
    const tank = (tx, r, h, fill) => {
      const shell = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 10), lambert(0x2b313c, { transparent: true, opacity: 0.45 })); shell.position.set(tx, h / 2, 0); G.add(shell);
      const f = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.85, r * 0.85, 1, 10), lambert(fill, { emissive: fill, emissiveIntensity: 0.25 })); f.position.set(tx, 0, 0); G.add(f);
      return { f, h };
    };
    ec.buffer = tank(4.8, 1.1, 5.5, 0xff8a3c); ec.co2 = tank(7.4, 0.9, 4.2, 0x7cc4ff);
    // power pole and wire
    const pole = box(0.3, 9, 0.3, lambert(0x4a4036)); pole.position.set(9.5, 4.5, -4); G.add(pole);
    const pts = []; for (let i = 0; i <= 30; i++) { const k = i / 30; pts.push(new THREE.Vector3(lerp(9.5, 0, k), lerp(8.8, 4.4, k) - Math.sin(Math.PI * k) * 1.2, lerp(-4, -1, k))); }
    ec.wire = pts; G.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x22262e })));
    ec.sparks = []; for (let i = 0; i < 4; i++) { const s = new THREE.Mesh(new THREE.SphereGeometry(0.18, 4, 3), basic(0xffe066)); G.add(s); ec.sparks.push(s); }
    // smoke puffs
    ec.smoke = []; for (let i = 0; i < 36; i++) { const s = box(0.6, 0.6, 0.6, basic(0xd2d4da, { transparent: true, opacity: 0 })); s.visible = false; scene.add(s); ec.smoke.push({ m: s, life: 1 }); }
    ec.fault = []; for (let i = 0; i < 14; i++) { const s = box(0.15, 0.15, 0.15, basic(0xffb040)); s.visible = false; scene.add(s); ec.fault.push({ m: s, v: new THREE.Vector3(), life: 0 }); }
    ec.hit = box(14, 9, 9, basic(0, { visible: false })); ec.hit.position.set(3, 4, 0); ec.hit.userData.pick = "energy"; G.add(ec.hit);
    ec.lbl = document.createElement("div"); ec.lbl.className = "lbl"; ec.lbl.textContent = "ENERGY"; layerLbl.appendChild(ec.lbl);
  }

  // ---------------- per-hour layout: beds and plants ----------------
  // Voxel models of one plant at full size: [size xyz, position xyz, tilt about z, colour, grows-late].
  // A "late" part (a radish bulb, broccoli florets) only appears as the plant matures.
  const MAXV = 2600, PLANT = 2.1;          // PLANT: models are drawn this many times life-size so they read
  const MODELS = {
    broccoli: { step: 1.5, parts: [
      [[0.16, 0.42, 0.16], [0, 0.21, 0], 0, 0xb5d48a],
      [[0.34, 0.05, 0.12], [0.2, 0.26, 0], -0.4, 0x5fa04e], [[0.34, 0.05, 0.12], [-0.2, 0.3, 0], 0.4, 0x5fa04e],
      [[0.24, 0.22, 0.24], [0, 0.55, 0], 0, 0x2f7a3a, 1], [[0.2, 0.2, 0.2], [0.15, 0.49, 0.06], 0, 0x2a6e34, 1],
      [[0.2, 0.2, 0.2], [-0.15, 0.5, -0.05], 0, 0x357f3c, 1], [[0.2, 0.2, 0.2], [0.03, 0.48, 0.16], 0, 0x2a6e34, 1],
      [[0.2, 0.2, 0.2], [-0.02, 0.5, -0.17], 0, 0x3a8a42, 1]] },
    radish: { step: 1.15, parts: [
      [[0.3, 0.26, 0.3], [0, 0.13, 0], 0, 0xd8335c, 1], [[0.12, 0.1, 0.12], [0, -0.02, 0], 0, 0xf2e6ea, 1],
      [[0.22, 0.06, 0.22], [0, 0.28, 0], 0, 0xb02a4c, 1],
      [[0.08, 0.42, 0.05], [0.07, 0.5, 0], -0.35, 0x5bb04a], [[0.08, 0.38, 0.05], [-0.07, 0.48, 0.02], 0.4, 0x4fa040],
      [[0.07, 0.34, 0.05], [0, 0.47, -0.06], 0.05, 0x68bc55]] },
    lettuce: { step: 1.5, parts: [
      [[0.4, 0.3, 0.4], [0, 0.17, 0], 0, 0x8fd456], [[0.5, 0.12, 0.2], [0, 0.1, 0.18], 0, 0x9be05a],
      [[0.5, 0.12, 0.2], [0, 0.1, -0.18], 0, 0x9be05a], [[0.2, 0.12, 0.5], [0.18, 0.1, 0], 0, 0x7cc44a],
      [[0.2, 0.12, 0.5], [-0.18, 0.1, 0], 0, 0x7cc44a]] },
    other: { step: 1.0, parts: [[[0.1, 0.5, 0.1], [0, 0.25, 0], 0, 0x3f8f3a], [[0.3, 0.06, 0.14], [0, 0.45, 0], 0, 0x5fae4a]] },
  };
  function growth(b) { return b.st === "ready" ? 1 : b.ready != null ? clamp(b.age / (b.age + b.ready), 0.05, 1) : clamp(b.w / (meta.maxW[b.crop] || 1), 0.05, 1); }
  function layout(f) {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), c = new THREE.Color();
    const rq = new THREE.Quaternion(), plantM = new THREE.Matrix4(), partM = new THREE.Matrix4(), pq = new THREE.Quaternion(), v = new THREE.Vector3(), w = new THREE.Vector3();
    const UP = new THREE.Vector3(0, 1, 0), Z = new THREE.Vector3(0, 0, 1), TAN = new THREE.Color(0xb8a050);
    for (const id of ids) {
      const h = houses[id], list = f.b.filter((b) => b.c === id && b.st !== "harvested");
      const total = list.reduce((a, b) => a + b.area, 0) + f.c[id].free, usable = HD - 1;
      let z = -usable / 2, pi = 0, bi = 0, ci = 0, mi = 0;
      h.marks.forEach((mk) => (mk.visible = false));
      for (const b of list) {
        const d = (b.area / total) * usable, g = growth(b), crop = b.crop.split("_")[0];
        const qk = b.qual >= 0.85 ? 0 : b.qual >= 0.6 ? 0.4 : 0.75, model = MODELS[crop] || MODELS.other;
        m.compose(p.set(0, 0.2, z + d / 2), q, s.set(HW - 1.4, 0.3, Math.max(0.2, d - 0.25))); h.beds.setMatrixAt(bi++, m);
        const size = PLANT * (0.45 + 0.55 * g), late = clamp((g - 0.35) / 0.65, 0, 1), step = model.step;
        for (let x = -HW / 2 + 1.2; x <= HW / 2 - 1.2; x += step) for (let zz = z + step / 2; zz < z + d - 0.2; zz += step) {
          if (pi + model.parts.length > MAXV) break;
          const jit = ((x * 73 + zz * 131) % 1 + 1) % 1;                      // stable per-spot variety
          plantM.compose(p.set(x + (jit - 0.5) * 0.15, 0.35, zz), rq.setFromAxisAngle(UP, jit * 6.28), s.set(size, size * (0.85 + jit * 0.3), size));
          for (const [sz, ps, tilt, hex, lateOnly] of model.parts) {
            const k = lateOnly ? late : 1; if (k < 0.05) continue;
            partM.compose(v.set(...ps), pq.setFromAxisAngle(Z, tilt), w.set(sz[0] * k, sz[1] * k, sz[2] * k));
            h.plants.setMatrixAt(pi, m.multiplyMatrices(plantM, partM));
            c.set(hex).lerp(TAN, qk).offsetHSL(0, 0, (jit - 0.5) * 0.06); h.plants.setColorAt(pi++, c);
          }
        }
        if (b.st === "ready" && mi < 6) { const mk = h.marks[mi++]; mk.visible = true; mk.position.set(0, 2.2, z + d / 2); }
        if (b.q && ci < 12) for (const cx of [-2, 0, 2]) { if (ci >= 12) break; m.compose(p.set(cx, 0.6, z + d / 2), q, s.set(1, 1, 1)); h.crates.setMatrixAt(ci++, m); }
        z += d;
      }
      h.plants.count = pi; h.beds.count = bi; h.crates.count = ci;
      h.plants.instanceMatrix.needsUpdate = h.beds.instanceMatrix.needsUpdate = h.crates.instanceMatrix.needsUpdate = true;
      if (h.plants.instanceColor) h.plants.instanceColor.needsUpdate = true;
    }
  }

  // ---------------- people ----------------
  const SHIRTS = [0xe85d4a, 0x4a90e8, 0xf2b33d, 0x9b6be0, 0x3dbf8a, 0xe06aa8, 0xffffff, 0x8bc34a];
  function updateWorkers(f, hd, dt, speed) {
    while (workers.length < f.staff) {
      const i = workers.length, g = new THREE.Group();
      const body = box(0.5, 0.8, 0.35, lambert(SHIRTS[i % 8])); body.position.y = 0.75; g.add(body);
      const head = box(0.38, 0.38, 0.38, lambert(0xf0c8a0)); head.position.y = 1.35; g.add(head);
      const legs = box(0.45, 0.4, 0.3, lambert(0x2a2f3a)); legs.position.y = 0.2; g.add(legs);
      const crate = box(0.6, 0.35, 0.4, lambert(0xa0703c)); crate.position.set(0, 0.85, 0.35); g.add(crate);
      g.position.set(world.x0 - 8 - i, 0, HD / 2 + 3.2); scene.add(g); workers.push({ g, crate, i });
    }
    while (workers.length > f.staff) scene.remove(workers.pop().g);
    const on = hd >= meta.shift[0] && hd < meta.shift[1], task = f.tasks.find((k) => k.st !== "done");
    workers.forEach((w, i) => {
      let tx, tz, carry = false;
      if (!on) { tx = world.x0 - 10 - i * 1.2; tz = HD / 2 + 3.2; }
      else if (task && (task.kind === "harvest" || task.kind === "plant")) {
        const hid = ids.includes(task.target[0]) ? task.target[0] : ids.includes(task.target) ? task.target : ids[0];
        tx = houses[hid].cx - 3 + ((i * 1.7) % 6); tz = -4 + ((i * 2.3) % 8); carry = task.kind === "harvest";
      } else if (task && task.kind === "repair") { tx = ec.x - 1 + i; tz = 3.5; }
      else { tx = world.x0 + 8 + i * 4 + Math.sin(t * 0.3 + i) * 2; tz = HD / 2 + 3.2; }
      const p = w.g.position, dx = tx - p.x, dz = tz - p.z, d = Math.hypot(dx, dz), v = 6 * Math.min(speed, 4) * dt;
      if (d > 25) { p.x = tx; p.z = tz; } else if (d > 0.05) { p.x += (dx / d) * Math.min(v, d); p.z += (dz / d) * Math.min(v, d); w.g.rotation.y = Math.atan2(dx, dz); }
      p.y = d > 0.05 ? Math.abs(Math.sin(t * 10 + i)) * 0.12 : 0;
      w.crate.visible = carry; w.g.visible = p.x > world.x0 - 6;
    });
  }

  // ---------------- every frame ----------------
  function daylight(f, hd) {
    const clockK = hd > 8.3 && hd < 17 ? Math.sin(Math.PI * (hd - 8.3) / 8.7) : 0;
    return clamp(Math.max(clamp(clockK * 1.6, 0, 1) * 0.7, f.out.sun / 120), 0, 1);
  }
  function render(f, hf, dt, speed) {
    if (!ids.length) return;
    t += dt;
    const hd = hf % 24, day = daylight(f, hd), dark = 1 - day, h = Math.floor(hf);
    if (h !== lastHour) { layout(f); lastHour = h; }
    // sky and light
    const twi = (hd > 7 && hd < 10) || (hd > 15 && hd < 18) ? clamp(1 - Math.abs(day - 0.15) * 4, 0, 1) : 0;
    renderer.setClearColor(mixc("#0b1230", "#7fb2e0", day).lerp(col(0xf0a060), twi * 0.35));
    world.amb.intensity = 0.18 + day * 0.35; world.amb.color = mixc("#7080c0", "#ffffff", day);
    world.hemi.intensity = 0.15 + day * 0.35; world.sun.intensity = day * 0.85;
    const sunA = Math.PI * clamp((hd - 8.3) / 8.7, 0, 1); world.sun.position.set(-Math.cos(sunA) * 40, 10 + Math.sin(sunA) * 30, 25);
    const snowy = meta.snowAt[h] === 1; world.ground.material.color = col(snowy ? 0xdfe8ee : 0x3d5a3a);
    // houses
    for (const id of ids) {
      const H = houses[id], c = f.c[id], lampK = clamp(c.lamp / (meta.maxLamp[id] || 1), 0, 1);
      H.lampMat.color = col(lampK > 0.02 ? 0xffd25a : 0x3a3f48); H.coneMat.opacity = 0.1 * lampK; H.light.intensity = lampK * 1.4;
      H.screen.visible = !!c.screen;
      const open = clamp(c.vent / 100, 0, 1) * 0.7;
      for (const v of H.vents) v.rotation.z = -v.userData.side * (SLOPE - open);
      const cold = clamp((c.sp_night - 1 - c.t) / 6, 0, 0.3), hot = clamp((c.t - c.sp_day - 3) / 8, 0, 0.25);
      H.tint.material.color = col(cold > 0 ? 0x5aa0ff : 0xff5a3c); H.tint.material.opacity = Math.max(cold, hot);
      const hk = clamp(c.heat / (meta.maxHeat[id] || 1), 0, 1) * (0.85 + 0.15 * Math.sin(t * 4));
      H.pipeMat.emissive = mixc("#000000", "#ff4a20", hk);
      H.co2.geometry.setDrawRange(0, clamp(Math.round((c.co2 - 380) / 12), 0, 60)); H.co2.rotation.y = Math.sin(t * 0.2) * 0.02;
      H.marks.forEach((m, i) => { m.rotation.y = t * 2; m.position.y = 2.2 + Math.sin(t * 4 + i) * 0.2; });
    }
    // energy centre
    const e = f.ec, broken = f.faults.some((x) => !ids.includes(x.split(".")[0])), heatK = clamp(e.heat / (meta.maxHeatAll || 1), 0, 1);
    world.pipe.material.emissive = mixc("#000000", "#ff5a2a", heatK * 0.9);
    ec.winMat.color = col(dark > 0.4 ? 0xffd977 : 0x9cc8e0);
    ec.beacon.material.color = col(broken ? (Math.sin(t * 10) > 0 ? 0xff3b30 : 0x5a1410) : 0x5ee06a);
    if (e.chp > 0) ec.fan.rotation.z += dt * 20;
    const setTank = (tk, k) => { const hh = Math.max(0.01, (tk.h - 0.2) * k); tk.f.scale.y = hh; tk.f.position.y = 0.1 + hh / 2; };
    setTank(ec.buffer, clamp(e.buffer / (meta.maxBuffer || 1), 0, 1));
    const co2k = clamp(e.co2 / (meta.maxCO2 || 1), 0, 1); setTank(ec.co2, co2k);
    ec.co2.f.material.color = col(co2k < 0.15 && Math.sin(t * 6) > 0 ? 0xff5a4a : 0x7cc4ff);
    const flow = e.imp > 0.5 ? 1 : e.exp > 0.5 ? -1 : 0;
    ec.sparks.forEach((s, j) => { s.visible = !!flow; let k = (t * 0.5 + j / 4) % 1; if (flow < 0) k = 1 - k; s.position.copy(ec.wire[Math.round(k * 30)]); s.material.color = col(flow > 0 ? 0xffe066 : 0x7bd88f); });
    const rate = clamp(e.gas / 40, 0, 1) * dt * 14;
    for (const s of ec.smoke) {
      if (s.life >= 1 && Math.random() < rate) { s.life = 0; s.m.visible = true; s.m.position.copy(ec.chimneyTop); }
      if (s.life < 1) { s.life += dt * 0.35; s.m.position.y += dt * 2.2; s.m.position.x += dt * (0.6 + f.out.wind * 0.4); const sc = 1 + s.life * 2.5; s.m.scale.set(sc, sc, sc);
        s.m.material.opacity = 0.7 * (1 - s.life); s.m.material.color = col(dark > 0.5 ? 0x8a8a96 : 0xd8dae0); }
      else s.m.visible = false;
    }
    for (const s of ec.fault) {
      if (broken && s.life <= 0 && Math.random() < dt * 3) { s.life = 1; s.m.visible = true; s.m.position.set(ec.x + (rnd() - 0.5) * 4, 2.5, 2); s.v.set((rnd() - 0.5) * 4, 4 + rnd() * 3, (rnd() - 0.5) * 4); }
      if (s.life > 0) { s.life -= dt * 1.3; s.v.y -= 12 * dt; s.m.position.addScaledVector(s.v, dt); } else s.m.visible = false;
    }
    // truck on delivery
    world.truck.visible = false;
    for (const d of meta.deliveries) {
      const k = (hf - (d - 4)) / 7; if (k < 0 || k > 1) continue;
      const a = world.x0 - 20, stop = ec.x - 5, b = world.x0 + world.span + 20;
      world.truck.visible = true; world.truck.position.x = k < 0.4 ? lerp(a, stop, k / 0.4) : k < 0.65 ? stop : lerp(stop, b, (k - 0.65) / 0.35);
    }
    updateWorkers(f, hd, dt, speed);
    // snow or rain
    const snow = f.out.t <= 0.5 && f.out.rh >= 82, rain = !snow && f.out.rh >= 94, fl = world.flakes;
    fl.visible = snow || rain; fl.material.color = col(snow ? 0xffffff : 0x9cc0ff);
    if (fl.visible) { const a = fl.geometry.attributes.position, v = snow ? 3 : 18;
      for (let i = 0; i < a.count; i++) { let y = a.getY(i) - v * dt; if (y < 0) y += 22; a.setY(i, y); a.setX(i, a.getX(i) + f.out.wind * 0.15 * dt); }
      a.needsUpdate = true; }
    placeCamera(); resize();
    renderer.render(scene, camera);
    labels(f, dt);
  }

  function placeCamera() {
    const cx = world.x0 + world.span / 2, el = 0.6, d = 120, aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
    camera.position.set(cx + Math.sin(az) * Math.cos(el) * d, Math.sin(el) * d, Math.cos(az) * Math.cos(el) * d);
    camera.lookAt(cx, 2, 0);
    const halfW = (world.span * 0.52) / zoom, halfH = halfW / aspect;
    camera.left = -halfW; camera.right = halfW; camera.top = halfH; camera.bottom = -halfH; camera.updateProjectionMatrix();
  }
  function resize() {
    const w = Math.max(1, Math.round(canvas.clientWidth / PIX)), h = Math.max(1, Math.round(canvas.clientHeight / PIX));
    if (canvas.width !== w || canvas.height !== h) renderer.setSize(w, h, false);
  }

  // ---------------- HTML labels and speech bubbles ----------------
  const v3 = new THREE.Vector3();
  function toScreen(x, y, z) { v3.set(x, y, z).project(camera); return [(v3.x + 1) / 2 * canvas.clientWidth, (1 - v3.y) / 2 * canvas.clientHeight]; }
  function labels(f, dt) {
    for (const id of ids) {
      const H = houses[id], c = f.c[id], crop = (meta.compartments[id].crop || "").split("_")[0];
      const cls = c.t < c.sp_night - 1 ? "cold" : c.t > c.sp_day + 3 ? "hot" : "ok";
      const dmg = f.faults.filter((x) => x.startsWith(id + ".")).map((x) => x.split(".")[1].replace(/_/g, " ").toUpperCase());
      const html = `${id} ${crop.toUpperCase()} <b class="${cls}">${c.t.toFixed(1)}°</b>${dmg.length ? ` <b class="hot">⚠ ${dmg.join(" ")}</b>` : ""}`;
      if (H.lbl.innerHTML !== html) H.lbl.innerHTML = html;
      const [x, y] = toScreen(H.cx, 0, HD / 2 + 1.6); H.lbl.style.transform = `translate(${x}px, ${y}px) translate(-50%, 0)`;
    }
    const [ex, ey] = toScreen(ec.x + 2, 0, 5); ec.lbl.style.transform = `translate(${ex}px, ${ey}px) translate(-50%, 0)`;
    bubbles = bubbles.filter((b) => { b.life += dt; if (b.life > 3.2) { b.el.remove(); return false; }
      const [x, y] = toScreen(...b.at); b.el.style.transform = `translate(${x}px, ${y - b.lvl * 26 - Math.min(b.life, 0.3) * 30}px) translate(-50%, -100%)`;
      b.el.style.opacity = b.life > 2.7 ? (3.2 - b.life) / 0.5 : 1; return true; });
  }
  function bubble(where, msg, color) {
    if (!ids.length) return;
    let at;
    if (houses[where]) at = [houses[where].cx, WALL + RIDGE + 0.5, 0];
    else if (where === "co2") at = [ec.x + 8.4, 5, -1]; else if (where === "road") at = [ec.x - 5, 3, ROAD_Z]; else at = [ec.x, 6, -1];
    const lvl = bubbles.filter((b) => b.at[0] === at[0] && b.life < 3).length;
    const el = document.createElement("div"); el.className = "bubble"; el.textContent = msg.toUpperCase(); el.style.borderColor = color; el.style.color = color;
    layerLbl.appendChild(el); bubbles.push({ el, at, lvl, life: 0 });
    while (bubbles.length > 6) bubbles.shift().el.remove();
  }

  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(e) {
    const r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const targets = [...ids.map((id) => houses[id].hit), ec.hit].filter(Boolean);
    const hit = ray.intersectObjects(targets, false)[0];
    return hit ? hit.object.userData.pick : "weather";
  }
  function reset() { bubbles.forEach((b) => b.el.remove()); bubbles = []; }
  return { init, setData, render, bubble, reset };
})();
