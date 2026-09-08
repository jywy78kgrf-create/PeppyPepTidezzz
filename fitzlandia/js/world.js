/* FitzLandia — world.js
   Renderer, scene, sky, city backdrop, park ground, camera controls, geometry helpers. */
'use strict';

const CELL = 4;        // world units per grid cell
const RISE = 2;        // world units per track level
const MAX_LEVEL = 12;  // highest track level
const MAX_PARK = 44;   // largest park (cells per side)
const UP = new THREE.Vector3(0, 1, 0);
const DIRS = [ {x:1,z:0}, {x:0,z:1}, {x:-1,z:0}, {x:0,z:-1} ]; // heading 0..3 = E,S,W,N

const World = {
  scene: null, camera: null, renderer: null,
  parkCells: 20,
  parkGroup: null, grid: null, fence: null, gate: null, grass: null,
  city: null, clouds: [], cars: [], balloons: [], animated: [],
  cam: { target: new THREE.Vector3(0, 0, 0), az: 0.7, pol: 0.95, dist: 60 },
  rideCam: null,        // {ride, vehicle} when following a vehicle
  sun: null,
};

// ---------- canvas texture helpers ----------
function canvasTex(w, h, draw, opts = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d'); draw(ctx, w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  if (opts.repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(opts.repeat[0], opts.repeat[1]); }
  t.anisotropy = 4;
  return t;
}
function grassTexture() {
  return canvasTex(256, 256, (ctx, w, h) => {
    ctx.fillStyle = '#5fb84a'; ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 2600; i++) {
      const g = 150 + Math.random() * 60, r = 70 + Math.random() * 50;
      ctx.fillStyle = `rgb(${r|0},${g|0},${(40 + Math.random()*40)|0})`;
      ctx.fillRect(Math.random() * w, Math.random() * h, 2 + Math.random() * 3, 2 + Math.random() * 3);
    }
  }, { repeat: [1, 1] });
}
function pavementTexture() {
  return canvasTex(128, 128, (ctx, w, h) => {
    ctx.fillStyle = '#d9c9a8'; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#c4b28f'; ctx.lineWidth = 3;
    for (let i = 0; i <= 4; i++) { ctx.beginPath(); ctx.moveTo(i * 32, 0); ctx.lineTo(i * 32, h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i * 32); ctx.lineTo(w, i * 32); ctx.stroke(); }
  }, { repeat: [1, 1] });
}
function windowsTexture(tint) {
  return canvasTex(64, 128, (ctx, w, h) => {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
    for (let y = 4; y < h; y += 12) for (let x = 4; x < w; x += 12) {
      const lit = Math.random() < 0.55;
      ctx.fillStyle = lit ? tint : '#0c1220';
      ctx.fillRect(x, y, 7, 7);
    }
  }, { repeat: [1, 1] });
}
function textTexture(text, opts = {}) {
  const w = opts.w || 512, h = opts.h || 128;
  return canvasTex(w, h, (ctx) => {
    ctx.fillStyle = opts.bg || '#ffffff';
    roundRect(ctx, 0, 0, w, h, 24); ctx.fill();
    if (opts.border) { ctx.lineWidth = 12; ctx.strokeStyle = opts.border; roundRect(ctx, 6, 6, w - 12, h - 12, 20); ctx.stroke(); }
    ctx.fillStyle = opts.color || '#222';
    ctx.font = `bold ${opts.size || 64}px "Fredoka", "Arial Rounded MT Bold", Arial, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, w / 2, h / 2 + 4);
  });
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h); ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
}
function stripeTexture(c1, c2) {
  return canvasTex(64, 64, (ctx, w, h) => {
    for (let i = 0; i < 8; i++) { ctx.fillStyle = i % 2 ? c1 : c2; ctx.fillRect(i * 8, 0, 8, h); }
  }, { repeat: [2, 1] });
}

// ---------- geometry helpers ----------
/** Sweep a 2D profile (array of [side, up]) along frames [{p,t,n,b}] -> BufferGeometry (flat-shaded per segment). */
function sweepGeometry(frames, profile, closed) {
  const pos = [], nor = [], uv = [], idx = [];
  const nF = frames.length, nS = profile.length - 1;
  const tmpN = new THREE.Vector3();
  const along = [0]; for (let i = 1; i < nF; i++) along.push(along[i - 1] + frames[i].p.distanceTo(frames[i - 1].p));
  for (let k = 0; k < nS; k++) {
    const a = profile[k], b = profile[k + 1];
    // 2D outward normal of segment (perpendicular)
    const ex = b[0] - a[0], ey = b[1] - a[1], len = Math.hypot(ex, ey) || 1;
    const nx = -ey / len, ny = ex / len; // outward for a clockwise (side, up) profile; consistent with the CCW winding below
    const base = pos.length / 3;
    for (let i = 0; i < nF; i++) {
      const f = frames[i];
      tmpN.set(0, 0, 0).addScaledVector(f.n, nx).addScaledVector(f.b, ny);
      for (const pt of [a, b]) {
        pos.push(f.p.x + f.n.x * pt[0] + f.b.x * pt[1], f.p.y + f.n.y * pt[0] + f.b.y * pt[1], f.p.z + f.n.z * pt[0] + f.b.z * pt[1]);
        nor.push(tmpN.x, tmpN.y, tmpN.z);
        uv.push(along[i] / 4, pt === a ? k / nS : (k + 1) / nS);
      }
    }
    const count = closed ? nF : nF - 1;
    for (let i = 0; i < count; i++) {
      const j = (i + 1) % nF;
      const a0 = base + i * 2, a1 = a0 + 1, b0 = base + j * 2, b1 = b0 + 1;
      idx.push(a0, b0, a1, a1, b0, b1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

// ---------- water (shared, animated) ----------
const Water = { map: null, normal: null };
function waterTextures() {
  if (Water.map) return Water;
  Water.map = canvasTex(256, 256, (ctx, w, h) => {
    ctx.fillStyle = '#9fe4ff'; ctx.fillRect(0, 0, w, h);
    // soft caustic streaks
    for (let i = 0; i < 70; i++) {
      ctx.strokeStyle = `rgba(255,255,255,${0.10 + Math.random() * 0.25})`; ctx.lineWidth = 1 + Math.random() * 3;
      ctx.beginPath(); const x = Math.random() * w, y = Math.random() * h; ctx.moveTo(x, y);
      ctx.bezierCurveTo(x + 40 - Math.random() * 80, y + 30, x + 60, y - 30 + Math.random() * 60, x + 90 - Math.random() * 40, y + 10); ctx.stroke();
    }
    for (let i = 0; i < 40; i++) { ctx.fillStyle = `rgba(60,170,230,${Math.random() * 0.25})`; ctx.beginPath(); ctx.ellipse(Math.random() * w, Math.random() * h, 8 + Math.random() * 30, 4 + Math.random() * 10, Math.random() * 3, 0, 6.3); ctx.fill(); }
  }, { repeat: [1, 1] });
  // ripple normal map from a sum of sines
  const N = 128, c = document.createElement('canvas'); c.width = N; c.height = N; const ctx = c.getContext('2d'); const img = ctx.createImageData(N, N);
  const hgt = (x, y) => Math.sin(x * 0.25 + y * 0.1) * 0.5 + Math.sin(y * 0.33 - x * 0.07) * 0.35 + Math.sin((x + y) * 0.15) * 0.25;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const dx = hgt((x + 1) % N, y) - hgt((x - 1 + N) % N, y), dy = hgt(x, (y + 1) % N) - hgt(x, (y - 1 + N) % N);
    const nx = -dx * 1.4, ny = -dy * 1.4, nz = 1; const l = Math.hypot(nx, ny, nz);
    const o = (y * N + x) * 4; img.data[o] = (nx / l * 0.5 + 0.5) * 255; img.data[o + 1] = (ny / l * 0.5 + 0.5) * 255; img.data[o + 2] = (nz / l * 0.5 + 0.5) * 255; img.data[o + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  Water.normal = new THREE.CanvasTexture(c); Water.normal.wrapS = Water.normal.wrapT = THREE.RepeatWrapping;
  return Water;
}
/** A translucent, rippling light-blue water material. `flow` scales the scrolling speed. */
function waterMaterial(opts = {}) {
  const w = waterTextures();
  const m = new THREE.MeshStandardMaterial({ color: opts.color || 0xbdf0ff, map: w.map, normalMap: w.normal, normalScale: new THREE.Vector2(0.55, 0.55),
    roughness: 0.08, metalness: 0.12, transparent: true, opacity: opts.opacity || 0.72, side: THREE.DoubleSide, depthWrite: false });
  return m;
}
function animateWater(dt) {
  const w = Water; if (!w.map) return;
  w.map.offset.x -= dt * 0.35; w.normal.offset.x -= dt * 0.25; w.normal.offset.y += dt * 0.05;
}

/** Merge many boxes (with per-box color and UV scaled to size) into one geometry. */
function mergedBoxes(boxes) {
  const pos = [], nor = [], uv = [], col = [], idx = [];
  const faces = [
    { n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0] }, { n: [-1, 0, 0], u: [0, 0, 1], v: [0, 1, 0] },
    { n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1] }, { n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1] },
    { n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] }, { n: [0, 0, -1], u: [-1, 0, 0], v: [0, 1, 0] },
  ];
  const c = new THREE.Color();
  for (const b of boxes) {
    c.set(b.color);
    const hw = b.w / 2, hh = b.h / 2, hd = b.d / 2;
    for (const f of faces) {
      const base = pos.length / 3;
      const su = Math.abs(f.u[0]) * b.w + Math.abs(f.u[1]) * b.h + Math.abs(f.u[2]) * b.d;
      const sv = Math.abs(f.v[0]) * b.w + Math.abs(f.v[1]) * b.h + Math.abs(f.v[2]) * b.d;
      const uvS = b.uvScale || 1;
      for (let k = 0; k < 4; k++) {
        const a = (k === 1 || k === 2) ? 1 : -1, bb = (k >= 2) ? 1 : -1;
        const x = f.n[0] * hw + f.u[0] * a * hw + f.v[0] * bb * hw;
        const y = f.n[1] * hh + f.u[1] * a * hh + f.v[1] * bb * hh;
        const z = f.n[2] * hd + f.u[2] * a * hd + f.v[2] * bb * hd;
        pos.push(b.x + x, b.y + y, b.z + z);
        nor.push(f.n[0], f.n[1], f.n[2]);
        uv.push((a + 1) / 2 * su * uvS, (bb + 1) / 2 * sv * uvS);
        col.push(c.r, c.g, c.b);
      }
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  return g;
}

function disposeObject(obj) {
  obj.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) { const ms = Array.isArray(o.material) ? o.material : [o.material]; ms.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); }); }
  });
  if (obj.parent) obj.parent.remove(obj);
}

// ---------- world init ----------
function initWorld(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  World.renderer = renderer;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x8ed0ff);
  scene.fog = new THREE.Fog(0xbfe3ff, 160, 520);
  World.scene = scene;

  const camera = new THREE.PerspectiveCamera(50, 1, 0.5, 1500);
  World.camera = camera;

  scene.add(new THREE.HemisphereLight(0xcfe9ff, 0x5c8f3a, 0.75));
  const sun = new THREE.DirectionalLight(0xfff1d6, 1.7);
  sun.position.set(90, 140, 70);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const sc = sun.shadow.camera; sc.left = -110; sc.right = 110; sc.top = 110; sc.bottom = -110; sc.near = 20; sc.far = 400;
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.02;
  scene.add(sun); scene.add(sun.target);
  World.sun = sun;

  buildSky();
  buildCityGround();
  buildMountains();
  buildClouds();
  buildCity();
  buildRoad();
  buildBalloons();

  World.parkGroup = new THREE.Group(); scene.add(World.parkGroup);
  rebuildPark();

  resize();
  window.addEventListener('resize', resize);
  return renderer;
}

function resize() {
  const r = World.renderer, w = window.innerWidth, h = window.innerHeight;
  r.setSize(w, h, false);
  World.camera.aspect = w / h; World.camera.updateProjectionMatrix();
}

function buildSky() {
  const geo = new THREE.SphereGeometry(1300, 24, 12);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x3d8fe8) }, mid: { value: new THREE.Color(0x8ed0ff) }, bot: { value: new THREE.Color(0xe6f4ff) } },
    vertexShader: `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `uniform vec3 top, mid, bot; varying vec3 vP; void main(){ float h = normalize(vP).y; vec3 c = h < 0.0 ? bot : (h < 0.25 ? mix(bot, mid, h/0.25) : mix(mid, top, (h-0.25)/0.75)); gl_FragColor = vec4(c,1.0); }`
  });
  const sky = new THREE.Mesh(geo, mat); sky.renderOrder = -10; World.scene.add(sky);
  // sun disc
  const sunTex = canvasTex(128, 128, (ctx, w, h) => {
    const g = ctx.createRadialGradient(w/2, h/2, 6, w/2, h/2, 64);
    g.addColorStop(0, 'rgba(255,250,220,1)'); g.addColorStop(0.35, 'rgba(255,240,180,0.9)'); g.addColorStop(1, 'rgba(255,230,150,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  });
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: sunTex, transparent: true, fog: false, depthWrite: false }));
  sp.position.set(500, 620, 380); sp.scale.set(260, 260, 1); World.scene.add(sp);
}

function buildCityGround() {
  const g = new THREE.PlaneGeometry(2600, 2600);
  const m = new THREE.MeshLambertMaterial({ color: 0x6e7a6a });
  const ground = new THREE.Mesh(g, m); ground.rotation.x = -Math.PI / 2; ground.position.y = -0.05; ground.receiveShadow = true;
  World.scene.add(ground);
}

function buildMountains() {
  const grp = new THREE.Group();
  const mat = new THREE.MeshLambertMaterial({ color: 0x7fa8c9, flatShading: true });
  const snow = new THREE.MeshLambertMaterial({ color: 0xf4f8ff, flatShading: true });
  for (let i = 0; i < 26; i++) {
    const a = (i / 26) * Math.PI * 2 + Math.random() * 0.2;
    const r = 720 + Math.random() * 140, h = 120 + Math.random() * 200, w = 120 + Math.random() * 120;
    const m = new THREE.Mesh(new THREE.ConeGeometry(w, h, 6), mat);
    m.position.set(Math.cos(a) * r, h / 2 - 4, Math.sin(a) * r); m.rotation.y = Math.random() * Math.PI;
    grp.add(m);
    if (h > 220) { const s = new THREE.Mesh(new THREE.ConeGeometry(w * 0.32, h * 0.32, 6), snow); s.position.copy(m.position); s.position.y = h - h * 0.16 - 4; s.rotation.y = m.rotation.y; grp.add(s); }
  }
  World.scene.add(grp);
}

function buildClouds() {
  const tex = canvasTex(256, 128, (ctx, w, h) => {
    ctx.fillStyle = 'rgba(255,255,255,0)'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    const blobs = [[70, 80, 40], [120, 60, 50], [170, 78, 42], [100, 88, 34], [145, 90, 36]];
    for (const [x, y, r] of blobs) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); }
  });
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0.95 });
  for (let i = 0; i < 18; i++) {
    const s = new THREE.Sprite(mat);
    const sc = 60 + Math.random() * 80;
    s.scale.set(sc, sc * 0.5, 1);
    s.position.set((Math.random() - 0.5) * 1400, 150 + Math.random() * 120, (Math.random() - 0.5) * 1400);
    s.userData.speed = 1.5 + Math.random() * 2;
    World.scene.add(s); World.clouds.push(s);
  }
}

function buildCity() {
  const boxes = [], glassBoxes = [];
  const palettes = [0xc9d3dc, 0xb8c5d1, 0xe3d7c3, 0xd7b9a3, 0xa9b6c7, 0xf0e6d8, 0x9fb0c2, 0xd9c7b6];
  const minR = MAX_PARK * CELL / 2 + 26; // stays outside the largest park
  const rnd = mulberry(1234);
  for (let gx = -14; gx <= 14; gx++) for (let gz = -14; gz <= 14; gz++) {
    const x = gx * 24 + (rnd() - 0.5) * 6, z = gz * 24 + (rnd() - 0.5) * 6;
    const d = Math.hypot(x, z);
    if (d < minR) continue;
    if (d > 360) continue;
    if (rnd() < 0.12) continue; // parks / gaps
    const near = Math.max(0, 1 - (d - minR) / 200);
    let h = 8 + rnd() * 18 + rnd() * rnd() * 70 * (0.4 + near);
    if (rnd() < 0.08) h += 60 + rnd() * 60; // skyscrapers
    const w = 9 + rnd() * 9, dd = 9 + rnd() * 9;
    const color = palettes[(rnd() * palettes.length) | 0];
    const glass = rnd() < 0.3;
    (glass ? glassBoxes : boxes).push({ x, y: h / 2, z, w, h, d: dd, color: glass ? 0x6fa6d8 : color, uvScale: 1 / 12 });
    // rooftop details
    if (rnd() < 0.5) boxes.push({ x: x + (rnd() - 0.5) * w * 0.4, y: h + 1.5, z: z + (rnd() - 0.5) * dd * 0.4, w: 3, h: 3, d: 3, color: 0x8a949c, uvScale: 0 });
    if (h > 90) boxes.push({ x, y: h + 10, z, w: 0.8, h: 20, d: 0.8, color: 0xdddddd, uvScale: 0 });
  }
  const winTex = windowsTexture('#ffe9a8');
  const winTex2 = windowsTexture('#bfe8ff');
  const m1 = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, metalness: 0.05, emissiveMap: winTex, emissive: new THREE.Color(0x665533), emissiveIntensity: 0.9, map: winTex, });
  // building walls: map darkens with windows; use a lighter blend by tinting via vertex colors
  m1.map = null;
  const m2 = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.3, metalness: 0.5, emissiveMap: winTex2, emissive: new THREE.Color(0x335566), emissiveIntensity: 0.8 });
  const c1 = new THREE.Mesh(mergedBoxes(boxes), m1); c1.castShadow = false; c1.receiveShadow = true;
  const c2 = new THREE.Mesh(mergedBoxes(glassBoxes), m2);
  const grp = new THREE.Group(); grp.add(c1, c2);
  World.scene.add(grp); World.city = grp;
}

function buildRoad() {
  const R = MAX_PARK * CELL / 2 + 14;
  const ring = new THREE.Mesh(new THREE.RingGeometry(R - 5, R + 5, 96), new THREE.MeshLambertMaterial({ color: 0x3f4448 }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.02; ring.receiveShadow = true; World.scene.add(ring);
  const dash = new THREE.Mesh(new THREE.RingGeometry(R - 0.25, R + 0.25, 96), new THREE.MeshBasicMaterial({ color: 0xf7e26b }));
  dash.rotation.x = -Math.PI / 2; dash.position.y = 0.03; World.scene.add(dash);
  const colors = [0xff4d4d, 0x4da6ff, 0xffd84d, 0x66e07a, 0xffffff, 0xff9f43];
  for (let i = 0; i < 14; i++) {
    const car = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(3.2, 1.1, 1.7), new THREE.MeshStandardMaterial({ color: colors[i % colors.length], roughness: 0.4 }));
    body.position.y = 0.75; car.add(body);
    const top = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.8, 1.5), new THREE.MeshStandardMaterial({ color: 0x9bd2ff, roughness: 0.2 }));
    top.position.set(-0.1, 1.65, 0); car.add(top);
    car.userData = { a: Math.random() * Math.PI * 2, r: R + (i % 2 ? 2.6 : -2.6), speed: (i % 2 ? 1 : -1) * (0.05 + Math.random() * 0.03) };
    World.scene.add(car); World.cars.push(car);
  }
}

function buildBalloons() {
  const colors = [0xff5a5a, 0x5ab4ff, 0xffd95a, 0x7ee36b, 0xff7ad9];
  for (let i = 0; i < 6; i++) {
    const b = new THREE.Mesh(new THREE.SphereGeometry(1.2, 12, 10), new THREE.MeshStandardMaterial({ color: colors[i % colors.length], roughness: 0.3 }));
    b.scale.y = 1.25;
    b.position.set((Math.random() - 0.5) * 120, 10 + Math.random() * 40, (Math.random() - 0.5) * 120);
    b.userData = { vy: 1 + Math.random(), wob: Math.random() * 10 };
    World.scene.add(b); World.balloons.push(b);
  }
}

function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

// ---------- park (grass, fence, gate, grid) ----------
function parkHalf() { return World.parkCells * CELL / 2; }
function inPark(cx, cz) { const n = World.parkCells / 2; return cx >= -n && cx < n && cz >= -n && cz < n; }
function cellCenter(cx, cz) { return new THREE.Vector3((cx + 0.5) * CELL, 0, (cz + 0.5) * CELL); }

function rebuildPark() {
  const g = World.parkGroup;
  while (g.children.length) disposeObject(g.children[0]);
  const size = World.parkCells * CELL, half = size / 2;
  const grass = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshStandardMaterial({ map: grassTexture(), roughness: 1 }));
  grass.material.map.repeat.set(World.parkCells / 2, World.parkCells / 2);
  grass.rotation.x = -Math.PI / 2; grass.position.y = 0.0; grass.receiveShadow = true; grass.name = 'grass';
  g.add(grass); World.grass = grass;
  // main path down the middle from the gate
  const path = new THREE.Mesh(new THREE.PlaneGeometry(CELL * 1.6, size), new THREE.MeshStandardMaterial({ map: pavementTexture(), roughness: 1 }));
  path.material.map.repeat.set(1.6, World.parkCells); path.rotation.x = -Math.PI / 2; path.position.y = 0.01; g.add(path);
  // fence
  const posts = [], rails = [];
  const postMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.8 });
  const n = World.parkCells * 2;
  const step = size / n;
  for (let i = 0; i <= n; i++) {
    const t = -half + i * step;
    for (const [x, z] of [[t, -half], [t, half], [-half, t], [half, t]]) {
      if (z === half && Math.abs(x) < CELL * 1.2) continue; // gate opening
      posts.push({ x, y: 0.6, z, w: 0.25, h: 1.2, d: 0.25, color: 0xffffff });
    }
  }
  for (const [x, z, w, d] of [[0, -half, size, 0.12], [-half, 0, 0.12, size], [half, 0, 0.12, size]]) rails.push({ x, y: 0.9, z, w, h: 0.12, d, color: 0xffffff }, { x, y: 0.45, z, w, h: 0.12, d, color: 0xffffff });
  const gw = CELL * 1.2; const sideLen = half - gw;
  rails.push({ x: -half + sideLen / 2, y: 0.9, z: half, w: sideLen, h: 0.12, d: 0.12, color: 0xffffff }, { x: half - sideLen / 2, y: 0.9, z: half, w: sideLen, h: 0.12, d: 0.12, color: 0xffffff });
  const fence = new THREE.Mesh(mergedBoxes(posts.concat(rails)), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8 }));
  fence.castShadow = true; g.add(fence); World.fence = fence;
  // gate arch with sign
  const gate = new THREE.Group();
  const pillarMat = new THREE.MeshStandardMaterial({ color: 0xff5f8f, roughness: 0.6 });
  for (const s of [-1, 1]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.9, 7, 12), pillarMat); p.position.set(s * (gw + 0.5), 3.5, half); p.castShadow = true; gate.add(p);
    const ball = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 10), new THREE.MeshStandardMaterial({ color: 0xffd93d, roughness: 0.3 })); ball.position.set(s * (gw + 0.5), 7.4, half); gate.add(ball); }
  const sign = new THREE.Mesh(new THREE.BoxGeometry(gw * 2 + 3, 2.4, 0.6), new THREE.MeshStandardMaterial({ color: 0xffffff }));
  sign.position.set(0, 6.8, half); sign.castShadow = true; gate.add(sign);
  const signTex = textTexture('🎡 FitzLandia 🎢', { bg: '#fff7e0', color: '#ff3d7f', border: '#ffd93d', size: 76, w: 768, h: 160 });
  const signFace = new THREE.Mesh(new THREE.PlaneGeometry(gw * 2 + 2.6, 2.2), new THREE.MeshBasicMaterial({ map: signTex }));
  signFace.position.set(0, 6.8, half + 0.32); gate.add(signFace);
  const signBack = signFace.clone(); signBack.position.z = half - 0.32; signBack.rotation.y = Math.PI; gate.add(signBack);
  g.add(gate); World.gate = gate;
  // build grid overlay
  const grid = new THREE.GridHelper(size, World.parkCells, 0xffffff, 0xffffff);
  grid.material.opacity = 0.25; grid.material.transparent = true; grid.position.y = 0.04; grid.visible = false;
  g.add(grid); World.grid = grid;
  // shadow camera covers park
  const sc = World.sun.shadow.camera; const ext = half + 12; sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.updateProjectionMatrix();
}

// ---------- camera ----------
function updateCameraTransform() {
  const c = World.cam, cam = World.camera;
  if (World.customCam) { World.customCam(); return; }
  if (World.rideCam && World.rideCam.vehicle) {
    const v = World.rideCam.vehicle; const f = v.frontFrame;
    if (f) {
      const eye = f.p.clone().addScaledVector(f.b, 1.1).addScaledVector(f.t, 1.6);
      const look = f.p.clone().addScaledVector(f.t, 10).addScaledVector(f.b, 0.6);
      cam.position.lerp(eye, 0.35);
      const m = new THREE.Matrix4().lookAt(cam.position, look, f.b);
      const q = new THREE.Quaternion().setFromRotationMatrix(m); cam.quaternion.slerp(q, 0.3);
      return;
    }
  }
  const lim = parkHalf() + 40;
  c.target.x = THREE.MathUtils.clamp(c.target.x, -lim, lim); c.target.z = THREE.MathUtils.clamp(c.target.z, -lim, lim);
  c.pol = THREE.MathUtils.clamp(c.pol, 0.2, 1.45); c.dist = THREE.MathUtils.clamp(c.dist, 10, 240);
  const x = c.target.x + c.dist * Math.sin(c.pol) * Math.sin(c.az);
  const y = c.target.y + c.dist * Math.cos(c.pol);
  const z = c.target.z + c.dist * Math.sin(c.pol) * Math.cos(c.az);
  cam.position.set(x, Math.max(y, 2), z); cam.up.set(0, 1, 0); cam.lookAt(c.target);
}

function focusCamera(x, z, dist) {
  World.cam.target.set(x, 0, z);
  if (dist) World.cam.dist = dist;
}

/** Screen point -> ground plane (y=0) world point, or null. */
const _ray = new THREE.Raycaster(); const _plane = new THREE.Plane(UP, 0); const _v2 = new THREE.Vector2();
function screenToGround(px, py) {
  _v2.set((px / window.innerWidth) * 2 - 1, -(py / window.innerHeight) * 2 + 1);
  _ray.setFromCamera(_v2, World.camera);
  const out = new THREE.Vector3();
  return _ray.ray.intersectPlane(_plane, out) ? out : null;
}
function screenRay(px, py) {
  _v2.set((px / window.innerWidth) * 2 - 1, -(py / window.innerHeight) * 2 + 1);
  _ray.setFromCamera(_v2, World.camera);
  return _ray;
}

/** Pointer / touch controls */
function initControls(canvas, onTap) {
  const pts = new Map();
  let dragging = false, start = null, lastMid = null, lastDist = 0, startTime = 0;
  const c = World.cam;
  canvas.addEventListener('pointerdown', e => {
    canvas.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY, btn: e.button, shift: e.shiftKey });
    if (pts.size === 1) { start = { x: e.clientX, y: e.clientY }; dragging = false; startTime = performance.now(); }
    if (pts.size === 2) { const [a, b] = [...pts.values()]; lastMid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; lastDist = Math.hypot(a.x - b.x, a.y - b.y); dragging = true; }
  });
  canvas.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    const p = pts.get(e.pointerId); const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY;
    if (pts.size === 1) {
      if (!dragging && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 8) dragging = true;
      if (dragging) {
        if (World.dragHook && World.dragHook(dx, dy)) { /* consumed (walk look) */ }
        else if (p.btn === 2 || p.shift) panCamera(dx, dy); else { c.az -= dx * 0.006; c.pol -= dy * 0.005; }
      }
    } else if (pts.size === 2 && !World.dragHook) {
      const [a, b] = [...pts.values()]; const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (lastMid) panCamera(mid.x - lastMid.x, mid.y - lastMid.y);
      if (lastDist) c.dist *= lastDist / d;
      lastMid = mid; lastDist = d;
    }
  });
  const end = e => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pts.size === 0) {
      if (!dragging && performance.now() - startTime < 600) onTap(e.clientX, e.clientY);
      dragging = false; lastMid = null; lastDist = 0;
    } else { lastMid = null; lastDist = 0; }
  };
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('wheel', e => { e.preventDefault(); if (!World.dragHook) c.dist *= Math.exp(e.deltaY * 0.0012); }, { passive: false });
  canvas.addEventListener('contextmenu', e => e.preventDefault());
}
function panCamera(dx, dy) {
  const c = World.cam; const k = c.dist * 0.0016;
  const fx = Math.sin(c.az), fz = Math.cos(c.az); // camera->target direction on ground (reversed)
  // right vector
  const rx = fz, rz = -fx;
  c.target.x -= (rx * dx + (-fx) * dy) * k; c.target.z -= (rz * dx + (-fz) * dy) * k;
}

// ---------- ambient animation ----------
function animateWorld(dt, t) {
  animateWater(dt);
  for (const s of World.clouds) { s.position.x += s.userData.speed * dt; if (s.position.x > 750) s.position.x = -750; }
  for (const car of World.cars) { const u = car.userData; u.a += u.speed * dt; car.position.set(Math.cos(u.a) * u.r, 0, Math.sin(u.a) * u.r); car.rotation.y = -u.a + (u.speed > 0 ? Math.PI : 0); }
  for (const b of World.balloons) { const u = b.userData; b.position.y += u.vy * dt; b.position.x += Math.sin(t * 0.5 + u.wob) * dt * 1.2; if (b.position.y > 90) { b.position.y = 6; b.position.x = (Math.random() - 0.5) * 120; b.position.z = (Math.random() - 0.5) * 120; } }
}
