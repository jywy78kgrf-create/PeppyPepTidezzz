/* FitzLandia — spooky.js
   The Spooky House: a walk-through haunted hallway with jump scares. Rendered in its own dark scene. */
'use strict';

const Spooky = {
  scene: null, built: false, active: false, building: null, savedPos: null, savedYaw: 0,
  cells: new Set(), path: [], scares: [], anims: [], lights: [], flicker: 0, shake: 0, t: 0, exitCell: null, ghostMat: null,
  C: 4, // cell size

  // hallway route through a grid (x,z cells)
  route: [[0,0],[0,1],[0,2],[1,2],[2,2],[2,1],[2,0],[3,0],[4,0],[4,1],[4,2],[4,3],[3,3],[2,3],[1,3],[0,3],[0,4],[0,5],[1,5],[2,5],[3,5],[4,5],[5,5],[6,5]],

  key(x, z) { return x + ',' + z; },
  center(x, z) { return new THREE.Vector3((x + 0.5) * this.C, 0, (z + 0.5) * this.C); },

  build() {
    if (this.built) return; this.built = true;
    const sc = new THREE.Scene(); sc.background = new THREE.Color(0x05030a); sc.fog = new THREE.Fog(0x0a0614, 5, 34); this.scene = sc;
    sc.add(new THREE.AmbientLight(0x7a6aa0, 2.2));
    const C = this.C;
    for (const [x, z] of this.route) this.cells.add(this.key(x, z));
    // textures
    const wallTex = canvasTex(256, 256, (ctx, w, h) => {
      ctx.fillStyle = '#4a2a60'; ctx.fillRect(0, 0, w, h);
      for (let i = 0; i < 8; i++) { ctx.fillStyle = i % 2 ? '#553270' : '#452858'; ctx.fillRect(0, i * 32, w, 32); ctx.fillStyle = 'rgba(0,0,0,.45)'; ctx.fillRect(0, i * 32 + 30, w, 2); }
      for (let i = 0; i < 40; i++) { ctx.strokeStyle = 'rgba(0,0,0,.35)'; ctx.beginPath(); const x = Math.random() * w, y = Math.random() * h; ctx.moveTo(x, y); ctx.lineTo(x + Math.random() * 40 - 20, y + Math.random() * 30); ctx.stroke(); }
    }, { repeat: [1, 1] });
    const floorTex = canvasTex(128, 128, (ctx, w, h) => { for (let y = 0; y < 2; y++) for (let x = 0; x < 2; x++) { ctx.fillStyle = (x + y) % 2 ? '#3a2f44' : '#241c2c'; ctx.fillRect(x * 64, y * 64, 64, 64); } }, { repeat: [2, 2] });
    const webTex = canvasTex(128, 128, (ctx, w, h) => { ctx.strokeStyle = 'rgba(230,230,240,.75)'; ctx.lineWidth = 1.2; for (let i = 0; i < 9; i++) { const a = i / 8 * Math.PI / 2; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * 128, Math.sin(a) * 128); ctx.stroke(); } for (let r = 16; r < 128; r += 18) { ctx.beginPath(); for (let i = 0; i <= 8; i++) { const a = i / 8 * Math.PI / 2; const rr = r * (0.9 + 0.1 * (i % 2)); ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); } ctx.stroke(); } });
    const wallMat = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.95 });
    const floorMat = new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.9 });
    const ceilMat = new THREE.MeshStandardMaterial({ color: 0x241a30, roughness: 1 });
    const H = 4.2;
    // floors, ceilings and walls where a neighbour is not part of the route
    for (const [x, z] of this.route) {
      const c = this.center(x, z);
      const f = new THREE.Mesh(new THREE.PlaneGeometry(C, C), floorMat); f.rotation.x = -Math.PI / 2; f.position.set(c.x, 0, c.z); f.receiveShadow = true; sc.add(f);
      const ce = new THREE.Mesh(new THREE.PlaneGeometry(C, C), ceilMat); ce.rotation.x = Math.PI / 2; ce.position.set(c.x, H, c.z); sc.add(ce);
      const sides = [[1, 0, 0], [-1, 0, Math.PI], [0, 1, -Math.PI / 2], [0, -1, Math.PI / 2]]; // dx, dz, wall yaw
      for (const [dx, dz, yaw] of sides) {
        if (this.cells.has(this.key(x + dx, z + dz))) continue;
        const w = new THREE.Mesh(new THREE.PlaneGeometry(C, H), wallMat);
        w.position.set(c.x + dx * C / 2, H / 2, c.z + dz * C / 2); w.rotation.y = yaw + Math.PI; w.rotation.y = Math.atan2(-dx, -dz); sc.add(w);
        if (Math.random() < 0.35) { const web = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.4), new THREE.MeshBasicMaterial({ map: webTex, transparent: true, depthWrite: false })); web.position.set(c.x + dx * (C / 2 - 0.05) + (dz ? (Math.random() - 0.5) * 2 : 0), H - 0.75, c.z + dz * (C / 2 - 0.05) + (dx ? (Math.random() - 0.5) * 2 : 0)); web.rotation.y = Math.atan2(-dx, -dz); sc.add(web); }
      }
    }
    // candle lights along the route
    const lightCells = [[0,1],[2,1],[4,1],[4,3],[1,3],[0,5],[3,5],[6,5]];
    const lcol = [0xff9a3c, 0x9b59ff, 0x3cff7a, 0xff9a3c, 0x9b59ff, 0x3cff7a, 0xff4d4d, 0xffe08a];
    lightCells.forEach(([x, z], i) => {
      const c = this.center(x, z); const l = new THREE.PointLight(lcol[i], 3.2, 18, 2); l.position.set(c.x, 2.8, c.z); sc.add(l); this.lights.push(l);
      const candle = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.5, 6), new THREE.MeshStandardMaterial({ color: 0xf1e6c8 })); candle.position.set(c.x + 1.6, 1.3, c.z + 1.6); sc.add(candle);
      const flame = new THREE.Mesh(new THREE.SphereGeometry(0.1, 6, 5), new THREE.MeshBasicMaterial({ color: lcol[i] })); flame.position.set(c.x + 1.6, 1.62, c.z + 1.6); sc.add(flame);
      const shelf = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.08, 0.6), new THREE.MeshStandardMaterial({ color: 0x3b2a20 })); shelf.position.set(c.x + 1.6, 1.0, c.z + 1.6); sc.add(shelf);
    });
    // pumpkins
    const pumpTex = canvasTex(128, 128, (ctx, w, h) => { ctx.fillStyle = '#ff7a1a'; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#ffe66b'; ctx.beginPath(); ctx.moveTo(30, 40); ctx.lineTo(50, 60); ctx.lineTo(20, 60); ctx.fill(); ctx.beginPath(); ctx.moveTo(98, 40); ctx.lineTo(108, 60); ctx.lineTo(78, 60); ctx.fill(); ctx.beginPath(); ctx.moveTo(25, 85); for (let i = 0; i <= 6; i++) ctx.lineTo(25 + i * 13, 85 + (i % 2 ? 14 : 0)); ctx.lineTo(103, 100); ctx.lineTo(25, 100); ctx.fill(); });
    for (const [x, z] of [[2,2],[4,0],[0,3],[2,5],[5,5]]) { const c = this.center(x, z); const p = new THREE.Mesh(new THREE.SphereGeometry(0.45, 12, 10), new THREE.MeshStandardMaterial({ map: pumpTex, emissive: 0xff6a00, emissiveIntensity: 0.35, emissiveMap: pumpTex })); p.scale.y = 0.8; p.position.set(c.x - 1.5, 0.4, c.z - 1.5); p.rotation.y = Math.random() * 6; sc.add(p); }
    // portraits
    const portrait = (variant) => canvasTex(128, 160, (ctx, w, h) => { ctx.fillStyle = '#6b4e2a'; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#1a1a22'; ctx.fillRect(10, 10, w - 20, h - 20); ctx.fillStyle = '#d9cfc0'; ctx.beginPath(); ctx.ellipse(w / 2, 78, 30, 40, 0, 0, 6.3); ctx.fill(); ctx.fillStyle = '#111'; ctx.beginPath(); ctx.arc(w / 2 - 12, 70, 5, 0, 6.3); ctx.arc(w / 2 + 12, 70, 5, 0, 6.3); ctx.fill(); ctx.strokeStyle = '#111'; ctx.lineWidth = 3; ctx.beginPath(); if (variant) { ctx.arc(w / 2, 100, 10, 0, Math.PI); } else { ctx.moveTo(w / 2 - 10, 104); ctx.lineTo(w / 2 + 10, 104); } ctx.stroke(); });
    this.portraits = [];
    for (const [x, z, dx, dz] of [[0,1,-1,0],[2,1,1,0],[4,2,1,0],[1,3,0,-1],[0,4,-1,0],[2,5,0,1],[4,5,0,-1]]) {
      const c = this.center(x, z); const g = new THREE.Group();
      const pic = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 1.5), new THREE.MeshStandardMaterial({ map: portrait(Math.random() < 0.5), roughness: 0.8 })); g.add(pic);
      const eyes = new THREE.Group(); for (const ex of [-0.11, 0.11]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.05, 6, 5), new THREE.MeshBasicMaterial({ color: 0xff2020 })); e.position.set(ex, 0.08, 0.03); e.visible = false; eyes.add(e); } g.add(eyes); g.userData.eyes = eyes;
      g.position.set(c.x + dx * (C / 2 - 0.06), 2.3, c.z + dz * (C / 2 - 0.06)); g.rotation.y = Math.atan2(-dx, -dz); sc.add(g); this.portraits.push(g);
    }
    // actors (hidden until their scare)
    const ghostMat = new THREE.MeshStandardMaterial({ color: 0xf4f4ff, emissive: 0x8899ff, emissiveIntensity: 0.6, transparent: true, opacity: 0.92 }); this.ghostMat = ghostMat;
    const mkGhost = (sz) => { const g = new THREE.Group(); const body = new THREE.Mesh(new THREE.SphereGeometry(sz, 14, 12), ghostMat); body.scale.y = 1.3; g.add(body); const tail = new THREE.Mesh(new THREE.ConeGeometry(sz, sz * 1.4, 12, 1, true), ghostMat); tail.position.y = -sz * 1.1; tail.rotation.x = Math.PI; g.add(tail); for (const ex of [-0.35, 0.35]) { const e = new THREE.Mesh(new THREE.SphereGeometry(sz * 0.18, 8, 6), new THREE.MeshBasicMaterial({ color: 0x111122 })); e.position.set(ex * sz, sz * 0.25, sz * 0.85); g.add(e); } const m = new THREE.Mesh(new THREE.SphereGeometry(sz * 0.22, 8, 6), new THREE.MeshBasicMaterial({ color: 0x111122 })); m.scale.y = 1.6; m.position.set(0, -sz * 0.25, sz * 0.9); g.add(m); g.visible = false; sc.add(g); return g; };
    this.ghost = mkGhost(0.7); this.bigGhost = mkGhost(1.6);
    // skeleton
    const bone = new THREE.MeshStandardMaterial({ color: 0xf2f2e6, roughness: 0.6 });
    const sk = new THREE.Group(); const skull = new THREE.Mesh(new THREE.SphereGeometry(0.32, 10, 8), bone); skull.position.y = 1.6; sk.add(skull);
    for (const ex of [-0.1, 0.1]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.07, 6, 5), new THREE.MeshBasicMaterial({ color: 0x000 })); e.position.set(ex, 1.65, 0.28); sk.add(e); }
    const spine = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.0, 6), bone); spine.position.y = 0.9; sk.add(spine);
    for (let i = 0; i < 4; i++) { const rib = new THREE.Mesh(new THREE.TorusGeometry(0.3 - i * 0.03, 0.04, 6, 12, Math.PI), bone); rib.rotation.x = Math.PI / 2; rib.rotation.z = Math.PI; rib.position.y = 1.3 - i * 0.18; sk.add(rib); }
    for (const sx of [-1, 1]) { const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.9, 6), bone); arm.position.set(sx * 0.45, 1.05, 0); arm.rotation.z = sx * 0.5; sk.add(arm); const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.05, 0.9, 6), bone); leg.position.set(sx * 0.15, 0.0, 0); sk.add(leg); }
    sk.visible = false; sc.add(sk); this.skeleton = sk;
    // spider
    const sp = new THREE.Group(); const spMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.7 });
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.3, 10, 8), spMat); sp.add(body); const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 6), spMat); head.position.set(0, 0.05, 0.35); sp.add(head);
    for (const ex of [-0.07, 0.07]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.04, 6, 5), new THREE.MeshBasicMaterial({ color: 0xff3030 })); e.position.set(ex, 0.12, 0.5); sp.add(e); }
    for (let i = 0; i < 8; i++) { const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.8, 4), spMat); const side = i < 4 ? -1 : 1; leg.position.set(side * 0.4, 0, -0.25 + (i % 4) * 0.17); leg.rotation.z = side * 1.1; leg.rotation.x = 0.3; sp.add(leg); }
    const thread = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 6, 3), new THREE.MeshBasicMaterial({ color: 0xdddddd })); thread.position.y = 3; sp.add(thread);
    sp.visible = false; sc.add(sp); this.spider = sp;
    // bats
    const batTex = canvasTex(128, 64, (ctx, w, h) => { ctx.fillStyle = '#000'; ctx.beginPath(); ctx.moveTo(64, 40); ctx.quadraticCurveTo(40, 10, 4, 24); ctx.quadraticCurveTo(24, 30, 20, 44); ctx.quadraticCurveTo(44, 36, 64, 52); ctx.quadraticCurveTo(84, 36, 108, 44); ctx.quadraticCurveTo(104, 30, 124, 24); ctx.quadraticCurveTo(88, 10, 64, 40); ctx.fill(); ctx.beginPath(); ctx.arc(64, 34, 8, 0, 6.3); ctx.fill(); ctx.fillStyle = '#ff3030'; ctx.beginPath(); ctx.arc(60, 32, 1.6, 0, 6.3); ctx.arc(68, 32, 1.6, 0, 6.3); ctx.fill(); });
    this.bats = []; for (let i = 0; i < 7; i++) { const b = new THREE.Sprite(new THREE.SpriteMaterial({ map: batTex, transparent: true, depthWrite: false })); b.scale.set(1.0, 0.5, 1); b.visible = false; sc.add(b); this.bats.push(b); }
    // exit door at the end of the route
    const [ex, ez] = this.route[this.route.length - 1]; this.exitCell = [ex, ez];
    const ec = this.center(ex, ez);
    const door = new THREE.Group(); const dm = new THREE.Mesh(new THREE.BoxGeometry(1.6, 3, 0.12), new THREE.MeshStandardMaterial({ color: 0x5a3b1e })); dm.position.set(0.8, 1.5, 0); door.add(dm);
    const knob = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 5), new THREE.MeshStandardMaterial({ color: 0xffd11a })); knob.position.set(1.4, 1.5, 0.1); door.add(knob);
    door.position.set(ec.x + C / 2 - 0.1, 0, ec.z - 0.8); door.rotation.y = Math.PI / 2; sc.add(door); this.door = door;
    const glow = new THREE.PointLight(0xfff0c0, 0, 8, 2); glow.position.set(ec.x + 1.5, 2, ec.z); sc.add(glow); this.exitGlow = glow;
    const exitSign = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.5), new THREE.MeshBasicMaterial({ map: textTexture('EXIT', { bg: '#3cff7a', color: '#052', size: 80, w: 256, h: 80 }) })); exitSign.position.set(ec.x + C / 2 - 0.08, 3.4, ec.z); exitSign.rotation.y = -Math.PI / 2; sc.add(exitSign);
    // scares: [cell, handler]
    this.scares = [
      { cell: [0, 2], fn: () => this.scarePortrait(0) },
      { cell: [2, 1], fn: () => this.scareGhost() },
      { cell: [4, 1], fn: () => this.scareFlicker() },
      { cell: [4, 3], fn: () => this.scareSpider() },
      { cell: [2, 3], fn: () => this.scareSkeleton() },
      { cell: [0, 4], fn: () => this.scarePortrait(4) },
      { cell: [3, 5], fn: () => this.scareBoo() },
      { cell: [6, 5], fn: () => this.reachExit() },
    ];
  },

  // ---- enter / exit ----
  enter(b) {
    this.build(); this.building = b; this.active = true; this.t = 0; this.anims = []; this.shake = 0;
    for (const s of this.scares) s.fired = false;
    this.savedPos = Walk.pos.clone(); this.savedYaw = Walk.yaw;
    const c = this.center(0, 0); Walk.pos.set(c.x, 0, c.z - 1.2); Walk.yaw = Math.PI; Walk.pitch = 0; // route heads +z; yaw=PI looks toward +z
    Walk.speed = 4.2;
    document.getElementById('flash').classList.remove('on');
    toast('🏚️ Ooooh… it\'s dark in here. Find the EXIT! 👻', 3000);
    Audio_.creak(); renderContext();
  },
  exit(finished) {
    if (!this.active) return; this.active = false; Walk.speed = 7;
    if (this.savedPos) { const d = this.building ? this.building.door : this.savedPos; Walk.pos.set(d.x, 0, d.z + 1.5); Walk.yaw = 0; Walk.pitch = -0.05; }
    for (const g of [this.ghost, this.bigGhost, this.skeleton, this.spider]) g.visible = false; for (const b of this.bats) b.visible = false;
    if (finished) { toast('🏆 You made it out of the Spooky House! Brave!', 3500, 'gold'); Audio_.fanfare(); Particles.confetti(Walk.pos.clone().setY(3)); if (this.building) { this.building.visitors++; G.stats.spookySurvived = (G.stats.spookySurvived || 0) + 1; } }
    renderContext();
  },
  /** keep the player inside the hallway cells */
  collide(prev) {
    const p = Walk.pos, r = 0.45, C = this.C;
    const inside = (x, z) => this.cells.has(this.key(Math.floor(x / C), Math.floor(z / C)));
    const okAt = (x, z) => inside(x - r, z - r) && inside(x + r, z - r) && inside(x - r, z + r) && inside(x + r, z + r);
    if (!okAt(p.x, p.z)) { if (okAt(p.x, prev.z)) p.z = prev.z; else if (okAt(prev.x, p.z)) p.x = prev.x; else { p.x = prev.x; p.z = prev.z; } }
  },
  update(dt) {
    if (!this.active) return; this.t += dt;
    const C = this.C; const cx = Math.floor(Walk.pos.x / C), cz = Math.floor(Walk.pos.z / C);
    for (const s of this.scares) if (!s.fired && s.cell[0] === cx && s.cell[1] === cz) { s.fired = true; s.fn(); }
    for (let i = this.anims.length - 1; i >= 0; i--) { const a = this.anims[i]; a.t += dt; const u = Math.min(1, a.t / a.dur); a.fn(u, a.t); if (u >= 1) { if (a.done) a.done(); this.anims.splice(i, 1); } }
    if (this.flicker > 0) { this.flicker -= dt; for (const l of this.lights) l.intensity = Math.random() < 0.5 ? 0.1 : 2.5; if (this.flicker <= 0) for (const l of this.lights) l.intensity = 3.2; }
    else for (const l of this.lights) l.intensity = 3.2 + Math.sin(this.t * 7 + l.position.x) * 0.25;
    if (this.shake > 0) { this.shake -= dt; World.camera.position.x += (Math.random() - 0.5) * 0.12; World.camera.position.y += (Math.random() - 0.5) * 0.12; }
  },
  inFront(dist, h) { const f = Walk.forward(); return new THREE.Vector3(Walk.pos.x + f.x * dist, h, Walk.pos.z + f.z * dist); },
  flash(ms = 160) { const el = document.getElementById('flash'); el.classList.add('on'); setTimeout(() => el.classList.remove('on'), ms); },
  addLight(pos, color, dur) { const l = new THREE.PointLight(color, 5, 10, 2); l.position.copy(pos); this.scene.add(l); this.anims.push({ t: 0, dur, fn: u => { l.intensity = 5 * (1 - u); }, done: () => this.scene.remove(l) }); },

  // ---- the scares ----
  scarePortrait(i) {
    const g = this.portraits[i]; if (!g) return; const eyes = g.userData.eyes;
    Audio_.creak(); eyes.children.forEach(e => e.visible = true);
    this.anims.push({ t: 0, dur: 2.5, fn: (u, t) => { g.rotation.z = Math.sin(t * 6) * 0.25 * (1 - u); eyes.children.forEach(e => e.scale.setScalar(1 + Math.sin(t * 20) * 0.4)); }, done: () => { g.rotation.z = 0; eyes.children.forEach(e => e.visible = false); } });
  },
  scareGhost() {
    const g = this.ghost; g.visible = true; const start = this.inFront(5, 1.6); const end = this.inFront(1.6, 1.5);
    g.position.copy(start); Audio_.scream(); this.flash(); this.shake = 0.5; this.addLight(end, 0x99aaff, 0.6);
    this.anims.push({ t: 0, dur: 2.2, fn: (u, t) => { const k = Math.min(1, u * 3); g.position.lerpVectors(start, end, k); g.position.y = 1.5 + Math.sin(t * 8) * 0.15 + (u > 0.7 ? (u - 0.7) * 8 : 0); g.lookAt(Walk.pos.x, 1.5, Walk.pos.z); g.rotation.z = Math.sin(t * 10) * 0.2; this.ghostMat.opacity = u > 0.75 ? (1 - u) * 4 * 0.92 : 0.92; }, done: () => { g.visible = false; this.ghostMat.opacity = 0.92; } });
  },
  scareFlicker() {
    this.flicker = 1.6; Audio_.creak(); Audio_.bats();
    const f = Walk.forward(), r = Walk.right();
    this.bats.forEach((b, i) => { b.visible = true; const off = (i - 3) * 0.5; this.anims.push({ t: 0, dur: 2.2, fn: (u, t) => { const s = -6 + u * 12; b.position.set(Walk.pos.x + f.x * (2.5 + off) + r.x * s, 2.2 + Math.sin(t * 9 + i) * 0.4 + i * 0.12, Walk.pos.z + f.z * (2.5 + off) + r.z * s); b.scale.set(1.0, 0.25 + Math.abs(Math.sin(t * 18 + i)) * 0.35, 1); }, done: () => b.visible = false }); });
  },
  scareSpider() {
    const sp = this.spider; sp.visible = true; const p = this.inFront(1.5, 4); sp.position.copy(p); Audio_.creak();
    this.anims.push({ t: 0, dur: 3.2, fn: (u, t) => { const drop = u < 0.25 ? u / 0.25 : 1; const y = 4 - drop * 2.7 + (u > 0.25 ? Math.sin(t * 5) * 0.15 : 0); sp.position.set(p.x, u > 0.8 ? y + (u - 0.8) * 20 : y, p.z); sp.lookAt(Walk.pos.x, sp.position.y, Walk.pos.z); sp.rotation.y += Math.PI; if (u > 0.24 && u < 0.27) { Audio_.scream(); this.flash(120); this.shake = 0.35; } }, done: () => sp.visible = false });
  },
  scareSkeleton() {
    const sk = this.skeleton; sk.visible = true; const p = this.inFront(1.8, 0); sk.position.set(p.x, 4.5, p.z); sk.lookAt(Walk.pos.x, 0, Walk.pos.z); Audio_.bones(); this.addLight(this.inFront(1.5, 2), 0x66ff88, 0.8);
    this.anims.push({ t: 0, dur: 2.6, fn: (u, t) => { const fall = Math.min(1, u * 4); sk.position.y = 4.5 - fall * 4.5 + (fall >= 1 ? Math.abs(Math.sin(t * 12)) * 0.15 * (1 - u) : 0); sk.rotation.z = Math.sin(t * 14) * 0.15 * (1 - u); if (u > 0.24 && u < 0.27) { Audio_.scream(); this.flash(120); this.shake = 0.4; } if (u > 0.8) sk.position.y -= (u - 0.8) * 30 * (1 / 60); }, done: () => sk.visible = false });
  },
  scareBoo() {
    const g = this.bigGhost; g.visible = true; const start = this.inFront(9, 1.7); const end = this.inFront(1.1, 1.6); g.position.copy(start);
    this.flicker = 0.8; Audio_.boo(); this.addLight(end, 0xff3060, 1.2);
    this.anims.push({ t: 0, dur: 2.0, fn: (u, t) => { const k = Math.min(1, u * 1.8); g.position.lerpVectors(start, end, k * k); g.position.y = 1.6 + Math.sin(t * 6) * 0.1; g.lookAt(Walk.pos.x, 1.6, Walk.pos.z); const s = 1 + (u > 0.55 ? (u - 0.55) * 1.5 : 0); g.scale.setScalar(s); if (u > 0.5 && u < 0.53) { Audio_.scream(); this.flash(220); this.shake = 0.7; toast('👻 BOO!!!', 900); } this.ghostMat.opacity = u > 0.8 ? (1 - u) * 5 * 0.92 : 0.92; }, done: () => { g.visible = false; g.scale.setScalar(1); this.ghostMat.opacity = 0.92; this.exitGlow.intensity = 3; this.anims.push({ t: 0, dur: 1.0, fn: u => { this.door.rotation.y = Math.PI / 2 + u * 1.6; } }); } });
  },
  reachExit() { setTimeout(() => this.exit(true), 200); },
};
