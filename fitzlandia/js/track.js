/* FitzLandia — track.js
   Track pieces, Ride class (building rules), path sampling, track meshes, vehicles and physics. */
'use strict';

const PIECES = {
  station:  { name: 'Station',    icon: '🏠', cost: 0,  dl: 0,  turn: 0, station: true },
  straight: { name: 'Straight',   icon: '➡️', cost: 10, dl: 0,  turn: 0 },
  up:       { name: 'Hill Up',    icon: '↗️', cost: 20, dl: 1,  turn: 0 },
  down:     { name: 'Drop',       icon: '↘️', cost: 20, dl: -1, turn: 0 },
  bigdrop:  { name: 'Big Drop',   icon: '⬇️', cost: 35, dl: -2, turn: 0 },
  left:     { name: 'Turn Left',  icon: '↩️', cost: 15, dl: 0,  turn: -1 },
  right:    { name: 'Turn Right', icon: '↪️', cost: 15, dl: 0,  turn: 1 },
  lift:     { name: 'Chain Lift', icon: '⛓️', cost: 30, dl: 1,  turn: 0, lift: true },
  loop:     { name: 'Loop',       icon: '➰', cost: 80, dl: 0,  turn: 0, cells: 1, hgt: 3, inversion: true, minSpeed: 12, samples: 56 },
  corkscrew:{ name: 'Corkscrew',  icon: '🌪️', cost: 70, dl: 0,  turn: 0, cells: 2, hgt: 2, inversion: true, minSpeed: 9,  samples: 44 },
  conveyor: { name: 'Conveyor',   icon: '🔼', cost: 30, dl: 1,  turn: 0, lift: true, water: true },
  splash:   { name: 'Splash Pool',icon: '💦', cost: 40, dl: 0,  turn: 0, splash: true, water: true },
};
const COASTER_PIECES = ['lift', 'straight', 'up', 'down', 'bigdrop', 'left', 'right', 'loop', 'corkscrew'];
const LOOP_R = 2.6, LOOP_A = 2.0, CORK_R = 1.5;
const WATER_PIECES = ['conveyor', 'straight', 'up', 'down', 'bigdrop', 'left', 'right', 'splash'];

// Physics rules (the "laws of FitzLandia")
const PHYS = {
  g: 9.8,
  liftSpeed: 4.5,      // chain lift / conveyor speed
  launch: 4.0,         // speed leaving the station
  stationBrake: 5.0,   // max speed inside the station
  turnMax: 13.0,       // faster than this on a turn = cars fly off
  flow: 2.6,           // water current speed on flat/down water pieces
  muCoaster: 0.012,    // rolling friction
  muWater: 0.03,       // water drag on flat
  drag: 0.0015,        // air drag ~ v^2
  loadTime: 4.0,       // seconds stopped at station when open
};

const RIDE_COLORS = [0xff3d6e, 0xff8c1a, 0xffd11a, 0x2ecc71, 0x1e90ff, 0x9b59b6];

let _rideId = 1;
class Ride {
  constructor(type, cx, cz, heading, color) {
    this.id = _rideId++;
    this.type = type;              // 'coaster' | 'water'
    this.color = color || RIDE_COLORS[(Math.random() * RIDE_COLORS.length) | 0];
    this.name = type === 'coaster' ? 'New Coaster' : 'New Water Ride';
    this.pieces = [{ type: 'station', cx, cz, h: heading, l0: 0, l1: 0 }];
    this.open = false; this.stars = 0; this.stats = null;
    this.group = new THREE.Group(); this.group.userData.ride = this;
    this.vehicle = null; this.path = null;
    this.queue = []; this.riders = []; this.earned = 0; this.ridersServed = 0;
    this.stationMesh = null;
  }
  get station() { return this.pieces[0]; }
  get water() { return this.type === 'water'; }
  get palette() { return this.water ? WATER_PIECES : COASTER_PIECES; }
  exitOf(p) {
    const def = PIECES[p.type]; const h2 = (p.h + def.turn + 4) % 4; const d = DIRS[h2]; const n = def.cells || 1;
    const d0 = DIRS[p.h];
    return { cx: p.cx + d0.x * (n - 1) + d.x, cz: p.cz + d0.z * (n - 1) + d.z, h: h2, l: p.l1 };
  }
  get cursor() { return this.exitOf(this.pieces[this.pieces.length - 1]); }
  get closed() {
    if (this.pieces.length < 4) return false;
    const c = this.cursor, s = this.station;
    return c.cx === s.cx && c.cz === s.cz && c.h === s.h && c.l === 0;
  }
  get cost() { return this.pieces.reduce((a, p) => a + PIECES[p.type].cost, 0); }
  /** Can a piece of `type` be added at the cursor? -> {ok, reason} */
  canAdd(type, occupiedFn) {
    if (this.closed) return { ok: false, reason: 'The track is finished! Press TEST 🧪' };
    const def = PIECES[type]; const c = this.cursor;
    if (!inPark(c.cx, c.cz)) return { ok: false, reason: 'Outside the park! Turn around or buy more land 🌱' };
    const l1 = c.l + def.dl;
    if (l1 < 0) return { ok: false, reason: "Can't go underground! ⛏️ Try a flat or up piece" };
    if (l1 > MAX_LEVEL) return { ok: false, reason: `Too high! Max height is ${MAX_LEVEL} 🏔️` };
    if (def.splash && c.l !== 0) return { ok: false, reason: 'Splash Pools must be on the ground (height 0) 💦' };
    if (l1 + (def.hgt || 0) > MAX_LEVEL) return { ok: false, reason: `Too high for a ${def.name}! Max height is ${MAX_LEVEL} 🏔️` };
    const s = this.station;
    const probe = { type, cx: c.cx, cz: c.cz, h: c.h, l0: c.l, l1 };
    for (const [x, z] of Ride.pieceCells(probe)) {
      if (!inPark(x, z)) return { ok: false, reason: `No room for a ${def.name} here — it needs ${def.cells || 1} cell${def.cells > 1 ? 's' : ''} inside the park 🚧` };
      if (x === s.cx && z === s.cz) return { ok: false, reason: 'That is the Station cell — line up with its arrow to finish ➡️🏠' };
      if (occupiedFn(x, z, Math.min(c.l, l1), Math.max(c.l, l1) + (def.hgt || 0), this, -1)) return { ok: false, reason: 'Something is in the way! Go higher, or turn 🚧' };
    }
    return { ok: true };
  }
  add(type) {
    const c = this.cursor; const def = PIECES[type];
    this.pieces.push({ type, cx: c.cx, cz: c.cz, h: c.h, l0: c.l, l1: c.l + def.dl });
  }
  undo() { if (this.pieces.length > 1) return this.pieces.pop(); return null; }

  // ---------- geometry ----------
  /** Cells a piece occupies: [[cx,cz],...] */
  static pieceCells(p) { const d = DIRS[p.h]; const n = PIECES[p.type].cells || 1; const out = []; for (let k = 0; k < n; k++) out.push([p.cx + d.x * k, p.cz + d.z * k]); return out; }
  static pieceCenter(p) { const cells = Ride.pieceCells(p); const c = new THREE.Vector3(); for (const [x, z] of cells) c.add(cellCenter(x, z)); return c.multiplyScalar(1 / cells.length); }
  /** World position (without Hermite height) + up-hint for a piece at t in [0,1]. */
  static shapeAt(p, t, out, hint) {
    const d = DIRS[p.h], def = PIECES[p.type]; const C = cellCenter(p.cx, p.cz);
    const r = CELL / 2; const S = { x: -d.z, z: d.x }; // right-hand side
    hint.set(0, 1, 0);
    if (def.turn !== 0) {
      const sx = def.turn < 0 ? d.z : -d.z, sz = def.turn < 0 ? -d.x : d.x; // side (left or right)
      const ex = C.x - d.x * r, ez = C.z - d.z * r;                             // entry point
      const ox = ex + sx * r, oz = ez + sz * r;                                // arc center
      const th = t * Math.PI / 2, cs = Math.cos(th), sn = Math.sin(th);
      return out.set(ox - sx * r * cs + d.x * r * sn, 0, oz - sz * r * cs + d.z * r * sn);
    }
    const ex = C.x - d.x * r, ez = C.z - d.z * r; // entry point
    let along, side = 0, y = 0;
    const smooth = u => u * u * (3 - 2 * u);
    if (p.type === 'loop') {
      const R = LOOP_R, A = LOOP_A;
      if (t < 0.12) { const u = t / 0.12; along = u * r; side = -A / 2 * smooth(u); }
      else if (t < 0.88) { const th = (t - 0.12) / 0.76 * Math.PI * 2; along = r + R * Math.sin(th); y = R * (1 - Math.cos(th)); side = -A / 2 + A * (th / (Math.PI * 2));
        hint.set(-d.x * Math.sin(th), Math.cos(th), -d.z * Math.sin(th)); }
      else { const u = (t - 0.88) / 0.12; along = r + u * r; side = A / 2 * (1 - smooth(u)); }
    } else if (p.type === 'corkscrew') {
      const L = CELL * 2, ph = t * Math.PI * 2;
      along = t * L; y = CORK_R * (1 - Math.cos(ph)); side = CORK_R * Math.sin(ph);
      hint.set(-S.x * Math.sin(ph), Math.cos(ph), -S.z * Math.sin(ph));
    } else {
      along = t * CELL * (def.cells || 1);
    }
    return out.set(ex + d.x * along + S.x * side, y, ez + d.z * along + S.z * side);
  }
  static pieceLen(p) { const def = PIECES[p.type]; return def.turn ? Math.PI * CELL / 4 : CELL * (def.cells || 1); }

  /** Sample the whole track. Returns {pts, frames, s, piece, total} */
  buildPath() {
    const P = this.pieces, n = P.length;
    const slopes = P.map(p => PIECES[p.type].dl * RISE / Ride.pieceLen(p));
    const pts = [], pieceIdx = [], hints = [];
    const closed = this.closed;
    for (let i = 0; i < n; i++) {
      const p = P[i], L = Ride.pieceLen(p), def = PIECES[p.type], N = def.samples || 10;
      const y0 = p.l0 * RISE, y1 = p.l1 * RISE;
      const mPrev = i > 0 ? slopes[i - 1] : (closed ? slopes[n - 1] : slopes[i]);
      const mNext = i < n - 1 ? slopes[i + 1] : (closed ? slopes[0] : slopes[i]);
      let m0 = (mPrev + slopes[i]) / 2, m1 = (slopes[i] + mNext) / 2;
      if (def.inversion) { m0 = 0; m1 = 0; }
      const last = (i === n - 1 && !closed) ? N + 1 : N;
      for (let k = 0; k < last; k++) {
        const t = k / N, t2 = t * t, t3 = t2 * t;
        const y = (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * L * m0 + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * L * m1;
        const hint = new THREE.Vector3();
        const v = Ride.shapeAt(p, t, new THREE.Vector3(), hint); v.y += y + 0.4;
        pts.push(v); pieceIdx.push(i); hints.push(hint);
      }
    }
    // frames + arc length
    const M = pts.length, frames = [], s = [0];
    for (let i = 0; i < M; i++) {
      const a = pts[(i - 1 + M) % M], b = pts[(i + 1) % M];
      let t;
      if (!closed && (i === 0 || i === M - 1)) t = i === 0 ? pts[1].clone().sub(pts[0]) : pts[M - 1].clone().sub(pts[M - 2]);
      else t = b.clone().sub(a);
      t.normalize();
      const nrm = new THREE.Vector3().crossVectors(hints[i], t).normalize();
      const bn = new THREE.Vector3().crossVectors(t, nrm).normalize();
      frames.push({ p: pts[i], t, n: nrm, b: bn });
      if (i > 0) s.push(s[i - 1] + pts[i].distanceTo(pts[i - 1]));
    }
    const total = closed ? s[M - 1] + pts[M - 1].distanceTo(pts[0]) : s[M - 1];
    this.path = { pts, frames, s, piece: pieceIdx, total, closed };
    return this.path;
  }
  /** Interpolated frame at arc length `dist` (wraps if closed). */
  frameAt(dist, out) {
    const path = this.path; const M = path.pts.length;
    let d = path.closed ? ((dist % path.total) + path.total) % path.total : THREE.MathUtils.clamp(dist, 0, path.total - 1e-4);
    let lo = 0, hi = M - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (path.s[mid] <= d) lo = mid; else hi = mid - 1; }
    const i = lo, j = (i + 1) % M;
    const segLen = (j === 0 ? path.total : path.s[j]) - path.s[i];
    const u = segLen > 0 ? (d - path.s[i]) / segLen : 0;
    const A = path.frames[i], B = path.frames[j];
    out = out || { p: new THREE.Vector3(), t: new THREE.Vector3(), n: new THREE.Vector3(), b: new THREE.Vector3() };
    out.p.copy(A.p).lerp(B.p, u); out.t.copy(A.t).lerp(B.t, u).normalize();
    out.n.copy(A.n).lerp(B.n, u).normalize(); out.b.copy(A.b).lerp(B.b, u).normalize();
    out.pieceIndex = path.piece[i]; out.tPiece = u; out.sampleIndex = i;
    return out;
  }
  pieceRange(i) { // arc-length range of piece i
    const path = this.path; let a = Infinity, b = -Infinity;
    for (let k = 0; k < path.piece.length; k++) if (path.piece[k] === i) { a = Math.min(a, path.s[k]); b = Math.max(b, path.s[k]); }
    return [a, b + (path.total / path.pts.length)];
  }

  /** (Re)build meshes for the whole ride. */
  buildMesh(scene) {
    disposeObject(this.group); this.group = new THREE.Group(); this.group.userData.ride = this;
    const path = this.buildPath(); const F = path.frames; const closed = path.closed;
    const col = this.color;
    const mat = new THREE.MeshStandardMaterial({ color: col, roughness: 0.45, metalness: 0.3 });
    const steel = new THREE.MeshStandardMaterial({ color: 0xb9c2cc, roughness: 0.5, metalness: 0.6 });
    if (!this.water) {
      const rail = 0.14;
      for (const off of [-0.55, 0.55]) {
        const m = new THREE.Mesh(sweepGeometry(F, [[off - rail, rail], [off + rail, rail], [off + rail, -rail], [off - rail, -rail], [off - rail, rail]], closed), mat);
        m.castShadow = true; this.group.add(m);
      }
      const spine = new THREE.Mesh(sweepGeometry(F, [[-0.18, -0.25], [0.18, -0.25], [0.18, -0.6], [-0.18, -0.6], [-0.18, -0.25]], closed), steel);
      spine.castShadow = true; this.group.add(spine);
    } else {
      const trough = new THREE.Mesh(sweepGeometry(F, [[-1.15, 0.9], [-1.15, 0.15], [-0.85, -0.05], [0.85, -0.05], [1.15, 0.15], [1.15, 0.9]], closed),
        new THREE.MeshStandardMaterial({ color: 0xdfe9f2, roughness: 0.6, side: THREE.DoubleSide }));
      trough.castShadow = true; trough.receiveShadow = true; this.group.add(trough);
      const water = new THREE.Mesh(sweepGeometry(F, [[-0.95, 0.35], [0.95, 0.35]], closed),
        new THREE.MeshStandardMaterial({ color: 0x3fb4ff, roughness: 0.15, metalness: 0.1, transparent: true, opacity: 0.8, side: THREE.DoubleSide }));
      this.group.add(water);
      const rim = new THREE.Mesh(sweepGeometry(F, [[-1.3, 0.95], [-1.15, 0.95], [-1.15, 0.75], [-1.3, 0.75], [-1.3, 0.95]], closed), mat);
      this.group.add(rim);
      const rim2 = new THREE.Mesh(sweepGeometry(F, [[1.15, 0.95], [1.3, 0.95], [1.3, 0.75], [1.15, 0.75], [1.15, 0.95]], closed), mat);
      this.group.add(rim2);
    }
    // ties (instanced), yellow on lift pieces
    const tieCount = Math.floor(F.length / 2);
    const tieGeo = this.water ? new THREE.BoxGeometry(2.7, 0.12, 0.3) : new THREE.BoxGeometry(1.5, 0.1, 0.3);
    const ties = new THREE.InstancedMesh(tieGeo, new THREE.MeshStandardMaterial({ roughness: 0.7 }), tieCount);
    const m4 = new THREE.Matrix4(), c3 = new THREE.Color();
    let ti = 0;
    for (let i = 0; i < F.length; i += 2) {
      const f = F[i]; const def = PIECES[this.pieces[path.piece[i]].type];
      const pos = f.p.clone().addScaledVector(f.b, this.water ? -0.12 : -0.2);
      m4.makeBasis(f.n, f.b, f.t).setPosition(pos);
      ties.setMatrixAt(ti, m4);
      ties.setColorAt(ti, c3.set(def.lift ? 0xffd11a : (def.splash ? 0x3fb4ff : 0x5a6570)));
      ti++;
    }
    ties.count = ti; ties.castShadow = true; this.group.add(ties);
    // supports
    const sup = [];
    for (let i = 0; i < F.length;) { const f = F[i]; const inv = PIECES[this.pieces[path.piece[i]].type].inversion; if (f.p.y > 0.9 && f.b.y > (inv ? 0.15 : 0.45)) sup.push(f); i += inv ? 3 : 5; }
    if (sup.length) {
      const supGeo = new THREE.CylinderGeometry(0.16, 0.2, 1, 8); supGeo.translate(0, 0.5, 0);
      const supports = new THREE.InstancedMesh(supGeo, steel, sup.length * (this.water ? 2 : 1));
      let k = 0;
      for (const f of sup) {
        const offs = this.water ? [-0.9, 0.9] : [0];
        for (const o of offs) {
          const base = new THREE.Vector3(f.p.x + f.n.x * o, 0, f.p.z + f.n.z * o);
          const top = f.p.y - 0.5;
          m4.makeScale(1, top, 1).setPosition(base); supports.setMatrixAt(k++, m4);
        }
      }
      supports.castShadow = true; this.group.add(supports);
    }
    // station building
    this.stationMesh = buildStationMesh(this);
    this.group.add(this.stationMesh);
    // splash pools
    for (const p of this.pieces) if (p.type === 'splash') {
      const C = cellCenter(p.cx, p.cz);
      const pool = new THREE.Mesh(new THREE.CylinderGeometry(2.4, 2.4, 0.5, 20), new THREE.MeshStandardMaterial({ color: 0x2a9df4, roughness: 0.2, transparent: true, opacity: 0.85 }));
      pool.position.set(C.x, 0.25, C.z); this.group.add(pool);
      const rimm = new THREE.Mesh(new THREE.TorusGeometry(2.4, 0.2, 8, 24), new THREE.MeshStandardMaterial({ color: 0xffffff })); rimm.rotation.x = Math.PI / 2; rimm.position.set(C.x, 0.5, C.z); this.group.add(rimm);
    }
    // end-of-track arrow marker (while building)
    if (!closed) {
      const c = this.cursor; const C = cellCenter(c.cx, c.cz); const d = DIRS[c.h];
      const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.7, 1.8, 4), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 }));
      arrow.rotation.x = Math.PI / 2; arrow.rotation.z = Math.PI / 4;
      const holder = new THREE.Group(); holder.add(arrow);
      holder.position.set(C.x - d.x * 1.2, c.l * RISE + 1.2, C.z - d.z * 1.2);
      holder.lookAt(C.x + d.x, c.l * RISE + 1.2, C.z + d.z);
      holder.name = 'cursorArrow'; this.group.add(holder);
      const ring = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.8, 24), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.6, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(C.x, 0.06, C.z); ring.name = 'cursorRing'; this.group.add(ring);
    }
    scene.add(this.group);
    if (this.vehicle) { disposeObject(this.vehicle.group); this.vehicle = null; }
    if (closed) this.vehicle = makeVehicle(this);
    return this.group;
  }
  highlightPiece(i, on) {
    // mark a piece with a red glowing ring
    const old = this.group.getObjectByName('failRing'); if (old) disposeObject(old);
    if (!on) return;
    const p = this.pieces[i]; const C = Ride.pieceCenter(p);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.2, 0.25, 8, 28), new THREE.MeshBasicMaterial({ color: 0xff2020 }));
    ring.rotation.x = Math.PI / 2; ring.position.set(C.x, (Math.max(p.l0, p.l1) + (PIECES[p.type].hgt || 0)) * RISE + 0.6, C.z); ring.name = 'failRing';
    this.group.add(ring);
  }
  toJSON() { return { type: this.type, name: this.name, color: this.color, pieces: this.pieces, open: this.open, stars: this.stars, stats: this.stats, earned: this.earned, ridersServed: this.ridersServed }; }
  static fromJSON(j) {
    const r = new Ride(j.type, j.pieces[0].cx, j.pieces[0].cz, j.pieces[0].h, j.color);
    r.name = j.name; r.pieces = j.pieces; r.open = j.open; r.stars = j.stars || 0; r.stats = j.stats || null; r.earned = j.earned || 0; r.ridersServed = j.ridersServed || 0;
    return r;
  }
}

function buildStationMesh(ride) {
  const s = ride.station; const C = cellCenter(s.cx, s.cz); const d = DIRS[s.h];
  const g = new THREE.Group(); g.position.set(C.x, 0, C.z); g.rotation.y = -s.h * Math.PI / 2;
  const platMat = new THREE.MeshStandardMaterial({ color: 0xe8dcc8, roughness: 0.9 });
  for (const side of [-1, 1]) {
    const plat = new THREE.Mesh(new THREE.BoxGeometry(CELL, 0.5, 1.2), platMat); plat.position.set(0, 0.25, side * 1.6); plat.receiveShadow = true; plat.castShadow = true; g.add(plat);
  }
  const postMat = new THREE.MeshStandardMaterial({ color: ride.color, roughness: 0.5 });
  for (const x of [-1.6, 1.6]) for (const z of [-2.0, 2.0]) { const post = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 4, 8), postMat); post.position.set(x, 2, z); g.add(post); }
  const roof = new THREE.Mesh(new THREE.BoxGeometry(CELL + 0.6, 0.3, 5), new THREE.MeshStandardMaterial({ map: stripeTexture(ride.water ? '#3fb4ff' : '#' + new THREE.Color(ride.color).getHexString(), '#ffffff'), roughness: 0.7 }));
  roof.position.y = 4.1; roof.castShadow = true; g.add(roof);
  const signTex = textTexture((ride.water ? '🌊 ' : '🎢 ') + ride.name, { bg: '#ffffff', color: '#222', border: '#' + new THREE.Color(ride.color).getHexString(), size: 56, w: 640, h: 128 });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(4.4, 0.9), new THREE.MeshBasicMaterial({ map: signTex, side: THREE.DoubleSide }));
  sign.position.set(0, 4.75, 0); g.add(sign);
  const sign2 = sign.clone(); sign2.rotation.y = Math.PI; g.add(sign2);
  g.userData.pick = { kind: 'ride', id: ride.id };
  g.traverse(o => { o.userData.pick = g.userData.pick; });
  return g;
}

// ---------- vehicles ----------
function makeVehicle(ride) {
  const g = new THREE.Group(); const cars = [];
  const seatsPerCar = ride.water ? 4 : 2, carCount = ride.water ? 1 : 3, spacing = ride.water ? 0 : 2.1;
  const bodyMat = new THREE.MeshStandardMaterial({ color: ride.water ? 0x8b5a2b : ride.color, roughness: 0.4, metalness: 0.2 });
  const seatMat = new THREE.MeshStandardMaterial({ color: 0x222831, roughness: 0.8 });
  for (let i = 0; i < carCount; i++) {
    const car = new THREE.Group();
    if (!ride.water) {
      const body = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.55, 1.8), bodyMat); body.position.y = 0.35; body.castShadow = true; car.add(body);
      const nose = new THREE.Mesh(new THREE.SphereGeometry(0.62, 12, 8), bodyMat); nose.scale.set(1, 0.5, 0.8); nose.position.set(0, 0.4, 0.95); car.add(nose);
      for (const [x, z] of [[-0.55, 0.6], [0.55, 0.6], [-0.55, -0.6], [0.55, -0.6]]) { const w = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.12, 10), seatMat); w.rotation.z = Math.PI / 2; w.position.set(x * 1.25, 0.15, z); car.add(w); }
      for (const x of [-0.32, 0.32]) { const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), seatMat); seat.position.set(x, 0.6, -0.35); car.add(seat); }
    } else {
      const log = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 3.2, 12), bodyMat); log.rotation.x = Math.PI / 2; log.position.y = 0.55; log.castShadow = true; car.add(log);
      const front = new THREE.Mesh(new THREE.SphereGeometry(0.75, 12, 8), bodyMat); front.position.set(0, 0.55, 1.6); car.add(front);
      const back = front.clone(); back.position.z = -1.6; car.add(back);
      const hollow = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.5, 2.6), seatMat); hollow.position.y = 0.95; car.add(hollow);
    }
    car.position.z = -i * spacing;
    car.userData.seats = [];
    for (let s = 0; s < seatsPerCar; s++) {
      const seat = new THREE.Object3D();
      if (!ride.water) seat.position.set(s === 0 ? -0.32 : 0.32, 0.85, -0.35);
      else seat.position.set(s % 2 === 0 ? -0.28 : 0.28, 1.1, 0.6 - Math.floor(s / 2) * 1.1);
      car.add(seat); car.userData.seats.push(seat);
    }
    g.add(car); cars.push(car);
  }
  World.scene.add(g);
  const v = { group: g, cars, spacing, ride, s: 0, v: 0, mode: 'idle', timer: 0, frontFrame: null, seats: cars.flatMap(c => c.userData.seats), riders: [] };
  resetVehicle(v);
  return v;
}
function resetVehicle(v) {
  const [a, b] = v.ride.pieceRange(0);
  v.s = (a + b) / 2 + (v.ride.water ? 0 : v.spacing); v.v = 0; v.mode = 'idle'; v.timer = 0; v.lastPiece = 0;
  placeVehicle(v);
}
const _fr = { p: new THREE.Vector3(), t: new THREE.Vector3(), n: new THREE.Vector3(), b: new THREE.Vector3() };
const _m4 = new THREE.Matrix4();
function placeVehicle(v) {
  for (let i = 0; i < v.cars.length; i++) {
    const f = v.ride.frameAt(v.s - i * v.spacing, i === 0 ? null : _fr);
    const car = v.cars[i];
    car.position.copy(f.p).addScaledVector(f.b, 0.1);
    _m4.makeBasis(f.n, f.b, f.t); car.quaternion.setFromRotationMatrix(_m4);
    if (i === 0) v.frontFrame = f;
  }
}

/** Advance vehicle physics by dt. Returns null or a failure {reason, piece}. `stats` accumulates. */
function stepVehicle(v, dt, stats, opts = {}) {
  const ride = v.ride, path = ride.path;
  if (v.mode === 'loading') { v.timer -= dt; if (v.timer <= 0) { v.mode = 'run'; v.v = PHYS.launch; } placeVehicle(v); return null; }
  if (v.mode === 'idle') { v.mode = 'run'; v.v = PHYS.launch; }
  const sub = Math.max(4, Math.ceil(dt / 0.006)), h = dt / sub;
  const [st0, st1] = ride.pieceRange(0); const stMid = (st0 + st1) / 2 + (ride.water ? 0 : v.spacing);
  for (let k = 0; k < sub; k++) {
    const f = ride.frameAt(v.s, _fr); const pi = f.pieceIndex; const piece = ride.pieces[pi]; const def = PIECES[piece.type];
    const slope = f.t.y;
    if (def.inversion && v.lastPiece !== pi) {
      if (v.v < def.minSpeed) { placeVehicle(v); return { reason: `Not enough speed for the ${def.name}! It needs speed ${def.minSpeed} but the cars only had ${v.v.toFixed(0)}. Put a bigger drop ⬇️ right before it!`, piece: pi }; }
    }
    v.lastPiece = pi;
    let v2;
    if (def.lift && slope > -0.02) { v.v = Math.max(Math.min(v.v, PHYS.liftSpeed + 0.001), PHYS.liftSpeed); v2 = v.v * v.v; }
    else {
      const mu = ride.water ? (slope <= 0.02 ? PHYS.muWater : PHYS.muCoaster) : PHYS.muCoaster;
      const ds = v.v * h;
      v2 = v.v * v.v - 2 * PHYS.g * slope * ds - 2 * mu * PHYS.g * ds - 2 * PHYS.drag * v.v * v.v * ds;
      if (def.splash) { v2 = Math.min(v2, Math.max(PHYS.flow * PHYS.flow, v2 - 2 * 9 * ds)); if (stats && !stats.splashed) { stats.splashed = true; stats.splashSpeed = v.v; if (opts.onSplash) opts.onSplash(f, v.v); } }
      if (ride.water && slope <= 0.03 && v2 < PHYS.flow * PHYS.flow) v2 = PHYS.flow * PHYS.flow;
      if (def.station && v2 > PHYS.stationBrake * PHYS.stationBrake) v2 = Math.max(PHYS.stationBrake * PHYS.stationBrake, v2 - 2 * 14 * ds);
      if (v2 <= 0.05) {
        v.v = 0; placeVehicle(v);
        const up = slope > 0.01;
        let reason;
        if (ride.water && up) reason = 'Water can\'t flow uphill! Use a Conveyor 🔼 to lift the boat, or make this hill smaller.';
        else if (up) reason = 'Not enough speed to get over this hill! Use a Chain Lift ⛓️, or make the hill before it taller.';
        else reason = 'The car ran out of energy and stopped! Add a taller lift hill so it has more speed.';
        return { reason, piece: pi };
      }
    }
    v.v = Math.sqrt(v2);
    if (def.turn && v.v > PHYS.turnMax && !ride.water) { placeVehicle(v); return { reason: `Too fast on the turn! (${v.v.toFixed(0)} — max is ${PHYS.turnMax}) The cars would fly off! Add a small hill ↗️ before the turn to slow down.`, piece: pi }; }
    if (def.turn && v.v > PHYS.turnMax * 1.15 && ride.water) { placeVehicle(v); return { reason: `Too fast on the turn! The boat would tip over! Add a Splash Pool 💦 or a hill ↗️ before the turn.`, piece: pi }; }
    const prevS = v.s;
    v.s += v.v * h;
    if (stats) {
      stats.maxV = Math.max(stats.maxV, v.v); stats.maxH = Math.max(stats.maxH, f.p.y);
      stats.time += h;
      if (def.turn && stats.lastTurn !== pi) { stats.turns++; stats.lastTurn = pi; }
      if (def.inversion && stats.lastInv !== pi) { stats.inversions++; stats.lastInv = pi; }
      if (slope < -0.3 && v.v > 9 && stats.lastDrop !== pi && (def.dl < 0)) { stats.drops++; stats.lastDrop = pi; }
      if (stats.prevSlope > 0.15 && slope < -0.15 && v.v > 6) stats.airtime++;
      stats.prevSlope = slope;
      if (stats.time > 240) { placeVehicle(v); return { reason: 'The ride took way too long! Make it shorter or faster.', piece: pi }; }
    }
    // station arrival (wrap-aware)
    const wrapped = path.closed && v.s >= path.total;
    if (wrapped) v.s -= path.total;
    const crossed = (prevS < stMid && v.s >= stMid) || (wrapped && v.s >= stMid);
    if (crossed && stats && stats.time > 1.5) { v.s = stMid; v.v = 0; v.mode = 'loading'; v.timer = PHYS.loadTime; placeVehicle(v); return { done: true }; }
    if (crossed && !stats) { v.s = stMid; v.v = 0; v.mode = 'loading'; v.timer = PHYS.loadTime; placeVehicle(v); if (opts.onStation) opts.onStation(v); return null; }
  }
  placeVehicle(v);
  return null;
}

function newStats() { return { maxV: 0, maxH: 0, time: 0, turns: 0, drops: 0, airtime: 0, inversions: 0, lastTurn: -1, lastDrop: -1, lastInv: -1, prevSlope: 0, splashed: false }; }

/** Stars 1..5 from stats + layout. */
function rateRide(ride, st) {
  const P = ride.pieces;
  const maxLevel = Math.max(...P.map(p => Math.max(p.l0, p.l1)));
  // biggest continuous drop in levels
  let best = 0, run = 0;
  for (const p of P) { const dl = PIECES[p.type].dl; if (dl < 0) { run += -dl; best = Math.max(best, run); } else if (dl > 0) run = 0; }
  const loops = P.filter(p => p.type === 'loop').length, corks = P.filter(p => p.type === 'corkscrew').length;
  let ex = best * 1.6 + st.turns * 0.5 + st.drops * 0.9 + Math.min(st.maxV, 26) * 0.3 + P.length * 0.12 + st.airtime * 1.0 + loops * 4.5 + corks * 3.5;
  if (ride.water) ex += st.splashed ? 3 + Math.min(st.splashSpeed || 0, 15) * 0.25 : 0;
  const stars = ex >= 29 ? 5 : ex >= 21 ? 4 : ex >= 14 ? 3 : ex >= 8 ? 2 : 1;
  return { stars, excitement: Math.round(ex * 10) / 10, maxLevel, bigDrop: best, loops, corks };
}

/** BFS auto-connect: find pieces (flat/turn/down) from cursor back to the station entry. */
function autoConnect(ride, occupiedFn, maxPieces = 60) {
  const start = ride.cursor, s = ride.station;
  const goal = `${s.cx},${s.cz},${s.h},0`;
  const key = c => `${c.cx},${c.cz},${c.h},${c.l}`;
  const prev = new Map(); prev.set(key(start), null);
  const q = [start];
  const moves = ride.water ? ['straight', 'down', 'left', 'right'] : ['straight', 'down', 'left', 'right'];
  let found = null, iter = 0;
  while (q.length && iter++ < 250000) {
    const c = q.shift();
    if (key(c) === goal) { found = c; break; }
    if (!inPark(c.cx, c.cz) || (c.cx === s.cx && c.cz === s.cz)) continue;
    const depth = (prev.get(key(c)) || {}).depth || 0;
    if (depth > maxPieces) continue;
    const order = c.l > 0 ? ['down', 'straight', 'left', 'right'] : moves;
    for (const type of order) {
      const def = PIECES[type]; const l1 = c.l + def.dl; if (l1 < 0) continue;
      if (occupiedFn(c.cx, c.cz, Math.min(c.l, l1), Math.max(c.l, l1), ride, -1)) continue;
      const piece = { type, cx: c.cx, cz: c.cz, h: c.h, l0: c.l, l1 };
      const nx = ride.exitOf(piece); const k = key(nx);
      if (prev.has(k)) continue;
      prev.set(k, { from: key(c), piece, depth: depth + 1 });
      q.push(nx);
    }
  }
  if (!found) return null;
  const pieces = []; let k = key(found);
  while (prev.get(k)) { const e = prev.get(k); pieces.unshift(e.piece); k = e.from; }
  return pieces;
}
